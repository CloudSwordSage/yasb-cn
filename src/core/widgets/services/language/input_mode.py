import ctypes
import logging
from ctypes import wintypes

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from core.widgets.services.language.mode import format_imm_probe, input_mode_key


logger = logging.getLogger("input_mode")


class InputModeMonitor(QObject):
    """Read the foreground window's IMM32 conversion mode after WinEvents."""

    changed = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._imm32 = ctypes.WinDLL("imm32", use_last_error=True)
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._imm32.ImmGetContext.argtypes = [wintypes.HWND]
        self._imm32.ImmGetContext.restype = wintypes.HANDLE
        self._imm32.ImmGetConversionStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
        self._imm32.ImmGetConversionStatus.restype = wintypes.BOOL
        self._imm32.ImmReleaseContext.argtypes = [wintypes.HWND, wintypes.HANDLE]
        self._imm32.ImmReleaseContext.restype = wintypes.BOOL

    def current(self) -> str:
        """Return the foreground window's current conversion-mode label key."""
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            logger.debug("input_mode: foreground window unavailable")
            return "unknown"
        context = self._imm32.ImmGetContext(hwnd)
        if not context:
            logger.debug("input_mode: ImmGetContext hwnd=%s unavailable", hwnd)
            return "unknown"
        conversion = wintypes.DWORD()
        sentence = wintypes.DWORD()
        try:
            success = bool(self._imm32.ImmGetConversionStatus(context, ctypes.byref(conversion), ctypes.byref(sentence)))
        finally:
            self._imm32.ImmReleaseContext(hwnd, context)
        value = conversion.value if success else None
        logger.debug("input_mode: hwnd=%s %s", hwnd, format_imm_probe(success, value))
        return input_mode_key(value)

    def request_update(self, hwnd: int, event) -> None:
        """Read now and once more after the IME change has settled.

        Args:
            hwnd: Window handle supplied by WinEvent.
            event: WinEvent type supplied by the system listener.
        """
        logger.debug("input_mode: WinEvent event=%s hwnd=%s", event, hwnd)
        self._emit_current()
        QTimer.singleShot(75, self._emit_current)

    def _emit_current(self) -> None:
        self.changed.emit(self.current())
