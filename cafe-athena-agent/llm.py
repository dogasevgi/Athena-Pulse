"""Thin HTTP clients for each AI platform + helpers to parse answers.

Every ask_* function returns {"text": str, "citations": [{"url", "title"}]}.
Plain HTTP (no SDKs) so version drift can't break the demo.
"""
import json
import os
import re
import time
import unicodedata
from urllib.parse import urlparse

import requests

from config import EXTRACT_MODEL, MOCK, MODELS, TARGET, WRITER_MODEL

TIMEOUT = 120


def _post(url, headers, body, tries=5):
    last = None
    for i in range(tries):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=TIMEOUT)
        except requests.RequestException as e:
            last = str(e)
            time.sleep(2 * (i + 1))
            continue
        if r.status_code == 429 and re.search(r"limit:\s*0\b", r.text):
            # Free tiers sometimes give a model (or its search tool) zero quota: retrying can't help.
            raise RuntimeError("429: this key has no free quota for this model/tool. Set GEMINI_MODEL to a "
                               "'-lite' model, or run without web search. " + r.text[:200])
        if r.status_code in (429, 500, 502, 503, 529):
            last = f"{r.status_code}: {r.text[:200]}"
            m = re.search(r'"retryDelay":\s*"(\d+)', r.text)  # Gemini says how long to wait
            time.sleep(min(int(m.group(1)) + 1, 90) if m else 3 * (i + 1) ** 2)
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"{r.status_code}: {r.text[:400]}")
        return r.json()
    raise RuntimeError(f"gave up after {tries} tries ({last})")


def _dedupe(cites):
    seen, out = set(), []
    for c in cites:
        u = c.get("url")
        if u and u not in seen:
            seen.add(u)
            out.append(c)
    return out


# ---------------------------------------------------------------- providers
def ask_anthropic(query, system=None, search=True, model=None, max_tokens=1500):
    body = {
        "model": model or MODELS["anthropic"],
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": query}],
    }
    if system:
        body["system"] = system
    if search:
        body["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]
    d = _post(
        "https://api.anthropic.com/v1/messages",
        {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
         "content-type": "application/json"},
        body,
    )
    text, cites = [], []
    for b in d.get("content", []):
        if b.get("type") == "text":
            text.append(b.get("text", ""))
            for c in b.get("citations") or []:
                if c.get("url"):
                    cites.append({"url": c["url"], "title": c.get("title", "")})
    return {"text": "".join(text), "citations": _dedupe(cites)}


def ask_openai(query, system=None, search=True, model=None, max_tokens=None):
    body = {"model": model or MODELS["openai"], "input": query}
    if system:
        body["instructions"] = system
    headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}
    if search:
        body["tools"] = [{"type": "web_search"}]
    try:
        d = _post("https://api.openai.com/v1/responses", headers, body)
    except RuntimeError as e:  # older accounts/models use the preview tool name
        if search and "web_search" in str(e):
            body["tools"] = [{"type": "web_search_preview"}]
            d = _post("https://api.openai.com/v1/responses", headers, body)
        else:
            raise
    text, cites = [], []
    for item in d.get("output", []):
        if item.get("type") != "message":
            continue
        for c in item.get("content", []):
            if c.get("type") == "output_text":
                text.append(c.get("text", ""))
                for a in c.get("annotations", []):
                    if a.get("type") == "url_citation" and a.get("url"):
                        cites.append({"url": a["url"], "title": a.get("title", "")})
    return {"text": "".join(text), "citations": _dedupe(cites)}


_GEMINI_AUTO = {}


def pick_gemini_model():
    """Newest stable Flash model this key can use (prefers non-preview, then '-lite' last)."""
    if "model" not in _GEMINI_AUTO:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                         headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                         params={"pageSize": 200}, timeout=30)
        r.raise_for_status()
        names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
        bad = ("image", "tts", "audio", "live", "embedding", "thinking", "exp", "native", "omni")

        def score(n):
            v = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
            return ("preview" not in n, float(v.group(1)) if v else 0, "lite" not in n)
        pool = [n for n in names if "flash" in n and not any(b in n for b in bad)]
        if not pool:
            raise RuntimeError(f"no usable Gemini Flash model for this key: {names[:8]}")
        _GEMINI_AUTO["model"] = max(pool, key=score)
        print(f"  Gemini model not available; using {_GEMINI_AUTO['model']} (set GEMINI_MODEL to choose)")
    return _GEMINI_AUTO["model"]


def ask_gemini(query, system=None, search=True, model=None, max_tokens=None):
    m = model or _GEMINI_AUTO.get("model") or MODELS["gemini"]
    body = {"contents": [{"role": "user", "parts": [{"text": query}]}]}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if search:
        body["tools"] = [{"google_search": {}}]
    headers = {"x-goog-api-key": os.environ["GEMINI_API_KEY"], "content-type": "application/json"}
    url = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
    try:
        d = _post(url.format(m), headers, body)
    except RuntimeError as e:
        # Model names retire often: if the default is gone, switch to one this key can use.
        if not str(e).startswith("404") or model or os.getenv("GEMINI_MODEL"):
            raise
        d = _post(url.format(pick_gemini_model()), headers, body)
    cand = (d.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
    cites = []
    for ch in cand.get("groundingMetadata", {}).get("groundingChunks", []):
        w = ch.get("web") or {}
        if w.get("uri"):
            # Gemini returns redirect URLs; the title holds the real domain.
            cites.append({"url": w["uri"], "title": w.get("title", "")})
    return {"text": text, "citations": _dedupe(cites)}


def ask_perplexity(query, system=None, search=True, model=None, max_tokens=None):
    msgs = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": query}]
    d = _post(
        "https://api.perplexity.ai/chat/completions",
        {"Authorization": f"Bearer {os.environ['PERPLEXITY_API_KEY']}"},
        {"model": model or MODELS["perplexity"], "messages": msgs},
    )
    text = d["choices"][0]["message"]["content"]
    results = d.get("search_results") or [{"url": u} for u in d.get("citations", [])]
    cites = [{"url": r["url"], "title": r.get("title", "")} for r in results if r.get("url")]
    return {"text": text, "citations": _dedupe(cites)}


PROVIDERS = {
    "anthropic": (ask_anthropic, "ANTHROPIC_API_KEY"),
    "openai": (ask_openai, "OPENAI_API_KEY"),
    "gemini": (ask_gemini, "GEMINI_API_KEY"),
    "perplexity": (ask_perplexity, "PERPLEXITY_API_KEY"),
}


def available():
    return [name for name, (_, env) in PROVIDERS.items() if os.getenv(env)]


# ------------------------------------------------------- plain completions
def complete(prompt, system=None, max_tokens=4000, model=None):
    """Non-search completion for parsing, diagnosis, and writing."""
    if MOCK:
        return mock_complete(prompt, system or "")
    if os.getenv("ANTHROPIC_API_KEY"):
        return ask_anthropic(prompt, system=system, search=False,
                             model=model or WRITER_MODEL, max_tokens=max_tokens)["text"]
    if os.getenv("OPENAI_API_KEY"):
        return ask_openai(prompt, system=system, search=False)["text"]
    if os.getenv("GEMINI_API_KEY"):
        return ask_gemini(prompt, system=system, search=False)["text"]
    raise RuntimeError("Need ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY for completions")


def parse_json(text):
    """Pull the first JSON object/array out of a model reply."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    if start == -1:
        raise ValueError("no JSON found")
    return json.JSONDecoder().raw_decode(text[start:])[0]


EXTRACT_SYSTEM = (
    "You extract restaurant recommendations from an AI assistant's answer. "
    "Return ONLY JSON: {\"restaurants\": [\"Name 1\", \"Name 2\", ...]} listing every "
    "restaurant, bar, cafe, or caterer the answer recommends, in order of first appearance. "
    "Use the business name only (no neighborhood or descriptors). Empty list if none."
)


def extract_restaurants(answer_text):
    if not answer_text.strip():
        return []
    model = EXTRACT_MODEL if os.getenv("ANTHROPIC_API_KEY") else None
    try:
        out = complete(answer_text[:12000], system=EXTRACT_SYSTEM, max_tokens=800, model=model)
        names = parse_json(out).get("restaurants", [])
        return [n.strip() for n in names if isinstance(n, str) and n.strip()]
    except Exception:
        return []


# ---------------------------------------------------------------- matching
def norm(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"^the ", "", s.strip())
    return re.sub(r"\s+", " ", s).strip()


def is_target(name):
    n = norm(name)
    return any(norm(a) in n for a in TARGET["aliases"])


def mentions_target(text):
    t = norm(text)
    return any(norm(a) in t for a in TARGET["aliases"])


BRANDS = ("opentable", "airbnb", "foursquare", "tripadvisor", "yelp", "ubereats", "doordash",
          "atly", "happycow", "zola", "theknot", "peerspace", "wanderlog", "findmeglutenfree")


def domain_of(cite):
    host = urlparse(cite.get("url", "")).netloc.lower().removeprefix("www.")
    if "vertexaisearch" in host or "googleusercontent" in host:
        host = (cite.get("title") or host).lower().removeprefix("www.")
    labels = host.split(".")
    for b in BRANDS:  # opentable.ie / opentable.co.uk / es.foursquare.com -> one brand
        if b in labels:
            return b + ".com"
    return host


# ------------------------------------------------------------------ mock mode
MOCK_POOL = ["Mock Taverna", "Sample Mezze House", "Placeholder Grill", "Demo Kitchen PB",
             "Example Oyster Bar", "Test Tapas Co"]


def names_from_list(text):
    """Pull names from numbered/bulleted lines like '1. **Name** - why'."""
    out = []
    for line in text.splitlines():
        m = re.match(r"\s*(?:\d+[.)]|[-*•])\s*\**([^*\n\-–:]+?)\**\s*(?:[-–:(]|$)", line)
        if m and m.group(1).strip():
            out.append(m.group(1).strip())
    return out


def mock_complete(prompt, system):
    """Deterministic stand-in for an LLM so the whole loop runs offline.
    Clearly fake: it never invents facts about real businesses."""
    import random
    rng = random.Random(prompt[:500])
    if "extract restaurant" in system.lower():
        return json.dumps({"restaurants": names_from_list(prompt)})
    if "AI search assistant" in system:
        names = rng.sample(MOCK_POOL, 4)
        # Our new page is in the context: give it a fair shot at being picked.
        if "/new-page" in prompt and rng.random() < 0.65:
            names.insert(rng.randint(0, 2), TARGET["name"])
        elif TARGET["domain"] in prompt and rng.random() < 0.15:
            names.insert(3, TARGET["name"])
        return "\n".join(f"{i+1}. **{n}** - matches the question" for i, n in enumerate(names))
    raise RuntimeError("mock mode: no canned reply for this prompt")
