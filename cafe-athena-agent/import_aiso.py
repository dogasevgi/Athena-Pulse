"""Bring answers collected by the aiso_agent tool into this agent.

Reads aiso_agent's out/aiso.db (live runs only; demo and simulation runs are skipped)
and writes answers/<platform>_<date>.csv in the same format as the other answer files,
so `python3 agent.py --manual answers/*.csv` analyzes everything together.

    python3 import_aiso.py ~/Downloads/aiso_agent/out/aiso.db
"""
import argparse
import csv
import datetime as dt
import json
import sqlite3
from collections import Counter
from pathlib import Path

from config import ROOT

PLATFORM = {"gemini": "gemini", "gemini-web": "gemini", "gemini-chat": "gemini", "claude": "claude",
            "claude-web": "claude", "claude-chat": "claude", "gpt": "chatgpt", "perplexity": "perplexity"}


def main(db_path, out_dir):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cols = {r[1] for r in con.execute("PRAGMA table_info(results)")}
    src = "r.sources" if "sources" in cols else "'[]'"
    rows = con.execute(
        f"SELECT r.platform, r.query, r.answer, r.restaurants, {src} AS sources, r.created_at "
        "FROM results r JOIN runs u ON r.run_id = u.run_id WHERE u.kind = 'live' ORDER BY r.created_at").fetchall()
    if not rows:
        raise SystemExit("No live answers in that database (demo and simulation runs are skipped).")
    groups = {}
    skipped = Counter()
    for r in rows:
        plat = PLATFORM.get(r["platform"])
        if not plat or r["platform"].startswith("mock"):
            skipped[r["platform"]] += 1
            continue
        groups.setdefault(plat, []).append(r)
    out_dir.mkdir(parents=True, exist_ok=True)
    for plat, rs in groups.items():
        day = dt.date.fromtimestamp(rs[0]["created_at"]).isoformat()
        path = out_dir / f"{plat}_aiso_{day}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["platform", "query", "answer", "restaurants", "sources", "date"])
            for r in rs:
                urls = [u for u in json.loads(r["sources"] or "[]") if str(u).startswith("http")]
                w.writerow([plat, r["query"], r["answer"], "; ".join(json.loads(r["restaurants"] or "[]")),
                            " ".join(urls), dt.date.fromtimestamp(r["created_at"]).isoformat()])
        print(f"Wrote {len(rs)} {plat} answers -> {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    if skipped:
        print("Skipped:", dict(skipped))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("db", help="path to aiso_agent/out/aiso.db")
    ap.add_argument("--out", default=str(ROOT / "answers"))
    a = ap.parse_args()
    main(Path(a.db).expanduser(), Path(a.out))
