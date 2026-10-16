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
                 on_result: Callable[[Result], None] | None = None):
        self.cfg = cfg
        self.log = log
        self.on_result = on_result
        self.combo = parse_combo(cfg.hotkey.combo)
        self.recorder = audio.Recorder(max_seconds=MAX_SECONDS, on_limit=self._on_limit)
        self.injector = Injector(cfg.insert.paste_chord, cfg.insert.restore_clipboard)
        self.listener = (HotkeyListener(self.combo, self.handle_hotkey)
                         if cfg.hotkey.evdev_enabled else None)
        self.engine: Engine | None = None
        self._jobs: queue.Queue[np.ndarray | None] = queue.Queue()
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._work, name="hark-worker", daemon=True)

    # -- lifecycle -------------------------------------------------------------------

    def load(self) -> float:
        """Load the speech model (seconds taken) and warm up the LLM in the background."""
        start = time.perf_counter()
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
        if self.listener:
            HotkeyListener.check_access()
            self.listener.start()
        self._worker.start()

    def close(self) -> None:
        self.cancel(quiet=True)
        if self.listener:
            self.listener.stop()
        self._jobs.put(None)
        self.injector.close()

    # -- hotkey / commands -----------------------------------------------------------

    @property
    def recording(self) -> bool:
        return self.recorder.recording

    def handle_hotkey(self, event: str) -> None:
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

    def begin(self) -> None:
        with self._lock:
            if self.recording:
                return
            try:
                self.recorder.start()
            except HarkError as e:
                self.log(f"✘ {e}")
                return
        if self.cfg.ui.sounds:
            audio.beep("start")
        self.log("● Listening…")

    def finish(self) -> None:
        with self._lock:
            if not self.recording:
                return
            elapsed = self.recorder.elapsed
            recording = self.recorder.stop()
        if elapsed < MIN_SECONDS:
            self.log("  (too short, ignored)")
            return
        if self.cfg.ui.sounds:
            audio.beep("stop")
        self._jobs.put(recording)

    def cancel(self, quiet: bool = False) -> None:
        with self._lock:
            if not self.recording:
                return
            self.recorder.cancel()
        if not quiet:
            if self.cfg.ui.sounds:
                audio.beep("cancel")
            self.log("  Cancelled.")

    def _on_limit(self) -> None:
        self.log(f"  Reached the {MAX_SECONDS // 60}-minute limit; transcribing.")
        self.finish()

    # -- processing ------------------------------------------------------------------

    def _work(self) -> None:
        while (recording := self._jobs.get()) is not None:
            try:
                self._handle_recording(recording)
            except HarkError as e:
                self.log(f"✘ {e}")
            except Exception as e:  # noqa: BLE001 - one bad dictation must not stop the loop
                self.log(f"✘ unexpected error: {e!r}")

    def _handle_recording(self, recording: np.ndarray) -> None:
        audio_s = recording.size / SAMPLE_RATE
        if audio.is_silent(recording):
            self.log("  (no speech detected)")
            return
        if self.engine is None:
            self.load()
        self.log(f"  Transcribing {audio_s:.1f}s…")
        start = time.perf_counter()
        raw = self.engine.transcribe(recording, language=self.cfg.stt.language,
                                     hints=vocabulary.terms(self.cfg.vocabulary))
        stt_s = time.perf_counter() - start
        processed = process(raw, self.cfg)
        text = processed.text
        if not text:
            self.log("  (nothing to insert)")
            return
        if self.cfg.insert.trailing_space and not text.endswith("\n"):
            text += " "
        if self.listener:
            self.listener.wait_released()
        delivered = self.injector.insert(text)
        result = Result(raw=raw, text=processed.text, delivered=delivered, audio_s=audio_s,
                        stt_s=stt_s, llm_status=processed.llm_status, llm_s=processed.llm_s)
        llm = (f", llm {processed.llm_s:.1f}s {processed.llm_status}"
               if processed.llm_status != "off" else "")
        self.log(f"✔ {delivered} · stt {stt_s:.1f}s{llm}\n  “{processed.text}”")
        if self.on_result:
            self.on_result(result)
