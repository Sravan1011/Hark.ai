"""XDG base-directory locations used by Hark.

Functions (not constants) so that environment changes, e.g. in tests, take effect.
"""

from __future__ import annotations

import os
from pathlib import Path

APP = "hark"


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var, "").strip()
    # The XDG spec says relative paths must be ignored.
    if value and os.path.isabs(value):
        return Path(value)
    return Path.home() / fallback


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / APP


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / APP


def cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / APP


def runtime_dir() -> Path:
    value = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    if value and os.path.isabs(value):
        return Path(value)
    return Path(f"/tmp/{APP}-{os.getuid()}")


def config_file() -> Path:
    return config_dir() / "config.json"


def models_dir() -> Path:
    return data_dir() / "models"


def history_file() -> Path:
    return data_dir() / "history.jsonl"


def socket_path() -> Path:
    return runtime_dir() / f"{APP}.sock"
