import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.widgets.services.media.aumid_process import (
    get_app_audio_sessions,
    get_app_audio_state,
    set_app_audio_muted,
    set_app_audio_volume,
)


class _Session:
    def __init__(self, pid: int, executable: str, state: int) -> None:
        self.Process = SimpleNamespace(pid=pid, name=lambda: executable)
        self.State = state


class _Volume:
    def __init__(self) -> None:
        self.levels = []
        self.mutes = []

    def SetMasterVolume(self, level: float, _event_context) -> None:
        self.levels.append(level)

    def SetMute(self, muted: bool, _event_context) -> None:
        self.mutes.append(muted)


class _BrokenVolume:
    def GetMasterVolume(self) -> float:
        raise OSError("session disconnected")


class AppAudioSessionTests(unittest.TestCase):
    def test_reenumerates_and_prefers_all_active_sessions(self) -> None:
        stale = _Session(1, "player.exe", 0)
        active_one = _Session(2, "player.exe", 1)
        active_two = _Session(3, "player.exe", 1)
        expired = _Session(4, "player.exe", 2)
        unrelated = _Session(5, "other.exe", 1)

        with (
            patch(
                "core.widgets.services.media.aumid_process.AudioUtilities.GetAllSessions",
                side_effect=[[stale], [stale, active_one, expired, unrelated, active_two]],
            ) as get_all_sessions,
            patch(
                "core.widgets.services.media.aumid_process.get_process_name_for_aumid",
                return_value="player.exe",
            ),
            patch(
                "core.widgets.services.media.aumid_process.get_process_aumid",
                return_value=None,
            ),
        ):
            self.assertEqual(get_app_audio_sessions("Player.App"), [stale])
            self.assertEqual(get_app_audio_sessions("Player.App"), [active_one, active_two, stale])

        self.assertEqual(get_all_sessions.call_count, 2)

    def test_sets_volume_and_mute_on_every_active_session(self) -> None:
        volumes = [_Volume(), _Volume()]
        sessions = [SimpleNamespace(SimpleAudioVolume=volume) for volume in volumes]

        with patch(
            "core.widgets.services.media.aumid_process.get_app_audio_sessions",
            return_value=sessions,
        ):
            self.assertTrue(set_app_audio_volume("Player.App", 0.42))
            self.assertTrue(set_app_audio_muted("Player.App", True))

        self.assertEqual([volume.levels for volume in volumes], [[0.42], [0.42]])
        self.assertEqual([volume.mutes for volume in volumes], [[True], [True]])

    def test_reads_recreated_session_after_stale_interface(self) -> None:
        replacement = SimpleNamespace(GetMasterVolume=lambda: 0.65, GetMute=lambda: True)
        sessions = [
            SimpleNamespace(State=1, SimpleAudioVolume=_BrokenVolume()),
            SimpleNamespace(State=1, SimpleAudioVolume=replacement),
        ]

        with patch(
            "core.widgets.services.media.aumid_process.get_app_audio_sessions",
            return_value=sessions,
        ):
            self.assertEqual(get_app_audio_state("Player.App"), (0.65, True))

    def test_matches_same_application_across_processes(self) -> None:
        direct_aumid = _Session(11, "host.exe", 1)
        executable_match = _Session(12, "player.exe", 1)

        with (
            patch(
                "core.widgets.services.media.aumid_process.AudioUtilities.GetAllSessions",
                return_value=[direct_aumid, executable_match],
            ),
            patch(
                "core.widgets.services.media.aumid_process.get_process_name_for_aumid",
                return_value="player.exe",
            ),
            patch(
                "core.widgets.services.media.aumid_process.get_process_aumid",
                side_effect=lambda pid: "Player.App" if pid == 11 else None,
            ),
        ):
            self.assertEqual(
                get_app_audio_sessions("Player.App"),
                [direct_aumid, executable_match],
            )


if __name__ == "__main__":
    unittest.main()
