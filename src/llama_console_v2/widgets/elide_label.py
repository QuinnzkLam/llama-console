"""ElideLabel - 共享的「单行省略号」QLabel.

Quinn 12:00 创建 (R9 GPU 型号防 wrap 撑高).
Quinn 16:11 修复 (R9):
- 修 color 丢失 (styleSheet 颜色直接画)
- override sizeHint/minimumSizeHint 强制单行高度
Quinn 16:11 (R11): 提到 widgets 包, 供 Card 等其他 widget 复用 (修复 FRP/Token 标题挤压)
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QLabel, QSizePolicy


class ElideLabel(QLabel):
    """单行 QLabel, 超过宽度时尾部省略. 全文本放进 tooltip.

    关键约束:
    - sizeHint / minimumSizeHint 必须返回「单行」高度, 否则 QVBoxLayout 仍按
      多行算 min_h, 卡片照旧被撑高.
    - paintEvent 直接拿 self._color 而非 palette, 否则 styleSheet 设的颜色失效.
    - 默认 Expanding/Fixed 让 QHBoxLayout 留出足够宽度, 长度超限时尾部省略号.
    """

    def __init__(self, text: str = "", color: str = "#ffffff",
                 parent=None) -> None:
        super().__init__(text, parent)
        self._full_text = text
        self._color = color
        self.setStyleSheet(
            f"color: {color}; background: transparent; border: none;"
        )
        self.setToolTip(text)
        # 不开启 word_wrap, 不接受 tab 焦点
        self.setWordWrap(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # Quinn 16:11 (R11): 标题场景下 align 默认靠左; 调用方可 setAlignment 覆盖
        self.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt API)
        self._full_text = text
        self.setToolTip(text)
        # 不调用 super().setText, 改在我们自己的 paintEvent 中渲染 elided text
        self.update()

    def text(self) -> str:  # noqa: N802 (Qt API)
        return self._full_text

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        """强制单行高度, 防止布局给两行空间."""
        fm = QFontMetrics(self.font())
        # 宽按完整文本算 (扩展时优先), 高严格按单行 = font height
        return QSize(max(0, fm.horizontalAdvance(self._full_text)), fm.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        """最小尺寸也按单行; 1 个字符宽保证 label 不会被布局挤没."""
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance("…"), fm.height())

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        fm = QFontMetrics(self.font())
        # 计算可绘制宽度, 扣掉 1px 边距防截贴边
        w = max(0, self.width() - 1)
        elided = fm.elidedText(self._full_text, Qt.TextElideMode.ElideRight, w)
        # 用构造参数里的颜色 (styleSheet 被覆盖后无法从 palette 读到)
        painter.setPen(QColor(self._color))
        painter.drawText(self.rect(), int(self.alignment() | Qt.TextFlag.TextSingleLine),
                         elided)
        painter.end()
