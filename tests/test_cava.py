import ctypes
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pydantic import ValidationError
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from core.validation.widgets.yasb.cava import CavaConfig
from core.widgets.yasb.cava import (
    CavaHealth,
    CavaProcessManager,
    CavaState,
    CavaWidget,
    _make_cava_cleanup,
    _read_cava_version,
)


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

    def __init__(
        self,
        *,
        timeout_on_terminate: bool = False,
        terminate_error: bool = False,
        timeout_after_kill: bool = False,
        eof: bool = False,
    ) -> None:
        type(self)._next_pid += 1
        self.pid = type(self)._next_pid
        self._stopped = threading.Event()
        self._timeout_on_terminate = timeout_on_terminate
        self._terminate_error = terminate_error
        self._timeout_after_kill = timeout_after_kill
        self._killed = False
        self.stdout = _EofStdout(self._stopped) if eof else _BlockingStdout(self._stopped)
        self.wait_calls = 0
        self.wait_timeouts: list[float | None] = []

    def poll(self) -> int | None:
        return 0 if self._stopped.is_set() else None

    def terminate(self) -> None:
        if self._terminate_error:
            raise OSError("terminate failed")
        if not self._timeout_on_terminate:
            self._stopped.set()

    def kill(self) -> None:
        self._killed = True
        if not self._timeout_after_kill:
            self._stopped.set()

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        self.wait_timeouts.append(timeout)
        if self._timeout_on_terminate and not self._killed:
            raise subprocess.TimeoutExpired("cava", timeout)
        if self._timeout_after_kill and self._killed:
            raise subprocess.TimeoutExpired("cava", timeout)
        self._stopped.wait(timeout)
        return 0


class _StuckThread:
    def __init__(self) -> None:
        self.join_timeout: float | None = None

    def is_alive(self) -> bool:
        return True

    def join(self, timeout: float | None = None) -> None:
        self.join_timeout = timeout


class _ExitingThread(_StuckThread):
    def __init__(self, process: _FakeProcess) -> None:
        super().__init__()
        self._process = process
        self._alive = True

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout: float | None = None) -> None:
        super().join(timeout)
        self._process._stopped.set()
        self._alive = False


class CavaProcessManagerTests(unittest.TestCase):
    def test_signal_health_requires_sustained_system_audio_mismatch(self) -> None:
        manager = CavaProcessManager("cava.conf", 2, "8bit", lambda _samples: None, cava_peak_threshold=0.1)
        manager._state = CavaState.RUNNING
        manager._last_frame_time = 10.0
        manager._record_signal([0.0, 0.0], now=10.0)

        with patch("core.widgets.yasb.cava.time.monotonic", side_effect=[11.0, 13.9, 14.1]):
            self.assertIs(manager.health(0.5, 10.0, 3.0, 0.01), CavaHealth.HEALTHY)
            self.assertIs(manager.health(0.5, 10.0, 3.0, 0.01), CavaHealth.HEALTHY)
            self.assertIs(manager.health(0.5, 10.0, 3.0, 0.01), CavaHealth.SIGNAL_STALLED)

    def test_effective_signal_updates_metrics_and_resets_mismatch(self) -> None:
        manager = CavaProcessManager("cava.conf", 2, "8bit", lambda _samples: None, cava_peak_threshold=0.1)
        manager._state = CavaState.RUNNING
        manager._last_frame_time = 10.0
        manager._record_signal([0.0, 0.0], now=10.0)

        with patch("core.widgets.yasb.cava.time.monotonic", return_value=11.0):
            manager.health(0.5, 10.0, 3.0, 0.01)
        manager._record_signal([0.05, 0.2], now=12.0)

        self.assertEqual(manager.signal_metrics(now=13.0), (0.2, 1.0))
        self.assertIsNone(manager._signal_mismatch_since)

    def test_stop_keeps_ownership_when_worker_does_not_exit(self) -> None:
        manager = CavaProcessManager("cava.conf", 2, "8bit", lambda _samples: None)
        process = _FakeProcess()
        thread = _StuckThread()
        manager._state = CavaState.RUNNING
        manager._generation = 1
        manager._process = process
        manager._thread = thread
        manager._stop_event = threading.Event()

        self.assertFalse(manager.stop())

        self.assertEqual(thread.join_timeout, 3)
        self.assertEqual(manager.state, CavaState.STOPPING)
        self.assertFalse(manager.start(""))
        self.assertEqual(manager.generation, 1)

    def test_terminate_error_falls_back_to_kill(self) -> None:
        process = _FakeProcess(terminate_error=True)

        self.assertTrue(CavaProcessManager._terminate_process(process, 1, "test"))

        self.assertTrue(process._killed)
        self.assertEqual(process.wait_timeouts, [2])

    def test_stop_accepts_process_reaped_by_exiting_worker(self) -> None:
        manager = CavaProcessManager("cava.conf", 2, "8bit", lambda _samples: None)
        process = _FakeProcess()
        manager._state = CavaState.RUNNING
        manager._generation = 1
        manager._process = process
        manager._thread = _ExitingThread(process)
        manager._stop_event = threading.Event()

        with patch.object(manager, "_terminate_process", return_value=False):
            self.assertTrue(manager.stop())

        self.assertEqual(manager.state, CavaState.STOPPED)
        self.assertIsNone(manager.process_id)

    def test_kill_wait_is_bounded_and_reports_failure(self) -> None:
        process = _FakeProcess(timeout_on_terminate=True, timeout_after_kill=True)

        self.assertFalse(CavaProcessManager._terminate_process(process, 1, "test"))

        self.assertEqual(process.wait_timeouts, [2, 2])


class CavaConfigurationTests(unittest.TestCase):
    def test_runtime_sensitive_values_are_validated(self) -> None:
        invalid_values = {
            "bar_height": 0,
            "min_bar_height": -1,
            "bars_number": 0,
            "output_bit_format": "32bit",
            "sleep_timer": -1,
            "framerate": 0,
            "edge_fade": [10],
            "cava_peak_threshold": -0.1,
            "system_peak_threshold": -0.1,
            "signal_timeout": 0,
        }

        for field, value in invalid_values.items():
            with self.subTest(field=field), self.assertRaises(ValidationError):
                CavaConfig(**{field: value})

        for edge_fade in (-1, [-1, 10], [10, -1]):
            with self.subTest(edge_fade=edge_fade), self.assertRaises(ValidationError):
                CavaConfig(edge_fade=edge_fade)

        self.assertEqual(CavaConfig(edge_fade=[10, 20]).edge_fade, (10, 20))

        config = CavaConfig(cava_peak_threshold=0.01, system_peak_threshold=0.02, signal_timeout=4)
        self.assertEqual(
            (config.cava_peak_threshold, config.system_peak_threshold, config.signal_timeout),
            (0.01, 0.02, 4),
        )


class CavaCleanupTests(unittest.TestCase):
    def test_failed_stop_remains_registered_for_retry(self) -> None:
        manager = Mock()
        manager.stop.side_effect = [False, True]
        app = Mock()
        enumerator = Mock()
        cleanup = _make_cava_cleanup(manager, app, object(), enumerator, object())

        with patch("core.widgets.yasb.cava.atexit.unregister") as unregister:
            cleanup()
            unregister.assert_not_called()
            cleanup()
            cleanup()

        self.assertEqual(manager.stop.call_count, 2)
        unregister.assert_called_once_with(cleanup)
        app.removeNativeEventFilter.assert_called_once()
        enumerator.UnregisterEndpointNotificationCallback.assert_called_once()


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
        if self.widget is not None:
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
        manager = CavaProcessManager(
            str(Path(self.temp_dir.name) / "manager.conf"),
            2,
            "8bit",
            lambda _samples: None,
        )
        callers = [threading.Thread(target=manager.start, args=("",)) for _ in range(20)]
        for caller in callers:
            caller.start()
        for caller in callers:
            caller.join()

        self.assertTrue(self._wait_until(lambda: manager.process_id is not None))
        self.assertEqual(manager.generation, 1)
        manager.stop()

    def test_concurrent_reload_runs_on_widget_thread_and_debounces(self) -> None:
        callers = [threading.Thread(target=self.widget._reload_cava) for _ in range(20)]
        for caller in callers:
            caller.start()
        self.assertTrue(self._wait_until(lambda: all(not caller.is_alive() for caller in callers)))
        for caller in callers:
            caller.join()
        QTest.qWait(700)

        self.assertEqual(len(self.processes), 2)

    def test_stop_waits_after_forced_kill(self) -> None:
        process = self.processes[0]
        process._timeout_on_terminate = True

        self.widget.stop_cava()

        self.assertEqual(process.wait_calls, 2)

    def test_zero_frame_requests_repaint(self) -> None:
        with patch.object(type(self.widget._bar_frame), "update") as update:
            self.widget.on_samples_updated([0] * self.widget.config.bars_number)

        update.assert_called_once_with()

    def test_single_gradient_color_draws_in_all_paths(self) -> None:
        self.widget.colors = [QColor("#89b4fa")]
        self.widget.samples = [0.5] * self.widget.config.bars_number
        image = QImage(
            max(1, self.widget._bar_frame.width()),
            max(1, self.widget._bar_frame.height()),
            QImage.Format.Format_ARGB32,
        )
        image.fill(Qt.GlobalColor.transparent)

        for method_name in ("draw_bars", "draw_bars_mirrored", "draw_waves"):
            with self.subTest(method=method_name):
                painter = QPainter(image)
                try:
                    getattr(self.widget._bar_frame, method_name)(painter)
                finally:
                    painter.end()

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

    def test_close_event_performs_final_cleanup(self) -> None:
        process = self.processes[0]

        self.widget.close()
        QTest.qWait(50)

        self.assertIsNotNone(process.poll())
        self.assertTrue(self.widget._shutdown)
        self.assertIsNone(self.widget._system_event_filter)

    def test_delete_later_performs_final_cleanup(self) -> None:
        process = self.processes[0]

        self.widget.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.widget = None

        self.assertIsNotNone(process.poll())

    def test_parent_disposal_performs_final_cleanup(self) -> None:
        process = self.processes[0]
        parent = QWidget()
        self.widget.setParent(parent)

        parent.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.widget = None

        self.assertIsNotNone(process.poll())


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

    def test_version_probe_uses_documented_short_flag(self) -> None:
        with patch(
            "core.widgets.yasb.cava.subprocess.run",
            return_value=subprocess.CompletedProcess(["cava", "-v"], 0, "cava 1.0.0", ""),
        ) as run:
            self.assertEqual(_read_cava_version("cava.exe"), (1, 0, 0))

        self.assertEqual(run.call_args.args[0], ["cava.exe", "-v"])

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
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_real_stalled_child_is_replaced_and_reaped(self) -> None:
        script = "import sys,time;sys.stdout.buffer.write(bytes((64,128)));sys.stdout.buffer.flush();time.sleep(30)"
        with tempfile.TemporaryDirectory() as temp_dir:
            with self._real_child_widget(temp_dir, script):
                widget = CavaWidget(
                    CavaConfig(
                        source="integration-test",
                        bars_number=2,
                        output_bit_format="8bit",
                        output_timeout=0.1,
                    )
                )
                self.assertTrue(self._wait_until(lambda: widget._manager.process_id is not None))
                old_pid = widget._manager.process_id
                self.assertTrue(
                    self._wait_until(
                        lambda: widget._manager.generation >= 2
                        and widget._manager.process_id is not None
                        and widget._manager.process_id != old_pid,
                        timeout=3,
                    )
                )
                replacement_pid = widget._manager.process_id
                self.assertFalse(self._pid_is_running(old_pid))
                widget.close()

        self.assertFalse(self._pid_is_running(replacement_pid))

    def test_real_killed_child_is_replaced_and_reaped(self) -> None:
        script = "import time;time.sleep(30)"
        with tempfile.TemporaryDirectory() as temp_dir:
            with self._real_child_widget(temp_dir, script):
                widget = CavaWidget(
                    CavaConfig(source="integration-test", bars_number=2, output_bit_format="8bit", output_timeout=5)
                )
                self.assertTrue(self._wait_until(lambda: widget._manager.process_id is not None))
                old_pid = widget._manager.process_id
                self.assertTrue(self._terminate_pid(old_pid))
                self.assertTrue(
                    self._wait_until(
                        lambda: widget._manager.generation >= 2
                        and widget._manager.process_id is not None
                        and widget._manager.process_id != old_pid,
                        timeout=3,
                    )
                )
                replacement_pid = widget._manager.process_id
                self.assertFalse(self._pid_is_running(old_pid))
                widget.close()

        self.assertFalse(self._pid_is_running(replacement_pid))

    @staticmethod
    @contextmanager
    def _real_child_widget(temp_dir: str, script: str):
        original_init = CavaProcessManager.__init__

        def manager_init(
            manager,
            config_path,
            bars_number,
            bit_format,
            on_samples,
            on_failure=None,
            _command=None,
        ) -> None:
            original_init(
                manager,
                config_path,
                bars_number,
                bit_format,
                on_samples,
                on_failure,
                [sys.executable, "-u", "-c", script],
            )

        with (
            patch("core.widgets.yasb.cava.shutil.which", return_value=sys.executable),
            patch("core.widgets.yasb.cava._read_cava_version", return_value=(1, 0, 0)),
            patch(
                "core.widgets.yasb.cava.app_data_path",
                side_effect=lambda name: str(Path(temp_dir) / name),
            ),
            patch.object(CavaProcessManager, "__init__", new=manager_init),
        ):
            yield

    @staticmethod
    def _wait_until(condition, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return True
            QTest.qWait(10)
        return condition()

    @staticmethod
    def _terminate_pid(pid: int) -> bool:
        handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)
        if not handle:
            return False
        try:
            return bool(ctypes.windll.kernel32.TerminateProcess(handle, 9))
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

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
