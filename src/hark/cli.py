"""Command-line entry point: `hark <command>`."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import asdict, is_dataclass

from . import __version__, paths
from . import config as config_mod
from .errors import HarkError
from .stt import catalog


def cmd_doctor(args: argparse.Namespace) -> int:
    from . import doctor

    return doctor.main(as_json=args.json)


def cmd_config(args: argparse.Namespace) -> int:
    path = paths.config_file()
    action = args.config_command

    if action == "path":
        print(path)
        return 0

    if action == "edit":
        if not path.exists():
            config_mod.save(config_mod.Config())
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or shutil.which("nano") \
            or "vi"
        os.execvp(editor, [editor, str(path)])

    cfg = config_mod.load()
    if action == "show":
        print(json.dumps(asdict(cfg), indent=2))
    elif action == "get":
        value = config_mod.get_value(cfg, args.key)
        if is_dataclass(value):
            print(json.dumps(asdict(value), indent=2))
        elif isinstance(value, (bool, list)):
            print(json.dumps(value))
        else:
            print(value)
    elif action == "set":
        value = config_mod.set_value(cfg, args.key, args.value)
        config_mod.save(cfg)
        print(f"{args.key} = {json.dumps(value)}")
    return 0


def _fmt_mb(size_bytes: int) -> str:
    return f"{size_bytes / 1e6:,.0f} MB"


def cmd_models(args: argparse.Namespace) -> int:
    action = args.models_command
    cfg = config_mod.load()

    if action == "list":
        rows = [("", "ID", "SIZE", "LANGUAGES", "STATUS", "NOTES")]
        for m in catalog.selectable():
            rows.append(("*" if m.id == cfg.stt.model else "", m.id, f"{m.size_mb:,} MB",
                         m.languages, "downloaded" if catalog.is_downloaded(m.id) else "-",
                         m.note))
        widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
        for r in rows:
            print("  ".join(cell.ljust(w) for cell, w in zip(r, widths)).rstrip())
        print(f"\n* = active model. Files: {paths.models_dir()}")
        return 0

    info = catalog.get(args.model)
    if info.hidden:
        raise catalog.ModelError(f"'{info.id}' is a support file, not a speech model")

    if action == "download":
        if catalog.is_downloaded(info.id):
            print(f"{info.id} is already downloaded.")
        else:
            print(f"Downloading {info.name} (~{info.size_mb:,} MB) from huggingface.co/{info.repo}")
            catalog.download(info.id)
            print(f"Downloaded {info.id}.")
        if args.use or cfg.stt.model == info.id:
            return _use_model(cfg, info.id)
        print(f"Make it active with: hark models use {info.id}")
        return 0

    if action == "use":
        return _use_model(cfg, info.id)

    if action == "rm":
        size = catalog.disk_usage(info.id)
        if size == 0:
            print(f"{info.id} isn't downloaded.")
            return 0
        if not args.yes:
            answer = input(f"Delete {info.id} ({_fmt_mb(size)})? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                return 1
        print(f"Removed {info.id}, freed {_fmt_mb(catalog.remove(info.id))}.")
        if cfg.stt.model == info.id:
            print("Note: that was the active model; pick another with: hark models use <id>")
    return 0


def _use_model(cfg: config_mod.Config, model_id: str) -> int:
    cfg.stt.model = model_id
    config_mod.save(cfg)
    print(f"Active model: {model_id}")
    if not catalog.is_downloaded(model_id):
        print(f"It isn't downloaded yet. Run: hark models download {model_id}")
    return 0


def cmd_transcribe(args: argparse.Namespace) -> int:
    from .stt import SAMPLE_RATE, load_engine
    from .stt.audiofile import load_audio

    cfg = config_mod.load()
    model_id = args.model or cfg.stt.model
    language = args.language or cfg.stt.language
    hints = [v["to"] for v in cfg.vocabulary]

    audio = load_audio(args.file)
    t0 = time.perf_counter()
    engine = load_engine(model_id)
    t1 = time.perf_counter()
    text = engine.transcribe(audio, language=language, hints=hints)
    t2 = time.perf_counter()

    audio_s = len(audio) / SAMPLE_RATE
    stats = {"model": model_id, "audio_s": round(audio_s, 2), "load_s": round(t1 - t0, 2),
             "transcribe_s": round(t2 - t1, 2)}
    if args.json:
        print(json.dumps({"text": text, **stats}, ensure_ascii=False))
    else:
        print(text)
        speed = audio_s / (t2 - t1) if t2 > t1 else float("inf")
        print(f"[{model_id}] audio {audio_s:.1f}s · load {t1 - t0:.1f}s · "
              f"transcribe {t2 - t1:.2f}s ({speed:.0f}x realtime)", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hark", description="Local-first push-to-talk dictation for Linux.")
    parser.add_argument("--version", action="version", version=f"hark {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("doctor", help="check that this machine is ready for Hark")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("config", help="show or change settings")
    csub = p.add_subparsers(dest="config_command", metavar="<action>", required=True)
    csub.add_parser("path", help="print the config file location")
    csub.add_parser("show", help="print all settings")
    csub.add_parser("edit", help="open the config file in $EDITOR")
    g = csub.add_parser("get", help="print one setting, e.g. llm.model")
    g.add_argument("key")
    s = csub.add_parser("set", help="change one setting, e.g. llm.model qwen2.5:1.5b")
    s.add_argument("key")
    s.add_argument("value")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("models", help="list, download, select or remove speech models")
    msub = p.add_subparsers(dest="models_command", metavar="<action>", required=True)
    msub.add_parser("list", help="show available models")
    d = msub.add_parser("download", help="download a model (resumes if interrupted)")
    d.add_argument("model")
    d.add_argument("--use", action="store_true", help="also make it the active model")
    u = msub.add_parser("use", help="set the active model")
    u.add_argument("model")
    r = msub.add_parser("rm", help="delete a downloaded model")
    r.add_argument("model")
    r.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    p.set_defaults(func=cmd_models)

    p = sub.add_parser("transcribe", help="transcribe an audio file (wav, mp3, ogg, ...)")
    p.add_argument("file")
    p.add_argument("--model", help="model id (default: the active model)")
    p.add_argument("--language", help="language code for Whisper, e.g. en, de (default: auto)")
    p.add_argument("--json", action="store_true", help="print text and timings as JSON")
    p.set_defaults(func=cmd_transcribe)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except HarkError as e:
        print(f"hark: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 130
