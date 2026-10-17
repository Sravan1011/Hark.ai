"""Settings: shortcut, typing, feedback, privacy, system integration and a system check."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QVBoxLayout

from ... import desktop, doctor
from ...hotkey import HotkeyError, HotkeyListener, parse_combo, pretty
from .. import theme
from ..context import Context
from ..widgets import Card, Page, Segmented, Toggle, button, clear_layout, label, setting_row

PASTE_OPTIONS = [("ctrl+v", "Ctrl+V (most apps)"), ("ctrl+shift+v", "Ctrl+Shift+V (terminals)"),
                 ("shift+insert", "Shift+Insert"), ("type", "Type it (X11 / wlroots only)")]
# Mouse clicks and touchpad taps can't be the shortcut (you'd click the dialog's buttons).
_IGNORED_KEYS = {"BTN_LEFT", "BTN_RIGHT", "BTN_MIDDLE", "BTN_TOUCH", "BTN_TOOL_FINGER",
                 "BTN_TOOL_DOUBLETAP", "BTN_TOOL_TRIPLETAP", "BTN_TOOL_QUADTAP"}
_STATUS_COLORS = {"ok": theme.SUCCESS, "info": theme.MUTED, "warn": theme.WARNING,
                  "fail": theme.DANGER}


class ShortcutDialog(QDialog):
    """Records a key or combination: press it, then release all keys."""

    def __init__(self, parent, ctx: Context):
        super().__init__(parent)
        self.setWindowTitle("Change shortcut")
        self.setMinimumWidth(420)
        self.setStyleSheet(f"QDialog {{ background: {theme.CARD}; }}")
        self.ctx = ctx
        self.keys: list[str] = []
        self._down: set[str] = set()
        self.result_combo = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        layout.addWidget(label("Press the key or keys you want to use, then let go.",
                               "SectionTitle"))
        layout.addWidget(label("A key you don't otherwise use alone works best, such as "
                               "Right Ctrl, Right Alt, F9, or a mouse side button.", "Muted",
                               wrap=True))
        self.preview = label("Waiting for keys…", "StatValue")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet(f"color: {theme.ACCENT}; font-size: 16pt; padding: 12px;")
        layout.addWidget(self.preview)
        cancel = button("Cancel", on_click=self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        layout.addLayout(row)
        self.listener = HotkeyListener((), self._from_thread, report_all_keys=True)

    def exec(self) -> int:
        self.ctx.dictation.paused = True
        try:
            HotkeyListener.check_access()
            self.listener.start()
        except HotkeyError as e:
            self.preview.setText(str(e))
            self.preview.setWordWrap(True)
            self.preview.setStyleSheet(f"color: {theme.DANGER}; font-size: 10pt;")
        try:
            return super().exec()
        finally:
            self.listener.stop()
            self.ctx.dictation.paused = False

    def _from_thread(self, event: str) -> None:
        self.ctx.bridge.call_soon(lambda: self._on_key(event))

    def _on_key(self, event: str) -> None:
        kind, _, name = event.partition(":")
        if name in _IGNORED_KEYS or kind not in ("key", "keyup"):
            return
        if kind == "key":
            if name == "KEY_ESC":
                self.reject()
                return
            self._down.add(name)
            if name not in self.keys:
                self.keys.append(name)
            self.preview.setText(pretty(parse_combo("+".join(self.keys))))
        else:
            self._down.discard(name)
            if self.keys and not self._down:
                self.result_combo = "+".join(self.keys)
                self.accept()


class SettingsPage(Page):
    def __init__(self, ctx: Context):
        super().__init__("Settings")
        self.ctx = ctx

        shortcut = Card("Shortcut")
        row = QHBoxLayout()
        self.combo_label = label("", "SectionTitle")
        self.combo_label.setStyleSheet(f"color: {theme.ACCENT};")
        row.addWidget(label("Dictation key:"))
        row.addWidget(self.combo_label)
        row.addStretch(1)
        row.addWidget(button("Change…", icon="keyboard", on_click=self._change_shortcut))
        shortcut.body.addLayout(row)
        self.mode = Segmented([("hold", "Hold to talk"), ("toggle", "Press to start / stop")])
        self.mode.changed.connect(lambda m: self._set(lambda c: setattr(c.hotkey, "mode", m)))
        shortcut.body.addWidget(self.mode)
        self.hotkey_error = label("", wrap=True)
        self.hotkey_error.setStyleSheet(f"color: {theme.WARNING};")
        shortcut.body.addWidget(self.hotkey_error)
        toggle_cmd = f"{_hark_command()} toggle"
        tip = QHBoxLayout()
        tip.addWidget(label("Prefer your desktop's own shortcut settings? Bind this command "
                            "(press once to start, again to stop):", "Faint", wrap=True), 1)
        tip.addWidget(button("Copy command", icon="copy", on_click=lambda: QGuiApplication
                             .clipboard().setText(toggle_cmd)))
        shortcut.body.addLayout(tip)
        self.content.addWidget(shortcut)

        typing = Card("Typing")
        self.paste = QComboBox()
        for key, text in PASTE_OPTIONS:
            self.paste.addItem(text, key)
        self.paste.activated.connect(lambda i: self._set(
            lambda c: setattr(c.insert, "paste_chord", self.paste.itemData(i))))
        typing.body.addWidget(setting_row("Paste with", "How Hark inserts the text.", self.paste))
        self.space = Toggle(on_change=lambda v: self._set(
            lambda c: setattr(c.insert, "trailing_space", v)))
        typing.body.addWidget(setting_row("Add a space after", "So dictations in a row don't "
                                          "run together.", self.space))
        self.restore = Toggle(on_change=lambda v: self._set(
            lambda c: setattr(c.insert, "restore_clipboard", v)))
        typing.body.addWidget(setting_row("Restore clipboard", "Put back what you had copied "
                                          "after pasting.", self.restore))
        self.content.addWidget(typing)

        feedback = Card("Feedback & privacy")
        self.sounds = Toggle(on_change=lambda v: self._set(lambda c: setattr(c.ui, "sounds", v)))
        feedback.body.addWidget(setting_row("Sounds", "A short tone when recording starts and "
                                            "stops.", self.sounds))
        self.overlay = Toggle(on_change=lambda v: self._set(
            lambda c: setattr(c.ui, "overlay", v)))
        feedback.body.addWidget(setting_row("Recording capsule", "The small indicator at the "
                                            "bottom of the screen.", self.overlay))
        self.history = Toggle(on_change=lambda v: self._set(
            lambda c: setattr(c, "save_history", v)))
        feedback.body.addWidget(setting_row("Keep history", "Save dictations on this computer "
                                            "for the History page.", self.history))
        self.content.addWidget(feedback)

        system = Card("System")
        self.autostart = Toggle(on_change=desktop.set_autostart)
        system.body.addWidget(setting_row("Start at login", "Run Hark in the background when "
                                          "you log in.", self.autostart))
        self.launcher_btn = button("Add", on_click=self._add_launcher)
        system.body.addWidget(setting_row("App menu entry", "Show Hark in your applications "
                                          "menu.", self.launcher_btn))
        self.content.addWidget(system)

        check = Card("System check")
        self.checks = QVBoxLayout()
        self.checks.setSpacing(6)
        check.body.addLayout(self.checks)
        check.body.addWidget(button("Run again", on_click=self._run_checks),
                             alignment=Qt.AlignmentFlag.AlignLeft)
        self.content.addWidget(check)
        self.content.addStretch(1)
        self._checked = False

    def refresh(self) -> None:
        cfg = self.ctx.cfg
        self.combo_label.setText(pretty(self.ctx.dictation.combo))
        self.mode.select(cfg.hotkey.mode)
        error = self.ctx.daemon.hotkey_error
        self.hotkey_error.setText(f"The key can't be read: {error}" if error else "")
        self.hotkey_error.setVisible(bool(error))
        self.paste.setCurrentIndex(max(0, self.paste.findData(cfg.insert.paste_chord)))
        self.space.set_silently(cfg.insert.trailing_space)
        self.restore.set_silently(cfg.insert.restore_clipboard)
        self.sounds.set_silently(cfg.ui.sounds)
        self.overlay.set_silently(cfg.ui.overlay)
        self.history.set_silently(cfg.save_history)
        self.autostart.set_silently(desktop.autostart_enabled())
        installed = desktop.launcher_file().is_file()
        self.launcher_btn.setText("Added" if installed else "Add")
        self.launcher_btn.setEnabled(not installed)
        if not self._checked:
            self._run_checks()

    def _set(self, change) -> None:
        error = self.ctx.update_settings(change)
        self.hotkey_error.setText(error or "")
        self.hotkey_error.setVisible(bool(error))

    def _change_shortcut(self) -> None:
        dialog = ShortcutDialog(self, self.ctx)
        if dialog.exec() and dialog.result_combo:
            self._set(lambda c: setattr(c.hotkey, "combo", dialog.result_combo))
            self.refresh()

    def _add_launcher(self) -> None:
        desktop.install_launcher()
        self.refresh()

    def _run_checks(self) -> None:
        self._checked = True
        clear_layout(self.checks)
        self.checks.addWidget(label("Checking…", "Muted"))

        def done(results: list[doctor.Check]) -> None:
            clear_layout(self.checks)
            for c in results:
                row = QHBoxLayout()
                dot = label("●")
                dot.setStyleSheet(f"color: {_STATUS_COLORS[c.status]};")
                row.addWidget(dot)
                name = label(c.name)
                name.setFixedWidth(150)
                row.addWidget(name)
                text = c.detail + (f"\n→ {c.fix.splitlines()[0]}" if c.fix else "")
                row.addWidget(label(text, "Faint", wrap=True), 1)
                self.checks.addLayout(row)

        self.ctx.run_async(doctor.run_checks, done)


def _hark_command() -> str:
    import shutil
    import sys
    from pathlib import Path

    local = Path(sys.executable).with_name("hark")
    return str(local) if local.exists() else (shutil.which("hark") or "hark")
