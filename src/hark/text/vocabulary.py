"""User vocabulary: phrase replacements and spelling hints.

An entry {"from": "hark ai", "to": "Hark.ai"} replaces the phrase (whole words, any case).
An entry whose "from" equals "to" (e.g. "Kubernetes") is a spelling hint: it fixes the
casing and is passed to Whisper and the LLM as a term to spell exactly.
"""

from __future__ import annotations

import re


def _pattern(phrase: str) -> re.Pattern[str]:
    words = r"\s+".join(re.escape(w) for w in phrase.split())
    return re.compile(rf"(?<!\w){words}(?!\w)", re.IGNORECASE)


def apply(text: str, entries: list[dict[str, str]]) -> str:
    for entry in sorted(entries, key=lambda e: len(e["from"]), reverse=True):
        if entry["from"].strip():
            # A function replacement so backslashes in "to" are taken literally.
            text = _pattern(entry["from"]).sub(lambda _m, to=entry["to"]: to, text)
    return text


def terms(entries: list[dict[str, str]]) -> list[str]:
    """Distinct target spellings, for Whisper's prompt and the LLM."""
    return list(dict.fromkeys(e["to"] for e in entries if e["to"].strip()))
