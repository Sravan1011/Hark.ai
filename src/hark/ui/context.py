"""Glue between the daemon's background threads and the Qt main thread.

Qt widgets may only be touched from the main thread. Every callback from dictation
threads goes through a Signal, and `run_async` runs slow work (downloads, Ollama calls)
on a thread and delivers the outcome back on the main thread.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal

from .. import config as config_mod
from ..config import Config
from ..daemon import Daemon
from ..errors import HarkError


class Bridge(QObject):
    event = Signal(str, object)  # dictation events: state / level / notice / error
    result = Signal(object)  # history entry dict of a finished dictation
    loaded = Signal(float)  # speech model ready (seconds taken)
    show_window = Signal()
    settings_changed = Signal()
    _call = Signal(object)

    def __init__(self):
        super().__init__()
        self._call.connect(lambda fn: fn())

    def call_soon(self, fn: Callable[[], None]) -> None:
        """Run fn on the Qt main thread (safe to call from any thread)."""
        self._call.emit(fn)


class Context:
    def __init__(self, daemon: Daemon, bridge: Bridge):
        self.daemon = daemon
        self.bridge = bridge

    @property
    def cfg(self) -> Config:
        return self.daemon.cfg

    @property
    def dictation(self):
        return self.daemon.dictation

    def update_settings(self, change: Callable[[Config], None]) -> str | None:
        """Change, save and apply settings. Returns an error message, or None."""
        cfg = config_mod.load()
        change(cfg)
        config_mod.save(cfg)
        try:
            self.daemon.reload()
        except HarkError as e:
            return str(e)
        finally:
            self.bridge.settings_changed.emit()
        return None

    def run_async(self, work: Callable[[], Any], on_done: Callable[[Any], None] | None = None,
                  on_error: Callable[[str], None] | None = None) -> None:
        def target() -> None:
            try:
                result = work()
            except HarkError as e:
                if on_error:
                    message = str(e)
                    self.bridge.call_soon(lambda: on_error(message))
                return
            if on_done:
                self.bridge.call_soon(lambda: on_done(result))

        threading.Thread(target=target, daemon=True).start()
