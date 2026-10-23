"""Add real search demand from Google Trends to the query bank.

Google Trends blocks automated access, so this reads the CSV you download by hand:
Trends > Explore > set the term, location and time range > "Related queries" panel >
download icon. Plain text files with one query per line also work.

Only food/drink/venue queries are kept, "near me" gets a Pacific Beach location (API calls
carry no user location), and each query is tagged source=google-trends with its Trends value.
"""
from __future__ import annotations

import csv
import io
import json
import re

from .queries import categorize

RELEVANT = ["restaurant", "food", "eat", "dinner", "lunch", "brunch", "happy hour", "bar", "cocktail",
            "greek", "mediterranean", "gyro", "souvlaki", "falafel", "hummus", "mezze", "tapas", "vegan",
            "vegetarian", "gluten", "catering", "private room", "rehearsal", "party", "date night",
            "drinks", "wine", "patio", "takeout", "delivery"]
LOCAL = ["pacific beach", "pb", "san diego", "garnet", "mission bay", "mission beach", "la jolla"]


def parse(text: str) -> list[dict]:
    """Return [{query, value, section}] from a Trends related-queries CSV or a plain list."""
    rows, section = [], "TOP"
    for rec in csv.reader(io.StringIO(text)):
        if not rec or not rec[0].strip():
            continue
        head = rec[0].strip()
        if head.upper() in ("TOP", "RISING"):
            section = head.upper()
            continue
        if head.lower().startswith(("category:", "query", "top queries", "rising queries")):
            continue
        value = rec[1].strip() if len(rec) > 1 else ""
        rows.append({"query": head, "value": value, "section": section})
    return rows


def to_questions(rows: list[dict]) -> tuple[list[dict], list[str]]:
    kept, dropped, seen = [], [], set()
    for r in rows:
        q = re.sub(r"\s+", " ", r["query"].lower()).strip()
        if not any(re.search(rf"\b{re.escape(w)}", q) for w in RELEVANT):
            dropped.append(r["query"])
            continue
        if "near me" in q:
            q = q.replace("near me", "in Pacific Beach, San Diego")
        elif not any(re.search(rf"\b{re.escape(l)}\b", q) for l in LOCAL):
            q += " in Pacific Beach, San Diego"
        if q in seen:
            continue
        seen.add(q)
        kept.append({"text": q, "category": categorize(q), "source": "google-trends",
                     "trends_value": r["value"], "trends_section": r["section"]})
    return kept, dropped


def add_to_bank(bank_path: str, new: list[dict]) -> list[dict]:
    with open(bank_path) as f:
        bank = json.load(f)
    have = {q["text"].lower() for q in bank}
    start = sum(1 for q in bank if q["id"].startswith("t"))
    added = []
    for q in new:
        if q["text"].lower() in have:
            continue
        start += 1
        q = {"id": f"t{start:03d}", **q}
        bank.append(q)
        added.append(q)
    with open(bank_path, "w") as f:
        json.dump(bank, f, indent=2)
    return added
