import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.widgets.services.language.mode import (
    format_imm_probe,
    input_mode_code,
    input_mode_key,
    input_mode_target,
    mode_from_input_mode_code,
)


class InputModeTests(unittest.TestCase):
    def test_classifies_native_conversion_mode(self) -> None:
        self.assertEqual(input_mode_key(0x0001), "native")
        self.assertEqual(input_mode_key(0x0000), "alphanumeric")
        self.assertEqual(input_mode_key(None), "unknown")

    def test_formats_raw_imm32_probe(self) -> None:
        self.assertEqual(format_imm_probe(True, 1), "success=True conversion=0x00000001 mode=native")
        self.assertEqual(format_imm_probe(False, None), "success=False conversion=-- mode=unknown")

    def test_prefers_focus_then_caret_then_foreground(self) -> None:
        self.assertEqual(input_mode_target(101, 102, 100), 101)
        self.assertEqual(input_mode_target(0, 102, 100), 102)
        self.assertEqual(input_mode_target(0, 0, 100), 100)

    def test_failed_query_keeps_last_mode(self) -> None:
        self.assertEqual(input_mode_key(None, "native"), "native")
        self.assertEqual(input_mode_key(None), "unknown")

    def test_encodes_the_pipe_protocol_in_one_byte(self) -> None:
        self.assertEqual(input_mode_code("unknown"), b"\x00")
        self.assertEqual(input_mode_code("alphanumeric"), b"\x01")
        self.assertEqual(input_mode_code("native"), b"\x02")
        self.assertEqual(mode_from_input_mode_code(b"\x00"), "unknown")
        self.assertEqual(mode_from_input_mode_code(b"\x01"), "alphanumeric")
        self.assertEqual(mode_from_input_mode_code(b"\x02"), "native")
        self.assertEqual(mode_from_input_mode_code(b"\xff"), "unknown")


if __name__ == "__main__":
    unittest.main()
