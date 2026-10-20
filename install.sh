#!/usr/bin/env bash
# Hark installer: local-first push-to-talk dictation for Linux.
#
#   curl -fsSL https://<hark website>/install.sh | bash
#   (or from GitHub: curl -fsSL https://raw.githubusercontent.com/Sravan1011/Hark.ai/main/install.sh | bash)
#
# Options (with curl, pass them after `bash -s --`, e.g. `| bash -s -- --no-model`):
#   --version vX.Y.Z   install a specific release (default: latest)
#   --no-system        skip system packages and keyboard permissions (no sudo)
#   --no-model         don't download the default speech model (~670 MB)
#   -y, --yes          don't ask for confirmation
#   --uninstall        remove Hark (keeps your models, history, notes and settings)
#   --purge            with --uninstall: also delete models, history, notes and settings
#   --wheel FILE       install from a local wheel (for testing)
#
# What it does: installs PortAudio, clipboard tools and keyboard/virtual-keyboard
# permissions (asks for sudo, via scripts/setup-linux.sh from the same release), creates a
# private Python environment in ~/.local/share/hark/venv, links `hark` into ~/.local/bin,
# adds Hark to your app menu and downloads the default speech model.

set -euo pipefail

REPO="Sravan1011/Hark.ai"
DEFAULT_MODEL="parakeet-v3"

main() {
    local version="latest" system=1 model=1 assume_yes=0 uninstall=0 purge=0 wheel=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --version) version="${2:?--version needs a tag, e.g. v0.1.0}"; shift ;;
            --no-system) system=0 ;;
            --no-model) model=0 ;;
            -y|--yes) assume_yes=1 ;;
            --uninstall) uninstall=1 ;;
            --purge) purge=1 ;;
            --wheel) wheel="${2:?--wheel needs a file}"; shift ;;
            -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]:-/dev/null}" 2>/dev/null \
                         || echo "See https://github.com/$REPO"; return 0 ;;
            *) fail "unknown option: $1 (see --help)" ;;
        esac
        shift
    done

    local data="${XDG_DATA_HOME:-$HOME/.local/share}/hark"
    VENV="${HARK_VENV:-$data/venv}"
    BIN_DIR="${HARK_BIN_DIR:-$HOME/.local/bin}"

    [[ "$(uname -s)" == "Linux" ]] || fail "Hark runs on Linux only."
    [[ $EUID -ne 0 ]] || fail "run this as your normal user (not root/sudo); it asks for sudo itself."

    if [[ $uninstall -eq 1 ]]; then
        do_uninstall "$purge" "$data"
        return
    fi

    # -- what to install -------------------------------------------------------------
    local tag spec
    if [[ -n "$wheel" ]]; then
        [[ -f "$wheel" ]] || fail "no such wheel: $wheel"
        tag="local"
        spec="hark[stt,gui] @ file://$(cd "$(dirname "$wheel")" && pwd)/$(basename "$wheel")"
    else
        tag="$version"
        if [[ "$tag" == "latest" ]]; then
            tag="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
                   | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n1)" \
                || fail "couldn't reach GitHub to find the latest release."
            [[ -n "$tag" ]] || fail "couldn't find a published Hark release."
        fi
        spec="hark[stt,gui] @ https://github.com/$REPO/releases/download/$tag/hark-${tag#v}-py3-none-any.whl"
    fi

    say "Installing Hark $tag"
    note "app:    $VENV"
    note "command: $BIN_DIR/hark"
    [[ $system -eq 1 ]] && note "system: audio/clipboard packages and keyboard permissions (sudo)"
    [[ $model -eq 1 ]] && note "model:  $DEFAULT_MODEL speech model (~670 MB, one-time download)"
    confirm "$assume_yes" || fail "cancelled."

    # -- 1. system packages and permissions ----------------------------------------------
    local relogin=0
    if [[ $system -eq 1 ]]; then
        say "System packages and keyboard permissions"
        local setup tmp
        tmp="$(mktemp -d)"
        trap 'rm -rf "$tmp"' EXIT
        if [[ -n "${HARK_SETUP_SCRIPT:-}" ]]; then
            setup="$HARK_SETUP_SCRIPT"
        else
            local ref="$tag"
            [[ "$ref" == "local" ]] && ref="main"
            setup="$tmp/setup-linux.sh"
            curl -fsSL "https://raw.githubusercontent.com/$REPO/$ref/scripts/setup-linux.sh" \
                -o "$setup" || fail "couldn't download the system setup script."
        fi
        # stdin from /dev/null: package managers must not read the rest of this piped
        # script as answers. sudo asks for the password on the terminal directly.
        bash "$setup" --system-only --yes < /dev/null
        if id -nG "$USER" | tr ' ' '\n' | grep -qx input \
                && ! id -nG | tr ' ' '\n' | grep -qx input; then
            relogin=1
        fi
    fi

    # -- 2. Python environment ------------------------------------------------------------
    say "Hark itself"
    local python="${PYTHON:-python3}"
    command -v "$python" >/dev/null || fail "python3 not found; install Python 3.10 or newer."
    "$python" -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
        || fail "Python 3.10+ is required (found $("$python" --version 2>&1))."
    "$python" -c 'import venv, ensurepip' 2>/dev/null \
        || fail "Python's venv module is missing (Debian/Ubuntu: sudo apt install python3-venv)."
    if [[ ! -x "$VENV/bin/python" ]]; then
        mkdir -p "$(dirname "$VENV")"
        "$python" -m venv "$VENV"
    fi
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet --upgrade "$spec" \
        || fail "installing Hark failed (see the pip output above)."
    mkdir -p "$BIN_DIR"
    ln -sfn "$VENV/bin/hark" "$BIN_DIR/hark"
    "$VENV/bin/python" -c 'from hark import desktop; desktop.install_launcher()'
    note "installed $("$VENV/bin/hark" --version)"

    # -- 3. speech model -------------------------------------------------------------------
    if [[ $model -eq 1 ]]; then
        say "Speech model ($DEFAULT_MODEL)"
        "$VENV/bin/hark" models download "$DEFAULT_MODEL" \
            || note "The download didn't finish; resume later with: hark models download $DEFAULT_MODEL"
    fi

    # -- done -------------------------------------------------------------------------------
    say "Done"
    if "$VENV/bin/hark" status --json >/dev/null 2>&1; then
        note "Hark is running an older version; restart it: hark quit && hark app"
    fi
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *) note "$BIN_DIR isn't on your PATH; add it, or run $BIN_DIR/hark directly." ;;
    esac
    if [[ $relogin -eq 1 ]]; then
        printf '\n    \033[1;33mLog out and back in once\033[0m so the keyboard permission applies.\n'
        printf '    Then open Hark from your app menu, or run: hark app\n\n'
    else
        printf '\n    Open Hark from your app menu, or run: \033[1mhark app\033[0m\n'
        printf '    Then hold Right Ctrl in any text box, speak, and let go.\n\n'
    fi
}

do_uninstall() {
    local purge="$1" data="$2"
    say "Uninstalling Hark"
    if [[ -x "$VENV/bin/hark" ]]; then
        "$VENV/bin/hark" quit >/dev/null 2>&1 || true
        "$VENV/bin/python" -c 'from hark import desktop
desktop.set_autostart(False)
desktop.launcher_file().unlink(missing_ok=True)' || true
    fi
    if [[ -L "$BIN_DIR/hark" && "$(readlink "$BIN_DIR/hark")" == "$VENV/"* ]]; then
        rm -f "$BIN_DIR/hark"
    fi
    rm -rf "$VENV"
    note "removed the app, the hark command and the app-menu entry"
    if [[ "$purge" -eq 1 ]]; then
        rm -rf "$data" "${XDG_CONFIG_HOME:-$HOME/.config}/hark" \
               "${XDG_STATE_HOME:-$HOME/.local/state}/hark"
        note "deleted models, history, notes and settings"
    else
        note "kept your models, history, notes and settings ($data); --purge deletes them"
    fi
    note "System packages and the keyboard permission were left in place. To remove the"
    note "permission: sudo rm /etc/udev/rules.d/80-hark-uinput.rules /etc/modules-load.d/hark-uinput.conf"
}

confirm() {
    [[ "$1" -eq 1 ]] && return 0
    if [[ ! -r /dev/tty ]]; then
        note "No terminal to ask for confirmation; re-run with --yes to proceed."
        return 1
    fi
    local answer
    printf '\n    Continue? [Y/n] ' > /dev/tty
    read -r answer < /dev/tty || return 1
    [[ -z "$answer" || "$answer" =~ ^[Yy] ]]
}

say()  { printf '\n\033[1;34m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
fail() { printf '\n\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

# Everything runs from main, so a partially downloaded script can't run half-way.
main "$@"
