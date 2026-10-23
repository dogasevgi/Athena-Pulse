"""Stage 2b - Head to head: for every rival that beats the target in at least one kind of
request, how far ahead it is and what sets it apart. Writes data/head_to_head.json.

Evidence, strongest first:
  1. What the answers SAY about the rival vs. the target (reason themes in the sentences)
  2. What the answers CITE (domains in answers naming the rival vs. naming the target)
  3. What the WEBSITES show (data/competitor_sites.json vs. data/site_audit.json)

    python3 compare.py --label baseline
"""
import argparse
import re
from collections import Counter, defaultdict

from analyze import load_rows
from config import DATA, TARGET, read_json, write_json
from llm import is_target, norm

THEMES = {
    "happy hour and value": ["happy hour", "deal", "affordable", "cheap", "value", "small plates", "tapas"],
    "cocktails and bar": ["cocktail", "drinks", "wine list", "mixolog", "craft beer"],
    "views, patio or atmosphere": ["patio", "view", "ocean", "waterfront", "oceanfront", "ambiance", "atmosphere",
                                   "cozy", "romantic", "vibe", "outdoor", "rooftop", "lively"],
    "private events and groups": ["private", "event", "group", "party", "rehearsal", "catering", "banquet"],
    "dietary options": ["vegan", "vegetarian", "gluten"],
    "reviews and reputation": ["review", "rated", "popular", "favorite", "locals", "award", "institution",
                               "beloved", "well-known", "go-to"],
    "authentic food": ["authentic", "traditional", "family recipe", "homemade", "scratch", "fresh"],
    "location": ["walk", "near the beach", "steps from", "parking", "boardwalk", "beachfront"],
    "longevity": ["since 19", "since 20", "long-running", "decades", "longest"],
}
MIN_DIFF = 0.2      # a theme or source counts as a difference at 20+ points apart
MIN_SNIPPETS = 3    # below this, the target is mentioned too rarely to compare descriptions
SPLIT = re.compile(r"\n(?=\s*(?:\d+[.)]|[-*•]|\*\*|#+ ))")


def snippets(answer, name):
    key = norm(name)
    chunks = [c for part in answer.split("\n\n") for c in SPLIT.split(part)]
    if len(chunks) == 1:  # prose answers: fall back to sentences
        chunks = re.split(r"(?<=[.!?])\s+", answer)
    return [c.strip() for c in chunks if key and key in norm(c)]


def themes(snips):
    c = Counter()
    for s in snips:
        low = s.lower()
        for t, words in THEMES.items():
            if any(w in low for w in words):
                c[t] += 1
    return c


def named(row, key):
    return any(norm(n) == key for n in row.get("restaurants", []))


def build(label):
    rows = load_rows(label)
    if not rows:
        raise SystemExit(f"No rows for {label}")
    by_intent = defaultdict(list)
    for r in rows:
        by_intent[r["intent"]].append(r)

    # Leader of each kind of request (the most-named rival).
    display, wins = {}, defaultdict(list)
    for intent, rs in by_intent.items():
        c = Counter()
        for r in rs:
            for n in {norm(x): x for x in r.get("restaurants", []) if not is_target(x)}.items():
                c[n[0]] += 1
                display.setdefault(n[0], n[1])
        if not c:
            continue
        k, cnt = c.most_common(1)[0]
        us = sum(r["mentioned"] for r in rs)
        if cnt > us:
            wins[k].append(intent)

    us_snips = [s for r in rows if r["mentioned"] for n in r.get("restaurants", []) if is_target(n)
                for s in snippets(r["answer"], n)]
    if not us_snips:
        us_snips = [s for r in rows if r["mentioned"] for a in TARGET["aliases"] for s in snippets(r["answer"], a)]
    us_t = themes(us_snips)
    site = read_json(DATA / "site_audit.json") or {}
    rival_sites = {norm(c["name"]): c for c in read_json(DATA / "competitor_sites.json", []) if "error" not in c}

    out = []
    for k, intents in wins.items():
        name = display[k]
        sub = [r for r in rows if r["intent"] in intents]
        lead = [r for r in sub if named(r, k)]
        lost = [r for r in lead if not r["mentioned"]]
        both = [r for r in lead if r.get("position")]
        ahead = sum(1 for r in both
                    if next(i for i, n in enumerate(r["restaurants"], 1) if norm(n) == k) < r["position"])
        snips = [s for r in rows for s in snippets(r["answer"], name)]
        lt = themes(snips)
        nl, nu = max(len(snips), 1), max(len(us_snips), 1)
        said = []
        for t in THEMES:
            l, u = lt[t] / nl, us_t[t] / nu
            if l - u >= MIN_DIFF and lt[t] >= 2:
                ex = next((s for s in snips if any(w in s.lower() for w in THEMES[t])), "")
                said.append({"theme": t, "rival": round(l, 2), "target": round(u, 2),
                             "example": re.sub(r"[*#]", "", ex)[:200]})
        cites_l = Counter(d for r in lead for d in set(r.get("cited_domains", [])))
        cites_u = Counter(d for r in rows if r["mentioned"] for d in set(r.get("cited_domains", [])))
        n_us = max(sum(r["mentioned"] for r in rows), 1)
        src = [{"domain": d, "rival": round(c / max(len(lead), 1), 2), "target": round(cites_u[d] / n_us, 2)}
               for d, c in cites_l.most_common(8) if c / max(len(lead), 1) - cites_u[d] / n_us >= MIN_DIFF]
        rs = rival_sites.get(k) or next((v for kk, v in rival_sites.items() if kk in k or k in kk), None)
        web = []
        if rs:
            for label_, key in (("Restaurant schema", "has_restaurant_schema"), ("FAQ schema", "has_faq_schema"),
                                ("Menu schema", "has_menu_schema"), ("llms.txt", "has_llms_txt")):
                if rs.get(key) and not site.get(key):
                    web.append(label_)
            if rs.get("menu_price_count") and not site.get("html_menu_price_count"):
                web.append("menu prices as text")
        out.append({
            "rival": name, "wins": sorted(intents),
            "rival_rate": round(len(lead) / len(sub), 3),
            "target_rate": round(sum(r["mentioned"] for r in sub) / len(sub), 3),
            "answers": len(sub), "lost": len(lost), "lost_value": sum(r["value"] for r in lost),
            "both_named": len(both), "rival_ahead": ahead,
            "said": said,
            "target_mentions_too_rare": len(us_snips) < MIN_SNIPPETS,
            "sources": src, "website": web, "website_checked": bool(rs),
        })
    out.sort(key=lambda x: (-x["lost_value"], -x["lost"]))
    write_json(DATA / "head_to_head.json", out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="baseline")
    res = build(ap.parse_args().label)
    for x in res:
        print(f"{x['rival']}: leads {', '.join(x['wins'])}; {x['rival_rate']:.0%} vs {x['target_rate']:.0%}, "
              f"{x['lost']} answers lost (~${x['lost_value']:,})")
        for d in x["said"]:
            print(f"   praised for {d['theme']}: {d['rival']:.0%} vs {d['target']:.0%}")
        if x["website"]:
            print(f"   its site has, ours doesn't: {', '.join(x['website'])}")
