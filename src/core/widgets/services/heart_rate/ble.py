import asyncio
import logging
import time
from collections.abc import Callable

from bleak import BleakClient, BleakScanner

from core.validation.widgets.yasb.heart_rate import HeartRateConfig
from core.widgets.services.heart_rate.data import GAP_SECONDS, SampleWindow, graph_segments, parse_measurement
from core.widgets.services.heart_rate.ipc import HeartRatePublisher, HeartRateSubscriber
from core.widgets.services.heart_rate.store import DeviceStore

logger = logging.getLogger(__name__)
HR_SERVICE_UUID = f"{0x180D:08x}-0000-1000-8000-00805f9b34fb"
HR_MEASUREMENT_UUID = f"{0x2A37:08x}-0000-1000-8000-00805f9b34fb"


class HeartRateBackend:
    """Single-loop owner for a BLE or IPC heart rate source.

    UI commands must be submitted onto its asyncio loop. A serialized selection
    lock cancels and awaits the old connection before a new one starts. Only the
    connection runner registers notify. Temporary validation clients are scoped
    to the scan and never replace the current source. With ``source: ble`` the
    backend may additionally serve samples to IPC clients; with ``source: ipc``
    it subscribes to an external publisher and never touches Bluetooth.
    """

    def __init__(
        self,
        config: HeartRateConfig,
        emit: Callable[[dict], None],
        store: DeviceStore,
        client_factory=BleakClient,
        scanner_factory=BleakScanner,
    ):
        self.config = config
        self.emit = emit
        self.store = store
        self.client_factory = client_factory
        self.scanner_factory = scanner_factory
        self.window = SampleWindow(config.graph.window_seconds)
        self.devices = {}
        self.saved = {}
        self.runtime_devices = {}
        self.state = "disconnected"
        self.error = ""
        self.storage_error = ""
        self.address = None
        self.name = ""
        self.current = None
        self.last_wall = None
        self.last_monotonic = None
        self.segment = 0
        self.scanning = False
        self.closed = False
        self.connection_task = None
        self.scan_task = None
        self._ticker = None
        self._select_lock = asyncio.Lock()
        self._scan_lock = asyncio.Lock()
        self._dirty = True
        self._graph_revision = -1
        self._graph_points = []
        self._quarantined = False
        self._views = {}
        self._logged_errors: set[str] = set()
        self._publisher = None
        self._subscriber_task = None
        self._ipc_seq = None

    def _report_error(self, category: str, message: str) -> None:
        """Log each distinct retry failure once; repeats stay at debug level.

        A persistent outage therefore keeps the log readable instead of writing
        one warning per reconnect attempt.
        """
        if category in self._logged_errors:
            logger.debug("Heart rate (%s): %s", category, message)
        else:
            self._logged_errors.add(category)
            logger.warning("Heart rate (%s): %s", category, message)

    async def add_view(self, key: str, graph) -> None:
        """Register an independently configured graph/window on the shared source."""
        if self.closed:
            return
        if key not in self._views:
            window = SampleWindow(graph.window_seconds)
            for sample in self.window.samples:
                window.add(sample.value, sample.monotonic, sample.wall, sample.segment)
            self._views[key] = {"graph": graph, "window": window, "revision": -1, "segments": []}
        self._publish()

    async def remove_view(self, key: str) -> None:
        """Release one view without disconnecting the shared heart rate source."""
        self._views.pop(key, None)
        self._publish()

    async def start(self) -> None:
        """Prepare the selected source: load devices, then start BLE or subscribe to IPC."""
        if self.config.source == "ble":
            try:
                self.saved = self.store.load()
            except (OSError, ValueError):
                logger.exception("Unable to load saved heart rate devices")
                self.storage_error = "无法读取已保存设备，请检查设备文件及权限"
            for address, record in self.saved.items():
                self.devices[address] = {**record, "rssi": None, "verified": None}
            if self.config.ipc.publish:
                await self._start_publisher()
        self._ticker = asyncio.create_task(self._refresh_loop())
        if self.config.source == "ble":
            if self.config.connection.auto_connect:
                default = next((record for record in self.saved.values() if record["auto_connect"]), None)
                if default:
                    await self.select(default["address"], default["name"], restoring=True)
        else:
            self.state = "connecting"
            self.name = f"{self.config.ipc.host}:{self.config.ipc.port}"
            self._subscriber_task = asyncio.create_task(self._ipc_loop())
        self._publish()

    async def _start_publisher(self) -> None:
        """Serve samples to IPC clients; a bind failure is reported, not fatal."""
        self._publisher = HeartRatePublisher(self.config.ipc.host, self.config.ipc.port)
        try:
            await self._publisher.start()
        except OSError as error:
            self._publisher = None
            self.error = f"心率 IPC 服务启动失败：{error}"
            logger.warning("Heart rate IPC server failed to start: %s", error)

    async def _ipc_loop(self) -> None:
        """Subscribe to the external publisher forever; only cancellation ends it."""
        subscriber = HeartRateSubscriber(
            self.config.ipc.host,
            self.config.ipc.port,
            self.config.ipc.reconnect_interval,
            self._ipc_sample,
            self._ipc_status,
            self._ipc_link,
            self._ipc_error,
        )
        await subscriber.run()

    def _ipc_sample(self, message) -> None:
        """Add one received measurement; a replayed sample is deduplicated."""
        if self.closed:
            return
        if message.seq is not None:
            if message.seq == self._ipc_seq:
                return
            self._ipc_seq = message.seq
        now = time.monotonic()
        # Keep the publisher's original capture time for display; local monotonic
        # time only orders the sample inside the shared window.
        wall = message.timestamp / 1000 if message.timestamp is not None else time.time()
        self.window.add(message.bpm, now, wall, self.segment)
        for view in self._views.values():
            view["window"].add(message.bpm, now, wall, self.segment)
        self.last_monotonic, self.last_wall = now, wall
        if self.state == "connected":
            self.current = message.bpm
        self._dirty = True

    def _ipc_status(self, message) -> None:
        """Mirror the publisher state; history is kept, live data cleared on loss."""
        if self.closed:
            return
        if message.state == "connected":
            self.state = "connected"
            self.error = ""
        elif message.state == "error":
            self.state = "error"
            self.error = message.error or "发布端报告错误"
            self.current = None
        else:
            self.state = "disconnected"
            self.error = ""
            self.current = None
        self._publish()

    def _ipc_link(self, state: str) -> None:
        """Track the TCP link only; the publisher status decides the data state."""
        if self.closed:
            return
        if state == "connected":
            # A new TCP session starts a new segment so the graph breaks the line.
            self.segment += 1
            self.state = "connecting"
            self.error = ""
            self._logged_errors.clear()
        else:
            self.state = "reconnecting"
            self.current = None
        self._publish()

    def _ipc_error(self, text: str) -> None:
        self.error = text
        self._report_error("ipc", f"心率 IPC 连接失败：{text}")

    async def select(self, address: str | None, name: str = "", restoring: bool = False) -> None:
        """Select a source or manually disconnect; wait for old resources first."""
        if self.config.source != "ble":
            return
        async with self._select_lock:
            if self.closed or self._quarantined:
                return
            if address == self.address and self.connection_task and not self.connection_task.done():
                return
            await self.stop_scan()
            await self._cancel(self.connection_task)
            self.connection_task = None
            # Manual disconnect suppresses reconnection for this session, not the
            # persisted startup default. History is retained, never gap-filled.
            self.current = None
            if address != self.address and address is not None:
                self.window = SampleWindow(self.window.seconds)
                self._graph_revision = -1
                for view in self._views.values():
                    view["window"] = SampleWindow(view["graph"].window_seconds)
                    view["revision"] = -1
                self.last_wall = self.last_monotonic = None
            self.address = address
            self.name = name or (self.devices.get(address, {}).get("name", "") if address else "")
            self.state = "disconnected"
            self.error = ""
            if address and not self._quarantined:
                self.devices.setdefault(
                    address, {"address": address, "name": self.name or "未命名设备", "rssi": None, "verified": None}
                )
                self.connection_task = asyncio.create_task(self._connection_loop(restoring))
            self._publish()

    @staticmethod
    async def _cancel(task) -> None:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _characteristic(self, client):
        service = client.services.get_service(HR_SERVICE_UUID)
        if service:
            for characteristic in service.characteristics:
                if characteristic.uuid.lower() == HR_MEASUREMENT_UUID and "notify" in characteristic.properties:
                    return characteristic
        raise ValueError("设备不支持标准心率通知（0x180D / 0x2A37）")

    async def _cleanup(self, client, characteristic=None) -> None:
        # Always disconnect even when stop_notify fails. A failed disconnect is
        # fail-closed: do not open another client and multiply leaked resources.
        if characteristic and client.is_connected:
            try:
                async with asyncio.timeout(self.config.connection.connect_timeout / 1000):
                    await client.stop_notify(characteristic)
            except Exception:
                self._report_error("stop-notify", "停止心率通知失败")
        try:
            async with asyncio.timeout(self.config.connection.connect_timeout / 1000):
                await client.disconnect()
        except Exception:
            self._quarantined = True
            self.error = "蓝牙连接清理失败，请重新启动 YASB 后重试"
            logger.exception("Unable to release heart rate BLE client; further connections disabled")

    async def _connection_loop(self, restoring: bool) -> None:
        retry = restoring
        while not self.closed:
            self.state = "reconnecting" if retry else "connecting"
            self.current = None
            self._publish()
            client = None
            characteristic = None
            lost = asyncio.Event()
            try:
                client = self.client_factory(
                    self.runtime_devices.get(self.address, self.address),
                    disconnected_callback=lambda _: lost.set(),
                    timeout=self.config.connection.connect_timeout / 1000,
                )
                async with asyncio.timeout(self.config.connection.connect_timeout / 1000):
                    await client.connect()
                    characteristic = self._characteristic(client)
                    self.segment += 1
                    segment = self.segment

                    # Backend callbacks are delivered on this loop by Bleak.
                    # Malformed payloads are ignored; the callback must never
                    # raise into Bleak's notification dispatch.
                    def notify(_sender, payload):
                        if self.closed or lost.is_set() or segment != self.segment:
                            return
                        try:
                            value = parse_measurement(payload)
                            if value is None:
                                logger.debug("Ignoring malformed heart rate payload (%d bytes)", len(payload))
                                return
                            now = time.monotonic()
                            wall = time.time()
                            self.window.add(value, now, wall, segment)
                            for view in self._views.values():
                                view["window"].add(value, now, wall, segment)
                            self.current = value
                            self.last_monotonic, self.last_wall = now, wall
                            self.state = "connected"
                            if self._publisher is not None:
                                self._publisher.publish(value, wall)
                            self._dirty = True
                        except Exception as error:
                            self._report_error("notify", f"心率数据处理失败：{type(error).__name__}：{error}")
                            logger.debug("Heart rate notification exception detail", exc_info=True)

                    await client.start_notify(characteristic, notify)
                self.state = "connected"
                self.error = ""
                self._logged_errors.clear()
                connected_at = time.monotonic()
                self.devices[self.address]["verified"] = True
                self._remember()
                self._publish()
                while not lost.is_set():
                    age = time.monotonic() - (self.last_monotonic if self.current is not None else connected_at)
                    if age >= self.config.connection.stale_timeout / 1000 and self.state != "stale":
                        self.current = None
                        self.state = "stale"
                        self._publish()
                    try:
                        await asyncio.wait_for(
                            lost.wait(), timeout=min(0.2, self.config.connection.stale_timeout / 1000)
                        )
                    except TimeoutError:
                        continue
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                self.error = "连接或心率通知订阅超时"
                self._report_error("timeout", self.error)
            except ValueError as error:
                self.error = str(error)
                self.devices[self.address]["verified"] = False
                self._report_error("service", self.error)
            except Exception as error:
                self.error = f"连接失败：{type(error).__name__}：{error}"
                self._report_error("connect", self.error)
            finally:
                lost.set()
                if client is not None:
                    await self._cleanup(client, characteristic)
                self.current = None
            if self._quarantined:
                self.state = "disconnected"
                self._publish()
                return
            self.state = "reconnecting"
            self._publish()
            # Retry delay is measured AFTER attempt and disconnect cleanup.
            await asyncio.sleep(self.config.connection.reconnect_interval / 1000)
            retry = True

    def _remember(self) -> None:
        record = self.saved.get(self.address)
        default_exists = any(record["auto_connect"] for record in self.saved.values())
        self.saved[self.address] = {
            "name": self.name or self.devices[self.address]["name"],
            "address": self.address,
            "auto_connect": record["auto_connect"] if record else not default_exists,
            "last_connected": time.time(),
        }
        self._save()

    def _save(self) -> None:
        try:
            self.store.save(self.saved)
            self.storage_error = ""
        except (OSError, ValueError):
            self.storage_error = "无法保存设备，请检查设备文件及权限"
            logger.exception("Unable to save heart rate devices")
        self._dirty = True

    async def set_default(self, address: str) -> None:
        """Persist one startup default; selecting it does not reconnect immediately."""
        if self.config.source != "ble" or address not in self.devices or self.closed:
            return
        device = self.devices[address]
        self.saved.setdefault(
            address, {"address": address, "name": device["name"], "auto_connect": False, "last_connected": None}
        )
        for key, record in self.saved.items():
            record["auto_connect"] = key == address
        self._save()
        self._publish()

    async def forget(self, address: str) -> None:
        """Remove a record, first disconnecting it if it is the current source."""
        if self.config.source != "ble" or self.closed:
            return
        if address == self.address:
            await self.select(None)
        self.saved.pop(address, None)
        self.devices.pop(address, None)
        self.runtime_devices.pop(address, None)
        self._save()
        self._publish()

    async def scan(self, deep: bool = False) -> None:
        """Begin incremental advertisements; deep mode also verifies GATT candidates."""
        if self.config.source != "ble":
            return
        async with self._scan_lock:
            if self.closed or self._quarantined or (self.scan_task and not self.scan_task.done()):
                return
            self.scan_task = asyncio.create_task(self._scan(deep))

    async def stop_scan(self) -> None:
        """Cancel scanner and await every temporary verification client cleanup."""
        if self.config.source != "ble":
            return
        async with self._scan_lock:
            await self._cancel(self.scan_task)
            self.scan_task = None

    async def _scan(self, deep: bool) -> None:
        self.scanning = True
        self._publish()
        semaphore = asyncio.Semaphore(self.config.connection.scan_concurrency)
        tasks = {}
        failures = []

        def detected(device, advertisement):
            advertised = HR_SERVICE_UUID in [uuid.lower() for uuid in advertisement.service_uuids]
            if not deep and not advertised and device.address not in self.saved:
                return
            self.runtime_devices[device.address] = device
            entry = self.devices.setdefault(device.address, {"address": device.address, "verified": None})
            entry.update(
                name=advertisement.local_name or device.name or entry.get("name") or "未命名设备",
                rssi=advertisement.rssi,
                advertised=advertised,
            )
            self._dirty = True
            if deep and device.address != self.address and device.address not in tasks:
                entry["verifying"] = True
                tasks[device.address] = asyncio.create_task(verify(device))

        async def verify(device, serial_retry=False):
            async with semaphore:
                if self.closed or self._quarantined or device.address == self.address:
                    return
                client = None
                entry = self.devices[device.address]
                try:
                    client = self.client_factory(device, timeout=self.config.connection.connect_timeout / 1000)
                    async with asyncio.timeout(self.config.connection.connect_timeout / 1000):
                        await client.connect()
                        self._characteristic(client)
                    entry.update(verified=True, error="")
                except asyncio.CancelledError:
                    raise
                except ValueError as error:
                    entry.update(verified=False, error=str(error))
                except Exception as error:
                    entry.update(verified=None, error=f"验证失败：{type(error).__name__}：{error}")
                    if not serial_retry:
                        failures.append(device)
                    logger.warning("Heart rate candidate verification failed: %s", type(error).__name__)
                finally:
                    if client is not None:
                        await self._cleanup(client)
                    entry["verifying"] = False
                    self._publish()

        try:
            # No service filter in deep mode: devices with omitted UUIDs or names
            # remain candidates. Only advertisements are used in ordinary scans.
            async with self.scanner_factory(detection_callback=detected):
                await asyncio.sleep(self.config.connection.scan_timeout / 1000)
            if tasks:
                await asyncio.gather(*tasks.values())
            if failures and self.config.connection.scan_concurrency > 1 and not self._quarantined:
                logger.info("Retrying failed BLE candidate verification serially")
                for device in failures:
                    if self._quarantined:
                        break
                    self.devices[device.address]["verifying"] = True
                    await verify(device, serial_retry=True)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.error = f"扫描失败：{type(error).__name__}：{error}"
            logger.exception("Heart rate device scan failed")
        finally:
            for task in tasks.values():
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks.values(), return_exceptions=True)
            self.scanning = False
            self._publish()

    def _sync_publisher(self) -> None:
        """Forward the current data state to IPC clients as a status message."""
        if self._publisher is None:
            return
        if self.state == "connected":
            self._publisher.set_state("connected")
        elif self.error:
            self._publisher.set_state("error", self.error)
        else:
            self._publisher.set_state("disconnected")

    def _publish(self) -> None:
        if self.closed:
            return
        self._sync_publisher()
        now = time.monotonic()
        stats = self.window.statistics(now)
        stats["current"] = self.current if self.state == "connected" and self.window.samples else None
        if self._graph_revision != self.window.revision:
            # Limit GUI work to <=4 points/pixel/segment. Statistics always use
            # the unmodified raw deque and are computed on this background loop.
            self._graph_points = graph_segments(
                list(self.window.samples),
                now,
                self.window.seconds,
                self.config.graph.width,
                GAP_SECONDS,
                self.config.graph.gap_on_disconnect,
            )
            self._graph_revision = self.window.revision
        devices = {}
        for address, device in self.devices.items():
            devices[address] = {
                **device,
                "saved": address in self.saved,
                "auto_connect": self.saved.get(address, {}).get("auto_connect", False),
                "state": self.state if address == self.address else "disconnected",
            }
        views = {}
        for key, view in self._views.items():
            window, graph = view["window"], view["graph"]
            statistics = window.statistics(now)
            statistics["current"] = self.current if self.state == "connected" and window.samples else None
            if view["revision"] != window.revision:
                view["segments"] = graph_segments(
                    list(window.samples), now, window.seconds, graph.width, GAP_SECONDS, graph.gap_on_disconnect
                )
                view["revision"] = window.revision
            views[key] = {"statistics": statistics, "segments": view["segments"], "revision": window.revision}
        self.emit(
            {
                "state": self.state,
                "error": self.error,
                "storage_error": self.storage_error,
                "address": self.address,
                "name": self.name,
                "last_wall": self.last_wall,
                "statistics": stats,
                "segments": self._graph_points,
                "revision": self.window.revision,
                "now": now,
                "devices": devices,
                "scanning": self.scanning,
                "views": views,
            }
        )
        self._dirty = False

    async def _refresh_loop(self) -> None:
        while not self.closed:
            await asyncio.sleep(0.2)
            if self.window.prune(time.monotonic()):
                self._dirty = True
            for view in self._views.values():
                if view["window"].prune(time.monotonic()):
                    self._dirty = True
            if self._dirty:
                self._publish()

    async def close(self) -> None:
        """Permanently cancel scans/retries, release clients, and stop refresh work."""
        async with self._select_lock:
            if self.closed:
                return
            self.closed = True
            await self.stop_scan()
            await self._cancel(self.connection_task)
            self.connection_task = None
            if self._subscriber_task is not None:
                await self._cancel(self._subscriber_task)
                self._subscriber_task = None
            if self._publisher is not None:
                await self._publisher.close()
                self._publisher = None
            await self._cancel(self._ticker)
            self._ticker = None
