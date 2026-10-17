"""The dictation loop: hotkey -> record -> transcribe -> clean up -> paste.

Used by `hark listen` (foreground) and, later, by the background daemon. Hotkey events
arrive on the listener thread; transcription runs on a worker thread so the hotkey stays
responsive while the previous dictation is still being processed.
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from . import audio
from .config import Config
from .errors import HarkError
from .hotkey import HotkeyListener, parse_combo
from .inject import Injector
from .pipeline import keep_alive, process
from .stt import SAMPLE_RATE, Engine, load_engine
from .text import vocabulary

MIN_SECONDS = 0.3  # shorter presses are accidental taps
MAX_SECONDS = 120

# on_event(kind, data) kinds, for the UI (called from background threads):
#   "state"  {"state": "idle" | "recording" | "transcribing"}
#   "level"  {"rms": float}            ~20 times a second while recording
#   "notice" {"message": str}          e.g. no speech detected, cancelled
#   "error"  {"message": str}
EventCallback = Callable[[str, dict], None]


@dataclass
class Result:
    raw: str
    text: str
    delivered: str
    audio_s: float
    stt_s: float
    llm_status: str
    llm_s: float


class Dictation:
    def __init__(self, cfg: Config, *, log: Callable[[str], None],
                 on_result: Callable[[Result], None] | None = None, log_text: bool = True,
                 on_event: EventCallback | None = None):
        self.cfg = cfg
        self.log = log
        self.on_result = on_result
        self.on_event = on_event
        self.log_text = log_text  # off for the daemon's log file: it would hold dictations
        self.combo = parse_combo(cfg.hotkey.combo)
        self.recorder = audio.Recorder(max_seconds=MAX_SECONDS, on_limit=self._on_limit,
                                       on_level=lambda rms: self._emit("level", rms=rms))
        self.injector = Injector(cfg.insert.paste_chord, cfg.insert.restore_clipboard)
        self.listener = (HotkeyListener(self.combo, self.handle_hotkey)
                         if cfg.hotkey.evdev_enabled else None)
        self.engine: Engine | None = None
        self.paused = False  # hotkey ignored, e.g. while the user records a new shortcut
        # Where the current recording's text goes instead of being pasted (e.g. a note).
        self._capture: Callable[[str], None] | None = None
        self._jobs: queue.Queue[tuple[np.ndarray, Callable[[str], None] | None] | None] = \
            queue.Queue()
        self._lock = threading.Lock()
        self._load_lock = threading.Lock()
        self._busy = 0
        self._worker = threading.Thread(target=self._work, name="hark-worker", daemon=True)

    # -- lifecycle -------------------------------------------------------------------

    def load(self) -> float:
        """Load the speech model (seconds taken) and warm up the LLM in the background.
        Safe to call from several threads: a dictation arriving mid-load waits for it."""
        start = time.perf_counter()
        with self._load_lock:
            if self.engine is None or self.engine.model_id != self.cfg.stt.model:
                self.engine = load_engine(self.cfg.stt.model)
        if self.cfg.llm.enabled:
            threading.Thread(target=self._warm_llm, daemon=True).start()
        return time.perf_counter() - start

    def _warm_llm(self) -> None:
        from .llm.ollama import LLMError, OllamaClient

        try:
            OllamaClient(self.cfg.llm.url).warm_up(self.cfg.llm.model, keep_alive(self.cfg))
        except LLMError as e:
            self.log(f"LLM cleanup unavailable, using rules only: {e}")

    def start(self) -> None:
        """Start processing; raises HotkeyError if the keyboard can't be read (commands
        such as `hark toggle` still work then)."""
        self._worker.start()
        if self.listener:
            HotkeyListener.check_access()
            self.listener.start()

    def reconfigure(self, cfg: Config) -> list[str]:
        """Apply new settings without restarting; returns a description of what changed."""
        combo = parse_combo(cfg.hotkey.combo)  # validate before changing anything
        old, self.cfg = self.cfg, cfg
        changes = []
        self.injector.chord = cfg.insert.paste_chord
        self.injector.restore_clipboard = cfg.insert.restore_clipboard
        if (cfg.hotkey.combo, cfg.hotkey.evdev_enabled) != (old.hotkey.combo,
                                                           old.hotkey.evdev_enabled):
            if self.listener:
                self.listener.stop()
                self.listener = None
            self.combo = combo
            if cfg.hotkey.evdev_enabled:
                listener = HotkeyListener(combo, self.handle_hotkey)
                HotkeyListener.check_access()
                listener.start()
                self.listener = listener
            changes.append("hotkey")
        if cfg.stt.model != old.stt.model:
            threading.Thread(target=self.load, daemon=True).start()
            changes.append(f"model -> {cfg.stt.model}")
        elif cfg.llm.enabled and (not old.llm.enabled or cfg.llm.model != old.llm.model):
            threading.Thread(target=self._warm_llm, daemon=True).start()
        if cfg.llm != old.llm:
            changes.append("llm")
        return changes

    def close(self) -> None:
        self.cancel(quiet=True)
        if self.listener:
            self.listener.stop()
        self._jobs.put(None)
        self.injector.close()

    # -- events ----------------------------------------------------------------------

    def _emit(self, kind: str, **data) -> None:
        if self.on_event:
            self.on_event(kind, data)

    def _report(self, kind: str, message: str) -> None:
        self.log(f"✘ {message}" if kind == "error" else f"  {message}")
        self._emit(kind, message=message)

    def _state_changed(self) -> None:
        self._emit("state", state=self.state)

    # -- hotkey / commands -----------------------------------------------------------

    @property
    def recording(self) -> bool:
        return self.recorder.recording

    @property
    def state(self) -> str:
        if self.recording:
            return "recording"
        return "transcribing" if self._busy else "idle"

    def handle_hotkey(self, event: str) -> None:
        if self.paused:
            return
        hold = self.cfg.hotkey.mode == "hold"
        if event == "press":
            self.begin() if hold else self.toggle()
        elif event == "release" and hold:
            self.finish()
        elif event == "interrupt" and hold:
            self.cancel(quiet=True)  # it was a shortcut such as Right Ctrl+C
        elif event == "escape":
            self.cancel()

    def toggle(self) -> None:
        self.finish() if self.recording else self.begin()

    def begin(self, capture: Callable[[str], None] | None = None) -> None:
        """Start recording. With `capture`, the text is passed to it instead of pasted."""
        with self._lock:
            if self.recording:
                return
            try:
                self.recorder.start()
            except HarkError as e:
                self._report("error", str(e))
                return
            self._capture = capture
        if self.cfg.ui.sounds:
            audio.beep("start")
        self.log("● Listening…")
        self._state_changed()

    def finish(self) -> None:
        with self._lock:
            if not self.recording:
                return
            elapsed = self.recorder.elapsed
            recording = self.recorder.stop()
            capture, self._capture = self._capture, None
        if elapsed < MIN_SECONDS:
            self._report("notice", "Too short, ignored")
            self._state_changed()
            return
        if self.cfg.ui.sounds:
            audio.beep("stop")
        with self._lock:
            self._busy += 1
        self._jobs.put((recording, capture))
        self._state_changed()

    def cancel(self, quiet: bool = False) -> None:
        with self._lock:
            if not self.recording:
                return
            self.recorder.cancel()
            self._capture = None
        if not quiet:
            if self.cfg.ui.sounds:
                audio.beep("cancel")
            self._report("notice", "Cancelled")
        self._state_changed()

    def _on_limit(self) -> None:
        self.log(f"  Reached the {MAX_SECONDS // 60}-minute limit; transcribing.")
        self.finish()

    # -- processing ------------------------------------------------------------------

    def _work(self) -> None:
        while (job := self._jobs.get()) is not None:
            try:
                self._handle_recording(*job)
            except HarkError as e:
                self._report("error", str(e))
            except Exception as e:  # noqa: BLE001 - one bad dictation must not stop the loop
                self._report("error", f"unexpected error: {e!r}")
            finally:
                with self._lock:
                    self._busy -= 1
                self._state_changed()

    def _handle_recording(self, recording: np.ndarray,
                          capture: Callable[[str], None] | None = None) -> None:
        audio_s = recording.size / SAMPLE_RATE
        if audio.is_silent(recording):
            self._report("notice", "No speech detected")
            return
        if self.engine is None or self.engine.model_id != self.cfg.stt.model:
            self.load()
        self.log(f"  Transcribing {audio_s:.1f}s…")
        start = time.perf_counter()
        raw = self.engine.transcribe(recording, language=self.cfg.stt.language,
                                     hints=vocabulary.terms(self.cfg.vocabulary))
        stt_s = time.perf_counter() - start
        processed = process(raw, self.cfg)
        text = processed.text
        if not text:
            self._report("notice", "Nothing to insert")
            return
        if capture:
            capture(text)
            delivered = "added to note"
        else:
            if self.cfg.insert.trailing_space and not text.endswith("\n"):
                text += " "
            if self.listener:
                self.listener.wait_released()
            delivered = self.injector.insert(text)
        result = Result(raw=raw, text=processed.text, delivered=delivered, audio_s=audio_s,
                        stt_s=stt_s, llm_status=processed.llm_status, llm_s=processed.llm_s)
        llm = (f", llm {processed.llm_s:.1f}s {processed.llm_status}"
               if processed.llm_status != "off" else "")
        quoted = f"\n  “{processed.text}”" if self.log_text else ""
        self.log(f"✔ {delivered} · stt {stt_s:.1f}s{llm}{quoted}")
        if self.on_result:
            self.on_result(result)
