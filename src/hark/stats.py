"""Dictation statistics for the Home page, computed from the history."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

_WORD = re.compile(r"[\w']+")


@dataclass
class Stats:
    total_dictations: int
    total_words: int
    words_this_week: int
    avg_wpm: int  # speaking speed, from entries with at least 2 s of audio
    streak_days: int  # consecutive days with a dictation, ending today or yesterday


def _day(entry: dict[str, Any]) -> dt.date | None:
    try:
        return dt.datetime.fromisoformat(entry["ts"]).date()
    except (KeyError, ValueError):
        return None


def compute(entries: list[dict[str, Any]], today: dt.date | None = None) -> Stats:
    today = today or dt.date.today()
    week_start = today - dt.timedelta(days=6)
    total_words = words_week = 0
    timed_words, timed_seconds = 0, 0.0
    days: set[dt.date] = set()
    for e in entries:
        words = len(_WORD.findall(e.get("text", "")))
        total_words += words
        day = _day(e)
        if day:
            days.add(day)
            if day >= week_start:
                words_week += words
        audio_s = e.get("audio_s") or 0
        if audio_s >= 2 and words:
            timed_words += words
            timed_seconds += audio_s
    streak = 0
    cursor = today if today in days else today - dt.timedelta(days=1)
    while cursor in days:
        streak += 1
        cursor -= dt.timedelta(days=1)
    wpm = round(timed_words / timed_seconds * 60) if timed_seconds else 0
    return Stats(len(entries), total_words, words_week, wpm, streak)
