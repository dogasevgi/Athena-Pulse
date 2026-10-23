"""Stage 1c + 2a: run the query bank against AI platforms, then score visibility."""
from __future__ import annotations
import time
from collections import Counter, defaultdict

from .config import BOOKING_VALUE
from .extract import extract_restaurants, is_target, norm, target_position


def run_discovery(db, queries, providers, extractor, aliases, label="baseline",
                  kind="live", pause=0.5):
    run_id = db.new_run(label, kind)
    total = len(queries) * len(providers)
    done = 0
    for p in providers:
        fails = 0
        for q in queries:
            done += 1
            try:
                answer = p.ask(q["text"])
                fails = 0
            except Exception as e:
                fails += 1
                print(f"  ! {p.name} failed on {q['id']}: {e}")
                if fails >= 3:
                    print(f"  ! {p.name} failed 3 times in a row; skipping the rest for this platform.")
                    break
                continue
            names = extract_restaurants(answer, extractor)
            pos = target_position(names, aliases)
            db.add_result(run_id, q, p.name, answer, names, pos, getattr(p, 'last_sources', []))
            mark = f"#{pos}" if pos else "–"
            print(f"  [{done}/{total}] {p.name:<11} {mark:>3}  {q['text']}")
            if not p.is_mock:
                time.sleep(pause if not p.name.startswith("gemini") else max(pause, 4))
    return run_id


def scorecard(rows: list[dict], aliases: list[str]) -> dict:
    if not rows:
        return {"n": 0}
    hit = [r for r in rows if r["target_pos"]]
    display = {}
    comp = Counter()
    total_mentions = 0
    for r in rows:
        total_mentions += len(r["restaurants"])
        for n in r["restaurants"]:
            if not is_target(n, aliases):
                k = norm(n)
                display.setdefault(k, n)
                comp[k] += 1

    def block(sub):
        h = [r for r in sub if r["target_pos"]]
        c = Counter(norm(n) for r in sub for n in r["restaurants"] if not is_target(n, aliases))
        top = c.most_common(1)
        val = lambda rs: sum(BOOKING_VALUE.get(r["category"], 50) for r in rs)
        return {
            "n": len(sub),
            "value_weighted": round(val(h) / val(sub), 3) if sub else 0,
            "mention_rate": round(len(h) / len(sub), 3),
            "avg_rank": round(sum(r["target_pos"] for r in h) / len(h), 2) if h else None,
            "top3_rate": round(sum(1 for r in h if r["target_pos"] <= 3) / len(sub), 3),
            "top_competitor": display.get(top[0][0]) if top else None,
        }

    by_cat, by_plat = defaultdict(list), defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
        by_plat[r["platform"]].append(r)

    lost = [{"query": r["query"], "platform": r["platform"], "category": r["category"],
             "winners": r["restaurants"][:3]} for r in rows if not r["target_pos"]]

    return {
        **block(rows),
        "share_of_voice": round(len(hit) / total_mentions, 3) if total_mentions else 0,
        "competitors": [{"name": display[k], "mentions": v,
                         "share_of_voice": round(v / total_mentions, 3)}
                        for k, v in comp.most_common(10)],
        "by_category": {k: block(v) for k, v in sorted(by_cat.items())},
        "by_platform": {k: block(v) for k, v in sorted(by_plat.items())},
        "lost_queries": lost,
    }


def print_scorecard(sc: dict, title="Visibility scorecard"):
    if not sc.get("n"):
        print("No results.")
        return
    print(f"\n=== {title} ===")
    print(f"Answers analyzed : {sc['n']}")
    print(f"Mention rate     : {sc['mention_rate']:.0%}")
    print(f"Top-3 rate       : {sc['top3_rate']:.0%}")
    print(f"Avg rank (when mentioned): {sc['avg_rank']}")
    print(f"Share of voice   : {sc['share_of_voice']:.0%}")
    print(f"Value-weighted   : {sc['value_weighted']:.0%} of potential booking value "
          "(events/catering weigh most; see BOOKING_VALUE)")
    print("\nBy category:")
    for cat, b in sc["by_category"].items():
        print(f"  {cat:<11} mention {b['mention_rate']:>4.0%}  avg rank {str(b['avg_rank']):>5}"
              f"  most-cited rival: {b['top_competitor']}")
    print("\nBy platform:")
    for plat, b in sc["by_platform"].items():
        print(f"  {plat:<11} mention {b['mention_rate']:>4.0%}  avg rank {b['avg_rank']}")
    print("\nTop competitors (share of voice):")
    for c in sc["competitors"][:6]:
        print(f"  {c['name']:<32} {c['mentions']:>3} mentions  {c['share_of_voice']:.0%}")
