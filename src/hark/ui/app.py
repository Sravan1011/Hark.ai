"""`hark app`: the dictation service plus the window, capsule and tray, in one process."""

from __future__ import annotations

import os
import signal
import sys
import time

from .. import config as config_mod
from .. import ipc


def _log(message: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}", flush=True)


def _pick_platform() -> None:
    # Under XWayland the capsule can be positioned and kept from taking focus; native
    # Wayland lets the compositor place windows. Respect an explicit user choice.
    if "QT_QPA_PLATFORM" not in os.environ and os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb;wayland"


def run(hidden: bool = False) -> int:
    _pick_platform()
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QAction, QIcon
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

    from ..daemon import Daemon
    from . import icons, theme
    from .capsule import Capsule
    from .context import Bridge, Context
    from .window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Hark")
    app.setDesktopFileName("hark")
    app.setQuitOnLastWindowClosed(False)

    bridge = Bridge()
    daemon = Daemon(config_mod.load(), log=_log,
                    on_event=lambda kind, data: bridge.event.emit(kind, data),
                    on_result=lambda _result, entry: bridge.result.emit(entry),
                    on_show=bridge.show_window.emit)
    try:
        daemon.start(on_ready=lambda _d, seconds: (
            _log(f"Ready: {daemon.cfg.stt.model} loaded in {seconds:.1f}s"),
            bridge.loaded.emit(seconds)))
    except ipc.AlreadyRunning:
        ipc.request("show")
        return 0
    ctx = Context(daemon, bridge)

    capsule = Capsule()
    capsule.enabled = daemon.cfg.ui.overlay
    bridge.event.connect(capsule.on_event)
    bridge.result.connect(lambda entry: capsule.flash(
        "✓ Added to note" if entry.get("delivered") == "added to note" else "✓ Inserted"))
    bridge.settings_changed.connect(lambda: setattr(capsule, "enabled", ctx.cfg.ui.overlay))

    tray = None
    first_close = [True]

    def closed() -> None:
        if first_close[0]:
            first_close[0] = False
            message = "Hark keeps running. Quit it from the tray or with: hark quit"
            if tray:
                tray.showMessage("Hark", message, QSystemTrayIcon.MessageIcon.Information, 4000)
            else:
                capsule.flash("Still running in the background", theme.MUTED, 2.5)

    def quit_now() -> None:
        # exit(), not quit(): in Qt 6 quit() first asks windows to close, and the main
        # window refuses (closing it only hides it), which would cancel the quit.
        app.exit(0)

    window = MainWindow(ctx, on_close=closed)
    bridge.show_window.connect(window.bring_to_front)

    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = QSystemTrayIcon(QIcon(icons.pixmap("mic", theme.ACCENT, 32)))
        tray.setToolTip("Hark")
        menu = QMenu()
        open_action = QAction("Open Hark", menu, triggered=window.bring_to_front)
        dictate_action = QAction("Start dictating", menu, triggered=daemon.dictation.toggle)
        menu.addAction(open_action)
        menu.addAction(dictate_action)
        menu.addSeparator()
        menu.addAction(QAction("Quit", menu, triggered=quit_now))
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: window.bring_to_front()
                               if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        bridge.event.connect(lambda kind, data: kind == "state" and dictate_action.setText(
            "Stop dictating" if data["state"] == "recording" else "Start dictating"))
        tray.show()

    if not hidden or tray is None:
        window.show()

    # Ctrl+C, SIGTERM and `hark quit` only set a flag; this timer acts on it. Polling (rather
    # than a signal) also covers a quit that arrives before the event loop starts, and gives
    # Python a chance to run its signal handlers while Qt's loop is running.
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: daemon.request_quit())
    heartbeat = QTimer(interval=250)
    heartbeat.timeout.connect(lambda: daemon.quit_requested and quit_now())
    heartbeat.start()

    app.aboutToQuit.connect(daemon.stop)
    code = app.exec()
    daemon.exit_if_loading(code)
    return code
