import re
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from core.validation.widgets.yasb.codex_usage import CodexUsageConfig
from core.widgets.base import BaseWidget
from core.widgets.services.codex_usage.app_server import EMPTY_USAGE, read_rate_limits


class _RateLimitsWorker(QThread):
    data_ready = pyqtSignal(dict)

    def __init__(self, command: str, parent: Any = None):
        super().__init__(parent)
        self._command = command

    def run(self) -> None:
        self.data_ready.emit(read_rate_limits(self._command, 10))


class CodexUsageWidget(BaseWidget):
    """Display Codex ChatGPT rate limits reported by app-server."""

    validation_schema = CodexUsageConfig

    def __init__(self, config: CodexUsageConfig):
        super().__init__(int(config.update_interval * 1000), class_name=f"codex-usage {config.class_name}")
        self.config = config
        self._show_alt_label = False
        self._usage = dict(EMPTY_USAGE)
        self._worker: _RateLimitsWorker | None = None
        self._init_container()
        self.build_widget_label(self.config.label, self.config.label_alt)
        self.register_callback("toggle_label", self._toggle_label)
        self.register_callback("update_label", self._update_label)
        self.callback_left = self.config.callbacks.on_left
        self.callback_middle = self.config.callbacks.on_middle
        self.callback_right = self.config.callbacks.on_right
        self.callback_timer = "update_label"
        self.destroyed.connect(lambda *_: self._stop_worker())
        self.start_timer()

    def _stop_worker(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.terminate()

    def _toggle_label(self) -> None:
        self._show_alt_label = not self._show_alt_label
        for widget in self._widgets:
            widget.setVisible(not self._show_alt_label)
        for widget in self._widgets_alt:
            widget.setVisible(self._show_alt_label)
        self._render_label()

    def _update_label(self) -> None:
        if self._worker is None:
            self._worker = _RateLimitsWorker(self.config.command, self)
            self._worker.data_ready.connect(self._on_data)
            self._worker.finished.connect(self._on_finished)
            self._worker.start()
        self._render_label()

    def _on_data(self, usage: dict[str, dict[str, int | float | None]]) -> None:
        self._usage = usage
        self._render_label()

    def _on_finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()

    def _render_label(self) -> None:
        template = self.config.label_alt if self._show_alt_label else self.config.label
        labels = self._widgets_alt if self._show_alt_label else self._widgets
        parts = [part for part in re.split(r"(<span.*?>.*?</span>)", template) if part.strip()]
        for index, part in enumerate(parts):
            if index >= len(labels):
                return
            if "<span" in part and "</span>" in part:
                text = re.sub(r"<span.*?>|</span>", "", part).strip()
            else:
                text = part.strip()
            try:
                labels[index].setText(text.format(usage=self._usage))
            except (IndexError, KeyError, ValueError):
                labels[index].setText(text)
