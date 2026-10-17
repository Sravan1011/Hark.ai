"""Desktop integration: the app-launcher entry and start-at-login (XDG autostart)."""

from __future__ import annotations

import sys
from pathlib import Path

from . import paths


def _entry(hidden: bool) -> str:
    exec_line = f"{sys.executable} -m hark app" + (" --hidden" if hidden else "")
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=Hark",
        "GenericName=Voice dictation",
        "Comment=Hold a key, speak, and your words are typed into any app",
        f"Exec={exec_line}",
        "Icon=audio-input-microphone",
        "Terminal=false",
        "Categories=Utility;Accessibility;",
        "Keywords=dictation;speech;voice;transcription;",
        "StartupNotify=false",
        "",
    ])


def launcher_file() -> Path:
    return paths._xdg("XDG_DATA_HOME", ".local/share") / "applications" / "hark.desktop"


def autostart_file() -> Path:
    return paths._xdg("XDG_CONFIG_HOME", ".config") / "autostart" / "hark.desktop"


def install_launcher() -> Path:
    path = launcher_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_entry(hidden=False), encoding="utf-8")
    return path


def autostart_enabled() -> bool:
    return autostart_file().is_file()


def set_autostart(enabled: bool) -> None:
    path = autostart_file()
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_entry(hidden=True), encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
