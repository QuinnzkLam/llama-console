"""
KeyValueRow - 设计图：监听地址 0.0.0.0:8080 / PID 18472 / 运行时间 3h 24m 18s
Label 上 / Value 下，2-column grid

v2.1 (Quinn 16:55) - 修复小窗口下 label/value 文字相互挤压/重叠问题
- label-value 内部 spacing 2→5
- 整体 min_h 38 防止 row 被压扁

v2.2 (Quinn 16:11) - 当 pairs 项数非 2 整数倍, 最后一项跨 2 列,
  避免 3 项单空一格的"假 2x2" 视觉效果挤压 (用户 R11 反馈).
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget
from PySide6.QtGui import QFont

from .. import theme as t


class KeyValueRow(QWidget):
    """Single label/value pair."""

    def __init__(
        self,
        label: str,
        value: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("KeyValueRow")
        self.setStyleSheet("background: transparent; border: none;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # Quinn 16:55: 2→5, 让 label 和 value 之间有呼吸空间, 不挤压
        layout.setSpacing(t.scaled(4, floor=2))

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
        self._value.setFont(font_v)
        # Quinn 17:30: value 默认 word_wrap, 长 URL/PID 等不被挤压重叠
        self._value.setWordWrap(True)
        self._value.setStyleSheet(
            f"color: {t.color('text_primary')}; background: transparent; border: none;"
        )
        layout.addWidget(self._value)

        # Quinn 16:55: 给 row 一个明确的 min_h, 防止父容器挤压时 label/value 重叠
        t.min_h(self, t.scaled(36, floor=28))

    def set_value(self, value: str) -> None:
        self._value.setText(value)


class KeyValueGrid(QWidget):
    """2-column grid of KeyValueRow.

    Quinn 16:11 (R11): 当 pairs 数 = 奇数 (如 3 项), 最后一项自动跨 2 列,
    避免出现「空 cell」导致下游 widget (如外网地址标题) 浮升假象.
    """

    def __init__(
        self, pairs: list[tuple[str, str]], n_cols: int = 2,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("KeyValueGrid")
        self.setStyleSheet("background: transparent; border: none;")
        self._rows: list[KeyValueRow] = []
        self._n_cols = max(1, n_cols)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(t.scaled(t.space("5")))
        # Quinn 16:55: 12→16, 让 row 之间有清晰分隔
        layout.setVerticalSpacing(t.scaled(t.space("3")))
        n = len(pairs)
        for i, (k, v) in enumerate(pairs):
            row_widget = KeyValueRow(k, v)
            self._rows.append(row_widget)
            row_idx = i // self._n_cols
            col_idx = i % self._n_cols
            # Quinn 16:11 (R11): 末项若所在行还有空 slot, 自动跨满剩余 cols
            # 例: 3 项×2 列: row=1 col=0, 剩 1 slot → colspan=2  (监听地址满宽)
            # 例: 4 项×2 列: row=1 col=1, 剩 0 slot → colspan=1  (公网地址正常)
            is_last = (i == n - 1)
            remaining = self._n_cols - col_idx
            if is_last and remaining > 1:
                col_span = remaining  # 填满本行剩余 cols
            else:
                col_span = 1
            layout.addWidget(row_widget, row_idx, col_idx, 1, col_span)

    def set_value(self, index: int, value: str) -> None:
        if 0 <= index < len(self._rows):
            self._rows[index].set_value(value)