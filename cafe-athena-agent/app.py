"""No-code control panel for the AI search agent.

Double-click "Start Agent.command" (or run `python3 app.py`). A page opens in
your browser; everything runs on this computer. API keys you type stay in
memory only and are forgotten when you close the Terminal window.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).parent
DATA, OUT, ANSWERS = ROOT / "data", ROOT / "artifacts", ROOT / "answers"
for d in (DATA, OUT, ANSWERS):
    d.mkdir(exist_ok=True)
LOG = DATA / "job.log"
KEY_NAMES = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
             "gemini": "GEMINI_API_KEY", "perplexity": "PERPLEXITY_API_KEY",
             "github_token": "GITHUB_TOKEN", "github_repo": "GITHUB_REPO"}
KEYS = {}            # in memory only
JOB = {"proc": None, "kind": None, "started": None}
STAGE_ORDER = ["DISCOVERY", "ANALYSIS   - scoring", "ANALYSIS   - auditing", "ANALYSIS   - explaining",
               "ACTION     - writing", "MEASUREMENT - before", "MEASUREMENT - building"]
STAGE_LABELS = ["Ask the AI assistants", "Score visibility", "Check website & sources",
                "Explain the gaps", "Write the fixes", "Before/after test", "Build the report"]
DEFAULT = {"name": "Café Athena", "website": "https://cafeathena.com/",
           "location": "Pacific Beach, San Diego, CA", "street": "1846 Garnet Ave",
           "cuisine": "Greek, Mediterranean"}


def read_json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def target_view():
    t = read_json(DATA / "target.json") or {}
    if not t.get("name"):  # Café Athena (optionally with edited facts)
        sys.path.insert(0, str(ROOT))
        from config import DEFAULT_TARGET
        return {**DEFAULT, "highlights": t.get("highlights") or DEFAULT_TARGET["highlights"],
                "is_default": True}
    return {"name": t.get("name"), "website": t.get("website") or "", "street": t.get("street") or "",
            "location": t.get("location") or ", ".join(x for x in (t.get("neighborhood"), t.get("city"),
                                                                   t.get("region")) if x),
            "cuisine": ", ".join(t.get("cuisine") or []), "highlights": t.get("highlights") or [],
            "is_default": False}


def clear_results():
    shutil.rmtree(DATA / "runs", ignore_errors=True)
    for p in DATA.glob("*"):
        if p.is_file() and p.name != "target.json":
            p.unlink()
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(exist_ok=True)


def save_target(body):
    name = (body.get("name") or "").strip()
    old = target_view()["name"]
    highlights = [h.strip() for h in (body.get("highlights") or "").splitlines() if h.strip()]
    if not name or name == DEFAULT["name"]:
        # Café Athena keeps its verified hours and address from config.py.
        tj = {"highlights": highlights} if highlights else None
        if tj:
            (DATA / "target.json").write_text(json.dumps(tj, indent=2, ensure_ascii=False))
        else:
            (DATA / "target.json").unlink(missing_ok=True)
        new_name = DEFAULT["name"]
    else:
        parts = [p.strip() for p in (body.get("location") or "").split(",") if p.strip()]
        website = (body.get("website") or "").strip()
        tj = {"name": name, "aliases": [name.lower()], "website": website or None,
              "domain": website.split("//")[-1].split("/")[0].replace("www.", "") or None,
              "street": (body.get("street") or "").strip() or None,
              "neighborhood": parts[0] if len(parts) >= 2 else None,
              "city": parts[1] if len(parts) >= 2 else (parts[0] if parts else None),
              "region": parts[2] if len(parts) >= 3 else None, "postal": None,
              "location": body.get("location") or "",
              "cuisine": [c.strip() for c in (body.get("cuisine") or "").split(",") if c.strip()],
              "founded": None, "hours": [], "highlights": highlights}
        (DATA / "target.json").write_text(json.dumps(tj, indent=2, ensure_ascii=False))
        new_name = name
    if new_name != old:
        clear_results()
    (DATA / "queries.json").unlink(missing_ok=True)


def csv_files():
    out = []
    for p in sorted(ANSWERS.rglob("*.csv")):
        try:
            import csv
            with p.open(encoding="utf-8-sig", newline="") as f:
                rows = sum(1 for r in csv.DictReader(f) if (r.get("answer") or "").strip())
        except Exception:
            rows = 0
        out.append({"path": p.relative_to(ROOT).as_posix(), "name": p.name, "answers": rows})
    return out


def job_state():
    proc = JOB["proc"]
    running = bool(proc and proc.poll() is None)
    text = LOG.read_text(encoding="utf-8", errors="replace") if LOG.exists() else ""
    seen = [i for i, key in enumerate(STAGE_ORDER) if f"=== {key}" in text]
    return {"running": running, "kind": JOB["kind"],
            "exit": None if running or not proc else proc.returncode,
            "elapsed": int(time.time() - JOB["started"]) if JOB["started"] else 0,
            "stages": STAGE_LABELS, "reached": max(seen) if seen else -1,
            "skipped": [5] if "Skipping the simulated" in text else [],
            "log": "\n".join(l for l in text.splitlines() if "warnings.warn" not in l
                             and "NotOpenSSLWarning" not in l and "urllib3" not in l)[-6000:]}


def outreach():
    log = read_json(DATA / "actions_log.json", [])
    status = {e["detail"]: e["status"] for e in log if e["action"] == "outreach_email"}
    d = OUT / "outreach"
    return [{"name": p.name, "text": p.read_text(encoding="utf-8"), "status": status.get(p.name)}
            for p in sorted(d.glob("*.txt"))] if d.exists() else []


def state():
    files = sorted(p.relative_to(OUT).as_posix() for p in OUT.rglob("*")
                   if p.is_file() and p.name != "report.html")
    card = read_json(DATA / "scorecard_baseline.json") or read_json(DATA / "scorecard_demo.json")
    return {"target": target_view(),
            "keys": {k: bool(KEYS.get(v) or os.getenv(v)) for k, v in KEY_NAMES.items()},
            "job": job_state(), "csvs": csv_files(), "files": files, "outreach": outreach(),
            "summary": read_json(DATA / "summary.json"),
            "has_report": (OUT / "report.html").exists(),
            "demo": bool((read_json(DATA / "site_audit.json") or {}).get("mock")),
            "overall": (card or {}).get("overall"),
            "actions": read_json(DATA / "actions_log.json", [])[-8:]}


def start_job(kind, body):
    if JOB["proc"] and JOB["proc"].poll() is None:
        return "A run is already in progress."
    mode = body.get("mode")
    cmd = [sys.executable, str(ROOT / "agent.py")]
    if kind == "measure":
        cmd.append("measure")
    if mode == "demo":
        cmd.append("--demo")
    elif mode == "manual":
        files = [f for f in body.get("files", []) if (ROOT / f).is_file()]
        if not files:
            return "Pick at least one answers file."
        cmd += ["--manual", *files]
    elif mode == "live":
        if not any(KEYS.get(KEY_NAMES[k]) or os.getenv(KEY_NAMES[k])
                   for k in ("anthropic", "openai", "gemini", "perplexity")):
            return "Add at least one AI key first."
        if body.get("quick"):
            cmd.append("--quick")
    else:
        return "Choose where the answers come from."
    cmd.append("--no-open")
    env = {**os.environ, **KEYS, "PYTHONWARNINGS": "ignore", "PYTHONUNBUFFERED": "1"}
    if kind == "run":
        (DATA / "summary.json").unlink(missing_ok=True)
    f = LOG.open("w", encoding="utf-8")
    JOB.update(proc=subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT),
               kind=kind, started=time.time())
    return None


def log_action(action, status, detail=""):
    entries = read_json(DATA / "actions_log.json", [])
    entries.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "action": action, "status": status,
                    "detail": detail})
    (DATA / "actions_log.json").write_text(json.dumps(entries, indent=2))


def open_pr():
    env = {**os.environ, **KEYS}
    if not (env.get("GITHUB_TOKEN") and env.get("GITHUB_REPO")):
        return {"error": "Add a GitHub token and repository first."}
    code = "import act, json; print(json.dumps({'url': act.open_pr(act.site_files())}))"
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        log_action("github_pr", "failed", r.stderr[-300:])
        return {"error": "GitHub refused the request: " + r.stderr.strip().splitlines()[-1][:200]}
    url = json.loads(r.stdout.strip().splitlines()[-1])["url"]
    log_action("github_pr", "opened", url)
    return {"url": url}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else (
            json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def serve_file(self, path):
        types = {".html": "text/html; charset=utf-8", ".md": "text/plain; charset=utf-8",
                 ".txt": "text/plain; charset=utf-8", ".jsonld": "application/json; charset=utf-8",
                 ".json": "application/json; charset=utf-8", ".csv": "text/csv; charset=utf-8"}
        if not path.is_file():
            return self.send(404, "Not found", "text/plain")
        self.send(200, path.read_bytes(), types.get(path.suffix, "application/octet-stream"))

    def do_GET(self):
        p = unquote(urlparse(self.path).path)
        if p == "/":
            return self.send(200, PAGE, "text/html; charset=utf-8")
        if p == "/api/state":
            return self.send(200, state())
        if p == "/report":
            return self.serve_file(OUT / "report.html")
        if p == "/template.csv":
            return self.serve_file(ANSWERS / "template.csv")
        if p.startswith("/artifacts/"):
            target = (OUT / p[len("/artifacts/"):]).resolve()
            if OUT.resolve() in target.parents:
                return self.serve_file(target)
        self.send(404, "Not found", "text/plain")

    def do_POST(self):
        p = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self.send(400, {"error": "Bad request"})
        if p == "/api/target":
            if JOB["proc"] and JOB["proc"].poll() is None:
                return self.send(409, {"error": "Wait for the current run to finish."})
            save_target(body)
            return self.send(200, {"ok": True})
        if p == "/api/keys":
            for k, v in body.items():
                if k in KEY_NAMES:
                    if v:
                        KEYS[KEY_NAMES[k]] = v.strip()
                    else:
                        KEYS.pop(KEY_NAMES[k], None)
            return self.send(200, {"ok": True})
        if p == "/api/upload":
            name = re.sub(r"[^A-Za-z0-9._-]+", "_", body.get("name") or "answers.csv")
            if not name.lower().endswith(".csv"):
                name += ".csv"
            (ANSWERS / "uploads").mkdir(exist_ok=True)
            (ANSWERS / "uploads" / name).write_text(body.get("text") or "", encoding="utf-8")
            return self.send(200, {"ok": True, "path": f"answers/uploads/{name}"})
        if p in ("/api/run", "/api/measure"):
            err = start_job("run" if p == "/api/run" else "measure", body)
            return self.send(400 if err else 200, {"error": err} if err else {"ok": True})
        if p == "/api/stop":
            if JOB["proc"] and JOB["proc"].poll() is None:
                JOB["proc"].terminate()
            return self.send(200, {"ok": True})
        if p == "/api/approve":
            name = Path(body.get("name") or "").name
            src = OUT / "outreach" / name
            if not src.is_file():
                return self.send(404, {"error": "Draft not found"})
            if body.get("decision") == "approve":
                (OUT / "approved_outreach").mkdir(exist_ok=True)
                shutil.copy(src, OUT / "approved_outreach" / name)
                log_action("outreach_email", "approved", name)
            else:
                log_action("outreach_email", "declined", name)
            return self.send(200, {"ok": True})
        if p == "/api/pr":
            return self.send(200, open_pr())
        if p == "/api/reset":
            if JOB["proc"] and JOB["proc"].poll() is None:
                return self.send(409, {"error": "Wait for the current run to finish."})
            clear_results()
            return self.send(200, {"ok": True})
        self.send(404, {"error": "Unknown action"})


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Search Agent</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Alegreya:wght@400;700&family=Alegreya+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#F6F8F7;--surface:#FFFFFF;--ink:#17212B;--muted:#5F6B76;--line:#D6DEE2;--sea:#0F3D63;
--olive:#5B6B2C;--sun:#C98A1E;--miss:#A3412F;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#0E1A24;--surface:#142533;--ink:#E7EDF0;--muted:#9AA7B1;
--line:#25394A;--sea:#7DB8E6;--olive:#A9BC6E;--sun:#E8B65A;--miss:#E48B78;color-scheme:dark}}
*{box-sizing:border-box}
[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.55 "Alegreya Sans",system-ui,sans-serif}
main{max-width:820px;margin:0 auto;padding:40px 22px 90px}
header h1{font:700 2.3rem/1.15 "Alegreya",Georgia,serif;color:var(--sea);margin:0 0 6px}
header p{margin:0;color:var(--muted);max-width:60ch}
.step{display:grid;grid-template-columns:44px 1fr;gap:16px;padding:30px 0;border-top:1px solid var(--line)}
.step:first-of-type{border-top:0}
.num{font:700 1.6rem/1 "Alegreya",Georgia,serif;color:var(--sea);padding-top:4px}
h2{font:700 1.45rem/1.2 "Alegreya",Georgia,serif;margin:0 0 4px}
.hint{color:var(--muted);margin:0 0 14px;max-width:62ch}
label{display:block;font-weight:500;margin:12px 0 4px}
input[type=text],input[type=password],textarea{width:100%;padding:10px 12px;font:inherit;color:var(--ink);
background:var(--surface);border:1px solid var(--line);border-radius:6px}
textarea{min-height:110px;resize:vertical}
.row{display:grid;grid-template-columns:1fr 1fr;gap:0 16px}
@media (max-width:620px){.row{grid-template-columns:1fr}.step{grid-template-columns:1fr}.num{padding:0}}
button,.btn{font:500 1rem "Alegreya Sans",system-ui,sans-serif;padding:10px 18px;border-radius:6px;cursor:pointer;
border:1px solid var(--sea);background:var(--sea);color:var(--bg);text-decoration:none;display:inline-block}
button.ghost,.btn.ghost{background:transparent;color:var(--sea)}
button:disabled{opacity:.45;cursor:not-allowed}
button:focus-visible,input:focus-visible,textarea:focus-visible,.btn:focus-visible{outline:2px solid var(--sun);outline-offset:2px}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px;align-items:center}
.modes{display:grid;gap:10px}
.mode{display:grid;grid-template-columns:22px 1fr;gap:10px;padding:14px 16px;background:var(--surface);
border:1px solid var(--line);border-radius:6px;cursor:pointer}
.mode:has(input:checked){border-color:var(--sea);box-shadow:inset 3px 0 0 var(--sea)}
.mode b{display:block}.mode span{color:var(--muted)}
.sub{margin-top:12px;padding-left:32px}
.files label{font-weight:400;display:flex;gap:8px;align-items:center;margin:6px 0}
.muted{color:var(--muted)}
.stages{list-style:none;padding:0;margin:4px 0 12px}
.stages li{padding:5px 0 5px 28px;position:relative;color:var(--muted)}
.stages li::before{content:"";position:absolute;left:4px;top:12px;width:10px;height:10px;border-radius:50%;border:2px solid var(--line)}
.stages li.done{color:var(--ink)}.stages li.done::before{background:var(--olive);border-color:var(--olive)}
.stages li.skip{color:var(--muted);text-decoration:line-through}
.stages li.now{color:var(--sea);font-weight:700}.stages li.now::before{border-color:var(--sea);animation:pulse 1s infinite alternate}
@keyframes pulse{to{background:var(--sea)}}
@media (prefers-reduced-motion:reduce){.stages li.now::before{animation:none;background:var(--sea)}}
pre{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:12px;max-height:260px;overflow:auto;
font:13px/1.45 ui-monospace,Menlo,monospace;white-space:pre-wrap}
.figure{font:700 2.6rem/1 "Alegreya",Georgia,serif;color:var(--sea)}
.figs{display:flex;gap:32px;flex-wrap:wrap;margin:6px 0 16px}.figs div span{display:block;color:var(--muted)}
dl.five dt{font-weight:700;color:var(--sea);margin-top:12px}dl.five dd{margin:2px 0 0}
.note{padding:10px 14px;border-left:3px solid var(--sun);background:var(--surface);margin:10px 0}
.err{color:var(--miss);font-weight:500}
.draft{border:1px solid var(--line);border-radius:6px;background:var(--surface);margin:10px 0;padding:10px 14px}
.draft pre{border:0;padding:6px 0;background:none;max-height:none}
.tag{font-size:.85rem;padding:2px 8px;border-radius:10px;border:1px solid currentColor}
.ok{color:var(--olive)}.no{color:var(--miss)}
ul.files-list{padding-left:18px}ul.files-list a{color:var(--sea)}
details summary{cursor:pointer;color:var(--sea)}
</style></head><body><main>
<header><h1>AI search agent</h1>
<p>Find out how often ChatGPT, Claude, Gemini and Perplexity recommend a restaurant, why competitors win, and what to fix.</p></header>

<section class="step"><div class="num">1</div><div>
<h2>Restaurant</h2><p class="hint">Only facts you enter here go into generated content. Anything else is marked “VERIFY” for you to confirm.</p>
<div class="row"><div><label for="t-name">Name</label><input id="t-name" type="text"></div>
<div><label for="t-website">Website</label><input id="t-website" type="text" placeholder="https://"></div></div>
<div class="row"><div><label for="t-location">Neighborhood, city, state</label><input id="t-location" type="text" placeholder="Pacific Beach, San Diego, CA"></div>
<div><label for="t-cuisine">Cuisine</label><input id="t-cuisine" type="text" placeholder="Greek, Mediterranean"></div></div>
<label for="t-street">Street address</label><input id="t-street" type="text">
<label for="t-high">Verified facts, one per line</label><textarea id="t-high"></textarea>
<div class="actions"><button id="save-target">Save restaurant</button><span id="target-msg" class="muted"></span></div>
</div></section>

<section class="step"><div class="num">2</div><div>
<h2>Where the AI answers come from</h2><p class="hint">Pick one. The free option uses answers your team copied from the AI apps.</p>
<div class="modes">
<label class="mode"><input type="radio" name="mode" value="manual"><div><b>Answers we collected (free)</b>
<span>Use spreadsheets of answers pasted from the free ChatGPT, Gemini, Perplexity or Claude apps.</span></div></label>
<div class="sub" id="manual-box"><div class="files" id="files"></div>
<div class="actions"><label class="btn ghost" for="upload" style="margin:0">Add a spreadsheet (.csv)</label>
<input id="upload" type="file" accept=".csv,text/csv" hidden>
<a class="btn ghost" href="/template.csv" download="answers_template.csv">Download blank template</a></div></div>
<label class="mode"><input type="radio" name="mode" value="live"><div><b>Ask the AI assistants automatically</b>
<span>Needs at least one API key. Uses your API credit.</span></div></label>
<div class="sub" id="live-box">
<div class="row"><div><label for="k-anthropic">Claude key</label><input id="k-anthropic" type="password" autocomplete="off"></div>
<div><label for="k-openai">ChatGPT (OpenAI) key</label><input id="k-openai" type="password" autocomplete="off"></div></div>
<div class="row"><div><label for="k-gemini">Gemini key</label><input id="k-gemini" type="password" autocomplete="off"></div>
<div><label for="k-perplexity">Perplexity key</label><input id="k-perplexity" type="password" autocomplete="off"></div></div>
<p class="muted">Keys stay in this computer’s memory and are forgotten when you close the agent.</p>
<label style="font-weight:400;display:flex;gap:8px;align-items:center"><input type="checkbox" id="quick" checked> Quick run (8 questions, about 5 minutes)</label>
<div class="actions"><button class="ghost" id="save-keys">Save keys</button><span id="keys-msg" class="muted"></span></div></div>
<label class="mode"><input type="radio" name="mode" value="demo"><div><b>Practice run with fake data</b>
<span>Shows every step working, with placeholder restaurant names. Good for rehearsing.</span></div></label>
</div></div></section>

<section class="step"><div class="num">3</div><div>
<h2>Run the agent</h2><p class="hint">Takes a minute or two. Checking the website and cited pages is the slowest part.</p>
<ul class="stages" id="stages"></ul>
<div class="actions"><button id="run">Run the agent</button><button class="ghost" id="stop" hidden>Stop</button>
<span id="run-msg"></span></div>
<details id="log-box"><summary>Show details</summary><pre id="log"></pre></details>
</div></section>

<section class="step"><div class="num">4</div><div>
<h2>Results</h2><div id="results"><p class="muted">Run the agent to see results here.</p></div>
</div></section>

<section class="step"><div class="num">5</div><div>
<h2>Approve the fixes</h2><p class="hint">Nothing is sent or published until you approve it here.</p>
<div id="fixes"><p class="muted">Fixes appear here after a run.</p></div>
</div></section>

<section class="step"><div class="num">6</div><div>
<h2>Measure again later</h2><p class="hint">After publishing the fixes, collect new answers (or use live mode) and compare with today.</p>
<div class="actions"><button class="ghost" id="measure">Re-measure with the option chosen in step 2</button></div>
<p class="muted" style="margin-top:18px">Start over: <button class="ghost" id="reset">Clear all results</button></p>
</div></section>
</main>
<script>
const $ = s => document.querySelector(s);
let S = null, selected = new Set(), firstLoad = true;
function el(tag, attrs = {}, ...kids) { const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) { if (k === "class") e.className = v; else if (k.startsWith("on")) e[k] = v; else e.setAttribute(k, v); }
  for (const k of kids) e.append(k); return e; }
async function api(path, body) { const r = await fetch(path, body === undefined ? {} :
  {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const j = await r.json(); if (!r.ok || j.error) throw new Error(j.error || "Something went wrong"); return j; }
function mode() { const m = document.querySelector('input[name=mode]:checked'); return m && m.value; }
function pct(x) { return x == null ? "–" : Math.round(x * 100) + "%"; }

function render() {
  const t = S.target;
  if (firstLoad) {
    $("#t-name").value = t.name || ""; $("#t-website").value = t.website || ""; $("#t-location").value = t.location || "";
    $("#t-cuisine").value = t.cuisine || ""; $("#t-street").value = t.street || ""; $("#t-high").value = (t.highlights || []).join("\n");
    S.csvs.forEach(f => { if (f.answers > 0) selected.add(f.path); });
    const def = S.csvs.some(f => f.answers > 0) ? "manual" : "demo";
    document.querySelector(`input[name=mode][value=${def}]`).checked = true;
    firstLoad = false;
  }
  $("#manual-box").hidden = mode() !== "manual"; $("#live-box").hidden = mode() !== "live";
  // files
  const fb = $("#files"); fb.replaceChildren();
  if (!S.csvs.length) fb.append(el("p", {class: "muted"}, "No spreadsheets yet. Add one below."));
  S.csvs.forEach(f => { const cb = el("input", {type: "checkbox"}); cb.checked = selected.has(f.path);
    cb.onchange = () => { cb.checked ? selected.add(f.path) : selected.delete(f.path); };
    fb.append(el("label", {}, cb, `${f.name} `, el("span", {class: "muted"}, `(${f.answers} answers)`))); });
  for (const k of ["anthropic", "openai", "gemini", "perplexity"]) $("#k-" + k).placeholder = S.keys[k] ? "Saved" : "";
  // job
  const j = S.job, st = $("#stages"); st.replaceChildren();
  j.stages.forEach((name, i) => {
    const skip = j.skipped.includes(i);
    const cls = skip ? "skip" : i < j.reached || (!j.running && j.exit === 0 && i <= j.reached) ? "done" : (i === j.reached && j.running ? "now" : "");
    st.append(el("li", {class: cls}, skip ? name + " (needs an API key)" : name)); });
  $("#run").disabled = j.running; $("#measure").disabled = j.running; $("#stop").hidden = !j.running;
  $("#run").textContent = j.running ? "Running…" : "Run the agent";
  const msg = $("#run-msg"); msg.className = "";
  if (j.running) msg.textContent = `${j.elapsed}s`;
  else if (j.exit && j.exit !== 0) { msg.className = "err"; msg.textContent = "The run stopped with an error. Open “Show details” to see why."; $("#log-box").open = true; }
  else if (j.exit === 0) msg.textContent = "Done.";
  $("#log").textContent = j.log || "";
  if (j.running) $("#log").scrollTop = 1e9;
  renderResults(); renderFixes();
}

function renderResults() {
  const r = $("#results"); r.replaceChildren();
  if (!S.summary) { r.append(el("p", {class: "muted"}, S.job.running ? "Working on it…" : "Run the agent to see results here.")); return; }
  if (S.demo) r.append(el("p", {class: "note"}, "Practice data: restaurant names are placeholders. Don’t quote these numbers."));
  if (S.overall) r.append(el("div", {class: "figs"},
    el("div", {}, el("div", {class: "figure"}, pct(S.overall.mention_rate)), el("span", {}, "of AI answers recommend it")),
    el("div", {}, el("div", {class: "figure"}, pct(S.overall.revenue_weighted_visibility)), el("span", {}, "of booking value covered")),
    el("div", {}, el("div", {class: "figure"}, String(S.overall.avg_rank ?? "–")), el("span", {}, "average position"))));
  const dl = el("dl", {class: "five"});
  S.summary.answers.forEach(([q, a]) => dl.append(el("dt", {}, q), el("dd", {}, a)));
  r.append(dl);
  if (S.has_report) r.append(el("div", {class: "actions"}, el("a", {class: "btn", href: "/report", target: "_blank"}, "Open the full report")));
}

function renderFixes() {
  const f = $("#fixes"); f.replaceChildren();
  if (!S.files.length) { f.append(el("p", {class: "muted"}, "Fixes appear here after a run.")); return; }
  const pretty = n => n.replace("restaurant_schema.jsonld", "Restaurant schema (paste into website)")
    .replace("faq_schema.jsonld", "FAQ schema").replace("faq.html", "FAQ section for the website")
    .replace("about.md", "About text").replace("gbp_description.txt", "Google Business Profile description")
    .replace(/^pages\/(.*)\.html$/, (_, n) => "Web page: " + n.replace(/-/g, " "));
  const ul = el("ul", {class: "files-list"});
  S.files.filter(n => !n.startsWith("outreach/") && !n.startsWith("approved_outreach/"))
    .forEach(n => ul.append(el("li", {}, el("a", {href: "/artifacts/" + n, target: "_blank"}, pretty(n)))));
  f.append(el("h3", {}, "Website content"), ul);
  if (S.outreach.length) {
    f.append(el("h3", {}, "Emails to local guides"));
    S.outreach.forEach(d => {
      const box = el("div", {class: "draft"}, el("pre", {}, d.text));
      const st = d.status === "approved" ? el("span", {class: "tag ok"}, "Approved")
        : d.status === "declined" ? el("span", {class: "tag no"}, "Skipped") : null;
      box.append(el("div", {class: "actions"},
        el("button", {onclick: () => decide(d.name, "approve")}, "Approve"),
        el("button", {class: "ghost", onclick: () => decide(d.name, "decline")}, "Skip"), st || ""));
      f.append(box);
    });
  }
  const pr = el("details", {}, el("summary", {}, "Publish website changes to GitHub (optional)"),
    el("p", {class: "muted"}, "Opens a pull request on your site’s repository. Nothing goes live until someone merges it."),
    el("div", {class: "row"}, el("div", {}, el("label", {for: "gh-token"}, "GitHub token"), el("input", {id: "gh-token", type: "password", placeholder: S.keys.github_token ? "Saved" : ""})),
      el("div", {}, el("label", {for: "gh-repo"}, "Repository (owner/name)"), el("input", {id: "gh-repo", type: "text", placeholder: S.keys.github_repo ? "Saved" : ""}))),
    el("div", {class: "actions"}, el("button", {onclick: openPR}, "Open pull request"), el("span", {id: "pr-msg", class: "muted"})));
  f.append(pr);
}

async function refresh() { try { S = await api("/api/state"); render(); } catch (e) {} }
async function decide(name, decision) { await api("/api/approve", {name, decision}); refresh(); }
async function openPR() {
  const m = $("#pr-msg"); m.textContent = "Opening…";
  try { await api("/api/keys", {github_token: $("#gh-token").value, github_repo: $("#gh-repo").value});
    const r = await api("/api/pr", {}); m.replaceChildren("Opened: ", el("a", {href: r.url, target: "_blank"}, r.url)); }
  catch (e) { m.className = "err"; m.textContent = e.message; }
}
document.querySelectorAll("input[name=mode]").forEach(r => r.onchange = render);
$("#save-target").onclick = async () => {
  const m = $("#target-msg");
  try { await api("/api/target", {name: $("#t-name").value, website: $("#t-website").value, location: $("#t-location").value,
      cuisine: $("#t-cuisine").value, street: $("#t-street").value, highlights: $("#t-high").value});
    m.className = "muted"; m.textContent = "Saved."; refresh(); } catch (e) { m.className = "err"; m.textContent = e.message; } };
$("#save-keys").onclick = async () => {
  const b = {}; for (const k of ["anthropic", "openai", "gemini", "perplexity"]) { const v = $("#k-" + k).value; if (v) b[k] = v; }
  await api("/api/keys", b); for (const k of Object.keys(b)) $("#k-" + k).value = "";
  $("#keys-msg").textContent = "Saved for this session."; refresh(); };
$("#upload").onchange = async e => { const file = e.target.files[0]; if (!file) return;
  const r = await api("/api/upload", {name: file.name, text: await file.text()}); selected.add(r.path);
  document.querySelector('input[name=mode][value=manual]').checked = true; e.target.value = ""; refresh(); };
async function go(path) { const m = $("#run-msg"); m.className = "";
  try { await api(path, {mode: mode(), files: [...selected], quick: $("#quick").checked}); refresh(); }
  catch (e) { m.className = "err"; m.textContent = e.message; } }
$("#run").onclick = () => go("/api/run");
$("#measure").onclick = () => go("/api/measure");
$("#stop").onclick = () => api("/api/stop", {}).then(refresh);
$("#reset").onclick = async () => { if (confirm("Delete all results and generated files? Your answer spreadsheets are kept.")) { await api("/api/reset", {}); refresh(); } };
refresh(); setInterval(refresh, 2000);
</script></body></html>"""


def main():
    port = 8765
    for p in range(8765, 8785):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            continue
    else:
        raise SystemExit("No free port between 8765 and 8784.")
    url = f"http://127.0.0.1:{port}/"
    print(f"\nAI search agent is running at {url}\nKeep this window open. Close it (or press Ctrl+C) to stop.\n")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
