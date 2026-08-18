import re

from PyQt6.QtCore import pyqtSignal

from core.events.service import EventService
from core.events.win32 import WinEvent
from core.validation.widgets.yasb.input_mode import InputModeConfig
from core.widgets.base import BaseWidget
from core.widgets.services.language.input_mode import InputModeMonitor

try:
    from core.utils.win32.event_listener import SystemEventListener
except ImportError:
    SystemEventListener = None


class InputModeWidget(BaseWidget):
    """Display the active Windows IME conversion mode."""

    validation_schema = InputModeConfig
    event_listener = SystemEventListener
    input_mode_change = pyqtSignal(int, WinEvent)

    def __init__(self, config: InputModeConfig):
        super().__init__(class_name=f"input-mode-widget {config.class_name}")
        self.config = config
        self._init_container()
        self.build_widget_label(self.config.label)
        self.callback_left = self.config.callbacks.on_left
        self.callback_middle = self.config.callbacks.on_middle
        self.callback_right = self.config.callbacks.on_right
        self._event_service = EventService()
        self._monitor = InputModeMonitor(self)
        self._monitor.changed.connect(self._on_mode_changed)
        self.input_mode_change.connect(self._monitor.request_update)
        for event in (WinEvent.EventSystemForeground, WinEvent.EventObjectFocus, WinEvent.EventObjectIMEChange):
            self._event_service.register_event(event, self.input_mode_change)
        self.destroyed.connect(self._cleanup_events)
        self._monitor.start()

    def _cleanup_events(self, *_args) -> None:
        self._monitor.close()
        for event in (WinEvent.EventSystemForeground, WinEvent.EventObjectFocus, WinEvent.EventObjectIMEChange):
            self._event_service.unregister_event(event, self.input_mode_change)

    def _on_mode_changed(self, mode: str) -> None:
        self._render(mode)

    def _render(self, mode: str) -> None:
        parts = [part for part in re.split(r"(<span.*?>.*?</span>)", self.config.label) if part.strip()]
        for index, part in enumerate(parts):
            if index >= len(self._widgets):
                return
            text = re.sub(r"<span.*?>|</span>", "", part).strip() if "<span" in part else part.strip()
            self._widgets[index].setText(
                text.format(input_mode_label=getattr(self.config.input_mode_labels, mode, self.config.input_mode_labels.unknown))
            )
