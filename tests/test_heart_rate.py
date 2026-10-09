import importlib
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def require(test, module):
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError as error:
        test.fail(f"Heart rate implementation missing: {error}")


class DataTests(unittest.TestCase):
    def setUp(self):
        self.data = require(self, "core.widgets.services.heart_rate.data")

    def test_uint8_and_uint16(self):
        self.assertEqual(self.data.parse_measurement(bytes([0, 67])), 67)
        self.assertEqual(self.data.parse_measurement(bytes([1, 44, 1])), 300)

    def test_optional_fields_and_lengths(self):
        self.assertEqual(self.data.parse_measurement(bytes([24, 67, 1, 0, 0, 4])), 67)
        for payload in (
            b"",
            b"\x00",
            b"\x01\x43",
            b"\x00\x43\x00",
            b"\x08\x43",
            b"\x10\x43",
            b"\x10\x43\x01",
            b"\x20\x43",
            b"\x00\x00",
        ):
            with self.subTest(payload=payload):
                self.assertIsNone(self.data.parse_measurement(payload))

    def test_empty_and_single_sample(self):
        window = self.data.SampleWindow(60)
        self.assertEqual(window.statistics(60)["sample_count"], 0)
        self.assertIsNone(window.statistics(60)["avg"])
        window.add(67, 60, 100, 1)
        result = window.statistics(60)
        self.assertEqual(result["current"], 67)
        self.assertEqual(result["stddev"], 0)

    def test_irregular_window_and_population_statistics(self):
        window = self.data.SampleWindow(60)
        for value, timestamp in [(10, 0), (60, 1), (70, 20), (80, 61)]:
            window.add(value, timestamp, 100 + timestamp, 1)
        result = window.statistics(61)
        self.assertEqual(
            result,
            {
                "current": 80,
                "avg": 70,
                "min": 60,
                "max": 80,
                "median": 70,
                "stddev": math.sqrt(200 / 3),
                "range": 20,
                "sample_count": 3,
            },
        )
        self.assertEqual(window.statistics(121)["sample_count"], 1)
        self.assertEqual(window.statistics(122)["sample_count"], 0)

    def test_no_fabrication_during_gap(self):
        window = self.data.SampleWindow(60)
        window.add(67, 0, 100, 1)
        window.add(76, 30, 130, 2)
        self.assertEqual(window.statistics(30)["sample_count"], 2)
        self.assertEqual(len(self.data.graph_segments(window.samples, 30, 60, 100, 10, True)), 2)
        self.assertEqual(window.statistics(61)["current"], 76)

    def test_downsampling_preserves_peaks_and_order(self):
        samples = [self.data.Sample(60 if i != 49 else 200, i / 100, 100, 1) for i in range(100)]
        for width in (1, 10, 200):
            segments = self.data.graph_segments(samples, 1, 1, width, 10, True)
            points = segments[0]
            self.assertIn(200, [sample.value for sample in points])
            self.assertEqual(points, sorted(points, key=lambda sample: sample.monotonic))
            self.assertLessEqual(len(points), max(width, 1) * 4)
        self.assertEqual(len(samples), 100)
        self.assertEqual(self.data.graph_segments([], 0, 60, 100, 10, True), [])

    def test_minimum_vertical_span(self):
        self.assertGreaterEqual(self.data.y_bounds([65, 68], 20)[1] - self.data.y_bounds([65, 68], 20)[0], 20)
        low, high = self.data.y_bounds([40, 220], 20)
        self.assertLess(low, 40)
        self.assertGreater(high, 220)


class ConfigTests(unittest.TestCase):
    def test_defaults_and_validation(self):
        module = require(self, "core.validation.widgets.yasb.heart_rate")
        from pydantic import ValidationError

        config = module.HeartRateConfig()
        self.assertEqual(config.display.normal.statistics, ["avg", "max"])
        self.assertEqual(config.connection.reconnect_interval, 2000)
        for value in (
            {"graph": {"height": 20}},
            {"graph": {"width": 0}},
            {"display": {"normal": {"statistics": ["unknown"]}}},
            {"connection": {"scan_concurrency": 0}},
            {"display": {"default_mode": "bad"}},
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                module.HeartRateConfig.model_validate(value)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.module = require(self, "core.widgets.services.heart_rate.store")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "devices.json"

    def test_save_deduplicate_default_and_restart(self):
        store = self.module.DeviceStore(self.path)
        self.assertEqual(store.load(), {})
        records = {"A": {"name": "Watch", "address": "A", "auto_connect": True, "last_connected": 100}}
        store.save(records)
        self.assertEqual(self.module.DeviceStore(self.path).load(), records)
        self.assertEqual(len(json.loads(self.path.read_text(encoding="utf-8"))), 1)

    def test_corrupt_file_is_not_silently_overwritten(self):
        self.path.write_text("broken", encoding="utf-8")
        store = self.module.DeviceStore(self.path)
        with self.assertRaises(ValueError):
            store.load()
        with self.assertRaises(ValueError):
            store.save({})
        self.assertEqual(self.path.read_text(), "broken")

    def test_failed_replace_keeps_previous_file(self):
        store = self.module.DeviceStore(self.path)
        store.save({})
        with patch("os.replace", side_effect=PermissionError("denied")), self.assertRaises(PermissionError):
            store.save({"B": {"address": "B", "name": "Watch", "auto_connect": False, "last_connected": None}})
        self.assertEqual(json.loads(self.path.read_text()), {})


if __name__ == "__main__":
    unittest.main()
