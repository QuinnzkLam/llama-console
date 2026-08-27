"""
Card 容器 - 标题 + 可选 pill + body (普通 QVBoxLayout, 无滚动条)

v2 排版重设计 v2.1 (Quinn 14:15 反馈: 5 卡不应该有滚动条, 要完整显示)
- body 取消 QScrollArea, 改返普通 QVBoxLayout
- body 大小 = sizeHint (由 children 高度决定)
- 卡片 setSizePolicy Expanding/Expanding 撑满 column
- 窗口太细 → 父容器 (column) 滚动, 唔系 card body 滚动
- 防止 card 内部 squeezed → body.setMinimumHeight 由 children sizeHint 累计

v2.2 (Quinn 17:53): icon 支持 QWidget (例如 ChipSvgIcon 芯片 SVG) 或字符串
v2.3 (Quinn 16:11 R11): 标题改用 ElideLabel 单行省略, 避免窄卡片被 pill 挤压
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget, QSizePolicy,
)
from PySide6.QtGui import QFont

from .. import theme as t
from .elide_label import ElideLabel


class Card(QFrame):
    """Card with title row (icon + title + optional pill) + body container.

    v2.1 fix (Quinn 14:15): body 改返普通 QVBoxLayout, 取消 QScrollArea。
    卡片自动撑满 column 高度, 内容完整显示无滚动条。
    窗口太细时, 父容器滚动。

    v2.2 (Quinn 17:53): icon 支持 QWidget (例如 ChipSvgIcon 芯片 SVG) 或字符串
    """

    def __init__(
        self,
        title: str,
        icon: str | QWidget = "",
        body_height: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setStyleSheet(
            f"""
            QFrame#Card {{
                background-color: {t.color('card')};
                border: 1px solid {t.color('border')};
                border-radius: {t.radius('lg')}px;
            }}
            """
        )

        # Outer layout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.setSizeConstraint(QVBoxLayout.SizeConstraint.SetNoConstraint)

        # Title row (icon + title + pill)
        title_row = QWidget()
        title_row.setObjectName("CardTitle")
        title_row.setStyleSheet("background: transparent; border: none;")
        # Quinn 16:08: 标题与 body 间距加大 -> 上下用 space(4)，左右用 inner_lr
        title_layout = QHBoxLayout(title_row)
        title_layout.setContentsMargins(
            t.scaled(t.card_pad("inner_lr")), t.scaled(t.space("4")),
            t.scaled(t.card_pad("inner_lr")), t.scaled(t.space("5"))  # 底部留更多空白
        )
        title_layout.setSpacing(t.scaled(t.space("3")))
        title_layout.setSizeConstraint(QHBoxLayout.SizeConstraint.SetNoConstraint)

        # Quinn 17:53: icon 允许 QWidget (SVG 等矢量控件) 或字符串
        if isinstance(icon, QWidget):
            # 已是矢量控件, 直接 add; 用容器保证垂直对齐
            icon_w = icon
            icon_w.setParent(title_row)
            icon_holder = QWidget()
            icon_holder.setStyleSheet("background: transparent; border: none;")
            icon_holder_layout = QHBoxLayout(icon_holder)
            icon_holder_layout.setContentsMargins(0, t.scaled(2), 0, 0)
            icon_holder_layout.setSpacing(0)
            icon_holder_layout.addWidget(icon_w)
            title_layout.addWidget(icon_holder)
        elif icon:
            icon_lbl = QLabel(icon)
            # Quinn 16:08: icon 与 title 同号，太大抢戏 -> 改 base
            icon_font = QFont()
            icon_font.setPointSize(t.FONT_SIZE["base"])  # 14
            icon_lbl.setFont(icon_font)
            icon_lbl.setStyleSheet(
                f"color: {t.color('primary')}; background: transparent; border: none;"
            )
            title_layout.addWidget(icon_lbl)

        # Quinn 16:11 (R11): 标题改用 ElideLabel, 窄卡片中被 pill 挤压时省略号截断
        # (FRP 隧道 / Token 统计 在窗口模式下不再被 pill 挤压到换行/裁剪)
        title_lbl = ElideLabel(title, color=t.color("text_primary"))
        # Quinn 16:08: 2xl 太大 -> 改 xl (17pt)，用 bold 区隔正文
        title_font = QFont()
        title_font.setPointSize(t.FONT_SIZE["xl"])
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        title_lbl.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        title_layout.addWidget(title_lbl, 1)  # stretch=1, 抢占剩余空间给 pill 让位

        # Pill 容器 (延迟挂载 via set_pill)
        # Quinn 16:55: (Maximum, Preferred) 让 pill_host 保留自己的 sizeHint 宽度,
        # 避免在窄卡片中被 stretch 挤压到 0 导致 pill 文本裁剪
        self._pill_host = QWidget()
        self._pill_host.setStyleSheet("background: transparent; border: none;")
        self._pill_host.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self._pill_layout = QHBoxLayout(self._pill_host)
        self._pill_layout.setContentsMargins(0, 0, 0, 0)
        self._pill_layout.setSpacing(0)
        title_layout.addWidget(self._pill_host)

        # Quinn 16:08: title_row 高度 = xl header + 上下 padding (4+5)
        # R12 (17:38): 改一致缩放, 避免「基础值32 + 缩放值27」混搭导致 title_row 被压
        #   → 标题 (ElideLabel) 可见高度不足被竖向截断 (FRP/Token 标题只显一半/3/4)
        t.min_h(title_row, t.scaled(t.row_height("xl") + t.space("4") + t.space("5")))
        outer.addWidget(title_row)

        # Quinn 16:08: body 内部自动套 padding + spacing；调用方统一用 card.body_layout
        self._body = QWidget()
        self._body.setObjectName("CardBody")
        self._body.setStyleSheet("background: transparent; border: none;")
        self._body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(
            t.scaled(t.card_pad('inner_lr')), t.scaled(t.card_pad('inner')),
            t.scaled(t.card_pad('inner_lr')), t.scaled(t.card_pad('inner'))
        )
        self._body_layout.setSpacing(t.scaled(t.card_pad('row_gap')))
        self._body_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetNoConstraint)
        if body_height is not None:
            t.min_h(self._body, body_height)
        outer.addWidget(self._body, 1)

        # R12 (17:38): 给 Card 整体一个最低高度, 防止 engine_col 内 3 卡 stretch=1
        #   平分窗口高度时整体被压到标题/内容重叠. 矮窗下由外层 QScrollArea 兜底滚动.
        t.min_h(self, t.scaled(180))

    @property
    def body(self) -> QWidget:
        """Body widget (backward compat)."""
        return self._body

    @property
    def body_layout(self) -> QVBoxLayout:
        """Pre-installed body layout with card padding applied — 调用方统一用此接口."""
        return self._body_layout

    def set_pill(self, pill: QWidget) -> None:
        """Attach a pill widget to the title row."""
        # 移除旧
        while self._pill_layout.count():
            item = self._pill_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self._pill_layout.addWidget(pill)
