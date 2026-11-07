"""Sign-in panel.

The app never asks for a password. Pressing the button opens the browser, where the user
signs in properly, and the app waits.
"""

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.cloud.constants import PRIVACY_URL, TERMS_URL
from core.ui.components.button import Button
from core.ui.components.content_dialog import ContentDialog
from core.ui.components.link import Link
from core.ui.components.loader import Spinner
from core.ui.components.text_block import TextBlock
from core.ui.theme import FONT_FAMILIES, get_tokens
from settings import SCRIPT_PATH


class ConnectView(QWidget):
    """Two states: idle, and waiting for browser approval."""

    connect_requested = pyqtSignal()
    cancel_requested = pyqtSignal()
    reopen_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        t = get_tokens()
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 20)
        root.setSpacing(0)
        root.addStretch(1)

        logo = QLabel()
        icon = os.path.join(SCRIPT_PATH, "assets", "images", "app_icon.png")
        if os.path.exists(icon):
            logo.setPixmap(
                QPixmap(icon).scaled(
                    72,
                    72,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(logo)
        root.addSpacing(18)

        title = TextBlock("YASB Cloud", variant="title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        self._subtitle = TextBlock("你的状态栏配置，随账号同步到每台电脑。", variant="body-secondary")
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle.setWordWrap(True)
        root.addWidget(self._subtitle)
        root.addSpacing(24)

        self._idle = QWidget(self)
        idle = QVBoxLayout(self._idle)
        idle.setContentsMargins(0, 0, 0, 0)
        idle.setSpacing(0)
        self._connect_btn = Button("登录", variant="accent")
        self._connect_btn.setFixedHeight(34)
        self._connect_btn.setMinimumWidth(200)
        self._connect_btn.clicked.connect(self.connect_requested.emit)
        idle.addWidget(self._connect_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._idle)

        self._waiting = QWidget(self)
        waiting = QVBoxLayout(self._waiting)
        waiting.setContentsMargins(0, 0, 0, 0)
        waiting.setSpacing(10)
        waiting.setAlignment(Qt.AlignmentFlag.AlignCenter)

        code_font = QFont()
        code_font.setFamilies(["Cascadia Mono", "Consolas", *FONT_FAMILIES])
        code_font.setPixelSize(24)
        code_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        self._code = QLabel("")
        self._code.setFont(code_font)
        self._code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._code.setStyleSheet(f"color: {t['text_primary']}; background: transparent;")
        waiting.addWidget(self._code)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_row.addWidget(Spinner(size=16, color=t["accent_fill_default"], parent=self._waiting))
        self._status = TextBlock("等待授权…", variant="body-secondary")
        status_row.addWidget(self._status)
        waiting.addLayout(status_row)
        waiting.addSpacing(6)

        reopen = Link("重新打开浏览器", parent=self._waiting)
        reopen.clicked.connect(self.reopen_requested.emit)
        waiting.addWidget(reopen, alignment=Qt.AlignmentFlag.AlignCenter)

        cancel = Button("取消", variant="default")
        cancel.setFixedHeight(30)
        cancel.clicked.connect(self.cancel_requested.emit)
        waiting.addWidget(cancel, alignment=Qt.AlignmentFlag.AlignCenter)

        root.addWidget(self._waiting)
        self._waiting.hide()

        root.addStretch(1)

        self._terms = QLabel(
            "登录即表示你同意我们的 "
            f'<a href="{TERMS_URL}" style="color: {t["accent_text_primary"]}; text-decoration: none;">'
            "服务条款</a>和 "
            f'<a href="{PRIVACY_URL}" style="color: {t["accent_text_primary"]}; text-decoration: none;">'
            "隐私政策</a>。"
        )
        self._terms.setOpenExternalLinks(True)
        self._terms.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._terms.setWordWrap(True)
        self._terms.setStyleSheet(f"color: {t['text_secondary']}; font-size: 12px; background: transparent;")
        root.addWidget(self._terms)

    def show_idle(self) -> None:
        self._waiting.hide()
        self._idle.show()
        self._terms.show()
        self._connect_btn.setEnabled(True)
        self._connect_btn.setText("登录")
        self._subtitle.setText("你的状态栏配置，随账号同步到每台电脑。")

    def show_connecting(self) -> None:
        self._connect_btn.setEnabled(False)
        self._connect_btn.setText("正在打开浏览器…")

    def show_waiting(self, user_code: str) -> None:
        self._idle.hide()
        self._terms.hide()
        self._code.setText(user_code)
        self._status.setText("等待授权…")
        self._subtitle.setText("请在刚刚打开的浏览器窗口中授权此设备。")
        self._waiting.show()

    def set_status(self, message: str) -> None:
        self._status.setText(message)

    def show_error(self, message: str, title: str = "无法登录") -> None:
        self.show_idle()
        ContentDialog(parent=self.window() or self, title=title, content=message, close_button_text="确定").show_dialog()
