"""Stage 2c: explain WHY competitors win, as a prioritized list of evidence-backed gaps."""
from __future__ import annotations
import json
import statistics

WEAK_THRESHOLD = 0.30
PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}

OFFSITE_CHECKLIST = [
    "Google Business Profile: categories include Greek AND Mediterranean AND bar; attributes for "
    "happy hour, vegan/vegetarian/gluten-free options, private events; Q&A section filled in.",
    "Yelp and TripAdvisor: review count and recency vs. the top 3 rivals; owner responses; "
    "photos of happy-hour plates and cocktails.",
    "Reddit (r/sandiego, r/PacificBeach): threads where rivals are recommended and Café Athena "
    "is not. Note them; do not astroturf.",
    "Press and local blogs: 'best of Pacific Beach' or 'best happy hour San Diego' lists that "
    "cite rivals. These are outreach targets.",
]


def diagnose(sc: dict, target: dict, competitors: list[dict], llm=None) -> dict:
    gaps = []

    def add(priority, gap, evidence, fix, category=None):
        gaps.append({"priority": priority, "gap": gap, "evidence": evidence,
                     "fix": fix, "category": category})

    cats = sc.get("by_category", {})
    weak = {c: b for c, b in cats.items() if b["mention_rate"] < WEAK_THRESHOLD}
    comp_cov = lambda cat: [c["name"] for c in competitors if c["coverage"].get(cat)]

    # 1. Weak query categories, cross-checked with on-site coverage
    for cat, b in sorted(weak.items(), key=lambda kv: kv[1]["mention_rate"]):
        said = target["coverage"].get(cat, [])
        rivals = comp_cov(cat)
        ev = (f"Mentioned in {b['mention_rate']:.0%} of {b['n']} '{cat}' answers; "
              f"most-cited rival: {b['top_competitor']}.")
        if rivals:
            ev += f" Rival sites covering this topic: {', '.join(rivals)}."
        if not said:
            add("High", f"Site never talks about {cat.replace('_', ' ')}",
                ev + " Your crawled site text contains none of the relevant terms.",
                f"Publish a dedicated page + FAQ entries for {cat.replace('_', ' ')}.", cat)
        else:
            add("Medium", f"{cat.replace('_', ' ').title()} is mentioned but buried",
                ev + f" Site mentions {said[:3]} but has no dedicated, answerable content.",
                f"Create a focused landing page and FAQPage answers for {cat.replace('_', ' ')}.", cat)

    # 2. Structured data
    if not target["has_restaurant_schema"]:
        rivals = [c["name"] for c in competitors if c["has_restaurant_schema"]]
        add("High", "No Restaurant schema (JSON-LD)",
            "No Restaurant/FoodEstablishment JSON-LD found on crawled pages."
            + (f" Rivals with it: {', '.join(rivals)}." if rivals else ""),
            "Add the generated restaurant.jsonld to the site <head>.")
    if not target["has_faq_schema"]:
        add("High" if weak else "Medium", "No FAQPage schema",
            "Assistants favor direct question→answer content; none is marked up.",
            "Publish faq.html with the generated FAQPage JSON-LD.")
    if not target["has_menu_schema"]:
        add("Medium", "Menu is not machine-readable",
            "No Menu/MenuItem structured data found.",
            "Add descriptive dish copy (ingredients, diet tags) and Menu schema.")

    # 3. Content depth vs rivals
    if competitors:
        med = statistics.median(c["word_count"] for c in competitors)
        if target["word_count"] < 0.6 * med:
            add("Medium", "Thin site content vs. competitors",
                f"{target['word_count']} words crawled vs. rival median {int(med)}.",
                "Expand About, menu descriptions, and neighborhood copy.")
    if target.get("blocked_ai_crawlers"):
        add("High", "AI crawlers are blocked",
            f"robots.txt blocks: {', '.join(target['blocked_ai_crawlers'])}.",
            "Allow AI search crawlers in robots.txt (keep training crawlers blocked if preferred).")
    if target.get("price_count", 1) == 0:
        pdf = len(target.get("menu_pdf_links", []))
        add("Medium", "Menu isn't readable as text",
            f"Found 0 prices in the site's HTML text" + (f" and {pdf} PDF link(s)." if pdf else "."),
            "Publish the menu as an HTML page with dish names, descriptions, prices and V/VG/GF tags.")
    if target.get("has_llms_txt") is False:
        add("Low", "No llms.txt", "No /llms.txt file summarizing the site for AI tools.",
            "Publish the generated llms.txt at the site root.")
    if not target.get("meta_description"):
        add("Low", "Missing meta description",
            "Home page has no meta description for crawlers to summarize.",
            "Add the generated one-sentence description.")

    gaps.sort(key=lambda g: PRIORITY_ORDER[g["priority"]])

    narrative = None
    if llm is not None and not llm.is_mock:
        prompt = ("You are an AI-search consultant. Using ONLY the JSON evidence below, explain to "
                  "a restaurant owner in 5 plain sentences why competitors are recommended by AI "
                  "assistants more often. Cite the numbers. No invented facts.\n\n"
                  + json.dumps({"scorecard": {k: v for k, v in sc.items() if k != "lost_queries"},
                                "gaps": gaps}, indent=1)[:12000])
        narrative = llm.ask(prompt)
    return {"gaps": gaps, "offsite_checklist": OFFSITE_CHECKLIST, "narrative": narrative,
            "weak_categories": list(weak)}


def print_diagnosis(d: dict):
    print("\n=== Why competitors win (prioritized) ===")
    for i, g in enumerate(d["gaps"], 1):
        print(f"\n{i}. [{g['priority']}] {g['gap']}\n   Evidence: {g['evidence']}\n   Fix: {g['fix']}")
    print("\nOff-site checks (manual, ToS-safe):")
    for c in d["offsite_checklist"]:
        print(f"  - {c}")
    if d.get("narrative"):
        print("\nSummary for the owner:\n" + d["narrative"])
