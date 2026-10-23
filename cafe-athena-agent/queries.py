"""Build the query bank: how real diners ask AI assistants.

`value` is a rough dollar estimate of one booking from that query (whole party).
It powers the revenue-weighted visibility score. Tune freely.

Café Athena gets a hand-written San Diego bank. Any other restaurant gets a
bank built from templates using its cuisine, neighborhood and city.
"""
from config import DATA, DEFAULT_TARGET, TARGET, write_json

VALUES = {"cuisine": 70, "dishes": 60, "happy_hour": 45, "date_night": 130, "dietary": 70,
          "local": 80, "lunch": 30, "events": 2000, "catering": 1200}

ATHENA = {
    "cuisine": [
        # Google Trends: Greek searches are citywide, not neighborhood
        "Greek restaurant San Diego",
        "Mediterranean food San Diego",
        "best Greek food in Pacific Beach",
        "best Mediterranean restaurant in San Diego",
        "authentic Greek restaurant in San Diego",
        "where can I get a really good gyro in PB",
        "best falafel near Pacific Beach San Diego",
        "Greek restaurant near Mission Bay",
        "best moussaka in San Diego",
        "good spanakopita in Pacific Beach",
    ],
    # Niche dish queries: where a specialist can beat bigger competitors.
    "dishes": [
        "best skordalia in San Diego",
        "where to get yemista in San Diego",
        "best keftedes in Pacific Beach",
        "good lentil soup Greek restaurant San Diego",
        "where to drink ouzo in San Diego",
        "best Greek desserts in Pacific Beach",
    ],
    "happy_hour": [
        # Google Trends, San Diego, past 12 months: the most-searched happy hour phrasings
        "best happy hour in San Diego",
        "happy hour near me in Pacific Beach",
        "happy hour with good food near Garnet Ave",
        "best happy hour in Pacific Beach San Diego",
        "happy hour small plates in PB that isn't just bar food",
        "where to get drinks and appetizers after work in Pacific Beach",
        "early happy hour 3pm Pacific Beach",
    ],
    "date_night": [
        "date night spot in PB with good cocktails",
        "romantic dinner in Pacific Beach that isn't too expensive",
        "unique cocktail bar in Pacific Beach San Diego",
        "first date restaurant in Pacific Beach",
        "anniversary dinner near Mission Beach San Diego",
    ],
    "dietary": [
        "Mediterranean restaurant with gluten-free options in San Diego",
        "vegan-friendly restaurants in Pacific Beach",
        "vegetarian dinner in Pacific Beach San Diego",
        "gluten free dinner in PB San Diego",
        "restaurant in Pacific Beach good for a vegan and a meat eater together",
    ],
    "local": [
        # Google Trends: the key local phrases
        "best restaurants in Pacific Beach",
        "Pacific Beach restaurants on the water",
        "where to eat in Pacific Beach San Diego",
        "best restaurants on Garnet Avenue",
        "best local restaurants in Pacific Beach that aren't touristy",
        "family friendly restaurant in Pacific Beach",
        "longest running local restaurants in Pacific Beach",
        "visiting San Diego for a weekend, where should I eat near the beach",
    ],
    "lunch": [
        "healthy lunch spot in Pacific Beach",
        "best lunch on Garnet Avenue",
        "healthy takeout in Pacific Beach San Diego",
    ],
    "events": [
        "where to host a rehearsal dinner in Pacific Beach",
        "restaurant with a private dining room in Pacific Beach San Diego",
        "restaurant for a birthday dinner for 15 people in PB",
        "group dinner for 20 people near the beach in San Diego",
        "restaurant with private event space near Mission Beach",
    ],
    "catering": [
        "Mediterranean catering in San Diego",
        "Greek catering for an office lunch in San Diego",
        "catering for a graduation party in San Diego, Mediterranean food",
        "healthy catering for a corporate event in San Diego",
    ],
}

TEMPLATES = {
    "cuisine": ["best {c} food in {n}", "best {c} restaurant in {city}", "authentic {c} restaurant in {city}",
                "top rated {c} spot near {n}", "where to get great {c} food in {n} {city}"],
    "happy_hour": ["best happy hour in {n} {city}", "happy hour with good food in {n}",
                   "where to get drinks and appetizers after work in {n}"],
    "date_night": ["date night restaurant in {n} {city}", "romantic dinner in {n} that isn't too expensive",
                   "first date restaurant in {n}"],
    "dietary": ["vegan-friendly restaurants in {n}", "gluten free dinner in {n} {city}",
                "vegetarian {c} food in {city}"],
    "local": ["where to eat in {n} {city}", "best local restaurants in {n} that aren't touristy",
              "family friendly restaurant in {n}", "visiting {city}, where should I eat near {n}"],
    "lunch": ["healthy lunch spot in {n}", "quick lunch in {n} {city}"],
    "events": ["restaurant with a private dining room in {n} {city}",
               "restaurant for a birthday dinner for 15 people in {n}",
               "where to host a rehearsal dinner in {n}"],
    "catering": ["{c} catering in {city}", "catering for an office lunch in {city}, {c} food"],
}


def build():
    if TARGET["name"] == DEFAULT_TARGET["name"]:
        bank = ATHENA
    else:
        fill = {"c": (TARGET.get("cuisine") or ["local"])[0],
                "n": TARGET.get("neighborhood") or TARGET.get("city") or "my area",
                "city": TARGET.get("city") or ""}
        bank = {i: [t.format(**fill).replace("  ", " ").strip() for t in ts] for i, ts in TEMPLATES.items()}
    queries = []
    for intent, items in bank.items():
        for i, q in enumerate(items):
            queries.append({"id": f"{intent}-{i:02d}", "intent": intent, "value": VALUES[intent], "query": q})
    write_json(DATA / "queries.json", queries)
    return queries


if __name__ == "__main__":
    qs = build()
    print(f"Wrote {len(qs)} queries for {TARGET['name']} to data/queries.json")
