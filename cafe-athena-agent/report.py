"""Stage 4b - One-page visibility report for the owner (and the judges).

    python report.py --label baseline [--after rerun_label]
Writes artifacts/report.html (open in any browser; works offline).
"""
import argparse
import csv
import html
import os
from collections import OrderedDict

from analyze import load_rows
from config import DATA, OUT, TARGET, read_json
from llm import is_target

E = html.escape
PROVIDER_NAMES = {"other": "Other", "anthropic": "Claude", "openai": "ChatGPT", "gemini": "Gemini", "perplexity": "Perplexity"}
INTENT_NAMES = {"cuisine": "Greek & Mediterranean", "happy_hour": "Happy hour", "date_night": "Date night",
                "dietary": "Vegan & gluten-free", "local": "General local", "lunch": "Lunch",
                "events": "Private events", "catering": "Catering"}


def pct(x):
    return "–" if x is None else f"{x * 100:.0f}%"


def bar(value, cls=""):
    w = max(0.0, min(1.0, value or 0)) * 100
    return f'<span class="bar {cls}"><span style="width:{w:.1f}%"></span></span>'


def five_answers(label, card, after_card=None):
    """Plain-text answers to the 5 questions in the problem statement."""
    o = card["overall"]
    provs = card["by_provider"]
    best = max(provs.items(), key=lambda kv: kv[1]["mention_rate"]) if provs else None
    worst = min(provs.items(), key=lambda kv: kv[1]["mention_rate"]) if provs else None
    a1 = (f"Recommended in {pct(o['mention_rate'])} of {o['answers']} AI answers "
          f"(average position {o['avg_rank'] or 'n/a'}), covering {pct(o['revenue_weighted_visibility'])} "
          f"of potential booking value.")
    if best and worst and best[0] != worst[0]:
        a1 += (f" Strongest on {PROVIDER_NAMES.get(best[0], best[0])} ({pct(best[1]['mention_rate'])}), "
               f"weakest on {PROVIDER_NAMES.get(worst[0], worst[0])} ({pct(worst[1]['mention_rate'])}).")
    diag = read_json(DATA / "diagnosis.json") or {}
    g = diag.get("gaps", [])
    a2 = diag.get("headline", "Run diagnose.py.") + (" Main reasons: " + "; ".join(x["title"] for x in g[:3]) + "."
                                                    if g else "")
    a3 = " ".join(f"({i + 1}) {x.get('fix', '')}" for i, x in enumerate(g[:3])) or "Run diagnose.py."
    files = [p for p in OUT.rglob("*") if p.is_file() and p.name != "report.html"]
    log = read_json(DATA / "actions_log.json", [])
    done = [e for e in log if e["status"] in ("opened", "approved")]
    a4 = (f"Yes. It generated {len(files)} ready-to-use files (schema, FAQ, pages, outreach)"
          + (f" and completed {len(done)} owner-approved actions: "
             + "; ".join(f"{e['action']} {e['detail']}".strip() for e in done[-3:]) + "." if done
             else "; each action waits for owner approval (python3 act.py)."))
    exp = read_json(DATA / "experiment.json")
    a5 = []
    if exp:
        s_ = exp["summary"]
        a5.append(f"In a controlled retrieval test on the {s_['queries']} hardest queries, mentions went from "
                  f"{pct(s_['before_mention_rate'])} to {pct(s_['after_mention_rate'])} once our new page was "
                  f"available (value-weighted {pct(s_['before_revenue_weighted'])} to "
                  f"{pct(s_['after_revenue_weighted'])}).")
    if after_card:
        a5.append(f"Live re-run \"{after_card['label']}\": {pct(o['mention_rate'])} to "
                  f"{pct(after_card['overall']['mention_rate'])}.")
    a5 = " ".join(a5) or ("Not measured yet. After publishing the fixes, re-ask the same questions and run "
                          "`python3 agent.py measure --manual ...` (or `measure` with an API key) to compare.")
    return [("Where do I currently rank in AI search?", a1),
            ("Why are competitors beating me?", a2),
            ("What should I change?", a3),
            ("Can the agent make those changes for me?", a4),
            ("Did my visibility improve?", a5)]


def answers_html(label, card, after_card):
    items = "".join(f"<dt>{E(q)}</dt><dd>{E(a)}</dd>" for q, a in five_answers(label, card, after_card))
    return f"""<section><h2>The five answers</h2><dl class="five">{items}</dl></section>"""


def consistency_html(c):
    if not c:
        return ""
    if not c.get("issues"):
        body = f"<p class=\"lede\">No conflicts found across {c['sources_checked']} sources that mention the restaurant.</p>"
    else:
        body = "<ul class=\"checks issues\">" + "".join(
            f"<li class=\"miss\">{E(i['detail'])} <span class=\"muted\">({E(', '.join(i['sources'][:3]))})</span></li>"
            for i in c["issues"]) + "</ul>"
    return f"""<section><h2>Do the sources agree?</h2>
<p class="lede">Hours, phone and name near every mention of the restaurant, compared with the official facts.</p>{body}</section>"""


def hero(label, card):
    rows = load_rows(label)
    want = [r for r in rows if not r["mentioned"] and len(r.get("restaurants", [])) >= 3]
    pick = (next((r for r in want if r["qid"] == "cuisine-00"), None)
            or max(want, key=lambda r: r["value"], default=None)
            or (rows[0] if rows else None))
    if not pick:
        return ""
    items = "".join(
        f'<li class="{"us" if is_target(n) else ""}">{E(n)}</li>' for n in pick["restaurants"][:6])
    verdict = (f"{E(TARGET['name'])} is #{pick['position']}" if pick.get("position")
               else f"{E(TARGET['name'])} isn’t in this answer")
    return f"""
<section class="hero">
  <p class="who">A diner asks {E(PROVIDER_NAMES.get(pick['provider'], pick['provider']))}</p>
  <h1>“{E(pick['query'])}”</h1>
  <div class="answer"><ol>{items}</ol></div>
  <p class="verdict">{verdict}.</p>
</section>"""


def scores(card):
    o = card["overall"]
    rows = "".join(
        f"<tr><th>{E(PROVIDER_NAMES.get(p, p))}</th><td>{pct(m['mention_rate'])}</td>"
        f"<td>{bar(m['mention_rate'])}</td><td>{pct(m['revenue_weighted_visibility'])}</td>"
        f"<td>{m['avg_rank'] or '–'}</td><td>{m['answers']}</td></tr>"
        for p, m in card["by_provider"].items())
    return f"""
<section>
  <h2>Where {E(TARGET['name'])} stands</h2>
  <div class="figures">
    <p><strong>{pct(o['mention_rate'])}</strong> of AI answers recommend {E(TARGET['name'])}</p>
    <p><strong>{pct(o['revenue_weighted_visibility'])}</strong> of booking value it shows up for, weighting events and catering by ticket size</p>
    <p><strong>{o['avg_rank'] or '–'}</strong> average position when it does appear</p>
  </div>
  <div class="scroll"><table>
    <thead><tr><th>Assistant</th><th>Mentioned</th><th></th><th>Value-weighted</th><th>Avg rank</th><th>Answers</th></tr></thead>
    <tbody>{rows}</tbody></table></div>
</section>"""


def money(card):
    rows = sorted(card["by_intent"].items(), key=lambda kv: -kv[1]["value"])
    body = "".join(
        f"<tr><th>{E(INTENT_NAMES.get(i, i))}</th><td>${m['value']:,}</td>"
        f"<td>{bar(m['mention_rate'], 'olive')}</td><td>{pct(m['mention_rate'])}</td></tr>"
        for i, m in rows)
    return f"""
<section>
  <h2>Where the money is</h2>
  <p class="lede">Each row is a kind of request, with a rough value of one booking. Low bars on the expensive rows are the biggest losses.</p>
  <div class="scroll"><table><thead><tr><th>Request type</th><th>Value per booking</th><th></th><th>Mentioned</th></tr></thead>
  <tbody>{body}</tbody></table></div>
</section>"""


def competitors(card):
    comps = card["competitors"][:8]
    t = card["target"]
    top = max([c["share_of_voice"] for c in comps] + [t["share_of_voice"], 0.01])
    rows = [(c["name"], c["share_of_voice"], False) for c in comps] + [(t["name"], t["share_of_voice"], True)]
    rows.sort(key=lambda r: -r[1])
    body = "".join(
        f'<tr class="{"us" if us else ""}"><th>{E(n)}</th><td>{bar(v / top, "sun" if us else "")}</td><td>{pct(v)}</td></tr>'
        for n, v, us in rows)
    return f"""
<section>
  <h2>Who the assistants recommend instead</h2>
  <p class="lede">Share of all answers that name each place.</p>
  <div class="scroll"><table class="sov">{body}</table></div>
</section>"""


def head_to_head(h2h):
    """One block per rival that beats the target in at least one kind of request."""
    if not h2h:
        return ""
    blocks = []
    for x in h2h[:6]:
        wins = ", ".join(E(INTENT_NAMES.get(i, i.replace("_", " "))) for i in x["wins"])
        said = "".join(f"<tr><th>{E(d['theme'])}</th><td>{pct(d['rival'])}</td><td>{pct(d['target'])}</td>"
                       f"<td class=\"evidence\">{E(d['example'])}</td></tr>" for d in x["said"])
        rare = ('<p class="note">The target is mentioned too rarely to compare how the two are described.</p>'
                if x.get("target_mentions_too_rare") else "")
        src = "".join(f"<li>{E(d['domain'])}: cited in {pct(d['rival'])} of answers naming {E(x['rival'])}, "
                      f"{pct(d['target'])} naming {E(TARGET['name'])}</li>" for d in x["sources"][:4])
        web = (f"<p><strong>Its website has, {E(TARGET['name'])}'s doesn't:</strong> {E(', '.join(x['website']))}</p>"
               if x["website"] else ("" if x["website_checked"] else
                                     f'<p class="note">Website not compared: add {E(x["rival"])} to COMPETITOR_SITES in config.py.</p>'))
        h2 = (f" When both are named, {E(x['rival'])} comes first {x['rival_ahead']} of {x['both_named']} times."
              if x["both_named"] else "")
        blocks.append(f"""<h3>{E(TARGET['name'])} vs {E(x['rival'])}</h3>
<p class="lede">Leads {wins}: named in {pct(x['rival_rate'])} of those answers vs {pct(x['target_rate'])};
{x['lost']} answer{'s' if x['lost'] != 1 else ''} named it and left {E(TARGET['name'])} out (~${x['lost_value']:,} of bookings).{h2}</p>
{'<div class="scroll"><table><thead><tr><th>Praised for</th><th>' + E(x['rival']) + '</th><th>' + E(TARGET['name']) + '</th><th>Example</th></tr></thead><tbody>' + said + '</tbody></table></div>' if said else ''}
{rare}{'<ul>' + src + '</ul>' if src else ''}{web}""")
    return f"""<section><h2>Head to head with each leader</h2>
<p class="lede">Every rival that beats {E(TARGET['name'])} in at least one kind of request, and what sets it apart.</p>
{''.join(blocks)}</section>"""


def sources(card, cov):
    by_domain = OrderedDict()
    for c in cov:
        if c.get("status") != "ok":
            continue
        d = by_domain.setdefault(c["domain"], {"pages": 0, "athena": 0, "comps": set()})
        d["pages"] += 1
        d["athena"] += bool(c.get("target_present"))
        d["comps"].update(c.get("competitors_present", []))
    body = ""
    for s in card["sources"][:12]:
        d = by_domain.get(s["domain"])
        if d:
            status = (f'<span class="ok">Listed</span>' if d["athena"]
                      else f'<span class="miss">Missing</span>')
            comps = E(", ".join(sorted(d["comps"])[:3])) or "–"
        else:
            status, comps = '<span class="muted">Not checked</span>', "–"
        body += f"<tr><th>{E(s['domain'])}</th><td>{pct(s['share'])}</td><td>{status}</td><td>{comps}</td></tr>"
    return f"""
<section>
  <h2>What the assistants read before answering</h2>
  <p class="lede">The sites cited most often, and whether {E(TARGET['name'])} appears on the cited pages.</p>
  <div class="scroll"><table><thead><tr><th>Source</th><th>Cited in</th><th>{E(TARGET['name'])}</th><th>Competitors on the page</th></tr></thead>
  <tbody>{body}</tbody></table></div>
</section>"""


def site(audit):
    if not audit or audit.get("error"):
        return ""
    checks = [
        ("Restaurant schema markup", audit.get("has_restaurant_schema")),
        ("FAQ schema markup", audit.get("has_faq_schema")),
        ("Menu readable as text with prices", (audit.get("html_menu_price_count") or 0) >= 5),
        ("llms.txt file", audit.get("has_llms_txt")),
        ("No AI crawlers blocked", not any(audit.get("ai_bots_blocked", {}).values())),
    ] + [(f"Site mentions “{k}”", v) for k, v in audit.get("mentions", {}).items()]
    body = "".join(f'<li class="{"ok" if v else "miss"}">{E(n)}</li>' for n, v in checks)
    return f"""
<section>
  <h2>What an AI crawler sees on {E(TARGET.get('domain') or 'the website')}</h2>
  <ul class="checks">{body}</ul>
</section>"""


def gaps(diag):
    if not diag:
        return ""
    items = "".join(f"""
<li><h3>{E(g.get('title', ''))}</h3>
  <p class="evidence">{E(g.get('evidence', ''))}</p>
  <p><b>Fix:</b> {E(g.get('fix', ''))}</p>
  <p class="tags">Impact {E(g.get('impact', ''))} · effort {E(g.get('effort', ''))}{' · agent can do this' if g.get('agent_can_do') else ''}</p></li>"""
                    for g in diag.get("gaps", []))
    return f"""
<section>
  <h2>Why competitors win</h2>
  <p class="lede">{E(diag.get('headline', ''))}</p>
  <ol class="gaps">{items}</ol>
</section>"""


def proof(exp, after_card, card):
    parts = []
    if exp:
        s = exp["summary"]
        parts.append(f"""
<div class="beforeafter">
  <div><p class="label">Before</p><p class="big">{pct(s['before_mention_rate'])}</p><p>mentioned</p></div>
  <div><p class="label">After our content</p><p class="big after">{pct(s['after_mention_rate'])}</p><p>mentioned</p></div>
  <div><p class="label">Value-weighted</p><p class="big">{pct(s['before_revenue_weighted'])} → {pct(s['after_revenue_weighted'])}</p></div>
</div>
<p class="note">{E(s['note'])} {s['queries']} hardest queries × {s['runs']} runs.</p>""")
    if after_card:
        a, b = after_card["overall"], card["overall"]
        parts.append(f"""<p class="lede">Live re-run “{E(after_card['label'])}”: mention rate {pct(b['mention_rate'])} → {pct(a['mention_rate'])},
value-weighted {pct(b['revenue_weighted_visibility'])} → {pct(a['revenue_weighted_visibility'])}.</p>""")
    if not parts:
        return ""
    return f"<section><h2>Did it work?</h2>{''.join(parts)}</section>"


def trend():
    p = DATA / "history.csv"
    if not p.exists():
        return ""
    latest = OrderedDict()
    with p.open() as f:
        for r in csv.DictReader(f):
            if r["provider"] == "all":
                latest[r["label"]] = r
    pts = sorted(latest.values(), key=lambda r: r["timestamp"])
    if len(pts) < 2:
        return """<section><h2>Tracking over time</h2><p class="lede">One measurement so far. Re-run
<code>discover.py</code> and <code>analyze.py</code> with a new label each week; this chart fills in automatically.</p></section>"""
    W, H, pad = 640, 200, 30
    xs = [pad + i * (W - 2 * pad) / (len(pts) - 1) for i in range(len(pts))]

    def line(key, cls):
        ys = [H - pad - float(r[key]) * (H - 2 * pad) for r in pts]
        return f'<polyline class="{cls}" points="{" ".join(f"{x:.0f},{y:.0f}" for x, y in zip(xs, ys))}"/>'
    labels = "".join(f'<text x="{x:.0f}" y="{H - 8}" text-anchor="middle">{E(r["label"])}</text>'
                     for x, r in zip(xs, pts))
    return f"""
<section><h2>Tracking over time</h2>
<div class="scroll"><svg viewBox="0 0 {W} {H}" class="trend" role="img" aria-label="Visibility over time">
<line x1="{pad}" y1="{H - pad}" x2="{W - pad}" y2="{H - pad}"/>
{line('mention_rate', 'l1')}{line('revenue_weighted_visibility', 'l2')}{labels}</svg></div>
<p class="legend"><span class="k1"></span>Mention rate <span class="k2"></span>Value-weighted</p></section>"""


def made():
    files = sorted(p for p in OUT.rglob("*") if p.is_file() and p.name != "report.html")
    if not files:
        return ""
    lis = "".join(f'<li><a href="{E(p.relative_to(OUT).as_posix())}">{E(p.relative_to(OUT).as_posix())}</a></li>'
                  for p in files)
    log = read_json(DATA / "actions_log.json", [])
    log_html = "".join(f"<li>{E(e['ts'])}: {E(e['action'])}, {E(e['status'])} {E(e.get('detail', ''))}</li>"
                       for e in log[-8:])
    return f"""<section><h2>Ready-to-use fixes</h2><ul class="files">{lis}</ul>
{'<h3>Approval log</h3><ul class="log">' + log_html + '</ul>' if log_html else ''}</section>"""


CSS = """
:root{--bg:#F6F8F7;--surface:#FFFFFF;--ink:#17212B;--muted:#64707B;--line:#D6DEE2;
--sea:#0F3D63;--olive:#5B6B2C;--sun:#C98A1E;--miss:#A3412F;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0E1A24;--surface:#142533;--ink:#E7EDF0;
--muted:#9AA7B1;--line:#25394A;--sea:#7DB8E6;--olive:#A9BC6E;--sun:#E8B65A;--miss:#E48B78;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:18px/1.6 "Alegreya",Georgia,serif}
main{max-width:860px;margin:0 auto;padding:48px 24px 96px}
h1,h2,h3{font-weight:700;line-height:1.2;margin:0}
h2{font-size:1.6rem;margin-bottom:.4rem;color:var(--sea)}
h3{font-size:1.1rem}
section{padding:40px 0;border-top:1px solid var(--line)}
.lede{color:var(--muted);margin:.2rem 0 1rem;max-width:62ch}
.hero{border:0;padding-top:8px}
.hero .who{font-family:"Alegreya Sans",system-ui,sans-serif;color:var(--muted);margin:0 0 .5rem}
.hero h1{font-size:clamp(2rem,5vw,3.4rem);color:var(--sea);letter-spacing:-.01em;max-width:18ch}
.answer{margin:28px 0 12px;background:var(--surface);border-left:4px solid var(--sea);padding:18px 24px;max-width:520px}
.answer ol{margin:0;padding-left:1.4rem;font-family:"Alegreya Sans",system-ui,sans-serif;font-size:1.1rem}
.answer li.us{color:var(--olive);font-weight:700}
.verdict{font-size:1.4rem;font-style:italic;color:var(--miss);margin:.4rem 0 0}
.figures{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:24px;margin:16px 0 24px}
.figures p{margin:0;color:var(--muted);font-size:.95rem}
.figures strong{display:block;font-size:2.4rem;color:var(--ink);line-height:1.1}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-family:"Alegreya Sans",system-ui,sans-serif;font-size:.98rem}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--line);vertical-align:middle}
thead th{color:var(--muted);font-weight:500;white-space:nowrap}
tbody th{font-weight:500}
td:has(.bar){width:38%}
.bar{display:block;height:10px;background:var(--line);border-radius:5px;overflow:hidden;min-width:80px}
.bar>span{display:block;height:100%;background:var(--sea)}
.bar.olive>span{background:var(--olive)}.bar.sun>span{background:var(--sun)}
.sov tr.us th,.sov tr.us td{font-weight:700;color:var(--sun)}
.ok{color:var(--olive)}.miss{color:var(--miss)}.muted{color:var(--muted)}
.checks{list-style:none;padding:0;columns:2 260px;font-family:"Alegreya Sans",system-ui,sans-serif}
.checks li{padding:4px 0 4px 26px;position:relative;break-inside:avoid}
.checks li::before{position:absolute;left:0;font-weight:700}
.checks li.ok::before{content:"✓"}.checks li.miss::before{content:"✗"}
.five{margin:0;display:grid;gap:14px}
.five dt{font-weight:700;color:var(--sea)}
.five dd{margin:0 0 6px;max-width:68ch}
.checks.issues{columns:auto}
.demo{background:var(--sun);color:#17212B;padding:8px 14px;font-family:"Alegreya Sans",system-ui,sans-serif;margin:0 0 24px}
.gaps{padding-left:1.4rem}.gaps li{margin:0 0 22px}
.gaps p{margin:.25rem 0}.evidence{color:var(--muted)}
.tags{font-family:"Alegreya Sans",system-ui,sans-serif;font-size:.85rem;color:var(--muted)}
.beforeafter{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:24px}
.beforeafter p{margin:0}.label{color:var(--muted);font-family:"Alegreya Sans",system-ui,sans-serif}
.big{font-size:2.6rem;font-weight:700;line-height:1.1}.big.after{color:var(--olive)}
.note{color:var(--muted);font-size:.9rem;margin-top:16px}
.trend{width:100%;min-width:420px;height:auto}
.trend line{stroke:var(--line)}.trend polyline{fill:none;stroke-width:3}
.trend .l1{stroke:var(--sea)}.trend .l2{stroke:var(--sun)}
.trend text{fill:var(--muted);font:12px "Alegreya Sans",system-ui,sans-serif}
.legend{font-family:"Alegreya Sans",system-ui,sans-serif;color:var(--muted);font-size:.9rem}
.legend span{display:inline-block;width:14px;height:4px;margin:0 6px 3px 12px;vertical-align:middle}
.k1{background:var(--sea)}.k2{background:var(--sun)}
.files,.log{font-family:"Alegreya Sans",system-ui,sans-serif;font-size:.95rem}
a{color:var(--sea)}a:focus-visible{outline:2px solid var(--sun);outline-offset:2px}
footer{color:var(--muted);font-size:.85rem;padding-top:24px;border-top:1px solid var(--line)}
@media (max-width:600px){body{font-size:17px}main{padding:28px 16px 64px}}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--after", default="")
    args = ap.parse_args()
    card = read_json(DATA / f"scorecard_{args.label}.json")
    if not card:
        raise SystemExit("Run analyze.py first.")
    after_card = read_json(DATA / f"scorecard_{args.after}.json") if args.after else None
    cov = read_json(DATA / "source_coverage.json", [])
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(TARGET['name'])}: AI search visibility</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Alegreya:ital,wght@0,400;0,700;1,400&family=Alegreya+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><main>
{'<p class="demo">Demo mode: simulated data with placeholder restaurant names. Run without --demo for real results.</p>' if (read_json(DATA / 'site_audit.json') or {}).get('mock') else ''}
{hero(args.label, card)}
{answers_html(args.label, card, after_card)}
{scores(card)}
{money(card)}
{competitors(card)}
{head_to_head(read_json(DATA / 'head_to_head.json', []))}
{sources(card, cov)}
{site(read_json(DATA / 'site_audit.json'))}
{consistency_html(read_json(DATA / 'consistency.json'))}
{gaps(read_json(DATA / 'diagnosis.json'))}
{proof(read_json(DATA / 'experiment.json'), after_card, card)}
{trend()}
{made()}
<footer>Measured {E(card['generated'])} across {card['overall']['answers']} AI answers from
{E(', '.join(PROVIDER_NAMES.get(p, p) for p in card['by_provider']))}. Each query asked several times because AI answers vary.</footer>
</main></body></html>"""
    out = OUT / "report.html"
    out.write_text(doc, encoding="utf-8")
    print("Wrote", os.path.relpath(out))


if __name__ == "__main__":
    main()
