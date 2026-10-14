"""Spoken commands: punctuation, line breaks, "scratch that", and @mentions.

Rules adapted from OpenDictate's voice_commands.rs (Apache-2.0); see NOTICE.
"""

from __future__ import annotations

import re

from . import EDGE, SENTENCE_END, capitalize, norm

Phrase = tuple[str, ...]

# Always active: these words are rarely meant literally.
ALWAYS: dict[Phrase, str] = {
    ("exclamation", "mark"): "!", ("exclamation", "point"): "!", ("question", "mark"): "?",
    ("full", "stop"): ".", ("semicolon",): ";", ("comma",): ",",
}
# Common words: only after "add/insert/put" ("add a colon"), or "period" at the very end.
REQUESTED: dict[Phrase, str] = {
    ("period",): ".", ("colon",): ":", ("dash",): " –", ("hyphen",): "-",
}
BREAKS: dict[Phrase, str] = {
    ("new", "line"): "\n", ("next", "line"): "\n",
    ("new", "paragraph"): "\n\n", ("next", "paragraph"): "\n\n",
}
DELETE_ALWAYS: set[Phrase] = {("scratch", "that"), ("strike", "that")}
# Everyday phrases: only when set off, e.g. "Sorry, remove that." but not "remove that file".
DELETE_SET_OFF: set[Phrase] = {("remove", "that"), ("delete", "that"), ("undo", "that"),
                               ("cancel", "that")}
REQUESTS = {"add", "insert", "put"}
NOUN_MARKERS = {"a", "an", "the", "this", "that", "oxford", "serial"}
APOLOGIES = {"sorry", "oops", "wait"}
SET_OFF_PUNCT = (",", ".", "!", "?", ";", ":", "…")


def _match(norms: list[str], i: int, phrases) -> Phrase | None:
    for phrase in sorted(phrases, key=len, reverse=True):
        if tuple(norms[i:i + len(phrase)]) == phrase:
            return phrase
    return None


def _attach(out: list[str], punct: str) -> None:
    if out and not out[-1].startswith("\n"):
        out[-1] = out[-1].rstrip(".,!?;:") + punct


def _delete_sentence(out: list[str]) -> None:
    """Delete the sentence being dictated (or the last finished one, if it just ended)."""
    while out and norm(out[-1]) in APOLOGIES:
        out.pop()
    for k in range(len(out) - 2, -1, -1):
        if out[k].startswith("\n") or out[k].endswith(SENTENCE_END):
            del out[k + 1:]
            return
    out.clear()


def _is_set_off(tokens: list[str], norms: list[str], i: int, length: int) -> bool:
    before = i == 0 or tokens[i - 1].endswith(SET_OFF_PUNCT) or norms[i - 1] in APOLOGIES
    end = i + length
    after = end == len(tokens) or tokens[end - 1].endswith(SET_OFF_PUNCT)
    return before and after


def _mention(tokens: list[str], norms: list[str], i: int) -> tuple[str, int] | None:
    """'at the rate KV' / 'at sign KV' / '@ KV' -> ('@KV', tokens consumed)."""
    if norms[i:i + 3] == ["at", "the", "rate"]:
        k = i + 3
    elif norms[i:i + 2] == ["at", "sign"]:
        k = i + 2
    elif tokens[i] == "@":
        k = i + 1
    else:
        return None
    if k >= len(tokens) or not norms[k] or norms[k] == "of":  # "at the rate of 5 percent"
        return None
    return "@" + tokens[k].lstrip(EDGE), k + 1 - i


def _join(out: list[str]) -> str:
    text = ""
    for tok in out:
        if tok.startswith("\n"):
            text = text.rstrip(" ") + tok
        else:
            text += ("" if not text or text.endswith("\n") else " ") + tok
    text = re.sub(r"[ \t]+([,.!?;:])", r"\1", text)
    text = re.sub(r"([,;:])[,;:]+", r"\1", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    return text.strip()


def apply(text: str) -> str:
    tokens = text.split()
    norms = [norm(t) for t in tokens]
    out: list[str] = []
    cap_next = False
    i, n = 0, len(tokens)

    while i < n:
        # "add a comma", "insert the Oxford comma"
        if norms[i] in REQUESTS:
            j = i + 1
            while j < n and j <= i + 2 and norms[j] in NOUN_MARKERS:
                j += 1
            phrase = _match(norms, j, ALWAYS.keys() | REQUESTED.keys())
            if phrase and out:
                value = ALWAYS.get(phrase) or REQUESTED[phrase]
                _attach(out, value)
                cap_next = value in SENTENCE_END
                i = j + len(phrase)
                continue

        # "the period ended", "I love the Oxford comma", "a new line of products"
        guarded = i > 0 and norms[i - 1] in NOUN_MARKERS
        if not guarded:
            phrase = _match(norms, i, ALWAYS)
            value = ALWAYS.get(phrase) if phrase else None
            if phrase is None and norms[i] == "period" and i == n - 1:
                phrase, value = ("period",), "."
            if phrase and value:
                _attach(out, value)
                cap_next = value in SENTENCE_END
                i += len(phrase)
                continue
            phrase = _match(norms, i, BREAKS)
            if phrase:
                if out:
                    out.append(BREAKS[phrase])
                    cap_next = True
                i += len(phrase)
                continue

        phrase = _match(norms, i, DELETE_ALWAYS)
        if phrase is None:
            candidate = _match(norms, i, DELETE_SET_OFF)
            if candidate and _is_set_off(tokens, norms, i, len(candidate)):
                phrase = candidate
        if phrase:
            _delete_sentence(out)
            cap_next = True
            i += len(phrase)
            continue

        mention = _mention(tokens, norms, i)
        if mention:
            out.append(mention[0])
            cap_next = False
            i += mention[1]
            continue

        out.append(capitalize(tokens[i]) if cap_next else tokens[i])
        cap_next = False
        i += 1

    return _join(out)
