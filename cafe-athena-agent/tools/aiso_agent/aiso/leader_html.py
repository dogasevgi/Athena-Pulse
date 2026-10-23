"""HTML for the leader analysis, using the same classes and CSS as report.html.

render_sections(a) returns <section> blocks you can paste into report.html.
render_page(a, css) wraps them in a standalone page.
"""
from __future__ import annotations

from html import escape as e

CAT_LABEL = {"cuisine": "Greek & Mediterranean", "dietary": "Vegan & gluten-free",
             "happy_hour": "Happy hour", "date_night": "Date night", "events": "Private events",
             "casual": "General local", "catering": "Catering", "lunch": "Lunch"}

EXTRA_CSS = """
.gapbars{display:grid;gap:6px;margin:4px 0}
.gapbars .row{display:grid;grid-template-columns:9rem 1fr 3.2rem;gap:10px;align-items:center;
  font-family:"Alegreya Sans",system-ui,sans-serif;font-size:.95rem}
section>h3{margin:28px 0 8px}
.reasons{margin:.4rem 0 0;padding-left:1.2rem}.reasons li{margin:.2rem 0}
.quote{color:var(--muted);font-style:italic;font-size:.95rem}
.cat{padding:18px 0;border-bottom:1px solid var(--line)}.cat:last-child{border-bottom:0}
.cat h3{display:flex;flex-wrap:wrap;gap:.2rem .8rem;align-items:baseline}
.cat h3 .gap{font-family:"Alegreya Sans",system-ui,sans-serif;font-weight:500;color:var(--miss);font-size:1rem}
.cat h3 .gap.ahead{color:var(--olive)}
"""


def _pct(x):
    return "–" if x is None else f"{x:.0%}"


def _bars(leader, lr, ar):
    def row(name, v, cls):
        return (f'<div class="row"><span>{e(name)}</span><span class="bar {cls}">'
                f'<span style="width:{100 * v:.1f}%"></span></span><span>{v:.0%}</span></div>')
    return f'<div class="gapbars">{row(leader, lr, "")}{row("Café Athena", ar, "sun")}</div>'


def _reasons(rs):
    if not rs:
        return '<p class="muted">Not enough evidence yet. Run more queries, or audit this site.</p>'
    return '<ul class="reasons">' + "".join(f"<li>{e(r)}</li>" for r in rs) + "</ul>"


def _gap_label(g):
    if g > 0:
        return f'<span class="gap">Café Athena is {g:.0f} pts behind</span>'
    return f'<span class="gap ahead">Café Athena is {-g:.0f} pts ahead</span>'


def render_sections(a: dict) -> str:
    o = a["overall"]
    lead = e(o["leader"])
    rank_line = (f'{lead} averages position {o["leader_avg_rank"]}, Café Athena '
                 f'{o["athena_avg_rank"] or "is rarely listed"}.')
    h2h = (f'When both are named, {lead} comes first {o["leader_ahead"]} of {o["both_named"]} times.'
           if o["both_named"] else f'They are never named in the same answer.')

    why_rows = "".join(
        f'<tr><th>{e(w["theme"])}</th><td>{_pct(w["leader_share"])}</td>'
        f'<td>{_pct(w["athena_share"])}</td>'
        f'<td class="quote">{e(w["example"] or "")}</td></tr>' for w in o["why"])
    why_table = (f'<div class="scroll"><table><thead><tr><th>What assistants praise</th>'
                 f'<th>{lead}</th><th>Café Athena</th><th>Example</th></tr></thead>'
                 f'<tbody>{why_rows}</tbody></table></div>') if why_rows else ""

    src_rows = "".join(
        f'<tr><th>{e(s["domain"])}</th><td>{_pct(s["leader_answers"])}</td>'
        f'<td>{_pct(s["athena_answers"])}</td></tr>' for s in o["sources"][:6])
    src_table = (f'<h3>Sources behind the answers</h3><p class="lede">Share of answers naming each '
                 f'restaurant that cite the site.</p><div class="scroll"><table><thead><tr>'
                 f'<th>Source</th><th>{lead}</th><th>Café Athena</th></tr></thead>'
                 f'<tbody>{src_rows}</tbody></table></div>') if src_rows else ""

    def yn(v):
        if v is True:
            return '<span class="ok">Yes</span>'
        if v is False:
            return '<span class="miss">No</span>'
        return e(str(v))
    site_rows = "".join(
        f'<tr><th>{e(r["topic"] if r["topic"][0].isupper() else r["topic"].replace("_", " ").capitalize())}</th><td>{yn(r["leader"])}</td>'
        f'<td>{yn(r["athena"])}</td></tr>' for r in (o["site"] or []))
    site_block = (f'<h3>Websites compared</h3><div class="scroll"><table><thead><tr><th>Topic or markup</th>'
                  f'<th>{lead}</th><th>Café Athena</th></tr></thead><tbody>{site_rows}</tbody>'
                  f'</table></div>') if site_rows else ""

    overall = f"""
<section>
  <h2>Why {lead} wins</h2>
  <p class="lede">{lead} is the restaurant AI assistants name most often. {rank_line} {h2h}</p>
  {_bars(o["leader"], o["leader_rate"], o["athena_rate"])}
  <div class="figures">
    <p><strong>{o["gap_pts"]:+.0f} pts</strong> mention-rate gap to Café Athena</p>
    <p><strong>{o["lost_to_leader"]}</strong> answers named {lead} and left Café Athena out</p>
  </div>
  <h3>The reasons, from the evidence</h3>
  {_reasons(o["reasons"])}
  {why_table}
  {src_table}
  {site_block}
</section>"""

    cats = []
    for cat, c in a["by_category"].items():
        cats.append(f"""
  <div class="cat">
    <h3>{e(CAT_LABEL.get(cat, cat.replace("_", " ").title()))}: {e(c["leader"])} {_gap_label(c["gap_pts"])}</h3>
    {_bars(c["leader"], c["leader_rate"], c["athena_rate"])}
    {_reasons(c["reasons"][:3])}
  </div>""")
    same = ("The same restaurant leads every category." if a.get("same_leader_everywhere")
            else "A different restaurant leads some categories, so each needs its own fix.")
    by_cat = f"""
<section>
  <h2>Category by category</h2>
  <p class="lede">The most-named rival for each kind of request, how far behind Café Athena is,
  and why. {same}</p>
  {"".join(cats)}
</section>"""
    narrative = (f'<section><h2>In plain words</h2><p>{e(a["narrative"])}</p></section>'
                 if a.get("narrative") else "")
    return overall + by_cat + narrative


def render_per_leader(pl: list[dict]) -> str:
    if not pl:
        return ""
    blocks = []
    for p in pl:
        L = e(p["leader"])
        cats = ", ".join(e(CAT_LABEL.get(c, c)) for c in p["wins"])
        said = "".join(
            f'<tr><th>{e(d["theme"])}</th><td>{_pct(d["leader"])}</td><td>{_pct(d["athena"])}</td>'
            f'<td class="quote">{e(d.get("example") or "")}</td></tr>' for d in p["said_gaps"])
        edges = "".join(
            f'<tr><th>{e(d["theme"])}</th><td>{_pct(d["leader"])}</td>'
            f'<td class="ok">{_pct(d["athena"])}</td><td class="quote">{e(d.get("example") or "")}</td></tr>'
            for d in p["athena_edges"])
        srcs = "".join(f'<li>{e(s["domain"])}: in {_pct(s["leader_answers"])} of answers naming {L}, '
                       f'{_pct(s["athena_answers"])} naming Café Athena</li>' for s in p["source_gaps"][:4])
        site = (", ".join(e(r["topic"].replace("_", " ")) for r in p["site_gaps"])
                if p["site_gaps"] else ("" if p["site_compared"] else None))
        site_html = ("" if site == "" else
                     f'<p class="muted">Website not compared yet. Add {L} to COMPETITOR_SITES and run audit.</p>'
                     if site is None else f'<p><strong>Its website covers, Café Athena’s doesn’t:</strong> {site}</p>')
        blocks.append(f"""
  <div class="cat">
    <h3>Café Athena vs {L} {_gap_label(p["gap_pts"])}</h3>
    <p class="lede">Leads in {cats}. {p["lost_to_leader"]} answers named {L} and not Café Athena.</p>
    {_bars(p["leader"], p["leader_rate"], p["athena_rate"])}
    {f'<div class="scroll"><table><thead><tr><th>Praised for</th><th>{L}</th><th>Café Athena</th><th>Example</th></tr></thead><tbody>{said}</tbody></table></div>' if said else '<p class="muted">No clear difference in how assistants describe them yet.</p>'}
    {f'<h3>Where Café Athena is described better</h3><div class="scroll"><table><tbody>{edges}</tbody></table></div>' if edges else ''}
    {f'<h3>Sources that favor {L}</h3><ul class="reasons">{srcs}</ul>' if srcs else ''}
    {site_html}
  </div>""")
    return f"""
<section>
  <h2>Head to head with each leader</h2>
  <p class="lede">Every restaurant that beats Café Athena in at least one category, and what sets it apart.</p>
  {"".join(blocks)}
</section>"""


def render_combined(ours: dict, ours_platform: str, teammates: list[dict]) -> str:
    """Side-by-side visibility by request type across assistants (ours + teammates' runs)."""
    if not teammates or not ours.get("n"):
        return ""
    label = ", ".join(x.replace("-web", " + web").capitalize() for x in ours_platform.split(", ")) + " (ours)"
    cols = [(label, ours.get("n"), {c: b["mention_rate"] for c, b in ours["by_category"].items()},
             ours["mention_rate"], ours.get("value_weighted"))]
    cols += [(t["platform"] + " (teammate)", t["answers"], t["by_category"], t["mention_rate"],
              t.get("value_weighted")) for t in teammates]
    cats = sorted({c for _, _, bc, _, _ in cols for c in bc},
                  key=lambda c: -__import__("aiso.config", fromlist=["x"]).BOOKING_VALUE.get(c, 0))
    head = "".join(f"<th>{e(n)}<br><span class=\"muted\">{k} answers</span></th>" for n, k, _, _, _ in cols)
    body = "".join(
        f"<tr><th>{e(CAT_LABEL.get(c, c.replace('_', ' ').title()))}</th>"
        + "".join(f'<td class="{"miss" if bc.get(c) == 0 else ""}">{_pct(bc.get(c))}</td>' for _, _, bc, _, _ in cols)
        + "</tr>" for c in cats)
    tot = ("<tr><th>All questions</th>" + "".join(f"<td><strong>{_pct(m)}</strong></td>" for *_, m, _ in cols)
           + "</tr><tr><th>Value-weighted</th>" + "".join(f"<td>{_pct(v)}</td>" for *_, v in cols) + "</tr>")
    t0 = teammates[0]
    site = t0.get("site_audit_cafeathena_com", {})
    checks = [("Restaurant schema", site.get("restaurant_schema")), ("FAQ schema", site.get("faq_schema")),
              ("Menu prices readable as text", site.get("menu_prices_as_text")),
              ("llms.txt", site.get("llms_txt")), ("AI crawlers allowed", not site.get("ai_crawlers_blocked", False))]
    checks += [(f"Site mentions “{k}”", v) for k, v in site.get("mentions", {}).items()]
    check_html = "".join(f'<li class="{"ok" if v else "miss"}">{e(k)}</li>' for k, v in checks if v is not None)
    srcs = "".join(
        f'<tr><th>{e(x["domain"])}</th><td>{_pct(x["cited"])}</td><td>'
        + {True: '<span class="ok">Listed</span>', False: '<span class="miss">Missing</span>',
           None: '<span class="muted">Not checked</span>'}[x["athena"]]
        + f'</td><td>{e(", ".join(x.get("competitors", [])) or "–")}</td></tr>' for x in t0.get("cited_sources", []))
    return f"""
<section>
  <h2>Two assistants, one story</h2>
  <p class="lede">Mention rate by request type, ordered by booking value. Each assistant was measured
  separately; the pattern is what matters: strong on Greek food, missing on occasions.</p>
  <div class="scroll"><table><thead><tr><th>Request type</th>{head}</tr></thead>
  <tbody>{body}{tot}</tbody></table></div>
  <h3>What an AI crawler sees on cafeathena.com</h3>
  <p class="lede">From the teammate’s live audit of the site.</p>
  <ul class="checks">{check_html}</ul>
  <h3>Pages {e(t0["platform"])} cites, and whether Café Athena is on them</h3>
  <div class="scroll"><table><thead><tr><th>Source</th><th>Cited in</th><th>Café Athena</th>
  <th>Competitors on the page</th></tr></thead><tbody>{srcs}</tbody></table></div>
  <p class="note">{e(t0.get("nap_consistency", ""))}</p>
</section>"""


def render_plan(plan: list[dict]) -> str:
    if not plan:
        return ""
    items = "".join(
        f'<li><h3>{e(a["title"])}</h3><p class="evidence">{"<br>".join(e(w) for w in a["why"][:3])}</p>'
        f'<p class="tags">{("Impact: ~$" + format(a["weight"], ",") + " of bookings") if a.get("basis", "value") == "value" else "From cited sources and names"}'
        f' · delivered by: {e(", ".join(a["deliver"]))}</p></li>'
        for a in plan)
    return f"""
<section>
  <h2>What to change, in order</h2>
  <p class="lede">Each action closes a specific difference above. The agent drafts the content for every one.</p>
  <ol class="gaps">{items}</ol>
</section>"""


def render_page(a: dict, base_css: str = "", warn: str = "", per_leader=None, plan=None,
                combined: str = "") -> str:
    warn_html = f'<p class="verdict">{e(warn)}</p>' if warn else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Café Athena: who beats it in AI answers, and why</title>
<link href="https://fonts.googleapis.com/css2?family=Alegreya:ital,wght@0,400;0,700;1,400&family=Alegreya+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<style>{base_css}{EXTRA_CSS}</style></head><body><main>
<section class="hero"><p class="who">Competitive gap</p>
<h1>Who AI assistants pick over Café Athena, and why</h1>{warn_html}</section>
{combined}
{render_sections(a)}
{render_per_leader(per_leader or [])}
{render_plan(plan or [])}
</main></body></html>"""
