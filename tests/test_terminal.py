import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtWidgets import QApplication

from core.validation.widgets.yasb.terminal import TerminalConfig
from core.widgets.yasb.terminal import TerminalWidget


class TerminalWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.widget = TerminalWidget(
            TerminalConfig(
                terminals=[
                    {"name": "PowerShell", "icon": "P", "command": "pwsh.exe", "alternate_command": "pwsh -home"},
                    {"name": "CMD", "icon": "C", "command": "cmd.exe", "alternate_command": "cmd -home"},
                ]
            )
        )

    def test_scroll_cycles_terminals_and_renders_selected_values(self) -> None:
        self.widget._select_previous()
        self.assertEqual(self.widget.current_terminal.name, "CMD")
        self.assertEqual(self.widget._widgets[0].text(), "C")
        self.assertEqual(self.widget._widgets[1].text(), "CMD")
        self.assertEqual(self.widget._widgets_alt[0].text(), "cmd.exe")

    def test_accepts_short_and_a_single_launch_command(self) -> None:
        config = TerminalConfig(
            label="<span>{icon}</span>{short}",
            label_alt="{name}",
            terminals=[{"name": "Git Bash", "short": "SH", "icon": "G", "alternate_command": "bash -home"}],
        )

        widget = TerminalWidget(config)
        self.assertEqual(widget._widgets[1].text(), "SH")
        self.assertEqual(widget._widgets_alt[0].text(), "Git Bash")

    def test_rejects_terminal_without_a_launch_command(self) -> None:
        with self.assertRaises(ValidationError):
            TerminalConfig(terminals=[{"name": "Invalid"}])

    @patch("core.widgets.yasb.terminal.subprocess.Popen")
    def test_launcher_uses_global_value_and_terminal_override(self, popen) -> None:
        widget = TerminalWidget(
            TerminalConfig(
                launcher="wt.exe",
                terminals=[
                    {"name": "PowerShell", "command": "pwsh.exe"},
                    {"name": "Git Bash", "launcher": "nO", "command": "bash.exe"},
                    {"name": "Custom", "launcher": "custom-host.exe", "command": "custom.exe"},
                ],
            )
        )

        widget._launch()
        widget._select_next()
        widget._launch()
        widget._select_next()
        widget._launch()

        self.assertEqual(
            [call.args[0] for call in popen.call_args_list],
            ["wt.exe pwsh.exe", "bash.exe", "custom-host.exe custom.exe"],
        )

    @patch("core.widgets.yasb.terminal.subprocess.Popen")
    def test_launch_callbacks_use_selected_command(self, popen) -> None:
        self.widget._launch()
        self.widget._launch_alternate()

        self.assertEqual(popen.call_args_list[0].args, ("pwsh.exe",))
        self.assertEqual(popen.call_args_list[1].args, ("pwsh -home",))
        self.assertTrue(all(call.kwargs["shell"] for call in popen.call_args_list))


if __name__ == "__main__":
    unittest.main()
