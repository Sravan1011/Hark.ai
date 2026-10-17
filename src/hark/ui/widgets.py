"""Reusable building blocks: pages, cards, toggle switches, stat tiles, segmented buttons."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme


def label(text: str = "", name: str = "", *, wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def button(text: str = "", *, name: str = "", icon: str = "", icon_color: str = theme.TEXT,
           on_click: Callable[[], None] | None = None, tooltip: str = "") -> QPushButton:
    widget = QPushButton(text)
    if name:
        widget.setObjectName(name)
    if icon:
        widget.setIcon(icons.icon(icon, icon_color))
        widget.setIconSize(QSize(16, 16))
    if on_click:
        widget.clicked.connect(lambda _checked=False: on_click())
    if tooltip:
        widget.setToolTip(tooltip)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


class Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", *, spacing: int = 12):
        super().__init__()
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 18, 20, 18)
        self.body.setSpacing(spacing)
        if title:
            self.body.addWidget(label(title, "SectionTitle"))
        if subtitle:
            self.body.addWidget(label(subtitle, "Muted", wrap=True))


class Page(QWidget):
    """Scrollable page with a title. Subclasses fill self.content and implement refresh(),
    which runs every time the page is shown."""

    def __init__(self, title: str, subtitle: str = "", *, scroll: bool = True):
        super().__init__()
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        inner.setObjectName("Page")
        self.content = QVBoxLayout(inner)
        self.content.setContentsMargins(36, 30, 36, 30)
        self.content.setSpacing(16)
        header = QVBoxLayout()
        header.setSpacing(4)
        header.addWidget(label(title, "PageTitle"))
        self.subtitle = label(subtitle, "PageSubtitle", wrap=True)
        self.subtitle.setVisible(bool(subtitle))
        header.addWidget(self.subtitle)
        self.content.addLayout(header)
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setWidget(inner)
            outer.addWidget(area)
        else:
            outer.addWidget(inner)

    def refresh(self) -> None:
        pass

    def showEvent(self, event) -> None:
        self.refresh()
        super().showEvent(event)


class Toggle(QAbstractButton):
    """An animated on/off switch."""

    def __init__(self, checked: bool = False, on_change: Callable[[bool], None] | None = None):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(42, 24)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)
        if on_change:
            self.toggled.connect(on_change)

    def set_silently(self, checked: bool) -> None:
        self.blockSignals(True)
        self.setChecked(checked)
        self._pos = 1.0 if checked else 0.0
        self.blockSignals(False)
        self.update()

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, value: float) -> None:
        self._pos = value
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def sizeHint(self) -> QSize:
        return QSize(42, 24)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        off, on = QColor(theme.BORDER), QColor(theme.ACCENT)
        track = QColor(
            int(off.red() + (on.red() - off.red()) * self._pos),
            int(off.green() + (on.green() - off.green()) * self._pos),
            int(off.blue() + (on.blue() - off.blue()) * self._pos))
        if not self.isEnabled():
            track.setAlpha(110)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, 42, 24), 12, 12)
        p.setBrush(QColor("white"))
        p.drawEllipse(QRectF(3 + 18 * self._pos, 3, 18, 18))


def setting_row(title: str, description: str, control: QWidget) -> QWidget:
    """Title and description on the left, a control on the right."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 2, 0, 2)
    text = QVBoxLayout()
    text.setSpacing(2)
    text.addWidget(label(title))
    if description:
        text.addWidget(label(description, "Faint", wrap=True))
    layout.addLayout(text, 1)
    layout.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
    return row


class StatTile(QFrame):
    def __init__(self, caption: str, accent: str = theme.ACCENT):
        super().__init__()
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(2)
        self.value = label("–", "StatValue")
        self.value.setStyleSheet(f"color: {accent};")
        layout.addWidget(self.value)
        layout.addWidget(label(caption, "StatLabel"))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class Segmented(QWidget):
    """A row of mutually exclusive buttons; emits the selected key."""

    changed = Signal(str)

    def __init__(self, options: Sequence[tuple[str, str]], selected: str = ""):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._group = QButtonGroup(self)
        self._buttons: dict[str, QPushButton] = {}
        for key, text in options:
            b = button(text, name="Segment")
            b.setCheckable(True)
            self._group.addButton(b)
            self._buttons[key] = b
            b.clicked.connect(lambda _c=False, k=key: self.changed.emit(k))
            layout.addWidget(b)
        layout.addStretch(1)
        self.select(selected)

    def select(self, key: str) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())
