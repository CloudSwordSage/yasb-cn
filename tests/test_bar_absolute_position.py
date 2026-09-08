import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtWidgets import QApplication, QFrame

from core.bar import Bar
from core.validation.bar import BarConfig


class BarAbsolutePositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_absolute_position_defaults_to_disabled_and_accepts_bool(self) -> None:
        self.assertFalse(BarConfig().absolute_position)
        self.assertTrue(BarConfig(absolute_position=True).absolute_position)

    def test_absolute_position_anchors_each_widget_group(self) -> None:
        bar = Bar.__new__(Bar)
        bar.config = BarConfig(absolute_position=True)
        bar._bar_id = "test-bar"
        bar.monitor_hwnd = 0
        bar._bar_frame = QFrame()
        bar._bar_frame.resize(600, 30)

        left, center, right = QFrame(), QFrame(), QFrame()
        left.setFixedSize(120, 20)
        center.setFixedSize(80, 20)
        right.setFixedSize(40, 20)

        Bar._add_widgets(bar, {"left": [left], "center": [center], "right": [right]})
        bar._bar_frame.show()
        self.app.processEvents()

        self.assertEqual(left.mapTo(bar._bar_frame, left.rect().topLeft()).x(), 0)
        self.assertEqual(center.mapTo(bar._bar_frame, center.rect().center()).x(), 299)
        self.assertEqual(right.mapTo(bar._bar_frame, right.rect().topRight()).x(), 599)


if __name__ == "__main__":
    unittest.main()
