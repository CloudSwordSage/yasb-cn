import ctypes
import logging
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from core.utils.win32.bindings.kernel32 import (
    CancelIoEx,
    CloseHandle,
    CreateEvent,
    CreateFile,
    GetCurrentProcessId,
    GetOverlappedResult,
    ProcessIdToSessionId,
    ReadFileOverlapped,
    SetEvent,
    WaitForMultipleObjects,
)
from core.utils.win32.bindings.shell32 import ShellExecuteEx
from core.utils.win32.constants import (
    ERROR_ACCESS_DENIED,
    ERROR_CANCELLED,
    ERROR_FILE_NOT_FOUND,
    ERROR_IO_PENDING,
    ERROR_PIPE_BUSY,
    FILE_FLAG_OVERLAPPED,
    GENERIC_READ,
    INFINITE,
    INVALID_HANDLE_VALUE,
    OPEN_EXISTING,
    WAIT_OBJECT_0,
)
from core.utils.win32.structs import OVERLAPPED, SHELLEXECUTEINFO
from core.widgets.services.language.input_mode_helper import _user_sid
from core.widgets.services.language.mode import input_mode_pipe_name, mode_from_input_mode_code

logger = logging.getLogger("input_mode")


def _pipe_name() -> str:
    session_id = ProcessIdToSessionId(GetCurrentProcessId())
    if session_id is None:
        raise OSError(ctypes.get_last_error(), "ProcessIdToSessionId")
    return input_mode_pipe_name(_user_sid(), session_id)


class InputModeMonitor(QObject):
    """Receive conversion-mode updates from the elevated helper process."""

    changed = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._stop = threading.Event()
        self._stop_handle = CreateEvent(None, True, False, None)
        if not self._stop_handle:
            raise OSError(ctypes.get_last_error(), "CreateEventW")
        self._thread: threading.Thread | None = None
        self._last_launch = 0.0
        self._elevation_denied = False
        self._last_mode: str | None = None

    def start(self) -> None:
        """Connect to, or elevate and start, the input-mode helper."""
        if not self._stop.is_set() and (self._thread is None or not self._thread.is_alive()):
            self._thread = threading.Thread(target=self._read_loop, name="input-mode-pipe", daemon=True)
            self._thread.start()

    def close(self) -> None:
        """Stop the pipe reader; the helper exits after its idle grace period."""
        self._stop.set()
        if self._stop_handle:
            SetEvent(self._stop_handle)
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join()
        if self._stop_handle:
            CloseHandle(self._stop_handle)
            self._stop_handle = None

    def _launch_helper(self) -> None:
        if self._elevation_denied or time.monotonic() - self._last_launch < 3:
            return
        self._last_launch = time.monotonic()
        helper = Path(sys.executable).with_name("yasb-input-mode-helper.exe")
        file = str(helper) if getattr(sys, "frozen", False) else sys.executable
        parameters = None if getattr(sys, "frozen", False) else "-m core.widgets.services.language.input_mode_helper"
        directory = None if getattr(sys, "frozen", False) else str(Path(__file__).parents[4])
        info = SHELLEXECUTEINFO(
            cbSize=ctypes.sizeof(SHELLEXECUTEINFO),
            lpVerb="runas",
            lpFile=file,
            lpParameters=parameters,
            lpDirectory=directory,
            nShow=0,
        )
        if not ShellExecuteEx(ctypes.byref(info)):
            error = ctypes.get_last_error()
            self._elevation_denied = error == ERROR_CANCELLED
            logger.warning("input_mode: helper elevation failed (error=%s)", error)

    def _open_pipe(self) -> tuple[int | None, int]:
        handle = CreateFile(_pipe_name(), GENERIC_READ, 0, None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
        return (None, ctypes.get_last_error()) if handle == INVALID_HANDLE_VALUE else (handle, 0)

    def _read_pipe(self, handle: int) -> bytes | None:
        event = CreateEvent(None, True, False, None)
        if not event:
            logger.warning("input_mode: read event creation failed (error=%s)", ctypes.get_last_error())
            return None
        try:
            payload = ctypes.create_string_buffer(1)
            count = wintypes.DWORD()
            overlapped = OVERLAPPED(hEvent=event)
            if not ReadFileOverlapped(handle, payload, ctypes.byref(overlapped)):
                error = ctypes.get_last_error()
                if error != ERROR_IO_PENDING:
                    return None
                handles = (wintypes.HANDLE * 2)(self._stop_handle, event)
                wait = WaitForMultipleObjects(2, handles, False, INFINITE)
                if wait != WAIT_OBJECT_0 + 1:
                    CancelIoEx(handle, ctypes.byref(overlapped))
                    GetOverlappedResult(handle, ctypes.byref(overlapped), True)
                    return None
                success, _ = GetOverlappedResult(handle, ctypes.byref(overlapped), False)
                if not success:
                    return None
            return payload.raw if count.value == 1 else None
        finally:
            CloseHandle(event)

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            handle, error = self._open_pipe()
            if handle is None:
                if error == ERROR_FILE_NOT_FOUND:
                    self._launch_helper()
                elif error == ERROR_ACCESS_DENIED:
                    logger.error("input_mode: pipe access denied")
                elif error != ERROR_PIPE_BUSY:
                    logger.warning("input_mode: pipe connection failed (error=%s)", error)
                self._stop.wait(0.2)
                continue
            try:
                while not self._stop.is_set() and (payload := self._read_pipe(handle)) is not None:
                    if self._stop.is_set():
                        break
                    mode = mode_from_input_mode_code(payload)
                    if mode != self._last_mode:
                        self._last_mode = mode
                        self.changed.emit(mode)
            finally:
                CloseHandle(handle)
