"""Command-line entry point: `hark <command>`."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import asdict, is_dataclass

from . import __version__, paths
from . import config as config_mod


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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except config_mod.ConfigError as e:
        print(f"hark: {e}", file=sys.stderr)
        return 1
