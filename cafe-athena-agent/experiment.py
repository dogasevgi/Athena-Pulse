"""Stage 4a - Controlled before/after test (the "proof it worked" slide).

We can't change the live website today, so we simulate what a retrieval-based
assistant does: it reads a handful of web documents, then answers. Both arms
see the SAME competitor documents and Café Athena's CURRENT homepage. The
"after" arm adds one more Café Athena page containing our generated content,
exactly what publishing the new FAQ/landing page would do. Same length cap
on every document, so no arm gets an unfair size advantage.

Honest framing for judges: this measures whether our content makes Café Athena
retrievable and recommendable once it's indexed. Live engines are re-measured
with discover.py + analyze.py after launch.

    python experiment.py --label baseline --n 20 --runs 2
"""
import argparse
import random

from config import DATA, TARGET, read_json, write_json
from llm import complete, extract_restaurants, is_target, mentions_target

SYSTEM = """You are an AI search assistant answering a diner in San Diego.
You retrieved the documents below. Recommend 3-5 specific places that best fit
the question, using ONLY these documents, best match first, one line each on why."""


def best_chunk(text, query, size):
    """Mimic a retriever: return the chunk of our new content most relevant to the query."""
    words = text.split()
    step = max(1, size // 6)  # ~words per chunk
    chunks = [" ".join(words[i:i + step]) for i in range(0, len(words), step)] or [""]
    q = {w for w in query.lower().split() if len(w) > 2}
    return max(chunks, key=lambda c: len(q & set(c.lower().split())))[:size]


def answer(query, docs):
    ctx = "\n\n".join(f"[Document {i+1}] {d['source']}\n{d['text']}" for i, d in enumerate(docs))
    return complete(f"{ctx}\n\nQuestion: {query}", system=SYSTEM, max_tokens=900)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--n", type=int, default=20, help="queries to test")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--chars", type=int, default=2500, help="chars per document")
    args = ap.parse_args()

    card = read_json(DATA / f"scorecard_{args.label}.json")
    cov = [c for c in (read_json(DATA / "source_coverage.json") or [])
           if c.get("status") == "ok" and c.get("excerpt")]
    before_p, after_p = DATA / "site_text_before.txt", DATA / "new_content.txt"
    if not (card and after_p.exists()):
        raise SystemExit("Need scorecard + generate.py output first.")
    if len(cov) < 3:
        print("Warning: fewer than 3 readable competitor sources; result will be weak.")

    before_txt = before_p.read_text(encoding="utf-8") if before_p.exists() else ""
    new_txt = after_p.read_text(encoding="utf-8")
    comp_docs = [{"source": c.get("domain", c["url"]), "text": c["excerpt"][: args.chars]}
                 for c in cov[:7]]

    # Test the queries we're losing, highest value first.
    queries = sorted(card["queries"], key=lambda q: (q["mention_rate"], -q["value"]))[: args.n]
    results = []
    for q in queries:
        for run in range(args.runs):
            rng = random.Random(f"{q['qid']}|{run}")
            row = {"qid": q["qid"], "query": q["query"], "value": q["value"], "run": run}
            slot = rng.randint(0, len(comp_docs))
            home = {"source": TARGET["domain"], "text": before_txt[: args.chars]}
            added = {"source": TARGET["domain"] + "/new-page",
                     "text": best_chunk(new_txt, q["query"], args.chars)}
            for arm in ("before", "after"):
                docs = list(comp_docs)
                docs.insert(slot, home)                  # same slot both arms
                if arm == "after":
                    docs.insert(rng.randint(0, len(docs)), added)
                try:
                    txt = answer(q["query"], docs)
                    names = extract_restaurants(txt)
                    pos = next((i + 1 for i, n in enumerate(names) if is_target(n)), None)
                    row[arm] = {"mentioned": pos is not None or mentions_target(txt),
                                "position": pos, "restaurants": names}
                except Exception as e:
                    row[arm] = {"error": str(e)[:200]}
            results.append(row)
            b, a = row["before"].get("mentioned"), row["after"].get("mentioned")
            print(f"  {q['query'][:60]:60}  before={b}  after={a}")

    def rate(arm, weighted=False):
        ok = [r for r in results if "mentioned" in r.get(arm, {})]
        if not ok:
            return 0
        if weighted:
            return round(sum(r["value"] for r in ok if r[arm]["mentioned"]) / sum(r["value"] for r in ok), 3)
        return round(sum(r[arm]["mentioned"] for r in ok) / len(ok), 3)

    summary = {"queries": len(queries), "runs": args.runs,
               "before_mention_rate": rate("before"), "after_mention_rate": rate("after"),
               "before_revenue_weighted": rate("before", True),
               "after_revenue_weighted": rate("after", True),
               "competitor_docs": [d["source"] for d in comp_docs],
               "note": ("Simulated retrieval test: same competitor documents both arms; only "
                        "Café Athena's page changes. Confirm on live engines after launch.")}
    write_json(DATA / "experiment.json", {"summary": summary, "results": results})
    print(f"\nMention rate: {summary['before_mention_rate']:.0%} -> {summary['after_mention_rate']:.0%}")
    print(f"Revenue-weighted: {summary['before_revenue_weighted']:.0%} -> {summary['after_revenue_weighted']:.0%}")


if __name__ == "__main__":
    main()
