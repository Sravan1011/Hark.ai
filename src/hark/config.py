"""User settings stored as JSON at ~/.config/hark/config.json.

Loading is tolerant: unknown keys are ignored and values of the wrong type fall
back to defaults, so an old or hand-edited file never prevents Hark from starting.
A file that is not valid JSON raises ConfigError instead of being silently replaced.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

from . import paths
from .errors import HarkError
from .stt.catalog import selectable_ids


class ConfigError(HarkError):
    pass


@dataclass
class HotkeyConfig:
    combo: str = "KEY_RIGHTCTRL"
    mode: str = "hold"
    # Built-in evdev listener; `hark toggle` via a desktop shortcut works regardless.
    evdev_enabled: bool = True


@dataclass
class STTConfig:
    model: str = "parakeet-v3"
    language: str = "auto"


@dataclass
class LLMConfig:
    enabled: bool = False
    url: str = "http://localhost:11434"
    model: str = "qwen2.5:3b"
    style: str = "plain"
    # Per-request timeout is timeout_s + 0.1 s per word; on timeout the rule output is used.
    timeout_s: float = 10.0
    # How long Ollama keeps the model in RAM after the last request.
    keep_alive_min: int = 30


@dataclass
class InsertConfig:
    paste_chord: str = "ctrl+v"
    trailing_space: bool = True
    restore_clipboard: bool = False


@dataclass
class UIConfig:
    overlay: bool = True
    sounds: bool = True


@dataclass
class Config:
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    insert: InsertConfig = field(default_factory=InsertConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    voice_commands: bool = True
    remove_fillers: bool = True
    save_history: bool = True
    # Each entry: {"from": "hark ai", "to": "Hark.ai"}
    vocabulary: list[dict[str, str]] = field(default_factory=list)


CHOICES: dict[str, tuple[str, ...]] = {
    "hotkey.mode": ("hold", "toggle"),
    "insert.paste_chord": ("ctrl+v", "ctrl+shift+v", "shift+insert", "type"),
    "llm.style": ("plain", "email", "message", "notes"),
    "stt.model": selectable_ids(),
}


def _accepts(default: Any, value: Any) -> bool:
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, float):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if isinstance(default, int):
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, type(default))


def _clean_vocabulary(value: list) -> list[dict[str, str]]:
    return [
        {"from": item["from"], "to": item["to"]}
        for item in value
        if isinstance(item, dict)
        and isinstance(item.get("from"), str)
        and isinstance(item.get("to"), str)
        and item["from"].strip()
    ]


def _from_dict(cls: type, data: Any, prefix: str = "") -> Any:
    obj = cls()
    if not isinstance(data, dict):
        return obj
    for f in fields(cls):
        if f.name not in data:
            continue
        current, value = getattr(obj, f.name), data[f.name]
        key = f"{prefix}{f.name}"
        if is_dataclass(current):
            setattr(obj, f.name, _from_dict(type(current), value, f"{key}."))
        elif not _accepts(current, value) or (key in CHOICES and value not in CHOICES[key]):
            continue
        elif key == "vocabulary":
            setattr(obj, f.name, _clean_vocabulary(value))
        else:
            setattr(obj, f.name, float(value) if isinstance(current, float) else value)
    return obj


def load(path: Path | None = None) -> Config:
    path = path or paths.config_file()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Config()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path} is not valid JSON ({e}); fix or delete it") from e
    return _from_dict(Config, data)


def save(cfg: Config, path: Path | None = None) -> None:
    path = path or paths.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(asdict(cfg), fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def _resolve(cfg: Config, key: str) -> tuple[Any, str]:
    """Return (parent object, attribute name) for a dotted key like 'llm.model'."""
    parts = key.split(".")
    obj: Any = cfg
    for part in parts[:-1]:
        if not is_dataclass(obj) or not hasattr(obj, part):
            raise ConfigError(f"unknown setting: {key}")
        obj = getattr(obj, part)
    if not is_dataclass(obj) or not hasattr(obj, parts[-1]):
        raise ConfigError(f"unknown setting: {key}")
    return obj, parts[-1]


def get_value(cfg: Config, key: str) -> Any:
    obj, name = _resolve(cfg, key)
    return getattr(obj, name)


_TRUE = {"true", "yes", "on", "1"}
_FALSE = {"false", "no", "off", "0"}


def set_value(cfg: Config, key: str, raw: str) -> Any:
    """Parse `raw` according to the current value's type and assign it."""
    obj, name = _resolve(cfg, key)
    current = getattr(obj, name)
    if is_dataclass(current) or isinstance(current, list):
        raise ConfigError(f"{key} can't be set from the command line; use `hark config edit`")
    if isinstance(current, bool):
        lowered = raw.strip().lower()
        if lowered not in _TRUE | _FALSE:
            raise ConfigError(f"{key} expects true or false, got {raw!r}")
        value: Any = lowered in _TRUE
    elif isinstance(current, (int, float)):
        try:
            value = type(current)(raw)
        except ValueError:
            raise ConfigError(f"{key} expects a number, got {raw!r}") from None
    else:
        value = raw
    if key in CHOICES and value not in CHOICES[key]:
        raise ConfigError(f"{key} must be one of: {', '.join(CHOICES[key])}")
    setattr(obj, name, value)
    return value
