"""Notes: dictate straight into Hark's own notepad, with an optional AI title and summary."""

from __future__ import annotations

import datetime as dt
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ... import notes as notes_store
from ...pipeline import keep_alive
from .. import theme
from ..context import Context
from ..widgets import button, label

AI_LABEL = "Title && summary"  # "&&" shows a literal "&" (a single one marks a shortcut key)


class NotesPage(QWidget):
    def __init__(self, ctx: Context):
        super().__init__()
        self.setObjectName("Page")
        self.ctx = ctx
        self.notes: list[notes_store.Note] = notes_store.load()
        self.current: notes_store.Note | None = None
        self._dictating = False
        self._save_timer = QTimer(self, singleShot=True, interval=500, timeout=self._save)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # -- note list --------------------------------------------------------------------
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(270)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(16, 30, 12, 16)
        side_layout.setSpacing(12)
        side_layout.addWidget(label("Notes", "PageTitle"))
        side_layout.addWidget(button("New note", name="Primary", icon="plus",
                                     icon_color="white", on_click=self.new_note))
        self.list = QListWidget()
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.currentRowChanged.connect(self._select)
        side_layout.addWidget(self.list, 1)
        root.addWidget(side)

        # -- editor -----------------------------------------------------------------------
        editor = QWidget()
        editor.setObjectName("Page")
        layout = QVBoxLayout(editor)
        layout.setContentsMargins(36, 26, 36, 24)
        layout.setSpacing(10)
        tools = QHBoxLayout()
        self.dictate_btn = button("Dictate", name="Primary", icon="mic", icon_color="white",
                                  on_click=self._toggle_dictation,
                                  tooltip="Record and insert at the cursor")
        self.ai_btn = button(AI_LABEL, icon="sparkle", icon_color=theme.ACCENT,
                             on_click=self._summarize,
                             tooltip="Uses your local Ollama model")
        self.delete_btn = button(name="Icon", icon="trash", icon_color=theme.MUTED,
                                 tooltip="Delete note", on_click=self._delete)
        tools.addWidget(self.dictate_btn)
        tools.addWidget(self.ai_btn)
        tools.addStretch(1)
        self.meta = label("", "Faint")
        tools.addWidget(self.meta)
        tools.addWidget(self.delete_btn)
        layout.addLayout(tools)

        self.title = QLineEdit()
        self.title.setObjectName("NoteTitle")
        self.title.setPlaceholderText("Untitled")
        self.title.textEdited.connect(self._edited)
        layout.addWidget(self.title)
        self.summary = label("", wrap=True)
        self.summary.setStyleSheet(f"background: {theme.ACCENT_SOFT}; border-radius: 10px;"
                                   f" padding: 10px 12px; color: {theme.TEXT};")
        layout.addWidget(self.summary)
        self.body = QPlainTextEdit()
        self.body.setObjectName("NoteBody")
        self.body.setPlaceholderText("Start typing, click Dictate, or hold your Hark key and "
                                     "speak…")
        self.body.textChanged.connect(self._edited)
        layout.addWidget(self.body, 1)
        root.addWidget(editor, 1)

        ctx.bridge.event.connect(self._on_event)
        self._reload_list()

    # -- list ---------------------------------------------------------------------------

    def _reload_list(self, select_id: str | None = None) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for note in self.notes:
            item = QListWidgetItem(f"{note.display_title}\n"
                                   f"{dt.datetime.fromtimestamp(note.updated):%d %b, %H:%M}")
            item.setData(Qt.ItemDataRole.UserRole, note.id)
            self.list.addItem(item)
        self.list.blockSignals(False)
        ids = [n.id for n in self.notes]
        target = select_id or (self.current.id if self.current else None)
        row = ids.index(target) if target in ids else (0 if ids else -1)
        self.list.setCurrentRow(row)
        if row == -1:
            self._select(-1)

    def _select(self, row: int) -> None:
        self.current = self.notes[row] if 0 <= row < len(self.notes) else None
        note = self.current
        for widget in (self.title, self.body, self.dictate_btn, self.ai_btn, self.delete_btn):
            widget.setEnabled(note is not None)
        self.title.blockSignals(True)
        self.body.blockSignals(True)
        self.title.setText(note.title if note else "")
        self.body.setPlainText(note.body if note else "")
        self.title.blockSignals(False)
        self.body.blockSignals(False)
        self.summary.setText(note.summary if note else "")
        self.summary.setVisible(bool(note and note.summary))
        self.meta.setText(f"Edited {dt.datetime.fromtimestamp(note.updated):%d %b %H:%M}"
                          if note else "")
        if note is None:
            self.body.setPlaceholderText("Create a note to start.")

    def new_note(self) -> None:
        note = notes_store.Note()
        self.notes.insert(0, note)
        self._save()
        self._reload_list(select_id=note.id)
        self.body.setFocus()

    def _delete(self) -> None:
        if not self.current:
            return
        answer = QMessageBox.question(self, "Delete note",
                                      f"Delete “{self.current.display_title}”?")
        if answer == QMessageBox.StandardButton.Yes:
            self.notes.remove(self.current)
            self.current = None
            self._save()
            self._reload_list()

    # -- editing ------------------------------------------------------------------------

    def _edited(self, *_args) -> None:
        if not self.current:
            return
        self.current.title = self.title.text()
        self.current.body = self.body.toPlainText()
        self.current.updated = time.time()
        item = self.list.currentItem()
        if item:
            item.setText(f"{self.current.display_title}\n"
                         f"{dt.datetime.fromtimestamp(self.current.updated):%d %b, %H:%M}")
        self._save_timer.start()

    def _save(self) -> None:
        notes_store.save_all(self.notes)

    def _insert(self, text: str) -> None:
        cursor = self.body.textCursor()
        before = self.body.toPlainText()[:cursor.position()]
        if before and not before[-1].isspace():
            text = " " + text
        cursor.insertText(text)
        self.body.setTextCursor(cursor)

    # -- dictation ----------------------------------------------------------------------

    def _toggle_dictation(self) -> None:
        dictation = self.ctx.dictation
        if dictation.recording:
            dictation.finish()
            return
        note_id = self.current.id if self.current else None

        def captured(text: str) -> None:  # runs on the dictation worker thread
            self.ctx.bridge.call_soon(lambda: self._captured(note_id, text))

        self._dictating = True
        dictation.begin(capture=captured)

    def _captured(self, note_id: str | None, text: str) -> None:
        if self.current and self.current.id == note_id:
            self._insert(text)
        else:  # the user switched notes meanwhile: append to the original note
            for note in self.notes:
                if note.id == note_id:
                    note.body = (note.body.rstrip() + " " + text).strip()
                    self._save()

    def _on_event(self, kind: str, data: dict) -> None:
        if kind != "state":
            return
        recording = data["state"] == "recording"
        if not recording and data["state"] == "idle":
            self._dictating = False
        self.dictate_btn.setText("Stop" if recording and self._dictating else "Dictate")

    # -- AI -----------------------------------------------------------------------------

    def _summarize(self) -> None:
        from ...llm.notes_ai import title_and_summary
        from ...llm.ollama import OllamaClient

        note = self.current
        if not note or not note.body.strip():
            return
        cfg = self.ctx.cfg
        self.ai_btn.setEnabled(False)
        self.ai_btn.setText("Thinking…")

        def done(result: tuple[str, str]) -> None:
            note.title, note.summary = result
            note.updated = time.time()
            self._save()
            self._finish_ai()
            self._reload_list(select_id=note.id)

        def failed(message: str) -> None:
            self._finish_ai()
            QMessageBox.warning(self, "Title & summary",
                                f"{message}\n\nThis uses Ollama with “{cfg.llm.model}” "
                                "(set on the Style page).")

        self.ctx.run_async(
            lambda: title_and_summary(note.body, OllamaClient(cfg.llm.url), model=cfg.llm.model,
                                      keep_alive=keep_alive(cfg)), done, failed)

    def _finish_ai(self) -> None:
        self.ai_btn.setEnabled(self.current is not None)
        self.ai_btn.setText(AI_LABEL)
