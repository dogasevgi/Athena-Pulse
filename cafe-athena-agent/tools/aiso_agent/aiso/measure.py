"""Stage 4: prove it worked.

Two complementary measurements:

1. Live tracking: re-run the frozen query bank against real assistants on a schedule
   (`python cli.py discover`), then `trend` compares every run. This is the real proof,
   but it lags because assistants need to re-crawl the site.

2. Same-day simulation: a RAG-style test. Each query is answered by a model that sees
   ONLY a fixed set of "web results": the competitors' page text plus Café Athena's
   page text, first as it is now (before), then with the approved content added (after).
   Everything else is held constant, so a lift isolates the effect of our content.
   It is a controlled estimate, not a guarantee of live results. Say so in the demo.
"""
from __future__ import annotations
import random
import re

from .discovery import scorecard
import time

from .extract import extract_restaurants, heuristic_extract, target_position

SYSTEM = ("You are an AI assistant that answers using web search results. Use ONLY the results "
          "provided. Recommend specific places by name, best match first, and say why briefly.")
DOC_CHARS = 5000


def _strip_md(text):
    text = re.sub(r"\[TODO:.*?\]", "", text)
    return re.sub(r"[#*_`>]", "", text)


def build_prompt(query, docs, seed):
    docs = docs[:]
    random.Random(seed).shuffle(docs)  # position bias is randomized but identical before/after
    body = "\n".join(f'<doc name="{n}">{t[:DOC_CHARS]}</doc>' for n, t in docs)
    return f"<web_results>\n{body}\n</web_results>\n<question>{query}</question>"


def balanced_sample(queries, limit):
    """Pick `limit` queries round-robin across categories, so every request type is covered."""
    if not limit or limit >= len(queries):
        return queries
    by_cat = {}
    for q in queries:
        by_cat.setdefault(q["category"], []).append(q)
    picked, i = [], 0
    while len(picked) < limit:
        for qs in by_cat.values():
            if i < len(qs) and len(picked) < limit:
                picked.append(qs[i])
        i += 1
    return picked


def run_simulation(db, label, queries, target_name, target_text, competitor_docs,
                   providers, extractor, aliases):
    run_id = db.new_run(label, kind="sim")
    docs = [(target_name, _strip_md(target_text))] + competitor_docs
    total = len(queries) * len(providers)
    done = 0
    for p in providers:
        for q in queries:
            done += 1
            try:
                ans = p.ask(build_prompt(q["text"], docs, seed=q["id"]), SYSTEM)
            except Exception as e:
                print(f"  ! {label} {p.name} {q['id']}: {e}")
                continue
            # answers here list names in bold; only ask the LLM to extract if that fails
            names = heuristic_extract(ans) or extract_restaurants(ans, extractor)
            pos = target_position(names, aliases)
            db.add_result(run_id, q, p.name, ans, names, pos)
            print(f"  [{label} {done}/{total}] {('#' + str(pos)) if pos else '-':>3}  {q['text']}")
            if not p.is_mock:
                time.sleep(4)
    return run_id


def compare(db, before_id, after_id, aliases):
    b = scorecard(db.results(before_id), aliases)
    a = scorecard(db.results(after_id), aliases)
    print(f"\n=== Before vs after ({before_id} -> {after_id}) ===")
    print(f"{'':<14}{'before':>8}{'after':>8}{'change':>9}")
    for k in ("mention_rate", "top3_rate", "share_of_voice"):
        print(f"{k:<14}{b[k]:>8.0%}{a[k]:>8.0%}{a[k]-b[k]:>+9.0%}")
    print("\nBy category (mention rate):")
    for cat in b["by_category"]:
        x = b["by_category"][cat]["mention_rate"]
        y = a["by_category"].get(cat, {}).get("mention_rate", 0)
        print(f"  {cat:<12}{x:>6.0%} -> {y:>4.0%}  ({y-x:+.0%})")
    return b, a


def trend(db, aliases, kind=None):
    rows = []
    for r in db.runs(kind):
        sc = scorecard(db.results(r["run_id"]), aliases)
        if sc.get("n"):
            rows.append({"run_id": r["run_id"], "label": r["label"], "kind": r["kind"],
                         "n": sc["n"], "mention_rate": sc["mention_rate"],
                         "top3_rate": sc["top3_rate"], "avg_rank": sc["avg_rank"],
                         "share_of_voice": sc["share_of_voice"]})
    print(f"\n{'run':<24}{'label':<16}{'kind':<6}{'n':>4}{'mention':>9}{'top3':>7}{'SoV':>6}")
    for x in rows:
        print(f"{x['run_id']:<24}{x['label']:<16}{x['kind']:<6}{x['n']:>4}"
              f"{x['mention_rate']:>9.0%}{x['top3_rate']:>7.0%}{x['share_of_voice']:>6.0%}")
    return rows
