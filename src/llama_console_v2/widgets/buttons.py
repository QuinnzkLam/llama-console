"""
PrimaryButton - 主按钮（启动 = 青色实心 / 暂停 = 描边 / 保存 = 青色实心 / 恢复默认 = 描边）
设计图：启动控制 / 设置页按钮
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton
from PySide6.QtGui import QFont, QIcon

from llama_console_v2 import theme as t


class PrimaryButton(QPushButton):
    """Filled primary button (e.g. 启动 / 保存)."""

    def __init__(self, text: str, icon_char: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName("PrimaryButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        t.fixed_h(self, 36)
        font = QFont()
        font.setPointSize(t.FONT_SIZE["sm"])
        font.setBold(True)
        self.setFont(font)
        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {t.color('primary')};
                color: {t.color('text_on_primary')};
                border: none;
                border-radius: {t.radius('md')}px;
                padding: 0 {t.scaled(16)}px;
            }}
            QPushButton:hover {{
                background-color: {t.color('primary_hover')};
            }}
            QPushButton:pressed {{
                background-color: {t.color('primary')};
            }}
            QPushButton:disabled {{
                background-color: {t.color('surface_3')};
                color: {t.color('text_muted')};
            }}
            """
        )
        if icon_char:
            # 简单 emoji 风格 icon（如 ▶ / ⏸）
            self.setText(f"{icon_char}  {text}")


class OutlineButton(QPushButton):
    """Outlined button (e.g. 暂停 / 恢复默认)."""

    def __init__(self, text: str, icon_char: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName("OutlineButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        t.fixed_h(self, 36)
        font = QFont()
        font.setPointSize(t.FONT_SIZE["sm"])
        font.setBold(True)
        self.setFont(font)
        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: transparent;
                color: {t.color('text_primary')};
                border: 1px solid {t.color('border')};
                border-radius: {t.radius('md')}px;
                padding: 0 {t.scaled(16)}px;
            }}
            QPushButton:hover {{
                background-color: {t.color('card_hover')};
                border-color: {t.color('border')};
            }}
            QPushButton:pressed {{
                background-color: {t.color('surface_3')};
            }}
            QPushButton:disabled {{
                color: {t.color('text_muted')};
                border-color: {t.color('border')};
            }}
            """
        )
        if icon_char:
            self.setText(f"{icon_char}  {text}")
