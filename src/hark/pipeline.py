"""Transcript post-processing: rules (fillers, voice commands, vocabulary), then optional
LLM cleanup. The LLM can only improve the text; on any failure the rule output is used."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .config import Config
from .llm.ollama import OllamaClient
from .llm.polish import ChatClient, polish
from .text import cleaner, vocabulary, voice_commands


@dataclass
class Processed:
    raw: str  # straight from speech-to-text
    rules_text: str  # after fillers, voice commands and vocabulary
    text: str  # final
    llm_status: str = "off"
    llm_s: float = 0.0


def keep_alive(cfg: Config) -> str:
    return f"{cfg.llm.keep_alive_min}m"


def apply_rules(raw: str, cfg: Config) -> str:
    text = raw.strip()
    if cfg.remove_fillers:
        text = cleaner.clean(text)
    if cfg.voice_commands:
        text = voice_commands.apply(text)
    return vocabulary.apply(text, cfg.vocabulary)


def process(raw: str, cfg: Config, *, use_llm: bool | None = None,
            client: ChatClient | None = None) -> Processed:
    rules_text = apply_rules(raw, cfg)
    result = Processed(raw=raw, rules_text=rules_text, text=rules_text)
    if not (cfg.llm.enabled if use_llm is None else use_llm) or not rules_text:
        return result

    start = time.perf_counter()
    outcome = polish(rules_text, client or OllamaClient(cfg.llm.url), model=cfg.llm.model,
                     style=cfg.llm.style, terms=vocabulary.terms(cfg.vocabulary),
                     base_timeout=cfg.llm.timeout_s, keep_alive=keep_alive(cfg))
    result.llm_s = time.perf_counter() - start
    result.llm_status = outcome.status
    if outcome.text is not None:
        # Re-apply replacements in case the model re-spelled a vocabulary term.
        result.text = vocabulary.apply(outcome.text, cfg.vocabulary)
    return result
