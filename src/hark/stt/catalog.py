"""Speech models Hark can download, and where they live on disk.

Kept free of heavy imports: config.py imports this for validation.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .. import paths
from ..errors import HarkError


class ModelError(HarkError):
    pass


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str
    engine: str  # "parakeet" | "whisper" | "vad"
    repo: str  # Hugging Face repo
    files: tuple[str, ...]  # allow_patterns for the download
    size_mb: int
    languages: str
    note: str = ""
    onnx_asr_name: str = ""  # model name passed to onnx-asr (Parakeet only)
    english_only: bool = False
    hidden: bool = False  # support files, not selectable as a speech model


_PARAKEET_FILES = ("config.json", "vocab.txt", "encoder-model.int8.onnx",
                   "decoder_joint-model.int8.onnx")
# Same patterns faster_whisper.utils.download_model uses.
_WHISPER_FILES = ("config.json", "preprocessor_config.json", "model.bin", "tokenizer.json",
                  "vocabulary.*")

CATALOG: tuple[ModelInfo, ...] = (
    ModelInfo("parakeet-v3", "Parakeet TDT 0.6B v3", "parakeet",
              "istupakov/parakeet-tdt-0.6b-v3-onnx", _PARAKEET_FILES, 670,
              "25 European languages", "recommended; fast on CPU",
              onnx_asr_name="nemo-parakeet-tdt-0.6b-v3"),
    ModelInfo("parakeet-v2", "Parakeet TDT 0.6B v2", "parakeet",
              "istupakov/parakeet-tdt-0.6b-v2-onnx", _PARAKEET_FILES, 661,
              "English", "best English accuracy; fast on CPU",
              onnx_asr_name="nemo-parakeet-tdt-0.6b-v2", english_only=True),
    ModelInfo("whisper-base.en", "Whisper base.en", "whisper",
              "Systran/faster-whisper-base.en", _WHISPER_FILES, 148,
              "English", "smallest; lower accuracy", english_only=True),
    ModelInfo("whisper-small", "Whisper small", "whisper",
              "Systran/faster-whisper-small", _WHISPER_FILES, 486,
              "99 languages", "multilingual"),
    ModelInfo("whisper-large-v3-turbo", "Whisper large-v3 turbo", "whisper",
              "mobiuslabsgmbh/faster-whisper-large-v3-turbo", _WHISPER_FILES, 1622,
              "99 languages", "most accurate; slow without a GPU"),
    ModelInfo("silero-vad", "Silero VAD", "vad", "istupakov/silero-vad-onnx",
              ("config.json", "silero_vad.onnx"), 2, "-", hidden=True),
)

# Parakeet handles ~25 s per pass; longer recordings are split with Silero VAD.
REQUIRES: dict[str, tuple[str, ...]] = {"parakeet": ("silero-vad",)}

_MARKER = ".hark-complete"


def selectable() -> list[ModelInfo]:
    return [m for m in CATALOG if not m.hidden]


def selectable_ids() -> tuple[str, ...]:
    return tuple(m.id for m in selectable())


def get(model_id: str) -> ModelInfo:
    for m in CATALOG:
        if m.id == model_id:
            return m
    raise ModelError(f"unknown model '{model_id}'. Available: {', '.join(selectable_ids())}")


def model_dir(model_id: str) -> Path:
    return paths.models_dir() / model_id


def _complete(model_id: str) -> bool:
    return (model_dir(model_id) / _MARKER).is_file()


def is_downloaded(model_id: str) -> bool:
    info = get(model_id)
    return _complete(model_id) and all(_complete(d) for d in REQUIRES.get(info.engine, ()))


def disk_usage(model_id: str) -> int:
    root = model_dir(model_id)
    if not root.exists():
        return 0
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def _download_one(info: ModelInfo, tqdm_class: type | None) -> None:
    # The xet transfer protocol can stall silently on some networks; plain HTTPS is
    # reliable and resumable. Must be set before huggingface_hub is imported.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    from huggingface_hub import snapshot_download

    target = model_dir(info.id)
    target.mkdir(parents=True, exist_ok=True)
    try:
        snapshot_download(info.repo, local_dir=target, allow_patterns=list(info.files),
                          tqdm_class=tqdm_class)
    except Exception as e:  # network/hub errors vary; all mean "retry"
        raise ModelError(f"downloading {info.id} failed: {e}\n"
                         f"Partial files are kept; run the same command again to resume.") from e
    (target / _MARKER).write_text(json.dumps({"repo": info.repo}) + "\n")


def download(model_id: str, tqdm_class: type | None = None) -> None:
    """Download a model (and anything it requires). Resumes interrupted downloads."""
    info = get(model_id)
    for dep in REQUIRES.get(info.engine, ()):
        if not _complete(dep):
            _download_one(get(dep), tqdm_class)
    if not _complete(model_id):
        _download_one(info, tqdm_class)


def remove(model_id: str) -> int:
    """Delete a model's files; returns bytes freed. Shared support files are kept."""
    get(model_id)
    freed = disk_usage(model_id)
    shutil.rmtree(model_dir(model_id), ignore_errors=True)
    return freed
