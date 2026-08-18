import json
import os
import subprocess
import threading
from typing import Any


EMPTY_USAGE = {
    "primary": {"used_percent": "--", "window_duration_mins": "--", "resets_at": "--"},
    "secondary": {"used_percent": "--", "window_duration_mins": "--", "resets_at": "--"},
}


def parse_rate_limits(payload: dict[str, Any]) -> dict[str, dict[str, int | float | None]]:
    """Normalize app-server rate-limit data for label formatting.

    Args:
        payload: The ``rateLimits`` object returned by app-server.
    Returns:
        Primary and secondary usage-window values, or ``None`` for missing values.
    """
    rate_limits = payload.get("rateLimits") or {}

    def parse_window(name: str) -> dict[str, int | float | None]:
        window = rate_limits.get(name) or {}
        return {
            "used_percent": window.get("usedPercent"),
            "window_duration_mins": window.get("windowDurationMins"),
            "resets_at": window.get("resetsAt"),
        }

    return {"primary": parse_window("primary"), "secondary": parse_window("secondary")}


def read_rate_limits(command: str, timeout: int) -> dict[str, dict[str, int | float | None]]:
    """Read account rate limits through a short-lived Codex app-server session.

    Args:
        command: Codex executable path or command name.
        timeout: Maximum seconds to wait for the JSON-RPC response.
    Returns:
        Normalized rate-limit data, or empty values if app-server is unavailable.
    """
    process = None
    timer = None
    try:
        requests = (
            json.dumps(
                {
                    "method": "initialize",
                    "id": 1,
                    "params": {"clientInfo": {"name": "yasb", "title": "YASB", "version": "1.0"}},
                }
            )
            + "\n"
            + json.dumps({"method": "initialized", "params": {}})
            + "\n"
            + json.dumps({"method": "account/rateLimits/read", "id": 2})
            + "\n"
        )
        process = subprocess.Popen(
            [command, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW,
            env=os.environ | {"HOME": os.environ.get("HOME") or os.environ.get("USERPROFILE", "")},
        )
        assert process.stdin is not None
        assert process.stdout is not None
        timer = threading.Timer(timeout, process.terminate)
        timer.start()
        process.stdin.write(requests)
        process.stdin.flush()
        for line in process.stdout:
            response = json.loads(line)
            if response.get("id") == 2:
                return parse_rate_limits(response.get("result") or {})
    except (OSError, ValueError, json.JSONDecodeError):
        return dict(EMPTY_USAGE)
    finally:
        if timer is not None:
            timer.cancel()
        if process is not None:
            process.terminate()
    return dict(EMPTY_USAGE)
