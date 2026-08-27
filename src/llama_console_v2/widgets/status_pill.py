"""
StatusPill - 圆角胶囊（带状态点 + 文字）
设计图：在线 / 运行中 / 已连接 等 pill

v2.1 (Quinn 16:55) 简化结构 - 去掉最外层 host 嵌套,
self 直接作为 pill 容器, 保证 sizeHint 正确传递给 Card title_row.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget
from PySide6.QtGui import QFont

from .. import theme as t


class StatusPill(QWidget):
    """Rounded status pill: dot + label. Color reflects state."""

    def __init__(
        self,
        text: str,
        state: str = "online",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("StatusPill")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(t.scaled(10), t.scaled(4), t.scaled(10), t.scaled(4))
        layout.setSpacing(t.scaled(6))

        # Status dot
        self._dot = QLabel("●")
        font_dot = QFont()
        font_dot.setPointSize(9)
        font_dot.setBold(True)
        self._dot.setFont(font_dot)
        self._dot.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self._dot)

        # Label
        self._label = QLabel(text)
        font_lbl = QFont()
        font_lbl.setPointSize(t.FONT_SIZE["xs"])
        font_lbl.setBold(True)
        self._label.setFont(font_lbl)
        self._label.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self._label)

        self.set_state(state)

    def set_state(self, state: str) -> None:
        """Update color based on state key (running/online/connected/...)."""
        color_token = t.status_color(state)
        color_hex = t.color(color_token)
        self.setStyleSheet(
            f"""
            QWidget#StatusPill {{
                background-color: {t.color('card_hover')};
                border-radius: {t.radius('md')}px;
            }}
            """
        )
        self._dot.setStyleSheet(
            f"color: {color_hex}; background: transparent; border: none;"
        )
        self._label.setStyleSheet(
            f"color: {color_hex}; background: transparent; border: none;"
        )

    def set_text(self, text: str) -> None:
        self._label.setText(text)