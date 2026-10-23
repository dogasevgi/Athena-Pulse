"""Stage 1 - Discovery. Ask every AI platform every query, RUNS times each.

Results append to data/runs/<label>.jsonl and the script resumes where it left
off, so a crash or rate limit never costs you finished calls.

    python discover.py --label baseline
    python discover.py --label baseline --providers anthropic,perplexity --limit 10
    python discover.py --label mock --mock      # offline fake data to test the pipeline
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import random
import threading

from config import DATA, MOCK, RUNS, WORKERS, TARGET, read_json, read_jsonl
from llm import PROVIDERS, available, domain_of, extract_restaurants, is_target, mentions_target

RUNS_DIR = DATA / "runs"
RUNS_DIR.mkdir(exist_ok=True)
_lock = threading.Lock()


def mock_answer(query, provider, run):
    """Deterministic fake answers so the whole pipeline can be demoed offline."""
    rng = random.Random(f"{query}|{provider}|{run}")
    pool = ["Mock Taverna", "Sample Mezze House", "Placeholder Grill", "Demo Kitchen PB",
            "Example Oyster Bar", "Test Tapas Co"]
    names = rng.sample(pool, 4)
    if rng.random() < 0.25:
        names.insert(rng.randint(0, 3), TARGET["name"])
    domains = ["yelp.com", "sandiego.eater.com", "reddit.com", "tripadvisor.com",
               "theinfatuation.com", "sandiegomagazine.com"]
    text = "Here are some options:\n" + "\n".join(f"{i+1}. **{n}**" for i, n in enumerate(names))
    cites = [{"url": f"https://{d}/mock-guide-{rng.randint(1, 3)}", "title": d}
             for d in rng.sample(domains, 3)]
    return {"text": text, "citations": cites}, names


def run_one(q, provider, run, mock):
    rec = {"provider": provider, "qid": q["id"], "query": q["query"], "intent": q["intent"],
           "value": q["value"], "run": run, "ts": dt.datetime.now().isoformat(timespec="seconds")}
    try:
        if mock:
            ans, names = mock_answer(q["query"], provider, run)
        else:
            ans = PROVIDERS[provider][0](q["query"])
            names = extract_restaurants(ans["text"])
        position = next((i + 1 for i, n in enumerate(names) if is_target(n)), None)
        rec.update({
            "answer": ans["text"],
            "restaurants": names,
            "position": position,
            "mentioned": position is not None or mentions_target(ans["text"]),
            "citations": ans["citations"],
            "cited_domains": sorted({domain_of(c) for c in ans["citations"]}),
        })
    except Exception as e:
        rec["error"] = str(e)[:500]
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--providers", default="")
    ap.add_argument("--runs", type=int, default=RUNS)
    ap.add_argument("--limit", type=int, default=0, help="only first N queries (quick test)")
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()
    args.mock = args.mock or MOCK

    queries = read_json(DATA / "queries.json")
    if not queries:
        raise SystemExit("Run `python queries.py` first.")
    if args.limit:
        queries = queries[: args.limit]

    providers = [p for p in args.providers.split(",") if p] or (
        ["anthropic", "openai", "gemini", "perplexity"] if args.mock else available())
    if not providers:
        raise SystemExit("No API keys found. Set ANTHROPIC_API_KEY / OPENAI_API_KEY / "
                         "GEMINI_API_KEY / PERPLEXITY_API_KEY, or use --mock.")

    out = RUNS_DIR / f"{args.label}.jsonl"
    done = {(r["provider"], r["qid"], r["run"]) for r in read_jsonl(out) if "error" not in r}
    tasks = [(q, p, r) for q in queries for p in providers for r in range(args.runs)
             if (p, q["id"], r) not in done]
    print(f"{len(done)} already done, {len(tasks)} to run on {providers}")

    ok = err = 0
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as pool, out.open("a", encoding="utf-8") as f:
        futs = [pool.submit(run_one, q, p, r, args.mock) for q, p, r in tasks]
        for i, fut in enumerate(cf.as_completed(futs), 1):
            rec = fut.result()
            with _lock:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
            if "error" in rec:
                err += 1
                print(f"  ! {rec['provider']} {rec['qid']}: {rec['error'][:120]}")
            else:
                ok += 1
            if i % 20 == 0:
                print(f"  {i}/{len(tasks)}")
    print(f"Done: {ok} ok, {err} errors -> {out}")


if __name__ == "__main__":
    main()
