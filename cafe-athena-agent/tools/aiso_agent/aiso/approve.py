"""Stage 3b: human-in-the-loop approval, then a reversible "publish".

Nothing leaves this machine without an explicit 'a' (approve) per file.
Files with unresolved [TODO] markers cannot be approved.
Every decision is logged with a content hash, so any published change can be traced
and rolled back. With --repo, approved files are committed on a new git branch,
ready to open as a pull request against the restaurant's website repo.
"""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import subprocess
import time

INSTRUCTIONS = """# How to publish these files

- restaurant.jsonld: paste inside <script type="application/ld+json"> ... </script>
  in the <head> of every page (or the site-wide header template).
- faq.md: publish as /faq. The FAQPage markup is already inside restaurant.jsonld.
- page-*.md: publish each as its own URL (the file name is the suggested slug) and
  link to it from the home page and navigation.
- about.md: replace the current About copy.
- meta-description.txt: set as the home page <meta name="description">.
- menu.md: replace the menu page copy (Menu schema is inside restaurant.jsonld).
- cms/*.html: the same pages as HTML, ready to paste into any CMS's HTML block,
  or push to WordPress as drafts with `python cli.py publish --wordpress`.
- outreach-*.md: send manually from the owner's own email.
- review-request.md: print as a table card / receipt line.
- llms.txt: upload to the site root (cafeathena.com/llms.txt). Check the page URLs match.
- gbp_description.txt: paste into Google Business Profile > Edit profile > Description.
- name-variants.md: owner confirms whether these names are Café Athena before anything changes.

After publishing, wait for re-crawl (days to weeks), then run:
  python cli.py discover --label after-<date>   and   python cli.py trend
"""


NOT_PAGES = ("outreach", "action_plan", "review-request", "name-variants", "SOURCES")  # drafts/notes, not site pages


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def review(content_dir, publish_dir="out/publish", log_path="out/approvals.jsonl",
           reviewer=None, assume_yes=False, repo=None):
    reviewer = reviewer or os.getenv("USER", "unknown")
    os.makedirs(publish_dir, exist_ok=True)
    approved = []
    names = sorted(os.path.relpath(os.path.join(d, f), content_dir)
                   for d, _, fs in os.walk(content_dir) for f in fs)
    for name in names:
        path = os.path.join(content_dir, name)
        with open(path) as f:
            text = f.read()
        todos = text.count("[TODO")
        print("\n" + "=" * 70 + f"\n{name}  ({len(text)} chars, {todos} TODOs)\n" + "-" * 70)
        print("\n".join(text.splitlines()[:20]) + ("\n..." if text.count("\n") > 20 else ""))
        if todos and not name.startswith(NOT_PAGES):
            print(f"\n  Blocked: resolve {todos} [TODO] marker(s) in {path} before approving.")
            decision = "blocked"
        elif assume_yes:
            decision = "approved"
        else:
            ans = input("\n[a]pprove / [s]kip / [q]uit > ").strip().lower()
            if ans == "q":
                break
            decision = "approved" if ans == "a" else "skipped"
        if decision == "approved":
            os.makedirs(os.path.dirname(os.path.join(publish_dir, name)), exist_ok=True)
            shutil.copy(path, os.path.join(publish_dir, name))
            approved.append(name)
            if name.endswith(".md") and not name.startswith(NOT_PAGES):
                from .action import md_to_html  # paste-ready HTML from the approved text
                os.makedirs(os.path.join(publish_dir, "cms"), exist_ok=True)
                cms = os.path.join("cms", os.path.basename(name)[:-3] + ".html")
                with open(os.path.join(publish_dir, cms), "w") as f:
                    f.write(md_to_html(text) + "\n")
                approved.append(cms)
        with open(log_path, "a") as f:
            f.write(json.dumps({"ts": time.time(), "file": name, "sha256": _sha(path),
                                "decision": decision, "reviewer": reviewer}) + "\n")
    with open(os.path.join(publish_dir, "PUBLISH_INSTRUCTIONS.md"), "w") as f:
        f.write(INSTRUCTIONS)
    print(f"\nApproved {len(approved)} file(s) -> {publish_dir}")
    if repo and approved:
        _commit_branch(repo, publish_dir, approved)
    return approved


def _commit_branch(repo, publish_dir, files):
    branch = "aiso/" + time.strftime("%Y%m%d-%H%M")
    dest = os.path.join(repo, "aiso-content")
    os.makedirs(dest, exist_ok=True)
    for f in files:
        os.makedirs(os.path.dirname(os.path.join(dest, f)), exist_ok=True)
        shutil.copy(os.path.join(publish_dir, f), os.path.join(dest, f))
    run = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True)
    run("checkout", "-b", branch)
    run("add", "aiso-content")
    run("commit", "-m", f"AISO: add {len(files)} approved content files")
    print(f"Committed on branch {branch}. Push it and open a PR; revert by deleting the branch.")
