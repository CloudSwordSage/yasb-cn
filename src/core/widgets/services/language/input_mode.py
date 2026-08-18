import ctypes
import logging
from ctypes import wintypes

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from core.widgets.services.language.mode import format_imm_probe, input_mode_key


logger = logging.getLogger("input_mode")
_WM_IME_CONTROL = 0x0283
_IMC_GETCONVERSIONMODE = 0x0001
_SMTO_ABORTIFHUNG = 0x0002


class InputModeMonitor(QObject):
    """Poll the foreground window's IMM32 conversion mode at a low frequency."""

    changed = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._imm32 = ctypes.WinDLL("imm32", use_last_error=True)
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._imm32.ImmGetDefaultIMEWnd.argtypes = [wintypes.HWND]
        self._imm32.ImmGetDefaultIMEWnd.restype = wintypes.HWND
        self._user32.SendMessageTimeoutW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self._user32.SendMessageTimeoutW.restype = wintypes.LPARAM
        self._mode: str | None = None
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(200)
        self._poll_timer.timeout.connect(self._poll)

    def start(self) -> None:
        """Start monitoring and emit the initial conversion mode."""
        self._poll()
        self._poll_timer.start()

    def close(self) -> None:
        """Stop the conversion-mode polling timer."""
        self._poll_timer.stop()

    def current(self) -> str:
        """Return the foreground window's current conversion-mode label key."""
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            logger.debug("input_mode: foreground window unavailable")
            return "unknown"
        ime_window = self._imm32.ImmGetDefaultIMEWnd(hwnd)
        if not ime_window:
            logger.debug("input_mode: ImmGetDefaultIMEWnd hwnd=%s unavailable", hwnd)
            return "unknown"
        result = ctypes.c_size_t()
        success = bool(
            self._user32.SendMessageTimeoutW(
                ime_window,
                _WM_IME_CONTROL,
                _IMC_GETCONVERSIONMODE,
                0,
                _SMTO_ABORTIFHUNG,
                100,
                ctypes.byref(result),
            )
        )
        value = result.value if success else None
        logger.debug("input_mode: hwnd=%s ime_hwnd=%s %s", hwnd, ime_window, format_imm_probe(success, value))
        return input_mode_key(value)

    def request_update(self, hwnd: int, event) -> None:
        """Read immediately after a foreground, focus, or IME event.

        Args:
            hwnd: Window handle supplied by WinEvent.
            event: WinEvent type supplied by the system listener.
        """
        logger.debug("input_mode: WinEvent event=%s hwnd=%s", event, hwnd)
        self._poll()

    def _poll(self) -> None:
        mode = self.current()
        if mode != self._mode:
            self._mode = mode
            logger.debug("input_mode: mode changed to %s", mode)
            self.changed.emit(mode)
