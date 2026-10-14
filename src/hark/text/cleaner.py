"""Remove filler words, set-off "you know", and stutters ("I I think").

Rules adapted from OpenDictate's cleaner.rs (Apache-2.0); see NOTICE.
"""

from __future__ import annotations

import re

from . import SENTENCE_END, capitalize, norm, trailing

FILLERS = {"uh", "uhh", "uhm", "um", "umm", "er", "erm", "hm", "hmm", "mm", "mmm"}
NUMBER_WORDS = {"zero", "oh", "one", "two", "three", "four", "five", "six", "seven", "eight",
                "nine", "ten"}
# Single words that are legitimately doubled ("had had", "bye bye", "no no").
KEEP_DOUBLED = {"that", "had", "is", "very", "really", "long", "bye", "no", "ha"}
CLAUSE_BREAK = (",", ".", ";", ":", "!", "…", "—")


def _is_number(token: str) -> bool:
    w = norm(token)
    return any(c.isdigit() for c in w) or w in NUMBER_WORDS


def _drop(out: list[str], removed: str) -> bool:
    """Account for a removed token's punctuation. Returns True if the next kept word
    should be capitalized (the removed token started a sentence)."""
    punct = trailing(removed)
    at_start = not out or out[-1].endswith(SENTENCE_END)
    if out and not at_start:
        if any(c in ".!?" for c in punct):
            out[-1] = out[-1].rstrip(",;:") + punct  # "go um." -> "go."
        elif "," in punct and out[-1].endswith(","):
            out[-1] = out[-1][:-1]  # "So, um, I" -> "So I"
    return at_start and removed[:1].isupper()


def _remove_fillers(tokens: list[str]) -> list[str]:
    out: list[str] = []
    cap_next = False
    i = 0
    while i < len(tokens):
        tok, w = tokens[i], norm(tokens[i])
        if w in FILLERS and not (w == "mm" and out and _is_number(out[-1])):  # "5 mm"
            cap_next = _drop(out, tok) or cap_next
            i += 1
            continue
        # "you know" only when set off: "I was, you know, tired" but not "Do you know?"
        if (w == "you" and i + 1 < len(tokens) and norm(tokens[i + 1]) == "know"
                and (not out or out[-1].endswith(CLAUSE_BREAK))
                and (i + 2 == len(tokens) or trailing(tokens[i + 1])[:1] in (",", ".", "!"))
                and "?" not in trailing(tokens[i + 1])):
            cap_next = _drop(out, tokens[i + 1]) or cap_next
            i += 2
            continue
        out.append(capitalize(tok) if cap_next else tok)
        cap_next = False
        i += 1
    return out


def _collapsible(copy: list[str]) -> bool:
    if any(not norm(t) or _is_number(t) for t in copy):
        return False
    if len(copy) == 1 and norm(copy[0]) in KEEP_DOUBLED:
        return False
    return not trailing(copy[-1])  # punctuation between the copies blocks collapsing


def _collapse_repeats(tokens: list[str]) -> list[str]:
    """Collapse adjacent repeats of 1-3 words, keeping the first copy."""
    tokens = list(tokens)
    changed = True
    while changed:
        changed = False
        for n in (3, 2, 1):
            i = 0
            while i + 2 * n <= len(tokens):
                first, second = tokens[i:i + n], tokens[i + n:i + 2 * n]
                if [norm(t) for t in first] == [norm(t) for t in second] and _collapsible(first):
                    tokens[i + n - 1] += trailing(second[-1])
                    del tokens[i + n:i + 2 * n]
                    changed = True
                else:
                    i += 1
    return tokens


def clean(text: str) -> str:
    tokens = _collapse_repeats(_remove_fillers(text.split()))
    return re.sub(r",$", "", " ".join(tokens)).strip()
