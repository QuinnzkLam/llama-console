"""
PageHeader - 页面顶部 header（标题 + 右上"在线" pill）
设计图：llama-server 控制台 v4 / 设置
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget
from PySide6.QtGui import QFont

from .. import theme as t
from .status_pill import StatusPill


class PageHeader(QWidget):
    """Page header with title (and optional back link) + status pill."""

    def __init__(
        self,
        title: str,
        back_text: str = "",
        show_online: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PageHeader")
        self.setStyleSheet("background: transparent; border: none;")
        t.fixed_h(self, 48)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            t.scaled(t.space("6")), t.scaled(t.space("4")),
            t.scaled(t.space("6")), t.scaled(t.space("2"))
        )
        layout.setSpacing(t.scaled(t.space("3")))

        if back_text:
            back_lbl = QLabel(back_text)
            font_b = QFont()
            font_b.setPointSize(t.FONT_SIZE["sm"])
            back_lbl.setFont(font_b)
            back_lbl.setStyleSheet(
                f"color: {t.color('text_secondary')}; background: transparent; border: none;"
            )
            back_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            layout.addWidget(back_lbl)
            self._back_label = back_lbl

        title_lbl = QLabel(title)
        font_t = QFont()
        font_t.setPointSize(t.FONT_SIZE["lg"])
        font_t.setBold(True)
        title_lbl.setFont(font_t)
        title_lbl.setStyleSheet(
            f"color: {t.color('text_primary')}; background: transparent; border: none;"
        )
        layout.addWidget(title_lbl)

        layout.addStretch(1)

        if show_online:
            self._pill = StatusPill("在线", "online")
            layout.addWidget(self._pill)

    @property
    def back_label(self) -> QLabel | None:
        return getattr(self, "_back_label", None)


class PageFooter(QWidget):
    """Page footer: left link text, right app-shell text."""

    def __init__(self, left: str = "", right: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageFooter")
        self.setStyleSheet("background: transparent; border: none;")
        t.fixed_h(self, 28)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            t.scaled(t.space("6")), 0,
            t.scaled(t.space("6")), t.scaled(t.space("2"))
        )

        left_lbl = QLabel(left)
        font = QFont()
        font.setPointSize(t.FONT_SIZE["xs"])
        left_lbl.setFont(font)
        left_lbl.setStyleSheet(
            f"color: {t.color('text_secondary')}; background: transparent; border: none;"
        )
        layout.addWidget(left_lbl)

        layout.addStretch(1)

        right_lbl = QLabel(right)
        right_lbl.setFont(font)
        right_lbl.setStyleSheet(
            f"color: {t.color('text_muted')}; background: transparent; border: none;"
        )
        layout.addWidget(right_lbl)
