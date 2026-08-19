import ctypes
import logging
import threading
import time
from ctypes import wintypes

from core.widgets.services.language.mode import input_mode_code, input_mode_key, input_mode_pipe_name, input_mode_target

_PIPE_ACCESS_OUTBOUND = 0x00000002
_FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
_PIPE_TYPE_BYTE = 0x00000000
_PIPE_READMODE_BYTE = 0x00000000
_PIPE_NOWAIT = 0x00000001
_PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
_ERROR_PIPE_CONNECTED = 535
_ERROR_PIPE_LISTENING = 536
_ERROR_BROKEN_PIPE = 109
_ERROR_NO_DATA = 232
_HEARTBEAT_SECONDS = 1.0
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_WM_IME_CONTROL = 0x0283
_IMC_GETCONVERSIONMODE = 0x0001
_SMTO_ABORTIFHUNG = 0x0002
_WINEVENT_OUTOFCONTEXT = 0
_EVENTS = (3, 0x8005, 0x8029)


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _GuiThreadInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


def _bind_win32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    imm32 = ctypes.WinDLL("imm32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.CreateNamedPipeW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_SecurityAttributes),
    ]
    kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
    kernel32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel32.ConnectNamedPipe.restype = wintypes.BOOL
    kernel32.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
    kernel32.DisconnectNamedPipe.restype = wintypes.BOOL
    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetCurrentProcessId.restype = wintypes.DWORD
    kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel32.ProcessIdToSessionId.restype = wintypes.BOOL
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(_GuiThreadInfo)]
    user32.GetGUIThreadInfo.restype = wintypes.BOOL
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    user32.SendMessageTimeoutW.restype = wintypes.LPARAM
    user32.SetWinEventHook.restype = wintypes.HANDLE
    user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
    user32.UnhookWinEvent.restype = wintypes.BOOL
    imm32.ImmGetDefaultIMEWnd.argtypes = [wintypes.HWND]
    imm32.ImmGetDefaultIMEWnd.restype = wintypes.HWND
    advapi32.GetUserNameW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetUserNameW.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    return kernel32, user32, imm32, advapi32


def _user_name(advapi32) -> str:
    size = wintypes.DWORD(256)
    value = ctypes.create_unicode_buffer(size.value)
    advapi32.GetUserNameW(value, ctypes.byref(size))
    return value.value


def _user_sid(kernel32, advapi32) -> str:
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise OSError(ctypes.get_last_error(), "OpenProcessToken")
    try:
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        data = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(token, 1, data, size, ctypes.byref(size)):
            raise OSError(ctypes.get_last_error(), "GetTokenInformation")
        sid = ctypes.cast(data, ctypes.POINTER(ctypes.c_void_p))[0]
        text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise OSError(ctypes.get_last_error(), "ConvertSidToStringSidW")
        try:
            return text.value
        finally:
            kernel32.LocalFree(text)
    finally:
        kernel32.CloseHandle(token)


def _pipe(kernel32, advapi32) -> tuple[int, ctypes.c_void_p]:
    descriptor = ctypes.c_void_p()
    sddl = f"D:(A;;GA;;;SY)(A;;GA;;;BA)(A;;GR;;;{_user_sid(kernel32, advapi32)})"
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
        raise OSError(ctypes.get_last_error(), "ConvertStringSecurityDescriptorToSecurityDescriptorW")
    security = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
    session_id = wintypes.DWORD()
    if not kernel32.ProcessIdToSessionId(kernel32.GetCurrentProcessId(), ctypes.byref(session_id)):
        kernel32.LocalFree(descriptor)
        raise OSError(ctypes.get_last_error(), "ProcessIdToSessionId")
    name = input_mode_pipe_name(_user_sid(kernel32, advapi32), session_id.value)
    handle = kernel32.CreateNamedPipeW(
        name,
        _PIPE_ACCESS_OUTBOUND | _FILE_FLAG_FIRST_PIPE_INSTANCE,
        _PIPE_TYPE_BYTE | _PIPE_READMODE_BYTE | _PIPE_NOWAIT | _PIPE_REJECT_REMOTE_CLIENTS,
        1,
        16,
        16,
        0,
        ctypes.byref(security),
    )
    if handle == _INVALID_HANDLE_VALUE:
        kernel32.LocalFree(descriptor)
        raise OSError(ctypes.get_last_error(), "CreateNamedPipeW")
    return handle, descriptor


def _mode(user32, imm32, last_mode: str | None) -> str:
    foreground = user32.GetForegroundWindow()
    pid = wintypes.DWORD()
    thread = user32.GetWindowThreadProcessId(foreground, ctypes.byref(pid)) if foreground else 0
    if not thread:
        return input_mode_key(None, last_mode)
    info = _GuiThreadInfo(cbSize=ctypes.sizeof(_GuiThreadInfo))
    target = (
        input_mode_target(info.hwndFocus, info.hwndCaret, foreground)
        if user32.GetGUIThreadInfo(thread, ctypes.byref(info))
        else foreground
    )
    ime = imm32.ImmGetDefaultIMEWnd(target)
    if not ime:
        return input_mode_key(None, last_mode)
    result = ctypes.c_size_t()
    ok = user32.SendMessageTimeoutW(
        ime, _WM_IME_CONTROL, _IMC_GETCONVERSIONMODE, 0, _SMTO_ABORTIFHUNG, 100, ctypes.byref(result)
    )
    return input_mode_key(result.value if ok else None, last_mode)


def main() -> None:
    kernel32, user32, imm32, advapi32 = _bind_win32()
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
    hooks = [user32.SetWinEventHook(event, event, None, callback, 0, 0, _WINEVENT_OUTOFCONTEXT) for event in _EVENTS]
    hooks = [hook for hook in hooks if hook]
    if not hooks:
        logging.warning("input_mode: all WinEvent hooks failed; using polling only")
    pipe, descriptor = _pipe(kernel32, advapi32)
    message = wintypes.MSG()
    try:
        deadline = time.monotonic() + 4
        while True:
            if kernel32.ConnectNamedPipe(pipe, None) or ctypes.get_last_error() == _ERROR_PIPE_CONNECTED:
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
                        current = _mode(user32, imm32, mode)
                        if current != mode or now >= next_heartbeat:
                            mode = current
                            next_heartbeat = now + _HEARTBEAT_SECONDS
                            sent = wintypes.DWORD()
                            if not kernel32.WriteFile(pipe, input_mode_code(mode), 1, ctypes.byref(sent), None):
                                if ctypes.get_last_error() in (_ERROR_BROKEN_PIPE, _ERROR_NO_DATA):
                                    break
                    time.sleep(0.02)
                kernel32.DisconnectNamedPipe(pipe)
                deadline = time.monotonic() + 4
            elif ctypes.get_last_error() == _ERROR_PIPE_LISTENING:
                if time.monotonic() >= deadline:
                    return
                time.sleep(0.05)
                continue
            else:
                return
            time.sleep(0.05)
    finally:
        for hook in hooks:
            user32.UnhookWinEvent(hook)
        kernel32.CloseHandle(pipe)
        kernel32.LocalFree(descriptor)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    main()
