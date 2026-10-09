import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtCore import QCoreApplication, QEvent, QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget

from core.validation.widgets.yasb.heart_rate import HeartRateConfig
from core.widgets.services.heart_rate.data import Sample


class FakeService(QObject):
    updated = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.commands = []
        self.released = 0

    def submit(self, command, *args):
        self.commands.append((command, args))

    def release(self):
        self.released += 1


def snapshot(state="connected", value=67):
    return {
        "state": state,
        "name": "Watch",
        "address": "A",
        "last_wall": 100,
        "statistics": {
            "current": value if state == "connected" else None,
            "avg": 68,
            "min": 58,
            "max": 76,
            "median": 67,
            "stddev": 4.2,
            "range": 18,
            "sample_count": 60,
        },
        "segments": [[Sample(65, 0, 100, 1), Sample(68, 1, 101, 1)]],
        "revision": 1,
        "now": 1,
        "error": "",
        "storage_error": "",
        "scanning": False,
        "devices": {
            "A": {
                "name": "Watch",
                "address": "A",
                "rssi": -50,
                "verified": True,
                "saved": True,
                "auto_connect": True,
                "state": state,
            }
        },
    }


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        try:
            self.module = importlib.import_module("core.widgets.yasb.heart_rate")
        except ModuleNotFoundError as error:
            self.fail(f"HeartRateWidget missing: {error}")
        self.service = FakeService()
        self.config = HeartRateConfig(
            display={
                "normal": {"statistics": ["max", "avg"]},
                "detailed": {"statistics": ["sample_count", "stddev", "current"]},
            }
        )
        with patch.object(self.module.HeartRateService, "acquire", return_value=self.service):
            self.widget = self.module.HeartRateWidget(self.config)
        self._widget_deleted = False

        def cleanup():
            if self._widget_deleted:
                return
            self.widget.shutdown()
            self.widget.deleteLater()

        self.addCleanup(cleanup)

    def test_registration_and_modes_do_not_connect(self):
        from core.widgets.registry import WIDGET_REGISTRY

        self.assertIs(WIDGET_REGISTRY["yasb.heart_rate.HeartRateWidget"], self.module.HeartRateWidget)
        self.widget._apply_snapshot(snapshot())
        self.assertEqual(self.widget.current_label.text(), "67 bpm")
        self.assertEqual([label.text() for label in self.widget.normal_values], ["↑ 76", "Ø 68"])
        self.widget.toggle_display_mode()
        self.assertEqual(self.widget.mode, "detailed")
        self.assertTrue(self.widget.graph.isHidden())
        self.assertEqual([label.text() for label in self.widget.detailed_values], ["N 60", "σ 4.2", "HR 67"])
        self.widget.toggle_display_mode()
        self.assertEqual(self.widget.mode, "normal")
        # Only the per-widget view registration is sent; mode switching never
        # issues connection commands.
        self.assertEqual([command for command, _ in self.service.commands if command != "add_view"], [])

    def test_independent_state_classes_and_tooltip(self):
        for state in ("disconnected", "connecting", "reconnecting", "stale", "connected"):
            self.widget._apply_snapshot(snapshot(state))
            self.assertIn(state, self.widget._widget_frame.property("class").split())
            tooltip = self.widget._tooltip_filter.tooltip_text
            self.assertIn("Watch", tooltip)
            self.assertIn("60 秒", tooltip)
            if state != "connected":
                self.assertEqual(self.widget.current_label.text(), "-- bpm")

    def test_popup_rows_update_in_place(self):
        self.widget._build_menu()
        self.widget._apply_snapshot(snapshot())
        first = self.widget.device_rows["A"]
        update = snapshot()
        update["devices"]["A"]["rssi"] = -60
        update["devices"]["B"] = {
            "address": "B",
            "name": "未命名设备",
            "rssi": None,
            "verified": None,
            "state": "disconnected",
            "auto_connect": False,
        }
        self.widget._apply_snapshot(update)
        self.assertIs(self.widget.device_rows["A"], first)
        self.assertEqual(len(self.widget.device_rows), 2)
        self.assertIn("-60", first.text())
        self.assertIn("未验证", self.widget.device_rows["B"].text())

    def test_graph_paints_empty_single_peak_and_resizes_with_height(self):
        parent = QWidget()
        parent.resize(300, 24)
        self.widget.setParent(parent)
        self.widget.resize(260, 24)
        self.widget.show()
        parent.show()
        self.widget.graph.setStyleSheet(".sparkline { color: #ff0000; }")
        for height in (24, 40, 80):
            parent.resize(300, height)
            self.widget.resize(260, height)
            for samples in ([], [Sample(67, 1, 101, 1)], [Sample(40, 0, 100, 1), Sample(220, 1, 101, 1)]):
                event = snapshot()
                event["segments"] = [samples] if samples else []
                event["revision"] = height + len(samples)
                self.widget._apply_snapshot(event)
                self.app.processEvents()
                pixmap = self.widget.graph.grab()
                self.assertFalse(pixmap.isNull())
                self.assertGreater(self.widget.graph.height(), 0)
                self.assertLessEqual(self.widget.graph.height(), height)
                if not samples:
                    # Without any sample the graph must still show an idle
                    # baseline instead of an empty area.
                    image = pixmap.toImage()
                    center = image.height() // 2
                    hit = any(
                        image.pixelColor(x, y).red() > 150
                        for y in range(max(0, center - 2), min(image.height(), center + 3))
                        for x in range(6, image.width() - 6, 6)
                    )
                    self.assertTrue(hit, "empty graph should draw an idle baseline")
        parent.hide()
        self.widget.setParent(None)
        parent.deleteLater()

    def test_deferred_delete_releases_once(self):
        self.widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self._widget_deleted = True
        self.assertEqual(self.service.released, 1)


class ThreadTests(unittest.TestCase):
    def test_worker_shutdown_and_recreation_leave_no_threads(self):
        try:
            module = importlib.import_module("core.widgets.services.heart_rate.service")
        except ModuleNotFoundError as error:
            self.fail(f"BLE thread service missing: {error}")
        app = QApplication.instance() or QApplication([])
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(module, "DEVICES_PATH", Path(folder) / "devices.json"),
        ):
            config = HeartRateConfig(connection={"auto_connect": False})
            for _ in range(2):
                service = module.HeartRateService.acquire(config)
                other = module.HeartRateService.acquire(config)
                self.assertIs(service, other)
                service.release()
                self.assertTrue(service.thread.is_alive())
                other.release()
                service.thread.join(3)
                self.assertFalse(service.thread.is_alive())
                app.processEvents()


if __name__ == "__main__":
    unittest.main()
