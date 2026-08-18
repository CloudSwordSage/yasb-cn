import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.widgets.services.language.mode import format_imm_probe, input_mode_key


class InputModeTests(unittest.TestCase):
    def test_classifies_native_conversion_mode(self) -> None:
        self.assertEqual(input_mode_key(0x0001), "native")
        self.assertEqual(input_mode_key(0x0000), "alphanumeric")
        self.assertEqual(input_mode_key(None), "unknown")

    def test_formats_raw_imm32_probe(self) -> None:
        self.assertEqual(format_imm_probe(True, 1), "success=True conversion=0x00000001 mode=native")
        self.assertEqual(format_imm_probe(False, None), "success=False conversion=-- mode=unknown")


if __name__ == "__main__":
    unittest.main()
