"""Stage 2c - Diagnosis. Turn the scorecard + evidence into prioritized gaps.

Every gap cites a number, URL or audit finding. Uses an LLM when available and
falls back to transparent rules (also used in MOCK mode), so it never fails.

    python3 diagnose.py --label baseline
"""
import argparse
import json

from config import DATA, MOCK, TARGET, read_json, write_json
from llm import complete, norm, parse_json

SYSTEM = """You are an AI-search-optimization analyst for a restaurant owner.
Use ONLY the evidence provided. Every gap must quote a specific number, query,
URL, or audit finding from the evidence. Never invent facts about the restaurant
or competitors. If evidence is thin, say so in the evidence field.

Return ONLY JSON:
{"headline": "one sentence an owner would understand",
 "gaps": [{"title": "...", "evidence": "...", "why_it_matters": "...",
           "fix": "specific change", "impact": "high|medium|low",
           "effort": "low|medium|high", "agent_can_do": true|false}]}
Return 5-8 gaps ordered by impact on revenue (weight event/catering queries heavily)."""


def pct(x):
    return f"{(x or 0) * 100:.0f}%"


def evidence(label):
    card = read_json(DATA / f"scorecard_{label}.json") or {}
    audit = read_json(DATA / "site_audit.json") or {}
    cov = read_json(DATA / "source_coverage.json") or []
    slim_cov = [{k: c.get(k) for k in ("url", "domain", "title", "status", "cited_in_answers",
                                        "target_present", "competitors_present")} for c in cov]
    return {
        "restaurant": {k: TARGET.get(k) for k in ("name", "website", "neighborhood", "cuisine",
                                                   "founded", "highlights")},
        "overall": card.get("overall"),
        "by_provider": card.get("by_provider"),
        "by_intent": card.get("by_intent"),
        "competitors": card.get("competitors", [])[:10],
        "cited_sources": card.get("sources", [])[:12],
        "worst_queries": card.get("queries", [])[:15],
        "site_audit": {k: v for k, v in audit.items() if k != "jsonld_blocks"},
        "source_coverage": slim_cov,
        "name_variants": card.get("target_name_variants", {}),
        "sources_when_absent": card.get("sources_when_absent", []),
        "consistency": (read_json(DATA / "consistency.json") or {}).get("issues", []),
    }


def rule_based(ev):
    """Deterministic diagnosis straight from the numbers."""
    name, o = ev["restaurant"]["name"], ev["overall"]
    comps, intents = ev["competitors"], ev["by_intent"] or {}
    gaps = []
    hi = {k: v for k, v in intents.items() if k in ("events", "catering")}
    if hi:
        rates = ", ".join(f"{k} {pct(v['mention_rate'])}" for k, v in hi.items())
        gaps.append({"title": "Invisible on the highest-value requests",
                     "evidence": f"Mentioned in {rates} of event/catering answers; these bookings are worth "
                                 f"$1,200-2,000 each vs. ~$30 for lunch.",
                     "why_it_matters": "One missed rehearsal dinner outweighs dozens of missed lunches.",
                     "fix": "Publish dedicated private events and catering pages: capacity, group menus, price "
                            "range, lead time, plus FAQ answers for 'rehearsal dinner' and 'office catering'.",
                     "impact": "high", "effort": "medium", "agent_can_do": True})
    missing = [c for c in ev["source_coverage"] if c.get("status") == "ok"
               and not c.get("target_present") and c.get("competitors_present")]
    if missing:
        doms = sorted({c.get("domain") or c["url"] for c in missing})
        gaps.append({"title": "Absent from the guides AI assistants cite",
                     "evidence": f"{len(missing)} cited pages ({', '.join(doms[:4])}) list competitors such as "
                                 f"{', '.join(missing[0]['competitors_present'][:2])} but not {name}.",
                     "why_it_matters": "Assistants with web search summarize these pages; if you're not on them "
                                       "you can't be in the answer.",
                     "fix": "Pitch the editors of these specific pages with accurate, current facts.",
                     "impact": "high", "effort": "low", "agent_can_do": True})
    absent = [x for x in ev.get("sources_when_absent", []) if x["answers"] >= 2][:5]
    if absent:
        gaps.insert(2, {"title": "Not listed on the platforms AI cites for occasions",
                        "evidence": "In the " + str(absent[0]["of"]) + " answers that left " + name + " out, the most-cited "
                                    "sources were " + ", ".join(f"{x['domain']} ({x['answers']})" for x in absent) + ".",
                        "why_it_matters": "For occasion questions (date night, groups, gluten-free) assistants lean on "
                                          "booking and directory platforms, not restaurant websites.",
                        "fix": "Claim or complete a listing on each of these platforms with the same name, hours, "
                               "dietary tags, event capacity and photos; for events, add venue listings "
                               "(e.g. wedding/venue marketplaces and the tourism board's member directory).",
                        "impact": "high", "effort": "medium", "agent_can_do": False})
    a = ev["site_audit"]
    if a and not a.get("error"):
        missing_schema = [n for k, n in (("has_restaurant_schema", "Restaurant"), ("has_faq_schema", "FAQPage"),
                                         ("has_menu_schema", "Menu")) if not a.get(k)]
        if missing_schema:
            gaps.append({"title": "No structured data for AI crawlers",
                         "evidence": f"Site audit found no {', '.join(missing_schema)} schema markup.",
                         "why_it_matters": "Schema states hours, cuisine, address and FAQs in a machine-readable "
                                           "form, so crawlers don't have to guess.",
                         "fix": "Add the generated JSON-LD (Restaurant + FAQPage) to the homepage.",
                         "impact": "medium", "effort": "low", "agent_can_do": True})
        if (a.get("html_menu_price_count") or 0) < 5:
            gaps.append({"title": "Menu isn't readable as text",
                         "evidence": f"Found {a.get('html_menu_price_count') or 0} prices in HTML menu text "
                                     f"({len(a.get('pdf_links') or [])} PDF links).",
                         "why_it_matters": "AI can recommend you for a specific dish only if that dish is written "
                                           "on a page it can read.",
                         "fix": "Publish the menu as an HTML page with dish names, short descriptions and "
                                "dietary tags (V, VG, GF).",
                         "impact": "medium", "effort": "medium", "agent_can_do": True})
        blocked = [b for b, v in (a.get("ai_bots_blocked") or {}).items() if v]
        if blocked:
            gaps.insert(0, {"title": "AI crawlers are blocked", "evidence": f"robots.txt blocks {', '.join(blocked)}.",
                            "why_it_matters": "Blocked assistants can't read the site at all.",
                            "fix": "Allow these user agents in robots.txt.", "impact": "high", "effort": "low",
                            "agent_can_do": True})
    for issue in ev["consistency"]:
        gaps.append({"title": f"Conflicting {issue['type']} across the web",
                     "evidence": f"{issue['detail']} ({', '.join(issue['sources'][:3])}).",
                     "why_it_matters": "When sources disagree, assistants hedge or pick a competitor with "
                                       "cleaner facts.",
                     "fix": "Correct the listing on each source so name, hours and phone match exactly.",
                     "impact": "medium", "effort": "low", "agent_can_do": False})
    # Known for the cuisine, invisible for everything else it offers.
    names = {"happy_hour": "happy hour", "date_night": "date night", "dietary": "vegan/gluten-free",
             "local": "general 'where to eat'", "lunch": "lunch", "events": "private events",
             "catering": "catering", "cuisine": "cuisine", "dishes": "signature dishes"}
    strong = [k for k, v in intents.items() if k in ("cuisine", "dishes") and v["mention_rate"] >= 0.5]
    weak = [k for k, v in intents.items() if k not in ("cuisine", "dishes") and v["mention_rate"] == 0]
    if strong and weak:
        gaps.insert(1, {"title": "Known for the food, invisible for everything else",
                        "evidence": f"Recommended for {', '.join(names[k] for k in strong)} questions but in 0% of "
                                    f"{', '.join(names[k] for k in weak)} answers, although it offers "
                                    + "; ".join((ev['restaurant'].get('highlights') or [])[1:4]) + ".",
                        "why_it_matters": "Most diners don't ask for a cuisine; they ask for an occasion. "
                                          "Those answers go to places whose pages describe that occasion.",
                        "fix": "Give each offer its own crawlable page and FAQ: happy hour (times, small plates), "
                               "vegan and gluten-free dishes by name, private events, cocktails.",
                        "impact": "high", "effort": "low", "agent_can_do": True})
    other = {n: c for n, c in (ev.get("name_variants") or {}).items() if norm(n) != norm(name)}
    if other:
        gaps.insert(2, {"title": "Recommended under a different name",
                        "evidence": "Some answers recommend " + ", ".join(f"\"{n}\" ({c}x)" for n, c in other.items())
                                    + f" without connecting it to {name}.",
                        "why_it_matters": "Credit for those mentions doesn't build the restaurant's reputation, and "
                                          "diners may not realize they're the same business.",
                        "fix": f"Present catering as part of {name} on the website, schema and listings "
                               "(e.g. 'Café Athena Catering'), and link the catering listings back to the restaurant.",
                        "impact": "medium", "effort": "low", "agent_can_do": True})
    if comps and comps[0]["share_of_voice"] > o["mention_rate"]:
        top = comps[0]
        gaps.append({"title": f"{top['name']} owns the conversation",
                     "evidence": f"{top['name']} appears in {pct(top['share_of_voice'])} of answers vs. "
                                 f"{pct(o['mention_rate'])} for {name}.",
                     "why_it_matters": "The most-mentioned place becomes the default answer.",
                     "fix": "Win the niche: signature-dish and dietary pages where a specialist beats a generalist.",
                     "impact": "medium", "effort": "medium", "agent_can_do": True})
    gaps.sort(key=lambda g: {"high": 0, "medium": 1, "low": 2}.get(g["impact"], 3))  # stable
    if strong and weak:
        return {"headline": f"{name} is recommended in {pct(o['mention_rate'])} of AI answers: it wins "
                            f"{' and '.join(names[k] for k in strong)} questions but is absent when diners ask by "
                            f"occasion ({', '.join(names[k] for k in weak[:4])}).",
                "gaps": gaps[:8], "method": "rules"}
    head = (f"{name} appears in {pct(o['mention_rate'])} of AI answers but only "
            f"{pct(o['revenue_weighted_visibility'])} of the booking value"
            + (f"; {comps[0]['name']} appears in {pct(comps[0]['share_of_voice'])}." if comps else "."))
    return {"headline": head, "gaps": gaps[:8], "method": "rules"}


def diagnose(label):
    ev = evidence(label)
    if not ev["overall"]:
        raise SystemExit("Run analyze.py first.")
    out = None
    if not MOCK:
        try:
            out = parse_json(complete("EVIDENCE:\n" + json.dumps(ev, ensure_ascii=False), system=SYSTEM,
                                      max_tokens=4000))
            out["method"] = "llm"
        except Exception as e:
            print("LLM diagnosis failed, using rules:", str(e)[:120])
    out = out or rule_based(ev)
    write_json(DATA / "diagnosis.json", out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="baseline")
    d = diagnose(ap.parse_args().label)
    print(d.get("headline", ""))
    for g in d.get("gaps", []):
        print(f"- [{g.get('impact')}] {g.get('title')}: {g.get('evidence')}")
