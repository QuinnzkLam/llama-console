"""
ChipSvgIcon - 矢量芯片 icon (Quinn 17:53 反馈)
原始 GPU 卡 icon "◇" 字符改成芯片外观 SVG (深底矩形 + 青色描边 + 上下左右针脚 + 中央小圆)
使用 QSvgRenderer 加载内嵌 SVG, paintEvent 用当前主题色重绘.

v1.1 (Quinn 17:53): 提高 fill 透明度 (28→90), 增加 stroke 粗细 (1.6→2.2),
让小尺寸 (14px) 也能看清芯片形状而非糊成深色块.

优势:
- 矢量, 无字体依赖
- 跟随当前主题主色 (primary)
- 任意缩放无锯齿
"""
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget

from llama_console_v2 import theme as t


# ============================================================
# SVG 模板: %FILL% / %STROKE% / %DETAIL% 占位, paintEvent 用主题色渲染时替换
# v1.2 (Quinn 17:53): 加大芯片本体比例 (4-20 -> 3-21 in 24x24),
# 让小尺寸 20px 仍能看清轮廓针脚. stroke 2.2 + linecap round.
# ============================================================
_CHIP_SVG_TEMPLATE = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <rect x="3" y="3" width="18" height="18" rx="2.5"
        fill="%FILL%" stroke="%STROKE%" stroke-width="2.2"/>
  <rect x="9" y="9" width="6" height="6" rx="0.8"
        fill="%DETAIL%" stroke="%STROKE%" stroke-width="1.4"/>
  <line x1="6" y1="1" x2="6" y2="3" stroke="%STROKE%" stroke-width="2.2" stroke-linecap="round"/>
  <line x1="12" y1="1" x2="12" y2="3" stroke="%STROKE%" stroke-width="2.2" stroke-linecap="round"/>
  <line x1="18" y1="1" x2="18" y2="3" stroke="%STROKE%" stroke-width="2.2" stroke-linecap="round"/>
  <line x1="6" y1="21" x2="6" y2="23" stroke="%STROKE%" stroke-width="2.2" stroke-linecap="round"/>
  <line x1="12" y1="21" x2="12" y2="23" stroke="%STROKE%" stroke-width="2.2" stroke-linecap="round"/>
  <line x1="18" y1="21" x2="18" y2="23" stroke="%STROKE%" stroke-width="2.2" stroke-linecap="round"/>
  <line x1="1" y1="6" x2="3" y2="6" stroke="%STROKE%" stroke-width="2.2" stroke-linecap="round"/>
  <line x1="1" y1="12" x2="3" y2="12" stroke="%STROKE%" stroke-width="2.2" stroke-linecap="round"/>
  <line x1="1" y1="18" x2="3" y2="18" stroke="%STROKE%" stroke-width="2.2" stroke-linecap="round"/>
  <line x1="21" y1="6" x2="23" y2="6" stroke="%STROKE%" stroke-width="2.2" stroke-linecap="round"/>
  <line x1="21" y1="12" x2="23" y2="12" stroke="%STROKE%" stroke-width="2.2" stroke-linecap="round"/>
  <line x1="21" y1="18" x2="23" y2="18" stroke="%STROKE%" stroke-width="2.2" stroke-linecap="round"/>
</svg>
"""


def _render_svg(stroke: QColor, fill: QColor, detail: QColor) -> QSvgRenderer:
    """根据主题色生成 SVG renderer."""
    svg_str = (
        _CHIP_SVG_TEMPLATE
        .replace("%FILL%", fill.name(QColor.NameFormat.HexArgb))
        .replace("%STROKE%", stroke.name(QColor.NameFormat.HexArgb))
        .replace("%DETAIL%", detail.name(QColor.NameFormat.HexArgb))
    )
    renderer = QSvgRenderer(svg_str.encode("utf-8"))
    renderer.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
    return renderer


class ChipSvgIcon(QWidget):
    """GPU 卡片标题左侧用芯片图标, 与其他卡片 icon 同号 (.base size 14pt area)."""

    def __init__(
        self,
        size: int | None = None,
        color: str = "primary",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ChipSvgIcon")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        if size is None:
            # 与其他卡片 icon 同号 base 14pt, 但因为是 24x24 viewBox 含针脚,
            # 设 floor 20 保证 14pt 在小窗口下也能看清芯片轮廓与针脚
            size = max(20, t.FONT_SIZE["base"])
        t.fixed_w(self, size)
        t.fixed_h(self, size)
        self._color_key = color
        # v1.1: fill_alpha 让芯片体更明显 (深底). detail 是中央纹理, 留透明度对比.
        self._fill_alpha = 130    # 主体填充透明度 (0-255)
        self._detail_alpha = 70   # 中央 detail 透明度

    def sizeHint(self) -> QSize:  # noqa: N802
        s = max(20, t.scaled(t.FONT_SIZE["base"]))
        return QSize(s, s)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        stroke_color = QColor(t.color(self._color_key))
        fill_color = QColor(stroke_color)
        fill_color.setAlpha(self._fill_alpha)
        detail_color = QColor(stroke_color)
        detail_color.setAlpha(self._detail_alpha)

        renderer = _render_svg(stroke_color, fill_color, detail_color)
        # 在 widget rect 内保持 viewBox 比例 (KeepAspectRatio 已设)
        rect = self.rect()
        renderer.render(painter, rect)
        painter.end()
