import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.widgets.services.language.mode import input_mode_key


class InputModeTests(unittest.TestCase):
    def test_classifies_native_conversion_mode(self) -> None:
        self.assertEqual(input_mode_key(0x0001), "native")
        self.assertEqual(input_mode_key(0x0000), "alphanumeric")
        self.assertEqual(input_mode_key(None), "unknown")


if __name__ == "__main__":
    unittest.main()
