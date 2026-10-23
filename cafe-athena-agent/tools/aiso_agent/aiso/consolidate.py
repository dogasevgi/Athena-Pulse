"""One report for the whole team: our Gemini runs + the teammate's Claude report + the
dashboard prototype's ideas, organized around the five owner questions in the brief.

Live numbers come from out/aiso.db when it exists (all live runs, plus the latest
simulate before/after). Otherwise the snapshot in consolidated_inputs.json is used.
"""
from __future__ import annotations

import json
import os
import time
from html import escape as e

from .discovery import scorecard
from .leader_html import CAT_LABEL, EXTRA_CSS

HERE = os.path.dirname(__file__)
STATUS = {"done": ("Done, approved", "ok"), "drafted": ("Drafted", "ok"),
          "next": ("Next", "muted"), "owner": ("Needs owner", "miss")}
ORDER = ["events", "catering", "date_night", "casual", "cuisine", "dietary", "happy_hour", "lunch"]


def _pct(x):
    return "–" if x is None else f"{x:.0%}"


def _yn(v):
    if v is True:
        return '<span class="ok">Yes</span>'
    if v is False:
        return '<span class="miss">No</span>'
    return '<span class="muted">Not checked</span>' if v is None else e(str(v))


def gather(db, aliases) -> dict:
    """Live Gemini numbers and simulate results from the database, if any."""
    live, sim = None, None
    if db is None:
        return {"live": None, "sim": None}
    runs = [r for r in db.runs("live") if db.results(r["run_id"])]
    if runs:
        rows = [x for r in runs for x in db.results(r["run_id"])]
        latest = db.results(runs[-1]["run_id"])
        live = {
            "runs": [{"label": r["label"], "n": len(db.results(r["run_id"])),
                      "mentioned": sum(1 for x in db.results(r["run_id"]) if x["target_pos"])} for r in runs],
            "platforms": sorted({x["platform"] for x in rows}),
            "all": scorecard(rows, aliases), "latest": scorecard(latest, aliases),
        }
    sims = db.runs("sim")
    before = [r for r in sims if r["label"] == "sim-before"]
    after = [r for r in sims if r["label"] == "sim-after"]
    if before and after and after[-1]["created_at"] > before[-1]["created_at"]:
        b, a = scorecard(db.results(before[-1]["run_id"]), aliases), scorecard(db.results(after[-1]["run_id"]), aliases)
        if b.get("n") and a.get("n"):
            sim = {"before": b, "after": a}
    return {"live": live, "sim": sim}


def render(inputs: dict, claude: dict | None, data: dict, css: str) -> str:
    live, sim = data["live"], data["sim"]
    snap = inputs["snapshot_gemini"]
    runs = live["runs"] if live else snap["runs"]
    g_n = sum(r["n"] for r in runs)
    g_m = sum(r["mentioned"] for r in runs)
    g_cat = ({c: b["mention_rate"] for c, b in live["latest"]["by_category"].items()} if live
             else snap["by_category_run2"])
    g_rivals = ([c["name"] for c in live["all"]["competitors"][:6]] if live else snap["top_rivals"])
    c_rivals = [n for n, _ in (claude or {}).get("top_competitors", [])]
    both = sorted({r for r in g_rivals + snap.get("run1_rivals", [])}
                  & {r.replace("Pacific Beach AleHouse", "PB AleHouse") for r in c_rivals})

    # ---- Q1
    run_rows = "".join(f"<tr><th>Gemini · {e(r['label'])}</th><td>{r['n']}</td><td>{r['mentioned']}</td>"
                       f"<td>{_pct(r['mentioned'] / r['n'] if r['n'] else None)}</td></tr>" for r in runs)
    if claude:
        run_rows += (f"<tr><th>Claude · teammate report</th><td>{claude['answers']}</td>"
                     f"<td>≈{round(claude['mention_rate'] * claude['answers'])}</td><td>{_pct(claude['mention_rate'])}</td></tr>")
    cats = [c for c in ORDER if c in g_cat or (claude and c in claude["by_category"])]
    cat_rows = "".join(
        f"<tr><th>{e(CAT_LABEL.get(c, c))}</th>"
        f'<td class="{"miss" if g_cat.get(c) == 0 else ""}">{_pct(g_cat.get(c))}</td>'
        f'<td class="{"miss" if claude and claude["by_category"].get(c) == 0 else ""}">'
        f'{_pct(claude["by_category"].get(c) if claude else None)}</td></tr>' for c in cats)
    examples = "".join(f"<li><strong>“{e(x['query'])}”</strong>: {e(x['result'])}</li>" for x in inputs["examples"])

    # ---- Q2
    sc = inputs["site_compare"]
    site_rows = "".join("<tr><th>" + e(r[0]) + "</th>" + "".join(f"<td>{_yn(v)}</td>" for v in r[1:]) + "</tr>"
                        for r in sc["rows"])
    missing = [x for x in (claude or {}).get("cited_sources", []) if x["athena"] is False]
    cited = "".join(f"<li>{e(x['domain'])} lists {e(', '.join(x.get('competitors', [])))}, not Café Athena</li>"
                    for x in missing)
    trends = "".join(f"<li>{e(t)}</li>" for t in inputs["trends"])
    conflicts = "".join(f"<li>{e(t)}</li>" for t in inputs["conflicts"])

    # ---- Q3/Q4
    plan = "".join(
        f'<li><h3>{e(p["title"])}</h3><p class="evidence">{e(p["evidence"])}</p>'
        f'<p class="tags"><span class="{STATUS[p["status"]][1]}">{STATUS[p["status"]][0]}</span>'
        f' · {e(p["value"])} · found by {e(", ".join(p["found_by"]))}'
        f'{" · delivered by: " + e(p["deliverable"]) if p["deliverable"] else ""}</p>'
        f'{"<p><strong>Owner:</strong> " + e(p["owner"]) + "</p>" if p["owner"] else ""}</li>'
        for p in inputs["plan"])
    done = sum(1 for p in inputs["plan"] if p["status"] in ("done", "drafted"))
    pages = ", ".join(e(x) for x in inputs["approved_pages"])

    # ---- Q5
    if sim:
        b, a = sim["before"], sim["after"]
        rows = "".join(
            f"<tr><th>{e(CAT_LABEL.get(c, c))}</th><td>{_pct(b['by_category'][c]['mention_rate'])}</td>"
            f"<td>{_pct(a['by_category'].get(c, {}).get('mention_rate'))}</td></tr>"
            for c in ORDER if c in b["by_category"])
        q5 = f"""
  <div class="beforeafter">
    <div><p class="label">Mentioned, before</p><p class="big">{_pct(b['mention_rate'])}</p></div>
    <div><p class="label">Mentioned, after</p><p class="big after">{_pct(a['mention_rate'])}</p></div>
    <div><p class="label">Top 3, before → after</p><p class="big">{_pct(b['top3_rate'])} → {_pct(a['top3_rate'])}</p></div>
  </div>
  <div class="scroll"><table><thead><tr><th>Request type</th><th>Before</th><th>After</th></tr></thead>
  <tbody>{rows}</tbody></table></div>
  <p class="note">Controlled simulation: the assistant answered each question using only real page text from Café Athena
  and the audited rivals, first with today’s site, then with the approved pages added. Everything else was held
  constant. This estimates the effect of the content; it is not a live ranking change.</p>"""
    else:
        q5 = """<p><strong>Pending.</strong> The before/after simulation is running. When it finishes, run
  <code>python cli.py consolidate</code> and this section fills in automatically.</p>"""

    def sources_rows():
        return "".join(f"<tr><th>{e(s['team'])}</th><td>{e(s['what'])}</td>"
                       f'<td class="{"ok" if s["status"] == "live" else "miss"}">{e(s["status"].title())}</td>'
                       f"<td>{e(s['use'])}</td></tr>" for s in inputs["sources"])

    claude_line = f" and in {_pct(claude['mention_rate'])} of {claude['answers']} Claude answers" if claude else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Café Athena: AI search plan (team report)</title>
<link href="https://fonts.googleapis.com/css2?family=Alegreya:ital,wght@0,400;0,700;1,400&family=Alegreya+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<style>{css}{EXTRA_CSS}
ol.plan{{padding-left:1.4rem}}ol.plan li{{margin:0 0 22px}}ol.plan p{{margin:.25rem 0}}
code{{font-size:.9em}}</style></head><body><main>

<section class="hero">
  <p class="who">Café Athena · 1846 Garnet Ave, Pacific Beach · since 1990</p>
  <h1>AI assistants rarely recommend Café Athena</h1>
  <p class="verdict">It was recommended in {g_m} of {g_n} Gemini answers{claude_line}, and never for
  private events, date night, happy hour or dietary questions in either assistant.</p>
</section>

<section>
  <h2>Where this report comes from</h2>
  <div class="scroll"><table><thead><tr><th>Source</th><th>What it contains</th><th>Data</th><th>In this report</th></tr></thead>
  <tbody>{sources_rows()}</tbody></table></div>
</section>

<section>
  <h2>1. Where do I rank in AI search?</h2>
  <div class="scroll"><table><thead><tr><th>Assistant · run</th><th>Answers</th><th>Recommended</th><th>Rate</th></tr></thead>
  <tbody>{run_rows}</tbody></table></div>
  <h3>By kind of request</h3>
  <p class="lede">Ordered by the value of one booking. Gemini column: {"latest live run" if live else "run 2"}.</p>
  <div class="scroll"><table><thead><tr><th>Request type</th><th>Gemini</th><th>Claude</th></tr></thead>
  <tbody>{cat_rows}</tbody></table></div>
  <h3>Examples</h3><ul class="reasons">{examples}</ul>
  <h3>Who gets recommended instead</h3>
  <p><strong>Gemini:</strong> {e(", ".join(g_rivals))}.<br><strong>Claude:</strong> {e(", ".join(c_rivals))}.</p>
  {f"<p><strong>Named by both assistants:</strong> {e(', '.join(both))}.</p>" if both else ""}
</section>

<section>
  <h2>2. Why are competitors beating me?</h2>
  <ol class="plan">
    <li><h3>Known for the food, invisible for everything else</h3><p class="evidence">Both assistants mention Café
    Athena mostly for Greek food questions, though it runs a daily happy hour, a mythology-themed cocktail bar, group
    dining and catering. Those offers have no pages of their own that assistants can quote.</p></li>
    <li><h3>The site doesn't tell machines it's a restaurant</h3><p class="evidence">Gemini's most-recommended rival
    (JRDN) marks up its site as a Restaurant with a FAQ and has an llms.txt. Café Athena has none of these.</p>
    <div class="scroll"><table><thead><tr><th></th>{"".join(f"<th>{e(c)}</th>" for c in sc["columns"])}</tr></thead>
    <tbody>{site_rows}</tbody></table></div><p class="note">{e(sc["source"])}</p></li>
    <li><h3>Missing from the guides assistants cite</h3><ul class="reasons">{cited}</ul></li>
    <li><h3>Demand is where Café Athena is absent</h3><ul class="reasons">{trends}</ul>
    <p class="note">Google Trends, San Diego, past 12 months.</p></li>
  </ol>
  <h3>Where the sources disagree</h3><ul class="reasons">{conflicts}</ul>
</section>

<section>
  <h2>3. What should I change?</h2>
  <p class="lede">One plan merged from all three teams, highest booking value first.</p>
  <ol class="plan">{plan}</ol>
</section>

<section>
  <h2>4. Can the agent make those changes?</h2>
  <p>Yes, with the owner's approval at every step. {done} of {len(inputs["plan"])} actions are done or drafted.
  All facts come from Café Athena's own website, bar menu, catering menu and ordering page.</p>
  <ul class="reasons">
    <li><strong>Approved pages:</strong> {pages}.</li>
    <li><strong>Structured data:</strong> Restaurant, Menu (with prices and diet tags) and FAQPage schema, plus llms.txt.</li>
    <li><strong>Publishing:</strong> pages go to WordPress as drafts only; one command removes them. Dry run passed.</li>
    <li><strong>Outreach:</strong> emails drafted to each guide that lists rivals but not Café Athena.</li>
  </ul>
</section>

<section>
  <h2>5. Did my visibility improve?</h2>
  {q5}
  <p class="note">After publishing, the same questions are re-asked every week (GitHub Actions schedule) to track
  the real change in Gemini, Claude and other assistants.</p>
</section>

<footer>Built {time.strftime("%Y-%m-%d %H:%M")}. Gemini numbers: {"live database" if live else "snapshot of runs on 2026-10-23"}.
Claude numbers: teammate report (aggregates). Dashboard prototype numbers are simulated and not used.</footer>
</main></body></html>"""


def build(db, aliases, out_path: str) -> dict:
    with open(os.path.join(HERE, "consolidated_inputs.json")) as f:
        inputs = json.load(f)
    claude_p = os.path.join(HERE, "teammate", "claude_2026-10-23.json")
    claude = json.load(open(claude_p)) if os.path.exists(claude_p) else None
    css = open(os.path.join(HERE, "report_base.css")).read()
    data = gather(db, aliases)
    with open(out_path, "w") as f:
        f.write(render(inputs, claude, data, css))
    return data
