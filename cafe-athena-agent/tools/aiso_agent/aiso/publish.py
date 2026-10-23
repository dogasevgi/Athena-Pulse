"""Bonus: act, not just advise.

Pushes APPROVED pages (out/publish/cms/*.html) to a WordPress site as DRAFT pages,
so the owner reviews them in WordPress and clicks Publish. Every page created is logged,
and `unpublish` deletes exactly those pages.

  WP_URL=https://example.com  WP_USER=...  WP_APP_PASSWORD=...  (WordPress > Users > Application Passwords)

Dry run is the default; nothing is sent without --live.
JSON-LD is not pushed into page bodies (WordPress strips <script> for most roles):
add restaurant.jsonld once to the site header with a header-code plugin or the theme.
Other CMSs (Squarespace, Wix, Webflow): paste each cms/*.html into an HTML/code block.
"""
from __future__ import annotations

import glob
import json
import os
import re
import time

import requests


def _wp():
    try:
        return os.environ["WP_URL"].rstrip("/"), (os.environ["WP_USER"], os.environ["WP_APP_PASSWORD"])
    except KeyError as e:
        raise SystemExit(f"Set {e} to publish to WordPress.")


def publish_wordpress(publish_dir="out/publish", live=False, log="out/published.jsonl"):
    pages = sorted(glob.glob(f"{publish_dir}/cms/*.html"))
    if not pages:
        raise SystemExit("No approved pages in out/publish/cms. Run `approve` first.")
    base, auth = _wp() if live else (os.getenv("WP_URL", "<WP_URL>"), None)
    for path in pages:
        body = open(path).read()
        if "[TODO" in body:
            print(f"  skip {path}: still has [TODO] markers")
            continue
        m = re.search(r"<h1>(.*?)</h1>", body)
        title = re.sub("<.*?>", "", m.group(1)) if m else os.path.basename(path)
        slug = os.path.basename(path)[:-5].removeprefix("page-")
        payload = {"title": title, "slug": slug, "content": re.sub(r"<h1>.*?</h1>\s*", "", body, 1),
                   "status": "draft"}
        if not live:
            print(f"  [dry run] would create DRAFT page '{title}' at {base}/{slug}/")
            continue
        r = requests.post(f"{base}/wp-json/wp/v2/pages", auth=auth, json=payload, timeout=30)
        r.raise_for_status()
        d = r.json()
        with open(log, "a") as f:
            f.write(json.dumps({"ts": time.time(), "id": d["id"], "slug": slug, "link": d.get("link"),
                                "file": path}) + "\n")
        print(f"  created draft #{d['id']}: {title}  (edit in WordPress, then Publish)")
    if not live:
        print("\nDry run only. Add --live to create the drafts.")


def unpublish_wordpress(log="out/published.jsonl"):
    if not os.path.exists(log):
        raise SystemExit("Nothing published yet.")
    base, auth = _wp()
    for line in open(log):
        d = json.loads(line)
        r = requests.delete(f"{base}/wp-json/wp/v2/pages/{d['id']}", auth=auth,
                            params={"force": "true"}, timeout=30)
        print(f"  {'deleted' if r.ok else 'failed  '} #{d['id']} {d['slug']}")
    os.rename(log, log + f".undone-{int(time.time())}")
