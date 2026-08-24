import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.widgets.services.media.aumid_process import get_app_audio_sessions


class _Session:
    def __init__(self, pid: int, executable: str, state: int) -> None:
        self.Process = SimpleNamespace(pid=pid, name=lambda: executable)
        self.State = state


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


if __name__ == "__main__":
    unittest.main()
