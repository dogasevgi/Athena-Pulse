"""Stage 3: close the gap.

build_plan()  turns each per-leader difference into a concrete action with its evidence.
generate()    writes the content those actions need:

  about.md                     About copy, leaning on the themes leaders win on
  menu.md                      menu descriptions (from data/menu.json, owner-supplied)
  faq.md                       FAQ, including questions for every losing category
  page-*.md                    local landing pages, e.g. "Mediterranean food in Pacific Beach"
  restaurant.jsonld            Restaurant + Menu + FAQPage + Review schema
  (cms/*.html is built from each page when it is approved; see approve.py)
  outreach-*.md                emails to the sites that cite leaders but not Café Athena
  review-request.md            a compliant way to earn more reviews
  action_plan.md               every action, why it exists, and which file delivers it

Facts come only from config.RESTAURANT, data/menu.json and data/reviews.json.
Unknowns become [TODO] markers, which the approval step refuses to publish.
"""
from __future__ import annotations

import html
import json
import os
import re

from .generate import PAGES, _address, _facts, _hours_text, faq_items, restaurant_schema

# theme -> (landing page, what to write, extra deliverables)
PLAYBOOK = {
    "happy hour and value": ("happy_hour", "Spell out happy hour: days, times, and named plates with prices.",
                             ["menu"]),
    "cocktails and bar": ("date_night", "Name the Greek-mythology cocktails and describe each one.", ["menu"]),
    "atmosphere, patio or views": ("date_night", "Describe the room and seating in concrete terms, with photos.",
                                   ["about"]),
    "private events and groups": ("events", "Publish capacity, minimums, sample menus and how to book.", []),
    "dietary options": ("dietary", "Tag each dish vegan, vegetarian or gluten-free, in text and schema.",
                        ["menu"]),
    "reviews and reputation": (None, "Show real reviews and ask happy guests for Google reviews.",
                               ["reviews"]),
    "authentic food": ("cuisine", "Describe signature dishes: ingredients, preparation, family history.",
                       ["menu", "about"]),
    "longevity": ("cuisine", "Lead with 'serving Pacific Beach since 1990' everywhere.", ["about"]),
    "location and convenience": ("cuisine", "Answer 'near me' questions: neighborhood, landmarks, parking.",
                                 []),
}
SITE_TOPIC_TO_PAGE = {"cuisine": "cuisine", "dietary": "dietary", "happy_hour": "happy_hour",
                      "date_night": "date_night", "events": "events", "location": "cuisine"}
CAT_NAMES = {"cuisine": "Greek and Mediterranean food", "dietary": "vegan and gluten-free",
             "happy_hour": "happy hour", "date_night": "date night", "events": "private event",
             "casual": "general dining"}
DIET_SCHEMA = {"vegan": "https://schema.org/VeganDiet", "vegetarian": "https://schema.org/VegetarianDiet",
               "gluten-free": "https://schema.org/GlutenFreeDiet"}

MENU_TEMPLATE = {
    "_instructions": "Fill in real dishes. Remove this template entry. Prices as numbers in USD.",
    "sections": [{"name": "Happy hour small plates", "items": [
        {"name": "[TODO: dish name]", "ingredients": "[TODO]", "price": None,
         "diets": ["vegetarian"], "notes": "[TODO: anything special, e.g. family recipe]"}]}],
}
REVIEWS_TEMPLATE = [{
    "_instructions": "Only real reviews or press quotes, with permission to republish. "
                     "Set permission to true once you have it.",
    "author": "[TODO]", "rating": 5, "text": "[TODO: exact quote]", "source": "[TODO: URL]",
    "date": "2026-01-01", "permission": False}]


# ------------------------------------------------------------------ plan ---
def build_plan(per_leader: list[dict], scorecard: dict, variants: list | None = None,
               cited_pages: list | None = None) -> list[dict]:
    actions: dict[str, dict] = {}

    def add(key, title, why, deliver, weight, basis="value"):
        a = actions.setdefault(key, {"id": key, "title": title, "why": [], "deliver": set(), "weight": 0,
                                     "basis": basis})
        a["why"].append(why)
        a["deliver"].update(deliver)
        a["weight"] += weight

    for p in per_leader:
        L, w = p["leader"], p.get("lost_value", p["lost_to_leader"])
        for d in p["said_gaps"]:
            page, what, extra = PLAYBOOK[d["theme"]]
            deliver = ([f"page:{page}"] if page else []) + extra + ["faq"]
            add(f"theme:{d['theme']}", what,
                f"Assistants praise {L} for {d['theme']} in {d['leader']:.0%} of mentions vs "
                f"{d['athena']:.0%} for Café Athena.", deliver, w)
        for s in p["source_gaps"]:
            add(f"source:{s['domain']}", f"Get Café Athena covered on {s['domain']}.",
                f"{s['domain']} is cited in {s['leader_answers']:.0%} of answers naming {L} vs "
                f"{s['athena_answers']:.0%} naming Café Athena.", ["outreach"], w)
        for r in p["site_gaps"]:
            topic = r["topic"]
            if topic in SITE_TOPIC_TO_PAGE:
                add(f"site:{topic}", f"Add a page that covers {topic.replace('_', ' ')}.",
                    f"{L}'s website covers {topic.replace('_', ' ')}; Café Athena's doesn't.",
                    [f"page:{SITE_TOPIC_TO_PAGE[topic]}", "faq"], w)
            else:
                add("schema", "Add structured data (Restaurant, Menu, FAQPage).",
                    f"{L}'s site has {topic}; Café Athena's doesn't.", ["schema"], w)
        for cat in p["wins"]:
            if cat in PAGES:
                label = CAT_NAMES.get(cat, cat)
                add(f"category:{cat}", f"Answer {label} questions directly, in their own words.",
                    f"{L} leads {label} answers by {p['gap_pts']:.0f} pts.",
                    [f"page:{cat}", "faq"], w)
    for v in variants or []:
        add(f"name:{v['name']}", f"Confirm whether \"{v['name']}\" is Café Athena, and if so connect the names.",
            f"Assistants recommended \"{v['name']}\" {v['count']}x without linking it to Café Athena.",
            ["entity"], 500 * v["count"], basis="priority")
    for c in cited_pages or []:
        if c["athena"] is False and c["competitors"]:
            dom = c["domain"]
            add(f"source:{dom}", f"Get Café Athena added to {dom}.",
                f"{c['url']} is cited by assistants and lists {', '.join(c['competitors'][:3])}, "
                "but not Café Athena.", ["outreach"], 300 * c["cited"], basis="priority")
    add("schema", "Add structured data (Restaurant, Menu, FAQPage) and llms.txt.",
        "Machine-readable facts are the easiest thing for assistants to quote.", ["schema"], 0)
    out = sorted(actions.values(), key=lambda a: -a["weight"])
    for a in out:
        a["deliver"] = sorted(a["deliver"])
    return out


# ----------------------------------------------------------------- inputs ---
def _load_or_template(path, template):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f), False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(template, f, indent=2)
    return None, True


def _real_menu(menu):
    if not menu:
        return []
    return [s for s in menu.get("sections", [])
            if any(i.get("name") and "[TODO" not in i["name"] for i in s.get("items", []))]


def _real_reviews(reviews):
    return [r for r in (reviews or []) if r.get("permission") is True and "[TODO" not in r.get("text", "")]


# ----------------------------------------------------------------- writers --
def _emphasis(plan):
    return [a["id"].split(":", 1)[1] for a in plan if a["id"].startswith("theme:")]


def about(r, plan, llm):
    themes = _emphasis(plan)
    if llm is not None and not llm.is_mock:
        return llm.ask(
            "Write a 150–200 word 'About' section for this restaurant's website. AI assistants currently "
            f"describe competitors in terms of: {', '.join(themes) or 'n/a'}. Where the FACTS support "
            "those themes for this restaurant, say so concretely; where they don't, write [TODO: ...] "
            "asking the owner for the detail. No competitor names, no unverifiable superlatives.\n\n"
            f"FACTS:\n{_facts(r)}")
    todo = ""
    if "atmosphere, patio or views" in themes:
        todo += " [TODO: describe the dining room, bar and any outdoor seating in one or two sentences]"
    if "authentic food" in themes:
        todo += " [TODO: name two signature dishes and where the recipes come from]"
    return (f"# About {r['name']}\n\n{r['name']} has served Greek and Mediterranean food in "
            f"{r['neighborhood']} since {r['founded']}, at {_address(r)}.{todo}\n\n"
            f"Happy hour runs {r['happy_hour']}. The {r['bar']} pours alongside a menu with vegan, "
            "vegetarian and gluten-free options, and the team handles catering, group dining and "
            "private events.\n")


def menu_markdown(r, sections, llm):
    if not sections:
        return ("# Menu\n\n[TODO: fill in data/menu.json with real dishes, then run `generate` again. "
                "Descriptions and Menu schema are built from it.]\n")
    out = ["# Menu\n"]
    for s in sections:
        out.append(f"## {s['name']}\n")
        for i in s["items"]:
            diets = ", ".join(i.get("diets") or [])
            base = f"{i['name']}: {i.get('ingredients', '')}. {i.get('notes', '')}".strip()
            if llm is not None and not llm.is_mock:
                desc = llm.ask("Rewrite as one appetizing, plain menu description of 15–30 words. Use ONLY "
                               f"these details, no invented ingredients:\n{base}").strip()
            else:
                parts = [x.strip() for x in (i.get("ingredients"), i.get("notes")) if x and x.strip()]
                desc = ". ".join(p[0].upper() + p[1:] for p in parts) + "."
            price = f" (${i['price']:.0f})" if isinstance(i.get("price"), (int, float)) else ""
            out.append(f"**{i['name']}**{price}{' · ' + diets if diets else ''}\n\n{desc}\n")
    return "\n".join(out)


def menu_schema(r, sections):
    def item(i):
        d = {"@type": "MenuItem", "name": i["name"], "description": i.get("ingredients")}
        if isinstance(i.get("price"), (int, float)):
            d["offers"] = {"@type": "Offer", "price": f"{i['price']:.2f}", "priceCurrency": "USD"}
        diets = [DIET_SCHEMA[x] for x in i.get("diets") or [] if x in DIET_SCHEMA]
        if diets:
            d["suitableForDiet"] = diets
        return d
    return {"@type": "Menu", "@id": r["website"] + "/menu#menu", "name": f"{r['name']} menu",
            "hasMenuSection": [{"@type": "MenuSection", "name": s["name"],
                                "hasMenuItem": [item(i) for i in s["items"]]} for s in sections]}


def review_schema(reviews):
    return [{"@type": "Review", "author": {"@type": "Person", "name": x["author"]},
             "reviewRating": {"@type": "Rating", "ratingValue": x["rating"], "bestRating": 5},
             "reviewBody": x["text"], "datePublished": x.get("date"), "url": x.get("source")}
            for x in reviews]


def full_schema(r, faqs, sections, reviews):
    # leave out FAQs whose answer is still only a TODO
    faqs = [(q, a) for q, a in faqs if re.sub(r"\[TODO:.*?\]", "", a).strip()]
    s = restaurant_schema(r, faqs)
    rest = s["@graph"][0]
    if sections:
        rest["hasMenu"] = {"@id": r["website"] + "/menu#menu"}
        s["@graph"].append(menu_schema(r, sections))
    if reviews:
        rest["review"] = review_schema(reviews)
    return s


LANDING_H2 = {
    "cuisine": "Looking for the best Mediterranean food in Pacific Beach?",
    "happy_hour": "Where's a good happy hour with real food in Pacific Beach?",
    "date_night": "Where should we go for date night in PB?",
    "dietary": "Where can I eat gluten-free or vegan Mediterranean food in San Diego?",
    "events": "Where can I host a rehearsal dinner or private party in Pacific Beach?",
}


def landing(r, cat, plan, llm):
    _, title = PAGES[cat]
    reasons = [w for a in plan if f"page:{cat}" in a["deliver"] for w in a["why"]][:4]
    if llm is not None and not llm.is_mock:
        return llm.ask(
            f"Write a 400–500 word web page in Markdown. H1: '{title}'. First H2, verbatim: "
            f"'{LANDING_H2[cat]}', followed by a 2–3 sentence direct answer an AI assistant could quote. "
            "Then sections with specifics, then 3 Q&A pairs. Context (do not mention competitors): AI "
            f"assistants currently favor other restaurants because: {reasons}. Address those themes "
            "using ONLY the facts below; where a fact is missing write [TODO: ...]. No unverifiable "
            f"superlatives.\n\nFACTS:\n{_facts(r)}")
    n, hood = r["name"], r["neighborhood"]
    answer = {
        "cuisine": f"{n} has served Greek and Mediterranean food in {hood} since {r['founded']}, on "
                   f"Garnet Ave. [TODO: name 3 signature dishes]",
        "happy_hour": f"{n} runs happy hour {r['happy_hour']}, alongside a {r['bar']}. "
                      "[TODO: 3–5 plates and prices]",
        "date_night": f"{n} pairs a Greek and Mediterranean menu with a {r['bar']}. "
                      "[TODO: name 2–3 cocktails; describe the room]",
        "dietary": f"{n} offers vegan, vegetarian and gluten-free options across its Greek and "
                   "Mediterranean menu. [TODO: list dishes with diet tags]",
        "events": f"{n} hosts private events and group dining in {hood}, and caters off-site. "
                  "[TODO: capacity, minimums, sample menus, how to book]",
    }[cat]
    return (f"# {title}\n\n## {LANDING_H2[cat]}\n\n{answer}\n\n"
            f"**Where:** {_address(r)}  \n**Hours:** {_hours_text(r)}\n")


def gap_faqs(r, plan):
    """Extra FAQs for each losing category, answered only with known facts."""
    n = r["name"]
    extra = {
        "page:happy_hour": (f"What's on the happy hour menu at {n}?",
                            f"Happy hour runs {r['happy_hour']}. [TODO: list plates and prices]"),
        "page:date_night": (f"What cocktails does {n} serve?",
                            f"{n} has a {r['bar']}. [TODO: name signature cocktails]"),
        "page:events": (f"How many guests can {n} host for a private event?",
                        "[TODO: seated and standing capacity, minimums]"),
        "page:dietary": (f"Which dishes at {n} are gluten-free?", "[TODO: list gluten-free dishes]"),
    }
    wanted = {d for a in plan for d in a["deliver"]}
    return [qa for key, qa in extra.items() if key in wanted]


def outreach(r, plan):
    out = {}
    for a in plan:
        if not a["id"].startswith("source:"):
            continue
        domain = a["id"].split(":", 1)[1]
        out[domain] = f"""# Outreach to {domain}

Why: {' '.join(a['why'])}

To: [TODO: editor or writer at {domain}]
Subject: {r['name']}: a Pacific Beach Greek restaurant since {r['founded']}

Hi [TODO: name],

I read [TODO: the specific article on {domain}]. I'd like to put {r['name']} on your radar for
future Pacific Beach coverage. We've been on Garnet Ave since {r['founded']}, run happy hour
{r['happy_hour']}, have a {r['bar']}, and offer vegan, vegetarian and gluten-free options.
We also host private events and rehearsal dinners.

If it's useful, I'm happy to host you or send photos and menus. [TODO: offer details]

[TODO: owner name]
{r['name']}, {_address(r)}
"""
    return out


REVIEW_REQUEST = """# Earning more reviews (policy-safe)

Google allows asking customers for reviews but not offering anything in return. Yelp asks
businesses not to solicit reviews at all, so this is for Google only.

Table card / receipt line:
  "Enjoyed your meal? A Google review helps neighbors find us. [TODO: short link or QR code]"

Never: offer discounts for reviews, write reviews yourself, or ask only happy guests via a filter.
"""


def llms_txt(r, pages):
    """llms.txt: a plain summary at the site root for AI tools. URLs must match the published pages."""
    links = "\n".join(f"- [{PAGES[c][1]}]({r['website']}/{PAGES[c][0]}/)" for c in pages)
    return (f"# {r['name']}\n\n> Greek and Mediterranean restaurant and bar at {_address(r)} "
            f"({r['neighborhood']}, San Diego), open since {r['founded']}. Hours: {_hours_text(r)}. "
            f"Happy hour {r['happy_hour']}. Vegan, vegetarian and gluten-free options. {r['bar'][0].upper() + r['bar'][1:]}. "
            "Catering, group dining and private events.\n\n## Pages\n"
            f"- [Menu]({r.get('menu_url') or r['website'] + '/menu/'})\n- [FAQ]({r['website']}/faq/)\n"
            f"{links}\n")


def gbp_description(r):
    """Google Business Profile description: under 750 characters, no links or promotions."""
    t = (f"{r['name']} has served Greek and Mediterranean food in {r['neighborhood']} since {r['founded']}. "
         f"Happy hour runs {r['happy_hour']}, and we have a {r['bar']}. "
         "The menu includes vegan, vegetarian and gluten-free options. We host rehearsal dinners, "
         "birthdays and group dinners, and cater events across San Diego.")
    assert len(t) <= 750
    return t + "\n"


# --------------------------------------------------------------- md -> html -
def md_to_html(md: str) -> str:
    out, para, in_list = [], [], False

    def inline(t):
        t = html.escape(t, quote=False)
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)

    def flush():
        nonlocal para
        if para:
            out.append("<p>" + " ".join(inline(x) for x in para) + "</p>")
            para = []

    for line in md.splitlines():
        s = line.strip()
        if s.startswith(("- ", "* ")):
            flush()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(s[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.endswith("  ") and s:
            s += "\x00"  # markdown hard line break
        m = re.match(r"(#{1,3}) (.*)", s)
        if m:
            flush()
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
        elif not s:
            flush()
        else:
            para.append(s)
    flush()
    if in_list:
        out.append("</ul>")
    return "\n".join(out).replace("\x00", "<br>")


# ----------------------------------------------------------------- main ----
def generate(r, plan: list[dict], llm, outdir: str, data_dir: str = "data") -> list[str]:
    os.makedirs(outdir, exist_ok=True)
    files = []

    def write(name, text):
        p = os.path.join(outdir, name)
        with open(p, "w") as f:
            f.write(text)
        files.append(p)

    menu, made_menu = _load_or_template(f"{data_dir}/menu.json", MENU_TEMPLATE)
    reviews, made_rev = _load_or_template(f"{data_dir}/reviews.json", REVIEWS_TEMPLATE)
    sections, real_reviews = _real_menu(menu), _real_reviews(reviews)

    faqs = faq_items(r) + gap_faqs(r, plan)
    write("about.md", about(r, plan, llm))
    write("menu.md", menu_markdown(r, sections, llm))
    write("faq.md", "# Frequently asked questions\n\n" +
          "\n\n".join(f"**{q}**\n\n{a}" for q, a in faqs) + "\n")
    pages = sorted({d.split(":")[1] for a in plan for d in a["deliver"] if d.startswith("page:")})
    for cat in pages or ["cuisine", "events"]:
        write(f"page-{PAGES[cat][0]}.md", landing(r, cat, plan, llm))
    write("restaurant.jsonld", json.dumps(full_schema(r, faqs, sections, real_reviews),
                                          indent=2, ensure_ascii=False))
    for domain, text in outreach(r, plan).items():
        write(f"outreach-{re.sub(r'[^a-z0-9]+', '-', domain)}.md", text)
    if any("reviews" in a["deliver"] for a in plan):
        write("review-request.md", REVIEW_REQUEST)
    write("llms.txt", llms_txt(r, pages or ["cuisine", "events"]))
    write("gbp_description.txt", gbp_description(r))
    ents = [a for a in plan if a["id"].startswith("name:")]
    if ents:
        write("name-variants.md", "# Name variants (owner must confirm)\n\n" + "\n".join(
            f"- {a['why'][0]}\n  If it IS Café Athena: call it 'Café Athena Catering' everywhere, list it "
            "in schema as part of the restaurant, and link every catering listing to cafeathena.com.\n"
            "  If it is NOT: do nothing; it's a different business." for a in ents) + "\n")

    notes = []
    if not sections:
        notes.append(f"Menu: fill in {data_dir}/menu.json" + (" (template created)" if made_menu else "")
                     + " to get menu descriptions and Menu schema.")
    if not real_reviews:
        notes.append(f"Reviews: add real reviews with permission to {data_dir}/reviews.json"
                     + (" (template created)" if made_rev else "") + ". Review schema is skipped until then. "
                     "Search engines ignore reviews a business marks up about itself for star ratings, "
                     "but the text is still readable by AI crawlers.")
    lines = ["# Action plan\n", "Highest impact first. Impact = rough booking value ($) of the answers that "
             "named the leaders behind this action and left out Café Athena (see BOOKING_VALUE; an answer "
             "can count toward more than one leader).\n"]
    for i, a in enumerate(plan, 1):
        tag = f"impact: ~${a['weight']:,}" if a.get("basis", "value") == "value" else "from cited sources / names"
        lines.append(f"## {i}. {a['title']}  ({tag})\n")
        lines += [f"- Why: {w}" for w in a["why"]]
        lines.append(f"- Delivered by: {', '.join(a['deliver'])}\n")
    if notes:
        lines.append("## Needs owner input\n")
        lines += [f"- {n}" for n in notes]
    write("action_plan.md", "\n".join(lines) + "\n")
    return files
