"""Manual mode: get real answers from chat apps (claude.ai, gemini.google.com, chatgpt.com)
without API keys.

1. export  -> writes an answers file with one block per query
2. you paste each query into a NEW chat and paste the reply under its block
3. import  -> parses the file and stores the answers like any other run
"""
from __future__ import annotations

import os
import re

HEADER = re.compile(r"^=== (\w+) \| (.*?) ===\s*$", re.M)
PLACEHOLDER = "(paste the full answer here)"

INSTRUCTIONS = """# MANUAL MODE ANSWERS FILE: platform = {platform}
#
# For each block below:
#   1. Open a NEW chat (use an incognito/temporary chat if available, so memory and
#      past chats don't bias the answer). Turn web search ON if the app offers it.
#   2. Paste the query exactly as written. Don't add context about Café Athena.
#   3. Copy the full reply and paste it under the block header, replacing the placeholder.
# Leave a block untouched to skip it. Don't edit the === header lines.
# When done:  python cli.py manual-import --platform {platform}
"""


def export(queries: list[dict], platform: str, path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(INSTRUCTIONS.format(platform=platform) + "\n")
        for q in queries:
            f.write(f"=== {q['id']} | {q['text']} ===\n{PLACEHOLDER}\n\n")
    return path


def parse(path: str) -> dict[str, str]:
    """Return {query_id: answer} for every block that has a pasted answer."""
    text = open(path).read()
    heads = list(HEADER.finditer(text))
    out = {}
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[m.end():end].strip()
        if body and body != PLACEHOLDER:
            out[m.group(1)] = body
    return out
