"""The floating capsule shown at the bottom of the screen while dictating.

It must never take keyboard focus (the text is pasted into the app below it), so it's
a frameless tool-tip window that ignores the mouse. Under XWayland it can be placed
precisely; on native Wayland the compositor decides where it goes.
"""

from __future__ import annotations

import math
import time
from collections import deque

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from . import theme

_W, _H = 196, 46
_BARS = 14


class Capsule(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(_W, _H)
        self.enabled = True
        self.mode = "hidden"  # recording | transcribing | message
        self.message = ""
        self.message_color = theme.TEXT
        self.levels: deque[float] = deque([0.0] * _BARS, maxlen=_BARS)
        self.started = 0.0
        self._tick = QTimer(self, interval=40, timeout=self.update)
        self._hide_timer = QTimer(self, singleShot=True, timeout=self._hide)

    # -- driven by dictation events -------------------------------------------------

    def on_event(self, kind: str, data: dict) -> None:
        if kind == "state":
            state = data["state"]
            if state == "recording":
                self.levels.extend([0.0] * _BARS)
                self.started = time.monotonic()
                self._show("recording")
            elif state == "transcribing":
                self._show("transcribing")
            elif self.mode in ("recording", "transcribing"):
                self._hide()
        elif kind == "level":
            # Speech RMS is ~0.01-0.2; a square-root curve makes quiet speech visible.
            self.levels.append(min(1.0, math.sqrt(data["rms"] * 12)))
        elif kind in ("notice", "error"):
            color = theme.DANGER if kind == "error" else theme.MUTED
            self.flash(data["message"], color, 2.5 if kind == "error" else 1.4)

    def flash(self, message: str, color: str = theme.SUCCESS, seconds: float = 1.0) -> None:
        self.message, self.message_color = message, color
        self._show("message")
        self._hide_timer.start(int(seconds * 1000))

    def _show(self, mode: str) -> None:
        self.mode = mode
        self._hide_timer.stop()
        if not self.enabled:
            return
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - _W // 2, screen.bottom() - _H - 60)
        self._tick.start()
        self.show()
        self.update()

    def _hide(self) -> None:
        self.mode = "hidden"
        self._tick.stop()
        self.hide()

    # -- drawing ----------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        shape = QPainterPath()
        shape.addRoundedRect(QRectF(1, 1, _W - 2, _H - 2), (_H - 2) / 2, (_H - 2) / 2)
        p.fillPath(shape, QColor(18, 19, 24, 238))
        p.setPen(QColor(255, 255, 255, 28))
        p.drawPath(shape)

        font = QFont(p.font())
        font.setPointSizeF(9.5)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)

        if self.mode == "recording":
            pulse = 0.55 + 0.45 * math.sin(time.monotonic() * 5)
            dot = QColor(theme.RECORDING)
            dot.setAlphaF(pulse)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(dot)
            p.drawEllipse(QRectF(18, _H / 2 - 5, 10, 10))
            p.setBrush(QColor(theme.TEXT))
            for i, level in enumerate(self.levels):
                height = 4 + level * 22
                p.drawRoundedRect(QRectF(40 + i * 7, (_H - height) / 2, 4, height), 2, 2)
            elapsed = int(time.monotonic() - self.started)
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(140, 0, 44, _H), Qt.AlignmentFlag.AlignCenter,
                       f"{elapsed // 60}:{elapsed % 60:02d}")
        elif self.mode == "transcribing":
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(3):
                phase = time.monotonic() * 6 - i * 0.8
                color = QColor(theme.ACCENT)
                color.setAlphaF(0.35 + 0.65 * (0.5 + 0.5 * math.sin(phase)))
                p.setBrush(color)
                p.drawEllipse(QRectF(24 + i * 13, _H / 2 - 4, 8, 8))
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(70, 0, _W - 84, _H), Qt.AlignmentFlag.AlignVCenter, "Transcribing")
        elif self.mode == "message":
            p.setPen(QColor(self.message_color))
            metrics = p.fontMetrics()
            text = metrics.elidedText(self.message, Qt.TextElideMode.ElideRight, _W - 32)
            p.drawText(QRectF(0, 0, _W, _H), Qt.AlignmentFlag.AlignCenter, text)
