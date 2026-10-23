"""Stage 2b - Evidence. Three checks that explain WHY competitors win.

1. Site audit: what can an AI crawler actually read on the restaurant's site?
2. Source coverage: open the pages the AIs cited and check whether the
   restaurant is on them vs. the top competitors.
3. Consistency: do the cited sources agree on hours, phone and name?
   Conflicting facts make AI assistants less confident recommending you.

    python audit.py --label baseline
"""
import argparse
import json
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import random
from collections import defaultdict

from config import COMPETITOR_SITES, DATA, MOCK, TARGET, read_json, write_json
from llm import mentions_target, norm
from safeurl import UnsafeURL, check_public_url

UA = ("Mozilla/5.0 (compatible; AISO-Hackathon-Audit/1.0; "
      "+https://github.com/DJPulseFoundry/Pulse-Foundry-X-NYU-SPS-Hackathon)")
AI_BOTS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot",
           "PerplexityBot", "Google-Extended", "Googlebot", "Bingbot"]


def fetch(url, timeout=20, max_bytes=2_000_000):
    """GET a public page. Every hop (including redirects) must resolve to a public IP,
    and the body is capped, so customer-supplied URLs can't reach internal services."""
    try:
        for _ in range(5):
            check_public_url(url)
            r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout,
                             allow_redirects=False, stream=True)
            if r.is_redirect and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                r.close()
                continue
            r._content = r.raw.read(max_bytes, decode_content=True)
            r._content_consumed = True
            return r
        return None
    except (requests.RequestException, UnsafeURL):
        return None


def visible_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "svg"]):
        t.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()


def count_prices(text):
    """Prices on a menu page. Many menus omit the $ ("Athena ... vodka, lime 15"), so when no
    $-prices exist, count standalone 1-2 digit numbers (not times, sizes or percentages)."""
    dollars = len(re.findall(r"\$\s?\d", text))
    if dollars:
        return dollars
    bare = re.findall(r"(?<![\d.,:$/(-])\b\d{1,2}(?:\.\d{1,2})?\b(?![\d:/%-]|\s?(?:am|pm|a\.m|p\.m|oz|ml|th|st|nd|rd|"
                      r"pieces?|people|guests|minutes?|hours?|days?|years?|skewers?|patties|rolls?|serves))",
                      text, re.I)
    return len(bare) if len(bare) >= 10 else 0  # too few to be a priced menu


def jsonld_types(soup):
    types, blocks = [], []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except Exception:
            blocks.append({"error": "invalid JSON-LD"})
            continue
        blocks.append(data)
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                t = d.get("@type")
                types += t if isinstance(t, list) else ([t] if t else [])
                stack += d.get("@graph", []) if isinstance(d.get("@graph"), list) else []
    return types, blocks


def robots_blocks(robots_txt):
    """Return {bot: blocked_from_root} using a simple group parser."""
    groups, agents, rules, last_was_agent = {}, [], [], False
    for raw in robots_txt.splitlines():
        line = raw.split("#")[0].strip()
        if ":" not in line:
            continue
        k, v = [x.strip() for x in line.split(":", 1)]
        k = k.lower()
        if k == "user-agent":
            if not last_was_agent:
                agents, rules = [], []
            agents.append(v.lower())
            for a in agents:
                groups[a] = rules
            last_was_agent = True
        elif k in ("disallow", "allow"):
            rules.append((k, v))
            last_was_agent = False
    out = {}
    for bot in AI_BOTS:
        rules = groups.get(bot.lower(), groups.get("*", []))
        out[bot] = any(k == "disallow" and v == "/" for k, v in rules)
    return out


def site_audit():
    base = TARGET["website"]
    res = {"url": base}
    home = fetch(base)
    if not home or home.status_code >= 400:
        res["error"] = f"homepage fetch failed ({getattr(home, 'status_code', 'no response')})"
        return res, ""
    soup = BeautifulSoup(home.text, "html.parser")
    types, blocks = jsonld_types(soup)
    links = [urljoin(base, a.get("href", "")) for a in soup.find_all("a")]
    menu_links = sorted({l for l in links if "menu" in l.lower()})
    pdfs = sorted({l for l in links if l.lower().split("?")[0].endswith(".pdf")})
    text = visible_text(home.text)

    # Check every HTML menu page on the site (not just the first): a bar or happy hour menu
    # can carry prices even when the main menu is images or a PDF.
    menu_text, menu_prices, html_menu, menu_pages = "", 0, None, []
    for link in [l for l in menu_links if not l.lower().split("?")[0].endswith(".pdf")
                 and urlparse(l).netloc.endswith(TARGET["domain"]) and "#" not in l][:4]:
        m = fetch(link)
        if m and m.ok and "html" in m.headers.get("content-type", ""):
            t = visible_text(m.text)
            n = count_prices(t)
            menu_pages.append({"url": link, "prices": n})
            menu_text += "\n" + t
            menu_prices += n
            if n and not html_menu:
                html_menu = link
    html_menu = html_menu or (menu_pages[0]["url"] if menu_pages else None)

    robots = fetch(urljoin(base, "/robots.txt"))
    llms = fetch(urljoin(base, "/llms.txt"))
    meta = soup.find("meta", attrs={"name": "description"})
    res.update({
        "title": soup.title.get_text(strip=True) if soup.title else None,
        "meta_description": meta.get("content") if meta else None,
        "h1": [h.get_text(" ", strip=True) for h in soup.find_all("h1")][:5],
        "homepage_words": len(text.split()),
        "jsonld_types": types,
        "jsonld_blocks": blocks[:5],
        "has_restaurant_schema": any(t in ("Restaurant", "FoodEstablishment", "BarOrPub") for t in types),
        "has_faq_schema": "FAQPage" in types,
        "has_menu_schema": any(t in ("Menu", "MenuItem") for t in types),
        "faq_on_homepage": "faq" in text.lower() or "frequently asked" in text.lower(),
        "menu_links": menu_links[:10],
        "pdf_links": pdfs[:10],
        "html_menu_url": html_menu,
        "html_menu_price_count": menu_prices,
        "menu_pages": menu_pages,
        "mentions": {kw: kw in (text + " " + menu_text).lower() for kw in
                     ["gluten", "vegan", "vegetarian", "happy hour", "catering", "private",
                      "rehearsal", "pacific beach", "1990", "cocktail"]},
        "robots_status": getattr(robots, "status_code", None),
        "ai_bots_blocked": robots_blocks(robots.text) if robots is not None and robots.ok else {},
        "has_llms_txt": bool(llms is not None and llms.ok and "html" not in llms.headers.get("content-type", "")),
    })
    return res, (text + "\n\n" + menu_text)[:20000]


def competitor_sites(sites):
    """Light audit of the rivals' own websites: does the winner tell machines it's a restaurant?"""
    out = []
    for name, url in sites.items():
        rec = {"name": name, "url": url}
        home = fetch(url)
        if not home or home.status_code >= 400:
            rec["error"] = f"fetch failed ({getattr(home, 'status_code', 'no response')})"
            out.append(rec)
            continue
        soup = BeautifulSoup(home.text, "html.parser")
        types, _ = jsonld_types(soup)
        host = urlparse(home.url).netloc
        links = [urljoin(home.url, a.get("href", "")) for a in soup.find_all("a")]
        menus = [l for l in links if "menu" in l.lower() and urlparse(l).netloc == host
                 and not l.lower().split("?")[0].endswith(".pdf") and "#" not in l][:2]
        prices = 0
        for l in menus:
            m = fetch(l)
            if m and m.ok and "html" in m.headers.get("content-type", ""):
                prices += count_prices(visible_text(m.text))
        llms = fetch(urljoin(home.url, "/llms.txt"))
        rec.update({
            "has_restaurant_schema": any(t in ("Restaurant", "FoodEstablishment", "BarOrPub") for t in types),
            "has_faq_schema": "FAQPage" in types,
            "has_menu_schema": any(t in ("Menu", "MenuItem") for t in types),
            "has_llms_txt": bool(llms is not None and llms.ok and "html" not in llms.headers.get("content-type", "")),
            "menu_price_count": prices,
            "homepage_words": len(visible_text(home.text).split()),
            "jsonld_types": types,
        })
        out.append(rec)
    return out


def source_coverage(card, max_urls=25):
    """Open cited pages; does Café Athena appear where competitors do?"""
    comps = [c["name"] for c in card["competitors"][:10]]
    out = []
    for u in card["top_urls"]:
        if len(out) >= max_urls:
            break
        if TARGET["domain"] in u["url"]:
            continue
        r = fetch(u["url"])
        rec = {"url": u["url"], "cited_in_answers": u["answers"]}
        if not r or r.status_code >= 400:
            rec["status"] = f"blocked/failed ({getattr(r, 'status_code', 'none')})"
            out.append(rec)
            continue
        is_html = "html" in r.headers.get("content-type", "")
        text = visible_text(r.text) if is_html else ""
        page = BeautifulSoup(r.text, "html.parser") if is_html else None
        low = norm(text)
        rec.update({
            "final_url": r.url,
            "domain": urlparse(r.url).netloc.removeprefix("www."),
            "status": "ok",
            "title": page.title.get_text(strip=True) if page and page.title else "",
            "target_present": mentions_target(text),
            "competitors_present": [c for c in comps if norm(c) and norm(c) in low],
            "excerpt": text[:3000],
        })
        out.append(rec)
        time.sleep(1.0)  # be polite
    return out


TIME_RE = re.compile(r"\b(1[0-2]|[1-9])(?::([0-5]\d))?\s*(a\.?m\.?|p\.?m\.?)", re.I)
PHONE_RE = re.compile(r"\(?\b(\d{3})\)?[\s.-]?(\d{3})[\s.-](\d{4})\b")
def _name_re():
    """Regex matching the restaurant's name and aliases, accent/apostrophe tolerant."""
    pats = []
    for a in sorted({TARGET["name"], *TARGET.get("aliases", [])}, key=len, reverse=True):
        p = re.escape(a.lower()).replace("é", "e").replace("e", "[eé]").replace("'", "'?")
        pats.append(p.replace("\\ ", "\\s+"))
    return re.compile("(" + "|".join(pats) + ")", re.I)


NAME_RE = _name_re()


def _official_times():
    out = set()
    for _days, o, c in TARGET.get("hours") or []:
        for t in (o, c):
            h, m = [int(x) for x in t.split(":")]
            out.add(f"{(h - 1) % 12 + 1}:{m:02d} {'PM' if h >= 12 else 'AM'}")
    return out


def consistency(coverage, site_text):
    """Compare facts near the restaurant's name across every readable source."""
    official = _official_times()
    times, phones, names = defaultdict(set), defaultdict(set), defaultdict(set)
    pages = [(c.get("domain") or c.get("url", "?"), c.get("excerpt", "")) for c in coverage
             if c.get("status") == "ok" and c.get("target_present")]
    pages.append((TARGET.get("domain") or "own site", site_text))
    for src, text in pages:
        for m in NAME_RE.finditer(text):
            names[m.group(1).strip().title()].add(src)
            window = text[max(0, m.start() - 600): m.end() + 600]
            for h, mi, ap in TIME_RE.findall(window):
                times[f"{int(h)}:{mi or '00'} {'PM' if ap.lower().startswith('p') else 'AM'}"].add(src)
            for a, b, c in PHONE_RE.findall(window):
                phones[f"({a}) {b}-{c}"].add(src)
    issues = []
    if official:
        for t, srcs in sorted(times.items()):
            if t not in official and t.endswith("PM") and int(t.split(":")[0]) >= 8:
                issues.append({"type": "hours",
                               "detail": f"{t} closing time listed, official hours say {' / '.join(sorted(x for x in official if x.endswith('PM')))}",
                               "sources": sorted(srcs)})
    if len(phones) > 1:
        issues.append({"type": "phone", "detail": f"{len(phones)} different phone numbers found",
                       "sources": sorted({s for v in phones.values() for s in v})})
    distinct = {norm(n) for n in names}  # accents alone don't count as a conflict
    if len(distinct) > 1:
        issues.append({"type": "name", "detail": "Name spelled several ways: " + ", ".join(sorted(names)),
                       "sources": sorted({s for v in names.values() for s in v})})
    return {"sources_checked": len(pages), "issues": issues,
            "times_found": {k: sorted(v) for k, v in times.items()},
            "phones_found": {k: sorted(v) for k, v in phones.items()},
            "name_variants": {k: sorted(v) for k, v in names.items()}}


def mock_evidence(card):
    """Offline stand-ins so the pipeline can be demoed without network access."""
    audit = {"url": TARGET.get("website"), "mock": True, "has_restaurant_schema": False,
             "has_faq_schema": False, "has_menu_schema": False, "html_menu_price_count": 0,
             "has_llms_txt": False, "ai_bots_blocked": {"GPTBot": False, "PerplexityBot": False},
             "mentions": {"gluten": True, "vegan": True, "happy hour": True, "catering": True,
                          "private": False, "rehearsal": False, "pacific beach": True}}
    site_text = (f"Welcome to {TARGET['name']}. Mediterranean kitchen and bar since 1990. "
                 "Open daily 11:00 AM to 9:00 PM. Call (858) 555-0100.")
    comps = [c["name"] for c in (card or {}).get("competitors", [])[:6]]
    cov = []
    for i, u in enumerate((card or {}).get("top_urls", [])[:12]):
        rng = random.Random(u["url"])
        present = rng.random() < 0.3
        dom = u["url"].split("/")[2]
        listed = rng.sample(comps, min(3, len(comps)))
        body = "Our favorite spots: " + ", ".join(listed)
        if present:
            body += f". Also try Cafe Athena, open until {'10 p.m.' if i % 2 else '9 p.m.'} on weekends."
        cov.append({"url": u["url"], "cited_in_answers": u["answers"], "final_url": u["url"],
                    "domain": dom, "status": "ok", "title": f"Mock guide on {dom}",
                    "target_present": present, "competitors_present": listed, "excerpt": body})
    return audit, site_text, cov


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--max-urls", type=int, default=25)
    args = ap.parse_args()

    card = read_json(DATA / f"scorecard_{args.label}.json")
    if MOCK:
        audit, site_text, cov = mock_evidence(card)
    else:
        audit, site_text = site_audit()
        cov = source_coverage(card, args.max_urls) if card else []
    write_json(DATA / "site_audit.json", audit)
    write_json(DATA / "competitor_sites.json", [] if MOCK else competitor_sites(COMPETITOR_SITES))
    (DATA / "site_text_before.txt").write_text(site_text, encoding="utf-8")
    write_json(DATA / "source_coverage.json", cov)
    cons = consistency(cov, site_text)
    write_json(DATA / "consistency.json", cons)

    print("Site audit:", {k: audit.get(k) for k in
                          ["error", "has_restaurant_schema", "has_faq_schema", "has_menu_schema",
                           "html_menu_price_count", "has_llms_txt"] if k in audit})
    blocked = [b for b, v in audit.get("ai_bots_blocked", {}).items() if v]
    print("AI bots blocked:", blocked or "none")
    for c in read_json(DATA / "competitor_sites.json", []):
        print(f"Rival site {c['name']}: " + (c.get("error") or ", ".join(
            k for k in ("has_restaurant_schema", "has_faq_schema", "has_llms_txt") if c.get(k)) or "no schema"))
    ok = [c for c in cov if c.get("status") == "ok"]
    miss = [c for c in ok if not c.get("target_present") and c.get("competitors_present")]
    print(f"Cited pages checked: {len(ok)} readable / {len(cov)} total. "
          f"{len(miss)} list competitors but not {TARGET['name']}.")
    for i in cons["issues"]:
        print(f"Consistency: {i['detail']} ({', '.join(i['sources'][:3])})")
