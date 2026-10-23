"""Stage 2b: audit the on-site signals AI assistants draw on.

Respects robots.txt, identifies itself, and waits between requests.
Off-site signals (Yelp, TripAdvisor, Google Business Profile, Reddit, press) are
captured as a manual checklist in diagnose.py, because their terms of service
generally prohibit scraping. Use their official APIs if you have access.
"""
from __future__ import annotations
import json
import re
import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .config import CRAWL_DELAY_SECONDS, MAX_PAGES_PER_SITE, USER_AGENT

# Terms that answer each query category. Coverage = does the site say it at all?
SIGNAL_TERMS = {
    "cuisine": ["greek", "mediterranean", "gyro", "souvlaki", "falafel", "hummus"],
    "dietary": ["gluten-free", "gluten free", "vegan", "vegetarian"],
    "happy_hour": ["happy hour"],
    "date_night": ["cocktail", "date night", "romantic"],
    "events": ["private event", "rehearsal", "catering", "group dining", "party", "banquet"],
    "location": ["pacific beach", "garnet", "mission bay"],
}
AI_CRAWLERS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-Web", "anthropic-ai",
               "PerplexityBot", "Google-Extended", "CCBot"]
PRICE = re.compile(r"\$\s?\d{1,3}(?:\.\d{2})?")
PRIORITY_LINK_WORDS = ["menu", "about", "event", "cater", "faq", "happy", "private", "party", "bar"]


_ROBOTS: dict = {}


def _robots(url):
    """Fetch robots.txt with our own User-Agent (urllib's default is often refused).
    Standard handling: 4xx = no rules (allowed), 5xx/network error = don't crawl."""
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    if base not in _ROBOTS:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = requests.get(base + "/robots.txt", headers={"User-Agent": USER_AGENT}, timeout=15)
            if r.status_code >= 500:
                rp.disallow_all = True
            elif r.status_code >= 400:
                rp.allow_all = True
            else:
                rp.parse(r.text.splitlines())
        except Exception:
            rp.disallow_all = True
        _ROBOTS[base] = rp
    return _ROBOTS[base]


def _allowed(url, agent=USER_AGENT):
    return _robots(url).can_fetch(agent, url)


def _jsonld_types(soup):
    types = set()
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                t = d.get("@type")
                types.update(t if isinstance(t, list) else [t] if t else [])
                stack.extend(v for v in d.values() if isinstance(v, (dict, list)))
            elif isinstance(d, list):
                stack.extend(d)
    return types


def ai_access(url: str, sess=None) -> dict:
    """Are AI crawlers allowed in robots.txt, and is there an llms.txt?"""
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    blocked = [a for a in AI_CRAWLERS if not _allowed(base + "/", a)]
    has_llms = False
    try:
        r = (sess or requests).get(base + "/llms.txt", timeout=15, headers={"User-Agent": USER_AGENT})
        has_llms = r.ok and "<html" not in r.text[:500].lower() and len(r.text.strip()) > 20
    except Exception:
        pass
    return {"blocked_ai_crawlers": blocked, "has_llms_txt": has_llms}


def summarize_text(name: str, url: str, text: str, jsonld: set, pages: list, meta: str | None,
                   menu_pdfs: list | None = None, access: dict | None = None):
    low = text.lower()
    return {
        "price_count": len(PRICE.findall(text)),     # prices readable as text
        "menu_pdf_links": menu_pdfs or [],
        "blocked_ai_crawlers": (access or {}).get("blocked_ai_crawlers", []),
        "has_llms_txt": (access or {}).get("has_llms_txt"),
        "name": name, "url": url, "pages": pages,
        "word_count": len(text.split()),
        "jsonld_types": sorted(jsonld),
        "has_restaurant_schema": bool({"Restaurant", "FoodEstablishment", "BarOrPub"} & jsonld),
        "has_menu_schema": bool({"Menu", "MenuSection", "MenuItem"} & jsonld),
        "has_faq_schema": "FAQPage" in jsonld,
        "has_faq_content": "faq" in low or "frequently asked" in low,
        "meta_description": meta,
        "coverage": {k: [t for t in v if t in low] for k, v in SIGNAL_TERMS.items()},
        "text": text[:8000],
    }


def audit_site(name: str, url: str) -> dict:
    sess = requests.Session()
    sess.headers["User-Agent"] = USER_AGENT
    host = urlparse(url).netloc
    queue, seen, pages, texts, jsonld, meta = [url], set(), [], [], set(), None
    pdfs = set()
    while queue and len(pages) < MAX_PAGES_PER_SITE:
        u = queue.pop(0)
        if u in seen:
            continue
        seen.add(u)
        if not _allowed(u):
            print(f"  robots.txt disallows {u}; skipping")
            continue
        try:
            r = sess.get(u, timeout=20)
            r.raise_for_status()
        except Exception as e:
            print(f"  ! {u}: {e}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        jsonld |= _jsonld_types(soup)
        if meta is None:
            m = soup.find("meta", attrs={"name": "description"})
            meta = m.get("content") if m else None
        for s in soup(["script", "style", "noscript"]):
            s.decompose()
        texts.append(re.sub(r"\s+", " ", soup.get_text(" ")).strip())
        pages.append(u)
        links = {urljoin(u, a["href"]).split("#")[0] for a in soup.find_all("a", href=True)}
        pdfs |= {l for l in links if l.lower().endswith(".pdf")}
        links = {l for l in links if not l.lower().endswith((".pdf", ".jpg", ".png", ".jpeg"))}
        links = [l for l in links if urlparse(l).netloc == host and l not in seen]
        links.sort(key=lambda l: -sum(w in l.lower() for w in PRIORITY_LINK_WORDS))
        queue.extend(links)
        time.sleep(CRAWL_DELAY_SECONDS)
    return summarize_text(name, url, " ".join(texts), jsonld, pages, meta,
                          sorted(pdfs), ai_access(url, sess))


def audit_from_text(name: str, text: str, url: str = "(provided text)") -> dict:
    """For offline demos, or for listing text pasted in by hand (e.g. a Yelp blurb)."""
    return summarize_text(name, url, text, set(), [url], None)
