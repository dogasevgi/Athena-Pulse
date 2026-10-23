"""Build artifacts/dashboard.html: the team's interactive dashboard, filled with REAL results.

Data comes from this agent's own outputs (answers, scorecard, audits, head-to-head, generated
files). Where the agent has no data of its own (the Gemini runs made with aiso_agent, the
earlier audits), dashboard_snapshot.json fills in and every such number is labeled "snapshot".
Nothing is simulated.

    python3 dashboard.py --label baseline
    open artifacts/dashboard.html
"""
import argparse
import datetime as dt
import re
import json
from collections import Counter, defaultdict
from pathlib import Path

from analyze import load_rows
from config import DATA, OUT, ROOT, TARGET, read_json
from llm import is_target, norm
from generate import hours_text
from queries import VALUES

NAMES = {"anthropic": "Claude", "openai": "ChatGPT", "gemini": "Gemini", "perplexity": "Perplexity"}
LABELS = {"events": "Private events", "catering": "Catering", "date_night": "Date night", "local": "General local",
          "casual": "General local", "cuisine": "Greek & Mediterranean", "dishes": "Specific dishes",
          "dietary": "Vegan & gluten-free", "happy_hour": "Happy hour", "lunch": "Lunch"}
SNAP_CAT = {"casual": "local"}
# Phrasings added to the query bank from Google Trends (San Diego, past 12 months).
TRENDS_QUERIES = {"best happy hour in San Diego", "happy hour near me in Pacific Beach", "best restaurants in Pacific Beach",
                  "Pacific Beach restaurants on the water", "Greek restaurant San Diego", "Mediterranean food San Diego"}  # aiso_agent category names -> this agent's intents


def assistants_from_rows(rows):
    by = defaultdict(list)
    for r in rows:
        by[r["provider"]].append(r)
    out = []
    for p, rs in by.items():
        hit = [r for r in rs if r["mentioned"]]
        ranks = [r["position"] for r in hit if r.get("position")]
        tv = sum(r["value"] for r in rs) or 1
        cats = defaultdict(list)
        for r in rs:
            cats[r["intent"]].append(r)
        comp = Counter()
        for r in rs:
            comp.update({norm(n): n for n in r.get("restaurants", []) if not is_target(n)}.values())
        out.append({
            "name": NAMES.get(p, p.title()), "source": "this agent", "answers": len(rs), "mentioned": len(hit),
            "rate": round(len(hit) / len(rs), 3), "avg_rank": round(sum(ranks) / len(ranks), 2) if ranks else None,
            "value_weighted": round(sum(r["value"] for r in hit) / tv, 3),
            "by_category": {c: round(sum(r["mentioned"] for r in v) / len(v), 3) for c, v in cats.items()},
            "rivals": [n for n, _ in comp.most_common(8)],
            "runs": [{"label": "Answers analyzed", "n": len(rs), "mentioned": len(hit)}],
        })
    return out, by


def curl(v):
    """Curly apostrophes and quotes in the text people read (never in files, answers or questions)."""
    if isinstance(v, str):
        v = re.sub(r"(?<![\w])'([^']+)'(?![\w])", "\u2018\\1\u2019", v)
        return re.sub(r"(\w)'(\w)", "\\1\u2019\\2", v)
    if isinstance(v, list):
        return [curl(x) for x in v]
    if isinstance(v, dict):
        return {k: (x if k in ("content", "answer", "query", "files") else curl(x)) for k, x in v.items()}
    return v


def render(data, hosted=False):
    if hosted:
        data = {k: (v if k == "files" else curl(v)) for k, v in data.items()}
    html = (ROOT / "dashboard_template.html").read_text(encoding="utf-8").replace(
        "/*__DATA__*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    if hosted:  # shared page: no live API tab (hosts block calls to other sites)
        html = html.replace("/*__HOSTED__*/false", "true")
    return html


def from_html(path, hosted):
    """Rebuild a dashboard someone else built (older version) in the current design: keeps its
    measured data, refreshes the curated parts (plan, notes) and adds what older builds lacked."""
    m = re.search(r"const DATA = (\{.*?\});\n", Path(path).read_text(encoding="utf-8"), re.S)
    if not m:
        raise SystemExit("No dashboard data found in that file.")
    data = json.loads(m.group(1).replace("<\\/", "</"))
    snap = read_json(ROOT / "dashboard_snapshot.json", {})
    for k in ("plan", "trends", "conflicts", "sources"):
        data[k] = snap.get(k, data.get(k))
    data["restaurant"] = {**data.get("restaurant", {}), **{k: TARGET.get(k) for k in ("cuisine", "highlights")},
                          "hours": hours_text() if TARGET.get("hours") else None}
    data.setdefault("actions_log", [])
    data.setdefault("query_bank", [{"query": q["query"], "intent": q["intent"], "value": q["value"],
                                    "trends": q["query"] in TRENDS_QUERIES} for q in read_json(DATA / "queries.json", []) or []])
    have = {f["name"] for f in data["files"]}
    if VERIFIED_PAGES.exists():  # pages added to the verified content since that build
        from generate import slug
        for pg in read_json(VERIFIED_PAGES)["pages"]:
            name = f"pages/{slug(pg['slug'])}.html"
            if name not in have:
                data["files"].append({"name": name, "kind": "Page", "content": pg["body_html"]})
    best = {}
    for c in data.get("cited", []):
        key = re.sub(r"^(www\.|redirect\.|es\.)", "", c.get("domain") or "")
        key = next((b + ".com" for b in ("opentable", "airbnb", "foursquare", "tripadvisor", "yelp") if b in key), key)
        rank = lambda x: (x["athena"] is not None, bool(x.get("competitors")), x.get("cited") or 0)
        if key not in best or rank(c) > rank(best[key]):
            best[key] = {**c, "domain": key}
    data["cited"] = list(best.values())[:12]
    out = OUT / ("dashboard_hosted.html" if hosted else "dashboard.html")
    out.write_text(render(data, hosted), encoding="utf-8")
    print(f"Wrote {out.relative_to(ROOT)} from {path}: {sum(a['answers'] for a in data['assistants'])} answers, "
          f"{len(data['files'])} files")


VERIFIED_PAGES = ROOT / "verified_content.json"


def build(label, hosted=False):
    snap = read_json(ROOT / "dashboard_snapshot.json", {})
    rows = load_rows(label) if (DATA / "runs" / f"{label}.jsonl").exists() else []
    assistants, by = assistants_from_rows(rows)
    queries = [{"assistant": NAMES.get(r["provider"], r["provider"]), "query": r["query"], "category": r["intent"],
                "position": r.get("position"), "mentioned": r["mentioned"], "top": r.get("restaurants", [])[:4],
                "answer": (r.get("answer") or "")[:1800], "sources": r.get("cited_domains", [])[:6]} for r in rows]

    g = snap.get("gemini")
    if g and "gemini" not in by:  # Gemini runs recorded with aiso_agent
        n = sum(x["n"] for x in g["runs"])
        m = sum(x["mentioned"] for x in g["runs"])
        assistants.append({"name": "Gemini", "source": "snapshot: " + g["source"], "answers": n, "mentioned": m,
                           "rate": round(m / n, 3), "avg_rank": None, "value_weighted": None,
                           "by_category": {SNAP_CAT.get(k, k): v for k, v in g["by_category"].items()},
                           "rivals": g["rivals"], "runs": g["runs"]})
        from manual import infer_intent
        queries += [{"assistant": "Gemini", "query": q["query"], "category": infer_intent(q["query"]),
                     "position": q["position"], "mentioned": q["position"] is not None, "top": [],
                     "answer": "", "sources": [], "snapshot": True} for q in g["queries"]]

    cats = sorted({c for a in assistants for c in a["by_category"]}, key=lambda c: -VALUES.get(c, 0))
    rival_sets = [{norm(x).replace("pacific beach alehouse", "pb alehouse"): x for x in a["rivals"]} for a in assistants]
    both = sorted(set.intersection(*[set(s) for s in rival_sets])) if len(rival_sets) > 1 else []
    both = [rival_sets[0][k] for k in both]

    # Website comparison: live audit if it worked, otherwise the recorded one.
    site = read_json(DATA / "site_audit.json") or {}
    rivals_web = read_json(DATA / "competitor_sites.json", []) or []
    if site and "error" not in site and not site.get("mock"):
        cols = [TARGET["name"]] + [c["name"] for c in rivals_web if "error" not in c]
        def row(lbl, k_us, k_them):
            return [lbl, site.get(k_us)] + [c.get(k_them) for c in rivals_web if "error" not in c]
        checks = [row("Restaurant schema", "has_restaurant_schema", "has_restaurant_schema"),
                  row("FAQ schema", "has_faq_schema", "has_faq_schema"),
                  row("Menu schema", "has_menu_schema", "has_menu_schema"),
                  row("llms.txt", "has_llms_txt", "has_llms_txt"),
                  ["Menu prices as text", bool(site.get("html_menu_price_count"))]
                  + [bool(c.get("menu_price_count")) for c in rivals_web if "error" not in c]]
        site_view = {"columns": cols, "rows": checks, "source": "live audit by this agent"}
    else:
        sc = snap.get("site_compare", {})
        site_view = {"columns": sc.get("columns", []), "rows": sc.get("rows", []),
                     "source": "snapshot: " + sc.get("source", "")}

    cov = read_json(DATA / "source_coverage.json", []) or []
    cited = [{"domain": c.get("domain"), "athena": c.get("target_present") if c.get("status") == "ok" else None,
              "competitors": c.get("competitors_present", [])[:3], "cited": c.get("cited_in_answers")}
             for c in cov if c.get("domain")]
    # One row per site (OpenTable .ie/.co.uk etc. count as one), keeping the most informative check.
    best = {}
    for c in cited:
        key = re.sub(r"^(www\.|redirect\.|es\.)", "", c["domain"] or "")
        key = next((b + ".com" for b in ("opentable", "airbnb", "foursquare", "tripadvisor", "yelp") if b in key), key)
        old_c = best.get(key)
        rank = lambda x: (x["athena"] is not None, bool(x["competitors"]), x.get("cited") or 0)
        if old_c is None or rank(c) > rank(old_c):
            best[key] = {**c, "domain": key}
    cited = list(best.values())[:12]
    cited_source = "live check by this agent"
    if not any(c["athena"] is not None for c in cited):
        cited = [{"domain": c["domain"], "athena": c["athena"], "competitors": c.get("competitors", []),
                  "cited": f"{c['cited']:.0%} of Claude answers"} for c in snap.get("cited_claude", [])]
        cited_source = "snapshot: teammate's check of pages Claude cited"

    files = []
    for p, kind in [("restaurant_schema.jsonld", "Schema"), ("faq_schema.jsonld", "Schema"), ("llms.txt", "Site file"),
                    ("gbp_description.txt", "Google profile"), ("about.md", "About copy"), ("faq.html", "FAQ")]:
        if (OUT / p).exists():
            files.append({"name": p, "kind": kind, "content": (OUT / p).read_text(encoding="utf-8")})
    for d, kind in (("pages", "Page"), ("outreach", "Outreach")):
        for p in sorted((OUT / d).glob("*")) if (OUT / d).exists() else []:
            files.append({"name": f"{d}/{p.name}", "kind": kind, "content": p.read_text(encoding="utf-8")})
    if not any(f["kind"] == "Outreach" for f in files):
        from generate import template_outreach
        for c in [x for x in snap.get("cited_claude", []) if x["athena"] is False]:
            mail = template_outreach({"title": c["domain"], "final_url": "https://" + c["domain"],
                                      "competitors_present": c.get("competitors", [])})
            files.append({"name": f"outreach/{c['domain']}.txt", "kind": "Outreach",
                          "content": f"To: [VERIFY: editor contact for {c['domain']}]\nSubject: {mail['subject']}\n\n{mail['body']}\n"})

    exp = read_json(DATA / "experiment.json")
    data = {
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "restaurant": {**{k: TARGET.get(k) for k in ("name", "street", "city", "neighborhood", "founded", "phone",
                                                     "website", "cuisine", "highlights")},
                       "hours": hours_text() if TARGET.get("hours") else None},
        "actions_log": read_json(DATA / "actions_log.json", []) or [],
        "assistants": assistants, "categories": [{"key": c, "label": LABELS.get(c, c), "value": VALUES.get(c)} for c in cats],
        "queries": queries, "both_rivals": both,
        "head_to_head": read_json(DATA / "head_to_head.json", []) or [],
        "site": site_view, "cited": cited, "cited_source": cited_source,
        "trends": snap.get("trends", []), "conflicts": snap.get("conflicts", []), "plan": snap.get("plan", []),
        "sources": snap.get("sources", []), "files": files,
        "experiment": exp, "simulation": snap.get("simulation"),
        "query_bank": [{"query": q["query"], "intent": q["intent"], "value": q["value"],
                        "trends": q["query"] in TRENDS_QUERIES} for q in read_json(DATA / "queries.json", []) or []],
    }
    html = render(data, hosted)
    out = OUT / ("dashboard_hosted.html" if hosted else "dashboard.html")
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out.relative_to(ROOT)}: {len(assistants)} assistants, {len(queries)} answers, "
          f"{len(files)} files. Snapshot used for: "
          + (", ".join(x for x, used in [("Gemini", g and 'gemini' not in by),
                                        ("website audit", site_view['source'].startswith('snapshot')),
                                        ("cited pages", cited_source.startswith('snapshot'))] if used) or "nothing"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--hosted", action="store_true", help="version for sharing online (no live API tab)")
    ap.add_argument("--from-html", metavar="FILE", help="rebuild an existing dashboard.html in the current design")
    a = ap.parse_args()
    from_html(a.from_html, a.hosted) if a.from_html else build(a.label, a.hosted)
