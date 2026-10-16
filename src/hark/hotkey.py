"""Global hotkey via evdev: reads keyboards (and mice, for side buttons) directly, so it
works on X11 and every Wayland compositor. Keys are observed, never grabbed.
Requires read access to /dev/input (the 'input' group)."""

from __future__ import annotations

import selectors
import threading
import time
from collections.abc import Callable

import evdev
from evdev import ecodes

from .errors import HarkError

VIRTUAL_KEYBOARD_NAME = "hark-virtual-keyboard"
_RESCAN_S = 2.0

_PRETTY = {"LEFTCTRL": "Left Ctrl", "RIGHTCTRL": "Right Ctrl", "LEFTALT": "Left Alt",
           "RIGHTALT": "Right Alt", "LEFTSHIFT": "Left Shift", "RIGHTSHIFT": "Right Shift",
           "LEFTMETA": "Super", "RIGHTMETA": "Right Super", "SPACE": "Space",
           "CAPSLOCK": "Caps Lock", "SIDE": "Mouse side button", "EXTRA": "Mouse extra button"}


class HotkeyError(HarkError):
    pass


def parse_combo(text: str) -> tuple[int, ...]:
    """'KEY_RIGHTCTRL', 'rightctrl+space' or 'BTN_SIDE' -> evdev key codes."""
    codes = []
    for part in text.split("+"):
        name = part.strip().upper()
        if not name.startswith(("KEY_", "BTN_")):
            name = "KEY_" + name
        code = ecodes.ecodes.get(name)
        if code is None:
            raise HotkeyError(f"unknown key '{part.strip()}'. Find key names with: "
                              "hark debug-hotkey")
        codes.append(code)
    if not codes:
        raise HotkeyError("the shortcut is empty")
    return tuple(codes)


def key_name(code: int) -> str:
    name = ecodes.KEY.get(code) or ecodes.BTN.get(code) or f"KEY_{code}"
    return name[0] if isinstance(name, list) else name


def pretty(combo: tuple[int, ...]) -> str:
    def one(code: int) -> str:
        bare = key_name(code).split("_", 1)[-1]
        return _PRETTY.get(bare, bare.title())
    return " + ".join(one(c) for c in combo)


class HotkeyListener(threading.Thread):
    """Calls on_event(name) from its own thread with one of:

    'press'     - every key of the combo is down
    'release'   - a combo key was released after 'press'
    'interrupt' - another key was pressed while the combo was held (it's a shortcut
                  like Right Ctrl+C, not dictation)
    'escape'    - Esc was pressed
    'key:NAME'  - any key press, only when report_all_keys is set (for debugging)
    """

    def __init__(self, combo: tuple[int, ...], on_event: Callable[[str], None], *,
                 report_all_keys: bool = False):
        super().__init__(name="hark-hotkey", daemon=True)
        self.combo = combo
        self.on_event = on_event
        self.report_all_keys = report_all_keys
        self._selector = selectors.DefaultSelector()
        self._devices: dict[str, evdev.InputDevice] = {}
        self._pressed: set[int] = set()
        self._active = False
        self._stopping = threading.Event()
        self._released = threading.Condition()

    # -- device management -------------------------------------------------------------

    def _wanted(self, device: evdev.InputDevice) -> bool:
        if device.name == VIRTUAL_KEYBOARD_NAME:
            return False  # our own Ctrl+V must not look like the user typing
        keys = set(device.capabilities().get(ecodes.EV_KEY, []))
        if self.report_all_keys:
            return bool(keys)
        return bool(keys & (set(self.combo) | {ecodes.KEY_ESC}))

    def _scan(self) -> None:
        for path in evdev.list_devices():
            if path in self._devices:
                continue
            try:
                device = evdev.InputDevice(path)
            except OSError:
                continue
            if self._wanted(device):
                self._devices[path] = device
                self._selector.register(device, selectors.EVENT_READ)
            else:
                device.close()

    def _drop(self, device: evdev.InputDevice) -> None:
        self._selector.unregister(device)
        self._devices.pop(device.path, None)
        device.close()
        self._set_pressed(set())  # unplugged mid-press: don't leave keys stuck down

    @staticmethod
    def check_access() -> int:
        """Number of readable input devices; raises if none (permissions)."""
        readable = 0
        for path in evdev.list_devices():
            try:
                evdev.InputDevice(path).close()
                readable += 1
            except OSError:
                pass
        if not readable:
            raise HotkeyError("can't read keyboards in /dev/input. Add yourself to the 'input' "
                              "group (bash scripts/setup-linux.sh), then log out and back in. "
                              "Or bind `hark toggle` to a desktop shortcut instead.")
        return readable

    # -- key state -------------------------------------------------------------------

    def _set_pressed(self, pressed: set[int]) -> None:
        with self._released:
            self._pressed = pressed
            if not (self._pressed & set(self.combo)):
                self._released.notify_all()
        if self._active and not all(k in self._pressed for k in self.combo):
            self._active = False
            self.on_event("release")

    def _handle(self, code: int, value: int) -> None:
        if value == 2:  # autorepeat
            return
        if value == 1:
            if self.report_all_keys:
                self.on_event(f"key:{key_name(code)}")
            if code == ecodes.KEY_ESC:
                self.on_event("escape")
            elif self._active and code not in self.combo:
                self.on_event("interrupt")
        pressed = self._pressed | {code} if value == 1 else self._pressed - {code}
        self._set_pressed(pressed)
        if not self._active and value == 1 and all(k in pressed for k in self.combo):
            self._active = True
            self.on_event("press")

    def wait_released(self, timeout: float = 1.0) -> bool:
        """Block until no combo key is held, so a pasted Ctrl+V isn't mixed with them."""
        deadline = time.monotonic() + timeout
        with self._released:
            while self._pressed & set(self.combo):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._released.wait(remaining)
        return True

    # -- thread ----------------------------------------------------------------------

    def run(self) -> None:
        last_scan = 0.0
        try:
            while not self._stopping.is_set():
                if time.monotonic() - last_scan > _RESCAN_S:  # hotplugged keyboards
                    self._scan()
                    last_scan = time.monotonic()
                if not self._devices:
                    self._stopping.wait(0.5)
                    continue
                for key, _ in self._selector.select(timeout=0.5):
                    device = key.fileobj
                    try:
                        events = list(device.read())
                    except OSError:
                        self._drop(device)
                        continue
                    for ev in events:
                        if ev.type == ecodes.EV_KEY:
                            self._handle(ev.code, ev.value)
        finally:
            for device in list(self._devices.values()):
                device.close()
            self._devices.clear()
            self._selector.close()

    def stop(self) -> None:
        """Ask the thread to exit; it closes its devices within ~0.5 s."""
        self._stopping.set()
