"""Stage 3a - Generate the fixes as ready-to-use files in artifacts/.

- restaurant_schema.jsonld  built from verified facts only (no LLM)
- faq.html + faq_schema.jsonld, about.md, gbp_description.txt
- pages/*.html  locally relevant pages written to earn citations
- outreach/*.txt  pitches to cited guides that list competitors but not us
Uses an LLM when available; falls back to fact-only templates (and in MOCK mode).

    python3 generate.py --label baseline
"""
import argparse
import html
import json
import re
import shutil

from config import DATA, DEFAULT_TARGET, MOCK, OUT, ROOT, TARGET, read_json, write_json
from llm import complete, parse_json

FACT_RULE = ("Use ONLY the facts listed. If a detail would help but is not listed "
             "(prices, dish names, room capacity, phone), write [VERIFY: what to confirm]. "
             "Never invent awards, reviews, or quotes.")
NAME = TARGET["name"]
CUISINE = " and ".join(TARGET.get("cuisine") or ["local"])
PLACE = ", ".join(x for x in (TARGET.get("neighborhood"), TARGET.get("city")) if x) or "[VERIFY: location]"


def hours_text():
    out = []
    for days, o, c in TARGET.get("hours") or []:
        def fmt(t):
            h, m = [int(x) for x in t.split(":")]
            return f"{(h - 1) % 12 + 1}{':%02d' % m if m else ''} {'PM' if h >= 12 else 'AM'}"
        span = f"{days[0]}-{days[-1]}" if len(days) > 1 else days[0]
        out.append(f"{span} {fmt(o)} to {fmt(c)}")
    return "; ".join(out)


def has(*words):
    text = " ".join(TARGET.get("highlights") or []).lower()
    return any(w in text for w in words)


def restaurant_schema():
    t = TARGET
    data = {"@context": "https://schema.org", "@type": ["Restaurant"], "name": t["name"]}
    if t.get("website"):
        data["url"] = t["website"]
    if t.get("cuisine"):
        data["servesCuisine"] = t["cuisine"]
    if t.get("founded"):
        data["foundingDate"] = str(t["founded"])
    if t.get("street"):
        data["address"] = {"@type": "PostalAddress", "streetAddress": t["street"],
                           "addressLocality": t.get("city"), "addressRegion": t.get("region"),
                           "postalCode": t.get("postal"), "addressCountry": "US"}
    if t.get("hours"):
        data["openingHoursSpecification"] = [
            {"@type": "OpeningHoursSpecification", "dayOfWeek": d, "opens": o, "closes": c}
            for d, o, c in t["hours"]]
    feats = [n for n, words in (("Happy hour", ("happy hour",)), ("Full bar", ("bar",)),
                                ("Catering", ("catering",)), ("Private events", ("private",)),
                                ("Vegan options", ("vegan",)), ("Gluten-free options", ("gluten",)))
             if has(*words)]
    if "Full bar" in feats:
        data["@type"].append("BarOrPub")
    if feats:
        data["amenityFeature"] = [{"@type": "LocationFeatureSpecification", "name": f, "value": True}
                                  for f in feats]
    if t.get("highlights"):
        data["description"] = f"{t['name']} in {PLACE}. " + ". ".join(t["highlights"]) + "."
    for key, field in (("phone", "telephone"), ("email", "email")):
        if t.get(key):
            data[field] = t[key]
    if t.get("reservations_url"):
        data["acceptsReservations"] = t["reservations_url"]
    if t.get("menu"):  # verified dishes and prices -> machine-readable Menu
        diet = {"vegan": "https://schema.org/VeganDiet", "vegetarian": "https://schema.org/VegetarianDiet",
                "gluten-free": "https://schema.org/GlutenFreeDiet"}
        data["hasMenu"] = {"@type": "Menu", "url": t.get("menu_url"), "hasMenuSection": [
            {"@type": "MenuSection", "name": sec["section"], "hasMenuItem": [
                {"@type": "MenuItem", "name": n, "description": d,
                 "offers": {"@type": "Offer", "price": f"{p:.2f}", "priceCurrency": "USD"},
                 **({"suitableForDiet": [diet[x] for x in tags if x in diet]} if tags else {})}
                for n, d, p, tags in sec["items"]]} for sec in t["menu"]]}
    else:
        menu_url = t.get("menu_url") or (read_json(DATA / "site_audit.json") or {}).get("html_menu_url")
        if menu_url:
            data["hasMenu"] = menu_url
    return data


def llms_txt(pages):
    """/llms.txt: a plain-text summary at the site root that AI tools can read in one request."""
    t, site = TARGET, (TARGET.get("website") or "").rstrip("/")
    lines = [f"# {t['name']}", "", f"> {CUISINE} restaurant in {PLACE}"
             + (f", at {t['street']}" if t.get("street") else "")
             + (f", open since {t['founded']}" if t.get("founded") else "") + "."]
    if t.get("hours"):
        lines.append(f"> Hours: {hours_text()}.")
    lines += ["", "## Key facts"] + [f"- {h}" for h in t.get("highlights") or []]
    if t.get("phone"):
        lines.append(f"- Phone: {t['phone']}")
    lines += ["", "## Pages"] + [f"- [{p['title']}]({site}/{slug(p['slug'])}/)" for p in pages]
    if t.get("menu_url"):
        lines.append(f"- [Menu]({t['menu_url']})")
    return "\n".join(lines) + "\n"


VERIFIED = ROOT / "verified_content.json"  # fact-checked pages for Café Athena (see SOURCES_AND_CHECKS.md)


def faq_schema(faqs):
    return {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": f["q"],
                            "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faqs]}


def template_content():
    """Fact-only content: nothing here goes beyond TARGET."""
    hl = TARGET.get("highlights") or []
    faqs = [{"q": f"Where is {NAME}?",
             "a": f"{NAME} is at {TARGET.get('street') or '[VERIFY: address]'} in {PLACE}."}]
    if TARGET.get("hours"):
        faqs.append({"q": f"What are {NAME}'s hours?", "a": f"{NAME} is open {hours_text()}."})
    if has("happy hour"):
        faqs.append({"q": f"Does {NAME} have a happy hour?",
                     "a": next(h for h in hl if "happy hour" in h.lower()) + "."})
    if has("vegan", "gluten", "vegetarian"):
        faqs.append({"q": f"Does {NAME} have vegan, vegetarian, or gluten-free options?",
                     "a": f"Yes. {next(h for h in hl if 'vegan' in h.lower() or 'gluten' in h.lower())}. "
                          "[VERIFY: which dishes are marked GF/VG on the menu]"})
    if has("private", "group"):
        faqs.append({"q": f"Can I host a rehearsal dinner or private event at {NAME}?",
                     "a": f"Yes, {NAME} offers group dining and private events. "
                          "[VERIFY: room capacity, minimums, and how to book]"})
    if has("catering"):
        faqs.append({"q": f"Does {NAME} cater events and office lunches?",
                     "a": f"Yes, {NAME} offers catering in {TARGET.get('city') or PLACE}. "
                          "[VERIFY: minimum order, lead time, delivery area]"})
    if has("cocktail"):
        faqs.append({"q": f"What drinks does {NAME} serve?",
                     "a": next(h for h in hl if "cocktail" in h.lower()) + "."})
    if TARGET.get("founded"):
        faqs.append({"q": f"How long has {NAME} been open?",
                     "a": f"{NAME} has served {PLACE} since {TARGET['founded']}."})
    about = (f"# About {NAME}\n\n{NAME} is a {CUISINE} restaurant in {PLACE}"
             + (f", serving the neighborhood since {TARGET['founded']}" if TARGET.get("founded") else "")
             + ".\n\n" + "\n".join(f"- {h}" for h in hl)
             + "\n\n[VERIFY: add 3-5 signature dishes with one-line descriptions]\n")
    gbp = (f"{NAME}: {CUISINE} in {PLACE}. " + ". ".join(hl) + ".")[:740]

    def page(slug, title, intro, items):
        body = (f"<h1>{html.escape(title)}</h1><p>{html.escape(intro)}</p><ul>"
                + "".join(f"<li>{html.escape(i)}</li>" for i in items) + "</ul>"
                + f"<p>Find us at {html.escape(TARGET.get('street') or '')}, {html.escape(PLACE)}."
                + (f" Open {html.escape(hours_text())}." if TARGET.get("hours") else "") + "</p>")
        return {"slug": slug, "title": title, "meta_description": intro[:155], "body_html": body}
    c0 = (TARGET.get("cuisine") or ["local"])[0]
    pages = [page(f"best-{c0.lower()}-food-{(TARGET.get('neighborhood') or 'near-you').lower().replace(' ', '-')}",
                  f"{c0} food in {PLACE}", f"{NAME} serves {CUISINE} food in {PLACE}.", hl)]
    if has("private", "catering", "group"):
        pages.append(page("private-events-and-catering", f"Private events and catering at {NAME}",
                          f"Rehearsal dinners, birthdays, office lunches and group dinners in {PLACE}.",
                          [h for h in hl if any(w in h.lower() for w in ("private", "catering", "group"))]
                          + ["[VERIFY: room capacity]", "[VERIFY: group menu and price range]",
                             "[VERIFY: how far ahead to book]"]))
    if has("vegan", "gluten"):
        pages.append(page("vegan-gluten-free", f"Vegan and gluten-free {c0} food in {PLACE}",
                          f"{NAME} has vegan, vegetarian and gluten-free options.",
                          [h for h in hl if "vegan" in h.lower() or "gluten" in h.lower()]
                          + ["[VERIFY: list the GF and vegan dishes by name]"]))
    return {"about": about, "gbp_description": gbp, "faqs": faqs, "pages": pages}


def template_outreach(c):
    comps = ", ".join(c.get("competitors_present", [])[:2])
    return {"subject": f"{NAME} for your {TARGET.get('neighborhood') or ''} guide".replace("  ", " "),
            "body": (f"Hi,\n\nI'm writing from {NAME}, a {CUISINE} restaurant in {PLACE}"
                     + (f" since {TARGET['founded']}" if TARGET.get("founded") else "") + ". "
                     f"I enjoyed your piece \"{c.get('title') or c.get('final_url')}\""
                     + (f" featuring {comps}" if comps else "") + ". "
                     "If you update it, we'd love to be considered. A few facts that may help:\n- "
                     + "\n- ".join(TARGET.get("highlights") or []) +
                     "\n\nHappy to host you anytime.\n\n[VERIFY: owner name and contact]")}


CONTENT_SYSTEM = f"""You write website content for a restaurant so AI assistants
(ChatGPT, Claude, Gemini, Perplexity) can find, understand, and cite it.
Write clear, specific, factual sentences that directly answer how diners ask.
{FACT_RULE}
Return ONLY JSON:
{{"about": "150-220 word About section (markdown)",
  "gbp_description": "Google Business Profile description, max 740 characters",
  "faqs": [{{"q": "...", "a": "2-3 sentences"}}],
  "pages": [{{"slug": "kebab-case", "title": "...", "meta_description": "...",
             "body_html": "<h1>..</h1><p>..</p> semantic HTML, 300-450 words"}}]}}
Write 10-12 FAQs mirroring the losing queries, and 3 pages (one must cover private events and catering)."""

OUTREACH_SYSTEM = f"""You draft short, respectful pitch emails from a restaurant owner
to the editor of a local guide/article that recommends competitors but not them.
Under 140 words. Specific to the article. No flattery padding, no pressure,
no offers of payment. {FACT_RULE}
Return ONLY JSON: {{"subject": "...", "body": "..."}}"""


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def main(label):
    card = read_json(DATA / f"scorecard_{label}.json") or {}
    diag = read_json(DATA / "diagnosis.json") or {}
    cov = read_json(DATA / "source_coverage.json") or []
    lost = [q["query"] for q in card.get("queries", []) if q.get("mention_rate", 0) < 0.5][:25]

    content = None
    if VERIFIED.exists() and TARGET["name"] == DEFAULT_TARGET["name"] and not MOCK:
        content = read_json(VERIFIED)
        print("Using fact-checked content from verified_content.json (no [VERIFY] gaps).")
    if not MOCK and content is None:
        try:
            brief = {"facts": TARGET, "queries_we_are_losing": lost, "diagnosis": diag.get("gaps", [])}
            content = parse_json(complete(json.dumps(brief, ensure_ascii=False), system=CONTENT_SYSTEM,
                                          max_tokens=8000))
            assert content.get("faqs") and content.get("pages")
        except Exception as e:
            print("LLM content failed, using fact-only templates:", str(e)[:120])
            content = None
    content = content or template_content()

    for d in ("pages", "outreach"):  # start fresh so old drafts never mix with this run
        shutil.rmtree(OUT / d, ignore_errors=True)
        (OUT / d).mkdir(exist_ok=True)
    write_json(OUT / "restaurant_schema.jsonld", restaurant_schema())
    write_json(OUT / "faq_schema.jsonld", faq_schema(content["faqs"]))
    (OUT / "about.md").write_text(content["about"], encoding="utf-8")
    (OUT / "gbp_description.txt").write_text(content["gbp_description"], encoding="utf-8")
    (OUT / "llms.txt").write_text(llms_txt(content["pages"]), encoding="utf-8")
    faq_html = ("<section id=\"faq\">\n<h2>Frequently asked questions</h2>\n" + "\n".join(
        f"<h3>{html.escape(f['q'])}</h3>\n<p>{html.escape(f['a'])}</p>" for f in content["faqs"])
        + "\n</section>\n<script type=\"application/ld+json\">\n"
        + json.dumps(faq_schema(content["faqs"]), indent=2, ensure_ascii=False) + "\n</script>\n")
    (OUT / "faq.html").write_text(faq_html, encoding="utf-8")

    page_texts = []
    for p in content["pages"]:
        doc = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
               f"<title>{html.escape(p['title'])}</title>"
               f"<meta name=\"description\" content=\"{html.escape(p['meta_description'])}\">"
               "<script type=\"application/ld+json\">"
               + json.dumps(restaurant_schema(), ensure_ascii=False)
               + f"</script></head><body>{p['body_html']}</body></html>")
        (OUT / "pages" / f"{slug(p['slug'])}.html").write_text(doc, encoding="utf-8")
        page_texts.append(re.sub(r"<[^>]+>", " ", p["body_html"]))

    # Editorial guides get a pitch; review platforms (Yelp etc.) need a listing fix, not an email.
    platforms = ("yelp.", "tripadvisor.", "google.", "doordash.", "ubereats.", "facebook.", "opentable.", "reddit.")
    targets = [c for c in cov if c.get("status") == "ok" and not c.get("target_present")
               and c.get("competitors_present")
               and not any(p in (c.get("domain") or "") for p in platforms)][:5]
    for c in targets:
        mail = None
        if not MOCK:
            try:
                ask = {"facts": TARGET, "article_title": c.get("title"), "article_url": c.get("final_url"),
                       "competitors_listed": c.get("competitors_present")}
                mail = parse_json(complete(json.dumps(ask, ensure_ascii=False), system=OUTREACH_SYSTEM,
                                           max_tokens=800))
            except Exception as e:
                print("  LLM outreach failed, using template:", str(e)[:100])
        mail = mail or template_outreach(c)
        (OUT / "outreach" / f"{slug(c.get('domain') or 'source')}.txt").write_text(
            f"To: [VERIFY: editor contact for {c.get('domain')}]\nRe: {c.get('final_url')}\n"
            f"Subject: {mail['subject']}\n\n{mail['body']}\n", encoding="utf-8")

    before_p = DATA / "site_text_before.txt"
    before = before_p.read_text(encoding="utf-8") if before_p.exists() else ""
    new = "\n\n".join([content["about"], "\n".join(f"Q: {f['q']}\nA: {f['a']}" for f in content["faqs"]),
                       *page_texts])
    (DATA / "new_content.txt").write_text(new, encoding="utf-8")
    (DATA / "site_text_after.txt").write_text(before + "\n\n" + new, encoding="utf-8")
    verify = sum(t.count("[VERIFY") for t in [new] + [p.read_text(encoding="utf-8")
                                                      for p in (OUT / "outreach").glob("*.txt")])
    print(f"Wrote schema, {len(content['faqs'])} FAQs, {len(content['pages'])} pages, "
          f"{len(targets)} outreach drafts to artifacts/ ({verify} [VERIFY] items to confirm)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="baseline")
    main(ap.parse_args().label)
