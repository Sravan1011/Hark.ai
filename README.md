# Hark

Local-first push-to-talk dictation for Linux. Hold a key (or trigger `hark toggle`
from your desktop's shortcut settings), speak, and the text is typed into the focused
app. Speech-to-text runs on-device (Parakeet / Whisper), with optional cleanup by a
local Ollama model. Works on X11 and Wayland.

> Status: early development. Phase 1 (installation + `hark doctor`) is done;
> dictation itself lands in later phases.

## Install

```bash
# 1. System packages + keyboard/uinput permissions + Python venv (asks for sudo)
bash scripts/setup-linux.sh          # add --dry-run to preview every command

# 2. Log out and back in (so the 'input' group membership applies)

# 3. Check everything is ready
.venv/bin/hark doctor

# 4. Optional: local LLM cleanup of transcripts
bash scripts/install-ollama.sh       # pulls qwen2.5:3b; --model qwen2.5:1.5b for speed
```

Supported package managers: apt, dnf, pacman, zypper. On other distros, install
PortAudio, wl-clipboard, xclip and xdotool yourself, then run
`bash scripts/setup-linux.sh --skip-packages`.

### Why the permissions?

- **`input` group** lets Hark see your hotkey being held and released on any desktop,
  including Wayland, where apps can't register global hotkeys themselves.
- **`/dev/uinput`** lets Hark press Ctrl+V through a virtual keyboard to paste the text.

## Commands so far

```
hark doctor [--json]            check this machine and print fixes
hark config path|show|edit      settings file (~/.config/hark/config.json)
hark config get llm.model
hark config set llm.model qwen2.5:1.5b
```
