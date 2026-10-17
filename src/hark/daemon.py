"""The background service: owns the speech model, the hotkey and the control socket.

`hark daemon` runs it in the foreground (what systemd uses), `hark daemon --detach`
starts it in the background with output in ~/.local/state/hark/hark.log, and
`hark listen` runs it in a terminal with the dictated text shown.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from . import config as config_mod
from . import history, ipc, paths
from .config import Config
from .dictation import Dictation, EventCallback, Result
from .errors import HarkError
from .hotkey import HotkeyError, pretty

_LOG_MAX_BYTES = 1_000_000


class Daemon:
    """Owns dictation and the control socket. Use run() to block until quit, or
    start()/stop() when another event loop (the Qt app) owns the main thread."""

    def __init__(self, cfg: Config, *, log: Callable[[str], None], log_text: bool = False,
                 on_event: EventCallback | None = None,
                 on_result: Callable[[Result, dict], None] | None = None,
                 on_show: Callable[[], None] | None = None):
        self.cfg = cfg
        self.log = log
        self.started = time.time()
        self.last: dict[str, Any] | None = None
        self.hotkey_error = ""
        self.model_error = ""
        self.on_result = on_result
        self.on_show = on_show
        self.dictation = Dictation(cfg, log=log, on_result=self._on_result, log_text=log_text,
                                   on_event=on_event)
        self._shutdown = threading.Event()
        self._server: ipc.Server | None = None
        self._loader: threading.Thread | None = None

    # -- commands from `hark <cmd>` ----------------------------------------------------

    def handle(self, req: dict[str, Any]) -> dict[str, Any]:
        cmd = req.get("cmd")
        actions = {
            "toggle": self.dictation.toggle,
            "start": self.dictation.begin,
            "stop": self.dictation.finish,
            "cancel": self.dictation.cancel,
            "ping": lambda: None,
            "status": lambda: None,
            "reload": self.reload,
            "quit": self.request_quit,
            "show": self._show,
        }
        if cmd not in actions:
            return {"ok": False, "error": f"unknown command: {cmd}"}
        actions[cmd]()
        return {"ok": True, **self.status()}

    def status(self) -> dict[str, Any]:
        d = self.dictation
        return {
            "state": d.state,
            "pid": os.getpid(),
            "uptime_s": round(time.time() - self.started),
            "model": self.cfg.stt.model,
            "model_loaded": d.engine is not None,
            "hotkey": pretty(d.combo) if d.listener else None,
            "hotkey_error": self.hotkey_error,
            "mode": self.cfg.hotkey.mode,
            "llm": self.cfg.llm.model if self.cfg.llm.enabled else None,
            "model_error": self.model_error,
            "ui": self.on_show is not None,
            "last": self.last,
        }

    def _show(self) -> None:
        if self.on_show is None:
            raise HarkError("Hark is running without its window (hark daemon). "
                            "Run `hark quit`, then `hark app`.")
        self.on_show()

    def request_quit(self) -> None:
        self._shutdown.set()

    @property
    def quit_requested(self) -> bool:
        return self._shutdown.is_set()

    def reload(self) -> None:
        cfg = config_mod.load()
        try:
            changes = self.dictation.reconfigure(cfg)
            self.hotkey_error = ""
        except HotkeyError as e:
            self.hotkey_error = str(e)
            raise
        self.cfg = cfg
        self.log(f"Settings reloaded{': ' + ', '.join(changes) if changes else ''}.")

    def _on_result(self, result: Result) -> None:
        self.last = {"text": result.text, "delivered": result.delivered,
                     "ts": time.strftime("%H:%M:%S")}
        entry = {"text": result.text, "raw": result.raw, "model": self.cfg.stt.model,
                 "audio_s": round(result.audio_s, 2), "stt_s": round(result.stt_s, 2),
                 "llm": result.llm_status, "delivered": result.delivered}
        if self.cfg.save_history:
            history.append(entry)
        if self.on_result:
            self.on_result(result, entry)

    # -- lifecycle -------------------------------------------------------------------

    def _load(self, on_ready: Callable[[Daemon, float], None] | None) -> None:
        try:
            load_s = self.dictation.load()
        except HarkError as e:
            self.model_error = str(e)
            self.log(f"✘ {e}")
            return
        self.model_error = ""
        if on_ready and not self._shutdown.is_set():
            on_ready(self, load_s)

    def start(self, on_ready: Callable[[Daemon, float], None] | None = None) -> None:
        """Claim the socket, start the hotkey, and load the model in the background (so
        `hark quit` works during the ~8 s load). Raises AlreadyRunning."""
        self._server = ipc.Server(self.handle)  # first, so a second instance fails fast
        self._server.start()
        try:
            self.dictation.start()
        except HotkeyError as e:
            self.dictation.listener = None
            self.hotkey_error = str(e)
            self.log(f"! Hotkey unavailable: {e}")
        self._loader = threading.Thread(target=self._load, args=(on_ready,), name="hark-load",
                                        daemon=True)
        self._loader.start()

    @property
    def loading(self) -> bool:
        return self._loader is not None and self._loader.is_alive()

    def exit_if_loading(self, code: int = 0) -> None:
        """Call after stop(). If the model is still loading, Python's normal shutdown would
        tear down the interpreter under onnxruntime mid-load, which aborts the process; skip
        finalization instead (everything Hark owns is already closed)."""
        if self.loading:
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(code)

    def stop(self) -> None:
        if self._server:
            self._server.close()
            self._server = None
        self.dictation.close()
        self.log("Stopped.")

    def run(self, on_ready: Callable[[Daemon, float], None] | None = None) -> None:
        signal.signal(signal.SIGTERM, lambda *_: self._shutdown.set())
        self.start(on_ready)
        try:
            # A timed wait keeps the main thread responsive to Ctrl+C.
            while not self._shutdown.wait(0.5):
                pass
        finally:
            self.stop()
        self.exit_if_loading()


def _timestamped(message: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}", flush=True)


def run_foreground(cfg: Config) -> None:
    """`hark daemon`: log lines on stdout (systemd's journal, or the --detach log file)."""
    def ready(daemon: Daemon, load_s: float) -> None:
        hotkey = (f"hotkey {pretty(daemon.dictation.combo)} ({cfg.hotkey.mode})"
                  if daemon.dictation.listener else "no hotkey (use hark toggle)")
        _timestamped(f"Ready: {cfg.stt.model} loaded in {load_s:.1f}s, {hotkey}, "
                     f"paste via {daemon.dictation.injector.method}.")

    Daemon(cfg, log=_timestamped).run(on_ready=ready)


def detach() -> int:
    """Start `hark daemon` in the background; returns its pid once it answers."""
    if ipc.is_running():
        raise ipc.AlreadyRunning("Hark is already running (see: hark status)")
    log_path = paths.log_file()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists() and log_path.stat().st_size > _LOG_MAX_BYTES:
        log_path.replace(log_path.with_suffix(".log.1"))
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "ab") as log:
        proc = subprocess.Popen([sys.executable, "-m", "hark", "daemon"], stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise HarkError(f"Hark exited during startup; see {log_path}")
        if ipc.is_running():
            return proc.pid
        time.sleep(0.2)
    raise HarkError(f"Hark didn't respond within 15s; see {log_path}")
