"""Stage 1b: turn a free-text AI answer into a ranked list of restaurants."""
from __future__ import annotations
import json
import re
import unicodedata

PROMPT = """List every specific restaurant, bar or café that the answer below recommends,
in order of first appearance. Exclude neighborhoods, websites and generic categories.
Respond with ONLY JSON: {"restaurants": ["..."]}

<answer>
__ANSWER__
</answer>"""


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _dedupe(names):
    seen, out = set(), []
    for n in names:
        k = norm(n)
        if k and k not in seen:
            seen.add(k)
            out.append(n.strip())
    return out


def heuristic_extract(answer: str) -> list[str]:
    names = re.findall(r"\*\*(.+?)\*\*", answer)
    if not names:
        names = re.findall(r"^\s*\d+[.)]\s*([^\n:(–—]+)", answer, re.M)
    return _dedupe([n.strip(" .:-") for n in names])


def extract_restaurants(answer: str, llm=None) -> list[str]:
    if llm is not None and not llm.is_mock:
        try:
            txt = re.sub(r"```(json)?", "", llm.ask(PROMPT.replace("__ANSWER__", answer))).strip()
            return _dedupe(json.loads(txt)["restaurants"])
        except Exception as e:  # fall back rather than lose the row
            print(f"  ! extraction fallback: {e}")
    return heuristic_extract(answer)


def is_target(name: str, aliases: list[str]) -> bool:
    n = norm(name)
    return any(a in n for a in aliases)


def target_position(names: list[str], aliases: list[str]) -> int | None:
    for i, n in enumerate(names, 1):
        if is_target(n, aliases):
            return i
    return None
