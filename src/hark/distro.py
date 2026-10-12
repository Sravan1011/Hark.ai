"""Distro, session and package-manager detection, used to print exact fix commands."""

from __future__ import annotations

import os
import shutil

# Logical dependency -> package name per package manager.
PACKAGES: dict[str, dict[str, str]] = {
    "portaudio": {"apt": "libportaudio2", "dnf": "portaudio", "pacman": "portaudio",
                  "zypper": "libportaudio2"},
    "wl-clipboard": {pm: "wl-clipboard" for pm in ("apt", "dnf", "pacman", "zypper")},
    "xclip": {pm: "xclip" for pm in ("apt", "dnf", "pacman", "zypper")},
    "xdotool": {pm: "xdotool" for pm in ("apt", "dnf", "pacman", "zypper")},
    "appindicator": {"apt": "gnome-shell-extension-appindicator",
                     "dnf": "gnome-shell-extension-appindicator",
                     "pacman": "gnome-shell-extension-appindicator",
                     "zypper": "gnome-shell-extension-appindicator"},
}

_INSTALL = {
    "apt": "sudo apt install",
    "dnf": "sudo dnf install",
    "pacman": "sudo pacman -S",
    "zypper": "sudo zypper install",
}

_PM_BINARIES = (("apt", "apt-get"), ("dnf", "dnf"), ("pacman", "pacman"), ("zypper", "zypper"))


def os_release() -> dict[str, str]:
    info: dict[str, str] = {}
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    key, sep, value = line.strip().partition("=")
                    if sep:
                        info[key] = value.strip().strip('"')
            break
        except OSError:
            continue
    return info


def pretty_name() -> str:
    return os_release().get("PRETTY_NAME", "Unknown Linux")


def package_manager() -> str | None:
    for name, binary in _PM_BINARIES:
        if shutil.which(binary):
            return name
    return None


def install_command(*deps: str) -> str:
    pm = package_manager()
    if pm is None:
        return "install with your package manager: " + ", ".join(deps)
    return f"{_INSTALL[pm]} " + " ".join(PACKAGES[d][pm] for d in deps)


def session_type() -> str:
    """'wayland', 'x11', or 'tty' when no graphical session is detected."""
    value = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if value in ("wayland", "x11"):
        return value
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "tty"


def desktop() -> str:
    return os.environ.get("XDG_CURRENT_DESKTOP", "") or os.environ.get("DESKTOP_SESSION", "")
