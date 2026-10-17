"""Dictation history: one JSON object per line in ~/.local/share/hark/history.jsonl.

The file holds everything you dictated, so it's created owner-only (0600).
`save_history: false` in the config turns it off.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from . import paths

MAX_ENTRIES = 1000


def append(entry: dict[str, Any]) -> None:
    path = paths.history_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"id": uuid.uuid4().hex[:12], "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **entry}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    _trim(path)


def _write(path, lines: list[str]) -> None:
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.writelines(lines)
    os.replace(tmp, path)


def _trim(path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if len(lines) > MAX_ENTRIES * 1.2:  # trim in batches, not on every append
        _write(path, lines[-MAX_ENTRIES:])


def delete(entry_id: str) -> bool:
    path = paths.history_file()
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except FileNotFoundError:
        return False
    kept = [line for line in lines if f'"id": "{entry_id}"' not in line]
    if len(kept) == len(lines):
        return False
    _write(path, kept)
    return True


def read(limit: int | None = None) -> list[dict[str, Any]]:
    """Newest last. Corrupt lines (e.g. from a crash mid-write) are skipped."""
    try:
        lines = paths.history_file().read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries[-limit:] if limit else entries


def clear() -> int:
    entries = len(read())
    paths.history_file().unlink(missing_ok=True)
    return entries
