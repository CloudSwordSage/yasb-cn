import atexit
import ctypes
import logging
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from enum import Enum

from pycaw.callbacks import MMNotificationClient
from pycaw.pycaw import AudioUtilities
from PyQt6.QtCore import (
    QAbstractNativeEventFilter,
    QMetaObject,
    QPointF,
    QRectF,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PyQt6.QtWidgets import QApplication, QFrame, QLabel

from core.utils.system import app_data_path
from core.validation.widgets.yasb.cava import CavaConfig
from core.widgets.base import BaseWidget

_MIN_CAVA_VERSION = (0, 10, 4)
_WM_POWERBROADCAST = 0x0218
_POWER_RESUME_EVENTS = {0x0006, 0x0007, 0x0012}


def _read_cava_version(executable: str) -> tuple[int, int, int] | None:
    try:
        result = subprocess.run(
            [executable, "-v"],
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        logging.warning("Unable to determine Cava version", exc_info=True)
        return None
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", f"{result.stdout}\n{result.stderr}")
    return tuple(map(int, match.groups())) if match else None


class _CavaSystemEventFilter(QAbstractNativeEventFilter):
    def __init__(self, on_resume: Callable[[str], None]) -> None:
        super().__init__()
        self._on_resume = on_resume

    def nativeEventFilter(self, _event_type, message):
        try:
            event = ctypes.wintypes.MSG.from_address(int(message))
            if event.message == _WM_POWERBROADCAST and event.wParam in _POWER_RESUME_EVENTS:
                self._on_resume("system resume")
        except (TypeError, ValueError):
            pass
        return False, 0


class _CavaAudioDeviceCallback(MMNotificationClient):
    def __init__(self, on_change: Callable[[str], None]) -> None:
        super().__init__()
        self._on_change = on_change

    def on_default_device_changed(self, flow, _flow_id, _role, _role_id, _default_device_id):
        if flow == "eRender":
            self._on_change("default audio device changed")


class CavaState(Enum):
    """Lifecycle states for one managed Cava process."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


class CavaProcessManager:
    """Own exactly one Cava process and its reader thread."""

    def __init__(
        self,
        config_path: str,
        bars_number: int,
        bit_format: str,
        on_samples: Callable[[list[float]], None],
        on_failure: Callable[[str, int], None] | None = None,
        command: list[str] | None = None,
    ) -> None:
        """Initialize process ownership without starting Cava.

        Args:
            config_path: Path used for the generated Cava configuration.
            bars_number: Number of values expected in each raw frame.
            bit_format: Cava raw output format, either ``8bit`` or ``16bit``.
            on_samples: Callback invoked for each complete normalized frame.
            on_failure: Callback invoked after an unexpected process failure.
            command: Optional executable command used by integration tests.
        """
        self._config_path = config_path
        self._bars_number = bars_number
        self._on_samples = on_samples
        self._on_failure = on_failure
        self._command = command or ["cava"]
        self._byte_type, self._byte_size, self._byte_norm = (
            ("H", 2, 65535) if bit_format == "16bit" else ("B", 1, 255)
        )
        self._state_lock = threading.RLock()
        self._transition_lock = threading.Lock()
        self._state = CavaState.STOPPED
        self._generation = 0
        self._process: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._stop_event: threading.Event | None = None
        self._shutdown = False
        self._last_frame_time: float | None = None

    @property
    def state(self) -> CavaState:
        """Return the current lifecycle state."""
        with self._state_lock:
            return self._state

    @property
    def generation(self) -> int:
        """Return the current process generation."""
        with self._state_lock:
            return self._generation

    @property
    def process_id(self) -> int | None:
        """Return the owned live process ID, if any."""
        with self._state_lock:
            return self._process.pid if self._process is not None and self._process.poll() is None else None

    def is_stalled(self, timeout: float) -> bool:
        """Return whether the running process has produced no frame in time.

        Args:
            timeout: Maximum allowed seconds without a complete frame.

        Returns:
            bool: ``True`` only for a currently running stalled generation.
        """
        with self._state_lock:
            return (
                self._state is CavaState.RUNNING
                and self._last_frame_time is not None
                and time.monotonic() - self._last_frame_time > timeout
            )

    def start(self, config_text: str) -> bool:
        """Start one reader worker unless one is already active.

        Args:
            config_text: Complete Cava configuration file contents.

        Returns:
            bool: ``True`` when a worker was created, otherwise ``False``.
        """
        with self._transition_lock, self._state_lock:
            if (
                self._shutdown
                or (self._thread is not None and self._thread.is_alive())
                or (self._process is not None and self._process.poll() is None)
                or self._state in {CavaState.STARTING, CavaState.RUNNING, CavaState.STOPPING}
            ):
                return False
            self._generation += 1
            generation = self._generation
            stop_event = threading.Event()
            self._stop_event = stop_event
            self._last_frame_time = None
            self._state = CavaState.STARTING
            thread = threading.Thread(
                target=self._run,
                args=(generation, stop_event, config_text),
                name=f"cava-{generation}",
                daemon=True,
            )
            self._thread = thread
            thread.start()
            return True

    def stop(self, *, shutdown: bool = False, reason: str = "requested stop") -> bool:
        """Stop and reap the owned process and worker.

        Args:
            shutdown: Permanently reject future starts when ``True``.
            reason: Lifecycle reason included in diagnostic logs.

        Returns:
            bool: ``True`` only when both process and worker have exited.
        """
        with self._transition_lock:
            with self._state_lock:
                self._shutdown = self._shutdown or shutdown
                generation = self._generation
                stop_event = self._stop_event
                process = self._process
                thread = self._thread
                if self._state is not CavaState.STOPPED:
                    self._state = CavaState.STOPPING
                if stop_event is not None:
                    stop_event.set()

            process_stopped = True
            if process is not None:
                logging.debug("Stopping Cava generation=%d PID=%d reason=%s", generation, process.pid, reason)
                process_stopped = self._terminate_process(process, generation, reason)
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=3)
            worker_stopped = thread is None or not thread.is_alive()
            if not worker_stopped:
                logging.error("Cava worker generation=%d failed to exit", generation)

            with self._state_lock:
                if worker_stopped and self._thread is thread:
                    self._thread = None
                if process_stopped and self._process is process:
                    self._process = None
                stopped = worker_stopped and process_stopped
                if stopped:
                    self._stop_event = None
                    self._state = CavaState.STOPPED
                else:
                    self._state = CavaState.STOPPING
                return stopped

    @staticmethod
    def _terminate_process(process: subprocess.Popen[bytes], generation: int, reason: str) -> bool:
        """Terminate and reap a process using bounded waits.

        Args:
            process: Owned Cava child process.
            generation: Lifecycle generation used in diagnostics.
            reason: Lifecycle reason used in diagnostics.

        Returns:
            bool: ``True`` when the child has exited and was reaped.
        """
        stopped = process.poll() is not None
        if process.poll() is None:
            try:
                logging.debug("Terminating Cava generation=%d PID=%d reason=%s", generation, process.pid, reason)
                process.terminate()
                process.wait(timeout=2)
                stopped = True
            except (OSError, subprocess.TimeoutExpired):
                logging.warning("Killing Cava generation=%d PID=%d after terminate failure", generation, process.pid)
                try:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=2)
                    stopped = True
                except (OSError, subprocess.TimeoutExpired):
                    logging.exception("Failed to kill Cava generation=%d PID=%d", generation, process.pid)
                    stopped = False
        if process.stdout is not None:
            try:
                process.stdout.close()
            except (OSError, ValueError):
                pass
        return stopped

    def _run(self, generation: int, stop_event: threading.Event, config_text: str) -> None:
        process: subprocess.Popen[bytes] | None = None
        stderr_file = tempfile.TemporaryFile()
        failure_reason = "stdout EOF"
        try:
            with open(self._config_path, "w") as config_file:
                config_file.write(config_text)

            if stop_event.is_set():
                return
            process = subprocess.Popen(
                [*self._command, "-p", self._config_path],
                stdout=subprocess.PIPE,
                stderr=stderr_file,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            with self._state_lock:
                if generation != self._generation or stop_event.is_set():
                    stale = True
                else:
                    stale = False
                    self._process = process
                    self._state = CavaState.RUNNING
                    self._last_frame_time = time.monotonic()
            if stale:
                self._terminate_process(process, generation, "stale generation")
                return
            logging.debug("Cava generation=%d PID=%d started", generation, process.pid)

            chunk = self._byte_size * self._bars_number
            frame_format = self._byte_type * self._bars_number
            while not stop_event.is_set():
                if process.stdout is None:
                    break
                data = process.stdout.read(chunk)
                if len(data) < chunk:
                    failure_reason = f"stdout EOF (exit={process.poll()})"
                    break
                with self._state_lock:
                    if generation != self._generation or stop_event.is_set():
                        break
                    self._last_frame_time = time.monotonic()
                samples = [value / self._byte_norm for value in struct.unpack(frame_format, data)]
                self._on_samples(samples)
        except Exception as error:
            failure_reason = f"worker error: {error}"
            logging.exception("Error running Cava generation=%d PID=%s", generation, getattr(process, "pid", None))
        finally:
            process_stopped = True
            if process is not None:
                process_stopped = self._terminate_process(process, generation, failure_reason)
            try:
                stderr_file.flush()
                stderr_file.seek(max(0, stderr_file.tell() - 4096))
                stderr_tail = stderr_file.read().decode(errors="replace")
                stderr_tail = " | ".join(stderr_tail.splitlines()[-5:])
            except (OSError, ValueError):
                stderr_tail = ""
            if stderr_tail:
                logging.error(
                    "Cava generation=%d PID=%s stderr: %s",
                    generation,
                    getattr(process, "pid", None),
                    stderr_tail,
                )
            stderr_file.close()
            try:
                os.unlink(self._config_path)
            except FileNotFoundError:
                pass
            except OSError:
                logging.exception("Failed to remove Cava config %s", self._config_path)
            failure_callback = None
            with self._state_lock:
                if generation == self._generation:
                    if process_stopped and self._process is process:
                        self._process = None
                    elif not process_stopped and process is not None:
                        self._process = process
                    if stop_event.is_set():
                        self._state = CavaState.STOPPED if process_stopped else CavaState.STOPPING
                    else:
                        self._state = CavaState.FAILED
                    if process_stopped and not stop_event.is_set() and not self._shutdown:
                        failure_callback = self._on_failure
            if failure_callback is not None:
                logging.warning(
                    "Cava generation=%d PID=%s failed: %s",
                    generation,
                    getattr(process, "pid", None),
                    failure_reason,
                )
                failure_callback(failure_reason, generation)
            with self._state_lock:
                if generation == self._generation and self._thread is threading.current_thread():
                    self._thread = None


def _make_cava_cleanup(manager, app, system_event_filter, audio_device_enumerator, audio_device_callback):
    cleaned = False

    def cleanup(*_args) -> None:
        nonlocal cleaned
        if cleaned:
            return
        cleaned = True
        atexit.unregister(cleanup)
        manager.stop(shutdown=True, reason="widget disposal")
        if app is not None and system_event_filter is not None:
            app.removeNativeEventFilter(system_event_filter)
        if audio_device_enumerator is not None and audio_device_callback is not None:
            try:
                audio_device_enumerator.UnregisterEndpointNotificationCallback(audio_device_callback)
            except Exception:
                logging.warning("Unable to unregister default audio device monitor", exc_info=True)

    return cleanup


class CavaBar(QFrame):
    _dpr: float | None
    _cava_widget: CavaWidget

    def __init__(self, cava_widget: CavaWidget) -> None:
        super().__init__()
        self._dpr = None
        self._cava_widget = cava_widget
        self.setFixedHeight(self._cava_widget.config.bar_height)
        self.setFixedWidth(
            self._cava_widget.config.bars_number
            * (
                self._cava_widget.config.bar_width
                + (
                    self._cava_widget.config.bar_spacing
                    if self._cava_widget.config.bar_type == "bars_mirrored"
                    or self._cava_widget.config.bar_type == "bars"
                    else 0
                )
            )
        )
        self.setContentsMargins(0, 0, 0, 0)

    def _device_pixel_ratio(self, painter: QPainter) -> float:
        """Return device pixel ratio for the painter's device."""
        if self._dpr is not None:
            return self._dpr

        try:
            dev = painter.device()
            if dev:
                dpr = float(dev.devicePixelRatioF())
            else:
                dpr = 1.0
        except Exception:
            dpr = 1.0

        self._dpr = dpr if dpr > 0 else 1.0
        return self._dpr

    def _get_fade_opacity(self, x_position: float) -> float:
        """Calculate opacity based on position for edge fade effect."""
        fade_left = self._cava_widget._edge_fade_left
        fade_right = self._cava_widget._edge_fade_right

        if fade_left <= 0 and fade_right <= 0:
            return 1.0

        widget_width = self.width()

        if fade_left > 0 and fade_right > 0:
            # Both sides have fade - cap each to half width to prevent overlap
            max_fade_width = widget_width / 2
            effective_fade_left = min(fade_left, max_fade_width)
            effective_fade_right = min(fade_right, max_fade_width)
        else:
            # Only one side has fade - allow it to use full width if needed
            effective_fade_left = min(fade_left, widget_width) if fade_left > 0 else 0
            effective_fade_right = min(fade_right, widget_width) if fade_right > 0 else 0

        # Left edge fade (0 to effective_fade_left)
        if effective_fade_left > 0 and x_position <= effective_fade_left:
            return max(0.0, x_position / effective_fade_left)

        # Right edge fade (widget_width - effective_fade_right to widget_width)
        elif effective_fade_right > 0 and x_position >= widget_width - effective_fade_right:
            return max(0.0, (widget_width - x_position) / effective_fade_right)

        # Middle area - full opacity
        return 1.0

    def paintEvent(self, event) -> None:
        """Draw the cava bars according to the selected style."""
        painter = QPainter(self)

        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        except Exception:
            pass

        if self._cava_widget.config.bar_type == "bars_mirrored":
            self.draw_bars_mirrored(painter)
        elif self._cava_widget.config.bar_type == "waves":
            self.draw_waves(painter)
        elif self._cava_widget.config.bar_type == "waves_mirrored":
            self.draw_waves_mirrored(painter)
        else:
            self.draw_bars(painter)

    def draw_bars(self, painter: QPainter) -> None:
        """Draw traditional bar visualization"""
        dpr = self._device_pixel_ratio(painter)

        bar_w_px = max(1, round(self._cava_widget.config.bar_width * dpr))
        bar_s_px = max(0, round(self._cava_widget.config.bar_spacing * dpr))
        left_margin_px = round((self._cava_widget.config.bar_spacing / 2.0) * dpr)

        for i, sample in enumerate(self._cava_widget.samples):
            min_height_logical = float(self._cava_widget.config.min_bar_height) / dpr
            computed_height = sample * float(self._cava_widget.config.bar_height)
            height = max(min_height_logical, computed_height)
            if height > 0.0:
                x_px = left_margin_px + i * (bar_w_px + bar_s_px)
                y_px = max(0, round((float(self._cava_widget.config.bar_height) - height) * dpr))
                h_px = max(1, round(height * dpr))

                rx = x_px / dpr
                ry = y_px / dpr
                rw = bar_w_px / dpr
                rh = h_px / dpr

                if self._cava_widget.config.gradient == 1 and self._cava_widget.colors:
                    gradient = QLinearGradient(0, 1, 0, 0)
                    gradient.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode)
                    stop_step = 1.0 / (len(self._cava_widget.colors) - 1)
                    for idx, color in enumerate(self._cava_widget.colors):
                        gradient.setColorAt(idx * stop_step, color)

                    if self._cava_widget._edge_fade_left > 0 or self._cava_widget._edge_fade_right > 0:
                        fade_opacity = self._get_fade_opacity(rx + rw / 2)
                        painter.setOpacity(fade_opacity)

                    painter.fillRect(QRectF(rx, ry, rw, rh), gradient)
                else:
                    if self._cava_widget._edge_fade_left > 0 or self._cava_widget._edge_fade_right > 0:
                        fade_opacity = self._get_fade_opacity(rx + rw / 2)
                        painter.setOpacity(fade_opacity)

                    painter.fillRect(QRectF(rx, ry, rw, rh), self._cava_widget.foreground_color)

    def draw_bars_mirrored(self, painter: QPainter) -> None:
        """Draw mirrored bar visualization"""
        if not self._cava_widget.samples:
            return
        dpr = self._device_pixel_ratio(painter)
        width = self.width()
        height = float(self._cava_widget.config.bar_height)
        samples = self._cava_widget.samples
        center_y = height / 2.0

        band_w_px = max(1, round(self._cava_widget.config.bar_width * dpr))
        band_s_px = max(0, round(self._cava_widget.config.bar_spacing * dpr))

        total_w_px = max(1, round(float(width) * dpr))
        bars_count = len(samples)
        total_bars_width_px = bars_count * band_w_px + max(0, (bars_count - 1)) * band_s_px
        left_margin_px = max(0, (total_w_px - total_bars_width_px) // 2)

        # Precompute brushes (single gradient instance reused)
        if self._cava_widget.config.gradient == 1 and self._cava_widget.colors:
            stop_step = 1.0 / (len(self._cava_widget.colors) - 1)
            gradient_upper = QLinearGradient(0, 1, 0, 0)
            gradient_upper.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode)
            gradient_lower = QLinearGradient(0, 0, 0, 1)
            gradient_lower.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode)
            for idx, color in enumerate(self._cava_widget.colors):
                gradient_upper.setColorAt(idx * stop_step, color)
                gradient_lower.setColorAt(idx * stop_step, color)
            brush_upper = gradient_upper
            brush_lower = gradient_lower
        else:
            brush_upper = brush_lower = self._cava_widget.foreground_color

        for i, sample in enumerate(samples):
            ux_px = left_margin_px + i * (band_w_px + band_s_px)

            min_height_logical = float(self._cava_widget.config.min_bar_height) / dpr
            full_height_logical = max(min_height_logical, sample * float(self._cava_widget.config.bar_height))

            full_h_px = round(full_height_logical * dpr)
            if full_h_px <= 0:
                continue

            up_px = full_h_px // 2
            down_px = full_h_px - up_px

            uy_px = max(0, round(center_y * dpr) - up_px)
            if up_px > 0:
                if self._cava_widget._edge_fade_left > 0 or self._cava_widget._edge_fade_right > 0:
                    fade_opacity = self._get_fade_opacity(ux_px / dpr + (band_w_px / dpr) / 2)
                    painter.setOpacity(fade_opacity)

                painter.fillRect(QRectF(ux_px / dpr, uy_px / dpr, band_w_px / dpr, up_px / dpr), brush_upper)

            ly_px = round(center_y * dpr)
            if down_px > 0:
                max_h_px = round(height * dpr)
                if ly_px + down_px > max_h_px:
                    down_px = max(0, max_h_px - ly_px)
                if down_px > 0:
                    if self._cava_widget._edge_fade_left > 0 or self._cava_widget._edge_fade_right > 0:
                        fade_opacity = self._get_fade_opacity(ux_px / dpr + (band_w_px / dpr) / 2)
                        painter.setOpacity(fade_opacity)

                    painter.fillRect(QRectF(ux_px / dpr, ly_px / dpr, band_w_px / dpr, down_px / dpr), brush_lower)

    def draw_waves(self, painter: QPainter, radius: int = 1) -> None:
        """Draw wave visualization."""
        if not self._cava_widget.samples:
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        dpr = self._device_pixel_ratio(painter)

        height = float(self._cava_widget.config.bar_height)
        samples = self._cava_widget.samples

        if self._cava_widget.config.gradient == 1 and self._cava_widget.colors:
            stop_step = 1.0 / (len(self._cava_widget.colors) - 1)
            gradient = QLinearGradient(0, 1, 0, 0)
            gradient.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode)
            for idx, color in enumerate(self._cava_widget.colors):
                gradient.setColorAt(idx * stop_step, color)
            brush = gradient
        else:
            brush = self._cava_widget.foreground_color

        n = len(samples)
        if n == 0:
            return

        def smooth(i: int) -> float:
            start = max(0, i - radius)
            end = min(n, i + radius + 1)
            window = samples[start:end]
            return sum(window) / len(window) if window else 0.0

        widget_w = float(self.width())
        step = widget_w / max(1, n)
        points = []
        min_h_logical = float(self._cava_widget.config.min_bar_height) / dpr
        for i in range(n):
            cx = i * step + step / 2.0
            val = max(min_h_logical, smooth(i) * height)
            top = max(0.0, height - val)
            points.append(QPointF(cx, top))

        path = QPainterPath()
        bottom = height
        path.moveTo(points[0].x(), bottom)
        path.lineTo(points[0])
        for p in points[1:]:
            path.lineTo(p)
        path.lineTo(points[-1].x(), bottom)
        path.closeSubpath()

        if self._cava_widget._edge_fade_left > 0 or self._cava_widget._edge_fade_right > 0:
            # Draw wave in strips with varying opacity
            widget_width = self.width()
            widget_height = int(height)  # Convert to int for setClipRect
            strip_width = 1  # 1 pixel wide strips for smooth fade

            for x in range(int(widget_width)):
                opacity = self._get_fade_opacity(x)
                if opacity > 0:
                    painter.setOpacity(opacity)
                    # Create a clip rect for this strip
                    painter.setClipRect(x, 0, strip_width, widget_height)
                    painter.fillPath(path, brush)

            # Reset clipping and opacity
            painter.setClipRect(0, 0, int(widget_width), widget_height)
            painter.setOpacity(1.0)
        else:
            # No fade effect - use simple fillPath for efficiency
            painter.fillPath(path, brush)

    def draw_waves_mirrored(self, painter: QPainter, radius: int = 1) -> None:
        """Draw a mirrored wave visualization."""
        if not self._cava_widget.samples:
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        dpr = self._device_pixel_ratio(painter)
        height = float(self._cava_widget.config.bar_height)
        samples = self._cava_widget.samples
        center_y = height / 2.0

        if self._cava_widget.config.gradient == 1 and self._cava_widget.colors:
            colors_len = len(self._cava_widget.colors)
            stop_step = 1.0 / (colors_len - 1) if colors_len > 1 else 1.0
            gradient = QLinearGradient(0, 0, 0, 1)
            gradient.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode)
            for idx, color in enumerate(self._cava_widget.colors):
                s = idx * stop_step
                pos_top = max(0.0, 0.5 - s * 0.5)
                pos_bottom = min(1.0, 0.5 + s * 0.5)
                gradient.setColorAt(pos_top, color)
                gradient.setColorAt(pos_bottom, color)
            fill_brush = gradient
        else:
            fill_brush = self._cava_widget.foreground_color

        n = len(samples)
        if n == 0:
            return

        def smooth(i: int) -> float:
            start = max(0, i - radius)
            end = min(n, i + radius + 1)
            window = samples[start:end]
            return sum(window) / len(window) if window else 0.0

        widget_w = float(self.width())
        step = widget_w / max(1, n)

        top_points = []
        bottom_points = []
        min_h_logical = float(self._cava_widget.config.min_bar_height) / dpr
        for i in range(n):
            cx = i * step + step / 2.0
            val = max(min_h_logical, smooth(i) * height / 2.0)
            top_y = max(0.0, center_y - val)
            bottom_y = min(height, center_y + val)
            top_points.append(QPointF(cx, top_y))
            bottom_points.append(QPointF(cx, bottom_y))

        combined = QPainterPath()
        combined.moveTo(top_points[0].x(), center_y)
        combined.lineTo(top_points[0])
        for p in top_points[1:]:
            combined.lineTo(p)
        for p in reversed(bottom_points):
            combined.lineTo(p)
        combined.closeSubpath()

        if self._cava_widget._edge_fade_left > 0 or self._cava_widget._edge_fade_right > 0:
            # Draw wave in strips with varying opacity
            widget_width = self.width()
            widget_height = int(height)  # Convert to int for setClipRect
            strip_width = 1  # 1 pixel wide strips for smooth fade

            for x in range(int(widget_width)):
                opacity = self._get_fade_opacity(x)
                if opacity > 0:
                    painter.setOpacity(opacity)
                    # Create a clip rect for this strip
                    painter.setClipRect(x, 0, strip_width, widget_height)
                    painter.fillPath(combined, fill_brush)

            # Reset clipping and opacity
            painter.setClipRect(0, 0, int(widget_width), widget_height)
            painter.setOpacity(1.0)
        else:
            # No fade effect - use simple fillPath for efficiency
            painter.fillPath(combined, fill_brush)


class CavaWidget(BaseWidget):
    validation_schema = CavaConfig
    samplesUpdated = pyqtSignal(list)
    restartRequested = pyqtSignal(str)
    _instance_counter = 0  # Class variable to track instances

    _edge_fade_left: int
    _edge_fade_right: int
    _manager: CavaProcessManager
    foreground_color: QColor
    colors: list[QColor]
    samples: list[float]
    _instance_id: int
    _hide_cava_widget: bool
    _hide_timer: QTimer | None
    _restart_timer: QTimer
    _watchdog_timer: QTimer
    _bar_frame: CavaBar

    def __init__(self, config: CavaConfig):
        super().__init__(class_name=f"cava-widget {config.class_name}")
        self.config = config
        # Assign unique instance ID
        CavaWidget._instance_counter += 1
        self._instance_id = CavaWidget._instance_counter

        self._hide_timer = None
        self._hide_cava_widget = True
        self._shutdown = False
        self._restart_allowed = True
        self._restart_failures = 0
        self._system_event_filter = None
        self._audio_device_enumerator = None
        self._audio_device_callback = None

        # Parse edge_fade parameter - support both integer and [left, right] formats
        if isinstance(self.config.edge_fade, list) and len(self.config.edge_fade) == 2:
            self._edge_fade_left = self.config.edge_fade[0]
            self._edge_fade_right = self.config.edge_fade[1]
        else:
            # Single value applies to both sides
            self._edge_fade_left = self.config.edge_fade
            self._edge_fade_right = self.config.edge_fade

        # Set up samples and colors
        self.samples = [0] * self.config.bars_number
        self.colors = []

        # Construct container layout
        self._init_container()

        # Check if cava is available
        cava_executable = shutil.which("cava")
        if cava_executable is None:
            error_label = QLabel("未安装 Cava")
            self._widget_container_layout.addWidget(error_label)
            return
        cava_version = _read_cava_version(cava_executable)
        if cava_version is not None and cava_version < _MIN_CAVA_VERSION:
            required = ".".join(map(str, _MIN_CAVA_VERSION))
            error_label = QLabel(f"Cava 版本过低（至少需要 {required}）")
            self._widget_container_layout.addWidget(error_label)
            logging.error("Cava %s is unsupported; version %s or newer is required", cava_version, required)
            return

        # Add the custom bar frame
        self._bar_frame = CavaBar(self)
        self._widget_container_layout.addWidget(self._bar_frame)

        self._manager = CavaProcessManager(
            app_data_path(f"yasb_cava_config_{self._instance_id}"),
            self.config.bars_number,
            self.config.output_bit_format,
            self.samplesUpdated.emit,
            lambda reason, _generation: self.restartRequested.emit(reason),
            [cava_executable],
        )
        self._restart_timer = QTimer(self)
        self._restart_timer.setSingleShot(True)
        self._restart_timer.timeout.connect(self.start_cava)
        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.setInterval(250)
        self._watchdog_timer.timeout.connect(self._check_cava_output)
        self._watchdog_timer.start()

        self.register_callback("reload_cava", self._reload_cava)

        self.callback_left = self.config.callbacks.on_left
        self.callback_right = self.config.callbacks.on_right
        self.callback_middle = self.config.callbacks.on_middle

        # Connect signal and start audio processing
        self.samplesUpdated.connect(self.on_samples_updated)
        self.restartRequested.connect(self._schedule_restart)
        self._install_system_event_handlers()
        self._cleanup_resources = _make_cava_cleanup(
            self._manager,
            QApplication.instance(),
            self._system_event_filter,
            self._audio_device_enumerator,
            self._audio_device_callback,
        )
        self.destroyed.connect(self._cleanup_resources)
        self.start_cava()

        # Set up auto-hide timer for silence
        if self.config.hide_empty and self.config.sleep_timer > 0:
            self.hide()
            self._hide_timer = QTimer(self)
            self._hide_timer.setInterval(self.config.sleep_timer * 1000)
            self._hide_timer.timeout.connect(self.hide_bar_frame)
        else:
            self._hide_timer = None

        if QApplication.instance():
            QApplication.instance().aboutToQuit.connect(self.shutdown)
        atexit.register(self._cleanup_resources)

    def _reload_cava(self):
        """Stop current cava process and start a new one"""
        if self._invoke_on_widget_thread("_reload_cava_on_widget_thread"):
            return
        self._reload_cava_on_widget_thread()

    @pyqtSlot()
    def _reload_cava_on_widget_thread(self) -> None:
        try:
            if not self._stop_cava_on_widget_thread():
                logging.error("Cava reload cancelled because the previous worker did not exit")
                return
            self._restart_failures = 0
            self.samples = [0] * self.config.bars_number
            self._restart_timer.stop()
            self._restart_timer.start(500)

            if self.config.hide_empty and self.config.sleep_timer > 0:
                if self._hide_timer:
                    self._hide_timer.stop()
                self._hide_cava_widget = True
                self.show()
        except Exception as e:
            logging.error("Error reloading cava: %s", e)

    def stop_cava(self) -> bool:
        if self._invoke_on_widget_thread("_stop_cava_on_widget_thread"):
            return self._manager.state is CavaState.STOPPED
        return self._stop_cava_on_widget_thread()

    @pyqtSlot()
    def _stop_cava_on_widget_thread(self) -> bool:
        self._restart_allowed = False
        if hasattr(self, "_restart_timer"):
            self._restart_timer.stop()
        self.colors.clear()
        if hasattr(self, "_manager"):
            return self._manager.stop(reason="requested stop")
        return True

    def shutdown(self, *_args) -> None:
        """Permanently stop Cava during widget or application disposal."""
        if self._shutdown:
            return
        self._shutdown = True
        self._restart_allowed = False
        if hasattr(self, "_restart_timer"):
            self._restart_timer.stop()
        if hasattr(self, "_watchdog_timer"):
            self._watchdog_timer.stop()
        if hasattr(self, "_cleanup_resources"):
            self._cleanup_resources()
        self._system_event_filter = None
        self._audio_device_enumerator = None
        self._audio_device_callback = None

    def closeEvent(self, event) -> None:
        """Release process and event resources before the widget closes."""
        self.shutdown()
        super().closeEvent(event)

    def _invoke_on_widget_thread(self, method_name: str) -> bool:
        if QThread.currentThread() == self.thread():
            return False
        QMetaObject.invokeMethod(self, method_name, Qt.ConnectionType.BlockingQueuedConnection)
        return True

    def _install_system_event_handlers(self) -> None:
        app = QApplication.instance()
        if app is not None:
            self._system_event_filter = _CavaSystemEventFilter(self.restartRequested.emit)
            app.installNativeEventFilter(self._system_event_filter)
        if self.config.source != "auto":
            return
        try:
            self._audio_device_callback = _CavaAudioDeviceCallback(self.restartRequested.emit)
            self._audio_device_enumerator = AudioUtilities.GetDeviceEnumerator()
            self._audio_device_enumerator.RegisterEndpointNotificationCallback(self._audio_device_callback)
        except Exception:
            self._audio_device_callback = None
            self._audio_device_enumerator = None
            logging.warning("Unable to monitor default audio device changes", exc_info=True)

    def _schedule_restart(self, reason: str) -> None:
        if self._shutdown or not self._restart_allowed or self._restart_timer.isActive():
            return
        if not self._manager.stop(reason=reason):
            logging.error("Cava restart cancelled because the previous worker did not exit")
            return
        delay = min(500 * (2**self._restart_failures), 10_000)
        self._restart_failures += 1
        logging.warning("Restarting Cava in %d ms: %s", delay, reason)
        self._restart_timer.start(delay)

    def _check_cava_output(self) -> None:
        if self.config.sleep_timer == 0 and self._manager.is_stalled(self.config.output_timeout):
            self._schedule_restart("stdout stalled")

    def initialize_colors(self) -> None:
        self.colors.clear()
        self.foreground_color = QColor(self.config.foreground)
        if self.config.gradient == 1:
            for color_str in [self.config.gradient_color_1, self.config.gradient_color_2, self.config.gradient_color_3]:
                if not color_str:
                    continue
                try:
                    c = QColor(color_str)
                    if not c.isValid():
                        logging.error("Invalid gradient color specified: %s", color_str)
                    self.colors.append(c)
                except Exception as e:
                    logging.error("Error setting gradient color '%s': %s", color_str, e)

    def on_samples_updated(self, new_samples: list) -> None:
        self._restart_failures = 0
        try:
            self.samples = new_samples
        except Exception:
            return
        if any(val != 0 for val in new_samples):
            try:
                if self.config.hide_empty and self.config.sleep_timer > 0:
                    if self._hide_cava_widget:
                        self.show()
                        self._hide_cava_widget = False
                    if self._hide_timer:
                        self._hide_timer.start()
                self._bar_frame.update()
            except Exception as e:
                logging.error("Error updating cava widget: %s", e)

    def hide_bar_frame(self) -> None:
        self.hide()
        self._hide_cava_widget = True

    def start_cava(self) -> None:
        if self._invoke_on_widget_thread("_start_cava_on_widget_thread"):
            return
        self._start_cava_on_widget_thread()

    @pyqtSlot()
    def _start_cava_on_widget_thread(self) -> None:
        if self._shutdown:
            return
        self._restart_allowed = True
        # Build configuration file, temp config file will be created in YASB TEMP directory
        lines: list[str] = []
        lines.append("# Cava config auto-generated by YASB")
        lines.append("[general]")
        lines.append(f"bars = {self.config.bars_number}")
        lines.append(f"bar_spacing = {self.config.bar_spacing}")
        lines.append(f"bar_width = {self.config.bar_width}")
        lines.append(f"sleep_timer = {self.config.sleep_timer}")
        lines.append(f"sensitivity = {self.config.sensitivity}")
        lines.append(f"lower_cutoff_freq = {self.config.lower_cutoff_freq}")
        lines.append(f"higher_cutoff_freq = {self.config.higher_cutoff_freq}")
        lines.append(f"framerate = {self.config.framerate}")
        lines.append("")
        lines.append("[input]")
        lines.append(f"source = {self.config.source}")
        lines.append("")
        lines.append("[output]")
        lines.append("method = raw")
        lines.append(f"bit_format = {self.config.output_bit_format}")
        lines.append(f"orientation = {self.config.orientation}")
        lines.append(f"channels = {self.config.channels}")
        lines.append(f"mono_option = {self.config.mono_option}")
        lines.append(f"reverse = {self.config.reverse}")
        lines.append(f"waveform = {self.config.waveform}")
        lines.append("")
        lines.append("[color]")
        lines.append(f"foreground = '{self.config.foreground}'")
        lines.append(f"gradient = {self.config.gradient}")
        if self.config.gradient_color_1:
            lines.append(f"gradient_color_1 = '{self.config.gradient_color_1}'")
        if self.config.gradient_color_2:
            lines.append(f"gradient_color_2 = '{self.config.gradient_color_2}'")
        if self.config.gradient_color_3:
            lines.append(f"gradient_color_3 = '{self.config.gradient_color_3}'")
        lines.append("")
        lines.append("[smoothing]")
        lines.append(f"monstercat = {self.config.monstercat}")
        lines.append(f"waves = {self.config.waves}")
        lines.append(f"noise_reduction = {int(self.config.noise_reduction)}")

        config_template = "\n".join(lines) + "\n"

        self.initialize_colors()

        self._manager.start(config_template)
