"""Home: dictation stats and the most recent dictations."""

from __future__ import annotations

import datetime as dt

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QVBoxLayout

from ... import history, stats
from ...hotkey import pretty
from .. import theme
from ..context import Context
from ..widgets import Card, Page, StatTile, button, clear_layout, label

RECENT = 6


def when(ts: str) -> str:
    try:
        moment = dt.datetime.fromisoformat(ts)
    except ValueError:
        return ts
    today = dt.date.today()
    if moment.date() == today:
        return moment.strftime("%H:%M")
    if moment.date() == today - dt.timedelta(days=1):
        return "Yesterday " + moment.strftime("%H:%M")
    return moment.strftime("%d %b %H:%M")


def entry_row(entry: dict, *, on_delete=None, show_raw: bool = False) -> QFrame:
    row = QFrame()
    row.setObjectName("Row")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(4, 10, 4, 10)
    layout.setSpacing(14)
    stamp = label(when(entry.get("ts", "")), "Faint")
    stamp.setFixedWidth(104)
    layout.addWidget(stamp)
    text_col = QVBoxLayout()
    text_col.setSpacing(3)
    text = entry.get("raw" if show_raw else "text", "")
    body = label(text, wrap=True)
    body.setTextInteractionFlags(body.textInteractionFlags().TextSelectableByMouse)
    text_col.addWidget(body)
    if show_raw:
        details = [entry.get("model", ""), f"{entry.get('audio_s', 0):.1f}s audio"]
        if entry.get("llm", "off") != "off":
            details.append(f"AI: {entry['llm']}")
        text_col.addWidget(label(" · ".join(d for d in details if d), "Faint"))
    layout.addLayout(text_col, 1)
    layout.addWidget(button(name="Icon", icon="copy", icon_color=theme.MUTED, tooltip="Copy",
                            on_click=lambda: QGuiApplication.clipboard().setText(text)))
    if on_delete:
        layout.addWidget(button(name="Icon", icon="trash", icon_color=theme.MUTED,
                                tooltip="Delete", on_click=lambda: on_delete(entry)))
    return row


class HomePage(Page):
    def __init__(self, ctx: Context):
        super().__init__("Welcome back", "")
        self.ctx = ctx
        tiles = QGridLayout()
        tiles.setSpacing(14)
        self.words = StatTile("words this week")
        self.wpm = StatTile("words per minute", theme.SUCCESS)
        self.streak = StatTile("day streak", theme.WARNING)
        self.total = StatTile("dictations", theme.TEXT)
        for i, tile in enumerate((self.words, self.wpm, self.streak, self.total)):
            tiles.addWidget(tile, 0, i)
        self.content.addLayout(tiles)

        recent = Card("Recent dictations")
        self.list = QVBoxLayout()
        self.list.setSpacing(0)
        recent.body.addLayout(self.list)
        self.content.addWidget(recent)
        self.content.addStretch(1)
        ctx.bridge.result.connect(lambda _entry: self.refresh())

    def refresh(self) -> None:
        cfg = self.ctx.cfg
        key = pretty(self.ctx.dictation.combo)
        how = (f"Hold <b>{key}</b> in any app, speak, and release."
               if cfg.hotkey.mode == "hold" else
               f"Press <b>{key}</b> in any app, speak, and press it again.")
        self.subtitle.setText(how)
        self.subtitle.show()

        entries = history.read()
        s = stats.compute(entries)
        self.words.value.setText(f"{s.words_this_week:,}")
        self.wpm.value.setText(str(s.avg_wpm) if s.avg_wpm else "–")
        self.streak.value.setText(str(s.streak_days))
        self.total.value.setText(f"{s.total_dictations:,}")

        clear_layout(self.list)
        if not entries:
            message = ("Your dictations will appear here. Click into any text box, " + how[0].lower()
                       + how[1:]) if cfg.save_history else (
                "History is turned off in Settings, so dictations aren't kept.")
            self.list.addWidget(label(message, "Muted", wrap=True))
        for entry in reversed(entries[-RECENT:]):
            self.list.addWidget(entry_row(entry))
