import ctypes
import logging
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from core.widgets.services.language.input_mode_helper import _bind_win32, _user_sid
from core.widgets.services.language.mode import input_mode_pipe_name, mode_from_input_mode_code

logger = logging.getLogger("input_mode")
_GENERIC_READ = 0x80000000
_OPEN_EXISTING = 3
_ERROR_FILE_NOT_FOUND = 2
_ERROR_PIPE_BUSY = 231
_ERROR_ACCESS_DENIED = 5
_ERROR_CANCELLED = 1223
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def _pipe_name() -> str:
    kernel32, _user32, _imm32, advapi32 = _bind_win32()
    session_id = wintypes.DWORD()
    if not kernel32.ProcessIdToSessionId(kernel32.GetCurrentProcessId(), ctypes.byref(session_id)):
        raise OSError(ctypes.get_last_error(), "ProcessIdToSessionId")
    return input_mode_pipe_name(_user_sid(kernel32, advapi32), session_id.value)


class InputModeMonitor(QObject):
    """Receive conversion-mode updates from the elevated helper process."""

    changed = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self._kernel32.CreateFileW.restype = wintypes.HANDLE
        self._kernel32.ReadFile.restype = wintypes.BOOL
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._shell32.ShellExecuteExW.restype = wintypes.BOOL
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_launch = 0.0
        self._elevation_denied = False
        self._last_mode: str | None = None

    def start(self) -> None:
        """Connect to, or elevate and start, the input-mode helper."""
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._read_loop, name="input-mode-pipe", daemon=True)
            self._thread.start()

    def close(self) -> None:
        """Stop the pipe reader; the helper exits after its idle grace period."""
        self._stop.set()

    def _launch_helper(self) -> None:
        if self._elevation_denied or time.monotonic() - self._last_launch < 3:
            return
        self._last_launch = time.monotonic()
        helper = Path(sys.executable).with_name("yasb-input-mode-helper.exe")
        file = str(helper) if getattr(sys, "frozen", False) else sys.executable
        parameters = None if getattr(sys, "frozen", False) else "-m core.widgets.services.language.input_mode_helper"
        directory = None if getattr(sys, "frozen", False) else str(Path(__file__).parents[4])
        info = _ShellExecuteInfo(
            cbSize=ctypes.sizeof(_ShellExecuteInfo),
            lpVerb="runas",
            lpFile=file,
            lpParameters=parameters,
            lpDirectory=directory,
            nShow=0,
        )
        if not self._shell32.ShellExecuteExW(ctypes.byref(info)):
            error = ctypes.get_last_error()
            self._elevation_denied = error == _ERROR_CANCELLED
            logger.warning("input_mode: helper elevation failed (error=%s)", error)

    def _open_pipe(self) -> tuple[int | None, int]:
        handle = self._kernel32.CreateFileW(_pipe_name(), _GENERIC_READ, 0, None, _OPEN_EXISTING, 0, None)
        return (None, ctypes.get_last_error()) if handle == _INVALID_HANDLE_VALUE else (handle, 0)

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            handle, error = self._open_pipe()
            if handle is None:
                if error == _ERROR_FILE_NOT_FOUND:
                    self._launch_helper()
                elif error == _ERROR_ACCESS_DENIED:
                    logger.error("input_mode: pipe access denied")
                elif error != _ERROR_PIPE_BUSY:
                    logger.warning("input_mode: pipe connection failed (error=%s)", error)
                self._stop.wait(0.2)
                continue
            try:
                payload = ctypes.create_string_buffer(1)
                count = wintypes.DWORD()
                while not self._stop.is_set() and self._kernel32.ReadFile(
                    handle, payload, 1, ctypes.byref(count), None
                ):
                    if count.value == 1:
                        mode = mode_from_input_mode_code(payload.raw)
                        if mode != self._last_mode:
                            self._last_mode = mode
                            self.changed.emit(mode)
            finally:
                self._kernel32.CloseHandle(handle)
