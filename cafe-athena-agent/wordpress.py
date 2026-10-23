"""Optional action: push the generated pages and FAQ to a WordPress site as DRAFTS.

The owner reviews each draft in WordPress and clicks Publish. Every page created is logged
in data/wordpress_log.jsonl, and `--undo` deletes exactly those drafts.
Dry run is the default; nothing is sent without --live.

    export WP_URL=https://example.com WP_USER=... WP_APP_PASSWORD=...   # Users > Application Passwords
    python3 wordpress.py              # dry run: list what would be created
    python3 wordpress.py --live       # create drafts
    python3 wordpress.py --undo       # delete the drafts this tool created

JSON-LD is not put in page bodies (WordPress strips <script> for most roles): add
artifacts/restaurant_schema.jsonld and faq_schema.jsonld once to the site header with a
header-code plugin, and upload artifacts/llms.txt to the site root.
"""
import argparse
import datetime as dt
import json
import os
import re

import requests

from config import DATA, OUT

LOG = DATA / "wordpress_log.jsonl"


def wp():
    try:
        return os.environ["WP_URL"].rstrip("/"), (os.environ["WP_USER"], os.environ["WP_APP_PASSWORD"])
    except KeyError as e:
        raise SystemExit(f"Set {e} to publish to WordPress.")


def drafts():
    out = []
    for p in sorted((OUT / "pages").glob("*.html")):
        doc = p.read_text(encoding="utf-8")
        body = re.search(r"<body>(.*)</body>", doc, re.S)
        body = body.group(1) if body else doc
        title = re.search(r"<h1>(.*?)</h1>", body, re.S)
        out.append({"slug": p.stem, "title": re.sub("<.*?>", "", title.group(1)) if title else p.stem,
                    "content": re.sub(r"<h1>.*?</h1>\s*", "", body, count=1, flags=re.S)})
    faq = OUT / "faq.html"
    if faq.exists():
        html = re.sub(r"<script.*?</script>", "", faq.read_text(encoding="utf-8"), flags=re.S)
        out.append({"slug": "faq", "title": "Frequently asked questions", "content": html})
    return out


def publish(live):
    pages = [d for d in drafts() if "[VERIFY" not in d["content"]]
    skipped = len(drafts()) - len(pages)
    base, auth = wp() if live else (os.getenv("WP_URL", "<WP_URL>"), None)
    for d in pages:
        if not live:
            print(f"  [dry run] would create DRAFT '{d['title']}' at {base}/{d['slug']}/")
            continue
        r = requests.post(f"{base}/wp-json/wp/v2/pages", auth=auth, timeout=30,
                          json={"title": d["title"], "slug": d["slug"], "content": d["content"], "status": "draft"})
        r.raise_for_status()
        rec = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "id": r.json()["id"], "slug": d["slug"]}
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"  created draft #{rec['id']}: {d['title']}")
    if skipped:
        print(f"  skipped {skipped} page(s) that still contain [VERIFY] items")
    if not live:
        print("Dry run only. Add --live to create the drafts.")


def undo():
    if not LOG.exists():
        raise SystemExit("Nothing published yet.")
    base, auth = wp()
    for line in LOG.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        r = requests.delete(f"{base}/wp-json/wp/v2/pages/{d['id']}", auth=auth, params={"force": "true"}, timeout=30)
        print(f"  {'deleted' if r.ok else 'failed  '} #{d['id']} {d['slug']}")
    LOG.rename(LOG.with_suffix(f".undone-{dt.datetime.now():%Y%m%d%H%M%S}"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--undo", action="store_true")
    a = ap.parse_args()
    undo() if a.undo else publish(a.live)
