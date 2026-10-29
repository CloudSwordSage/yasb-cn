import datetime
import json
import logging
import os
import re
import time
import urllib.parse
from functools import partial

from PyQt6.QtCore import QDate, QLocale, QMimeData, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QDrag, QIcon, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.config import HOME_CONFIGURATION_DIR
from core.utils.tooltip import set_tooltip
from core.utils.utilities import PopupWidget, refresh_widget_style
from core.utils.win32.utils import apply_qmenu_style
from core.validation.widgets.yasb.todo import TodoConfig
from core.widgets.base import BaseWidget

# 时间状态只用于渲染与统计，不写入 todo.json，避免跨天后数据需要迁移。
_STATE_ORDER = {
    "overdue": 0,
    "today_overdue": 1,
    "today": 1,
    "tomorrow": 2,
    "soon": 3,
    "later": 4,
    "none": 5,
}
_STATE_GROUPS = (
    ("overdue", "逾期"),
    ("today", "今天"),
    ("tomorrow", "明天"),
    ("soon", "即将到期"),
    ("later", "以后"),
    ("none", "无期限"),
)
_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _parse_due_at(value: str | None) -> datetime.datetime | None:
    """解析 due_at，兼容仅日期（补 23:59）与完整 ISO 时间。"""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        if len(text) == 10:
            return datetime.datetime.combine(datetime.date.fromisoformat(text), datetime.time(23, 59))
        parsed = datetime.datetime.fromisoformat(text)
    except TypeError, ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _due_state(due_at: datetime.datetime | None, now: datetime.datetime, soon_days: int) -> str:
    """Return the display state for a due timestamp.

    States: overdue (before today), today_overdue (today but past), today,
    tomorrow, soon (within soon_days), later, none (no due date).
    """
    if due_at is None:
        return "none"
    due_date = due_at.date()
    today = now.date()
    if due_date < today:
        return "overdue"
    if due_date == today:
        return "today_overdue" if due_at < now else "today"
    if due_date == today + datetime.timedelta(days=1):
        return "tomorrow"
    if soon_days > 0 and due_date <= today + datetime.timedelta(days=soon_days):
        return "soon"
    return "later"


def _state_group(state: str) -> str:
    """Map both today states to the single "今天" group."""
    return "today" if state in ("today", "today_overdue") else state


def _completed_until(task: dict, fallback: datetime.date) -> datetime.date:
    """最后一天仍显示在“已完成”里（含）。

    无期限任务只保留完成当天；有截止日期的保留到截止日与完成日中较晚的一天。
    """
    completed = _parse_due_at(task.get("completed_at"))
    end = completed.date() if completed else fallback
    due = _parse_due_at(task.get("due_at"))
    if due and due.date() > end:
        end = due.date()
    return end


class TodoWidget(BaseWidget):
    validation_schema = TodoConfig
    _instances = []

    def __init__(self, config: TodoConfig):
        super().__init__(class_name="todo-widget")
        TodoWidget._instances.append(self)
        self.config = config

        self._show_alt_label = False
        self._tasks = []
        self._menu = None
        self._selected_category = "default"
        self._category_buttons = []
        self._expanded_task_id = None
        self._view_mode = "active"
        self._category_filter = None
        self._sort_mode = "due"
        self._time_signature = None

        self._init_container()
        self.build_widget_label(self.config.label, self.config.label_alt)

        self.register_callback("toggle_label", self._toggle_label)
        self.register_callback("toggle_menu", self._toggle_menu)
        self.callback_left = self.config.callbacks.on_left
        self.callback_right = self.config.callbacks.on_right
        self.callback_middle = self.config.callbacks.on_middle

        self._load_tasks()
        self._update_label()
        self._time_signature = self._current_signature()

        self.destroyed.connect(self._on_destroyed)
        # 跨零点、以及“今天已超时”状态变化时刷新标签和已打开的菜单。
        self._date_timer = QTimer(self)
        self._date_timer.timeout.connect(self._check_time_state)
        self._date_timer.start(60_000)

    def _on_destroyed(self, _obj=None):
        try:
            TodoWidget._instances.remove(self)
        except ValueError:
            pass

    @classmethod
    def update_all(cls):
        for instance in cls._instances:
            instance._load_tasks()
            instance._update_label()

    def _get_tasks_file_path(self) -> str:
        if self.config.data_path and self.config.data_path.strip():
            return os.path.expanduser(self.config.data_path)
        return os.path.join(HOME_CONFIGURATION_DIR, "todo.json")

    def _load_tasks(self):
        try:
            tasks_file = self._get_tasks_file_path()
            if not os.path.exists(tasks_file):
                self._tasks = []
                return
            with open(tasks_file, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, list):
                raise ValueError("todo.json 必须是数组")
            now = datetime.datetime.now()
            tasks = []
            for index, item in enumerate(raw):
                if not isinstance(item, dict):
                    continue
                task = dict(item)
                if not task.get("id"):
                    task["id"] = time.time_ns() + index
                task.setdefault("title", "")
                task.setdefault("description", "")
                task.setdefault("category", "default")
                task.setdefault("completed", False)
                task.setdefault("created_at", now.isoformat(timespec="seconds"))
                try:
                    task["order"] = int(task.get("order", 0))
                except TypeError, ValueError:
                    task["order"] = 0
                # 旧数据的已完成任务没有 completed_at，用创建时间回退，避免历史丢失。
                if task.get("completed") and not task.get("completed_at"):
                    task["completed_at"] = task.get("created_at") or now.isoformat(timespec="seconds")
                tasks.append(task)
            tasks.sort(key=lambda t: (t["order"], str(t["id"])), reverse=True)
            self._tasks = tasks
        except Exception as e:
            logging.error("Error loading tasks: %s", e)
            self._tasks = []

    def _save_tasks(self):
        tasks_file = self._get_tasks_file_path()
        tmp_file = f"{tasks_file}.tmp"
        try:
            directory = os.path.dirname(tasks_file)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self._tasks, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, tasks_file)
        except Exception as e:
            logging.error("Error saving tasks: %s", e)
            try:
                if os.path.exists(tmp_file):
                    os.remove(tmp_file)
            except OSError:
                pass

    def _add_new_task(self, dialog):
        title = self._title_input.text().strip()
        description = self._desc_input.toPlainText().strip() if self._desc_input else ""
        if not title:
            return
        task_data = {
            "id": time.time_ns(),
            "title": title,
            "description": description,
            "category": self._selected_category,
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "completed": False,
            "completed_at": None,
            "due_at": self._selected_due_at(),
            "order": len(self._tasks),
        }
        self._tasks.insert(0, task_data)
        self._save_tasks()
        TodoWidget.update_all()
        dialog.accept()
        self._view_mode = "active"
        self._show_menu()

    def _edit_task(self, dialog, task):
        title = self._title_input.text().strip()
        description = self._desc_input.toPlainText().strip() if self._desc_input else ""
        if not title:
            return
        for t in self._tasks:
            if t["id"] == task["id"]:
                t["title"] = title
                t["description"] = description
                t["category"] = self._selected_category
                t["due_at"] = self._selected_due_at()
                break
        self._save_tasks()
        TodoWidget.update_all()
        dialog.accept()
        self._view_mode = "active"
        self._expanded_task_id = task["id"]
        self._show_menu()

    def _selected_due_at(self) -> str | None:
        """返回对话框里选中的截止时间；未勾选表示无期限。"""
        if not self._due_checkbox.isChecked() or self._due_value is None:
            return None
        return self._due_value.strftime("%Y-%m-%dT%H:%M")

    def _on_due_toggled(self, checked: bool):
        self._due_button.setEnabled(checked)
        if checked:
            if self._due_value is None:
                self._due_value = datetime.datetime.combine(datetime.date.today(), datetime.time(23, 59))
        else:
            self._due_value = None
        self._update_due_button()

    def _update_due_button(self):
        if self._due_checkbox.isChecked() and self._due_value is not None:
            self._due_button.setText(self._due_value.strftime("%Y-%m-%d %H:%M"))
        else:
            self._due_button.setText("未设置 · 无期限")

    def _ensure_due_picker(self) -> DateTimePicker:
        if self._due_picker is None:
            self._due_picker = DateTimePicker(self._due_button.window(), self._apply_due_value, self._clear_due_value)
        return self._due_picker

    def _open_due_picker(self):
        if not self._due_checkbox.isChecked():
            self._due_checkbox.setChecked(True)
        if self._due_value is None:
            self._due_value = datetime.datetime.combine(datetime.date.today(), datetime.time(23, 59))
            self._update_due_button()
        picker = self._ensure_due_picker()
        picker.set_value(self._due_value)
        picker.show_at(self._due_button)

    def _apply_due_value(self, value: datetime.datetime):
        self._due_value = value
        if not self._due_checkbox.isChecked():
            self._due_checkbox.setChecked(True)
        self._update_due_button()

    def _clear_due_value(self):
        self._due_value = None
        self._due_checkbox.setChecked(False)
        self._due_button.setEnabled(False)
        self._update_due_button()

    def _show_task_dialog(self, dialog_title, save_button_text, on_save, task=None):
        self._menu.hide()
        self._selected_category = task.get("category", "default") if task else "default"
        dialog = QDialog(self._menu)
        dialog.setWindowTitle(dialog_title)
        dialog.setMinimumSize(500, 260)
        dialog.setProperty("class", "app-dialog")
        dialog.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.MSWindowsFixedSizeDialogHint
        )

        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setSpacing(0)
        dialog_layout.setContentsMargins(0, 0, 0, 0)

        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setSpacing(0)
        content_layout.setContentsMargins(20, 0, 20, 0)

        self._title_input = QLineEdit()
        self.widget_context_menu(self._title_input)
        self._title_input.setPlaceholderText("任务标题…（最多 100 个字符，必填）")
        self._title_input.setProperty("class", "title-field")
        if task:
            self._title_input.setText(task["title"])
        self._title_input.textChanged.connect(lambda: self._limit_text_length("title", 100))
        content_layout.addWidget(self._title_input)

        self._desc_input = QTextEdit()
        self._desc_input.insertFromMimeData = lambda source: self._desc_input.insertPlainText(source.text())
        self.widget_context_menu(self._desc_input)
        self._desc_input.setPlaceholderText("任务描述…（最多 500 个字符）")
        if task:
            self._desc_input.setText(task.get("description", ""))
        self._desc_input.textChanged.connect(lambda: self._limit_text_length("description", 500))
        self._desc_input.setProperty("class", "desc-field")
        content_layout.addWidget(self._desc_input)

        category_container = QFrame()
        category_layout = QHBoxLayout(category_container)
        category_layout.setContentsMargins(0, 0, 0, 0)
        category_container.setProperty("class", "category-container")
        self._category_buttons = []
        for category_name, category_config in self.config.categories.items():
            category_btn = QPushButton(category_config.label)
            category_btn.setProperty("class", f"category-button {category_name}")
            category_btn.setCheckable(True)
            category_btn.clicked.connect(partial(self._select_category, category_name))
            category_layout.addWidget(category_btn)
            self._category_buttons.append((category_name, category_btn))

        for cat_name, btn in self._category_buttons:
            btn.setChecked(cat_name == self._selected_category)

        content_layout.addWidget(category_container)

        due_container = QFrame()
        due_container.setProperty("class", "due-container")
        due_layout = QHBoxLayout(due_container)
        due_layout.setContentsMargins(0, 0, 0, 0)
        due_layout.setSpacing(8)

        self._due_checkbox = QCheckBox("设置截止日期")
        self._due_checkbox.setProperty("class", "due-checkbox")

        existing_due = _parse_due_at(task.get("due_at")) if task else None
        self._due_value = existing_due
        self._due_picker = None

        self._due_button = QPushButton()
        self._due_button.setProperty("class", "due-field")
        self._due_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._due_button.clicked.connect(self._open_due_picker)
        self._due_button.setEnabled(existing_due is not None)

        self._due_checkbox.setChecked(existing_due is not None)
        self._update_due_button()
        self._due_checkbox.toggled.connect(self._on_due_toggled)

        due_layout.addWidget(self._due_checkbox)
        due_layout.addWidget(self._due_button, 1)
        content_layout.addWidget(due_container)

        dialog_layout.addWidget(content_container)

        button_container = QFrame()
        button_container.setProperty("class", "buttons-container")
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)

        cancel_button = QPushButton("取消")
        cancel_button.setProperty("class", "button cancel")
        cancel_button.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_button)

        save_button = QPushButton(save_button_text)
        save_button.setProperty("class", "button add")
        save_button.clicked.connect(lambda: on_save(dialog, task) if task else on_save(dialog))
        button_layout.addWidget(save_button)

        dialog_layout.addWidget(button_container)

        self._title_input.setFocus()
        dialog.exec()

    def _toggle_label(self):

        self._show_alt_label = not self._show_alt_label

        for widget in self._widgets:
            widget.setVisible(not self._show_alt_label)

        for widget in self._widgets_alt:
            widget.setVisible(self._show_alt_label)

        self._update_label()

    def _now(self) -> datetime.datetime:
        return datetime.datetime.now()

    def _due_sort_key(self, now: datetime.datetime):
        def key(task: dict):
            due = _parse_due_at(task.get("due_at"))
            state = _due_state(due, now, self.config.due_soon_days)
            return (_STATE_ORDER[state], due or datetime.datetime.max, -task.get("order", 0))

        return key

    def _active_tasks(self) -> list[dict]:
        tasks = [t for t in self._tasks if not t.get("completed")]
        if self._category_filter:
            tasks = [t for t in tasks if t.get("category") == self._category_filter]
        if self._sort_mode == "custom":
            return sorted(tasks, key=lambda t: (t.get("order", 0), str(t.get("id"))), reverse=True)
        return sorted(tasks, key=self._due_sort_key(self._now()))

    def _completed_tasks(self) -> list[dict]:
        today = self._now().date()
        tasks = [t for t in self._tasks if t.get("completed") and _completed_until(t, today) >= today]
        return sorted(tasks, key=self._completed_sort_key(), reverse=True)

    def _history_tasks(self) -> list[dict]:
        today = self._now().date()
        tasks = [t for t in self._tasks if t.get("completed") and _completed_until(t, today) < today]
        return sorted(tasks, key=self._completed_sort_key(), reverse=True)

    def _completed_sort_key(self):
        return lambda t: _parse_due_at(t.get("completed_at")) or datetime.datetime.min

    def _current_signature(self):
        """签名为“日期 + 今天已超时的任务集合”，只有它变化才需要刷新 UI。"""
        now = self._now()
        today_overdue = tuple(
            sorted(
                str(t.get("id"))
                for t in self._tasks
                if not t.get("completed")
                and _due_state(_parse_due_at(t.get("due_at")), now, self.config.due_soon_days) == "today_overdue"
            )
        )
        return now.date(), today_overdue

    def _check_time_state(self):
        signature = self._current_signature()
        if signature == self._time_signature:
            return
        self._time_signature = signature
        self._update_label()
        try:
            if self._menu and self._menu.isVisible():
                self._refresh_menu_task_list()
        except RuntimeError:
            self._menu = None

    def _update_label(self):
        active_widgets = self._widgets_alt if self._show_alt_label else self._widgets
        active_label_content = self.config.label_alt if self._show_alt_label else self.config.label

        now = self._now()
        today = now.date()
        active_tasks = [t for t in self._tasks if not t.get("completed")]
        completed_today = sum(
            1
            for t in self._tasks
            if t.get("completed") and (_parse_due_at(t.get("completed_at")) or now).date() == today
        )

        state_counts = dict.fromkeys(_STATE_ORDER, 0)
        for task in active_tasks:
            state_counts[_due_state(_parse_due_at(task.get("due_at")), now, self.config.due_soon_days)] += 1

        deadline_count = state_counts["overdue"] + state_counts["today"] + state_counts["today_overdue"]
        soon_count = state_counts["tomorrow"] + state_counts["soon"]
        replacements = {
            "{deadline}": str(deadline_count),
            "{count}": str(len(active_tasks)),
            "{total}": str(len(self._tasks)),
            "{completed}": str(completed_today),
            "{overdue}": str(state_counts["overdue"]),
            "{today}": str(state_counts["today"] + state_counts["today_overdue"]),
            "{soon}": str(soon_count),
        }
        if deadline_count == 0:
            # 默认格式 {deadline}/{count}/{completed}，为 0 时整段隐藏，不留前导斜杠。
            active_label_content = re.sub(r"\{deadline\}\s*/\s*", "", active_label_content)

        label_parts = re.split("(<span.*?>.*?</span>)", active_label_content)
        label_parts = [part for part in label_parts if part]

        for widget_index, part in enumerate(label_parts):
            if widget_index >= len(active_widgets) or not isinstance(active_widgets[widget_index], QLabel):
                continue

            current_widget = active_widgets[widget_index]

            if "<span" in part and "</span>" in part:
                icon = re.sub(r"<span.*?>|</span>", "", part).strip()
                current_widget.setText(icon)
            else:
                formatted_text = part
                for placeholder, value in replacements.items():
                    formatted_text = formatted_text.replace(placeholder, value)
                current_widget.setText(formatted_text)

        tooltip_counts = {
            "逾期": state_counts["overdue"],
            "今天": state_counts["today"] + state_counts["today_overdue"],
            "即将到期": soon_count,
            "以后": state_counts["later"],
            "无期限": state_counts["none"],
        }
        tooltip_text = "\n".join(f"{label}: {count}" for label, count in tooltip_counts.items() if count > 0)
        set_tooltip(self._widget_container, tooltip_text or "没有任务。")

    def _toggle_menu(self):
        self._view_mode = "active"
        self._expanded_task_id = None
        self._show_menu()

    def _show_menu(self):
        self._menu = PopupWidget(
            self,
            self.config.menu.blur,
            self.config.menu.round_corners,
            self.config.menu.round_corners_type,
            self.config.menu.border_color,
        )
        self._menu.setProperty("class", "todo-menu")

        main_layout = QVBoxLayout(self._menu)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        header_container = QFrame()
        header_container.setProperty("class", "header")
        header_layout = QHBoxLayout(header_container)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)

        add_task_button = QPushButton(self.config.icons.add)
        add_task_button.setProperty("class", "add-task-button")
        add_task_button.clicked.connect(self._show_add_task_dialog)

        header_layout.addWidget(add_task_button, alignment=Qt.AlignmentFlag.AlignLeft)
        header_layout.addStretch()

        self._in_progress_btn = QPushButton("进行中")
        self._in_progress_btn.setCheckable(True)
        self._in_progress_btn.setChecked(self._view_mode == "active")
        self._in_progress_btn.setProperty("class", "tab-buttons in-progress")
        self._in_progress_btn.clicked.connect(lambda: self._set_view_mode("active"))

        self._completed_btn = QPushButton("已完成")
        self._completed_btn.setCheckable(True)
        self._completed_btn.setChecked(self._view_mode == "completed")
        self._completed_btn.setProperty("class", "tab-buttons completed")
        self._completed_btn.clicked.connect(lambda: self._set_view_mode("completed"))

        self._history_btn = QPushButton("历史")
        self._history_btn.setCheckable(True)
        self._history_btn.setChecked(self._view_mode == "history")
        self._history_btn.setProperty("class", "tab-buttons history")
        self._history_btn.clicked.connect(lambda: self._set_view_mode("history"))

        self._order_btn = QPushButton(self.config.icons.sort)
        self._order_btn.setProperty("class", "tab-buttons sort")
        self._order_btn.clicked.connect(self._show_sort_menu)

        header_layout.addWidget(self._in_progress_btn)
        header_layout.addWidget(self._completed_btn)
        header_layout.addWidget(self._history_btn)
        header_layout.addWidget(self._order_btn)

        main_layout.addWidget(header_container)

        scroll_area = QScrollArea()
        scroll_area.setViewportMargins(0, 0, -4, 0)
        scroll_area.setStyleSheet("""
            QScrollArea { background: transparent; border: none; border-radius:0; }
            QScrollBar:vertical { border: none; background:transparent; width: 4px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
            QScrollBar::handle:vertical { background: rgba(255, 255, 255, 0.2); min-height: 10px; border-radius: 2px; }
            QScrollBar::handle:vertical:hover { background: rgba(255, 255, 255, 0.35); }
            QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical { height: 0px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        """)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        scroll_widget = QWidget()
        scroll_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        scroll_widget.setProperty("class", "scroll-widget")
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(0)

        tasks = self._tasks_for_view()
        if self._view_mode == "active" and self._expanded_task_id is None and tasks:
            self._expanded_task_id = tasks[0]["id"]

        self._refresh_task_list(scroll_layout, tasks)

        scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(scroll_area)

        self._menu.adjustSize()
        self._menu.setPosition(
            alignment=self.config.menu.alignment,
            direction=self.config.menu.direction,
            offset_left=self.config.menu.offset_left,
            offset_top=self.config.menu.offset_top,
        )
        self._menu.show()

    def _show_sort_menu(self):
        menu = QMenu(self._order_btn.window())
        menu.setProperty("class", "context-menu")
        menu.setStyleSheet("""
            QMenu::indicator:checked { background: transparent;color:transparent }
        """)
        apply_qmenu_style(menu)

        sort_due = QAction("按截止时间", self)
        sort_due.setCheckable(True)
        sort_due.setChecked(self._sort_mode == "due")
        sort_due.triggered.connect(lambda: self._set_sort_mode("due"))

        sort_custom = QAction("自定义排序", self)
        sort_custom.setCheckable(True)
        sort_custom.setChecked(self._sort_mode == "custom")
        sort_custom.triggered.connect(lambda: self._set_sort_mode("custom"))

        menu.addAction(sort_due)
        menu.addAction(sort_custom)
        menu.addSeparator()

        show_all_action = QAction("显示所有分类", self)
        show_all_action.triggered.connect(self._clear_category_filter)
        show_all_action.setCheckable(True)
        show_all_action.setChecked(self._category_filter is None)
        menu.addAction(show_all_action)
        for cat_key, cat_config in self.config.categories.items():
            action = QAction(f"仅显示 {cat_config.label}", self)
            action.setCheckable(True)
            action.setChecked(self._category_filter == cat_key)
            action.triggered.connect(lambda checked, c=cat_key: self._set_category_filter(c))
            menu.addAction(action)

        button_pos = self._order_btn.mapToGlobal(self._order_btn.rect().bottomLeft())
        menu_width = menu.sizeHint().width()
        pos = button_pos - QPoint(menu_width - self._order_btn.sizeHint().width(), -6)
        menu.exec(pos)

    def _set_sort_mode(self, mode):
        self._sort_mode = mode
        self._expanded_task_id = None
        self._refresh_menu_task_list()

    def _set_category_filter(self, category_key):
        self._category_filter = category_key
        self._expanded_task_id = None
        self._refresh_menu_task_list()

    def _clear_category_filter(self):
        self._category_filter = None
        self._expanded_task_id = None
        self._refresh_menu_task_list()

    def _set_view_mode(self, mode):
        self._view_mode = mode
        self._in_progress_btn.setChecked(mode == "active")
        self._completed_btn.setChecked(mode == "completed")
        self._history_btn.setChecked(mode == "history")
        if mode != "active":
            self._expanded_task_id = None
        self._refresh_menu_task_list()

    def _tasks_for_view(self) -> list[dict]:
        if self._view_mode == "completed":
            return self._completed_tasks()
        if self._view_mode == "history":
            return self._history_tasks()
        return self._active_tasks()

    def _refresh_task_list(self, layout, tasks=None):
        """Refresh the task list for the current view."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        if tasks is None:
            tasks = self._tasks_for_view()

        if not tasks:
            self._add_empty_state(layout)
            return

        if self._view_mode == "active" and self._sort_mode == "due":
            grouped = {}
            now = self._now()
            for task in tasks:
                state = _due_state(_parse_due_at(task.get("due_at")), now, self.config.due_soon_days)
                grouped.setdefault(_state_group(state), []).append(task)
            for group_key, group_title in _STATE_GROUPS:
                group_tasks = grouped.get(group_key)
                if not group_tasks:
                    continue
                self._add_group_title(layout, group_title)
                for task in group_tasks:
                    self._add_task_to_menu(task, layout)
        elif self._view_mode == "history":
            current_date = None
            for task in tasks:
                completed = _parse_due_at(task.get("completed_at"))
                completed_date = completed.date() if completed else self._now().date()
                if completed_date != current_date:
                    current_date = completed_date
                    self._add_group_title(layout, self._format_history_date(completed_date))
                self._add_task_to_menu(task, layout)
        else:
            for task in tasks:
                self._add_task_to_menu(task, layout)

    def _add_group_title(self, layout, title: str):
        label = QLabel(title)
        label.setProperty("class", "task-group-title")
        layout.addWidget(label)

    @staticmethod
    def _format_history_date(value: datetime.date) -> str:
        return f"{value.month}月{value.day}日 {_WEEKDAYS[value.weekday()]}"

    def _add_empty_state(self, layout):
        category_label = ""
        if self._view_mode == "active" and self._category_filter:
            cat_key = self._category_filter
            cat_conf = self.config.categories.get(cat_key)
            category_label = f"（<b>{cat_conf.label if cat_conf else cat_key}</b>）"

        if self._view_mode == "active":
            if category_label:
                msg = f"没有任务{category_label}。<br>点击<b>新建任务</b>创建第一项任务！"
            else:
                msg = "暂无任务。<br>点击<b>新建任务</b>创建第一项任务！"
        elif self._view_mode == "completed":
            msg = "今日没有已完成任务。"
        else:
            msg = "暂无历史任务。"

        no_tasks_icon = QLabel(self.config.icons.no_tasks)
        no_tasks_icon.setProperty("class", "no-tasks-icon")
        no_tasks_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        no_tasks_label = QLabel(msg)
        no_tasks_label.setProperty("class", "no-tasks")
        no_tasks_label.setWordWrap(True)
        no_tasks_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        no_tasks_label.setTextFormat(Qt.TextFormat.RichText)
        no_tasks_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(no_tasks_icon)
        layout.addWidget(no_tasks_label)

    def _refresh_menu_task_list(self):
        """Refresh the task list in the menu if it exists."""
        if hasattr(self, "_menu") and self._menu:
            scroll_areas = self._menu.findChildren(QScrollArea)
            if scroll_areas:
                scroll_area = scroll_areas[0]
                scroll_widget = scroll_area.widget()
                if scroll_widget:
                    self._refresh_task_list(scroll_widget.layout(), self._tasks_for_view())

    def _expand_task(self, task_id):
        self._expanded_task_id = task_id
        self._refresh_menu_task_list()

    def _show_add_task_dialog(self):
        self._show_task_dialog(dialog_title="添加新任务", save_button_text="添加任务", on_save=self._add_new_task)

    def _show_edit_task_dialog(self, task):
        self._show_task_dialog(dialog_title="编辑任务", save_button_text="保存更改", on_save=self._edit_task, task=task)

    def widget_context_menu(self, widget):
        def show_custom_menu(point):
            standard_menu = widget.createStandardContextMenu()
            menu = QMenu(widget.window())
            menu.setProperty("class", "context-menu")
            menu.addActions(standard_menu.actions())
            standard_menu.deleteLater()
            apply_qmenu_style(menu)
            for action in menu.actions():
                action.setIconVisibleInMenu(False)
                action.setIcon(QIcon())
            menu.exec(widget.mapToGlobal(point))

        widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        widget.customContextMenuRequested.connect(show_custom_menu)

    def _limit_text_length(self, field, max_length):
        """Limit the text length for title or description fields."""
        if field == "title":
            text = self._title_input.text()
            if len(text) > max_length:
                self._title_input.blockSignals(True)
                self._title_input.setText(text[:max_length])
                self._title_input.blockSignals(False)
        elif field == "description":
            text = self._desc_input.toPlainText()
            if len(text) > max_length:
                self._desc_input.blockSignals(True)
                self._desc_input.setPlainText(text[:max_length])
                self._desc_input.blockSignals(False)

    def _select_category(self, category_name):
        self._selected_category = category_name
        for cat_name, btn in self._category_buttons:
            btn.setChecked(cat_name == category_name)

    def _due_badge(self, due: datetime.datetime | None, state: str) -> tuple[str, str]:
        if due is None:
            return "", ""
        today = self._now().date()
        if state == "overdue":
            return f"逾期 {(today - due.date()).days} 天 · {due.strftime('%m-%d %H:%M')}", "overdue"
        if state == "today_overdue":
            return f"今天 {due.strftime('%H:%M')} · 已超时", "overdue"
        if state == "today":
            return f"今天 {due.strftime('%H:%M')} 截止", "today"
        if state == "tomorrow":
            return f"明天 {due.strftime('%H:%M')}", "soon"
        if state == "soon":
            return f"{(due.date() - today).days} 天后 · {due.strftime('%m-%d %H:%M')}", "soon"
        return due.strftime("%m-%d %H:%M"), "later"

    def _friendly_date(self, value: datetime.datetime) -> str:
        delta = self._now() - value
        if delta.days == 0:
            if delta.seconds < 60:
                return "刚刚"
            if delta.seconds < 3600:
                return f"{delta.seconds // 60} 分钟前"
            return f"{delta.seconds // 3600} 小时前"
        if delta.days == 1:
            return "昨天"
        if delta.days < 30:
            return f"{delta.days} 天前"
        return value.strftime("%Y-%m-%d")

    def _add_task_to_menu(self, task, layout):
        completed = bool(task.get("completed"))
        due = _parse_due_at(task.get("due_at"))
        state = _due_state(due, self._now(), self.config.due_soon_days)
        category = task.get("category", "default")
        category_class = category if category in self.config.categories else "default"
        category_config = self.config.categories.get(category)
        category_text = category_config.label if category_config else category
        expanded = self._expanded_task_id == task["id"]

        container = TaskFrame(
            self,
            task,
            completed,
            self.config.icons,
            self.config.categories,
            expand_callback=self._expand_task,
            delete_callback=self._delete_task,
            reorder_callback=self._reorder_tasks,
            draggable=self._view_mode == "active" and self._sort_mode == "custom",
        )
        class_list = ["task-item"]
        if completed:
            class_list.append("completed")
        class_list.append(category_class)
        if expanded:
            class_list.append("expanded")
        if state == "overdue":
            class_list.append("overdue")
        elif state in ("today", "today_overdue"):
            class_list.append("due-today")
        elif state in ("tomorrow", "soon"):
            class_list.append("due-soon")
        container.setProperty("class", " ".join(class_list))
        container._base_class = " ".join(class_list)
        container.setContentsMargins(0, 0, 0, 0)
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        checkbox = QPushButton(self.config.icons.checked if completed else self.config.icons.unchecked)
        checkbox.setProperty("class", "task-checkbox")
        checkbox.setCheckable(True)
        checkbox.setChecked(completed)
        if completed:
            checkbox.clicked.connect(lambda: self._uncomplete_task(task))
        else:

            def delayed_archive(checked, t=task, cb=checkbox):
                cb.setChecked(True)
                cb.setEnabled(False)
                container.setProperty("class", f"task-item completed {category_class}")
                refresh_widget_style(container)
                cb.setText(self.config.icons.checked)

                def do_archive():
                    for existing_task in self._tasks:
                        if existing_task["id"] == t["id"]:
                            existing_task["completed"] = True
                            existing_task["completed_at"] = datetime.datetime.now().isoformat(timespec="seconds")
                            break
                    self._save_tasks()
                    TodoWidget.update_all()
                    try:
                        if self._menu and self._menu.isVisible():
                            self._refresh_menu_task_list()
                    except RuntimeError:
                        self._menu = None

                QTimer.singleShot(200, do_archive)

            checkbox.clicked.connect(delayed_archive)
        container_layout.addWidget(checkbox, alignment=Qt.AlignmentFlag.AlignTop)

        text_container = QWidget()
        text_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        text_layout = QVBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)

        title_label = QLabel(task["title"])
        title_label.setProperty("class", "title")
        title_label.setWordWrap(True)

        text_layout.addWidget(title_label)

        badge_text, badge_tone = self._due_badge(due, state)
        if completed:
            completed_at = _parse_due_at(task.get("completed_at"))
            badge_text = f"完成于 {completed_at.strftime('%m-%d %H:%M')}" if completed_at else "已完成"
            badge_tone = "done"
        if badge_text:
            badge = QLabel(badge_text)
            badge.setProperty("class", f"due-badge {badge_tone}")
            text_layout.addWidget(badge)

        if expanded:
            if task.get("description"):
                desc_label = QLabel()
                desc_label.setProperty("class", "description")
                desc_label.setWordWrap(True)
                desc_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
                desc_label.setOpenExternalLinks(True)
                desc = task["description"]

                if not bool(re.search(r"<a\s+href=", desc, re.IGNORECASE)):

                    def replacer(match):
                        url = match.group(1)
                        domain = urllib.parse.urlparse(url).netloc or "链接"
                        return f'<a style="text-decoration:none" href="{url}">{domain}</a>'

                    desc = re.sub(r"(https?://[^\s]+)", replacer, desc)
                desc_label.setText(desc)
                if completed:
                    desc_label.setProperty("class", "description completed")
                text_layout.addWidget(desc_label)

            time_text = ""
            if completed:
                completed_at = _parse_due_at(task.get("completed_at"))
                if completed_at:
                    time_text = f"完成于 {completed_at.strftime('%m-%d %H:%M')}"
            elif due:
                time_text = f"截止 {due.strftime('%m-%d %H:%M')}"
            else:
                created_at = _parse_due_at(task.get("created_at"))
                if created_at:
                    time_text = f"创建于 {self._friendly_date(created_at)}"

            info_row = QFrame()
            info_row.setProperty("class", "task-info-row")
            info_layout = QHBoxLayout(info_row)
            info_layout.setContentsMargins(0, 0, 0, 0)
            info_layout.setSpacing(0)
            if time_text:
                date_label_icon = QLabel(self.config.icons.date)
                date_label_icon.setProperty("class", "date-icon")
                date_label = QLabel(time_text)
                date_label.setProperty("class", "date-text")
                info_layout.addWidget(date_label_icon)
                info_layout.addWidget(date_label)

            cat_label_icon = QLabel(self.config.icons.category)
            cat_label_icon.setProperty("class", f"category-icon {category_class}")
            cat_label = QLabel(category_text)
            cat_label.setProperty("class", f"category-text {category_class}")
            info_layout.addWidget(cat_label_icon)
            info_layout.addWidget(cat_label)
            info_layout.addStretch()

            edit_btn = QPushButton(self.config.icons.edit)
            edit_btn.setProperty("class", "edit-task-button")
            edit_btn.clicked.connect(lambda _, t=task: self._show_edit_task_dialog(t))

            delete_btn = QPushButton(self.config.icons.delete)
            delete_btn.setProperty("class", "delete-task-button")
            delete_btn.clicked.connect(lambda _, t=task: self._delete_task(t))

            info_layout.addWidget(edit_btn)
            info_layout.addWidget(delete_btn)
            text_layout.addWidget(info_row)

        container_layout.addWidget(text_container)
        container.setAcceptDrops(True)
        container._drag_start_position = None
        container._task_id = task["id"]
        container._drop_highlight = False

        layout.addWidget(container)

    def _uncomplete_task(self, task):
        for existing_task in self._tasks:
            if existing_task["id"] == task["id"]:
                existing_task["completed"] = False
                existing_task["completed_at"] = None
                break
        self._save_tasks()
        TodoWidget.update_all()
        self._refresh_menu_task_list()

    def _delete_task(self, task):
        if self._view_mode == "history":
            reply = QMessageBox.question(
                self,
                "删除任务",
                f"确定删除“{task.get('title', '')}”？删除后无法恢复。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._tasks = [t for t in self._tasks if t["id"] != task["id"]]
        if self._expanded_task_id == task["id"]:
            self._expanded_task_id = None
        self._save_tasks()
        TodoWidget.update_all()
        self._refresh_menu_task_list()

    def _reorder_tasks(self, source_id, target_id):
        try:
            tasks_sorted = sorted(self._tasks, key=lambda t: (t["order"], str(t["id"])), reverse=True)
            source_index = next((i for i, t in enumerate(tasks_sorted) if str(t["id"]) == source_id), -1)
            target_index = next((i for i, t in enumerate(tasks_sorted) if str(t["id"]) == target_id), -1)
            if source_index != -1 and target_index != -1 and source_index != target_index:
                task = tasks_sorted.pop(source_index)
                tasks_sorted.insert(target_index, task)
                for idx, t in enumerate(tasks_sorted):
                    t["order"] = len(tasks_sorted) - idx - 1

                self._tasks = sorted(tasks_sorted, key=lambda t: (t["order"], str(t["id"])), reverse=True)
                self._sort_mode = "custom"
                self._save_tasks()
                self._refresh_menu_task_list()
        except Exception as e:
            logging.error("Failed to reorder tasks: %s", e)


class TaskFrame(QFrame):
    def __init__(
        self,
        main_widget,
        task,
        completed,
        icons,
        categories,
        expand_callback,
        delete_callback,
        reorder_callback,
        draggable=False,
    ):
        super().__init__(main_widget)
        self._main_widget = main_widget
        self._drag_start_position = None
        self._task_id = task["id"]
        self._drop_highlight = False
        self._task = task
        self._completed = completed
        self._icons = icons
        self._categories = categories
        self._expand_callback = expand_callback
        self._delete_callback = delete_callback
        self._reorder_callback = reorder_callback
        self._draggable = draggable
        self._base_class = "task-item"

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_position = event.pos()
            if self._main_widget._expanded_task_id != self._task_id:
                self._expand_callback(self._task_id)

    def mouseMoveEvent(self, event):
        if not self._draggable:
            return
        if event.buttons() & Qt.MouseButton.LeftButton and self._drag_start_position:
            if (event.pos() - self._drag_start_position).manhattanLength() >= 4:
                drag = QDrag(self)
                mime_data = QMimeData()
                mime_data.setText(str(self._task_id))
                drag.setMimeData(mime_data)
                drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):
        if not self._draggable:
            event.ignore()
            return
        if event.mimeData().hasText():
            self._drop_highlight = True
            self.setProperty("class", f"{self._base_class} drop-highlight")
            refresh_widget_style(self)
            self.update()
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._drop_highlight = False
        self.setProperty("class", self._base_class)
        refresh_widget_style(self)
        self.update()

    def dragMoveEvent(self, event):
        scroll_area = self
        while scroll_area and not isinstance(scroll_area, QScrollArea):
            scroll_area = scroll_area.parent()
        if scroll_area:
            global_pos = self.mapToGlobal(event.position().toPoint())
            viewport_pos = scroll_area.viewport().mapFromGlobal(global_pos)
            margin = 40
            if viewport_pos.y() < margin:
                scroll_area.verticalScrollBar().setValue(scroll_area.verticalScrollBar().value() - 20)
            elif viewport_pos.y() > scroll_area.viewport().height() - margin:
                scroll_area.verticalScrollBar().setValue(scroll_area.verticalScrollBar().value() + 20)
        event.acceptProposedAction()

    def dropEvent(self, event):
        self._drop_highlight = False
        self.setProperty("class", self._base_class)
        refresh_widget_style(self)
        self.update()
        source_id = event.mimeData().text()
        target_id = str(self._task_id)
        if source_id != target_id:
            self._reorder_callback(source_id, target_id)
        event.acceptProposedAction()


class TimeField(QLabel):
    """两位数字时间框：无光标，点击后逐位输入，支持滚轮。"""

    valueChanged = pyqtSignal(int)

    def __init__(self, maximum: int, parent=None):
        super().__init__(parent)
        self._maximum = maximum
        self._buffer = "00"
        self._editing = False
        self._entered = 0
        self.setProperty("class", "time-field")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedWidth(40)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setText(self._buffer)

    def value(self) -> int:
        return int(self._buffer)

    def set_value(self, value: int):
        # 时分是循环列表：23/59 继续增加回到 00，00 减小回到 23/59。
        value = int(value) % (self._maximum + 1)
        self._buffer = f"{value:02d}"
        self._editing = False
        self._entered = 0
        self.setText(self._buffer)
        self.valueChanged.emit(value)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self._editing = True
            self._entered = 0
            event.accept()
            return
        super().mousePressEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._editing = True
        self._entered = 0

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._editing = False

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta:
            # 向下滚动（delta < 0）增大，向上滚动减小；基于当前值切换。
            self.set_value(self.value() + (-1 if delta > 0 else 1))
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Backspace:
            self._backspace()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.set_value(self.value() + (1 if event.key() == Qt.Key.Key_Up else -1))
            event.accept()
            return
        text = event.text()
        if text.isdigit():
            self._type_digit(text)
            event.accept()
            return
        super().keyPressEvent(event)

    def _type_digit(self, digit: str):
        if self._entered >= 2:
            self._entered = 0
        if self._entered == 0:
            if digit == "0":
                # 0 不能作为第一位；保持当前值，等待下一个有效数字。
                return
            self._buffer = f"0{digit}"
            self._entered = 1
        else:
            # 第二位与前一位组成 xx；超出范围时保持 0x。
            value = int(self._buffer[1] + digit)
            if value > self._maximum:
                return
            self._buffer = f"{self._buffer[1]}{digit}"
            self._entered = 2
        self.setText(self._buffer)
        self.update()
        self.valueChanged.emit(self.value())

    def _backspace(self):
        if self._entered == 2:
            # xx -> 0x：保留十位作为新的个位，例如 53 -> 05。
            self._buffer = f"0{self._buffer[0]}"
            self._entered = 1
        elif self._entered == 1:
            self._buffer = "00"
            self._entered = 0
        else:
            # 首次退格把当前值退成 0x（保留个位），例如 23 -> 03。
            value = self.value()
            self._buffer = f"0{value % 10}" if value else "00"
            self._entered = 1 if value else 0
        self.setText(self._buffer)
        self.update()
        self.valueChanged.emit(self.value())


class TimeColumn(QWidget):
    """时间列：上/下为暗淡相邻值，中间可输入并支持滚轮。"""

    def __init__(self, maximum: int, parent=None):
        super().__init__(parent)
        self._maximum = maximum
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.upper = QLabel()
        self.upper.setProperty("class", "time-neighbor")
        self.upper.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.field = TimeField(maximum)
        self.field.valueChanged.connect(self._sync_neighbors)

        self.lower = QLabel()
        self.lower.setProperty("class", "time-neighbor")
        self.lower.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.unit = QLabel("时" if maximum == 23 else "分")
        self.unit.setProperty("class", "picker-unit")
        self.unit.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.upper)
        layout.addWidget(self.field)
        layout.addWidget(self.lower)
        layout.addWidget(self.unit)
        self._sync_neighbors()

    def _sync_neighbors(self, *_args):
        value = self.field.value()
        cycle = self._maximum + 1
        self.upper.setText(f"{(value - 1) % cycle:02d}")
        self.lower.setText(f"{(value + 1) % cycle:02d}")

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta:
            self.field.set_value(self.field.value() + (-1 if delta > 0 else 1))
            event.accept()
            return
        super().wheelEvent(event)


class ValueList(QFrame):
    """5 行滚轮列表：中间为当前值，首尾暗淡，可点击选择。"""

    valueChanged = pyqtSignal(int)

    def __init__(self, minimum, maximum, selected, parent=None, cyclic=False, formatter=None):
        super().__init__(parent)
        self.setProperty("class", "scroll-list")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._minimum = minimum
        self._maximum = maximum
        self._cyclic = cyclic
        self._formatter = formatter or str
        self._selected = selected
        self._rows = 5

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        self._labels = []
        for index in range(self._rows):
            label = QLabel()
            label.setProperty("class", "scroll-row")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setCursor(Qt.CursorShape.PointingHandCursor)
            label.mousePressEvent = lambda event, i=index: self._pick_row(i)
            layout.addWidget(label)
            self._labels.append(label)

        self._refresh()

    def set_selected(self, value: int):
        self._selected = self._normalize(value)
        self._refresh()

    def _normalize(self, value: int) -> int:
        if self._cyclic:
            span = self._maximum - self._minimum + 1
            return ((value - self._minimum) % span) + self._minimum
        return max(self._minimum, min(self._maximum, value))

    def _refresh(self):
        for index in range(self._rows):
            value = self._normalize(self._selected + index - 1)
            label = self._labels[index]
            label.setText(self._formatter(value))
            classes = ["scroll-row"]
            if index == 1:
                classes.append("selected")
            elif index in (0, self._rows - 1):
                classes.append("dim")
            label.setProperty("class", " ".join(classes))
            refresh_widget_style(label)

    def _step(self, delta: int):
        value = self._normalize(self._selected + delta)
        if value == self._selected:
            return
        self._selected = value
        self._refresh()
        self.valueChanged.emit(value)

    def _pick_row(self, index: int):
        if index == 1:
            return
        self._step(index - 1)
        self.hide()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta:
            self._step(-1 if delta > 0 else 1)
            event.accept()
            return
        super().wheelEvent(event)


class DateTimePicker(QFrame):
    """截止时间弹出面板：左侧日历，右侧 24 小时制时分。"""

    def __init__(self, parent, on_accept, on_clear):
        super().__init__(
            parent,
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._on_accept = on_accept
        self._on_clear = on_clear

        content = QFrame(self)
        content.setProperty("class", "datetime-picker")
        self._content = content
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(2)
        self._prev_btn = QPushButton("‹")
        self._prev_btn.setProperty("class", "picker-nav")
        self._year_btn = QPushButton()
        self._year_btn.setProperty("class", "picker-title")
        self._month_btn = QPushButton()
        self._month_btn.setProperty("class", "picker-title")
        self._next_btn = QPushButton("›")
        self._next_btn.setProperty("class", "picker-nav")
        header.addWidget(self._prev_btn)
        header.addWidget(self._year_btn)
        header.addWidget(self._month_btn)
        header.addWidget(self._next_btn)
        header.addStretch()
        layout.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(10)

        self._calendar = QCalendarWidget()
        self._calendar.setProperty("class", "picker-calendar")
        self._calendar.setFixedSize(290, 220)
        self._calendar.setNavigationBarVisible(False)
        self._calendar.setGridVisible(False)
        self._calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self._calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self._calendar.setLocale(QLocale(QLocale.Language.Chinese, QLocale.Country.China))
        table = self._calendar.findChild(QTableView)
        if table:
            table.setProperty("class", "calendar-table")
            palette = table.palette()
            palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 0, 0, 0))
            palette.setColor(QPalette.ColorRole.HighlightedText, palette.color(QPalette.ColorRole.Text))
            table.setPalette(palette)
        body.addWidget(self._calendar, 1)

        time_col = QVBoxLayout()
        time_col.setSpacing(6)
        time_col.addStretch()

        fields = QHBoxLayout()
        fields.setSpacing(18)
        self._hour_col = TimeColumn(23)
        self._minute_col = TimeColumn(59)
        self._hour = self._hour_col.field
        self._minute = self._minute_col.field
        fields.addWidget(self._hour_col)
        fields.addWidget(self._minute_col)
        time_col.addLayout(fields)

        time_hint = QLabel("点击输入 · 滚轮增减")
        time_hint.setProperty("class", "picker-caption")
        time_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        time_hint.setWordWrap(True)
        time_col.addWidget(time_hint)
        time_col.addStretch()
        body.addLayout(time_col)
        layout.addLayout(body)

        footer = QHBoxLayout()
        footer.setSpacing(4)
        for text, handler in (("23:59", self._set_2359), ("09:00", self._set_0900), ("清除", self._clear)):
            btn = QPushButton(text)
            btn.setProperty("class", "picker-quick")
            btn.clicked.connect(handler)
            footer.addWidget(btn)
        footer.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.setProperty("class", "picker-button")
        cancel_btn.clicked.connect(self.hide)
        ok_btn = QPushButton("确定")
        ok_btn.setProperty("class", "picker-button primary")
        ok_btn.clicked.connect(self._accept)
        footer.addWidget(cancel_btn)
        footer.addWidget(ok_btn)
        layout.addLayout(footer)

        self._year_list = ValueList(1970, 2100, self._calendar.yearShown(), content, cyclic=False, formatter=str)
        self._year_list.hide()
        self._year_list.valueChanged.connect(self._on_year_selected)

        self._month_list = ValueList(
            1, 12, self._calendar.monthShown(), content, cyclic=True, formatter=lambda m: f"{m} 月"
        )
        self._month_list.hide()
        self._month_list.valueChanged.connect(self._on_month_selected)

        self._prev_btn.clicked.connect(lambda: self._shift_month(-1))
        self._next_btn.clicked.connect(lambda: self._shift_month(1))
        self._year_btn.clicked.connect(self._show_year_list)
        self._month_btn.clicked.connect(self._show_month_list)
        self._calendar.currentPageChanged.connect(self._sync_header)
        self._sync_header()

    def _set_2359(self):
        self._hour.set_value(23)
        self._minute.set_value(59)

    def _set_0900(self):
        self._hour.set_value(9)
        self._minute.set_value(0)

    def _clear(self):
        self._on_clear()
        self.hide()

    def _accept(self):
        date = self._calendar.selectedDate()
        value = datetime.datetime(date.year(), date.month(), date.day(), self._hour.value(), self._minute.value())
        self._on_accept(value)
        self.hide()

    def _shift_month(self, delta: int):
        year = self._calendar.yearShown()
        month = self._calendar.monthShown() + delta
        if month < 1:
            month = 12
            year -= 1
        elif month > 12:
            month = 1
            year += 1
        self._calendar.setCurrentPage(year, month)

    def _sync_header(self, *_args):
        year = self._calendar.yearShown()
        month = self._calendar.monthShown()
        self._year_btn.setText(f"{year} 年")
        self._month_btn.setText(f"{month} 月")
        self._year_list.set_selected(year)
        self._month_list.set_selected(month)

    def _on_year_selected(self, year: int):
        self._calendar.setCurrentPage(year, self._calendar.monthShown())

    def _on_month_selected(self, month: int):
        self._calendar.setCurrentPage(self._calendar.yearShown(), month)

    def _show_year_list(self):
        self._toggle_list(self._year_list, self._year_btn)

    def _show_month_list(self):
        self._toggle_list(self._month_list, self._month_btn)

    def _toggle_list(self, widget: ValueList, button: QPushButton):
        if widget.isVisible():
            widget.hide()
            return
        self._year_list.hide()
        self._month_list.hide()
        widget.adjustSize()
        pos = button.mapTo(self._content, QPoint(0, button.height() + 4))
        pos.setX(max(0, min(pos.x(), self._content.width() - widget.width())))
        widget.move(pos)
        widget.show()
        widget.raise_()

    def set_value(self, value: datetime.datetime):
        self._calendar.setSelectedDate(QDate(value.year, value.month, value.day))
        self._calendar.setCurrentPage(value.year, value.month)
        self._hour.set_value(value.hour)
        self._minute.set_value(value.minute)
        self._sync_header()

    def show_at(self, anchor: QWidget):
        self.adjustSize()
        pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 6))
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            if pos.y() + self.height() > geo.bottom():
                pos.setY(anchor.mapToGlobal(QPoint(0, 0)).y() - self.height() - 6)
            if pos.x() + self.width() > geo.right() + 1:
                pos.setX(geo.right() - self.width() + 1)
            pos.setX(max(geo.left(), pos.x()))
            pos.setY(max(geo.top(), pos.y()))
        self.move(pos)
        self.show()
        self.raise_()
        self.activateWindow()
