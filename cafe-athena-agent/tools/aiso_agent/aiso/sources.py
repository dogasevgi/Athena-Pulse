"""Do the pages AI assistants cite actually list Café Athena?

Takes the URLs saved with each answer (web-search platforms only), visits the most-cited
ones politely, and records whether Café Athena and the top competitors appear on each.
Pages that list competitors but not Café Athena become specific outreach targets.
"""
from __future__ import annotations

import re
import time
from collections import Counter
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .audit import _allowed
from .config import CRAWL_DELAY_SECONDS, USER_AGENT
from .extract import is_target, norm

# Sites that block bots or need logins; we report them as "not checked" instead of guessing.
SKIP = ("yelp.", "tripadvisor.", "google.", "facebook.", "instagram.", "reddit.", "opentable.",
        "airbnb.", "tiktok.", "x.com", "twitter.")


def check(rows: list[dict], aliases: list[str], top_competitors: list[str], limit: int = 12) -> list[dict]:
    urls = Counter(u for r in rows for u in (r.get("sources") or []) if str(u).startswith("http"))
    if not urls:
        return []
    out = []
    for url, cited in urls.most_common(limit):
        dom = urlparse(url).netloc.lower().removeprefix("www.")
        rec = {"url": url, "domain": dom, "cited": cited, "athena": None, "competitors": []}
        if any(s in dom for s in SKIP) or not _allowed(url):
            rec["note"] = "not checked (site blocks automated access)"
            out.append(rec)
            continue
        try:
            r = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            text = norm(BeautifulSoup(r.text, "html.parser").get_text(" "))
            rec["athena"] = any(a in text for a in aliases)
            rec["competitors"] = [c for c in top_competitors if norm(c) and norm(c) in text]
        except Exception as e:
            rec["note"] = f"not checked ({type(e).__name__})"
        out.append(rec)
        time.sleep(CRAWL_DELAY_SECONDS)
    return out


def print_check(res: list[dict]):
    if not res:
        print("No cited URLs in this run. Use a web-search platform (claude-web, gemini-web, perplexity).")
        return
    print(f"\n{'cited':>5}  {'Café Athena':<12} source")
    for c in res:
        a = {True: "listed", False: "MISSING", None: "–"}[c["athena"]]
        extra = f"  lists: {', '.join(c['competitors'][:3])}" if c["competitors"] else ""
        print(f"{c['cited']:>5}  {a:<12} {c['url'][:70]}{extra}  {c.get('note', '')}")
