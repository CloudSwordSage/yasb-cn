import re

from core.validation.widgets.yasb.input_mode import InputModeConfig
from core.widgets.base import BaseWidget
from core.widgets.services.language.input_mode import InputModeMonitor


class InputModeWidget(BaseWidget):
    """Display the active Windows IME conversion mode."""

    validation_schema = InputModeConfig

    def __init__(self, config: InputModeConfig):
        super().__init__(class_name=f"input-mode-widget {config.class_name}")
        self.config = config
        self._init_container()
        self.build_widget_label(self.config.label)
        self.callback_left = self.config.callbacks.on_left
        self.callback_middle = self.config.callbacks.on_middle
        self.callback_right = self.config.callbacks.on_right
        self._monitor = InputModeMonitor(self)
        self._monitor.changed.connect(self._on_mode_changed)
        self.destroyed.connect(self._cleanup_events)
        self._monitor.start()

    def _cleanup_events(self, *_args) -> None:
        self._monitor.close()

    def _on_mode_changed(self, mode: str) -> None:
        self._render(mode)

    def _render(self, mode: str) -> None:
        parts = [part for part in re.split(r"(<span.*?>.*?</span>)", self.config.label) if part.strip()]
        for index, part in enumerate(parts):
            if index >= len(self._widgets):
                return
            text = re.sub(r"<span.*?>|</span>", "", part).strip() if "<span" in part else part.strip()
            self._widgets[index].setText(
                text.format(
                    input_mode_label=getattr(self.config.input_mode_labels, mode, self.config.input_mode_labels.unknown)
                )
            )
