"""Main window: sidebar navigation and the pages."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme
from .context import Context
from .pages.dictionary import DictionaryPage
from .pages.history import HistoryPage
from .pages.home import HomePage
from .pages.models import ModelsPage
from .pages.notes import NotesPage
from .pages.settings import SettingsPage
from .pages.style import StylePage
from .widgets import label

NAV = [("home", "Home", HomePage), ("history", "History", HistoryPage),
       ("notes", "Notes", NotesPage), ("dictionary", "Dictionary", DictionaryPage),
       ("style", "Style", StylePage), ("models", "Models", ModelsPage),
       ("settings", "Settings", SettingsPage)]

_STATUS = {"loading": ("Loading speech model…", theme.WARNING),
           "idle": ("Ready", theme.SUCCESS),
           "recording": ("Listening…", theme.RECORDING),
           "transcribing": ("Transcribing…", theme.ACCENT),
           "error": ("Model unavailable: open Models", theme.DANGER)}


class MainWindow(QMainWindow):
    def __init__(self, ctx: Context, *, on_close=None):
        super().__init__()
        self.ctx = ctx
        self.on_close = on_close
        self.setWindowTitle("Hark")
        self.setWindowIcon(QIcon(icons.pixmap("mic", theme.ACCENT, 64)))
        self.resize(1040, 720)
        self.setMinimumSize(860, 560)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(212)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 22, 14, 18)
        side.setSpacing(4)
        brand = QHBoxLayout()
        brand.setContentsMargins(8, 0, 0, 18)
        mic = label()
        mic.setPixmap(icons.pixmap("mic", theme.ACCENT, 22))
        brand.addWidget(mic)
        brand.addWidget(label("Hark", "Brand"))
        brand.addStretch(1)
        side.addLayout(brand)

        self.stack = QStackedWidget()
        self.pages: dict[str, QWidget] = {}
        self.nav: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        for key, title, page_class in NAV:
            page = page_class(ctx)
            self.pages[key] = page
            self.stack.addWidget(page)
            nav = QPushButton(f"  {title}")
            nav.setObjectName("NavButton")
            nav.setCheckable(True)
            nav.setIcon(icons.icon(key, theme.MUTED))
            nav.setIconSize(QSize(18, 18))
            nav.setCursor(Qt.CursorShape.PointingHandCursor)
            nav.clicked.connect(lambda _c=False, k=key: self.open(k))
            group.addButton(nav)
            self.nav[key] = nav
            side.addWidget(nav)
        side.addStretch(1)

        status = QHBoxLayout()
        status.setContentsMargins(10, 0, 0, 0)
        self.status_dot = label("●")
        self.status_text = label("", "Faint")
        status.addWidget(self.status_dot)
        status.addWidget(self.status_text, 1)
        side.addLayout(status)

        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.setStyleSheet(theme.STYLESHEET)

        ctx.bridge.event.connect(self._on_event)
        ctx.bridge.loaded.connect(lambda _s: self.set_status("idle"))
        self.set_status("idle" if ctx.dictation.engine else
                        "error" if ctx.daemon.model_error else "loading")
        self.open("home")

    def open(self, key: str) -> None:
        self.nav[key].setChecked(True)
        for name, nav in self.nav.items():
            nav.setIcon(icons.icon(name, theme.TEXT if name == key else theme.MUTED))
        self.stack.setCurrentWidget(self.pages[key])

    def set_status(self, state: str) -> None:
        text, color = _STATUS.get(state, _STATUS["idle"])
        self.status_text.setText(text)
        self.status_dot.setStyleSheet(f"color: {color};")

    def _on_event(self, kind: str, data: dict) -> None:
        if kind == "state":
            self.set_status(data["state"])
        elif kind == "error" and not self.ctx.dictation.engine:
            self.set_status("error")

    def bring_to_front(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:
        # Closing the window keeps dictation running in the background.
        event.ignore()
        self.hide()
        if self.on_close:
            self.on_close()
