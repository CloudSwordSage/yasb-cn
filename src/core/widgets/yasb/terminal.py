import re
import subprocess

from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QLabel

from core.validation.widgets.yasb.terminal import TerminalConfig, TerminalEntryConfig
from core.widgets.base import BaseWidget


class TerminalWidget(BaseWidget):
    """Launch and switch between configured terminal applications."""

    validation_schema = TerminalConfig

    def __init__(self, config: TerminalConfig):
        super().__init__(class_name=f"terminal-widget {config.class_name}")
        self.config = config
        self._selected_index = 0
        self._show_alt_label = False
        self._init_container()
        self.build_widget_label(self.config.label, self.config.label_alt)
        self.register_callback("launch", self._launch)
        self.register_callback("launch_alternate", self._launch_alternate)
        self.register_callback("toggle_label", self._toggle_label)
        self.callback_left = self.config.callbacks.on_left
        self.callback_middle = self.config.callbacks.on_middle
        self.callback_right = self.config.callbacks.on_right
        self._render()

    @property
    def current_terminal(self) -> TerminalEntryConfig:
        """Return the terminal currently selected by the widget."""
        return self.config.terminals[self._selected_index]

    def _launch(self) -> None:
        """Start the selected terminal command."""
        self._launch_command(self.current_terminal.command)

    def _launch_alternate(self) -> None:
        """Start the selected terminal alternate command when configured."""
        self._launch_command(self.current_terminal.alternate_command)

    def _launch_command(self, command: str | None) -> None:
        """Launch a command through its configured terminal host when present."""
        if command is None:
            return
        launcher = self.current_terminal.launcher
        if launcher is None:
            launcher = self.config.launcher
        cmdline = f"{launcher} {command}" if launcher and launcher.casefold() != "no" else command
        subprocess.Popen(cmdline, shell=True)

    def _toggle_label(self) -> None:
        """Toggle between the configured primary and alternate labels."""
        self._show_alt_label = not self._show_alt_label
        for widget in self._widgets:
            widget.setVisible(not self._show_alt_label)
        for widget in self._widgets_alt:
            widget.setVisible(self._show_alt_label)

    def _select_previous(self) -> None:
        """Select the preceding terminal, wrapping at the beginning."""
        self._selected_index = (self._selected_index - 1) % len(self.config.terminals)
        self._render()

    def _select_next(self) -> None:
        """Select the next terminal, wrapping at the end."""
        self._selected_index = (self._selected_index + 1) % len(self.config.terminals)
        self._render()

    def _render(self) -> None:
        """Render the selected terminal into both label variants."""
        terminal = self.current_terminal
        values = {
            "name": terminal.name,
            "short": terminal.short,
            "icon": terminal.icon,
            "command": terminal.command or "",
        }
        self._render_label(self.config.label, self._widgets, values)
        self._render_label(self.config.label_alt, self._widgets_alt, values)

    @staticmethod
    def _render_label(label: str, widgets: list[QLabel], values: dict[str, str]) -> None:
        """Render a formatted label into its BaseWidget-created QLabel parts."""
        parts = [part.strip() for part in re.split(r"(<span.*?>.*?</span>)", label) if part.strip()]
        for widget, part in zip(widgets, parts):
            text = re.sub(r"<span.*?>|</span>", "", part).strip()
            widget.setText(text.format(**values))

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Select the previous terminal on upward wheel input and next on downward input."""
        if event.angleDelta().y() > 0:
            self._select_previous()
        elif event.angleDelta().y() < 0:
            self._select_next()
        event.accept()
