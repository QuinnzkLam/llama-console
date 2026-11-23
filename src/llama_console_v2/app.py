"""
app.py - font init now applies to headless and real mode.
Uses Windows-native font chain: Microsoft YaHei (CJK) + Segoe UI (Latin) + fallback.

Quinn 10:15 (第五轮): 修启动崩溃
- 上一轮加的 AA_DisableWindowContextHelpButton 在 PySide6 6.11.2 的 ApplicationAttribute
  枚举里不存在 (该属性是较新 Qt 才加的), 直接访问会抛 AttributeError 导致启动时崩溃。
- 改为 _set_app_attr() 防御式: 只 set 已存在的属性, 版本差异永不崩溃。
"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QPalette, QColor
from PySide6.QtWidgets import QApplication

from llama_console_v2 import theme as t
from llama_console_v2.main_window import MainWindow


def _set_app_attr(app: QApplication, attr_name: str, value) -> None:
    """防御式设置 Qt.ApplicationAttribute。

    仅当该枚举成员在已安装的 PySide6 版本中存在时才设置, 避免版本差异导致启动崩溃。
    Quinn 10:15: 修复 AA_DisableWindowContextHelpButton 在 6.11.2 不存在的问题。
    """
    attr = getattr(Qt.ApplicationAttribute, attr_name, None)
    if attr is not None:
        app.setAttribute(attr, value)


def _pick_font_family() -> str:
    """Pick first available family from chain; never return empty (fallback to system default)."""
    chain = ["Inter", "Noto Sans CJK SC", "Microsoft YaHei UI", "Microsoft YaHei",
             "Segoe UI", "PingFang SC", "PingFang HK", "Arial Unicode MS", "Arial"]
    available = set(QFontDatabase.families())
    for f in chain:
        if f in available:
            return f
    # System default
    return QFont().defaultFamily() or "Arial"


def _apply_dark_palette(app: QApplication) -> None:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(t.color("bg")))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(t.color("text_primary")))
    palette.setColor(QPalette.ColorRole.Base, QColor(t.color("card")))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(t.color("card_hover")))
    palette.setColor(QPalette.ColorRole.Text, QColor(t.color("text_primary")))
    palette.setColor(QPalette.ColorRole.Button, QColor(t.color("card")))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(t.color("text_primary")))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(t.color("primary")))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(t.color("text_on_primary")))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(t.color("text_muted")))
    palette.setColor(QPalette.ColorRole.Link, QColor(t.color("primary")))
    app.setPalette(palette)


def _apply_font(app: QApplication) -> None:
    family = _pick_font_family()
    font = QFont(family)
    font.setPointSize(t.FONT_SIZE["base"])
    # Quinn 09:30: 关闭 kerning + style strategy → 缩放字符计算, 减少 setFont 后重排
    font.setStyleStrategy(QFont.StyleStrategy.PreferDefault)
    app.setFont(font)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("llamadeck")
    app.setApplicationDisplayName("LlamaDeck")
    app.setOrganizationName("Quinn")
    app.setStyle("Fusion")

    # Quinn 10:15: 启动期 Qt 性能属性 (防御式 — 只 set 已存在的枚举成员)
    _set_app_attr(app, "AA_DisableWindowContextHelpButton", True)  # 关闭窗口帮助按钮 (新版本才支持)
    _set_app_attr(app, "AA_DontUseNativeMenuBar", True)            # 用 Qt 自绘菜单 (Win 原生菜单栏重绘慢)
    _set_app_attr(app, "AA_UseHighDpiPixmaps", False)             # 关掉高 DPI 像素图 — 拖动/缩放期间图标重绘开销大

    # 先按 1/4 窗口尺寸设定字体缩放，再应用到 app 默认字体，保证与卡片字体一致
    tw, th = t.recommended_window_size()
    t.set_font_scale(t.compute_font_scale(tw, th))
    _apply_font(app)
    _apply_dark_palette(app)

    window = MainWindow()
    # Quinn 09:30: 给 Central 加 WA_OpaquePaintEvent 减少背景重绘
    if window.centralWidget() is not None:
        window.centralWidget().setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
