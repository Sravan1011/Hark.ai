"""OpenAI Whisper via faster-whisper (CTranslate2, int8 on CPU)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from faster_whisper import WhisperModel

from . import catalog
from .catalog import ModelInfo


class WhisperEngine:
    def __init__(self, info: ModelInfo):
        self.model_id = info.id
        self._english_only = info.english_only
        self._model = WhisperModel(str(catalog.model_dir(info.id)), device="cpu",
                                   compute_type="int8")

    def transcribe(self, audio: np.ndarray, *, language: str = "auto",
                   hints: Sequence[str] = ()) -> str:
        if self._english_only:
            language = "en"
        segments, _ = self._model.transcribe(
            audio,
            language=None if language == "auto" else language,
            initial_prompt=f"Vocabulary: {', '.join(hints)}." if hints else None,
            vad_filter=True,  # avoids hallucinated text on silence
            condition_on_previous_text=False,
        )
        return " ".join(t for s in segments if (t := s.text.strip()))
