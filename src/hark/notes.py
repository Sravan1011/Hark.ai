"""Quick voice notes, stored privately in ~/.local/share/hark/notes.json."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field

from . import paths


@dataclass
class Note:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    body: str = ""
    summary: str = ""
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)

    @property
    def display_title(self) -> str:
        if self.title.strip():
            return self.title.strip()
        first_line = self.body.strip().split("\n", 1)[0]
        return (first_line[:60] + "…") if len(first_line) > 60 else (first_line or "New note")


def _file():
    return paths.data_dir() / "notes.json"


def load() -> list[Note]:
    """Newest first."""
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []
    fields = Note.__dataclass_fields__
    notes = [Note(**{k: v for k, v in item.items() if k in fields})
             for item in data if isinstance(item, dict)]
    return sorted(notes, key=lambda n: n.updated, reverse=True)


def save_all(notes: list[Note]) -> None:
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump([asdict(n) for n in notes], fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
