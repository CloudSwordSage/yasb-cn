import asyncio
import atexit
import logging
import sys
import threading
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from core.validation.widgets.yasb.heart_rate import HeartRateConfig
from core.widgets.services.heart_rate.ble import HeartRateBackend
from core.widgets.services.heart_rate.store import DeviceStore
from settings import DEFAULT_CONFIG_DIRECTORY

logger = logging.getLogger(__name__)

# Persisted device records live next to the YASB configuration files so users
# can back up or copy a portable YASB folder in one place.
DEVICES_PATH = Path(DEFAULT_CONFIG_DIRECTORY) / "heart_rate_devices.json"


class HeartRateService(QObject):
    """Reference-counted shared source; one persistent asyncio thread for all bars.

    Signal emissions are guarded against teardown. Commands are thread-safely
    scheduled and awaited on the BLE loop, never on Qt's main thread. Connection
    settings must agree across views of this single application-wide source.
    """

    updated = pyqtSignal(dict)
    _instance = None
    _retiring = []

    @classmethod
    def acquire(cls, config: HeartRateConfig):
        """Acquire the shared source on the Qt thread; reject conflicting settings."""
        if cls._instance is None:
            cls._instance = cls(config)
        elif (cls._instance.config.source, cls._instance.config.connection, cls._instance.config.ipc) != (
            config.source,
            config.connection,
            config.ipc,
        ):
            raise ValueError("同一心率数据源的所有小组件必须使用相同的 source、connection 和 ipc 配置")
        cls._instance._users += 1
        return cls._instance

    def __init__(self, config: HeartRateConfig):
        super().__init__()
        self.config = config
        self._users = 0
        self._lock = threading.Lock()
        self._closing = False
        self._loop = None
        self._backend = None
        self._pending = []
        self._stop = None
        self.thread = threading.Thread(target=self._run, name="YASB HeartRate", daemon=False)
        self.thread.start()
        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self.shutdown)
        atexit.register(self._join)

    def _emit(self, snapshot: dict) -> None:
        # The service stays alive until its worker exits. A release disables
        # emission under this lock before a subscriber QObject can be destroyed.
        with self._lock:
            if not self._closing:
                self.updated.emit(snapshot)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Do not allow_sta here: this thread has no Windows GUI message pump.
            # WinRT initializes MTA lazily; undo any accidental STA initialization
            # on THIS worker, without altering Qt/main-thread COM ownership.
            if sys.platform == "win32":
                try:
                    from bleak.backends.winrt.util import uninitialize_sta

                    uninitialize_sta()
                except Exception:
                    logger.debug("WinRT STA cleanup helper unavailable", exc_info=True)
            loop.run_until_complete(self._main(loop))
        except Exception:
            logger.exception("Heart rate worker failed")
            self._emit({"state": "disconnected", "error": "心率服务无法启动，请查看日志"})
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()
            with self._lock:
                self._loop = None
                # If the worker died before a normal shutdown, stop buffering
                # commands and emitting so a dead service can never grow state.
                self._closing = True
            logger.debug("Heart rate BLE worker stopped")

    async def _main(self, loop) -> None:
        self._stop = asyncio.Event()
        self._backend = HeartRateBackend(self.config, self._emit, DeviceStore(DEVICES_PATH))
        try:
            await self._backend.start()
            with self._lock:
                self._loop = loop
                commands, self._pending = self._pending, []
                closing = self._closing
            for command, args in commands:
                self._schedule(command, args)
            if closing:
                self._stop.set()
            await self._stop.wait()
        finally:
            await self._backend.close()

    def submit(self, command: str, *args) -> None:
        """Nonblocking UI entry point; buffer commands until loop initialization."""
        with self._lock:
            if self._closing:
                return
            if self._loop is None:
                self._pending.append((command, args))
                return
            self._loop.call_soon_threadsafe(self._schedule, command, args)

    def _schedule(self, command, args):
        if self._closing or self._backend.closed:
            return
        task = asyncio.create_task(getattr(self._backend, command)(*args))
        task.add_done_callback(self._command_done)

    @staticmethod
    def _command_done(task):
        if not task.cancelled() and task.exception():
            logger.error("Heart rate command failed", exc_info=task.exception())

    def release(self) -> None:
        """Drop one view; the final release asynchronously tears down the worker."""
        self._users = max(0, self._users - 1)
        if self._users == 0:
            self.shutdown()

    def shutdown(self) -> None:
        """Disable signals before asynchronous client cleanup; never block UI."""
        with self._lock:
            if self._closing:
                return
            self._closing = True
            self._pending.clear()
            if self._loop:
                self._loop.call_soon_threadsafe(self._stop.set)
        if type(self)._instance is self:
            type(self)._instance = None
        type(self)._retiring.append(self)

    def _join(self) -> None:
        # atexit runs after Qt shutdown. Joining here (not in a mouse callback)
        # ensures the non-daemon worker and its WinRT resources are reclaimed.
        self.shutdown()
        if threading.current_thread() is not self.thread:
            self.thread.join(self.config.connection.connect_timeout / 500 + 2)
            if self.thread.is_alive():
                logger.error("Heart rate BLE worker did not stop within cleanup timeout")
        if not self.thread.is_alive() and self in type(self)._retiring:
            type(self)._retiring.remove(self)
        atexit.unregister(self._join)
