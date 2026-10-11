import asyncio
import importlib
import json
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.validation.widgets.yasb.heart_rate import HeartRateConfig
from core.widgets.services.heart_rate.store import DeviceStore
from tests.test_heart_rate_ble import FakeClient, FakeScanner


def free_port() -> int:
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        return handle.getsockname()[1]


async def read_json(reader):
    return json.loads(await asyncio.wait_for(reader.readline(), 1))


async def _close_server(server):
    server.close()
    await server.wait_closed()


class ForbiddenBleFactory:
    """Fails the test if an ipc source ever tries to create a BLE client."""

    def __init__(self, *args, **kwargs):
        raise AssertionError("BLE must not be used when source is ipc")


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.ipc = importlib.import_module("core.widgets.services.heart_rate.ipc")

    def test_heart_rate_roundtrip(self):
        line = self.ipc.encode_heart_rate(78, 1791698640000, 102)
        self.assertTrue(line.endswith(b"\n"))
        self.assertEqual(
            json.loads(line),
            {"v": 1, "type": "heart_rate", "bpm": 78, "timestamp": 1791698640000, "seq": 102},
        )
        message = self.ipc.parse(line)
        self.assertEqual((message.bpm, message.timestamp, message.seq), (78, 1791698640000, 102))

    def test_status_roundtrip(self):
        line = self.ipc.encode_status("error", "连接失败", 1791698640000)
        self.assertTrue(line.endswith(b"\n"))
        self.assertEqual(json.loads(line)["state"], "error")
        message = self.ipc.parse(line)
        self.assertEqual((message.state, message.error), ("error", "连接失败"))

    def test_missing_optional_fields_are_none(self):
        message = self.ipc.parse(b'{"type":"heart_rate","bpm":70}')
        self.assertEqual((message.bpm, message.timestamp, message.seq), (70, None, None))

    def test_malformed_lines_are_rejected(self):
        for bad in (
            b"",
            b"not json\n",
            b'{"v":1,"type":"other","bpm":70}',
            b'{"v":1,"type":"heart_rate","bpm":0}',
            b'{"v":1,"type":"heart_rate","bpm":65536}',
            b'{"v":1,"type":"heart_rate","bpm":"70"}',
            b'{"v":1,"type":"heart_rate"}',
            b'{"v":1,"type":"status","state":"weird"}',
            b'{"v":2,"type":"heart_rate","bpm":70}',
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(self.ipc.parse(bad))


class PublisherTests(unittest.IsolatedAsyncioTestCase):
    async def test_replay_and_broadcast_to_every_client(self):
        ipc = importlib.import_module("core.widgets.services.heart_rate.ipc")
        publisher = ipc.HeartRatePublisher("127.0.0.1", 0)
        await publisher.start()
        self.addAsyncCleanup(publisher.close)
        port = publisher._server.sockets[0].getsockname()[1]

        first_reader, first_writer = await asyncio.open_connection("127.0.0.1", port)
        self.addCleanup(first_writer.close)
        await asyncio.sleep(0.05)
        # A client that connects before any sample still learns the current state.
        replay = await read_json(first_reader)
        self.assertEqual((replay["type"], replay["state"], replay["error"]), ("status", "disconnected", ""))
        self.assertIsInstance(replay["timestamp"], int)

        publisher.set_state("connected")
        publisher.publish(78, 1.0)
        publisher.publish(80, 1.5)
        self.assertEqual((await read_json(first_reader))["state"], "connected")
        self.assertEqual((await read_json(first_reader))["bpm"], 78)
        self.assertEqual((await read_json(first_reader))["bpm"], 80)

        # A late client immediately receives the state and the last reading.
        second_reader, second_writer = await asyncio.open_connection("127.0.0.1", port)
        self.addCleanup(second_writer.close)
        await asyncio.sleep(0.05)
        self.assertEqual((await read_json(second_reader))["state"], "connected")
        replay = await read_json(second_reader)
        self.assertEqual((replay["bpm"], replay["seq"]), (80, 2))

        publisher.publish(81, 2.0)
        for reader in (first_reader, second_reader):
            live = await read_json(reader)
            self.assertEqual((live["bpm"], live["seq"]), (81, 3))


class IpcBackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ble = importlib.import_module("core.widgets.services.heart_rate.ble")
        self.ipc = importlib.import_module("core.widgets.services.heart_rate.ipc")
        FakeClient.instances = []
        FakeClient.behavior = {}
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = DeviceStore(Path(self.temp.name) / "devices.json")
        self.events = []

    async def wait_for(self, condition, timeout=2):
        async with asyncio.timeout(timeout):
            while not condition():
                await asyncio.sleep(0.005)

    def _backend(self, port, reconnect_interval=1000):
        config = HeartRateConfig(
            source="ipc", ipc={"host": "127.0.0.1", "port": port, "reconnect_interval": reconnect_interval}
        )
        return self.ble.HeartRateBackend(
            config, self.events.append, self.store, client_factory=ForbiddenBleFactory, scanner_factory=ForbiddenBleFactory
        )

    async def test_ipc_source_ingests_without_touching_ble(self):
        port = free_port()

        async def handler(reader, writer):
            try:
                writer.write(self.ipc.encode_status("connected", "", 1791698640000))
                writer.write(self.ipc.encode_heart_rate(78, 1791698640000, 1))
                await writer.drain()
                await reader.read()
            finally:
                writer.close()

        server = await asyncio.start_server(handler, "127.0.0.1", port)
        self.addAsyncCleanup(_close_server, server)
        backend = self._backend(port)
        await backend.start()
        self.addAsyncCleanup(backend.close)
        await self.wait_for(lambda: self.events and self.events[-1]["statistics"]["current"] == 78)
        self.assertEqual(backend.current, 78)
        # The original capture time is preserved for display.
        self.assertEqual(backend.last_wall, 1791698640.0)
        # publish is ignored for the ipc source.
        self.assertIsNone(backend._publisher)

    async def test_disconnect_clears_live_value_but_keeps_history(self):
        port = free_port()

        async def handler(reader, writer):
            writer.write(self.ipc.encode_status("connected", "", 1791698640000))
            writer.write(self.ipc.encode_heart_rate(78, 1791698640000, 1))
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handler, "127.0.0.1", port)
        self.addAsyncCleanup(_close_server, server)
        backend = self._backend(port, reconnect_interval=60000)
        await backend.start()
        self.addAsyncCleanup(backend.close)
        # The publisher reports connected, sends one reading, then drops the link.
        await self.wait_for(lambda: backend.state == "reconnecting" and backend.current is None)
        # History survives the disconnect; only the live value is cleared.
        self.assertEqual(backend.window.statistics(time.monotonic())["sample_count"], 1)
        self.assertEqual(backend.last_wall, 1791698640.0)

    async def test_ble_source_publishes_status_and_samples(self):
        port = free_port()
        config = HeartRateConfig(source="ble", ipc={"publish": True, "host": "127.0.0.1", "port": port})
        backend = self.ble.HeartRateBackend(
            config, self.events.append, self.store, client_factory=FakeClient, scanner_factory=FakeScanner
        )
        await backend.start()
        self.addAsyncCleanup(backend.close)
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        self.addCleanup(writer.close)
        await asyncio.sleep(0.05)
        replay = await read_json(reader)
        self.assertEqual((replay["type"], replay["state"]), ("status", "disconnected"))
        await backend.select("A", "Watch")
        await self.wait_for(lambda: backend.state == "connected")
        connected = await read_json(reader)
        self.assertEqual((connected["type"], connected["state"]), ("status", "connected"))
        FakeClient.instances[-1].notify(None, b"\x00\x43")
        sample = await read_json(reader)
        self.assertEqual((sample["type"], sample["bpm"], sample["seq"]), ("heart_rate", 67, 1))


if __name__ == "__main__":
    unittest.main()
