"""Speech-to-text engines.

Engines take 16 kHz mono float32 audio and return text. Heavy libraries (onnxruntime,
ctranslate2) are imported only when an engine is loaded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from . import catalog
from .catalog import ModelError

if TYPE_CHECKING:
    from collections.abc import Sequence

    import numpy as np

SAMPLE_RATE = 16_000


class Engine(Protocol):
    model_id: str

    def transcribe(self, audio: np.ndarray, *, language: str = "auto",
                   hints: Sequence[str] = ()) -> str: ...


def load_engine(model_id: str) -> Engine:
    info = catalog.get(model_id)
    if info.hidden:
        raise ModelError(f"'{model_id}' is a support file, not a speech model")
    if not catalog.is_downloaded(model_id):
        raise ModelError(f"{model_id} isn't downloaded yet. Run: hark models download {model_id}")
    if info.engine == "parakeet":
        from .parakeet import ParakeetEngine

        return ParakeetEngine(info)
    from .whisper import WhisperEngine

    return WhisperEngine(info)


__all__ = ["SAMPLE_RATE", "Engine", "ModelError", "catalog", "load_engine"]
