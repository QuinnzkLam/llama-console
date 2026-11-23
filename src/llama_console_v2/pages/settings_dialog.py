"""SettingsDialog - 展开模式 ⚙ 弹出的二级设置窗口 (原样装 SettingsPage)."""
from PySide6.QtWidgets import QDialog, QVBoxLayout

from llama_console_v2 import theme as t
from llama_console_v2.pages.settings import SettingsPage


class SettingsDialog(QDialog):
    """深色播放器风格设置窗口; 内容复用现有 SettingsPage."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(900, 640)
        self.setStyleSheet(
            f"QDialog {{ background-color: #0d1117; color: {t.color('text_primary')}; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(SettingsPage())
