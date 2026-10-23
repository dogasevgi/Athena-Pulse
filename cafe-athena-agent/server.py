"""Customer-facing web server for the AI Search Optimization agent.

A restaurant owner fills in a form; the server runs the agent in a private per-customer
folder (jobs/<id>/) and serves the finished report at an unguessable link.

    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=...        # plus any of OPENAI/GEMINI/PERPLEXITY keys
    gunicorn -w 1 --threads 8 -b 0.0.0.0:8000 server:app      # production
    DEMO_MODE=1 python3 server.py                              # local, fake data, no keys

Run ONE gunicorn worker (threads are fine): the job queue and rate limits live in memory.
"""
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory

from safeurl import UnsafeURL, check_public_url

ROOT = Path(__file__).parent
JOBS = Path(os.getenv("JOBS_DIR") or ROOT / "jobs")
JOBS.mkdir(parents=True, exist_ok=True)

DEMO = os.getenv("DEMO_MODE") == "1"                       # fake data, no API keys
KEY_VARS = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "PERPLEXITY_API_KEY"]
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT_JOBS", "2"))
DAILY_LIMIT = int(os.getenv("MAX_JOBS_PER_DAY", "50"))      # all customers, protects your API bill
PER_IP_DAILY = int(os.getenv("MAX_JOBS_PER_IP_PER_DAY", "3"))
QUERIES_PER_JOB = int(os.getenv("QUERIES_PER_JOB", "16"))   # diner questions per customer
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "30"))
ACCESS_CODE = os.getenv("ACCESS_CODE", "")                  # optional: require a code on the form
TRUST_PROXY = os.getenv("TRUST_PROXY") == "1"               # behind Render/Fly/nginx: use X-Forwarded-For
STAGE_TIMEOUT = int(os.getenv("STAGE_TIMEOUT", "900"))
SALT = os.getenv("IP_SALT", "change-me")

STAGES = [
    ("queries.py", [], "Preparing the questions diners ask"),
    ("discover.py", ["--label", "baseline"], "Asking AI assistants"),
    ("analyze.py", ["--label", "baseline"], "Scoring your visibility"),
    ("audit.py", ["--label", "baseline"], "Checking your website and the sources AI cites"),
    ("compare.py", ["--label", "baseline"], "Comparing you with each leading rival"),
    ("diagnose.py", ["--label", "baseline"], "Working out why competitors win"),
    ("generate.py", ["--label", "baseline"], "Writing your fixes"),
    ("report.py", ["--label", "baseline"], "Building your report"),
]
ID_RE = re.compile(r"^[a-f0-9]{32}$")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024
pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT)
_lock = threading.Lock()


# ----------------------------------------------------------------- job storage
def job_dir(jid):
    return JOBS / jid


def read_job(jid):
    try:
        return json.loads((job_dir(jid) / "job.json").read_text(encoding="utf-8"))
    except Exception:
        return None


def write_job(jid, **changes):
    with _lock:
        job = read_job(jid) or {}
        job.update(changes)
        tmp = job_dir(jid) / "job.json.tmp"
        tmp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        tmp.replace(job_dir(jid) / "job.json")


def all_jobs():
    for d in JOBS.iterdir():
        if d.is_dir() and ID_RE.match(d.name):
            j = read_job(d.name)
            if j:
                yield j


def jobs_today(ip_hash=None):
    cutoff = time.time() - 86400
    return sum(1 for j in all_jobs() if j.get("created", 0) > cutoff
               and (ip_hash is None or j.get("ip") == ip_hash))


def startup_cleanup():
    for j in all_jobs():
        if j.get("state") in ("queued", "running"):
            write_job(j["id"], state="failed",
                      error="The server restarted while your report was being built. Please submit again.")
    cutoff = time.time() - RETENTION_DAYS * 86400
    for j in list(all_jobs()):
        if j.get("created", 0) < cutoff:
            shutil.rmtree(job_dir(j["id"]), ignore_errors=True)


# ------------------------------------------------------------------ validation
def clean(s, n):
    s = unicodedata.normalize("NFC", str(s or ""))
    s = "".join(c for c in s if c == "\n" or unicodedata.category(c)[0] != "C")
    return s.strip()[:n]


def fold(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def build_target(f):
    """Validate the form and return (target dict, error). Only facts the customer gave are used."""
    name = clean(f.get("name"), 80)
    website = clean(f.get("website"), 200)
    city = clean(f.get("city"), 60)
    region = clean(f.get("region"), 40)
    hood = clean(f.get("neighborhood"), 60)
    street = clean(f.get("street"), 100)
    cuisine = [c.strip() for c in clean(f.get("cuisine"), 100).split(",") if c.strip()][:4]
    highlights = [h.strip()[:200] for h in clean(f.get("highlights"), 1800).splitlines() if h.strip()][:8]

    if len(name) < 2:
        return None, "Enter the restaurant's name."
    if not city:
        return None, "Enter the city."
    if not cuisine:
        return None, "Enter at least one cuisine, for example “Italian”."
    if not website:
        return None, "Enter your website address."
    if not re.match(r"^https?://", website, re.I):
        website = "https://" + website
    try:
        check_public_url(website)
    except UnsafeURL as e:
        return None, str(e)

    domain = website.split("//", 1)[-1].split("/")[0].lower().removeprefix("www.")
    aliases = {name.lower(), fold(name), fold(name).replace("'", "")}
    aliases |= {a.removeprefix("the ") for a in set(aliases)}
    return {
        "name": name, "aliases": sorted(a for a in aliases if a), "website": website, "domain": domain,
        "street": street or None, "city": city, "region": region or None, "postal": None,
        "neighborhood": hood or None, "cuisine": cuisine, "founded": None, "hours": [],
        "highlights": highlights,
    }, None


def client_ip():
    if TRUST_PROXY and request.headers.get("X-Forwarded-For"):
        return request.headers["X-Forwarded-For"].split(",")[0].strip()
    return request.remote_addr or "unknown"


# ------------------------------------------------------------------ the pipeline
def balanced_sample(queries, n):
    """Pick n queries spread evenly across intents (date night, events, catering, ...)."""
    by = {}
    for q in queries:
        by.setdefault(q["intent"], []).append(q)
    out, i = [], 0
    while len(out) < n and any(by.values()):
        for items in by.values():
            if i < len(items) and len(out) < n:
                out.append(items[i])
        i += 1
        if all(i >= len(v) for v in by.values()):
            break
    return out


def run_job(jid):
    home = job_dir(jid)
    env = {k: v for k, v in os.environ.items() if k not in ("ACCESS_CODE", "IP_SALT")}
    env.update(ATHENA_HOME=str(home), RUNS="1", WORKERS="4", PYTHONUNBUFFERED="1")
    if DEMO:
        env["MOCK"] = "1"
    log = (home / "job.log").open("a", encoding="utf-8")
    write_job(jid, state="running", started=time.time(), stage=0)
    try:
        for i, (script, args, label) in enumerate(STAGES):
            write_job(jid, stage=i, stage_label=label)
            r = subprocess.run([sys.executable, str(ROOT / script), *args], cwd=ROOT, env=env,
                               stdout=log, stderr=subprocess.STDOUT, timeout=STAGE_TIMEOUT)
            if r.returncode != 0:
                raise RuntimeError(f"{script} exited {r.returncode}")
            if script == "queries.py":
                qf = home / "data" / "queries.json"
                qs = json.loads(qf.read_text(encoding="utf-8"))
                qf.write_text(json.dumps(balanced_sample(qs, QUERIES_PER_JOB), ensure_ascii=False))
            if script == "discover.py":
                runs = home / "data" / "runs" / "baseline.jsonl"
                ok = [1 for line in runs.read_text(encoding="utf-8").splitlines()
                      if line.strip() and '"error"' not in line] if runs.exists() else []
                if not ok:
                    raise RuntimeError("no AI provider returned an answer")
        write_job(jid, state="done", finished=time.time(), stage=len(STAGES))
    except Exception as e:  # details go to job.log, not to the customer
        log.write(f"\nJOB FAILED: {e!r}\n")
        write_job(jid, state="failed", finished=time.time(),
                  error="Something went wrong while building your report. Please try again in a few minutes.")
    finally:
        log.close()


# ----------------------------------------------------------------------- routes
@app.after_request
def secure(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    if request.path.startswith(("/r/", "/j/", "/api/jobs/")):
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


@app.get("/")
def index():
    return Response(INDEX_HTML.replace("__NEEDS_CODE__", "1" if ACCESS_CODE else ""), mimetype="text/html")


@app.get("/healthz")
def healthz():
    keys = [k for k in KEY_VARS if os.getenv(k)]
    return jsonify(ok=True, demo=DEMO, providers=len(keys), ready=DEMO or bool(keys))


@app.post("/api/jobs")
def create_job():
    f = request.get_json(silent=True) or request.form
    if f.get("company_url"):                       # honeypot: bots fill hidden fields
        return jsonify(id="0" * 32, url="/"), 200
    if ACCESS_CODE and not hmac.compare_digest(str(f.get("code") or ""), ACCESS_CODE):
        return jsonify(error="That access code isn't right."), 403
    if not DEMO and not any(os.getenv(k) for k in KEY_VARS):
        return jsonify(error="This service isn't set up yet. Please try again later."), 503
    target, err = build_target(f)
    if err:
        return jsonify(error=err), 400
    ip_hash = hashlib.sha256((SALT + client_ip()).encode()).hexdigest()[:16]
    with _lock:
        if jobs_today() >= DAILY_LIMIT:
            return jsonify(error="We're at capacity today. Please come back tomorrow."), 429
        if jobs_today(ip_hash) >= PER_IP_DAILY:
            return jsonify(error=f"Limit of {PER_IP_DAILY} reports per day reached. Please try again tomorrow."), 429
        jid = secrets.token_hex(16)
        (job_dir(jid) / "data").mkdir(parents=True)
        (job_dir(jid) / "data" / "target.json").write_text(json.dumps(target, ensure_ascii=False, indent=2))
        (job_dir(jid) / "job.json").write_text(json.dumps({
            "id": jid, "state": "queued", "name": target["name"], "created": time.time(), "ip": ip_hash,
            "stage": 0, "stage_label": "Waiting in line", "total": len(STAGES)}))
    pool.submit(run_job, jid)
    return jsonify(id=jid, url=f"/j/{jid}"), 202


@app.get("/api/jobs/<jid>")
def job_status(jid):
    j = read_job(jid) if ID_RE.match(jid) else None
    if not j:
        abort(404)
    return jsonify({k: j.get(k) for k in ("state", "name", "stage", "stage_label", "total", "error")})


@app.get("/j/<jid>")
def job_page(jid):
    if not ID_RE.match(jid) or not read_job(jid):
        abort(404)
    return Response(STATUS_HTML, mimetype="text/html")


REPORT_CSP = ("default-src 'none'; style-src 'unsafe-inline' https://fonts.googleapis.com; "
              "font-src https://fonts.gstatic.com; img-src data:; base-uri 'none'; form-action 'none'")


def _report_dir(jid):
    j = read_job(jid) if ID_RE.match(jid) else None
    if not j or j.get("state") != "done":
        abort(404)
    return job_dir(jid) / "artifacts"


@app.get("/r/<jid>/")
def report(jid):
    return report_file(jid, "report.html")


@app.get("/r/<jid>/<path:p>")
def report_file(jid, p):
    d = _report_dir(jid)
    if p == "download.zip":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(d.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(d).as_posix())
        buf.seek(0)
        return send_file(buf, mimetype="application/zip", as_attachment=True, download_name="ai-search-fixes.zip")
    resp = send_from_directory(d, p)
    resp.headers["Content-Security-Policy"] = REPORT_CSP
    if not p.endswith(".html"):                # show fix files as text instead of running them
        resp.headers["Content-Type"] = "text/plain; charset=utf-8"
    return resp


# ------------------------------------------------------------------------ pages
INDEX_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Is your restaurant showing up in AI search?</title>
<style>
:root{--bg:#f7f4ee;--ink:#1d2a33;--mut:#5b6b75;--card:#fff;--line:#e2dccf;--acc:#1f5f8b}
@media(prefers-color-scheme:dark){:root{--bg:#0e1a24;--ink:#e7edf0;--mut:#9fb0ba;--card:#142533;--line:#26394a;--acc:#6fb3de}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.55 Georgia,'Times New Roman',serif}
main{max-width:640px;margin:0 auto;padding:40px 20px 80px}h1{font-size:2rem;line-height:1.15;margin:0 0 .4em}
p.lead{color:var(--mut);margin:0 0 1.6em}form{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:22px}
label{display:block;font:600 .88rem system-ui,sans-serif;margin:14px 0 4px}small{color:var(--mut);font:400 .8rem system-ui,sans-serif}
input,textarea{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);font:1rem system-ui,sans-serif}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:520px){.row{grid-template-columns:1fr}}
button{margin-top:20px;width:100%;padding:13px;border:0;border-radius:10px;background:var(--acc);color:#fff;font:600 1rem system-ui,sans-serif;cursor:pointer}
button:disabled{opacity:.6}#err{color:#b3261e;font:500 .9rem system-ui,sans-serif;margin-top:12px;min-height:1.2em}
.hp{position:absolute;left:-9999px}ul{color:var(--mut);padding-left:1.2em}
</style></head><body><main>
<h1>Is your restaurant showing up in AI search?</h1>
<p class="lead">When diners ask ChatGPT, Gemini, Claude or Perplexity where to eat, does your name come up? Tell us about your restaurant and get a free report: where you rank, who beats you, and what to fix.</p>
<form id="f" novalidate>
<label for="name">Restaurant name *</label><input id="name" name="name" required maxlength="80" autocomplete="organization">
<label for="website">Website *</label><input id="website" name="website" required placeholder="yourrestaurant.com" inputmode="url">
<div class="row"><div><label for="city">City *</label><input id="city" name="city" required maxlength="60"></div>
<div><label for="region">State / region</label><input id="region" name="region" maxlength="40"></div></div>
<div class="row"><div><label for="neighborhood">Neighborhood</label><input id="neighborhood" name="neighborhood" maxlength="60"></div>
<div><label for="street">Street address</label><input id="street" name="street" maxlength="100"></div></div>
<label for="cuisine">Cuisine *</label><input id="cuisine" name="cuisine" required placeholder="Greek, Mediterranean" maxlength="100">
<label for="highlights">What makes you special? <small>(one fact per line, only true ones; we won't invent anything)</small></label>
<textarea id="highlights" name="highlights" rows="4" placeholder="Open since 1990&#10;Private room for 30&#10;Daily happy hour 3-6 PM"></textarea>
<div id="codebox" hidden><label for="code">Access code</label><input id="code" name="code" autocomplete="off"></div>
<input class="hp" name="company_url" tabindex="-1" autocomplete="off" aria-hidden="true">
<button id="go">Check my AI visibility</button><div id="err" role="alert"></div>
</form>
<p style="margin-top:28px"><small>The report takes about 5 to 10 minutes. We ask several AI assistants the questions real diners ask, then read your website and the pages they cite. Results are private to whoever has your link.</small></p>
</main><script>
if("__NEEDS_CODE__")document.getElementById("codebox").hidden=false;
const f=document.getElementById("f"),err=document.getElementById("err"),go=document.getElementById("go");
f.addEventListener("submit",async e=>{e.preventDefault();err.textContent="";go.disabled=true;go.textContent="Starting...";
try{const r=await fetch("/api/jobs",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(Object.fromEntries(new FormData(f)))});
const d=await r.json();if(!r.ok)throw new Error(d.error||"Something went wrong.");location.href=d.url}
catch(x){err.textContent=x.message;go.disabled=false;go.textContent="Check my AI visibility"}});
</script></body></html>"""

STATUS_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Building your report...</title>
<style>:root{--bg:#f7f4ee;--ink:#1d2a33;--mut:#5b6b75;--line:#e2dccf;--acc:#1f5f8b}
@media(prefers-color-scheme:dark){:root{--bg:#0e1a24;--ink:#e7edf0;--mut:#9fb0ba;--line:#26394a;--acc:#6fb3de}}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.55 Georgia,serif}main{max-width:560px;margin:0 auto;padding:60px 20px}
h1{font-size:1.7rem;margin:0 0 .3em}.bar{height:8px;background:var(--line);border-radius:8px;overflow:hidden;margin:22px 0 10px}
.bar>div{height:100%;width:4%;background:var(--acc);transition:width .6s}p{color:var(--mut)}a{color:var(--acc)}</style></head>
<body><main><h1 id="t">Building your report</h1><p id="s">Starting...</p>
<div class="bar"><div id="b"></div></div>
<p><small>Keep this tab open, or bookmark this page and come back. This link is private: anyone who has it can see your report.</small></p></main>
<script>
const id=location.pathname.split("/").pop(),$=x=>document.getElementById(x);
async function tick(){try{const j=await (await fetch("/api/jobs/"+id)).json();
if(j.state==="done"){location.replace("/r/"+id+"/");return}
if(j.state==="failed"){$("t").textContent="We couldn't finish your report";$("s").textContent=j.error||"Please try again.";
$("s").insertAdjacentHTML("beforeend",' <a href="/">Start over</a>');$("b").style.background="#b3261e";return}
$("t").textContent="Building the report for "+(j.name||"your restaurant");
$("s").textContent=(j.stage_label||"Working")+"...";$("b").style.width=Math.max(4,Math.round(100*(j.stage||0)/(j.total||7)))+"%"}catch(e){}
setTimeout(tick,3000)}tick();
</script></body></html>"""

startup_cleanup()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8000")))
