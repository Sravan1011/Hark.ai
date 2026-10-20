"""Decode any audio file (wav, mp3, ogg, m4a, ...) to 16 kHz mono float32.

Uses PyAV directly rather than faster_whisper.decode_audio, which passes an argument that
PyAV 19 removed (and PyAV 19 is what Python 3.12+ installs get).
"""

from __future__ import annotations

import numpy as np

from ..errors import HarkError
from . import SAMPLE_RATE


class AudioFileError(HarkError):
    pass


def load_audio(path: str) -> np.ndarray:
    import av

    chunks: list[np.ndarray] = []
    try:
        with av.open(path) as container:
            if not container.streams.audio:
                raise AudioFileError(f"{path} has no audio track")
            resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
            for frame in container.decode(audio=0):
                chunks.extend(out.to_ndarray().reshape(-1) for out in resampler.resample(frame))
            chunks.extend(out.to_ndarray().reshape(-1) for out in resampler.resample(None))
    except (OSError, ValueError, av.FFmpegError) as e:
        raise AudioFileError(f"can't read audio from {path}: {e}") from e
    if not chunks:
        return np.zeros(0, np.float32)
    return np.concatenate(chunks).astype(np.float32)
