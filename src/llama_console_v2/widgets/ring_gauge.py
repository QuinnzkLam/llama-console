"""RingGauge - QPainter 环形仪表 (LlamaDeck v3 硬件环).

底环深灰 + 数值弧紫→青渐变 (270°); 环内只有百分比大字居中,
标签/单位在环下方外侧一行 (mockup 两段式).
setValue() 只更新数值并触发重绘; 采样数据由调用方从 hardware.snapshot() 传入.
"""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from llama_console_v2 import theme as t


class RingGauge(QWidget):
    """环内显示百分比大字, 环下显示 sub_text (默认 label)."""

    def __init__(self, label: str, sub_text: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = label
        self._sub_text = sub_text or label
        self._percent = 0.0
        self._value_text = "0"
        self.setObjectName("RingGauge")
        self.setStyleSheet("background: transparent; border: none;")
        # 水平可拉伸 (由 layout stretch 均分), 高度固定 = 直径 + 下方文字行
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(t.scaled(t.COMPACT["gauge_diameter"]))
        t.fixed_h(self, t.COMPACT["gauge_diameter"] + 24)

    def setValue(self, percent: float, text: str, sub_text: str | None = None) -> None:
        """更新百分比与中央值文字; sub_text 传入时覆盖环下标签."""
        self._percent = max(0.0, min(100.0, float(percent)))
        self._value_text = text
        if sub_text is not None:
            self._sub_text = sub_text
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        diameter = t.scaled(t.COMPACT["gauge_diameter"])
        x0 = (self.width() - diameter) / 2
        margin = max(2, t.scaled(3))
        arc = QRectF(x0 + margin, margin,
                     diameter - 2 * margin, diameter - 2 * margin)
        width = t.scaled(6, floor=4)
        start, span = 135 * 16, t.RING["span_deg"] * 16

        # 底环
        base = QPen(QColor(t.RING["base"]), width)
        base.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(base)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(arc, start, span)

        # 数值弧: 紫 → 青
        if self._percent > 0:
            grad = QLinearGradient(arc.topLeft(), arc.bottomRight())
            grad.setColorAt(0.0, QColor(t.RING["start"]))
            grad.setColorAt(1.0, QColor(t.RING["end"]))
            value_pen = QPen(QBrush(grad), width)
            value_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(value_pen)
            p.drawArc(arc, start, int(span * self._percent / 100.0))

        # 环内: 百分比大字居中
        value_font = QFont()
        value_font.setPointSize(t.FONT_SIZE["xs"])
        value_font.setBold(True)
        p.setFont(value_font)
        p.setPen(QColor(t.color("text_primary")))
        p.drawText(arc, Qt.AlignmentFlag.AlignCenter, self._value_text)

        # 环下: 标签 / 单位 (小字, 允许 "21.6/64 GB" 这类较长文本)
        sub_font = QFont()
        sub_font.setPointSize(t.FONT_SIZE["xs"])
        if len(self._sub_text) > 6:
            sub_font.setPointSize(max(7, t.FONT_SIZE["xs"] - 2))
        p.setFont(sub_font)
        p.setPen(QColor(t.color("text_muted")))
        sub_top = diameter + t.scaled(2, floor=1)
        p.drawText(QRectF(0, sub_top, self.width(), self.height() - sub_top),
                   Qt.AlignmentFlag.AlignCenter, self._sub_text)
        p.end()
