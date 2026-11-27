import ctypes
import logging
import threading
import time
from ctypes import wintypes

from core.utils.win32.bindings.advapi32 import get_current_user_sid, security_descriptor_from_sddl
from core.utils.win32.bindings.imm32 import ImmGetDefaultIMEWnd
from core.utils.win32.bindings.kernel32 import (
    CloseHandle,
    ConnectNamedPipe,
    CreateNamedPipe,
    DisconnectNamedPipe,
    GetCurrentProcessId,
    LocalFree,
    ProcessIdToSessionId,
    WriteFile,
)
from core.utils.win32.bindings.user32 import (
    GetForegroundWindow,
    GetGUIThreadInfo,
    GetWindowThreadProcessId,
    SendMessageTimeoutW,
    SetWinEventHook,
    UnhookWinEvent,
    user32,
)
from core.utils.win32.constants import (
    ERROR_BROKEN_PIPE,
    ERROR_NO_DATA,
    ERROR_PIPE_CONNECTED,
    ERROR_PIPE_LISTENING,
    FILE_FLAG_FIRST_PIPE_INSTANCE,
    IMC_GETCONVERSIONMODE,
    INVALID_HANDLE_VALUE,
    PIPE_ACCESS_OUTBOUND,
    PIPE_NOWAIT,
    PIPE_READMODE_BYTE,
    PIPE_REJECT_REMOTE_CLIENTS,
    PIPE_TYPE_BYTE,
    SMTO_ABORTIFHUNG,
    WINEVENT_OUTOFCONTEXT,
    WM_IME_CONTROL,
)
from core.utils.win32.structs import GUITHREADINFO, SECURITY_ATTRIBUTES
from core.widgets.services.language.mode import input_mode_code, input_mode_key, input_mode_pipe_name, input_mode_target

_HEARTBEAT_SECONDS = 1.0
_EVENTS = (3, 0x8005, 0x8029)


def _user_sid() -> str:
    sid = get_current_user_sid()
    if sid is None:
        raise OSError(ctypes.get_last_error(), "GetTokenInformation")
    return sid


def _pipe() -> tuple[int, int]:
    descriptor = security_descriptor_from_sddl(f"D:(A;;GA;;;SY)(A;;GA;;;BA)(A;;GR;;;{_user_sid()})")
    if descriptor is None:
        raise OSError(ctypes.get_last_error(), "ConvertStringSecurityDescriptorToSecurityDescriptorW")
    security = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), ctypes.c_void_p(descriptor), False)
    session_id = ProcessIdToSessionId(GetCurrentProcessId())
    if session_id is None:
        LocalFree(ctypes.c_void_p(descriptor))
        raise OSError(ctypes.get_last_error(), "ProcessIdToSessionId")
    name = input_mode_pipe_name(_user_sid(), session_id)
    handle = CreateNamedPipe(
        name,
        PIPE_ACCESS_OUTBOUND | FILE_FLAG_FIRST_PIPE_INSTANCE,
        PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_NOWAIT | PIPE_REJECT_REMOTE_CLIENTS,
        1,
        16,
        16,
        0,
        ctypes.addressof(security),
    )
    if handle == INVALID_HANDLE_VALUE:
        LocalFree(ctypes.c_void_p(descriptor))
        raise OSError(ctypes.get_last_error(), "CreateNamedPipeW")
    return handle, descriptor


def _mode(last_mode: str | None) -> str:
    foreground = GetForegroundWindow()
    pid = wintypes.DWORD()
    thread = GetWindowThreadProcessId(foreground, ctypes.byref(pid)) if foreground else 0
    if not thread:
        return input_mode_key(None, last_mode)
    info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
    target = (
        input_mode_target(info.hwndFocus, info.hwndCaret, foreground)
        if GetGUIThreadInfo(thread, info)
        else foreground
    )
    ime = ImmGetDefaultIMEWnd(target)
    if not ime:
        return input_mode_key(None, last_mode)
    result = ctypes.c_size_t()
    ok = SendMessageTimeoutW(
        ime, WM_IME_CONTROL, IMC_GETCONVERSIONMODE, 0, SMTO_ABORTIFHUNG, 100, ctypes.byref(result)
    )
    return input_mode_key(result.value if ok else None, last_mode)


def main() -> None:
    changed = threading.Event()
    callback_type = ctypes.WINFUNCTYPE(
        None,
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.HWND,
        ctypes.c_long,
        ctypes.c_long,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    callback = callback_type(lambda _hook, _event, *_args: changed.set())
    hooks = [SetWinEventHook(event, event, None, callback, 0, 0, WINEVENT_OUTOFCONTEXT) for event in _EVENTS]
    hooks = [hook for hook in hooks if hook]
    if not hooks:
        logging.warning("input_mode: all WinEvent hooks failed; using polling only")
    pipe, descriptor = _pipe()
    message = wintypes.MSG()
    try:
        deadline = time.monotonic() + 4
        while True:
            if ConnectNamedPipe(pipe, None) or ctypes.get_last_error() == ERROR_PIPE_CONNECTED:
                mode = None
                next_poll = 0.0
                next_heartbeat = 0.0
                while True:
                    while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                        user32.TranslateMessage(ctypes.byref(message))
                        user32.DispatchMessageW(ctypes.byref(message))
                    now = time.monotonic()
                    if changed.is_set() or now >= next_poll:
                        changed.clear()
                        next_poll = now + 0.2
                        current = _mode(mode)
                        if current != mode or now >= next_heartbeat:
                            mode = current
                            next_heartbeat = now + _HEARTBEAT_SECONDS
                            if not WriteFile(pipe, input_mode_code(mode)):
                                if ctypes.get_last_error() in (ERROR_BROKEN_PIPE, ERROR_NO_DATA):
                                    break
                    time.sleep(0.02)
                DisconnectNamedPipe(pipe)
                deadline = time.monotonic() + 4
            elif ctypes.get_last_error() == ERROR_PIPE_LISTENING:
                if time.monotonic() >= deadline:
                    return
                time.sleep(0.05)
                continue
            else:
                return
            time.sleep(0.05)
    finally:
        for hook in hooks:
            UnhookWinEvent(hook)
        CloseHandle(pipe)
        LocalFree(ctypes.c_void_p(descriptor))


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    main()
