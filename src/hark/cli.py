"""Command-line entry point: `hark <command>`."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import time
from dataclasses import asdict, is_dataclass

from . import __version__, paths
from . import config as config_mod
from .errors import HarkError
from .stt import catalog


def _save(cfg: config_mod.Config) -> None:
    """Save settings and tell a running Hark to pick them up."""
    from . import ipc

    config_mod.save(cfg)
    try:
        ipc.request("reload", timeout=3)
    except ipc.NotRunning:
        pass
    except HarkError as e:
        print(f"Saved, but the running Hark couldn't apply it: {e}", file=sys.stderr)


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
        _save(cfg)
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
    _save(cfg)
    print(f"Active model: {model_id}")
    if not catalog.is_downloaded(model_id):
        print(f"It isn't downloaded yet. Run: hark models download {model_id}")
    return 0


def _report(processed, stats: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"text": processed.text, "raw": processed.raw,
                          "rules_text": processed.rules_text, "llm": processed.llm_status,
                          "llm_s": round(processed.llm_s, 2), **stats}, ensure_ascii=False))
        return
    print(processed.text)
    if processed.llm_status != "off":
        print(f"[llm {processed.llm_status} ({processed.llm_s:.1f}s)]", file=sys.stderr)


def cmd_transcribe(args: argparse.Namespace) -> int:
    from .pipeline import Processed, process
    from .stt import SAMPLE_RATE, load_engine
    from .stt.audiofile import load_audio
    from .text import vocabulary

    cfg = config_mod.load()
    model_id = args.model or cfg.stt.model
    language = args.language or cfg.stt.language

    audio = load_audio(args.file)
    t0 = time.perf_counter()
    engine = load_engine(model_id)
    t1 = time.perf_counter()
    raw = engine.transcribe(audio, language=language, hints=vocabulary.terms(cfg.vocabulary))
    t2 = time.perf_counter()

    processed = (Processed(raw=raw, rules_text=raw, text=raw) if args.raw
                 else process(raw, cfg, use_llm=args.llm))
    audio_s = len(audio) / SAMPLE_RATE
    if not args.json:
        speed = audio_s / (t2 - t1) if t2 > t1 else float("inf")
        print(f"[{model_id}] audio {audio_s:.1f}s · load {t1 - t0:.1f}s · "
              f"transcribe {t2 - t1:.2f}s ({speed:.0f}x realtime)", file=sys.stderr)
    _report(processed, {"model": model_id, "audio_s": round(audio_s, 2),
                        "load_s": round(t1 - t0, 2), "transcribe_s": round(t2 - t1, 2)},
            args.json)
    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    from .pipeline import process

    text = " ".join(args.text) if args.text else sys.stdin.read()
    _report(process(text, config_mod.load(), use_llm=args.llm), {}, args.json)
    return 0


def cmd_llm(args: argparse.Namespace) -> int:
    from .llm.ollama import OllamaClient
    from .pipeline import keep_alive

    cfg = config_mod.load()
    client = OllamaClient(cfg.llm.url)
    action = args.llm_command

    if action == "status":
        print(f"cleanup: {'on' if cfg.llm.enabled else 'off'}")
        print(f"model:   {cfg.llm.model}")
        print(f"style:   {cfg.llm.style}")
        print(f"ollama:  {cfg.llm.url}")
        names, loaded = client.models(), client.loaded()
        pulled = cfg.llm.model in names or f"{cfg.llm.model}:latest" in names
        in_ram = any(n.split(":latest")[0] == cfg.llm.model.split(":latest")[0] for n in loaded)
        print(f"state:   {'pulled' if pulled else 'NOT pulled'}, "
              f"{'loaded in RAM' if in_ram else 'not loaded'}")
        return 0

    if action == "list":
        names = client.models()
        if not names:
            print("No Ollama models yet. Pull one, e.g.: ollama pull qwen2.5:3b")
        for name in names:
            active = name in (cfg.llm.model, f"{cfg.llm.model}:latest")
            print(f"{'*' if active else ' '} {name}")
        return 0

    if action == "style":
        cfg.llm.style = args.style
        _save(cfg)
        print(f"Cleanup style: {args.style}")
        return 0

    if action == "off":
        cfg.llm.enabled = False
        _save(cfg)
        print("LLM cleanup off (rule-based cleanup still applies).")
        return 0

    if action == "use":
        cfg.llm.model = args.model
    if not client.has_model(cfg.llm.model):
        raise HarkError(f"'{cfg.llm.model}' isn't pulled. Run: ollama pull {cfg.llm.model}")
    cfg.llm.enabled = True
    _save(cfg)
    print(f"LLM cleanup on with {cfg.llm.model} (style: {cfg.llm.style}).")
    print("Loading the model into memory…", end=" ", flush=True)
    start = time.perf_counter()
    client.warm_up(cfg.llm.model, keep_alive(cfg))
    print(f"ready in {time.perf_counter() - start:.1f}s")
    return 0


def cmd_vocab(args: argparse.Namespace) -> int:
    cfg = config_mod.load()
    action = args.vocab_command
    if action == "list":
        if not cfg.vocabulary:
            print('No vocabulary yet. Add one: hark vocab add "hark ai" "Hark.ai"')
        for e in cfg.vocabulary:
            print(e["to"] + "   (spelling hint)" if e["from"] == e["to"]
                  else f'{e["from"]}  ->  {e["to"]}')
        return 0
    key = args.phrase.strip()
    remaining = [e for e in cfg.vocabulary if e["from"].lower() != key.lower()]
    if action == "add":
        if not key:
            raise HarkError("the phrase can't be empty")
        cfg.vocabulary = [*remaining, {"from": key, "to": args.to or key}]
        print(f'Added: {key} -> {args.to or key}')
    else:
        if len(remaining) == len(cfg.vocabulary):
            raise HarkError(f"'{key}' isn't in the vocabulary")
        cfg.vocabulary = remaining
        print(f"Removed: {key}")
    _save(cfg)
    return 0


def _stamp(message: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {message}", flush=True)


def cmd_listen(args: argparse.Namespace) -> int:
    from .daemon import Daemon
    from .hotkey import pretty

    cfg = config_mod.load()
    if args.key:
        cfg.hotkey.combo = args.key
    if args.mode:
        cfg.hotkey.mode = args.mode
    if args.llm is not None:
        cfg.llm.enabled = args.llm

    def ready(daemon, load_s: float) -> None:
        d = daemon.dictation
        print(f"Loaded {cfg.stt.model} in {load_s:.1f}s.\n")
        if d.listener:
            action = "Hold" if cfg.hotkey.mode == "hold" else "Press"
            finish = "release to insert" if cfg.hotkey.mode == "hold" else "press again"
            print(f"  {action} {pretty(d.combo)}, speak, {finish}. Esc cancels.")
        else:
            print(f"  Hotkey unavailable ({daemon.hotkey_error}).")
        print("  Or run `hark toggle` (e.g. from a desktop shortcut).")
        print(f"  Paste: {d.injector.method} ({cfg.insert.paste_chord}) · "
              f"LLM cleanup: {cfg.llm.model if cfg.llm.enabled else 'off'}")
        if d.injector.uinput_error:
            print(f"  Note: virtual keyboard unavailable ({d.injector.uinput_error})")
        print("  Ctrl+C here to quit.\n", flush=True)

    print(f"Loading {cfg.stt.model}…", flush=True)
    Daemon(cfg, log=_stamp, log_text=True).run(on_ready=ready)
    return 0


def cmd_app(args: argparse.Namespace) -> int:
    from . import ipc

    if ipc.is_running():  # bring the existing window to the front
        ipc.request("show")
        return 0
    from .ui.app import run

    return run(hidden=args.hidden)


def cmd_daemon(args: argparse.Namespace) -> int:
    from . import daemon

    if args.detach:
        pid = daemon.detach()
        print(f"Hark is running in the background (pid {pid}).")
        print(f"Logs: {paths.log_file()} · stop with: hark quit")
        return 0
    daemon.run_foreground(config_mod.load())
    return 0


_STATE_ICONS = {"idle": "○", "recording": "●", "transcribing": "…"}


def _print_state(resp: dict) -> None:
    print(f"{_STATE_ICONS.get(resp['state'], '?')} {resp['state']}")


def cmd_control(args: argparse.Namespace) -> int:
    from . import ipc

    _print_state(ipc.request(args.command))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from . import ipc

    try:
        resp = ipc.request("status", timeout=2)
    except ipc.NotRunning:
        if args.json:
            print(json.dumps({"state": "stopped"}))
            return 3
        raise
    if args.json:
        resp.pop("ok", None)
        print(json.dumps(resp, ensure_ascii=False))
        return 0
    _print_state(resp)
    minutes, seconds = divmod(resp["uptime_s"], 60)
    print(f"  model:  {resp['model']}{'' if resp['model_loaded'] else ' (loading…)'}")
    print(f"  hotkey: {resp['hotkey'] or 'none: ' + (resp['hotkey_error'] or 'disabled')}"
          f" ({resp['mode']})")
    print(f"  llm:    {resp['llm'] or 'off'}")
    print(f"  pid {resp['pid']}, up {int(minutes)}m{int(seconds):02d}s")
    if resp.get("last"):
        print(f"  last:   {resp['last']['ts']} “{resp['last']['text']}”")
    return 0


def cmd_quit(args: argparse.Namespace) -> int:
    from . import ipc

    ipc.request("quit")
    deadline = time.monotonic() + 5
    while ipc.is_running():
        if time.monotonic() > deadline:
            raise HarkError("Hark is still shutting down; check: hark status")
        time.sleep(0.1)
    print("Hark stopped.")
    return 0


def cmd_reload(args: argparse.Namespace) -> int:
    from . import ipc

    ipc.request("reload")
    print("Settings reloaded.")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    from . import history

    if args.action == "clear":
        print(f"Deleted {history.clear()} entries.")
        return 0
    entries = history.read(args.n)
    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return 0
    if not entries:
        print("No dictations yet." + ("" if config_mod.load().save_history
                                      else " (History is off: hark config set save_history true)"))
    for e in entries:
        text = e.get("raw" if args.raw else "text", "")
        print(f"{e.get('ts', '').replace('T', ' ')}  {text}")
    return 0


def cmd_debug_hotkey(args: argparse.Namespace) -> int:
    from .hotkey import HotkeyListener, parse_combo, pretty

    combo = parse_combo(args.key or config_mod.load().hotkey.combo)
    print(f"Found {HotkeyListener.check_access()} readable input devices.")
    print(f"Shortcut: {pretty(combo)}. Press keys to see their names "
          f"(use them with: hark config set hotkey.combo NAME). Ctrl+C to quit.")
    listener = HotkeyListener(combo, lambda event: _stamp(event), report_all_keys=True)
    listener.start()
    try:
        threading.Event().wait()
    finally:
        listener.stop()
    return 0


def cmd_debug_mic(args: argparse.Namespace) -> int:
    import numpy as np

    from . import audio
    from .stt import SAMPLE_RATE

    level = [0.0]
    recorder = audio.Recorder(on_level=lambda rms: level.__setitem__(0, rms))
    print(f"Recording {args.seconds:g}s from the default microphone. Speak normally, e.g.:")
    print("  “The quick brown fox jumps over the lazy dog. I'm testing my microphone today.”")
    recorder.start()
    end = time.monotonic() + args.seconds
    while time.monotonic() < end:
        bars = min(40, int(level[0] * 400))
        print(f"\r  level |{'█' * bars}{' ' * (40 - bars)}|", end="", flush=True)
        time.sleep(0.05)
    recording = recorder.stop()
    report = audio.analyze(recording)
    print(f"\n\n  peak {report.peak:.2f} · clipped {report.clipped_pct:.2f}% · "
          f"speech {report.speech_db:.0f} dBFS · noise {report.noise_db:.0f} dBFS · "
          f"speech-to-noise {report.snr_db:.0f} dB")
    problems = report.problems()
    for problem in problems:
        print(f"  ✘ {problem}")
    if audio.is_silent(recording):
        print("  ✘ Only silence was captured. Check Settings → Sound → Input (and the mute key).")
        return 1
    if not problems:
        print("  ✔ The microphone signal looks good.")
    if args.save:
        import wave

        with wave.open(args.save, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes((np.clip(recording, -1, 1) * 32767).astype("<i2").tobytes())
        print(f"  Saved {args.save}")
    if args.transcribe or args.compare:
        from .stt import catalog, load_engine

        cfg = config_mod.load()
        models = ([m.id for m in catalog.selectable() if catalog.is_downloaded(m.id)]
                  if args.compare else [cfg.stt.model])
        print()
        for model_id in models:
            engine = load_engine(model_id)
            start = time.perf_counter()
            text = engine.transcribe(recording, language=cfg.stt.language)
            print(f"  {model_id:24} {time.perf_counter() - start:4.1f}s  {text}")
    return 1 if problems else 0


def cmd_debug_paste(args: argparse.Namespace) -> int:
    from .inject import Injector

    cfg = config_mod.load()
    injector = Injector(args.chord or cfg.insert.paste_chord, cfg.insert.restore_clipboard)
    try:
        print(f"Method: {injector.method}. Click into a text field…")
        for remaining in range(args.delay, 0, -1):
            print(f"  pasting in {remaining}…", flush=True)
            time.sleep(1)
        print(f"  {injector.insert(args.text)}")
    finally:
        injector.close()
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
    p.add_argument("--llm", action=argparse.BooleanOptionalAction, default=None,
                   help="force LLM cleanup on/off (default: the llm.enabled setting)")
    p.add_argument("--raw", action="store_true", help="print the transcript unprocessed")
    p.add_argument("--json", action="store_true", help="print text and timings as JSON")
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser("clean", help="run the cleanup pipeline on text (args or stdin)")
    p.add_argument("text", nargs="*")
    p.add_argument("--llm", action=argparse.BooleanOptionalAction, default=None,
                   help="force LLM cleanup on/off (default: the llm.enabled setting)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_clean)

    from .llm.polish import STYLES

    p = sub.add_parser("llm", help="configure LLM cleanup with a local Ollama model")
    lsub = p.add_subparsers(dest="llm_command", metavar="<action>", required=True)
    lsub.add_parser("status", help="show settings and whether the model is loaded")
    lsub.add_parser("list", help="list models pulled in Ollama")
    u = lsub.add_parser("use", help="turn cleanup on with this model, e.g. qwen2.5:3b")
    u.add_argument("model")
    lsub.add_parser("on", help="turn cleanup on with the current model")
    lsub.add_parser("off", help="turn cleanup off")
    st = lsub.add_parser("style", help="output style")
    st.add_argument("style", choices=list(STYLES))
    p.set_defaults(func=cmd_llm)

    p = sub.add_parser("vocab", help="names and jargon: replacements and spelling hints")
    vsub = p.add_subparsers(dest="vocab_command", metavar="<action>", required=True)
    vsub.add_parser("list", help="show vocabulary")
    a = vsub.add_parser("add", help='add a replacement ("hark ai" Hark.ai) or a spelling hint')
    a.add_argument("phrase")
    a.add_argument("to", nargs="?", help="replacement (omit for a spelling hint)")
    rm = vsub.add_parser("rm", help="remove an entry")
    rm.add_argument("phrase")
    p.set_defaults(func=cmd_vocab)

    p = sub.add_parser("listen", help="run Hark in this terminal, showing what you dictate")
    p.add_argument("--key", help="override the shortcut, e.g. rightctrl or leftmeta+space")
    p.add_argument("--mode", choices=["hold", "toggle"], help="override hold/toggle mode")
    p.add_argument("--llm", action=argparse.BooleanOptionalAction, default=None,
                   help="force LLM cleanup on/off")
    p.set_defaults(func=cmd_listen)

    p = sub.add_parser("app", help="open the Hark app (dictation + dashboard)")
    p.add_argument("--hidden", action="store_true",
                   help="start without showing the window (used at login)")
    p.set_defaults(func=cmd_app)

    p = sub.add_parser("daemon", help="run Hark in the background service mode")
    p.add_argument("--detach", action="store_true", help="start in the background and return")
    p.set_defaults(func=cmd_daemon)

    for name, text in (("toggle", "start or stop dictating (bind this to a desktop shortcut)"),
                       ("start", "start dictating"), ("stop", "stop dictating and insert the text"),
                       ("cancel", "discard the current recording")):
        p = sub.add_parser(name, help=text)
        p.set_defaults(func=cmd_control)

    p = sub.add_parser("status", help="show whether Hark is running and what it's doing")
    p.add_argument("--json", action="store_true", help="for status bars (exit code 3 = stopped)")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("quit", help="stop the background service")
    p.set_defaults(func=cmd_quit)

    p = sub.add_parser("reload", help="make the running Hark re-read its settings")
    p.set_defaults(func=cmd_reload)

    p = sub.add_parser("history", help="show recent dictations")
    p.add_argument("action", nargs="?", choices=["clear"], help="delete the history")
    p.add_argument("-n", type=int, default=20, help="how many (default 20)")
    p.add_argument("--raw", action="store_true", help="show text before cleanup")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("debug-hotkey", help="show key presses and shortcut events")
    p.add_argument("--key", help="shortcut to test (default: hotkey.combo)")
    p.set_defaults(func=cmd_debug_hotkey)

    p = sub.add_parser("debug-mic", help="record a few seconds and show the input level")
    p.add_argument("--seconds", type=float, default=4)
    p.add_argument("--save", metavar="FILE.wav", help="also save the recording")
    p.add_argument("--transcribe", action="store_true", help="also transcribe it")
    p.add_argument("--compare", action="store_true",
                   help="transcribe with every downloaded model, to compare accuracy")
    p.set_defaults(func=cmd_debug_mic)

    p = sub.add_parser("debug-paste", help="paste test text into the focused app after a delay")
    p.add_argument("--text", default="Hello from Hark! ")
    p.add_argument("--delay", type=int, default=3)
    p.add_argument("--chord", choices=["ctrl+v", "ctrl+shift+v", "shift+insert", "type"])
    p.set_defaults(func=cmd_debug_paste)

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
