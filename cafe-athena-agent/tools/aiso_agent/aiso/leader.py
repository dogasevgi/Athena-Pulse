"""Who beats Café Athena, by how much, and why.

For the overall leader and for the leader of each query category, this computes:

  How far behind   mention-rate gap (percentage points), average rank of each,
                   answers that named the leader but not Café Athena, and
                   head-to-head order when both were named.
  Why (3 kinds of evidence, strongest first)
    1. What the assistants SAID: the sentences about the leader are tagged with
       reason themes (happy hour, patio, private events, reviews...), and compared
       with what they say about Café Athena when it does appear.
    2. What the assistants READ: domains cited in answers that name the leader
       vs. answers that name Café Athena (needs web-search platforms).
    3. What the WEBSITES say: if the leader's site was audited, which topics and
       schema it has that Café Athena's site lacks.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from urllib.parse import urlparse

from .config import BOOKING_VALUE
from .extract import is_target, norm

THEMES = {
    "happy hour and value": ["happy hour", "deal", "affordable", "cheap", "value", "small plates", "tapas"],
    "cocktails and bar": ["cocktail", "bar ", "drinks", "wine list", "mixolog"],
    "atmosphere, patio or views": ["patio", "view", "ocean", "waterfront", "ambiance", "atmosphere",
                                   "cozy", "romantic", "vibe", "outdoor", "dimly", "lively"],
    "private events and groups": ["private", "event", "group", "party", "rehearsal", "catering",
                                  "banquet", "large parties"],
    "dietary options": ["vegan", "vegetarian", "gluten"],
    "reviews and reputation": ["review", "rated", "popular", "favorite", "locals", "award",
                               "institution", "beloved", "well-known", "go-to"],
    "authentic food": ["authentic", "traditional", "family recipe", "homemade", "scratch", "fresh"],
    "location and convenience": ["walk", "near the beach", "steps from", "parking", "central"],
    "longevity": ["since 19", "since 20", "long-running", "decades", "years"],
}
# Website topic terms (audit.SIGNAL_TERMS keys) that address each theme
THEME_TO_SITE = {
    "happy hour and value": "happy_hour", "cocktails and bar": "date_night",
    "atmosphere, patio or views": "date_night", "private events and groups": "events",
    "dietary options": "dietary", "authentic food": "cuisine",
}
_ITEM_SPLIT = re.compile(r"\n(?=\s*(?:\d+[.)]|[-*•]|\*\*|#+ ))")
_DOMAIN = re.compile(r"https?://([^/\s)\]]+)|\b([a-z0-9-]+\.(?:com|org|net|co|io|test))\b", re.I)


def _snippets(answer: str, name: str) -> list[str]:
    """The list items / paragraphs of an answer that talk about `name`."""
    key = norm(name)
    chunks = [c for part in answer.split("\n\n") for c in _ITEM_SPLIT.split(part)]
    return [c.strip() for c in chunks if key and key in norm(c)]


def _themes(snips: list[str]) -> Counter:
    c = Counter()
    for s in snips:
        low = s.lower() + " "
        for theme, words in THEMES.items():
            if any(w in low for w in words):
                c[theme] += 1
    return c


def _domains(row) -> set[str]:
    src = row.get("sources") or []
    if not src:  # manual-mode answers: fall back to links written in the text
        src = ["".join(m) for m in _DOMAIN.findall(row["answer"])]
    out = set()
    for s in src:
        host = urlparse(s).netloc if "://" in s else s
        host = host.lower().removeprefix("www.")
        if host:
            out.add(host)
    return out


def _rank(row, name_key):
    for i, n in enumerate(row["restaurants"], 1):
        if norm(n) == name_key:
            return i
    return None


def _gap(rows, leader_key, aliases):
    n = len(rows)
    lead = [r for r in rows if _rank(r, leader_key)]
    us = [r for r in rows if r["target_pos"]]
    both = [r for r in rows if r["target_pos"] and _rank(r, leader_key)]
    ahead = sum(1 for r in both if _rank(r, leader_key) < r["target_pos"])
    avg = lambda xs: round(sum(xs) / len(xs), 2) if xs else None
    return {
        "answers": n,
        "leader_rate": round(len(lead) / n, 3),
        "athena_rate": round(len(us) / n, 3),
        "gap_pts": round(100 * (len(lead) - len(us)) / n, 1),
        "leader_avg_rank": avg([_rank(r, leader_key) for r in lead]),
        "athena_avg_rank": avg([r["target_pos"] for r in us]),
        "lost_to_leader": sum(1 for r in lead if not r["target_pos"]),
        "lost_value": sum(BOOKING_VALUE.get(r["category"], 50) for r in lead if not r["target_pos"]),
        "both_named": len(both),
        "leader_ahead": ahead,
        "athena_ahead": len(both) - ahead,
    }


def _leader(rows, aliases):
    c, display = Counter(), {}
    for r in rows:
        for n in r["restaurants"]:
            if not is_target(n, aliases):
                k = norm(n)
                display.setdefault(k, n)
                c[k] += 1
    if not c:
        return None, None
    k = c.most_common(1)[0][0]
    return k, display[k]


def _why(rows, leader_name, aliases, top=4):
    lead_snips, us_snips, examples = [], [], {}
    for r in rows:
        ls = _snippets(r["answer"], leader_name)
        lead_snips += ls
        us_snips += [s for n in r["restaurants"] if is_target(n, aliases)
                     for s in _snippets(r["answer"], n)]
        for s in ls:
            for t in _themes([s]):
                examples.setdefault(t, re.sub(r"[*#]", "", s)[:160])
    lt, ut = _themes(lead_snips), _themes(us_snips)
    nl, nu = max(len(lead_snips), 1), max(len(us_snips), 1)
    out = []
    for theme, cnt in lt.most_common(top):
        out.append({"theme": theme, "leader_share": round(cnt / nl, 2),
                    "athena_share": round(ut[theme] / nu, 2) if us_snips else None,
                    "example": examples.get(theme)})
    return out, len(lead_snips), len(us_snips)


def _sources(rows, leader_key):
    lead_rows = [r for r in rows if _rank(r, leader_key)]
    us_rows = [r for r in rows if r["target_pos"]]
    if not any(_domains(r) for r in rows):
        return []
    lc = Counter(d for r in lead_rows for d in _domains(r))
    uc = Counter(d for r in us_rows for d in _domains(r))
    out = []
    for d, cnt in lc.most_common(8):
        lr = cnt / max(len(lead_rows), 1)
        ur = uc[d] / max(len(us_rows), 1) if us_rows else 0
        out.append({"domain": d, "leader_answers": round(lr, 2), "athena_answers": round(ur, 2),
                    "gap": round(lr - ur, 2)})
    return sorted(out, key=lambda x: -x["gap"])


def _site_compare(leader_name, audits):
    if not audits:
        return None
    target = audits["target"]
    comp = next((c for c in audits["competitors"] if norm(c["name"]) == norm(leader_name)), None)
    if not comp:
        return None
    rows = []
    for topic, terms in comp["coverage"].items():
        rows.append({"topic": topic, "leader": bool(terms), "athena": bool(target["coverage"].get(topic))})
    for label, key in (("Restaurant schema", "has_restaurant_schema"),
                       ("FAQ schema", "has_faq_schema"), ("Menu schema", "has_menu_schema")):
        rows.append({"topic": label, "leader": comp[key], "athena": target[key]})
    rows.append({"topic": "Menu prices as text", "leader": comp.get("price_count", 0) > 0,
                 "athena": target.get("price_count", 0) > 0})
    rows.append({"topic": "llms.txt", "leader": bool(comp.get("has_llms_txt")),
                 "athena": bool(target.get("has_llms_txt"))})
    rows.append({"topic": "words on site", "leader": comp["word_count"], "athena": target["word_count"]})
    return rows


def _explain(gap, why, sources, site, leader):
    """Plain-English reasons, built only from the evidence above."""
    reasons = []
    for w in why[:3]:
        a = w["athena_share"]
        if a is None:
            reasons.append(f"Assistants praise {leader} for {w['theme']} "
                           f"({w['leader_share']:.0%} of its mentions); Café Athena is rarely named at all.")
        elif w["leader_share"] - a >= 0.2:
            reasons.append(f"Assistants praise {leader} for {w['theme']} in {w['leader_share']:.0%} of its "
                           f"mentions vs. {a:.0%} for Café Athena.")
    for s in sources[:2]:
        if s["gap"] >= 0.2:
            reasons.append(f"{s['domain']} is cited in {s['leader_answers']:.0%} of answers naming {leader} "
                           f"but {s['athena_answers']:.0%} naming Café Athena.")
    for r in site or []:
        if r["topic"] in THEME_TO_SITE.values() and r["leader"] and not r["athena"]:
            reasons.append(f"{leader}'s website covers {r['topic'].replace('_', ' ')}; Café Athena's doesn't.")
    if gap["both_named"] and gap["leader_ahead"] > gap["athena_ahead"]:
        reasons.append(f"When both are named, {leader} is listed first {gap['leader_ahead']} of "
                       f"{gap['both_named']} times.")
    return reasons


def analyze(rows: list[dict], aliases: list[str], audits: dict | None = None, llm=None) -> dict:
    lk, lname = _leader(rows, aliases)
    if not lk:
        return {}
    why, n_lead, n_us = _why(rows, lname, aliases)
    srcs = _sources(rows, lk)
    site = _site_compare(lname, audits)
    overall = {"leader": lname, **_gap(rows, lk, aliases), "why": why, "sources": srcs,
               "site": site, "leader_snippets": n_lead, "athena_snippets": n_us}
    overall["reasons"] = _explain(overall, why, srcs, site, lname)

    by_cat = {}
    groups = defaultdict(list)
    for r in rows:
        groups[r["category"]].append(r)
    for cat, sub in sorted(groups.items()):
        k, name = _leader(sub, aliases)
        if not k:
            continue
        g = _gap(sub, k, aliases)
        w, _, _ = _why(sub, name, aliases, top=2)
        s = _sources(sub, k)
        by_cat[cat] = {"leader": name, **g, "why": w, "sources": s[:2],
                       "reasons": _explain(g, w, s, _site_compare(name, audits), name)}

    # names that look like Café Athena but aren't matched to it (e.g. "Athenas Catering")
    key = norm(aliases[0]).split()[-1]  # "athena"
    variants = Counter(n for r in rows for n in r["restaurants"]
                       if key in norm(n) and not is_target(n, aliases))
    out = {"overall": overall, "by_category": by_cat,
           "name_variants": [{"name": n, "count": c} for n, c in variants.most_common()],
           "same_leader_everywhere": len({v["leader"] for v in by_cat.values()}) == 1}
    if llm is not None and not llm.is_mock:
        out["narrative"] = llm.ask(
            "Using ONLY this JSON evidence, explain to the owner of Café Athena in 4 plain sentences "
            "who is beating them in AI assistant answers, by how much, and why. Cite numbers. "
            "Do not invent facts.\n\n" + json.dumps(out, indent=1)[:12000])
    return out


def print_report(a: dict):
    o = a["overall"]
    print(f"\n=== Overall leader: {o['leader']} ===")
    print(f"Named in {o['leader_rate']:.0%} of answers vs Café Athena {o['athena_rate']:.0%} "
          f"({o['gap_pts']:+} pts). Avg rank {o['leader_avg_rank']} vs {o['athena_avg_rank']}.")
    print(f"Answers that named {o['leader']} but not Café Athena: {o['lost_to_leader']}. "
          f"Head-to-head: leader ahead {o['leader_ahead']}/{o['both_named']}.")
    print("Why:")
    for r in o["reasons"] or ["Not enough evidence yet; run more queries or audit the leader's site."]:
        print(f"  - {r}")
    print("\nBy category:")
    for cat, c in a["by_category"].items():
        print(f"  {cat:<11} {c['leader']:<28} {c['leader_rate']:>4.0%} vs {c['athena_rate']:>4.0%} "
              f"({c['gap_pts']:+.0f} pts)  lost {c['lost_to_leader']}")
        for r in c["reasons"][:2]:
            print(f"      - {r}")
    for v in a.get("name_variants", []):
        print(f"\nName variant: assistants said \"{v['name']}\" {v['count']}x. If that's Café Athena, "
              "connect the names on the site and listings.")
    if a.get("narrative"):
        print("\n" + a["narrative"])


# ------------------------------------------------- per-leader comparison ---
MIN_DIFF = 0.2  # a theme/source counts as a difference at 20+ points apart


def _profile(rows, name, aliases):
    """Theme shares and an example sentence for one restaurant, across all answers."""
    if name is None:
        snips = [s for r in rows for n in r["restaurants"] if is_target(n, aliases)
                 for s in _snippets(r["answer"], n)]
    else:
        snips = [s for r in rows for s in _snippets(r["answer"], name)]
    counts = _themes(snips)
    examples = {}
    for s in snips:
        for t in _themes([s]):
            examples.setdefault(t, re.sub(r"[*#]", "", s).strip()[:180])
    n = max(len(snips), 1)
    return {"n": len(snips), "share": {t: counts[t] / n for t in THEMES}, "examples": examples}


def per_leader(a: dict, rows: list[dict], aliases: list[str], audits: dict | None = None) -> list[dict]:
    """One side-by-side comparison for every restaurant that leads at least one category."""
    wins = defaultdict(list)
    for cat, c in a["by_category"].items():
        if c["gap_pts"] > 0:
            wins[c["leader"]].append(cat)
    us = _profile(rows, None, aliases)
    out = []
    for name, cats in wins.items():
        k = norm(name)
        sub = [r for r in rows if r["category"] in cats]
        lp = _profile(rows, name, aliases)
        said, ours = [], []
        for t in THEMES:
            l, u = lp["share"][t], us["share"][t]
            if l - u >= MIN_DIFF:
                said.append({"theme": t, "leader": round(l, 2), "athena": round(u, 2),
                             "example": lp["examples"].get(t)})
            elif u - l >= MIN_DIFF:
                ours.append({"theme": t, "leader": round(l, 2), "athena": round(u, 2),
                             "example": us["examples"].get(t)})
        said.sort(key=lambda d: d["athena"] - d["leader"])
        site = _site_compare(name, audits) or []
        out.append({
            "leader": name, "wins": cats, **_gap(sub, k, aliases),
            "leader_snippets": lp["n"], "athena_snippets": us["n"],
            "said_gaps": said,                       # praised for this, Café Athena isn't
            "athena_edges": ours,                    # Café Athena is praised for this, leader isn't
            "source_gaps": [s for s in _sources(rows, k) if s["gap"] >= MIN_DIFF],
            "site_gaps": [r for r in site if r["leader"] is True and r["athena"] is False],
            "site_compared": bool(site),
        })
    out.sort(key=lambda x: (-x["lost_value"], -x["lost_to_leader"]))
    return out


def print_per_leader(pl: list[dict]):
    for p in pl:
        cats = ", ".join(c.replace("_", " ") for c in p["wins"])
        print(f"\n=== Café Athena vs {p['leader']} (leads: {cats}) ===")
        print(f"In those categories: {p['leader_rate']:.0%} vs {p['athena_rate']:.0%} "
              f"({p['gap_pts']:+.0f} pts), {p['lost_to_leader']} answers lost to it "
              f"(~${p['lost_value']:,} of bookings at stake).")
        print("What assistants say about it that they don't say about Café Athena:")
        for d in p["said_gaps"] or [{"theme": "(nothing distinct yet)", "leader": 0, "athena": 0}]:
            print(f"  - {d['theme']:<28} {d['leader']:.0%} vs {d['athena']:.0%}")
        if p["athena_edges"]:
            print("Where Café Athena is described better:")
            for d in p["athena_edges"]:
                print(f"  + {d['theme']:<28} {d['athena']:.0%} vs {d['leader']:.0%}")
        if p["source_gaps"]:
            print("Sources that cite it more:")
            for s in p["source_gaps"][:4]:
                print(f"  - {s['domain']:<28} {s['leader_answers']:.0%} vs {s['athena_answers']:.0%}")
        if p["site_gaps"]:
            print("Its website has, Café Athena's doesn't: "
                  + ", ".join(r["topic"].replace("_", " ") for r in p["site_gaps"]))
        elif not p["site_compared"]:
            print(f"Website not compared: add {p['leader']} to COMPETITOR_SITES and run `audit`.")
