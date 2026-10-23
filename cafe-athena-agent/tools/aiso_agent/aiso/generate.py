"""Stage 3a: generate content the restaurant can actually publish.

Rule: only state facts from config.RESTAURANT. Unknowns become [TODO: ...] markers
that the human approval step forces someone to resolve.
"""
from __future__ import annotations
import json
import os
import re

PAGES = {
    "events": ("private-events-pacific-beach",
               "Private events, rehearsal dinners and group dining in Pacific Beach"),
    "happy_hour": ("happy-hour-pacific-beach", "Daily happy hour in Pacific Beach"),
    "date_night": ("date-night-cocktails-pacific-beach",
                   "Date night in Pacific Beach: Greek food and mythology-themed cocktails"),
    "dietary": ("gluten-free-vegan-mediterranean-san-diego",
                "Gluten-free, vegan and vegetarian Mediterranean food in San Diego"),
    "cuisine": ("greek-food-pacific-beach", "Greek and Mediterranean food in Pacific Beach since 1990"),
}


def _address(r):
    return f"{r['street']}, {r['city']}, {r['region']} {r['postal']}"


def _hours_text(r):
    def t(s):
        h, m = map(int, s.split(":"))
        return f"{(h - 1) % 12 + 1}:{m:02d} {'AM' if h < 12 else 'PM'}"
    return "; ".join(f"{d[0][:3]}–{d[-1][:3]} {t(o)}–{t(c)}" for d, o, c in r["hours"])


def faq_items(r) -> list[tuple[str, str]]:
    n, hood = r["name"], r["neighborhood"]
    return [
        (f"Where is {n}?",
         f"{n} is at {_address(r)}, in the {hood} neighborhood of San Diego."),
        (f"What kind of food does {n} serve?",
         f"{n} is a Greek and Mediterranean restaurant and bar that has been serving {hood} since {r['founded']}."),
        (f"What are {n}'s hours?", f"{n} is open {_hours_text(r)}."),
        (f"Does {n} have a happy hour?", f"Yes. Happy hour runs {r['happy_hour']}."),
        (f"Does {n} have gluten-free, vegan or vegetarian options?",
         f"Yes. {n} offers vegan, vegetarian and gluten-free options."),
        (f"Is {n} good for date night?",
         f"{n} has a {r['bar']}, alongside its Greek and Mediterranean menu."),
        (f"Can I host a rehearsal dinner or private event at {n}?",
         f"Yes. {n} offers private events and group dining, and also caters off-site. "
         "[TODO: add capacity, booking contact and lead time]"),
        (f"Does {n} do catering?", f"Yes. {n} offers catering. [TODO: add how to order]"),
    ]


def restaurant_schema(r, faqs) -> dict:
    restaurant = {
        "@type": ["Restaurant", "BarOrPub"],
        "@id": r["website"] + "/#restaurant",
        "name": r["name"],
        "url": r["website"],
        "servesCuisine": r["cuisine"],
        "foundingDate": str(r["founded"]),
        "address": {"@type": "PostalAddress", "streetAddress": r["street"],
                    "addressLocality": r["city"], "addressRegion": r["region"],
                    "postalCode": r["postal"], "addressCountry": r["country"]},
        "areaServed": f"{r['neighborhood']}, {r['city']}",
        "openingHoursSpecification": [
            {"@type": "OpeningHoursSpecification", "dayOfWeek": days, "opens": o, "closes": c}
            for days, o, c in r["hours"]],
        "description": (f"Greek and Mediterranean restaurant and bar in {r['neighborhood']}, "
                        f"San Diego since {r['founded']}. Happy hour {r['happy_hour']}; vegan, "
                        f"vegetarian and gluten-free options; {r['bar']}; catering, group "
                        "dining and private events."),
    }
    for key, field in (("phone", "telephone"), ("price_range", "priceRange"), ("menu_url", "hasMenu")):
        if r.get(key):
            restaurant[field] = r[key]
    faq = {"@type": "FAQPage", "@id": r["website"] + "/faq#faq",
           "mainEntity": [{"@type": "Question", "name": q,
                           "acceptedAnswer": {"@type": "Answer", "text": re.sub(r"\s*\[TODO:.*?\]", "", a)}}
                          for q, a in faqs]}
    return {"@context": "https://schema.org", "@graph": [restaurant, faq]}


def _facts(r) -> str:
    return json.dumps({k: v for k, v in r.items() if k != "aliases" and v is not None}, indent=1)


def landing_page(r, cat, llm=None) -> str:
    slug, title = PAGES[cat]
    if llm is not None and not llm.is_mock:
        prompt = (
            f"Write a 350–450 word web page in Markdown titled '{title}' for this restaurant. "
            "It must directly answer the question a diner would ask an AI assistant, in plain "
            "language, with a short 'Quick answer' paragraph first and 3 Q&A pairs at the end. "
            "Use ONLY these facts. If something useful is unknown (prices, dish names, capacity), "
            "write [TODO: ...] instead of guessing. No superlatives you cannot back up.\n\n"
            f"FACTS:\n{_facts(r)}")
        return llm.ask(prompt)
    n, hood = r["name"], r["neighborhood"]
    body = {
        "events": f"{n} hosts private events and group dining in {hood}, including rehearsal "
                  f"dinners, birthdays and work gatherings, and caters off-site. "
                  "[TODO: capacity, minimums, sample menus, how to book]",
        "happy_hour": f"Happy hour at {n} runs {r['happy_hour']}, alongside a {r['bar']}. "
                      "[TODO: 3–5 example plates and prices]",
        "date_night": f"For date night in {hood}, {n} pairs a Greek and Mediterranean menu with a "
                      f"{r['bar']}. [TODO: name 2–3 signature cocktails and describe the room]",
        "dietary": f"{n} offers vegan, vegetarian and gluten-free options across its Greek and "
                   "Mediterranean menu. [TODO: list specific dishes with diet tags]",
        "cuisine": f"{n} has served Greek and Mediterranean food in {hood} since {r['founded']}. "
                   "[TODO: describe signature dishes]",
    }[cat]
    return (f"# {title}\n\n**Quick answer:** {body}\n\n"
            f"**Where:** {_address(r)}  \n**Hours:** {_hours_text(r)}\n")


def about_copy(r, llm=None) -> str:
    if llm is not None and not llm.is_mock:
        return llm.ask("Write a 150-word 'About' section for this restaurant's website, warm but "
                       "factual, using ONLY these facts:\n" + _facts(r))
    return (f"# About {r['name']}\n\n{r['name']} has been a {r['neighborhood']} gathering place "
            f"since {r['founded']}, serving Greek and Mediterranean food at {_address(r)}. "
            f"Come for happy hour ({r['happy_hour']}), stay for the {r['bar']}. The menu "
            "includes vegan, vegetarian and gluten-free options, and the team handles catering, "
            "group dining and private events.\n")


def outreach_emails(r, top_rivals: list[str]) -> str:
    rivals = ", ".join(top_rivals[:3]) or "other local spots"
    return f"""# Outreach drafts (review before sending; fill every [TODO])

## To a local food blogger / 'best of Pacific Beach' list
Subject: A Pacific Beach Greek spot (since {r["founded"]}) for your next roundup

Hi [TODO: name],

I enjoyed your recent piece on [TODO: article]. It featured {rivals}, and I wanted to
put {r['name']} on your radar. We've been on Garnet Ave since {r['founded']}, run happy hour
{r['happy_hour']}, and pour Greek-mythology-themed cocktails. We also have
vegan, vegetarian and gluten-free options.

If you're open to it, we'd love to host you. [TODO: offer details]

[TODO: owner name], {r['name']}

## To an event or wedding planner
Subject: Rehearsal dinners and group events in Pacific Beach

Hi [TODO: name],

{r['name']} hosts private events and group dinners in Pacific Beach and caters off-site.
[TODO: capacity, minimums]. Happy to send menus for your next client.

[TODO: owner name]
"""


def generate_all(r, diagnosis: dict, sc: dict, llm, outdir: str) -> list[str]:
    os.makedirs(outdir, exist_ok=True)
    files = []

    def write(name, text):
        p = os.path.join(outdir, name)
        with open(p, "w") as f:
            f.write(text)
        files.append(p)

    faqs = faq_items(r)
    write("restaurant.jsonld", json.dumps(restaurant_schema(r, faqs), indent=2, ensure_ascii=False))
    write("faq.md", f"# Frequently asked questions\n\n" +
          "\n\n".join(f"**{q}**\n\n{a}" for q, a in faqs) + "\n")
    write("about.md", about_copy(r, llm))
    write("meta-description.txt",
          f"{r['name']}: Greek and Mediterranean restaurant and bar in {r['neighborhood']}, "
          f"San Diego since {r['founded']}. Daily happy hour 3–6 PM, gluten-free and vegan "
          "options, private events.\n")
    cats = [c for c in diagnosis.get("weak_categories", []) if c in PAGES] or ["events", "happy_hour"]
    for cat in cats:
        slug, _ = PAGES[cat]
        write(f"page-{slug}.md", landing_page(r, cat, llm))
    write("outreach-emails.md", outreach_emails(r, [c["name"] for c in sc.get("competitors", [])]))
    return files
