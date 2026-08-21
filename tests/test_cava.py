import ctypes
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pydantic import ValidationError
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel

from core.validation.widgets.yasb.cava import CavaConfig
from core.widgets.yasb.cava import CavaProcessManager, CavaState, CavaWidget


class _BlockingStdout:
    def __init__(self, stopped: threading.Event) -> None:
        self._stopped = stopped

    def read(self, _size: int) -> bytes:
        self._stopped.wait()
        return b""

    def close(self) -> None:
        self._stopped.set()


class _EofStdout:
    def __init__(self, stopped: threading.Event) -> None:
        self._stopped = stopped

    def read(self, _size: int) -> bytes:
        self._stopped.set()
        return b""

    def close(self) -> None:
        self._stopped.set()


class _FakeProcess:
    _next_pid = 1000

    def __init__(self, *, timeout_on_terminate: bool = False, eof: bool = False) -> None:
        type(self)._next_pid += 1
        self.pid = type(self)._next_pid
        self._stopped = threading.Event()
        self._timeout_on_terminate = timeout_on_terminate
        self._killed = False
        self.stdout = _EofStdout(self._stopped) if eof else _BlockingStdout(self._stopped)
        self.wait_calls = 0

    def poll(self) -> int | None:
        return 0 if self._stopped.is_set() else None

    def terminate(self) -> None:
        if not self._timeout_on_terminate:
            self._stopped.set()

    def kill(self) -> None:
        self._killed = True
        self._stopped.set()

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        if self._timeout_on_terminate and not self._killed:
            raise subprocess.TimeoutExpired("cava", timeout)
        self._stopped.wait(timeout)
        return 0


class CavaLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.processes: list[_FakeProcess] = []
        self.temp_dir = tempfile.TemporaryDirectory()
        self.which_patcher = patch("core.widgets.yasb.cava.shutil.which", return_value="cava.exe")
        self.version_patcher = patch("core.widgets.yasb.cava._read_cava_version", return_value=(1, 0, 0))
        self.path_patcher = patch(
            "core.widgets.yasb.cava.app_data_path",
            side_effect=lambda name: str(Path(self.temp_dir.name) / name),
        )
        self.popen_patcher = patch("core.widgets.yasb.cava.subprocess.Popen", side_effect=self._create_process)
        self.which_patcher.start()
        self.version_patcher.start()
        self.path_patcher.start()
        self.popen_patcher.start()
        self.widget = CavaWidget(CavaConfig())
        self.assertTrue(self._wait_until(lambda: len(self.processes) == 1))

    def tearDown(self) -> None:
        self.widget.shutdown()
        self.widget.close()
        self.popen_patcher.stop()
        self.path_patcher.stop()
        self.which_patcher.stop()
        self.version_patcher.stop()
        self.temp_dir.cleanup()

    def _create_process(self, *_args, **_kwargs) -> _FakeProcess:
        process = _FakeProcess()
        self.processes.append(process)
        return process

    @staticmethod
    def _wait_until(condition, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return True
            QTest.qWait(10)
        return condition()

    def test_reload_storm_starts_only_one_replacement(self) -> None:
        for _ in range(100):
            self.widget._reload_cava()

        QTest.qWait(700)

        self.assertEqual(len(self.processes), 2)

    def test_concurrent_start_creates_only_one_process(self) -> None:
        self.widget.stop_cava()
        callers = [threading.Thread(target=self.widget.start_cava) for _ in range(20)]
        for caller in callers:
            caller.start()
        for caller in callers:
            caller.join()

        self.assertTrue(self._wait_until(lambda: len(self.processes) > 1 or self.processes[-1].poll() is None))
        self.assertEqual(sum(process.poll() is None for process in self.processes), 1)

    def test_stop_waits_after_forced_kill(self) -> None:
        process = self.processes[0]
        process._timeout_on_terminate = True

        self.widget.stop_cava()

        self.assertEqual(process.wait_calls, 2)

    def test_system_resume_requests_one_restart(self) -> None:
        event_filter = getattr(self.widget, "_system_event_filter", None)
        self.assertIsNotNone(event_filter)
        if event_filter is None:
            return
        message = ctypes.wintypes.MSG()
        message.message = 0x0218
        message.wParam = 0x0012

        event_filter.nativeEventFilter("windows_generic_MSG", ctypes.addressof(message))
        QTest.qWait(700)

        self.assertEqual(len(self.processes), 2)

    def test_default_audio_device_change_requests_one_restart(self) -> None:
        callback = getattr(self.widget, "_audio_device_callback", None)
        self.assertIsNotNone(callback)
        if callback is None:
            return

        callback.on_default_device_changed("eRender", 0, "eMultimedia", 1, "device-id")
        QTest.qWait(700)

        self.assertEqual(len(self.processes), 2)

    def test_late_failure_signal_does_not_undo_active_stop(self) -> None:
        self.widget.stop_cava()

        self.widget.restartRequested.emit("late worker failure")
        QTest.qWait(700)

        self.assertEqual(len(self.processes), 1)


class CavaRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_accepts_positive_output_timeout(self) -> None:
        try:
            config = CavaConfig(output_timeout=0.1)
        except ValidationError as error:
            self.fail(f"output_timeout should be configurable: {error}")
        self.assertEqual(config.output_timeout, 0.1)

    def test_unexpected_exit_respawns_cava(self) -> None:
        processes: list[_FakeProcess] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("core.widgets.yasb.cava.shutil.which", return_value="cava.exe"),
                patch("core.widgets.yasb.cava._read_cava_version", return_value=(1, 0, 0)),
                patch(
                    "core.widgets.yasb.cava.app_data_path",
                    side_effect=lambda name: str(Path(temp_dir) / name),
                ),
                patch(
                    "core.widgets.yasb.cava.subprocess.Popen",
                    side_effect=lambda *_args, **_kwargs: processes.append(_FakeProcess(eof=True)) or processes[-1],
                ),
            ):
                widget = CavaWidget(CavaConfig())
                QTest.qWait(1200)
                widget.stop_cava()
                widget.close()

        self.assertGreaterEqual(len(processes), 2)

    def test_stalled_stdout_respawns_cava(self) -> None:
        processes: list[_FakeProcess] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("core.widgets.yasb.cava.shutil.which", return_value="cava.exe"),
                patch("core.widgets.yasb.cava._read_cava_version", return_value=(1, 0, 0)),
                patch(
                    "core.widgets.yasb.cava.app_data_path",
                    side_effect=lambda name: str(Path(temp_dir) / name),
                ),
                patch(
                    "core.widgets.yasb.cava.subprocess.Popen",
                    side_effect=lambda *_args, **_kwargs: processes.append(_FakeProcess()) or processes[-1],
                ),
            ):
                widget = CavaWidget(CavaConfig(output_timeout=0.1))
                QTest.qWait(900)
                widget.shutdown()
                widget.close()

        self.assertGreaterEqual(len(processes), 2)

    def test_active_stop_does_not_respawn_cava(self) -> None:
        processes: list[_FakeProcess] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("core.widgets.yasb.cava.shutil.which", return_value="cava.exe"),
                patch("core.widgets.yasb.cava._read_cava_version", return_value=(1, 0, 0)),
                patch(
                    "core.widgets.yasb.cava.app_data_path",
                    side_effect=lambda name: str(Path(temp_dir) / name),
                ),
                patch(
                    "core.widgets.yasb.cava.subprocess.Popen",
                    side_effect=lambda *_args, **_kwargs: processes.append(_FakeProcess()) or processes[-1],
                ),
            ):
                widget = CavaWidget(CavaConfig(output_timeout=0.1))
                QTest.qWait(50)
                widget.stop_cava()
                QTest.qWait(400)
                widget.shutdown()
                widget.close()

        self.assertEqual(len(processes), 1)

    def test_old_cava_version_is_rejected_before_spawn(self) -> None:
        processes: list[_FakeProcess] = []
        with (
            patch("core.widgets.yasb.cava.shutil.which", return_value="cava.exe"),
            patch("core.widgets.yasb.cava._read_cava_version", return_value=(0, 10, 3)),
            patch(
                "core.widgets.yasb.cava.subprocess.Popen",
                side_effect=lambda *_args, **_kwargs: processes.append(_FakeProcess()) or processes[-1],
            ),
        ):
            widget = CavaWidget(CavaConfig())
            QTest.qWait(50)
            labels = " ".join(label.text() for label in widget.findChildren(QLabel))
            widget.shutdown()
            widget.close()

        self.assertEqual(processes, [])
        self.assertIn("0.10.4", labels)

    def test_failure_log_contains_pid_reason_and_stderr(self) -> None:
        processes: list[_FakeProcess] = []

        def create_process(*_args, **kwargs) -> _FakeProcess:
            kwargs["stderr"].write(b"WASAPI backend failed\n")
            kwargs["stderr"].flush()
            processes.append(_FakeProcess(eof=True))
            return processes[-1]

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("core.widgets.yasb.cava.shutil.which", return_value="cava.exe"),
                patch("core.widgets.yasb.cava._read_cava_version", return_value=(1, 0, 0)),
                patch(
                    "core.widgets.yasb.cava.app_data_path",
                    side_effect=lambda name: str(Path(temp_dir) / name),
                ),
                patch("core.widgets.yasb.cava.subprocess.Popen", side_effect=create_process),
                self.assertLogs(level="DEBUG") as captured,
            ):
                widget = CavaWidget(CavaConfig())
                QTest.qWait(100)
                widget.shutdown()
                widget.close()

        log = "\n".join(captured.output)
        self.assertIn(f"PID={processes[0].pid}", log)
        self.assertIn("stdout EOF", log)
        self.assertIn("WASAPI backend failed", log)


@unittest.skipUnless(sys.platform == "win32", "Windows process integration")
class CavaWindowsIntegrationTests(unittest.TestCase):
    def test_real_child_stall_is_detected_and_process_is_reaped(self) -> None:
        frame_received = threading.Event()
        script = (
            "import sys,time;"
            "sys.stdout.buffer.write(bytes((64,128)));"
            "sys.stdout.buffer.flush();"
            "time.sleep(30)"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CavaProcessManager(
                str(Path(temp_dir) / "cava.conf"),
                2,
                "8bit",
                lambda _samples: frame_received.set(),
                command=[sys.executable, "-u", "-c", script],
            )
            try:
                self.assertTrue(manager.start(""))
                self.assertTrue(frame_received.wait(2))
                pid = manager.process_id
                self.assertIsNotNone(pid)
                time.sleep(0.2)
                self.assertTrue(manager.is_stalled(0.1))
            finally:
                manager.stop()

        self.assertEqual(manager.state, CavaState.STOPPED)
        self.assertFalse(self._pid_is_running(pid))

    @staticmethod
    def _pid_is_running(pid: int) -> bool:
        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.wintypes.DWORD()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)


if __name__ == "__main__":
    unittest.main()
