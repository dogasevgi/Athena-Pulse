"""Stage 1a: build a realistic San Diego query bank.

Queries vary along intent (category), location granularity, and phrasing.
The bank is deterministic (seeded) so every re-run measures the same queries.
"""
from __future__ import annotations
import json
import random
import re

LOCATIONS = [
    "Pacific Beach", "PB", "San Diego", "near Garnet Ave",
    "near Mission Bay", "Pacific Beach San Diego",
]

TEMPLATES = {
    "cuisine": [
        "best Greek food in {loc}",
        "good Mediterranean restaurant in {loc}",
        "where can I get a good gyro in {loc}",
        "authentic Greek restaurant {loc}",
        "best falafel and hummus {loc}",
    ],
    "dietary": [
        "Mediterranean restaurant with gluten-free options in {loc}",
        "vegan-friendly restaurant {loc}",
        "good vegetarian dinner spot {loc}",
        "restaurant with gluten free menu {loc}",
    ],
    "happy_hour": [
        "happy hour with good food {loc}",
        "best happy hour small plates {loc}",
        "cheap happy hour tapas {loc}",
        "where to get happy hour appetizers and drinks {loc}",
    ],
    "date_night": [
        "date night spot in {loc} with good cocktails",
        "romantic dinner {loc}",
        "fun cocktail bar with real food {loc}",
        "first date restaurant {loc} not too loud",
    ],
    "events": [
        "where to host a rehearsal dinner in {loc}",
        "restaurant with private room for a birthday party {loc}",
        "group dinner for 15 people {loc}",
        "catering for an office lunch {loc}",
    ],
    "casual": [
        "good lunch spot {loc}",
        "where should I eat in {loc} tonight",
        "family-friendly restaurant {loc}",
        "long-running local favorite restaurant {loc}",
    ],
}

CATEGORY_KEYWORDS = {  # order matters: first match wins
    "catering": ["catering", "cater "],
    "events": ["rehearsal", "private", "party", "group", "event", "wedding"],
    "happy_hour": ["happy hour", "tapas", "appetizer"],
    "date_night": ["date", "romantic", "cocktail"],
    "dietary": ["gluten", "vegan", "vegetarian", "dairy"],
    "lunch": ["lunch"],
    "cuisine": ["greek", "mediterranean", "gyro", "falafel", "hummus", "souvlaki"],
}


def categorize(text: str) -> str:
    t = text.lower()
    for cat, words in CATEGORY_KEYWORDS.items():
        if any(w in t for w in words):
            return cat
    return "casual"


def build_query_bank(per_template: int = 1, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    bank, seen = [], set()
    for cat, templates in TEMPLATES.items():
        for tpl in templates:
            for loc in rng.sample(LOCATIONS, per_template):
                text = tpl.format(loc=loc).replace(" in near ", " near ")
                if text in seen:
                    continue
                seen.add(text)
                bank.append({"id": f"q{len(bank)+1:03d}", "text": text, "category": categorize(text)})
    return bank


def llm_expand(llm, n: int = 20) -> list[dict]:
    """Ask an LLM for extra natural-sounding queries (optional)."""
    prompt = (
        f"Write {n} different questions real people in San Diego might type or say to an AI "
        "assistant when choosing where to eat or drink in Pacific Beach. Vary occasion, budget, "
        "diet, group size and time of day. Do not name any restaurant. "
        'Respond with ONLY JSON: {"queries": ["..."]}'
    )
    txt = re.sub(r"```(json)?", "", llm.ask(prompt)).strip()
    out = []
    for i, q in enumerate(json.loads(txt)["queries"], 1):
        out.append({"id": f"x{i:03d}", "text": q, "category": categorize(q)})
    return out


def load_or_build(path: str, per_template: int = 1) -> list[dict]:
    """Freeze the bank to disk so measurement always compares like with like."""
    import os
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    bank = build_query_bank(per_template)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(bank, f, indent=2)
    return bank
