"""Models: download, select and delete speech-to-text models."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QProgressBar, QVBoxLayout

from ...stt import catalog
from .. import theme
from ..context import Context
from ..widgets import Card, Page, button, label


def _chip(text: str, color: str) -> object:
    chip = label(text)
    chip.setStyleSheet(f"color: {color}; border: 1px solid {color}; border-radius: 10px;"
                       " padding: 0 10px; font-size: 9pt;")
    chip.setFixedHeight(22)
    return chip


class ModelCard(Card):
    def __init__(self, page: ModelsPage, info: catalog.ModelInfo):
        super().__init__(spacing=8)
        self.page, self.info = page, info
        top = QHBoxLayout()
        title = QVBoxLayout()
        title.setSpacing(2)
        title.addWidget(label(info.name, "SectionTitle"))
        title.addWidget(label(f"{info.languages} · {info.size_mb:,} MB · {info.note}", "Faint"))
        top.addLayout(title, 1)
        self.chip_slot = QHBoxLayout()
        top.addLayout(self.chip_slot)
        self.body.addLayout(top)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.body.addWidget(self.progress)
        actions = QHBoxLayout()
        self.download_btn = button("Download", name="Primary", icon="models", icon_color="white",
                                   on_click=lambda: page.download(info.id))
        self.use_btn = button("Use this model", on_click=lambda: page.use(info.id))
        self.delete_btn = button("Delete", name="Danger", on_click=lambda: page.delete(info.id))
        for b in (self.download_btn, self.use_btn, self.delete_btn):
            actions.addWidget(b)
        actions.addStretch(1)
        self.body.addLayout(actions)

    def update_state(self, active: bool, downloaded: bool, downloading: bool) -> None:
        while self.chip_slot.count():
            self.chip_slot.takeAt(0).widget().deleteLater()
        if active:
            self.chip_slot.addWidget(_chip("Active", theme.SUCCESS), 0, Qt.AlignmentFlag.AlignTop)
        elif downloaded:
            self.chip_slot.addWidget(_chip("Downloaded", theme.MUTED), 0,
                                     Qt.AlignmentFlag.AlignTop)
        self.download_btn.setVisible(not downloaded)
        self.download_btn.setEnabled(not downloading)
        self.download_btn.setText("Downloading…" if downloading else "Download")
        self.use_btn.setVisible(downloaded and not active)
        self.delete_btn.setVisible(downloaded and not active)
        self.progress.setVisible(downloading)


class ModelsPage(Page):
    def __init__(self, ctx: Context):
        super().__init__("Models", "Speech-to-text runs on this computer. Models download "
                         "once (from Hugging Face) and then work offline.")
        self.ctx = ctx
        self.downloading: str | None = None
        self.cards = {m.id: ModelCard(self, m) for m in catalog.selectable()}
        for card in self.cards.values():
            self.content.addWidget(card)
        self.content.addStretch(1)
        self._progress_timer = QTimer(self, interval=500, timeout=self._poll_progress)

    def refresh(self) -> None:
        active = self.ctx.cfg.stt.model
        for model_id, card in self.cards.items():
            card.update_state(model_id == active, catalog.is_downloaded(model_id),
                              model_id == self.downloading)

    def download(self, model_id: str) -> None:
        if self.downloading:
            return
        self.downloading = model_id
        self._progress_timer.start()
        self.refresh()

        def done(_result) -> None:
            self._finish()
            if not catalog.is_downloaded(self.ctx.cfg.stt.model):
                self.use(model_id)  # nothing usable was selected before

        def failed(message: str) -> None:
            self._finish()
            QMessageBox.warning(self, "Download failed", message)

        self.ctx.run_async(lambda: catalog.download(model_id), done, failed)

    def _poll_progress(self) -> None:
        if not self.downloading:
            return
        info = catalog.get(self.downloading)
        done_mb = catalog.disk_usage(self.downloading) / 1e6
        self.cards[self.downloading].progress.setValue(min(99, int(done_mb / info.size_mb * 100)))

    def _finish(self) -> None:
        self.downloading = None
        self._progress_timer.stop()
        self.refresh()

    def use(self, model_id: str) -> None:
        self.ctx.update_settings(lambda cfg: setattr(cfg.stt, "model", model_id))
        self.refresh()

    def delete(self, model_id: str) -> None:
        info = catalog.get(model_id)
        answer = QMessageBox.question(self, "Delete model",
                                      f"Delete {info.name} ({info.size_mb:,} MB)? You can "
                                      "download it again later.")
        if answer == QMessageBox.StandardButton.Yes:
            catalog.remove(model_id)
            self.refresh()
