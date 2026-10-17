"""Smoke tests: every page builds and refreshes off-screen with a fake daemon."""

import os
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication

from hark import config as c
from hark import history, notes
from hark.hotkey import parse_combo


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(app, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from hark.ui import context

    class FakeDictation:
        combo, engine, paused, recording, state = parse_combo("rightctrl"), object(), False, \
            False, "idle"

        def __init__(self):
            self.captures = []

        def begin(self, capture=None):
            self.captures.append(capture)

        def finish(self):
            pass

    fake = types.SimpleNamespace(cfg=c.Config(), dictation=FakeDictation(), hotkey_error="",
                                 model_error="")
    fake.reload = lambda: setattr(fake, "cfg", c.load())
    return context.Context(fake, context.Bridge())


def test_qt_calls_keep_none_alive(app):
    """PySide6 6.12.0 + Python 3.11 lost a reference to None on every void call, which
    aborted the app after a few thousand paint calls."""
    import sys

    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter

    image = QImage(20, 20, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    before = sys.getrefcount(None)
    for _ in range(500):
        painter.setBrush(QColor("#fff"))
        painter.drawRoundedRect(QRectF(1, 1, 4, 10), 2, 2)
    leaked = before - sys.getrefcount(None)
    painter.end()
    assert leaked < 50, f"Qt calls dropped {leaked} references to None: use PySide6 < 6.12"


def test_every_page_renders(ctx, app):
    from hark.ui.window import NAV, MainWindow

    history.append({"text": "Hello world.", "raw": "hello world", "audio_s": 2.0})
    window = MainWindow(ctx)
    window.show()
    for key, _title, _cls in NAV:
        window.open(key)
        app.processEvents()
        assert window.stack.currentWidget() is window.pages[key]
    window.close()
    assert window.isHidden()  # closing hides; dictation keeps running


def test_settings_changes_are_saved_and_applied(ctx, app):
    from hark.ui.pages.dictionary import DictionaryPage
    from hark.ui.pages.style import StylePage

    page = DictionaryPage(ctx)
    page.heard.setText("hark ai")
    page.write.setText("Hark.ai")
    page._add()
    assert ctx.cfg.vocabulary == [{"from": "hark ai", "to": "Hark.ai"}]
    page._remove("HARK AI")
    assert c.load().vocabulary == []

    style = StylePage(ctx)
    style._pick_style("email")
    assert ctx.cfg.llm.style == "email"


def test_note_dictation_inserts_at_cursor(ctx, app):
    from hark.ui.pages.notes import NotesPage

    page = NotesPage(ctx)
    page.new_note()
    page.body.setPlainText("Buy")
    cursor = page.body.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    page.body.setTextCursor(cursor)
    page._toggle_dictation()
    capture = ctx.dictation.captures[-1]
    capture("milk and eggs")  # called from the worker thread in real use
    app.processEvents()
    assert page.body.toPlainText() == "Buy milk and eggs"
    page._save()
    assert notes.load()[0].body == "Buy milk and eggs"


def test_capsule_follows_dictation_state(app):
    from hark.ui.capsule import Capsule

    capsule = Capsule()
    capsule.on_event("state", {"state": "recording"})
    assert capsule.mode == "recording" and capsule.isVisible()
    capsule.on_event("level", {"rms": 0.05})
    assert capsule.levels[-1] > 0
    capsule.on_event("state", {"state": "transcribing"})
    assert capsule.mode == "transcribing"
    capsule.on_event("state", {"state": "idle"})
    assert not capsule.isVisible()
    capsule.enabled = False
    capsule.on_event("state", {"state": "recording"})
    assert not capsule.isVisible()
