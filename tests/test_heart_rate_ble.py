import asyncio
import importlib
import logging
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Failure-path tests intentionally trigger logged BLE exceptions.
logging.getLogger("core.widgets.services.heart_rate.ble").setLevel(logging.CRITICAL)


class FakeClient:
    instances = []
    behavior = {}
    active = 0
    peak = 0

    def __init__(self, device, disconnected_callback=None, **kwargs):
        self.address = getattr(device, "address", device)
        self.callback = disconnected_callback
        self.is_connected = False
        self.notify = None
        self.stopped = False
        self.behavior = type(self).behavior.get(self.address, {})
        self.characteristic = SimpleNamespace(uuid=f"{0x2A37:08x}-0000-1000-8000-00805f9b34fb", properties=["notify"])
        self.services = SimpleNamespace(
            get_service=lambda uuid: (
                None if self.behavior.get("missing") else SimpleNamespace(characteristics=[self.characteristic])
            )
        )
        type(self).instances.append(self)

    async def connect(self):
        await asyncio.sleep(self.behavior.get("delay", 0))
        if self.behavior.get("fail"):
            raise RuntimeError("driver busy")
        self.is_connected = True
        type(self).active += 1
        type(self).peak = max(type(self).peak, type(self).active)

    async def start_notify(self, characteristic, callback):
        if self.behavior.get("notify_fail"):
            raise RuntimeError("subscription rejected")
        self.notify = callback

    async def stop_notify(self, characteristic):
        self.stopped = True
        self.notify = None

    async def disconnect(self):
        if self.is_connected:
            self.is_connected = False
            type(self).active -= 1
        if self.callback:
            self.callback(self)


class FakeScanner:
    devices = []
    running = 0

    def __init__(self, detection_callback, **kwargs):
        self.callback = detection_callback

    async def __aenter__(self):
        type(self).running += 1
        for address, name, services in self.devices:
            self.callback(
                SimpleNamespace(address=address, name=name),
                SimpleNamespace(local_name=name, service_uuids=services, rssi=-50),
            )
        return self

    async def __aexit__(self, *args):
        type(self).running -= 1


class BleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            module = importlib.import_module("core.widgets.services.heart_rate.ble")
        except ModuleNotFoundError as error:
            self.fail(f"BLE implementation missing: {error}")
        from core.validation.widgets.yasb.heart_rate import HeartRateConfig
        from core.widgets.services.heart_rate.store import DeviceStore

        FakeClient.instances = []
        FakeClient.behavior = {}
        FakeClient.active = FakeClient.peak = 0
        FakeScanner.devices = []
        FakeScanner.running = 0
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = DeviceStore(Path(self.temp.name) / "devices.json")
        self.events = []
        self.config = HeartRateConfig(
            connection={"connect_timeout": 100, "reconnect_interval": 100, "stale_timeout": 400, "scan_timeout": 100}
        )
        self.backend = module.HeartRateBackend(
            self.config, self.events.append, self.store, client_factory=FakeClient, scanner_factory=FakeScanner
        )
        await self.backend.start()
        self.addAsyncCleanup(self.backend.close)

    async def wait_for(self, condition, timeout=1):
        async with asyncio.timeout(timeout):
            while not condition():
                await asyncio.sleep(0.005)

    async def test_first_connection_notification_and_persistence(self):
        await self.backend.select("A", "Watch")
        await self.wait_for(lambda: self.backend.state == "connected")
        client = FakeClient.instances[-1]
        client.notify(None, b"\x00\x43")
        client.notify(None, b"\x01")
        await self.wait_for(lambda: any(event["statistics"]["current"] == 67 for event in self.events))
        self.assertEqual(self.store.load()["A"]["name"], "Watch")
        self.assertTrue(self.store.load()["A"]["auto_connect"])
        self.assertEqual(self.backend.window.statistics(time.monotonic())["sample_count"], 1)

    async def test_failures_release_resources_and_retry_after_attempt(self):
        for behavior in ({"delay": 1}, {"missing": True}, {"notify_fail": True}):
            with self.subTest(behavior=behavior):
                FakeClient.behavior["A"] = behavior
                await self.backend.select("A", "Watch")
                await self.wait_for(lambda: self.backend.state == "reconnecting")
                self.assertTrue(self.backend.error)
                self.assertEqual(FakeClient.active, 0)
                count = len(FakeClient.instances)
                await asyncio.sleep(0.03)
                self.assertEqual(len(FakeClient.instances), count)
                await self.backend.select(None)

    async def test_duplicate_request_and_manual_disconnect(self):
        await self.backend.select("A", "Watch")
        await self.wait_for(lambda: self.backend.state == "connected")
        await self.backend.select("A", "Watch")
        self.assertEqual(len(FakeClient.instances), 1)
        await self.backend.select(None)
        await asyncio.sleep(0.15)
        self.assertEqual(self.backend.state, "disconnected")
        self.assertEqual(len(FakeClient.instances), 1)
        self.assertTrue(FakeClient.instances[0].stopped)

    async def test_unexpected_disconnect_reconnect_and_segment_break(self):
        await self.backend.select("A", "Watch")
        await self.wait_for(lambda: self.backend.state == "connected")
        first = FakeClient.instances[-1]
        first.notify(None, b"\x00\x43")
        await first.disconnect()
        await self.wait_for(lambda: len(FakeClient.instances) >= 2 and self.backend.state == "connected")
        self.assertIsNone(self.backend.current)
        second = FakeClient.instances[-1]
        second.notify(None, b"\x00\x44")
        self.assertNotEqual(self.backend.window.samples[0].segment, self.backend.window.samples[-1].segment)

    async def test_switch_device_cleans_old_client(self):
        await self.backend.select("A", "Watch")
        await self.wait_for(lambda: self.backend.state == "connected")
        await self.backend.select("B", "Other")
        await self.wait_for(lambda: self.backend.state == "connected")
        self.assertFalse(FakeClient.instances[0].is_connected)
        self.assertEqual(FakeClient.active, 1)
        self.assertEqual(self.backend.address, "B")

    async def test_stale_is_not_disconnection(self):
        await self.backend.select("A", "Watch")
        await self.wait_for(lambda: self.backend.state == "connected")
        client = FakeClient.instances[-1]
        client.notify(None, b"\x00\x43")
        await self.wait_for(lambda: self.backend.state == "stale", timeout=2)
        self.assertTrue(client.is_connected)
        self.assertIsNone(self.backend.current)
        client.notify(None, b"\x00\x44")
        self.assertEqual(self.backend.state, "connected")

    async def test_repeated_failures_do_not_flood_logs(self):
        FakeClient.behavior["A"] = {"fail": True}
        with self.assertLogs("core.widgets.services.heart_rate.ble", level="WARNING") as captured:
            await self.backend.select("A", "Watch")
            await self.wait_for(lambda: self.backend.state == "reconnecting")
            await asyncio.sleep(0.35)
        self.assertGreater(len(FakeClient.instances), 1, "expected several reconnect attempts")
        warnings = [record for record in captured.records if record.levelno >= logging.WARNING]
        self.assertEqual(len(warnings), 1, [record.getMessage() for record in warnings])

    async def test_incremental_scan_cancel_and_no_name_filter(self):
        uuid = f"{0x180D:08x}-0000-1000-8000-00805f9b34fb"
        FakeScanner.devices = [("A", None, [uuid]), ("A", "Watch", [uuid]), ("B", "Other", [])]
        await self.backend.scan(False)
        await self.wait_for(lambda: "A" in self.backend.devices)
        self.assertEqual(len(FakeClient.instances), 0)
        self.assertEqual(self.backend.devices["A"]["rssi"], -50)
        self.assertEqual(self.backend.devices["A"]["name"], "Watch")
        self.assertNotIn("B", self.backend.devices)
        await self.backend.stop_scan()
        self.assertEqual(FakeScanner.running, 0)
        self.assertFalse(self.backend.scanning)

    async def test_deep_scan_concurrency_results_and_cleanup(self):
        FakeScanner.devices = [(str(i), None, []) for i in range(4)]
        FakeClient.behavior = {"0": {"delay": 0.08}, "1": {"delay": 0.01}, "2": {"missing": True}}
        await self.backend.scan(True)
        await self.wait_for(lambda: any(event["devices"].get("1", {}).get("verified") for event in self.events))
        self.assertFalse(self.backend.devices["0"].get("verified", False))
        await self.wait_for(lambda: not self.backend.scanning)
        self.assertLessEqual(FakeClient.peak, 2)
        self.assertEqual(FakeClient.active, 0)
        self.assertFalse(self.backend.devices["2"]["verified"])

    async def test_close_cancels_scan_and_connection(self):
        FakeScanner.devices = [("B", None, [])]
        FakeClient.behavior = {"A": {"delay": 2}, "B": {"delay": 2}}
        await self.backend.select("A", "Watch")
        await self.backend.scan(True)
        await asyncio.sleep(0.02)
        await self.backend.close()
        self.assertEqual(FakeScanner.running, 0)
        self.assertEqual(FakeClient.active, 0)
        self.assertTrue(self.backend.closed)
        self.assertTrue(self.backend.connection_task is None or self.backend.connection_task.done())

    async def test_saved_default_auto_restores(self):
        await self.backend.close()
        self.store.save({"A": {"address": "A", "name": "Watch", "auto_connect": True, "last_connected": 100}})
        module = importlib.import_module("core.widgets.services.heart_rate.ble")
        self.backend = module.HeartRateBackend(
            self.config, self.events.append, self.store, client_factory=FakeClient, scanner_factory=FakeScanner
        )
        await self.backend.start()
        await self.wait_for(lambda: self.backend.state == "connected")
        self.assertEqual(self.backend.address, "A")

    async def test_shared_source_views_have_independent_windows(self):
        from core.validation.widgets.yasb.heart_rate import HeartRateGraphConfig

        self.assertTrue(hasattr(self.backend, "add_view"), "Shared source needs per-view windows")
        await self.backend.add_view("short", HeartRateGraphConfig(window_seconds=1))
        await self.backend.add_view("long", HeartRateGraphConfig(window_seconds=300))
        await self.backend.select("A", "Watch")
        await self.wait_for(lambda: self.backend.state == "connected")
        FakeClient.instances[-1].notify(None, b"\x00\x43")
        await self.wait_for(
            lambda: self.events[-1].get("views", {}).get("short", {}).get("statistics", {}).get("sample_count") == 1
        )
        self.assertEqual(self.events[-1]["views"]["long"]["statistics"]["sample_count"], 1)
        await self.backend.remove_view("short")
        self.assertNotIn("short", self.events[-1]["views"])


if __name__ == "__main__":
    unittest.main()
