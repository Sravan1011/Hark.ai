# Changelog

## [0.1.0] - First public beta

Hold a key, speak, and your words are typed into any app — on X11 and Wayland, fully
on-device.

### Dictation
- Hold-to-talk (default **Right Ctrl**) or press-to-toggle, with any key or combination,
  including mouse side buttons. `hark toggle` can be bound to your desktop's own shortcut.
- Works in every app: text is pasted through a virtual keyboard (Ctrl+V, Ctrl+Shift+V for
  terminals, or Shift+Insert), with xdotool / wtype / ydotool fallbacks.
- Speech-to-text runs locally: NVIDIA Parakeet v2/v3 (fast on CPU) and Whisper base,
  small and large-v3 turbo. About 0.7 s for 5 s of speech on an 11th-gen Intel i5.

### Cleanup
- Removes filler words and stutters; voice commands for punctuation, new lines,
  "scratch that" and @mentions; your own dictionary of names and jargon.
- Optional AI cleanup with a local Ollama model, with safeguards that keep your original
  text if the model rewrites, answers or invents.

### App
- Dashboard with stats, searchable history, voice notes (with AI title & summary),
  dictionary, style, model manager and settings.
- Recording capsule with a live waveform that never steals focus.
- Start at login, app-menu entry, system check, and a microphone diagnostic
  (`hark debug-mic --compare`) that catches clipping and noise.

### Install
- One-line installer for apt, dnf, pacman and zypper systems, with `--uninstall`.

Tested on Debian 12 (GNOME, Wayland, Python 3.11). Other distributions and desktops are
supported by design but less tested — please report issues.
