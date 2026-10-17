"""Style: cleanup rules, AI cleanup with Ollama, and a box to try it out."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPlainTextEdit

from ...llm.ollama import OllamaClient
from ...llm.polish import STYLES
from ...pipeline import process
from .. import theme
from ..context import Context
from ..widgets import Card, Page, Segmented, Toggle, button, label, setting_row

STYLE_LABELS = {"plain": "Plain", "email": "Email", "message": "Message", "notes": "Notes"}
STYLE_HELP = {
    "plain": "Fixes punctuation, grammar and self-corrections. Keeps your words.",
    "email": "Greeting and sign-off on their own lines, short paragraphs.",
    "message": "Short and casual, for chat apps.",
    "notes": "One idea per line, as bullet points.",
}
COMMANDS = ("“comma”, “question mark”, “full stop”, “new line”, “new paragraph”, "
            "“add a colon”, “scratch that”, “sorry, remove that”, “at the rate KV” → @KV")


class StylePage(Page):
    def __init__(self, ctx: Context):
        super().__init__("Style", "How Hark tidies up what you say before typing it.")
        self.ctx = ctx

        rules = Card("Cleanup rules", "Instant and offline, applied to every dictation.")
        self.fillers = Toggle(on_change=lambda v: self._set("remove_fillers", v))
        self.commands = Toggle(on_change=lambda v: self._set("voice_commands", v))
        rules.body.addWidget(setting_row("Remove filler words",
                                         "“um”, “uh”, repeated words like “I I think”.",
                                         self.fillers))
        rules.body.addWidget(setting_row("Voice commands", COMMANDS, self.commands))
        self.content.addWidget(rules)

        ai = Card("AI cleanup", "A local Ollama model fixes grammar and self-corrections "
                  "(“Tuesday, no wait, Wednesday” → “Wednesday”). Its edits are checked, "
                  "and your text is kept if it misbehaves. Adds a few seconds on CPU.")
        self.ai_on = Toggle(on_change=self._toggle_ai)
        ai.body.addWidget(setting_row("Use AI cleanup", "", self.ai_on))
        model_row = QHBoxLayout()
        self.model = QComboBox()
        self.model.setMinimumWidth(220)
        self.model.activated.connect(self._pick_model)
        model_row.addWidget(self.model)
        model_row.addWidget(button("Refresh", on_click=self._load_models))
        self.ollama_state = label("", "Faint")
        model_row.addWidget(self.ollama_state, 1)
        ai.body.addLayout(model_row)
        self.style = Segmented([(k, STYLE_LABELS[k]) for k in STYLES])
        self.style.changed.connect(self._pick_style)
        ai.body.addWidget(self.style)
        self.style_help = label("", "Faint", wrap=True)
        ai.body.addWidget(self.style_help)
        self.content.addWidget(ai)

        trial = Card("Try it", "Type how you'd speak and see what Hark would insert.")
        self.sample = QPlainTextEdit("um so I I think we should uh meet on tuesday no wait "
                                     "wednesday comma at 3 pm")
        self.sample.setFixedHeight(80)
        trial.body.addWidget(self.sample)
        row = QHBoxLayout()
        self.run_btn = button("Clean up", name="Primary", icon="sparkle", icon_color="white",
                              on_click=self._try)
        row.addWidget(self.run_btn)
        self.trial_meta = label("", "Faint")
        row.addWidget(self.trial_meta, 1)
        trial.body.addLayout(row)
        self.output = label("", wrap=True)
        self.output.setStyleSheet(f"background: {theme.BG}; border: 1px solid {theme.BORDER};"
                                  " border-radius: 9px; padding: 10px 12px;")
        self.output.hide()
        trial.body.addWidget(self.output)
        self.content.addWidget(trial)
        self.content.addStretch(1)
        self._models_loaded = False

    def refresh(self) -> None:
        cfg = self.ctx.cfg
        self.fillers.set_silently(cfg.remove_fillers)
        self.commands.set_silently(cfg.voice_commands)
        self.ai_on.set_silently(cfg.llm.enabled)
        self.style.select(cfg.llm.style)
        self.style_help.setText(STYLE_HELP[cfg.llm.style])
        for widget in (self.model, self.style):
            widget.setEnabled(cfg.llm.enabled)
        if not self._models_loaded:
            self._load_models()

    # -- settings -----------------------------------------------------------------------

    def _set(self, name: str, value) -> None:
        self.ctx.update_settings(lambda cfg: setattr(cfg, name, value))

    def _toggle_ai(self, enabled: bool) -> None:
        self.ctx.update_settings(lambda cfg: setattr(cfg.llm, "enabled", enabled))
        self.refresh()

    def _pick_model(self, index: int) -> None:
        name = self.model.itemData(index)
        if name:
            self.ctx.update_settings(lambda cfg: setattr(cfg.llm, "model", name))

    def _pick_style(self, style: str) -> None:
        self.ctx.update_settings(lambda cfg: setattr(cfg.llm, "style", style))
        self.style_help.setText(STYLE_HELP[style])

    def _load_models(self) -> None:
        self._models_loaded = True
        self.ollama_state.setText("Checking Ollama…")
        current = self.ctx.cfg.llm.model

        def done(names: list[str]) -> None:
            self.model.clear()
            for name in names or [current]:
                self.model.addItem(name, name)
            matches = [i for i, n in enumerate(names) if n in (current, f"{current}:latest")]
            self.model.setCurrentIndex(matches[0] if matches else 0)
            self.ollama_state.setText(f"{len(names)} model(s) in Ollama" if names else
                                      "No models yet: run  ollama pull qwen2.5:3b")

        def failed(message: str) -> None:
            self.model.clear()
            self.model.addItem(current, current)
            self.ollama_state.setText("Ollama isn't running")
            self.ollama_state.setToolTip(message)

        self.ctx.run_async(lambda: OllamaClient(self.ctx.cfg.llm.url).models(), done, failed)

    # -- try it -------------------------------------------------------------------------

    def _try(self) -> None:
        text = self.sample.toPlainText()
        cfg = self.ctx.cfg
        self.run_btn.setEnabled(False)
        self.trial_meta.setText("Asking the AI…" if cfg.llm.enabled else "")

        def done(result) -> None:
            self.run_btn.setEnabled(True)
            self.output.setText(result.text or "(nothing)")
            self.output.show()
            self.trial_meta.setText("" if result.llm_status == "off" else
                                    f"AI {result.llm_status} · {result.llm_s:.1f}s")

        self.ctx.run_async(lambda: process(text, cfg), done)
