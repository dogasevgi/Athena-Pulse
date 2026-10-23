"""AISO growth agent for Café Athena: Discovery -> Analysis -> Action -> Measurement.

  python cli.py discover --platforms claude-web,gpt,gemini-web,perplexity
  python cli.py score
  python cli.py audit
  python cli.py diagnose
  python cli.py generate
  python cli.py approve [--repo ../cafeathena-site]
  python cli.py simulate --platforms claude
  python cli.py trend
  python cli.py leader          # who beats Café Athena, by how much, why, and the action plan
  python cli.py consolidate     # one team report: all sources, merged plan, before/after
  python cli.py sources         # do the pages assistants cite list Café Athena?
  python cli.py publish --wordpress [--live]   # push approved pages as WordPress drafts
  python cli.py unpublish                      # delete exactly the drafts that were created
  python cli.py demo            # full loop offline with MOCK data, no keys needed
  python cli.py trends-import relatedQueries.csv   # add real search demand to the bank
  python cli.py manual-export --platform claude-chat --limit 12   # no-API mode
  python cli.py manual-import --platform claude-chat
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import time

from aiso import action, approve, audit, diagnose, discovery, generate, leader, leader_html, llm, manual, measure, publish, queries, sources, trends
from aiso import consolidate
from aiso.config import COMPETITOR_SITES, RESTAURANT
from aiso.extract import norm
from aiso.storage import DB

OUT = "out"
ALIASES = [norm(RESTAURANT["name"])] + RESTAURANT["aliases"]


def _save(name, obj):
    os.makedirs(OUT, exist_ok=True)
    with open(f"{OUT}/{name}", "w") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def _load(name):
    with open(f"{OUT}/{name}") as f:
        return json.load(f)


def cmd_discover(a, db):
    bank = queries.load_or_build(f"{OUT}/query_bank.json", a.per_template)
    provs = llm.get_providers(a.platforms.split(","))
    if not provs:
        raise SystemExit("No platforms available. Set API keys or use --platforms mock.")
    print(f"Running {len(bank)} queries x {len(provs)} platforms")
    run = discovery.run_discovery(db, bank, provs, llm.analysis_llm(), ALIASES, a.label)
    print(f"\nRun saved: {run}")
    cmd_score(argparse.Namespace(run=run), db)


def cmd_score(a, db):
    run = a.run or db.latest("live")
    sc = discovery.scorecard(db.results(run), ALIASES)
    discovery.print_scorecard(sc, f"Visibility scorecard ({run})")
    _save("scorecard.json", sc)


def cmd_audit(a, db):
    target = audit.audit_site(RESTAURANT["name"], RESTAURANT["website"])
    comps = [audit.audit_site(n, u) for n, u in COMPETITOR_SITES.items()]
    _save("audit.json", {"target": target, "competitors": comps})
    for x in [target] + comps:
        print(f"{x['name']:<28} {x['word_count']:>6} words  schema={x['jsonld_types']}"
              f"  faq_schema={x['has_faq_schema']}")


def cmd_diagnose(a, db):
    au = _load("audit.json")
    d = diagnose.diagnose(_load("scorecard.json"), au["target"], au["competitors"],
                          llm.analysis_llm())
    _save("diagnosis.json", d)
    diagnose.print_diagnosis(d)


def cmd_generate(a, db):
    outdir = f"{OUT}/content/{time.strftime('%Y%m%d-%H%M')}"
    if os.path.exists(f"{OUT}/plan.json"):  # gap-driven content (run `leader` first)
        files = action.generate(RESTAURANT, _load("plan.json"), llm.analysis_llm(), outdir)
    else:
        print("No plan.json yet; run `python cli.py leader` for gap-driven content. Using basic content.")
        files = generate.generate_all(RESTAURANT, _load("diagnosis.json"), _load("scorecard.json"),
                                      llm.analysis_llm(), outdir)
    print("Generated:\n  " + "\n  ".join(files))


def _latest_content():
    dirs = sorted(glob.glob(f"{OUT}/content/*"), key=os.path.getmtime)  # newest last
    if not dirs:
        raise SystemExit("Run `generate` first.")
    return dirs[-1]


def cmd_approve(a, db):
    approve.review(_latest_content(), assume_yes=a.yes, repo=a.repo)


def _content_text(folder):
    parts = []
    for p in sorted(glob.glob(f"{folder}/*.md")):
        if "outreach" not in p:
            parts.append(open(p).read())
    return "\n".join(parts)


def cmd_simulate(a, db):
    au = _load("audit.json")
    bank = measure.balanced_sample(queries.load_or_build(f"{OUT}/query_bank.json"), a.limit)
    provs = llm.get_providers(a.platforms.split(","))
    comp_docs = [(c["name"], c["text"]) for c in au["competitors"] if c.get("text")]
    print(f"Simulating {len(bank)} questions x 2 (before and after) on {', '.join(p.name for p in provs)}")
    before_text = au["target"]["text"]
    after_text = before_text + "\n" + _content_text(a.content or "out/publish")
    ex = llm.analysis_llm()
    b = measure.run_simulation(db, "sim-before", bank, RESTAURANT["name"], before_text,
                               comp_docs, provs, ex, ALIASES)
    af = measure.run_simulation(db, "sim-after", bank, RESTAURANT["name"], after_text,
                                comp_docs, provs, ex, ALIASES)
    measure.compare(db, b, af, ALIASES)


def cmd_trend(a, db):
    _save("trend.json", measure.trend(db, ALIASES))


def cmd_leader(a, db):
    run = a.run or db.latest("live") or db.latest("demo")
    rows = db.results(run)
    audits = _load("audit.json") if os.path.exists(f"{OUT}/audit.json") else None
    res = leader.analyze(rows, ALIASES, audits, None if a.no_llm else llm.analysis_llm())
    if not res:
        raise SystemExit("No competitor mentions in this run.")
    pl = leader.per_leader(res, rows, ALIASES, audits)
    sc = discovery.scorecard(rows, ALIASES)
    mates = _teammates()
    variants = {v["name"]: v for t in mates for v in t.get("name_variants", [])}
    variants.update({v["name"]: v for v in res.get("name_variants", [])})
    cited = _load("sources_check.json") if os.path.exists(f"{OUT}/sources_check.json") else []
    for t in mates:  # teammate's checked pages count as outreach targets too
        cited += [{"url": "https://" + x["domain"], "domain": x["domain"], "cited": 1,
                   "athena": x["athena"], "competitors": x.get("competitors", [])}
                  for x in t.get("cited_sources", []) if x["athena"] is False]
    plan = action.build_plan(pl, sc, list(variants.values()), cited)
    leader.print_report(res)
    leader.print_per_leader(pl)
    _save("leader.json", res)
    _save("per_leader.json", pl)
    _save("plan.json", plan)
    _save("scorecard.json", sc)
    css_path = a.css or os.path.join(os.path.dirname(leader.__file__), "report_base.css")
    css = open(css_path).read()
    if a.css and a.css.endswith(".html"):  # take the <style> block from an existing report
        import re
        css = re.search(r"<style>(.*?)</style>", css, re.S).group(1)
    kind = next(r["kind"] for r in db.runs() if r["run_id"] == run)
    warn = "Demo data: competitor names and numbers are fake." if kind == "demo" else ""
    with open(f"{OUT}/leader_report.html", "w") as f:
        platform = ", ".join(sorted({r["platform"] for r in rows}))
        f.write(leader_html.render_page(res, css, warn, pl, plan,
                                        leader_html.render_combined(sc, platform, mates)))
    with open(f"{OUT}/leader_sections.html", "w") as f:
        f.write(leader_html.render_sections(res) + leader_html.render_per_leader(pl)
                + leader_html.render_plan(plan))
    print(f"\nWrote {OUT}/leader_report.html (standalone) and "
          f"{OUT}/leader_sections.html (paste into report.html)")
    print(f"Next: python cli.py generate   ({len(plan)} actions planned)")


def _teammates():
    """Teammates' results saved as JSON in aiso/teammate/ (e.g. the Claude report)."""
    folder = os.path.join(os.path.dirname(leader.__file__), "teammate")
    out = []
    for p in sorted(glob.glob(f"{folder}/*.json")):
        with open(p) as f:
            out.append(json.load(f))
    return out


def cmd_sources(a, db):
    run = a.run or db.latest("live")
    rows = db.results(run)
    sc = discovery.scorecard(rows, ALIASES)
    res = sources.check(rows, ALIASES, [c["name"] for c in sc.get("competitors", [])], a.limit)
    sources.print_check(res)
    _save("sources_check.json", res)
    print("\nSaved out/sources_check.json. Run `leader` again to turn missing pages into outreach.")


def cmd_consolidate(a, db):
    path = f"{OUT}/team_report.html"
    data = consolidate.build(db, ALIASES, path)
    print(f"Wrote {path}")
    print("  Gemini numbers: " + ("live database" if data["live"] else "snapshot"))
    print("  Before/after:   " + ("included" if data["sim"] else "pending (run simulate, then consolidate again)"))


def cmd_publish(a, db):
    if not a.wordpress:
        print("Approved files are in out/publish. Paste cms/*.html into your CMS, or use --wordpress.")
        return
    publish.publish_wordpress(live=a.live)


def cmd_unpublish(a, db):
    publish.unpublish_wordpress()


def cmd_trends_import(a, db):
    bank_path = f"{OUT}/query_bank.json"
    queries.load_or_build(bank_path)
    rows = trends.parse(open(a.file, encoding="utf-8-sig").read())
    kept, dropped = trends.to_questions(rows)
    if dropped:
        print(f"Skipped {len(dropped)} queries that aren't about food or drink, e.g. {dropped[:3]}")
    if not kept:
        raise SystemExit("Nothing restaurant-related in this file. Export Related queries for a "
                         "term like 'greek restaurant' or 'happy hour' instead.")
    added = trends.add_to_bank(bank_path, kept)
    if not added:
        print("No new queries; all of these are already in the bank.")
        return
    for q in added:
        print(f"  + {q['id']} [{q['category']}] {q['text']}  ({q['trends_section']} {q['trends_value']})")
    print(f"Added {len(added)} queries to {bank_path}. Runs before today did not include them, "
          "so compare trends on a run made after this import.")


def _manual_path(platform):
    return f"{OUT}/manual/{platform}.txt"


def cmd_manual_export(a, db):
    bank = queries.load_or_build(f"{OUT}/query_bank.json")
    if a.limit:
        # keep the sample balanced: take queries round-robin across categories
        by_cat = {}
        for q in bank:
            by_cat.setdefault(q["category"], []).append(q)
        picked, i = [], 0
        while len(picked) < min(a.limit, len(bank)):
            for qs in by_cat.values():
                if i < len(qs) and len(picked) < a.limit:
                    picked.append(qs[i])
            i += 1
        bank = picked
    path = _manual_path(a.platform)
    if os.path.exists(path) and not a.force:
        raise SystemExit(f"{path} already exists (it may hold your pasted answers). "
                         "Use --force to overwrite.")
    manual.export(bank, a.platform, path)
    print(f"Wrote {len(bank)} queries to {path}\nOpen it with:  open -e {path}")


def cmd_manual_import(a, db):
    path = a.file or _manual_path(a.platform)
    answers = manual.parse(path)
    if not answers:
        raise SystemExit(f"No pasted answers found in {path}.")
    bank = {q["id"]: q for q in queries.load_or_build(f"{OUT}/query_bank.json")}
    ex = llm.analysis_llm()
    run = a.into or db.new_run(a.label or f"manual-{a.platform}", kind="live")
    for qid, ans in answers.items():
        q = bank[qid]
        names = discovery.extract_restaurants(ans, ex)
        pos = discovery.target_position(names, ALIASES)
        db.add_result(run, q, a.platform, ans, names, pos)
        print(f"  {('#' + str(pos)) if pos else '-':>3}  {q['text']}  ->  {names[:4]}")
    print(f"\nImported {len(answers)} answers as run {run}")
    cmd_score(argparse.Namespace(run=run), db)


# ------------------------------------------------------------------ demo ---
DEMO_TARGET_TEXT = (  # deliberately thin placeholder, NOT the real cafeathena.com text
    "Cafe Athena. Greek and Mediterranean restaurant in Pacific Beach. Gyros, souvlaki, "
    "hummus. Located on Garnet Ave. Open daily.")
DEMO_COMPETITORS = [
    ("Competitor A Taverna", "Greek taverna in Pacific Beach. Gyros, falafel, hummus. Gluten-free "
     "and vegan menu. Romantic patio for date night."),
    ("Competitor B Mezze Bar", "Mezze and cocktails. Happy hour daily with small plates and tapas. "
     "Cheap happy hour appetizers near Mission Bay. Fun cocktail bar with real food."),
    ("Competitor C Grill", "Private room for birthday party and rehearsal dinner. Group dinner "
     "for 15 people. Catering for office lunch. Event planning."),
    ("Competitor D Cocktail Lounge", "Craft cocktail bar. First date spot, not too loud, "
     "romantic lighting."),
    ("Competitor E Bistro", "Family-friendly lunch spot. Vegetarian dinner. Local favorite."),
]


def cmd_demo(a, db):
    print("DEMO MODE: all answers and competitors below are FAKE placeholders.\n")
    provs = llm.get_providers(["mock-claude", "mock-gpt"])
    bank = queries.load_or_build(f"{OUT}/query_bank.json")
    print("Step 1  Discovery")
    run = discovery.run_discovery(db, bank, provs, None, ALIASES, "demo-baseline", kind="demo")
    sc = discovery.scorecard(db.results(run), ALIASES)
    _save("scorecard.json", sc)
    discovery.print_scorecard(sc)

    print("\nStep 2  Analysis (offline audit of placeholder text)")
    target = audit.audit_from_text(RESTAURANT["name"], DEMO_TARGET_TEXT)
    comps = [audit.audit_from_text(n, t) for n, t in DEMO_COMPETITORS]
    _save("audit.json", {"target": target, "competitors": comps})
    d = diagnose.diagnose(sc, target, comps, None)
    _save("diagnosis.json", d)
    diagnose.print_diagnosis(d)

    print("\nStep 2b Who beats Café Athena, and why")
    res = leader.analyze(db.results(run), ALIASES, {"target": target, "competitors": comps})
    pl = leader.per_leader(res, db.results(run), ALIASES, {"target": target, "competitors": comps})
    leader.print_per_leader(pl)
    plan = action.build_plan(pl, sc)
    _save("leader.json", res); _save("per_leader.json", pl); _save("plan.json", plan)

    print("\nStep 3  Action (gap-driven content, then approval gate)")
    outdir = f"{OUT}/content/demo"
    files = action.generate(RESTAURANT, plan, None, outdir, data_dir=f"{OUT}/demo-data")
    print("Generated:\n  " + "\n  ".join(files))
    approve.review(outdir, assume_yes=True)

    print("\nStep 4  Measurement (controlled RAG simulation, all generated content)")
    ex = None
    b = measure.run_simulation(db, "sim-before", bank, RESTAURANT["name"], DEMO_TARGET_TEXT,
                               DEMO_COMPETITORS, provs, ex, ALIASES)
    af = measure.run_simulation(db, "sim-after", bank, RESTAURANT["name"],
                                DEMO_TARGET_TEXT + "\n" + _content_text(outdir),
                                DEMO_COMPETITORS, provs, ex, ALIASES)
    measure.compare(db, b, af, ALIASES)
    measure.trend(db, ALIASES)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=f"{OUT}/aiso.db")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("discover")
    s.add_argument("--platforms", default="claude-web,gpt,gemini-web,perplexity")
    s.add_argument("--label", default="baseline")
    s.add_argument("--per-template", type=int, default=1)
    s = sub.add_parser("score"); s.add_argument("--run")
    sub.add_parser("audit"); sub.add_parser("diagnose"); sub.add_parser("generate")
    s = sub.add_parser("approve"); s.add_argument("--repo"); s.add_argument("--yes", action="store_true")
    s = sub.add_parser("simulate"); s.add_argument("--platforms", default="claude")
    s.add_argument("--content", help="folder of content to test (default: out/publish)")
    s.add_argument("--limit", type=int, help="only N questions, balanced across request types")
    sub.add_parser("trend"); sub.add_parser("demo")
    s = sub.add_parser("trends-import"); s.add_argument("file", help="Google Trends related-queries CSV")
    s = sub.add_parser("leader"); s.add_argument("--run")
    s.add_argument("--css", help="report.html or .css to copy styles from")
    s.add_argument("--no-llm", action="store_true", help="skip the plain-English summary")
    s = sub.add_parser("sources"); s.add_argument("--run"); s.add_argument("--limit", type=int, default=12)
    s = sub.add_parser("publish"); s.add_argument("--wordpress", action="store_true")
    s.add_argument("--live", action="store_true", help="actually create drafts (default: dry run)")
    sub.add_parser("unpublish")
    sub.add_parser("consolidate")
    s = sub.add_parser("manual-export"); s.add_argument("--platform", default="claude-chat")
    s.add_argument("--limit", type=int, help="only export N queries, balanced across categories")
    s.add_argument("--force", action="store_true")
    s = sub.add_parser("manual-import"); s.add_argument("--platform", default="claude-chat")
    s.add_argument("--file"); s.add_argument("--label")
    s.add_argument("--into", help="add answers to an existing run (e.g. your Gemini baseline)")
    a = p.parse_args()
    globals()[f"cmd_{a.cmd.replace('-', '_')}"](a, DB(a.db))


if __name__ == "__main__":
    main()
