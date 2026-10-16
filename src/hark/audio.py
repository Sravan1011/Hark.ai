"""Microphone capture (16 kHz mono float32) and short feedback tones."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import numpy as np

from .errors import HarkError
from .stt import SAMPLE_RATE


class AudioError(HarkError):
    pass


def _sd():
    try:
        import sounddevice as sd
    except OSError as e:
        raise AudioError(f"PortAudio isn't available ({e}). Run: hark doctor") from None
    return sd


def resample(audio: np.ndarray, rate: int) -> np.ndarray:
    if rate == SAMPLE_RATE or audio.size == 0:
        return audio.astype(np.float32)
    if rate % SAMPLE_RATE == 0:
        # Integer ratio (48 kHz, 32 kHz): average each group, a simple anti-aliasing filter.
        factor = rate // SAMPLE_RATE
        usable = audio[: audio.size - audio.size % factor]
        return usable.reshape(-1, factor).mean(axis=1).astype(np.float32)
    duration = audio.size / rate
    target = np.linspace(0, duration, int(duration * SAMPLE_RATE), endpoint=False)
    source = np.arange(audio.size) / rate
    return np.interp(target, source, audio).astype(np.float32)


class Recorder:
    """Records until stop()/cancel(), or until max_seconds, when on_limit is called."""

    def __init__(self, *, max_seconds: float = 120, on_level: Callable[[float], None] | None = None,
                 on_limit: Callable[[], None] | None = None):
        self.max_seconds = max_seconds
        self.on_level = on_level
        self.on_limit = on_limit
        self._chunks: list[np.ndarray] = []
        self._frames = 0
        self._stream = None
        self._rate = SAMPLE_RATE
        self._started = 0.0
        self._lock = threading.Lock()

    @property
    def recording(self) -> bool:
        return self._stream is not None

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._started if self.recording else 0.0

    def _callback(self, indata, frames, _time, _status) -> None:
        mono = indata[:, 0].copy()
        with self._lock:
            self._chunks.append(mono)
            self._frames += frames
            over = self._frames >= self.max_seconds * self._rate
        if self.on_level:
            self.on_level(float(np.sqrt(np.mean(mono ** 2))))
        if over:
            if self.on_limit:
                threading.Thread(target=self.on_limit, daemon=True).start()
            raise _sd().CallbackStop

    def start(self) -> None:
        if self.recording:
            return
        sd = _sd()
        self._chunks, self._frames = [], 0
        # Ask for 16 kHz (PipeWire/PulseAudio resample for us); fall back to the device rate.
        for rate in (SAMPLE_RATE, None):
            try:
                rate = rate or int(sd.query_devices(kind="input")["default_samplerate"])
                stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32",
                                        blocksize=rate // 20, callback=self._callback)
                stream.start()
            except (sd.PortAudioError, ValueError) as e:
                if rate == SAMPLE_RATE:
                    continue
                raise AudioError(f"can't open the microphone: {e}") from None
            self._rate, self._stream = rate, stream
            self._started = time.monotonic()
            return

    def _close(self) -> np.ndarray:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()
        with self._lock:
            audio = np.concatenate(self._chunks) if self._chunks else np.zeros(0, np.float32)
            self._chunks = []
        return resample(audio, self._rate)

    def stop(self) -> np.ndarray:
        """Stop and return the recording as 16 kHz mono float32."""
        return self._close()

    def cancel(self) -> None:
        self._close()


def is_silent(audio: np.ndarray, threshold: float = 0.004) -> bool:
    """True if the loudest 100 ms window is below speech level."""
    if audio.size < SAMPLE_RATE // 10:
        return True
    window = SAMPLE_RATE // 10
    frames = audio[: audio.size - audio.size % window].reshape(-1, window)
    return float(np.sqrt((frames ** 2).mean(axis=1)).max()) < threshold


def beep(kind: str) -> None:
    """Non-blocking feedback tone: 'start' (rising), 'stop' (falling) or 'cancel' (low)."""
    freqs = {"start": (660, 880), "stop": (880, 660), "cancel": (330, 330)}[kind]
    rate, part = 44_100, 0.06
    t = np.arange(int(rate * part)) / rate
    fade = np.minimum(1, np.minimum(t, part - t) / 0.01)
    tone = np.concatenate([np.sin(2 * np.pi * f * t) * fade for f in freqs]) * 0.15
    # A missing beep must never break dictation.
    try:
        sd = _sd()
    except AudioError:
        return
    try:
        sd.play(tone.astype(np.float32), rate)
    except (OSError, ValueError, sd.PortAudioError):
        return
