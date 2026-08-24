"""
Lookup process executable name from an AppUserModelID (AUMID).
"""

import ctypes
import ctypes.wintypes as wt
import os
from ctypes import POINTER, byref, c_void_p

import win32gui
import win32process
from pycaw.constants import AudioSessionState
from pycaw.pycaw import AudioUtilities
from win32com.client import Dispatch

from core.utils.win32.aumid import get_aumid_for_window
from core.utils.win32.constants import PROCESS_QUERY_LIMITED_INFORMATION, TH32CS_SNAPPROCESS
from core.utils.win32.structs import PROCESSENTRY32

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

CreateToolhelp32Snapshot = kernel32.CreateToolhelp32Snapshot
CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
CreateToolhelp32Snapshot.restype = wt.HANDLE

Process32First = kernel32.Process32FirstW
Process32First.argtypes = [wt.HANDLE, c_void_p]
Process32First.restype = wt.BOOL

Process32Next = kernel32.Process32NextW
Process32Next.argtypes = [wt.HANDLE, c_void_p]
Process32Next.restype = wt.BOOL

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wt.HANDLE]
CloseHandle.restype = wt.BOOL

OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
OpenProcess.restype = wt.HANDLE

ERROR_INSUFFICIENT_BUFFER = 0x7A

GetApplicationUserModelId = None
for dll_name in ("kernel32", "shell32"):
    try:
        dll = ctypes.WinDLL(dll_name, use_last_error=True)
        fn = getattr(dll, "GetApplicationUserModelId")
        fn.argtypes = [wt.HANDLE, POINTER(ctypes.c_uint32), wt.LPWSTR]
        fn.restype = ctypes.c_long
        GetApplicationUserModelId = fn
        break
    except OSError:
        continue

# AUMID -> (app_display_name, process_exe); negative results cached too.
_shell_app_cache: dict[str, tuple[str | None, str | None]] = {}


def get_process_aumid(pid: int) -> str | None:
    """Return the AppUserModelID assigned to a process.

    Args:
        pid(int): Process identifier.
    Returns:
        str | None: Process AppUserModelID, or ``None`` when unavailable.
    """
    if GetApplicationUserModelId is None:
        return None

    h_process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h_process:
        return None
    try:
        length = ctypes.c_uint32(0)
        if GetApplicationUserModelId(h_process, byref(length), None) != ERROR_INSUFFICIENT_BUFFER:
            return None
        buffer = ctypes.create_unicode_buffer(length.value)
        return buffer.value if GetApplicationUserModelId(h_process, byref(length), buffer) == 0 else None
    except OSError:
        return None
    finally:
        CloseHandle(h_process)


def get_app_audio_sessions(app_id: str):
    """Enumerate live audio sessions matching a media application.

    Args:
        app_id(str): Media session AUMID or executable name.
    Returns:
        list: Matching non-expired sessions, with active sessions first.
    """
    if not app_id:
        return []

    target = app_id.casefold()
    executable = get_process_name_for_aumid(app_id)
    executable = executable.casefold() if executable else ""
    matches = []
    for session in AudioUtilities.GetAllSessions():
        try:
            process = getattr(session, "Process", None)
            if process is None:
                continue
            process_aumid = get_process_aumid(int(process.pid))
            if (process_aumid and process_aumid.casefold() == target) or (
                executable and process.name().casefold() == executable
            ):
                if session.State != AudioSessionState.Expired:
                    matches.append(session)
        except Exception:
            continue
    return sorted(matches, key=lambda session: session.State != AudioSessionState.Active)


def _get_app_audio_interfaces(app_id: str):
    """Return every active volume interface, or inactive fallbacks when none are active."""
    sessions = get_app_audio_sessions(app_id)
    active = [session for session in sessions if getattr(session, "State", AudioSessionState.Active) == AudioSessionState.Active]
    targets = active or sessions
    return [
        interface
        for session in targets
        if (interface := getattr(session, "SimpleAudioVolume", None)) is not None
    ]


def set_app_audio_volume(app_id: str, level: float) -> bool:
    """Set every active audio session for an application to one level.

    Args:
        app_id(str): Media session AUMID or executable name.
        level(float): Scalar volume level from 0.0 through 1.0.
    Returns:
        bool: Whether at least one live session was updated.
    """
    level = max(0.0, min(1.0, float(level)))
    updated = False
    for interface in _get_app_audio_interfaces(app_id):
        try:
            interface.SetMasterVolume(level, None)
            updated = True
        except Exception:
            continue
    return updated


def set_app_audio_muted(app_id: str, muted: bool) -> bool:
    """Set the mute state of every active audio session for an application.

    Args:
        app_id(str): Media session AUMID or executable name.
        muted(bool): Desired mute state.
    Returns:
        bool: Whether at least one live session was updated.
    """
    updated = False
    for interface in _get_app_audio_interfaces(app_id):
        try:
            interface.SetMute(bool(muted), None)
            updated = True
        except Exception:
            continue
    return updated


def _enum_processes():
    """Yield (pid, exe_name) for running processes."""
    hSnap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if hSnap == wt.HANDLE(-1).value:
        return
    try:
        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if not Process32First(hSnap, ctypes.byref(pe)):
            return
        while True:
            yield pe.th32ProcessID, pe.szExeFile
            if not Process32Next(hSnap, ctypes.byref(pe)):
                break
    finally:
        CloseHandle(hSnap)


def get_process_image_path(pid: int) -> str | None:
    """Return full image path for a PID using QueryFullProcessImageNameW."""
    try:
        hProc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not hProc:
            return None
        try:
            QueryFullProcessImageName = kernel32.QueryFullProcessImageNameW
            QueryFullProcessImageName.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
            QueryFullProcessImageName.restype = wt.BOOL
            size = wt.DWORD(260)
            buf = ctypes.create_unicode_buffer(size.value)
            if QueryFullProcessImageName(hProc, 0, buf, ctypes.byref(size)):
                return buf.value
        finally:
            try:
                CloseHandle(hProc)
            except Exception:
                pass
    except OSError:
        pass
    return None


def get_pid_for_window_aumid(aumid: str) -> int | None:
    """PID of a visible window whose AppUserModelID matches (shell property store)."""
    if not aumid:
        return None

    target = aumid.lower()
    found: list[int] = []

    def _enum(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        wa = get_aumid_for_window(hwnd)
        if not wa or wa.lower() != target:
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid:
            found.append(pid)
            return False
        return True

    win32gui.EnumWindows(_enum, None)
    return found[0] if found else None


def resolve_shell_app(aumid: str) -> tuple[str | None, str | None]:
    """Resolve AUMID via shell:AppsFolder to (app display name, process exe).

    One ParseName: item.Name + System.Link.TargetParsingPath. Cached.
    """
    if not aumid:
        return None, None

    cached = _shell_app_cache.get(aumid)
    if cached is not None:
        return cached

    display_name: str | None = None
    process_exe: str | None = None
    try:
        folder = Dispatch("Shell.Application").NameSpace("shell:AppsFolder")
        item = folder.ParseName(aumid) if folder else None
        if item:
            raw_name = item.Name
            if raw_name:
                display_name = str(raw_name).strip() or None
            target = item.ExtendedProperty("System.Link.TargetParsingPath")
            if target:
                process_exe = os.path.basename(str(target)) or None
    except Exception:
        pass

    _shell_app_cache[aumid] = (display_name, process_exe)
    return display_name, process_exe


def get_process_name_for_aumid(aumid: str) -> str | None:
    """Resolve AUMID -> exe name the way Windows associates apps with processes.

    1. SMTC sometimes uses the exe name as the AUMID
    2. GetApplicationUserModelId(process) == aumid
    3. Window PKEY_AppUserModel_ID == aumid -> that window's process
    4. shell AppsFolder TargetParsingPath (when process/window AUMID missing)
    """
    if not aumid:
        return None

    if aumid.lower().endswith(".exe"):
        return os.path.basename(aumid)

    if GetApplicationUserModelId is not None:
        for pid, exe in _enum_processes():
            hProc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not hProc:
                continue
            try:
                length = ctypes.c_uint32(0)
                res = GetApplicationUserModelId(hProc, byref(length), None)
                if res == ERROR_INSUFFICIENT_BUFFER and length.value:
                    buf = ctypes.create_unicode_buffer(length.value)
                    res = GetApplicationUserModelId(hProc, byref(length), buf)
                    if res == 0 and buf.value == aumid:
                        name = os.path.basename(exe)
                        # Edge PWA host process
                        if name.lower() == "pwahelper.exe":
                            return "msedge.exe"
                        return name
            except OSError:
                pass
            finally:
                try:
                    CloseHandle(hProc)
                except OSError:
                    pass

    pid = get_pid_for_window_aumid(aumid)
    if pid:
        path = get_process_image_path(pid)
        if path:
            return os.path.basename(path)
        for p, exe in _enum_processes():
            if p == pid and exe:
                return os.path.basename(str(exe))

    _, process_exe = resolve_shell_app(aumid)
    return process_exe
