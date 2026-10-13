"""`hark doctor`: verify the machine is ready and print exact fixes for anything missing."""

from __future__ import annotations

import ctypes.util
import getpass
import glob
import grp
import importlib.util
import json
import os
import pwd
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass

from . import config as config_mod
from . import distro, paths

OK, INFO, WARN, FAIL = "ok", "info", "warn", "fail"

SETUP_HINT = "or run everything at once: bash scripts/setup-linux.sh"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def check_python() -> Check:
    # pip enforces requires-python >= 3.10, so this is informational.
    return Check("Python", OK, ".".join(map(str, sys.version_info[:3])))


def check_input_devices(cfg: config_mod.Config) -> Check:
    name = "Keyboard access"
    if any(os.access(p, os.R_OK) for p in glob.glob("/dev/input/event*")):
        return Check(name, OK, "can read /dev/input (hold-to-talk hotkey available)")

    # Without evdev, `hark toggle` bound to a desktop shortcut still works.
    severity = FAIL if cfg.hotkey.evdev_enabled else INFO
    try:
        group = grp.getgrnam("input")
    except KeyError:
        return Check(name, severity, "this system has no 'input' group",
                     f"sudo groupadd --system input && sudo usermod -aG input $USER\n{SETUP_HINT}")
    user = getpass.getuser()
    member = user in group.gr_mem or pwd.getpwnam(user).pw_gid == group.gr_gid
    if member and group.gr_gid not in os.getgroups():
        return Check(name, WARN, "you were added to 'input', but this login session predates it",
                     "log out and back in (or reboot)")
    return Check(name, severity, "cannot read /dev/input (not in the 'input' group)",
                 f"sudo usermod -aG input $USER, then log out and back in\n{SETUP_HINT}")


def check_uinput() -> Check:
    name = "Virtual keyboard"
    xdotool_fallback = distro.session_type() == "x11" and shutil.which("xdotool")
    severity = WARN if xdotool_fallback else FAIL
    if not os.path.exists("/dev/uinput"):
        return Check(name, severity, "/dev/uinput missing (uinput kernel module not loaded)",
                     f"sudo modprobe uinput\n{SETUP_HINT}")
    if not os.access("/dev/uinput", os.W_OK):
        return Check(name, severity, "/dev/uinput is not writable, so Hark can't press Ctrl+V",
                     "bash scripts/setup-linux.sh  (adds a udev rule giving the 'input' group "
                     "access), then log out and back in")
    return Check(name, OK, "/dev/uinput writable (paste works on X11 and Wayland)")


def check_clipboard() -> Check:
    name = "Clipboard tool"
    session = distro.session_type()
    if session == "wayland":
        if shutil.which("wl-copy"):
            return Check(name, OK, "wl-copy (Wayland)")
        return Check(name, FAIL, "wl-copy not found (needed on Wayland)",
                     distro.install_command("wl-clipboard"))
    if session == "x11":
        found = shutil.which("xclip") or shutil.which("xsel")
        if found:
            return Check(name, OK, f"{os.path.basename(found)} (X11)")
        return Check(name, FAIL, "xclip/xsel not found (needed on X11)",
                     distro.install_command("xclip"))
    return Check(name, WARN, "no graphical session detected; run doctor from your desktop session")


def check_paste_fallbacks() -> Check:
    found = [t for t in ("xdotool", "wtype", "ydotool") if shutil.which(t)]
    detail = ", ".join(found) if found else "none (uinput is the primary method)"
    return Check("Paste fallbacks", INFO, detail)


def check_portaudio() -> tuple[Check, bool]:
    if ctypes.util.find_library("portaudio"):
        return Check("PortAudio", OK, "found"), True
    return Check("PortAudio", FAIL, "libportaudio not found (needed to record audio)",
                 distro.install_command("portaudio")), False


def check_microphone() -> Check:
    name = "Microphone"
    if importlib.util.find_spec("sounddevice") is None:
        return Check(name, WARN, "python package 'sounddevice' not installed", "make install")
    try:
        import sounddevice as sd
    except OSError as e:
        return Check(name, FAIL, f"PortAudio failed to load ({e})", distro.install_command(
            "portaudio"))
    try:
        device = sd.query_devices(kind="input")
    except (sd.PortAudioError, ValueError) as e:
        return Check(name, FAIL, f"no default input device ({e})",
                     "check Settings → Sound → Input, or run: pactl list short sources")
    return Check(name, OK, f"{device['name']} ({int(device['default_samplerate'])} Hz)")


PYTHON_GROUPS = {
    "core": ("numpy", "sounddevice", "evdev", "httpx"),
    "stt": ("onnx_asr", "faster_whisper"),
    "gui": ("PySide6",),
}


def check_python_packages() -> list[Check]:
    checks = []
    for group, modules in PYTHON_GROUPS.items():
        missing = [m for m in modules if importlib.util.find_spec(m) is None]
        if not missing:
            checks.append(Check(f"Python deps ({group})", OK, ", ".join(modules)))
        else:
            status = FAIL if group == "core" else WARN
            checks.append(Check(f"Python deps ({group})", status,
                                "missing: " + ", ".join(missing), "make install"))
    return checks


def check_ollama(cfg: config_mod.Config) -> Check:
    name = "Ollama (optional)"
    url = cfg.llm.url.rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            models = [m["name"] for m in json.load(resp).get("models", [])]
    except (urllib.error.URLError, OSError, ValueError):
        if shutil.which("ollama"):
            return Check(name, WARN, f"installed but not reachable at {cfg.llm.url}",
                         "sudo systemctl start ollama   (or: ollama serve)")
        return Check(name, WARN, "not installed; transcripts won't get LLM cleanup",
                     "bash scripts/install-ollama.sh")
    wanted = cfg.llm.model
    if wanted in models or f"{wanted}:latest" in models:
        return Check(name, OK, f"running; {len(models)} model(s): {', '.join(models)}")
    return Check(name, WARN, f"running, but '{wanted}' isn't pulled "
                 f"(have: {', '.join(models) or 'none'})", f"ollama pull {wanted}")


def check_speech_model(cfg: config_mod.Config) -> Check:
    from .stt import catalog

    model_id = cfg.stt.model
    if catalog.is_downloaded(model_id):
        return Check("Speech model", OK, f"{model_id} (downloaded)")
    return Check("Speech model", FAIL, f"{model_id} is selected but not downloaded",
                 f"hark models download {model_id}")


def check_disk_space() -> Check:
    target = paths.models_dir()
    while not target.exists():
        target = target.parent
    free_gb = shutil.disk_usage(target).free / 1e9
    if free_gb >= 4:
        return Check("Disk space", OK, f"{free_gb:.1f} GB free for models")
    return Check("Disk space", WARN, f"only {free_gb:.1f} GB free; models need 0.2–2 GB each",
                 f"free up space on {target}")


def check_tray() -> Check:
    name = "Tray icon"
    if "GNOME" not in distro.desktop().upper():
        return Check(name, INFO, "your desktop shows tray icons natively")
    try:
        out = subprocess.run(["gnome-extensions", "list", "--enabled"],
                             check=False, capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    if "appindicator" in out.lower():
        return Check(name, OK, "GNOME AppIndicator extension enabled")
    return Check(name, WARN, "GNOME hides tray icons without the AppIndicator extension",
                 f"{distro.install_command('appindicator')}, then enable it in the Extensions app")


def run_checks() -> list[Check]:
    checks: list[Check] = []
    try:
        cfg = config_mod.load()
        checks.append(Check("Config", OK, str(paths.config_file())))
    except config_mod.ConfigError as e:
        cfg = config_mod.Config()
        checks.append(Check("Config", FAIL, str(e)))

    checks.append(check_python())
    checks.extend(check_python_packages())
    checks.append(check_input_devices(cfg))
    checks.append(check_uinput())
    checks.append(check_clipboard())
    checks.append(check_paste_fallbacks())
    portaudio, has_portaudio = check_portaudio()
    checks.append(portaudio)
    if has_portaudio:
        checks.append(check_microphone())
    checks.append(check_speech_model(cfg))
    checks.append(check_ollama(cfg))
    checks.append(check_disk_space())
    checks.append(check_tray())
    return checks


_SYMBOLS = {OK: ("✔", "32"), INFO: ("•", "36"), WARN: ("!", "33"), FAIL: ("✘", "31")}


def render(checks: list[Check], color: bool) -> str:
    def paint(text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if color else text

    session = f"{distro.session_type()} · {distro.desktop() or 'unknown desktop'}"
    lines = [f"Hark doctor — {distro.pretty_name()} · {session}", ""]
    width = max(len(c.name) for c in checks)
    for c in checks:
        symbol, code = _SYMBOLS[c.status]
        lines.append(f" {paint(symbol, code)} {c.name:<{width}}  {c.detail}")
        for fix_line in c.fix.splitlines():
            lines.append(f"   {' ' * width}  {paint('→ ' + fix_line, '2')}")
    counts = {s: sum(c.status == s for c in checks) for s in (OK, WARN, FAIL)}
    lines += ["", f"{counts[OK]} ok, {counts[WARN]} warning(s), {counts[FAIL]} problem(s)"]
    return "\n".join(lines)


def main(as_json: bool = False) -> int:
    checks = run_checks()
    if as_json:
        print(json.dumps([asdict(c) for c in checks], indent=2))
    else:
        print(render(checks, color=sys.stdout.isatty() and "NO_COLOR" not in os.environ))
    return 1 if any(c.status == FAIL for c in checks) else 0
