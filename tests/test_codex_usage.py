import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.widgets.services.codex_usage.app_server import parse_rate_limits


class ParseRateLimitsTests(unittest.TestCase):
    def test_parses_primary_and_secondary_windows(self) -> None:
        payload = {
            "rateLimits": {
                "limitId": "codex",
                "primary": {"usedPercent": 25, "windowDurationMins": 15, "resetsAt": 1730947200},
                "secondary": {"usedPercent": 42, "windowDurationMins": 60, "resetsAt": 1730950800},
            }
        }

        self.assertEqual(
            parse_rate_limits(payload),
            {
                "primary": {"used_percent": 25, "window_duration_mins": 15, "resets_at": 1730947200},
                "secondary": {"used_percent": 42, "window_duration_mins": 60, "resets_at": 1730950800},
            },
        )


if __name__ == "__main__":
    unittest.main()
