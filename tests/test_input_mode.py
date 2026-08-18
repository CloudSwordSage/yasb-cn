import sys
import unittest
import ctypes
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.widgets.services.language.mode import THREAD_MANAGER_COMPARTMENT_IID, callback_address, format_probe, input_mode_key


class InputModeTests(unittest.TestCase):
    def test_classifies_native_conversion_mode(self) -> None:
        self.assertEqual(input_mode_key(0x0001), "native")
        self.assertEqual(input_mode_key(0x0000), "alphanumeric")
        self.assertEqual(input_mode_key(None), "unknown")

    def test_converts_winapi_callback_to_vtable_pointer(self) -> None:
        callback = ctypes.WINFUNCTYPE(ctypes.c_long)(lambda: 0)
        self.assertIsInstance(callback_address(callback), ctypes.c_void_p)

    def test_formats_raw_compartment_probe(self) -> None:
        self.assertEqual(format_probe(0, 19, 1), "hr=0x00000000 vt=19 conversion=0x00000001 mode=native")

    def test_uses_thread_manager_compartment_interface(self) -> None:
        self.assertEqual(THREAD_MANAGER_COMPARTMENT_IID, "7DCF57AC-18AD-438B-824D-979BFFB74B7C")


if __name__ == "__main__":
    unittest.main()
