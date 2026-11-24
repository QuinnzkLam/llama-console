"""SettingsDialog - 展开模式 ⚙ 弹出的二级设置窗口.

2026-11-24 Quinn 反饋: 原生淺色標題欄 + 硬編碼 #0d1117 背景完全唔貼主頁面
風格 → 重寫成同主窗口同一語言: frameless + translucent + 自繪圓角深色面板
(theme bg/border 色) + 自繪標題欄 (標題 + 紅燈關閉, 可拖動).
"""
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from llama_console_v2 import theme as t
from llama_console_v2.pages.settings import SettingsPage
from llama_console_v2.pages.player import _RedButton

_MARGIN = 10  # 圓角面板與透明窗口邊緣嘅留白 (畀圓角呼吸位)


class _TitleBar(QWidget):
    """自繪標題欄: 「設置」 + 紅燈關閉; 空白區可拖動窗口."""

    def __init__(self, dialog: "SettingsDialog", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dialog = dialog
        self._drag_from: QPoint | None = None
        t.fixed_h(self, t.scaled(44, floor=36))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(
            t.scaled(t.card_pad("inner_lr")), t.scaled(4),
            t.scaled(t.card_pad("inner_lr")), t.scaled(0),
        )
        title = QLabel("设置")
        title.setStyleSheet(
            f"color: {t.color('text_secondary')}; background: transparent; "
            f"border: none; font-weight: bold; font-size: {t.FONT_SIZE['md']}pt;"
        )
        lay.addWidget(title)
        lay.addStretch(1)
        close_btn = _RedButton()
        close_btn.clicked.connect(dialog.reject)
        lay.addWidget(close_btn)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.globalPosition().toPoint() - self._dialog.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._dialog.move(event.globalPosition().toPoint() - self._drag_from)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_from = None
        super().mouseReleaseEvent(event)


class SettingsDialog(QDialog):
    """深色播放器風格設置窗口 (frameless 圓角面板, 同主窗口一致)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # 2026-11-24: 640px 裝唔低內容最小高度 → layout 壓扁標題行 (字形豎向裁斷)
        # 700px + editor min_h 降低 + title_row fixed 後, 壓縮由 editor 吸收
        self.resize(900, 700)

        root = QVBoxLayout(self)
        root.setContentsMargins(_MARGIN, _MARGIN, _MARGIN, _MARGIN)
        # 圓角深色面板 — stylesheet 大容器 border-radius 渲染正常 (小 widget 先會變方)
        panel = QWidget()
        panel.setObjectName("SettingsPanel")
        panel.setStyleSheet(
            f"QWidget#SettingsPanel {{ background-color: {t.color('bg')}; "
            f"border: 1px solid {t.color('border')}; "
            f"border-radius: {t.radius('xl')}px; }}"
        )
        root.addWidget(panel)

        panel_lay = QVBoxLayout(panel)
        panel_lay.setContentsMargins(_MARGIN, 0, _MARGIN, _MARGIN)
        panel_lay.setSpacing(0)
        panel_lay.addWidget(_TitleBar(self))
        panel_lay.addWidget(SettingsPage(), 1)
