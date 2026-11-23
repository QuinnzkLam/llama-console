"""RingGauge - QPainter 环形仪表 (LlamaDeck v3 硬件环).

底环深灰 + 数值弧紫→青渐变 (270°) + 中央两行文字 (值 / 标签).
setValue() 只更新数值并触发重绘; 采样数据由调用方从 hardware.snapshot() 传入.
"""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from llama_console_v2 import theme as t


class RingGauge(QWidget):
    """单个硬件环; 值文字可为百分比或 used/total (如 "21.6/64")."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = label
        self._percent = 0.0
        self._value_text = "0"
        self.setObjectName("RingGauge")
        self.setStyleSheet("background: transparent; border: none;")
        t.fixed_w(self, t.COMPACT["gauge_diameter"])
        t.fixed_h(self, t.COMPACT["gauge_diameter"])

    def setValue(self, percent: float, text: str) -> None:
        """更新百分比 (0-100) 与中央值文字, 触发重绘."""
        self._percent = max(0.0, min(100.0, float(percent)))
        self._value_text = text
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = min(self.width(), self.height())
        margin = max(2, t.scaled(3))
        arc = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
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

        # 中央两行: 值 (大) + 标签 (小)
        value_font = QFont()
        value_font.setPointSize(t.FONT_SIZE["xs"])
        value_font.setBold(True)
        if len(self._value_text) > 4:
            value_font.setPointSize(max(7, t.FONT_SIZE["xs"] - 2))
        p.setFont(value_font)
        p.setPen(QColor(t.color("text_primary")))
        p.drawText(arc.adjusted(0, -arc.height() * 0.10, 0, -arc.height() * 0.10),
                   Qt.AlignmentFlag.AlignCenter, self._value_text)

        label_font = QFont()
        label_font.setPointSize(t.FONT_SIZE["xs"])
        p.setFont(label_font)
        p.setPen(QColor(t.color("text_muted")))
        p.drawText(arc.adjusted(0, arc.height() * 0.20, 0, arc.height() * 0.20),
                   Qt.AlignmentFlag.AlignCenter, self._label)
        p.end()
