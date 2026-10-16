"""Put text into the focused app: copy it to the clipboard, then press the paste shortcut
through a uinput virtual keyboard (works on X11 and all Wayland compositors).

Fallbacks when /dev/uinput isn't writable: xdotool (X11), wtype (wlroots), ydotool.
If no method can press keys, the text stays on the clipboard for a manual Ctrl+V.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time

from . import distro
from .errors import HarkError
from .hotkey import VIRTUAL_KEYBOARD_NAME


class InjectError(HarkError):
    pass


CHORDS = {"ctrl+v": ("LEFTCTRL", "V"), "ctrl+shift+v": ("LEFTCTRL", "LEFTSHIFT", "V"),
          "shift+insert": ("LEFTSHIFT", "INSERT")}


def _run(cmd: list[str], text: str | None = None, timeout: float = 2.0, *,
         capture: bool = True) -> str | None:
    """Run a helper tool; returns its stdout ("" when not captured), or None on failure."""
    # Clipboard owners (wl-copy, xclip) fork a background process that keeps serving the
    # clipboard and inherits our pipes; capturing their output would block until timeout.
    out = subprocess.PIPE if capture else subprocess.DEVNULL
    try:
        result = subprocess.run(cmd, input=text, stdout=out, stderr=out, text=True,
                                timeout=timeout, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout or ""


class Clipboard:
    def __init__(self):
        session = distro.session_type()
        if session == "wayland" and shutil.which("wl-copy"):
            self._copy = ["wl-copy", "--type", "text/plain;charset=utf-8"]
            self._paste = ["wl-paste", "--no-newline"]
        elif shutil.which("xclip"):
            self._copy = ["xclip", "-selection", "clipboard"]
            self._paste = ["xclip", "-selection", "clipboard", "-o"]
        elif shutil.which("xsel"):
            self._copy = ["xsel", "--clipboard", "--input"]
            self._paste = ["xsel", "--clipboard", "--output"]
        else:
            raise InjectError("no clipboard tool found. Run: hark doctor")

    def copy(self, text: str) -> bool:
        return _run(self._copy, text, capture=False) is not None

    def read(self) -> str | None:
        return _run(self._paste, timeout=1.0)


class _UInputKeyboard:
    def __init__(self):
        from evdev import UInput
        from evdev import ecodes as e

        self._e = e
        keys = {getattr(e, f"KEY_{k}") for chord in CHORDS.values() for k in chord}
        self._ui = UInput({e.EV_KEY: sorted(keys)}, name=VIRTUAL_KEYBOARD_NAME)
        time.sleep(0.3)  # give the compositor time to notice the new keyboard

    def chord(self, keys: tuple[str, ...]) -> None:
        codes = [getattr(self._e, f"KEY_{k}") for k in keys]
        for code in codes:
            self._ui.write(self._e.EV_KEY, code, 1)
            self._ui.syn()
            time.sleep(0.012)
        for code in reversed(codes):
            self._ui.write(self._e.EV_KEY, code, 0)
            self._ui.syn()
            time.sleep(0.012)

    def close(self) -> None:
        self._ui.close()


class Injector:
    """insert(text) returns how the text was delivered, e.g. 'pasted (uinput)'."""

    def __init__(self, chord: str = "ctrl+v", restore_clipboard: bool = False):
        self.chord = chord
        self.restore_clipboard = restore_clipboard
        self.clipboard = Clipboard()
        self._keyboard: _UInputKeyboard | None = None
        self.uinput_error = ""
        try:
            self._keyboard = _UInputKeyboard()
        except OSError as e:
            self.uinput_error = str(e)

    @property
    def method(self) -> str:
        if self._keyboard:
            return "uinput"
        session = distro.session_type()
        for tool, ok in (("xdotool", session == "x11"), ("wtype", session == "wayland"),
                         ("ydotool", True)):
            if ok and shutil.which(tool):
                return tool
        return "clipboard only"

    def _press(self, chord: str) -> bool:
        keys = CHORDS[chord]
        method = self.method
        if method == "uinput":
            self._keyboard.chord(keys)
            return True
        names = [k.lower().replace("left", "") for k in keys]
        if method == "xdotool":
            return _run(["xdotool", "key", "--clearmodifiers", "+".join(names)]) is not None
        if method == "wtype":
            mods = names[:-1]
            cmd = ["wtype"] + [a for m in mods for a in ("-M", m)] + ["-k", names[-1]]
            return _run(cmd + [a for m in reversed(mods) for a in ("-m", m)]) is not None
        if method == "ydotool":
            from evdev import ecodes as e

            codes = [getattr(e, f"KEY_{k}") for k in keys]
            seq = [f"{c}:1" for c in codes] + [f"{c}:0" for c in reversed(codes)]
            return _run(["ydotool", "key", *seq]) is not None
        return False

    def _type(self, text: str) -> bool:
        if distro.session_type() == "x11" and shutil.which("xdotool"):
            return _run(["xdotool", "type", "--clearmodifiers", "--", text], timeout=30) is not None
        if shutil.which("wtype"):
            return _run(["wtype", "--", text], timeout=30) is not None
        return False

    def insert(self, text: str) -> str:
        if not text:
            return "nothing to insert"
        if self.chord == "type":
            if self._type(text):
                return "typed"
            chord = "ctrl+v"  # no typing tool for this session; paste instead
        else:
            chord = self.chord

        previous = self.clipboard.read() if self.restore_clipboard else None
        if not self.clipboard.copy(text):
            raise InjectError("couldn't copy the text to the clipboard")
        time.sleep(0.05)  # let the clipboard owner settle before the paste request
        if not self._press(chord):
            return "copied to clipboard (press Ctrl+V)"
        if previous is not None:
            # Restore later: the target app reads the clipboard asynchronously after Ctrl+V.
            threading.Timer(0.6, self.clipboard.copy, args=(previous,)).start()
        return f"pasted ({self.method})"

    def close(self) -> None:
        if self._keyboard:
            self._keyboard.close()
