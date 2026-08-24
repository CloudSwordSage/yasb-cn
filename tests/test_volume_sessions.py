import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.widgets.services.volume.service import AudioOutputService
from core.widgets.yasb.volume import VolumeWidget


class _Volume:
    def __init__(self) -> None:
        self.levels = []
        self.mutes = []
        self.muted = False

    def GetMasterVolume(self) -> float:
        return 1.0

    def GetMute(self) -> bool:
        return self.muted

    def SetMasterVolume(self, level: float, _event_context) -> None:
        self.levels.append(level)

    def SetMute(self, muted: bool, _event_context) -> None:
        self.muted = muted
        self.mutes.append(muted)


def _session(pid: int, executable: str, state: int, volume=None):
    process = SimpleNamespace(pid=pid, name=lambda: executable)
    return SimpleNamespace(
        DisplayName="",
        GroupingParam="group",
        Process=process,
        ProcessId=pid,
        SimpleAudioVolume=volume or _Volume(),
        State=state,
    )


class VolumeSessionTests(unittest.TestCase):
    def test_session_enumeration_never_returns_cached_snapshot(self) -> None:
        stale = _session(1, "player.exe", 0)
        live = _session(2, "player.exe", 1)
        service = SimpleNamespace(_cache_lock=threading.Lock(), _cached_sessions=[stale])

        with patch(
            "core.widgets.services.volume.service.AudioUtilities.GetAllSessions",
            return_value=[live],
        ):
            self.assertEqual(AudioOutputService.get_all_sessions(service), [live])

    def test_active_session_rows_are_grouped_by_application(self) -> None:
        inactive = _session(1, "player.exe", 0)
        active = _session(2, "player.exe", 1)
        service = SimpleNamespace(
            get_all_sessions=lambda: [inactive, active],
            get_speakers=lambda: object(),
        )

        rows = AudioOutputService.get_active_audio_sessions(service)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["app_id"], "player.exe")
        self.assertIs(rows[0]["volume_interface"], active.SimpleAudioVolume)

    def test_volume_change_resolves_the_current_application_sessions(self) -> None:
        live_volume = _Volume()
        live = _session(2, "player.exe", 1, live_volume)
        widget = SimpleNamespace()

        with (
            patch(
                "core.widgets.services.media.aumid_process.AudioUtilities.GetAllSessions",
                return_value=[live],
            ),
            patch(
                "core.widgets.services.media.aumid_process.get_process_aumid",
                return_value=None,
            ),
        ):
            VolumeWidget._set_app_volume(widget, "player.exe", 42)

        self.assertEqual(live_volume.levels, [0.42])

    def test_mute_toggle_resolves_the_current_application_sessions(self) -> None:
        live_volume = _Volume()
        live = _session(2, "player.exe", 1, live_volume)
        widget = SimpleNamespace(_update_app_mute_state=lambda *_args: None)

        with (
            patch(
                "core.widgets.services.media.aumid_process.AudioUtilities.GetAllSessions",
                return_value=[live],
            ),
            patch(
                "core.widgets.services.media.aumid_process.get_process_aumid",
                return_value=None,
            ),
        ):
            VolumeWidget._toggle_app_mute(widget, "player.exe", None, None, 2)

        self.assertEqual(live_volume.mutes, [True])


if __name__ == "__main__":
    unittest.main()
