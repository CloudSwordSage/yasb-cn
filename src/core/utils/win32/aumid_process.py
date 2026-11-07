"""
Lookup process executable name from an AppUserModelID (AUMID).
"""

import os

from pycaw.constants import AudioSessionState
from pycaw.pycaw import AudioUtilities

from core.utils.win32.aumid import get_aumid_for_process, get_pid_for_window_aumid
from core.utils.win32.bindings.kernel32 import snapshot_processes
from core.utils.win32.bindings.ole32 import create_dispatch
from core.utils.win32.utils import get_process_path

# AUMID -> (app_display_name, process_exe); negative results cached too.
_shell_app_cache: dict[str, tuple[str | None, str | None]] = {}


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
        folder = create_dispatch("Shell.Application").NameSpace("shell:AppsFolder")
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

    for process in snapshot_processes():
        if get_aumid_for_process(process.pid) == aumid:
            name = os.path.basename(process.exe)
            # Edge PWA host process
            if name.lower() == "pwahelper.exe":
                return "msedge.exe"
            return name

    pid = get_pid_for_window_aumid(aumid)
    if pid:
        path = get_process_path(pid)
        if path:
            return os.path.basename(path)
        for process in snapshot_processes():
            if process.pid == pid and process.exe:
                return os.path.basename(process.exe)

    _, process_exe = resolve_shell_app(aumid)
    return process_exe


def get_app_audio_sessions(app_id: str) -> list:
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
            process_aumid = get_aumid_for_process(int(process.pid))
            if (process_aumid and process_aumid.casefold() == target) or (
                executable and process.name().casefold() == executable
            ):
                if session.State != AudioSessionState.Expired:
                    matches.append(session)
        except Exception:
            continue
    return sorted(matches, key=lambda session: session.State != AudioSessionState.Active)


def _get_app_audio_interfaces(app_id: str) -> list:
    """Return every active volume interface, or inactive fallbacks when none are active."""
    sessions = get_app_audio_sessions(app_id)
    active = [
        session
        for session in sessions
        if getattr(session, "State", AudioSessionState.Active) == AudioSessionState.Active
    ]
    targets = active or sessions
    return [interface for session in targets if (interface := getattr(session, "SimpleAudioVolume", None)) is not None]


def get_app_audio_state(app_id: str) -> tuple[float, bool] | None:
    """Read volume and mute state from the first responsive active session.

    Args:
        app_id(str): Media session AUMID or executable name.
    Returns:
        tuple[float, bool] | None: Volume and mute state, or ``None`` when unavailable.
    """
    for interface in _get_app_audio_interfaces(app_id):
        try:
            return float(interface.GetMasterVolume()), bool(interface.GetMute())
        except Exception:
            continue
    return None


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
