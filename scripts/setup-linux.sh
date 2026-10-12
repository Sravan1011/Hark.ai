#!/usr/bin/env bash
# Hark setup: system packages, keyboard/uinput permissions, and the Python venv.
# Safe to re-run. Run as your normal user; it calls sudo only where needed.
set -euo pipefail

DRY_RUN=0
ASSUME_YES=0
DO_PACKAGES=1
DO_PERMISSIONS=1
DO_PYTHON=1
NEED_RELOGIN=0

usage() {
    cat <<'EOF'
Usage: bash scripts/setup-linux.sh [options]

  --dry-run           print the commands without running them
  -y, --yes           don't ask the package manager for confirmation
  --system-only       packages + permissions, skip the Python venv
  --python-only       only create .venv and install Python dependencies
  --skip-packages     skip installing system packages
  --skip-permissions  skip the input group / uinput setup
  -h, --help          show this help

Supported package managers: apt (Debian/Ubuntu/Mint/Pop), dnf (Fedora/RHEL),
pacman (Arch/Manjaro/EndeavourOS), zypper (openSUSE).
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        -y|--yes) ASSUME_YES=1 ;;
        --system-only) DO_PYTHON=0 ;;
        --python-only) DO_PACKAGES=0; DO_PERMISSIONS=0 ;;
        --skip-packages) DO_PACKAGES=0 ;;
        --skip-permissions) DO_PERMISSIONS=0 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

if [[ $EUID -eq 0 ]]; then
    echo "Run this as your normal user (without sudo); it asks for sudo when needed." >&2
    exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log()  { printf '\n\033[1;34m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
run()  { printf '    $ %s\n' "$*"; if [[ $DRY_RUN -eq 0 ]]; then "$@"; fi; }

# Write a root-owned file only if its content differs.
write_root_file() {
    local path=$1 content=$2
    if [[ -f $path && "$(<"$path")" == "$content" ]]; then
        note "unchanged: $path"
        return
    fi
    printf "    \$ echo '%s' | sudo tee %s\n" "$content" "$path"
    if [[ $DRY_RUN -eq 0 ]]; then
        printf '%s\n' "$content" | sudo tee "$path" >/dev/null
    fi
}

detect_pm() {
    for pm in apt-get dnf pacman zypper; do
        if command -v "$pm" >/dev/null 2>&1; then echo "$pm"; return; fi
    done
    echo ""
}

install_packages() {
    local pm
    pm=$(detect_pm)
    log "Installing system packages"
    case "$pm" in
        apt-get)
            # audio, clipboard (Wayland + X11), X11 paste fallback, evdev build deps, Qt xcb deps
            local pkgs=(libportaudio2 wl-clipboard xclip xdotool python3-venv python3-dev gcc
                        linux-libc-dev libxcb-cursor0 libxkbcommon-x11-0)
            local yes=(); [[ $ASSUME_YES -eq 1 ]] && yes=(-y)
            run sudo apt-get update
            run sudo apt-get install "${yes[@]}" "${pkgs[@]}"
            ;;
        dnf)
            local pkgs=(portaudio wl-clipboard xclip xdotool python3-devel gcc kernel-headers
                        xcb-util-cursor libxkbcommon-x11)
            local yes=(); [[ $ASSUME_YES -eq 1 ]] && yes=(-y)
            run sudo dnf install "${yes[@]}" "${pkgs[@]}"
            ;;
        pacman)
            local pkgs=(portaudio wl-clipboard xclip xdotool python gcc linux-api-headers
                        xcb-util-cursor libxkbcommon-x11)
            local yes=(); [[ $ASSUME_YES -eq 1 ]] && yes=(--noconfirm)
            run sudo pacman -S --needed "${yes[@]}" "${pkgs[@]}"
            ;;
        zypper)
            local pkgs=(libportaudio2 wl-clipboard xclip xdotool python3-devel gcc
                        linux-glibc-devel libxcb-cursor0 libxkbcommon-x11-0)
            local yes=(); [[ $ASSUME_YES -eq 1 ]] && yes=(--non-interactive)
            run sudo zypper "${yes[@]}" install "${pkgs[@]}"
            ;;
        *)
            note "No supported package manager found. Install these yourself:"
            note "  PortAudio, wl-clipboard, xclip, xdotool, Python 3.10+ headers, gcc,"
            note "  kernel/libc headers, xcb-util-cursor, libxkbcommon-x11"
            ;;
    esac
}

setup_permissions() {
    log "Keyboard access (hold-to-talk hotkey)"
    if ! getent group input >/dev/null; then
        run sudo groupadd --system input
    fi
    if id -nG "$USER" | tr ' ' '\n' | grep -qx input; then
        note "$USER is already in the 'input' group"
    else
        run sudo usermod -aG input "$USER"
        NEED_RELOGIN=1
    fi

    log "Virtual keyboard access (/dev/uinput, used to press Ctrl+V)"
    write_root_file /etc/udev/rules.d/80-hark-uinput.rules \
        'KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"'
    write_root_file /etc/modules-load.d/hark-uinput.conf 'uinput'
    run sudo modprobe uinput
    run sudo udevadm control --reload-rules
    run sudo udevadm trigger --action=change --name-match=/dev/uinput || true
    # Apply immediately too, in case this udev version ignores --name-match.
    if [[ -e /dev/uinput || $DRY_RUN -eq 1 ]]; then
        run sudo chgrp input /dev/uinput
        run sudo chmod 0660 /dev/uinput
    fi
}

setup_python() {
    log "Python environment (.venv)"
    local py=${PYTHON:-python3}
    if ! "$py" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
        echo "Python 3.10+ is required (found: $("$py" --version 2>&1))." >&2
        exit 1
    fi
    if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
        run "$py" -m venv "$ROOT/.venv"
    fi
    run "$ROOT/.venv/bin/pip" install --upgrade pip
    run "$ROOT/.venv/bin/pip" install -e "$ROOT[stt,gui,dev]"
}

[[ $DO_PACKAGES -eq 1 ]] && install_packages
[[ $DO_PERMISSIONS -eq 1 ]] && setup_permissions
[[ $DO_PYTHON -eq 1 ]] && setup_python

log "Done"
if [[ $NEED_RELOGIN -eq 1 ]]; then
    printf '    \033[1;33mLog out and back in\033[0m so the new input group membership applies.\n'
fi
if [[ -x "$ROOT/.venv/bin/hark" && $DRY_RUN -eq 0 ]]; then
    note "Check the result with: $ROOT/.venv/bin/hark doctor"
fi
note "Optional LLM cleanup: bash scripts/install-ollama.sh"
