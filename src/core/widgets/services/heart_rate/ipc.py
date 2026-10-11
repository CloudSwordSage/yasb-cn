"""Newline-delimited JSON transport for sharing heart rate between processes.

Two message types are exchanged as one compact JSON object per line, as in

    {"v":1,"type":"heart_rate","bpm":78,"timestamp":1791698640000,"seq":102}
    {"v":1,"type":"status","state":"connected","error":"","timestamp":1791698640000}

``timestamp`` is Unix epoch milliseconds from the sender's wall clock. ``seq``
increases once per sample. A ``ble`` source optionally acts as the server
(``ipc.publish``) while every ``ipc`` source connects as a client.
"""

import asyncio
import json
import logging
import time
from typing import NamedTuple

PROTOCOL_VERSION = 1
HEART_RATE = "heart_rate"
STATUS = "status"
STATES = frozenset({"connected", "disconnected", "error"})
# A consumer that stops reading must not grow the write buffer without bound.
# A late heart rate sample is worthless, so an over-full client is dropped
# instead of stalling the BLE notification path.
_MAX_WRITE_BUFFER = 1 << 20

logger = logging.getLogger(__name__)


class HeartRateMessage(NamedTuple):
    """One heart rate sample. ``timestamp``/``seq`` are ``None`` when absent."""

    bpm: int
    timestamp: int | None
    seq: int | None


class StatusMessage(NamedTuple):
    """A publisher state change; ``error`` is empty unless ``state`` is error."""

    state: str
    error: str


def _optional_int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def encode_heart_rate(bpm: int, timestamp_ms: int, seq: int) -> bytes:
    """Serialize one heart rate sample as a JSON line, including the newline."""
    payload = {"v": PROTOCOL_VERSION, "type": HEART_RATE, "bpm": bpm, "timestamp": timestamp_ms, "seq": seq}
    return json.dumps(payload, separators=(",", ":")).encode() + b"\n"


def encode_status(state: str, error: str, timestamp_ms: int) -> bytes:
    """Serialize one status change as a JSON line, including the newline."""
    payload = {"v": PROTOCOL_VERSION, "type": STATUS, "state": state, "error": error, "timestamp": timestamp_ms}
    return json.dumps(payload, separators=(",", ":")).encode() + b"\n"


def parse(line: bytes) -> HeartRateMessage | StatusMessage | None:
    """Return a validated message, or ``None`` for malformed/unsupported input."""
    try:
        payload = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    version = payload.get("v")
    if version is not None and version != PROTOCOL_VERSION:
        return None
    kind = payload.get("type")
    if kind == HEART_RATE:
        bpm = payload.get("bpm")
        if isinstance(bpm, bool) or not isinstance(bpm, int) or not 0 < bpm <= 65535:
            return None
        return HeartRateMessage(bpm, _optional_int(payload.get("timestamp")), _optional_int(payload.get("seq")))
    if kind == STATUS:
        state = payload.get("state")
        if state not in STATES:
            return None
        error = payload.get("error")
        return StatusMessage(state, error if isinstance(error, str) else "")
    return None


def _now_ms() -> int:
    return int(time.time() * 1000)


class HeartRatePublisher:
    """Broadcast samples and status changes to the connected ``ipc`` clients.

    ``publish`` and ``set_state`` are synchronous and never block. A new client
    immediately receives the current status and the last reading so its UI does
    not have to wait for the next notification. A slow client whose buffer
    exceeds ``_MAX_WRITE_BUFFER`` is dropped so the BLE path is never stalled.
    """

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self._server = None
        self._clients: set[asyncio.StreamWriter] = set()
        self._seq = 0
        self._state = "disconnected"
        self._error = ""
        self._last: tuple[int, int, int] | None = None

    async def start(self) -> None:
        """Bind the listening socket. An OSError propagates to the caller."""
        self._server = await asyncio.start_server(self._handle, self.host, self.port)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # The protocol is server to client only. Drain input purely to detect a
        # disconnect without accumulating unbounded data.
        self._clients.add(writer)
        try:
            # Replay the current status and the most recent reading so a client
            # shows live data immediately instead of waiting for the next notify.
            writer.write(encode_status(self._state, self._error, _now_ms()))
            if self._last is not None:
                writer.write(encode_heart_rate(*self._last))
            while await reader.read(4096):
                pass
        except OSError:
            pass
        finally:
            self._clients.discard(writer)
            writer.close()

    def publish(self, bpm: int, wall: float) -> None:
        """Record and queue one sample for every client without blocking."""
        self._seq += 1
        self._last = (bpm, int(wall * 1000), self._seq)
        self._broadcast(encode_heart_rate(*self._last))

    def set_state(self, state: str, error: str = "") -> None:
        """Broadcast a status change; an unchanged state is not re-sent."""
        if state == self._state and error == self._error:
            return
        self._state = state
        self._error = error
        self._broadcast(encode_status(state, error, _now_ms()))

    def _broadcast(self, data: bytes) -> None:
        for writer in tuple(self._clients):
            if writer.transport is None or writer.transport.get_write_buffer_size() > _MAX_WRITE_BUFFER:
                logger.warning("Dropping unresponsive heart rate IPC client")
                self._drop(writer)
                continue
            try:
                writer.write(data)
            except Exception:
                self._drop(writer)

    def _drop(self, writer: asyncio.StreamWriter) -> None:
        self._clients.discard(writer)
        writer.close()

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        for writer in tuple(self._clients):
            writer.close()
        self._clients.clear()


class HeartRateSubscriber:
    """Maintain one TCP connection to an external publisher and report messages.

    ``reconnect_interval`` is a delay in milliseconds. ``on_link`` reports the
    TCP link (``"connected"``/``"reconnecting"``), ``on_sample`` receives
    validated ``HeartRateMessage`` values, ``on_status`` receives
    ``StatusMessage`` changes, and ``on_error`` one message per failed attempt.
    ``run`` only returns by cancellation.
    """

    def __init__(self, host, port, reconnect_interval, on_sample, on_status, on_link, on_error):
        self.host = host
        self.port = port
        self.reconnect_interval = reconnect_interval
        self.on_sample = on_sample
        self.on_status = on_status
        self.on_link = on_link
        self.on_error = on_error

    async def run(self) -> None:
        """Connect and read forever, reconnecting after any failure."""
        while True:
            writer = None
            try:
                reader, writer = await asyncio.open_connection(self.host, self.port)
                self.on_link("connected")
                while True:
                    line = await reader.readline()
                    if not line:
                        raise ConnectionError("发布端已关闭连接")
                    message = parse(line)
                    if isinstance(message, HeartRateMessage):
                        self.on_sample(message)
                    elif isinstance(message, StatusMessage):
                        self.on_status(message)
            except asyncio.CancelledError:
                raise
            except (OSError, ValueError) as error:
                # ValueError covers a line that exceeds the stream limit.
                self.on_error(f"{type(error).__name__}：{error}")
            finally:
                if writer is not None:
                    writer.close()
            self.on_link("reconnecting")
            await asyncio.sleep(self.reconnect_interval / 1000)
