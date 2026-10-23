"""Shared configuration. Café Athena is the default target; `agent.py --name ...`
writes data/target.json to point the agent at any other restaurant."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).parent
# The web server sets ATHENA_HOME to a private folder per customer job so runs never mix.
HOME = Path(os.getenv("ATHENA_HOME") or ROOT)
DATA = HOME / "data"
OUT = HOME / "artifacts"
DATA.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

MOCK = os.getenv("MOCK") == "1"   # offline demo mode: fake data, no API keys

# Facts from the hackathon brief. The content generator may ONLY use these;
# anything else becomes a [VERIFY: ...] placeholder.
DEFAULT_TARGET = {
    "name": "Café Athena",
    "aliases": ["cafe athena", "café athena", "athena cafe", "athenas catering", "athena's catering"],
    "domain": "cafeathena.com",
    "website": "https://cafeathena.com/",
    "street": "1846 Garnet Ave",
    "city": "San Diego",
    "region": "CA",
    "postal": "92109",
    "neighborhood": "Pacific Beach",
    "cuisine": ["Greek", "Mediterranean"],
    "founded": 1990,
    "hours": [
        [["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"], "11:00", "21:00"],
        [["Friday", "Saturday"], "11:00", "21:30"],
    ],
    "highlights": [
        "Greek and Mediterranean restaurant and bar, open since 1990",
        "Daily happy hour 3-6 PM with tapas-style small plates",
        "Vegan, vegetarian, and gluten-free options",
        "Full bar with Greek-mythology-themed cocktails",
        "Catering, group dining, and private events",
        # Verified on cafeathena.com and its Nov 2025 catering menu (fetched 2026-10-23):
        "Happy hour is every day 3-6 PM, dine-in only: small plates from $5 and four $10 cocktails",
        "Group dining for parties of ten or more: a manager builds a custom menu and quote",
        "Hosts birthdays, wedding rehearsal dinners, and bachelor and bachelorette dinners",
        "Catering from office lunches to weddings; buffet menus $20.95 per person, 10-person minimum",
        "Reservations online and by phone at (858) 274-1140",
    ],
    # Verified contact details (cafeathena.com footer).
    "phone": "+1-858-274-1140",
    "email": "info@cafeathena.com",
    "reservations_url": "https://tables.toasttab.com/restaurants/954ad56c-1647-454e-85b1-027db07a2689/findTime",
    "menu_url": "https://cafeathena.com/bar-happy-hour-menu/",
    # Verified menu items (cafeathena.com/bar-happy-hour-menu). Used for Menu schema and pages.
    "menu": [
        {"section": "Happy hour small plates (daily 3-6 PM, dine-in)", "items": [
            ["Hummos", "chickpeas, sesame sauce, lemon juice, fresh garlic; with pita", 5, ["vegan"]],
            ["Tzatziki", "kefir cheese and cucumber spread; with pita", 5, ["vegetarian"]],
            ["Yalanji", "grape leaves filled with rice, tomatoes, mint and spices; served chilled", 5, ["vegan", "gluten-free"]],
            ["Artichoke Hearts", "marinated in lemon juice, olive oil and garlic", 5.5, ["vegan", "gluten-free"]],
            ["Spanakopita", "filo with spinach, feta, fresh basil and caramelized onion", 5.5, ["vegetarian"]],
            ["Feta Bruschetta", "feta, tomatoes, olive oil, balsamic, herbs and garlic on sourdough", 6, ["vegetarian"]],
            ["Keftedes", "baked beef meatballs with herbs and spices; scorpio sauce", 7, ["gluten-free"]],
            ["Rosemary Potatoes", "with red pepper aioli", 7, ["vegan", "gluten-free"]],
            ["Falafel & Tahini", "chickpea and fava bean patties with herbs and spices", 7.5, ["vegan", "gluten-free"]],
            ["Gyros", "gyros meat with warm pita and tzatziki", 9, []],
            ["Lemon Herb Veggies", "fire-roasted; with skordalia and pita", 9, ["vegan", "gluten-free"]],
            ["Calamari", "with red pepper aioli", 12, []],
            ["Chicken Souvlaki Skewers", "four mini skewers of char-broiled chicken tenderloin", 13, ["gluten-free"]],
            ["Souvlaki Combo", "two mini skewers each of chicken and beef", 18, ["gluten-free"]],
            ["Beef Souvlaki Skewers", "four mini skewers of char-broiled beef tenderloin", 23, ["gluten-free"]]]},
        {"section": "Zeus' Cocktails", "items": [
            ["Athena", "Tito's vodka, St-Germain elderflower, cucumber, lime, fresh mint", 15, []],
            ["Poseidon", "el Jimador tequila blanco, Cointreau, lime, agave", 14, []],
            ["Dionysus", "fig-infused Bulleit bourbon, pear liqueur, orange bitters", 15, []],
            ["Hercules", "Ilegal mezcal, tequila blanco, tamarind syrup, grapefruit, lemon", 15, []],
            ["Nike", "Empress 1908 gin, lychee liqueur, lemon, rosemary syrup, orange bitters", 15, []],
            ["Ares", "Maker's Mark bourbon, Aperol, amaro, lemon", 14, []],
            ["Hermes", "tequila blanco, Ancho Reyes Verde, lime, mango purée, jalapeño", 14, []],
            ["Nyx", "Grey Goose vodka, espresso, Mr Black, agave", 14, []],
            ["Artemis", "Kava Haven, guava purée, lemon, orange", 12, []]]},
    ],
}

# Rivals the assistants recommend most, audited side by side with the target's site
# (schema, FAQ, llms.txt, menu prices). Add more as discovery finds them.
COMPETITOR_SITES = {
    "JRDN": "https://www.t23hotel.com/jrdn",
    "The Fishery": "https://www.thefishery.com",
    "The Grass Skirt": "https://www.thegrassskirt.com",
}


def read_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def read_jsonl(path):
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


_custom = read_json(DATA / "target.json") or {}
TARGET = {**DEFAULT_TARGET, **_custom}
if _custom:  # another restaurant: never carry over Café Athena's contact details, menu or rivals
    for _k in ("phone", "email", "reservations_url", "menu_url", "menu"):
        TARGET[_k] = _custom.get(_k)
    COMPETITOR_SITES = _custom.get("competitor_sites", {})

# Model names change often; override any of these with env vars.
MODELS = {
    "anthropic": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
    "openai": os.getenv("OPENAI_MODEL", "gpt-5"),
    "gemini": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    "perplexity": os.getenv("PERPLEXITY_MODEL", "sonar"),
}
EXTRACT_MODEL = os.getenv("EXTRACT_MODEL", "claude-haiku-5-5")  # cheap parser
WRITER_MODEL = os.getenv("WRITER_MODEL", MODELS["anthropic"])   # content + diagnosis
RUNS = int(os.getenv("RUNS", "2"))          # repeats per query (answers vary)
WORKERS = int(os.getenv("WORKERS", "8"))    # parallel API calls
