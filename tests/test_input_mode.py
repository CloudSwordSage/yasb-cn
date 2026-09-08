import ctypes
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.widgets.services.language.input_mode import InputModeMonitor
from core.widgets.services.language.mode import (
    format_imm_probe,
    input_mode_code,
    input_mode_key,
    input_mode_target,
    mode_from_input_mode_code,
)


class _PendingPipeKernel:
    def __init__(self) -> None:
        self.read_started = threading.Event()
        self.release = threading.Event()
        self.calls: list[str] = []

    def CreateEventW(self, *_args) -> int:
        return 2

    def ReadFile(self, _handle, _payload, _size, _count, overlapped) -> bool:
        self.read_started.set()
        if overlapped is None:
            self.release.wait()
        else:
            ctypes.set_last_error(997)
        return False

    def WaitForMultipleObjects(self, *_args) -> int:
        self.release.wait()
        return 0

    def SetEvent(self, _handle) -> bool:
        self.calls.append("set")
        self.release.set()
        return True

    def CancelIoEx(self, *_args) -> bool:
        self.calls.append("cancel")
        return True

    def GetOverlappedResult(self, *_args) -> bool:
        self.calls.append("complete")
        return False

    def CloseHandle(self, _handle) -> bool:
        if _handle not in (None, 1, 2):
            return bool(ctypes.windll.kernel32.CloseHandle(_handle))
        return True


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

    @unittest.skipUnless(sys.platform == "win32", "Windows named-pipe lifecycle")
    def test_close_cancels_pending_pipe_read_and_joins_thread(self) -> None:
        monitor = InputModeMonitor()
        kernel = _PendingPipeKernel()
        monitor._kernel32 = kernel
        monitor._open_pipe = lambda: (1, 0)
        monitor.start()
        self.assertTrue(kernel.read_started.wait(1))
        thread = monitor._thread

        try:
            monitor.close()
            self.assertIsNotNone(thread)
            self.assertFalse(thread.is_alive())
            self.assertLess(kernel.calls.index("cancel"), kernel.calls.index("complete"))
        finally:
            kernel.release.set()
            if thread is not None:
                thread.join(1)

    @unittest.skipUnless(sys.platform == "win32", "Windows named-pipe lifecycle")
    def test_stop_during_completed_read_does_not_emit(self) -> None:
        monitor = InputModeMonitor()
        kernel = _PendingPipeKernel()
        monitor._kernel32 = kernel
        monitor._open_pipe = lambda: (1, 0)

        def completed_read(_handle: int) -> bytes:
            kernel.read_started.set()
            kernel.release.wait()
            return b"\x02"

        monitor._read_pipe = completed_read
        monitor.start()
        self.assertTrue(kernel.read_started.wait(1))
        monitor._stop.set()
        kernel.release.set()
        monitor._thread.join(1)
        monitor.close()

        self.assertIsNone(monitor._last_mode)


if __name__ == "__main__":
    unittest.main()
