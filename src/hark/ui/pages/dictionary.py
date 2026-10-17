"""Dictionary: names and jargon (replacements and spelling hints)."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QVBoxLayout

from .. import theme
from ..context import Context
from ..widgets import Card, Page, button, clear_layout, label


class DictionaryPage(Page):
    def __init__(self, ctx: Context):
        super().__init__("Dictionary", "Teach Hark names and jargon. Leave “Write as” empty to "
                         "just fix the spelling of a word.")
        self.ctx = ctx
        add = Card("Add a word")
        row = QHBoxLayout()
        self.heard = QLineEdit()
        self.heard.setPlaceholderText("When I say…  e.g. hark ai")
        self.write = QLineEdit()
        self.write.setPlaceholderText("Write as…  e.g. Hark.ai")
        for field in (self.heard, self.write):
            field.returnPressed.connect(self._add)
            row.addWidget(field, 1)
        row.addWidget(button("Add", name="Primary", icon="plus", icon_color="white",
                             on_click=self._add))
        add.body.addLayout(row)
        self.error = label("", "Faint")
        self.error.setStyleSheet(f"color: {theme.DANGER};")
        self.error.hide()
        add.body.addWidget(self.error)
        self.content.addWidget(add)

        self.card = Card("Your words")
        self.list = QVBoxLayout()
        self.list.setSpacing(0)
        self.card.body.addLayout(self.list)
        self.content.addWidget(self.card)
        self.content.addStretch(1)

    def refresh(self) -> None:
        clear_layout(self.list)
        entries = self.ctx.cfg.vocabulary
        if not entries:
            self.list.addWidget(label("No words yet.", "Muted"))
        for entry in entries:
            row = QFrame()
            row.setObjectName("Row")
            layout = QHBoxLayout(row)
            layout.setContentsMargins(4, 8, 4, 8)
            if entry["from"] == entry["to"]:
                layout.addWidget(label(entry["to"]), 1)
                layout.addWidget(label("spelling", "Faint"))
            else:
                layout.addWidget(label(entry["from"], "Muted"), 1)
                layout.addWidget(label("→", "Faint"))
                layout.addWidget(label(entry["to"]), 1)
            layout.addWidget(button(name="Icon", icon="trash", icon_color=theme.MUTED,
                                    tooltip="Remove",
                                    on_click=lambda e=entry: self._remove(e["from"])))
            self.list.addWidget(row)

    def _add(self) -> None:
        heard, write = self.heard.text().strip(), self.write.text().strip()
        if not heard:
            self.heard.setFocus()
            return

        def change(cfg) -> None:
            cfg.vocabulary = [e for e in cfg.vocabulary if e["from"].lower() != heard.lower()]
            cfg.vocabulary.append({"from": heard, "to": write or heard})

        self._apply(change)
        self.heard.clear()
        self.write.clear()
        self.heard.setFocus()

    def _remove(self, heard: str) -> None:
        self._apply(lambda cfg: setattr(cfg, "vocabulary", [
            e for e in cfg.vocabulary if e["from"].lower() != heard.lower()]))

    def _apply(self, change) -> None:
        error = self.ctx.update_settings(change)
        self.error.setText(error or "")
        self.error.setVisible(bool(error))
        self.refresh()
