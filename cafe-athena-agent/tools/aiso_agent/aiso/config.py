"""Restaurant profile. Every fact here comes from the hackathon brief.

Anything not confirmed (phone, price range, menu URL) is left as None so the
content generator never invents it. Fill these in once verified with the owner.
"""
from __future__ import annotations

RESTAURANT = {
    "name": "Café Athena",
    "aliases": ["cafe athena", "athena cafe", "cafeathena"],
    "website": "https://cafeathena.com",
    "street": "1846 Garnet Ave",
    "city": "San Diego",
    "region": "CA",
    "postal": "92109",
    "country": "US",
    "neighborhood": "Pacific Beach",
    "cuisine": ["Greek", "Mediterranean"],
    "founded": 1990,
    # (days, opens, closes) in 24h time
    "hours": [
        (["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"], "11:00", "21:00"),
        (["Friday", "Saturday"], "11:00", "21:30"),
    ],
    "happy_hour": "daily from 3 to 6 PM with tapas-style small plates",
    "dietary": ["vegan", "vegetarian", "gluten-free"],
    "bar": "full bar with Greek-mythology-themed cocktails",
    "services": ["catering", "group dining", "private events"],
    # Unverified: fill in before publishing anything.
    "phone": None,
    "price_range": None,
    "menu_url": None,
}

# Competitor websites to audit. Fill these in with the restaurants that the
# discovery step shows beating Café Athena (see `python cli.py score`).
COMPETITOR_SITES: dict[str, str] = {
    "JRDN": "https://www.t23hotel.com/jrdn",
    "JRDN at Tower23 Hotel": "https://www.t23hotel.com/jrdn",
    "The Fishery": "https://www.thefishery.com",
    "The Grass Skirt": "https://www.thegrassskirt.com",
}

# Polite crawling
USER_AGENT = "AISO-Hackathon-Audit/0.1 (NYU SPS x Pulse Foundry student project)"
CRAWL_DELAY_SECONDS = 1.5
MAX_PAGES_PER_SITE = 6

# Rough value of one booking per request type (from the teammate's Claude report).
# Assumptions: confirm with the owner. Used to rank losses by money, not just counts.
BOOKING_VALUE = {
    "events": 2000, "catering": 1200, "date_night": 130, "casual": 80,
    "cuisine": 70, "dietary": 70, "happy_hour": 45, "lunch": 30,
}
