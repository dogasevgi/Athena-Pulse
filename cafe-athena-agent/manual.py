"""Free Discovery: import answers your team collected from the free AI apps.

CSV columns: platform, query, answer, restaurants, sources, date
- platform:    claude / chatgpt / gemini / perplexity
- answer:      paste the AI's full answer
- restaurants: optional; "Name 1; Name 2" in the order recommended
               (if blank, names are read from numbered or bulleted lines)
- sources:     optional; cited URLs separated by spaces
Rows with an empty answer are skipped, so a half-filled template is fine.

    python3 manual.py answers/*.csv --label baseline
"""
import argparse
import csv
import glob
import json
from collections import Counter

from config import DATA, read_json
from queries import VALUES
from llm import domain_of, is_target, mentions_target, names_from_list, norm

PLATFORMS = {"claude": "anthropic", "anthropic": "anthropic", "chatgpt": "openai", "openai": "openai",
             "gpt": "openai", "gemini": "gemini", "google": "gemini", "perplexity": "perplexity"}


INTENT_WORDS = [  # first match wins; used for questions that aren't in queries.json
    ("catering", ["catering", "cater "]),
    ("events", ["rehearsal", "private", "party", "group", "birthday", "event", "wedding"]),
    ("happy_hour", ["happy hour", "tapas", "appetizer"]),
    ("date_night", ["date", "romantic", "anniversary", "cocktail"]),
    ("dietary", ["gluten", "vegan", "vegetarian", "dairy"]),
    ("lunch", ["lunch"]),
    ("cuisine", ["greek", "mediterranean", "gyro", "falafel", "hummus", "souvlaki"]),
]


def infer_intent(query):
    q = query.lower()
    return next((i for i, words in INTENT_WORDS if any(w in q for w in words)), "local")


def load(paths, label):
    bank = {norm(q["query"]): q for q in read_json(DATA / "queries.json", [])}
    runs, out = Counter(), []
    for path in paths:
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                answer = (row.get("answer") or "").strip()
                if not answer:
                    continue
                provider = PLATFORMS.get((row.get("platform") or "").strip().lower(),
                                         (row.get("platform") or "other").strip().lower())
                query = (row.get("query") or "").strip()
                intent = infer_intent(query)
                q = bank.get(norm(query)) or {"id": "custom-" + norm(query).replace(" ", "-")[:40],
                                               "intent": intent, "value": VALUES.get(intent, 60), "query": query}
                names = [n.strip() for n in (row.get("restaurants") or "").split(";") if n.strip()] \
                    or names_from_list(answer)
                cites = [{"url": u, "title": ""} for u in (row.get("sources") or "").split() if u.startswith("http")]
                position = next((i + 1 for i, n in enumerate(names) if is_target(n)), None)
                key = (provider, q["id"])
                out.append({"provider": provider, "qid": q["id"], "query": q["query"], "intent": q["intent"],
                            "value": q["value"], "run": runs[key], "ts": row.get("date") or "",
                            "answer": answer, "restaurants": names, "position": position,
                            "mentioned": position is not None or mentions_target(answer),
                            "citations": cites, "cited_domains": sorted({domain_of(c) for c in cites}),
                            "source": "manual"})
                runs[key] += 1
    (DATA / "runs").mkdir(exist_ok=True)
    with (DATA / "runs" / f"{label}.jsonl").open("w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--label", default="baseline")
    a = ap.parse_args()
    paths = sorted({p for pat in a.files for p in glob.glob(pat)})
    rows = load(paths, a.label)
    by = Counter(r["provider"] for r in rows)
    print(f"Imported {len(rows)} answers from {len(paths)} file(s): {dict(by)}")
    if not rows:
        raise SystemExit("No answers found. Check the CSV has an 'answer' column with text in it.")
