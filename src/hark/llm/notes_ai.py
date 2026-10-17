"""AI title and summary for a voice note (on request, with the local Ollama model)."""

from __future__ import annotations

import json

from .ollama import LLMError, OllamaClient

SYSTEM = ("You write a title and a summary for a personal note. Use only information that "
          "is in the note. Reply with JSON: {\"title\": \"at most 6 words\", "
          "\"summary\": \"one or two sentences\"}.")
MAX_CHARS = 8000


def title_and_summary(text: str, client: OllamaClient, *, model: str,
                      keep_alive: str) -> tuple[str, str]:
    if not text.strip():
        raise LLMError("the note is empty")
    reply = client.chat(model, SYSTEM, text[:MAX_CHARS], timeout=90, keep_alive=keep_alive,
                        max_tokens=200, json_format=True)
    try:
        data = json.loads(reply)
        title, summary = str(data["title"]).strip(), str(data["summary"]).strip()
    except (ValueError, KeyError, TypeError):
        raise LLMError("the model didn't return a usable title and summary") from None
    if not title or not summary:
        raise LLMError("the model returned an empty title or summary")
    return title.strip('"'), summary
