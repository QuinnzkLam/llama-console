"""
StatBlock - 数值块（label 上 + value 下，可选右对齐 / 单位）
设计图：CPU 旁边的 温度 / 核心数；RAM 旁边的 可用 / 利用率
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from PySide6.QtGui import QFont

from .. import theme as t


class StatBlock(QWidget):
    """A label + value (small + large) block, side-by-side or stacked."""

    def __init__(
        self,
        label: str,
        value: str,
        sub_value: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("StatBlock")
        self.setStyleSheet("background: transparent; border: none;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._label = QLabel(label)
        font_l = QFont()
        font_l.setPointSize(t.FONT_SIZE["xs"])
        self._label.setFont(font_l)
        self._label.setStyleSheet(
            f"color: {t.color('text_secondary')}; background: transparent; border: none;"
        )
        layout.addWidget(self._label)

        self._value = QLabel(value)
        font_v = QFont()
        font_v.setPointSize(t.FONT_SIZE["base"])
        font_v.setBold(True)
        self._value.setFont(font_v)
        self._value.setStyleSheet(
            f"color: {t.color('text_primary')}; background: transparent; border: none;"
        )
        layout.addWidget(self._value)

    def set_value(self, value: str) -> None:
        self._value.setText(value)


class StatRow(QWidget):
    """Row of StatBlocks evenly distributed."""

    def __init__(self, blocks: list[StatBlock], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatRow")
        self.setStyleSheet("background: transparent; border: none;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(t.space("3"))
        for b in blocks:
            layout.addWidget(b, 1)
