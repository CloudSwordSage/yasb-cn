import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.validation.widgets.yasb.input_mode import InputModeConfig


class InputModeConfigTests(unittest.TestCase):
    def test_accepts_custom_labels(self) -> None:
        config = InputModeConfig(label="{input_mode_label}", input_mode_labels={"native": "中"})
        self.assertEqual(config.input_mode_labels.native, "中")
        self.assertEqual(config.input_mode_labels.alphanumeric, "英")


if __name__ == "__main__":
    unittest.main()
