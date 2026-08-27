"""
ProgressBar - 标题 + 横线进度条 + 占比数字(右上角)
设计图：CPU / RAM / GPU 核心 / VRAM 利用率

Quinn 16:35 反馈 (16:55 优化迭代):
- 进度条拉满卡片宽度 + 左对齐(去掉居中 wrapper 与 max_width)
- 占比数字移到进度条右上角(与 bar 顶端齐平, 紧贴 bar 右侧)
- 标题独占一行, 仅 label
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget
from PySide6.QtGui import QFont

from .. import theme as t


class ProgressBar(QWidget):
    """Title row (label only) + bar (left-aligned, full width) + percent label
    on top-right of the bar (vertical-align: top, sits to the right of bar).

    Quinn 09:00 三轮: set_value 缓存 color, 仅在变化时重写 stylesheet (减重绘)
    """

    def __init__(
        self,
        title: str,
        percent: int = 0,
        color: str = "success",
        sub_label: str = "",
        sub_label_2: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ProgressBar")
        self.setStyleSheet("background: transparent; border: none;")

        # 紧凑 spacing (Quinn 09:00 三轮: 1.5x 行距)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(t.scaled(4, floor=2))

        # ---------- Row 1: title (label only, 左对齐) ----------
        self._title_lbl = QLabel(title)
        font_t = QFont()
        font_t.setPointSize(t.FONT_SIZE["xs"])
        self._title_lbl.setFont(font_t)
        self._title_lbl.setStyleSheet(
            f"color: {t.color('text_secondary')}; background: transparent; border: none;"
        )
        layout.addWidget(self._title_lbl)

        # ---------- Row 2: bar (左对齐拉满) + percent (右上角) ----------
        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.setSpacing(t.scaled(8))

        self._bar = QProgressBar()
        self._bar.setTextVisible(False)
        t.fixed_h(self._bar, 6, floor=4)
        self._bar.setRange(0, 100)
        self._bar.setValue(percent)
        self._last_color_hex = None
        self._apply_bar_style(t.color(color))

        bar_row.addWidget(self._bar, 1)

        self._pct_lbl = QLabel(f"{percent}%")
        font_p = QFont()
        font_p.setPointSize(t.FONT_SIZE["sm"])
        font_p.setBold(True)
        self._pct_lbl.setFont(font_p)
        self._pct_lbl.setStyleSheet(
            f"color: {t.color('text_primary')}; background: transparent; border: none;"
        )
        bar_row.addWidget(self._pct_lbl, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(bar_row)

        # ---------- Row 3 (optional): sub labels ----------
        if sub_label or sub_label_2:
            sub_row = QHBoxLayout()
            sub_row.setContentsMargins(0, 0, 0, 0)
            sub_row.setSpacing(0)
            self._sub1 = QLabel(sub_label)
            font_s = QFont()
            font_s.setPointSize(t.FONT_SIZE["xs"])
            self._sub1.setFont(font_s)
            self._sub1.setStyleSheet(
                f"color: {t.color('text_secondary')}; background: transparent; border: none;"
            )
            sub_row.addWidget(self._sub1)
            sub_row.addStretch(1)
            self._sub2 = QLabel(sub_label_2)
            self._sub2.setFont(font_s)
            self._sub2.setStyleSheet(
                f"color: {t.color('text_secondary')}; background: transparent; border: none;"
            )
            sub_row.addWidget(self._sub2)
            layout.addLayout(sub_row)

    def _apply_bar_style(self, color_hex: str) -> None:
        self._bar.setStyleSheet(
            f"""
            QProgressBar {{
                background-color: {t.color('bg')};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: {color_hex};
                border-radius: 3px;
            }}
            """
        )
        self._last_color_hex = color_hex

    def set_value(self, percent: int, color: str | None = None) -> None:
        """Update bar value + percentage label.
        Quinn 09:00 三轮: color 仅在变化时重写 stylesheet
        """
        self._bar.setValue(max(0, min(100, percent)))
        self._pct_lbl.setText(f"{percent}%")
        if color is not None:
            color_hex = t.color(color)
            if color_hex != self._last_color_hex:
                self._apply_bar_style(color_hex)

    def set_sub_labels(self, left: str = "", right: str = "") -> None:
        if hasattr(self, "_sub1"):
            self._sub1.setText(left)
            self._sub2.setText(right)
