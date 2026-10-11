from datetime import datetime
from itertools import count

from PyQt6.QtCore import QEvent, QPointF, QSize, Qt, QTimer
from PyQt6.QtGui import QPainter, QPainterPath, QPalette, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.utils.tooltip import set_tooltip
from core.utils.utilities import PopupWidget, refresh_widget_style
from core.validation.widgets.yasb.heart_rate import HeartRateConfig
from core.widgets.base import BaseWidget
from core.widgets.services.heart_rate.data import GAP_SECONDS, graph_segments, y_bounds
from core.widgets.services.heart_rate.service import HeartRateService

STATE_LABELS = {
    "disconnected": "未连接",
    "connecting": "正在连接",
    "connected": "已连接",
    "reconnecting": "正在重新连接",
    "stale": "数据已过期",
    "error": "错误",
}
COMPACT_LABELS = {
    "current": "HR",
    "avg": "Ø",
    "min": "↓",
    "max": "↑",
    "median": "MED",
    "stddev": "σ",
    "range": "Δ",
    "sample_count": "N",
}
DETAILED_LABELS = {
    "current": "HR",
    "avg": "AVG",
    "min": "MIN",
    "max": "MAX",
    "median": "MED",
    "stddev": "σ",
    "range": "Δ",
    "sample_count": "N",
}
_LINE_WIDTH = 1.6
# Horizontal breathing room between the graph, separator and statistics.
_GRAPH_GAP_PX = 5
_view_keys = count(1)


def format_statistic(value) -> str:
    """Compact integer/one-decimal presentation; missing measurements are not zero."""
    if value is None:
        return "--"
    return f"{value:.1f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)


class HeartRateGraph(QWidget):
    """Antialiased true heart-rate sparkline with layout-allocated height."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setProperty("class", "sparkline")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Ignored)
        self.setFixedWidth(config.width)
        self.segments = []
        self.now = 0
        self.average = None
        self.grid_style = QLabel(self)
        self.grid_style.setProperty("class", "grid")
        self.average_style = QLabel(self)
        self.average_style.setProperty("class", "average-line")
        self.grid_style.hide()
        self.average_style.hide()

    def sizeHint(self):
        return QSize(self.config.width, 0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(3, 3, -3, -3)
        if rect.width() <= 0 or rect.height() <= 0:
            return
        values = [sample.value for segment in self.segments for sample in segment]
        low, high = y_bounds(values, self.config.min_y_range)

        def point(sample):
            x = (
                rect.left()
                + (sample.monotonic - self.now + self.config.window_seconds) / self.config.window_seconds * rect.width()
            )
            y = rect.bottom() - (sample.value - low) / (high - low) * rect.height()
            return QPointF(x, y)

        painter.setClipRect(self.rect())
        if self.config.show_grid:
            color = self.grid_style.palette().color(QPalette.ColorRole.WindowText)
            color.setAlphaF(color.alphaF() * 0.2)
            painter.setPen(QPen(color, 1, Qt.PenStyle.DotLine))
            for fraction in (0.25, 0.5, 0.75):
                y = rect.top() + rect.height() * fraction
                painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        if self.config.show_average_line and self.average is not None:
            y = rect.bottom() - (self.average - low) / (high - low) * rect.height()
            # Keep the reference line visible but subdued: it must not compete
            # with the live curve for visual attention.
            color = self.average_style.palette().color(QPalette.ColorRole.WindowText)
            color.setAlphaF(color.alphaF() * 0.45)
            painter.setPen(QPen(color, 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        pen = QPen(self.palette().color(QPalette.ColorRole.WindowText), _LINE_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        if not self.segments:
            # Idle placeholder: a flat line instead of an empty graph area.
            # It is purely visual and is never added to the sample buffer.
            y = rect.center().y()
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            return
        for segment in self.segments:
            # A narrower allocation may need a second pixel reduction. Never
            # merge segments, interpolate across outages, or modify raw samples.
            reduced = graph_segments(
                segment, self.now, self.config.window_seconds, rect.width(), GAP_SECONDS, self.config.gap_on_disconnect
            )
            for points in reduced:
                if len(points) == 1:
                    painter.drawPoint(point(points[0]))
                elif points:
                    path = QPainterPath(point(points[0]))
                    for sample in points[1:]:
                        path.lineTo(point(sample))
                    painter.drawPath(path)
        if self.config.show_latest_point and self.segments:
            painter.setBrush(pen.color())
            painter.drawEllipse(point(self.segments[-1][-1]), 2, 2)


class HeartRateWidget(BaseWidget):
    """Heart rate source (BLE or IPC) shown in normal/detailed, height-adaptive layouts."""

    validation_schema = HeartRateConfig

    def __init__(self, config: HeartRateConfig):
        classes = " ".join(dict.fromkeys(["heart-rate-widget", *config.class_name.split()]))
        super().__init__(class_name=classes)
        self.config = config
        self._classes = classes
        self.mode = config.display.default_mode
        self._shutdown = False
        self._snapshot = {}
        self._pending_snapshot = None
        self._graph_key = None
        self._view_key = f"heart-rate-view-{next(_view_keys)}"
        self.popup = None
        self.device_rows = {}
        self._build_layout()
        self.register_callback("toggle_device_menu", self.toggle_device_menu)
        self.register_callback("toggle_display_mode", self.toggle_display_mode)
        self.callback_left = config.callbacks.on_left
        self.callback_middle = config.callbacks.on_middle
        self.callback_right = config.callbacks.on_right
        self._service = HeartRateService.acquire(config)
        self._service.updated.connect(self._queue_snapshot)
        self._service.submit("add_view", self._view_key, config.graph)
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(200)
        self._flush_timer.timeout.connect(self._flush_snapshot)
        self._apply_snapshot({"state": "disconnected"})
        self._set_mode()
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    @staticmethod
    def _layout(layout):
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        return layout

    def _build_layout(self):
        self.normal = QFrame()
        self.normal.setProperty("class", "normal")
        normal_layout = self._layout(QHBoxLayout(self.normal))
        normal_layout.setSpacing(_GRAPH_GAP_PX)
        self.graph = HeartRateGraph(self.config.graph)
        normal_layout.addWidget(self.graph, 1)
        self.separator = QFrame()
        self.separator.setProperty("class", "separator")
        self.separator.setFrameShape(QFrame.Shape.VLine)
        # Pin the frame width; Qt's VLine primitives otherwise reserve several
        # pixels and shift the visible line away from the text gap.
        self.separator.setFixedWidth(1)
        normal_layout.addWidget(self.separator)
        text = QFrame()
        text.setProperty("class", "statistics")
        text.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        column = self._layout(QVBoxLayout(text))
        self.current_label = QLabel("-- bpm")
        self.current_label.setProperty("class", "current")
        self.current_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        self.current_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        column.addWidget(self.current_label, 3)
        self.summary = QFrame()
        self.summary.setProperty("class", "summary")
        column.addWidget(self.summary, 2)
        self.normal_values = self._stat_labels(self.summary, self.config.display.normal, COMPACT_LABELS)
        normal_layout.addWidget(text)
        self.detailed = QFrame()
        self.detailed.setProperty("class", "detailed")
        self.detailed_values = self._stat_labels(self.detailed, self.config.display.detailed, DETAILED_LABELS)
        self.widget_layout.addWidget(self.normal)
        self.widget_layout.addWidget(self.detailed)

    def _stat_labels(self, frame, config, labels_map):
        layout = self._layout(QHBoxLayout(frame))
        layout.setSpacing(config.spacing)
        result = []
        for index, statistic in enumerate(config.statistics):
            if index:
                separator = QLabel(config.separator)
                separator.setProperty("class", "stat-separator")
                separator.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
                layout.addWidget(separator)
            label = QLabel(f"{labels_map[statistic]} --")
            label.setProperty("class", f"stat {statistic}")
            label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
            label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(label)
            result.append(label)
        return result

    def _set_mode(self):
        detailed = self.mode == "detailed"
        self.normal.setVisible(not detailed)
        self.detailed.setVisible(detailed)
        self.graph.setVisible(not detailed and self.config.graph.enabled)
        self.separator.setVisible(not detailed and self.config.graph.enabled)
        self.updateGeometry()

    def toggle_display_mode(self):
        """Switch bar layouts only, without touching the connection or data window."""
        self.mode = "detailed" if self.mode == "normal" else "normal"
        self._set_mode()

    def _queue_snapshot(self, snapshot):
        if not self._shutdown:
            self._pending_snapshot = snapshot
            if not self._flush_timer.isActive():
                self._flush_timer.start()

    def _flush_snapshot(self):
        if self._pending_snapshot is not None:
            snapshot, self._pending_snapshot = self._pending_snapshot, None
            self._apply_snapshot(snapshot)

    def _apply_snapshot(self, snapshot):
        if self._shutdown:
            return
        snapshot = {**snapshot, **snapshot.get("views", {}).get(self._view_key, {})}
        state = snapshot.get("state", "disconnected")
        previous_state = self._snapshot.get("state")
        self._snapshot = snapshot
        if previous_state != state:
            self._widget_frame.setProperty("class", f"widget {self._classes} {state}")
            refresh_widget_style(self._widget_frame, *self._widget_frame.findChildren(QWidget))
        statistics = snapshot.get("statistics", {})
        self.current_label.setText(
            f"{format_statistic(statistics.get('current') if state == 'connected' else None)} bpm"
        )
        for config, labels, labels_map in (
            (self.config.display.normal, self.normal_values, COMPACT_LABELS),
            (self.config.display.detailed, self.detailed_values, DETAILED_LABELS),
        ):
            for statistic, label in zip(config.statistics, labels):
                value = statistics.get(statistic)
                if statistic == "current" and state != "connected":
                    value = None
                label.setText(f"{labels_map[statistic]} {format_statistic(value)}")
        key = (snapshot.get("revision"), state)
        if key != self._graph_key:
            self._graph_key = key
            self.graph.segments = snapshot.get("segments", [])
            self.graph.now = snapshot.get("now", 0)
            self.graph.average = statistics.get("avg")
            self.graph.update()
        last = snapshot.get("last_wall")
        last_text = datetime.fromtimestamp(last).strftime("%Y-%m-%d %H:%M:%S") if last is not None else "尚未收到"
        source_text = (
            f"IPC：{self.config.ipc.host}:{self.config.ipc.port}"
            if self.config.source == "ipc"
            else f"设备：{snapshot.get('name') or '未选择'}"
        )
        set_tooltip(
            self,
            f"{source_text}\n"
            f"状态：{STATE_LABELS.get(state, state)}\n最近有效数据：{last_text}\n"
            f"统计窗口：{self.config.graph.window_seconds} 秒",
        )
        self._update_menu()

    def _build_menu(self):
        menu = self.config.menu_config
        self.popup = PopupWidget(
            self, menu.blur, menu.round_corners, menu.round_corners_type, menu.border_color, persistent=True
        )
        self.popup.setProperty("class", "heart-rate-menu")
        root = QVBoxLayout(self.popup)
        title = QLabel("心率设备")
        title.setProperty("class", "title")
        root.addWidget(title)
        self.menu_status = QLabel()
        self.menu_status.setProperty("class", "status")
        self.menu_status.setWordWrap(True)
        root.addWidget(self.menu_status)
        self.device_list = QListWidget()
        self.device_list.setProperty("class", "devices")
        self.device_list.setMinimumWidth(340)
        self.device_list.setMinimumHeight(180)
        self.device_list.currentItemChanged.connect(lambda *_: self._update_buttons())
        root.addWidget(self.device_list)
        self.menu_error = QLabel()
        self.menu_error.setProperty("class", "error")
        self.menu_error.setWordWrap(True)
        self.menu_error.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.menu_error)
        scan_row = QHBoxLayout()
        root.addLayout(scan_row)
        self.scan_button = self._button(scan_row, "开始扫描", lambda: self._service.submit("scan", False), "scan")
        self.deep_button = self._button(
            scan_row, "完整扫描并验证", lambda: self._service.submit("scan", True), "deep-scan"
        )
        self.stop_button = self._button(scan_row, "停止扫描", lambda: self._service.submit("stop_scan"), "stop-scan")
        actions = QHBoxLayout()
        root.addLayout(actions)
        self.connect_button = self._button(actions, "连接", self._connect_selected, "connect")
        self.disconnect_button = self._button(
            actions, "断开连接", lambda: self._service.submit("select", None), "disconnect"
        )
        self.default_button = self._button(
            actions, "设为默认", lambda: self._selected_command("set_default"), "set-default"
        )
        self.forget_button = self._button(actions, "移除已保存设备", lambda: self._selected_command("forget"), "forget")
        self.popup.installEventFilter(self)
        self._update_menu()

    @staticmethod
    def _button(layout, text, callback, class_name):
        button = QPushButton(text)
        button.setProperty("class", class_name)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _selected_address(self):
        item = self.device_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected_command(self, command):
        address = self._selected_address()
        if address:
            self._service.submit(command, address)

    def _connect_selected(self):
        address = self._selected_address()
        if address:
            name = self._snapshot.get("devices", {}).get(address, {}).get("name", "")
            self._service.submit("select", address, name)

    def _update_menu(self):
        if self.popup is None:
            return
        devices = self._snapshot.get("devices", {})
        for address in set(self.device_rows) - set(devices):
            item = self.device_rows.pop(address)
            self.device_list.takeItem(self.device_list.row(item))
        for address, device in devices.items():
            if address not in self.device_rows:
                item = QListWidgetItem(self.device_list)
                item.setData(Qt.ItemDataRole.UserRole, address)
                self.device_rows[address] = item
            verified = device.get("verified")
            support = "支持心率通知" if verified is True else "不支持心率通知" if verified is False else "未验证"
            if device.get("verifying"):
                support = "正在验证"
            rssi = f"{device['rssi']} dBm" if device.get("rssi") is not None else "RSSI 不可用"
            default = " · 默认自动连接" if device.get("auto_connect") else ""
            text = f"{device['name']}{default}\n{address} · {rssi}\n{support} · {STATE_LABELS[device.get('state', 'disconnected')]}"
            item = self.device_rows[address]
            if item.text() != text:
                item.setText(text)
            item.setToolTip(device.get("error", ""))
        self.menu_status.setText(
            "正在扫描 / 验证设备…"
            if self._snapshot.get("scanning")
            else STATE_LABELS.get(self._snapshot.get("state", "disconnected"), "未连接")
        )
        errors = [self._snapshot.get("error"), self._snapshot.get("storage_error")]
        self.menu_error.setText("\n".join(error for error in errors if error))
        self.menu_error.setVisible(bool(self.menu_error.text()))
        self._update_buttons()

    def _update_buttons(self):
        address = self._selected_address()
        device = self._snapshot.get("devices", {}).get(address, {})
        scanning = self._snapshot.get("scanning", False)
        self.scan_button.setEnabled(not scanning)
        self.deep_button.setEnabled(not scanning)
        self.stop_button.setEnabled(scanning)
        self.connect_button.setEnabled(bool(address) and address != self._snapshot.get("address"))
        self.disconnect_button.setEnabled(self._snapshot.get("state") != "disconnected")
        self.default_button.setEnabled(bool(address) and not device.get("auto_connect"))
        self.forget_button.setEnabled(bool(device.get("saved")))

    def toggle_device_menu(self):
        """Open/close the BLE device popup; the IPC source has no device manager."""
        if self.config.source != "ble":
            return
        if self.popup is None:
            self._build_menu()
        if self.popup.isVisible():
            self.popup.hide_animated()
        else:
            self._update_menu()
            menu = self.config.menu_config
            self.popup.adjustSize()
            self.popup.setPosition(menu.alignment, menu.direction, menu.offset_left, menu.offset_top)
            self.popup.show()

    def eventFilter(self, obj, event):
        if obj is self.popup and event.type() == QEvent.Type.Hide and not self._shutdown:
            self._service.submit("stop_scan")
        return super().eventFilter(obj, event)

    def shutdown(self, *_args):
        """Detach signals before QObject destruction; final subscriber stops BLE."""
        if self._shutdown:
            return
        self._shutdown = True
        self._flush_timer.stop()
        self._service.updated.disconnect(self._queue_snapshot)
        self._service.submit("remove_view", self._view_key)
        self._service.release()
        # The shared class-level hotkey signal disconnects itself when this
        # instance is destroyed; unregistering it would break other widgets.
        QApplication.instance().aboutToQuit.disconnect(self.shutdown)
        if self.popup:
            self.popup.hide()
            self.popup.deleteLater()
            self.popup = None

    def event(self, event):
        if event.type() == QEvent.Type.DeferredDelete:
            self.shutdown()
        return super().event(event)

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
