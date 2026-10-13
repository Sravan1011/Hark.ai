"""Decode any audio file (wav, mp3, ogg, m4a, ...) to 16 kHz mono float32."""

from __future__ import annotations

import numpy as np

from ..errors import HarkError
from . import SAMPLE_RATE


class AudioFileError(HarkError):
    pass


def load_audio(path: str) -> np.ndarray:
    import av
    from faster_whisper.audio import decode_audio

    try:
        return decode_audio(path, sampling_rate=SAMPLE_RATE)
    except (OSError, ValueError, av.FFmpegError) as e:
        raise AudioFileError(f"can't read audio from {path}: {e}") from e
