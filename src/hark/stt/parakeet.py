"""NVIDIA Parakeet TDT (int8 ONNX) via onnx-asr."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import onnx_asr

from . import SAMPLE_RATE, catalog
from .catalog import ModelInfo

# Parakeet transcribes up to ~25 s in one pass. Short clips skip VAD so word edges
# aren't trimmed; longer ones are split on pauses.
_VAD_THRESHOLD_S = 20


class ParakeetEngine:
    def __init__(self, info: ModelInfo):
        self.model_id = info.id
        self._asr = onnx_asr.load_model(info.onnx_asr_name, catalog.model_dir(info.id),
                                        quantization="int8")
        vad = onnx_asr.load_vad("silero", catalog.model_dir("silero-vad"))
        # onnx-asr splits on 100 ms pauses by default, which cuts sentences into fragments
        # and garbles punctuation; only split on sentence-length pauses.
        self._asr_vad = self._asr.with_vad(vad, min_silence_duration_ms=600, speech_pad_ms=200)

    def transcribe(self, audio: np.ndarray, *, language: str = "auto",
                   hints: Sequence[str] = ()) -> str:
        # Parakeet detects the language itself and has no prompt/hint input;
        # vocabulary is applied afterwards as replacements.
        if len(audio) <= _VAD_THRESHOLD_S * SAMPLE_RATE:
            return self._asr.recognize(audio, sample_rate=SAMPLE_RATE).strip()
        segments = self._asr_vad.recognize(audio, sample_rate=SAMPLE_RATE)
        return " ".join(t for s in segments if (t := s.text.strip()))
