"""Thin wrappers around the AI platforms we test against.

Each provider exposes .ask(prompt, system=None) -> str and a .name.
Model names are configurable via environment variables because they change often.

  ANTHROPIC_API_KEY  (+ ANTHROPIC_MODEL)
  OPENAI_API_KEY     (+ OPENAI_MODEL)
  GEMINI_API_KEY     (+ GEMINI_MODEL)
  PERPLEXITY_API_KEY (+ PERPLEXITY_MODEL)

The "-web" variants turn on each platform's live web search, which is much closer
to what a real consumer sees than a bare model answering from training data.

MockProvider produces FAKE answers with placeholder competitor names so the whole
pipeline can be demoed and tested without keys. Never present mock numbers as real.
"""
from __future__ import annotations
import hashlib
import os
import random
import re
import time

import requests

from .queries import categorize

TIMEOUT = 120


class Provider:
    name = "base"
    is_mock = False
    last_sources: list = []  # URLs or domains the last answer cited, when the API exposes them

    def ask(self, prompt: str, system: str | None = None) -> str:
        raise NotImplementedError


class AnthropicProvider(Provider):
    def __init__(self, web_search: bool = False):
        self.key = os.environ["ANTHROPIC_API_KEY"]
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
        self.web_search = web_search
        self.name = "claude-web" if web_search else "claude"

    def ask(self, prompt, system=None):
        body = {"model": self.model, "max_tokens": 1500,
                "messages": [{"role": "user", "content": prompt}]}
        if system:
            body["system"] = system
        if self.web_search:
            body["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": self.key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json=body, timeout=TIMEOUT)
        r.raise_for_status()
        blocks = r.json()["content"]
        urls = []
        for b in blocks:
            for c in b.get("citations") or []:
                urls.append(c.get("url"))
            if b.get("type") == "web_search_tool_result" and isinstance(b.get("content"), list):
                urls += [x.get("url") for x in b["content"]]
        self.last_sources = [u for u in dict.fromkeys(urls) if u]
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


class _ChatCompletions(Provider):
    url = ""
    key_env = ""
    model_env = ""
    default_model = ""

    def __init__(self):
        self.key = os.environ[self.key_env]
        self.model = os.getenv(self.model_env, self.default_model)

    def ask(self, prompt, system=None):
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
        r = requests.post(self.url, headers={"Authorization": f"Bearer {self.key}"},
                          json={"model": self.model, "messages": msgs}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        self.last_sources = list(data.get("citations") or
                                 [x.get("url") for x in data.get("search_results") or []])
        return data["choices"][0]["message"]["content"]


class OpenAIProvider(_ChatCompletions):
    name = "gpt"
    url = "https://api.openai.com/v1/chat/completions"
    key_env, model_env, default_model = "OPENAI_API_KEY", "OPENAI_MODEL", "gpt-4o"


class PerplexityProvider(_ChatCompletions):
    """Perplexity's sonar models search the live web by default."""
    name = "perplexity"
    url = "https://api.perplexity.ai/chat/completions"
    key_env, model_env, default_model = "PERPLEXITY_API_KEY", "PERPLEXITY_MODEL", "sonar"


GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def pick_gemini_model(key: str) -> str:
    """Ask the API which models this key can use and pick the newest stable Flash model."""
    r = requests.get(f"{GEMINI_BASE}/models", headers={"x-goog-api-key": key},
                     params={"pageSize": 200}, timeout=30)
    r.raise_for_status()
    names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    bad = ("image", "tts", "audio", "live", "embedding", "thinking", "exp", "native")

    def score(n):
        v = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        return ("preview" not in n, float(v.group(1)) if v else 0, "lite" not in n, -len(n))
    flash = [n for n in names if "flash" in n and not any(b in n for b in bad)]
    pool = flash or [n for n in names if n.startswith("gemini") and not any(b in n for b in bad)]
    if not pool:
        raise RuntimeError(f"No usable Gemini model for this key. Available: {names[:10]}")
    return max(pool, key=score)


class GeminiProvider(Provider):
    _auto_model = None  # found once per run, shared by all Gemini providers

    def __init__(self, grounded: bool = False):
        self.key = os.environ["GEMINI_API_KEY"]
        self.model = os.getenv("GEMINI_MODEL")
        if not self.model:
            if GeminiProvider._auto_model is None:
                GeminiProvider._auto_model = pick_gemini_model(self.key)
                print(f"  Using Gemini model: {GeminiProvider._auto_model} "
                      "(set GEMINI_MODEL to override)")
            self.model = GeminiProvider._auto_model
        self.grounded = grounded
        self.name = "gemini-web" if grounded else "gemini"

    def ask(self, prompt, system=None):
        url = f"{GEMINI_BASE}/models/{self.model}:generateContent"
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if self.grounded:
            body["tools"] = [{"google_search": {}}]
        # header auth works for both classic "AIza..." keys and newer "AQ...." keys
        for attempt in range(4):
            r = requests.post(url, headers={"x-goog-api-key": self.key}, json=body, timeout=TIMEOUT)
            if r.status_code in (500, 502, 503, 504):  # Google overloaded: back off and retry
                wait = 10 * (attempt + 1)
                print(f"    Gemini busy ({r.status_code}); waiting {wait}s (attempt {attempt + 1}/4)")
                time.sleep(wait)
                continue
            if r.status_code != 429:
                break
            msg = r.text
            if re.search(r"limit:\s*0\b", msg):
                raise RuntimeError(
                    f"429: your key has NO free quota for {self.model}"
                    + (" with web search" if self.grounded else "")
                    + ". Try --platforms gemini (no web search) or another model via GEMINI_MODEL.")
            m = re.search(r'"retryDelay":\s*"(\d+)', msg)
            wait = int(m.group(1)) + 1 if m else 15 * (attempt + 1)
            print(f"    rate limited; waiting {wait}s (attempt {attempt + 1}/4)")
            time.sleep(wait)
        if not r.ok:
            raise RuntimeError(f"{r.status_code}: {r.text[:300]}")
        cand = r.json()["candidates"][0]
        chunks = (cand.get("groundingMetadata") or {}).get("groundingChunks") or []
        # Gemini returns redirect URLs; the title field holds the source domain
        self.last_sources = [c["web"].get("title") or c["web"].get("uri")
                             for c in chunks if c.get("web")]
        parts = cand["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)


# ---------------------------------------------------------------- mock ----
MOCK_COMPETITORS = [
    "Competitor A Taverna", "Competitor B Mezze Bar", "Competitor C Grill",
    "Competitor D Cocktail Lounge", "Competitor E Bistro", "Competitor F Kitchen",
]
# Fake "why" text and fake cited sites, so the leader analysis has something to chew on.
MOCK_REASONS = {
    "Competitor A Taverna": "authentic family recipes, great reviews from locals, and a big patio",
    "Competitor B Mezze Bar": "a daily happy hour with cheap small plates and good cocktails",
    "Competitor C Grill": "a private room that's popular for rehearsal dinners and group events",
    "Competitor D Cocktail Lounge": "creative cocktails and a romantic, dimly lit room",
    "Competitor E Bistro": "strong reviews and a family-friendly menu near the beach",
    "Competitor F Kitchen": "a dedicated gluten-free and vegan menu",
    "Café Athena": "a long-running Greek spot on Garnet Ave",
}
MOCK_SITES = {
    "Competitor A Taverna": ["example-food-guide.test", "example-reviews.test", "example-forum.test"],
    "Competitor B Mezze Bar": ["example-food-guide.test", "example-magazine.test"],
    "Competitor C Grill": ["example-wedding-blog.test", "example-reviews.test"],
    "Competitor D Cocktail Lounge": ["example-magazine.test"],
    "Competitor E Bistro": ["example-reviews.test"],
    "Competitor F Kitchen": ["example-forum.test"],
    "Café Athena": ["cafeathena.com"],
}
# Baseline odds the fake assistant mentions the target, by query category.
MOCK_TARGET_RATE = {"cuisine": .55, "dietary": .35, "happy_hour": .25,
                    "date_night": .10, "events": .05, "casual": .20}
_STOP = {"the", "and", "with", "for", "near", "best", "good", "where", "can", "get",
         "restaurant", "spot", "san", "diego", "pacific", "beach", "what", "should"}


def _tokens(text):
    return set(re.findall(r"[a-z][a-z\-]{2,}", text.lower())) - _STOP


class MockProvider(Provider):
    is_mock = True

    def __init__(self, name="mock"):
        self.name = name

    def ask(self, prompt, system=None):
        if "<doc " in prompt:
            return self._rag(prompt)
        seed = int(hashlib.md5((self.name + prompt).encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        picks = rng.sample(MOCK_COMPETITORS, 4)
        if rng.random() < MOCK_TARGET_RATE.get(categorize(prompt), .2):
            picks.insert(rng.randint(0, 3), "Café Athena")
        self.last_sources = sorted({d for n in picks for d in MOCK_SITES[n]})
        return "[MOCK ANSWER]\n" + "\n".join(
            f"{i}. **{n}**: known for {MOCK_REASONS[n]}." for i, n in enumerate(picks, 1))

    def _rag(self, prompt):
        self.last_sources = []
        """Rank provided docs by keyword overlap with the question (tiny retriever)."""
        q = re.search(r"<question>(.*?)</question>", prompt, re.S).group(1)
        docs = re.findall(r'<doc name="(.*?)">(.*?)</doc>', prompt, re.S)
        qt = _tokens(q)
        scored = [(len(qt & _tokens(body)), -i, name) for i, (name, body) in enumerate(docs)]
        scored.sort(reverse=True)
        picks = [n for s, _, n in scored if s > 0][:4]
        return "[MOCK RAG ANSWER]\n" + "\n".join(
            f"{i}. **{n}**" for i, n in enumerate(picks, 1)) if picks else "[MOCK] No match."


# ---------------------------------------------------------------- factory -
_FACTORIES = {
    "claude": lambda: AnthropicProvider(False),
    "claude-web": lambda: AnthropicProvider(True),
    "gpt": OpenAIProvider,
    "gemini": lambda: GeminiProvider(False),
    "gemini-web": lambda: GeminiProvider(True),
    "perplexity": PerplexityProvider,
}


def get_providers(names: list[str]) -> list[Provider]:
    out = []
    for n in names:
        if n.startswith("mock"):
            out.append(MockProvider(n))
            continue
        try:
            out.append(_FACTORIES[n]())
        except KeyError as e:
            print(f"  ! skipping {n}: missing {e} (set the API key env var)")
    return out


def analysis_llm() -> Provider:
    """LLM used for extraction, diagnosis and writing. Falls back to mock."""
    for name, key in (("claude", "ANTHROPIC_API_KEY"), ("gpt", "OPENAI_API_KEY"),
                      ("gemini", "GEMINI_API_KEY")):
        if os.getenv(key):
            return get_providers([name])[0]
    return MockProvider("mock-writer")
