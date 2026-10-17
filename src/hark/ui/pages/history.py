"""History: search, copy and delete past dictations."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLineEdit, QMessageBox, QVBoxLayout

from ... import history
from .. import icons, theme
from ..context import Context
from ..widgets import Card, Page, button, clear_layout, label
from .home import entry_row

LIMIT = 200


class HistoryPage(Page):
    def __init__(self, ctx: Context):
        super().__init__("History", "Everything you've dictated, stored only on this computer.")
        self.ctx = ctx
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search dictations")
        self.search.addAction(icons.icon("search", theme.MUTED),
                              QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda _t: self.refresh())
        bar.addWidget(self.search, 1)
        self.show_raw = QCheckBox("Show original")
        self.show_raw.setToolTip("Show the text as heard, before cleanup")
        self.show_raw.toggled.connect(lambda _c: self.refresh())
        bar.addWidget(self.show_raw)
        bar.addWidget(button("Clear all", name="Danger", on_click=self._clear))
        self.content.addLayout(bar)

        card = Card()
        self.count = label("", "Faint")
        card.body.addWidget(self.count)
        self.list = QVBoxLayout()
        self.list.setSpacing(0)
        card.body.addLayout(self.list)
        self.content.addWidget(card)
        self.content.addStretch(1)
        ctx.bridge.result.connect(lambda _entry: self.isVisible() and self.refresh())

    def refresh(self) -> None:
        query = self.search.text().strip().lower()
        entries = [e for e in reversed(history.read())
                   if not query or query in e.get("text", "").lower()
                   or query in e.get("raw", "").lower()]
        clear_layout(self.list)
        shown = entries[:LIMIT]
        self.count.setText(f"{len(entries)} dictation{'s' * (len(entries) != 1)}"
                           + (f", showing the newest {LIMIT}" if len(entries) > LIMIT else ""))
        if not entries:
            self.list.addWidget(label("No matching dictations." if query else
                                      "No dictations yet.", "Muted"))
        for entry in shown:
            self.list.addWidget(entry_row(entry, on_delete=self._delete,
                                          show_raw=self.show_raw.isChecked()))

    def _delete(self, entry: dict) -> None:
        if entry.get("id"):
            history.delete(entry["id"])
        self.refresh()

    def _clear(self) -> None:
        answer = QMessageBox.question(self, "Clear history",
                                      "Delete all dictations from the history?")
        if answer == QMessageBox.StandardButton.Yes:
            history.clear()
            self.refresh()
