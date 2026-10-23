"""Stage 2a - Scorecard. Turns raw answers into numbers an owner understands.

    python analyze.py --label baseline

Writes data/scorecard_<label>.json and appends a row to data/history.csv
(the measurement loop: re-run discover + analyze on any day and compare).
"""
import argparse
import csv
import datetime as dt
from collections import Counter, defaultdict

from config import DATA, TARGET, read_jsonl, write_json
from llm import norm


def load_rows(label):
    rows = {}
    for r in read_jsonl(DATA / "runs" / f"{label}.jsonl"):
        if "error" not in r:
            rows[(r["provider"], r["qid"], r["run"])] = r  # last success wins
    return list(rows.values())


def metrics(rows):
    if not rows:
        return {"answers": 0}
    n = len(rows)
    hit = [r for r in rows if r["mentioned"]]
    ranked = [r["position"] for r in hit if r.get("position")]
    total_value = sum(r["value"] for r in rows)
    return {
        "answers": n,
        "mention_rate": round(len(hit) / n, 3),
        "avg_rank": round(sum(ranked) / len(ranked), 2) if ranked else None,
        # Share of potential booking value where Café Athena gets recommended.
        "revenue_weighted_visibility": round(sum(r["value"] for r in hit) / total_value, 3),
        # Position-aware: #1 = 1.0, #2 = 0.5, #3 = 0.33 ... (unranked mention = 0.25)
        "rank_score": round(sum((1 / r["position"]) if r.get("position") else (0.25 if r["mentioned"] else 0)
                                for r in rows) / n, 3),
    }


def build(label):
    rows = load_rows(label)
    if not rows:
        raise SystemExit(f"No successful rows in data/runs/{label}.jsonl")

    by_provider = defaultdict(list)
    by_intent = defaultdict(list)
    by_query = defaultdict(list)
    for r in rows:
        by_provider[r["provider"]].append(r)
        by_intent[r["intent"]].append(r)
        by_query[r["qid"]].append(r)

    # Competitors: count answers that recommend each place (not counting Café Athena).
    comp_count, display = Counter(), {}
    for r in rows:
        seen = set()
        for name in r.get("restaurants", []):
            k = norm(name)
            if not k or k in seen or any(norm(a) in k for a in TARGET["aliases"]):
                continue
            seen.add(k)
            comp_count[k] += 1
            display.setdefault(k, name)
    competitors = [{"name": display[k], "answers": c, "share_of_voice": round(c / len(rows), 3)}
                   for k, c in comp_count.most_common(15)]
    target_sov = {"name": TARGET["name"], "answers": sum(r["mentioned"] for r in rows),
                  "share_of_voice": round(sum(r["mentioned"] for r in rows) / len(rows), 3)}

    # Sources the AIs lean on.
    dom_count, url_count = Counter(), Counter()
    for r in rows:
        dom_count.update(r.get("cited_domains", []))
        url_count.update({c["url"] for c in r.get("citations", [])})
    sources = [{"domain": d, "answers": c, "share": round(c / len(rows), 3)}
               for d, c in dom_count.most_common(20)]

    # Per-query view, sorted by money left on the table.
    queries = []
    for qid, rs in by_query.items():
        m = metrics(rs)
        comps = Counter(n for r in rs for n in r.get("restaurants", []) if norm(n) and
                        not any(norm(a) in norm(n) for a in TARGET["aliases"]))
        queries.append({"qid": qid, "query": rs[0]["query"], "intent": rs[0]["intent"],
                        "value": rs[0]["value"], **m,
                        "top_competitors": [n for n, _ in comps.most_common(3)]})
    queries.sort(key=lambda q: (q["mention_rate"], -q["value"]))

    # Sources cited in answers that left the restaurant out: where it needs to be listed.
    absent_dom = Counter(d for r in rows if not r["mentioned"] for d in set(r.get("cited_domains", [])))
    absent_n = sum(1 for r in rows if not r["mentioned"])

    # Which names the AIs use when they do recommend us (catches split brands).
    variants = Counter(n for r in rows for n in r.get("restaurants", [])
                       if any(norm(a) in norm(n) for a in TARGET["aliases"]))

    card = {
        "label": label,
        "target_name_variants": dict(variants),
        "sources_when_absent": [{"domain": d, "answers": c, "of": absent_n} for d, c in absent_dom.most_common(8)],
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "overall": metrics(rows),
        "by_provider": {p: metrics(rs) for p, rs in sorted(by_provider.items())},
        "by_intent": {i: {**metrics(rs), "value": rs[0]["value"]} for i, rs in sorted(by_intent.items())},
        "target": target_sov,
        "competitors": competitors,
        "sources": sources,
        "top_urls": [{"url": u, "answers": c} for u, c in url_count.most_common(40)],
        "queries": queries,
    }
    write_json(DATA / f"scorecard_{label}.json", card)

    hist = DATA / "history.csv"
    new = not hist.exists()
    with hist.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "label", "provider", "answers", "mention_rate",
                        "revenue_weighted_visibility", "avg_rank"])
        for p, m in [("all", card["overall"])] + list(card["by_provider"].items()):
            w.writerow([card["generated"], label, p, m["answers"], m["mention_rate"],
                        m["revenue_weighted_visibility"], m["avg_rank"]])
    return card


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="baseline")
    c = build(ap.parse_args().label)
    o = c["overall"]
    print(f"Answers analyzed: {o['answers']}")
    print(f"Mention rate: {o['mention_rate']:.0%} | Revenue-weighted: "
          f"{o['revenue_weighted_visibility']:.0%} | Avg rank: {o['avg_rank']}")
    print("Top competitors:", ", ".join(f"{x['name']} ({x['share_of_voice']:.0%})" for x in c["competitors"][:5]))
    print("Top sources:", ", ".join(f"{x['domain']} ({x['share']:.0%})" for x in c["sources"][:6]))
