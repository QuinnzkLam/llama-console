"""PlayerPage - LlamaDeck v3 紧凑播放器主页 (单窗口双模式的内容体).

状态源与 sidebar 相同: backend_llama.snapshot().state (+ pid).
硬件环数据来自 backend_hardware.snapshot() 的 2s 缓存, 不另开采样线程.
播放键 / Space 与 sidebar 启动/停止共用同一组 MainWindow 回调.
"""
import re
import sys
import time
from pathlib import Path

import psutil
from PySide6.QtCore import Qt, QPoint, QRectF, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QIcon, QKeySequence, QLinearGradient, QMouseEvent,
    QPainter, QPainterPath, QPen, QShortcut,
)
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from llama_console_v2 import theme as t
from llama_console_v2.backend import hardware as backend_hw
from llama_console_v2.backend import llama_cpp as backend_llama
from llama_console_v2.widgets.ring_gauge import RingGauge

# 状态 → 文案 / 颜色 token / 是否视为运行中
_STATE_VIEW = {
    "idle":     ("待启动",   "danger",  False),
    "starting": ("启动中",   "warning", True),
    "running":  ("运行中",   "success", True),
    "stopping": ("关闭中",   "warning", False),
    "failed":   ("启动失败", "danger",  False),
}
_BORDER_COLOR = {
    "idle": "danger", "failed": "danger", "starting": "warning", "running": "success",
}


def _state_key(state: str) -> str:
    if state == "stopping":
        return "stopping"
    if state == "running":
        return "running"
    if state in ("loading", "starting"):
        return "starting"
    if state in ("error", "failed"):
        return "failed"
    return "idle"


class _DragBar(QWidget):
    """顶栏: frameless 下整条可作拖拽区移动窗口 (展开模式不拦截)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drag_pos: QPoint | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (event.button() == Qt.MouseButton.LeftButton and
                self.window().windowFlags() & Qt.WindowType.FramelessWindowHint):
            self._drag_pos = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None:
            self.window().move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)


class _PlayButton(QWidget):
    """自绘圆形播放/暂停键, hover 时轻微放大."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None, diameter: int | None = None) -> None:
        super().__init__(parent)
        self._running = False
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        d = diameter or t.COMPACT["play_diameter"]
        t.fixed_w(self, d)
        t.fixed_h(self, d)

    def setRunning(self, running: bool) -> None:
        if self._running != running:
            self._running = running
            self.update()

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        grow = t.scaled(3) if self._hover else 0
        circle = QRectF(grow, grow, self.width() - 2 * grow, self.height() - 2 * grow)

        grad = QLinearGradient(circle.topLeft(), circle.bottomRight())
        grad.setColorAt(0.0, QColor(t.color("card_hover")))
        grad.setColorAt(1.0, QColor(t.color("input")))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor(t.color("border")), t.scaled(2, floor=1)))
        p.drawEllipse(circle)

        p.setBrush(QColor(t.color("text_primary")))
        p.setPen(Qt.PenStyle.NoPen)
        cx, cy = circle.center().x(), circle.center().y()
        size = t.scaled(16)
        if self._running:
            bar_w, gap = max(3, t.scaled(5)), max(3, t.scaled(5))
            h = size + t.scaled(4)
            p.drawRect(QRectF(cx - gap / 2 - bar_w, cy - h / 2, bar_w, h))
            p.drawRect(QRectF(cx + gap / 2, cy - h / 2, bar_w, h))
        else:
            tri = QPainterPath()
            tri.moveTo(cx - size * 0.45, cy - size * 0.60)
            tri.lineTo(cx + size * 0.55, cy)
            tri.lineTo(cx - size * 0.45, cy + size * 0.60)
            tri.closeSubpath()
            p.drawPath(tri)
        p.end()


class _PulseBars(QWidget):
    """运行中状态点旁的三条跳动竖条."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._phase = 0
        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._tick)
        t.fixed_w(self, 26)
        t.fixed_h(self, 20)

    def showEvent(self, event) -> None:
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        self._phase = (self._phase + 1) % 24
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.color("success")))
        bar_w, gap = t.scaled(3, floor=2), t.scaled(4, floor=2)
        x0 = (self.width() - (3 * bar_w + 2 * gap)) / 2
        for i in range(3):
            h = 4 + (self.height() - 6) * abs(((self._phase + i * 5) % 12) - 6) / 6.0
            p.drawRoundedRect(QRectF(x0 + i * (bar_w + gap), (self.height() - h) / 2,
                                     bar_w, h), bar_w / 2, bar_w / 2)
        p.end()


class _SubtitleCombo(QComboBox):
    """两行下拉: 主名由 QComboBox 自绘在上半, 副标题自绘在下半."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sub_text = ""
        self._sub_px = 10

    def setSubText(self, text: str) -> None:
        self._sub_text = text
        self.update()

    def setSubPixel(self, px: int) -> None:
        self._sub_px = px
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._sub_text:
            return
        p = QPainter(self)
        f = QFont()
        f.setPixelSize(t.scaled(self._sub_px))
        p.setFont(f)
        p.setPen(QColor(t.color("text_muted")))
        # 下半行: 左侧留 padding, 右侧避开 drop-down 箭头
        rect = self.rect().adjusted(t.scaled(8), self.height() // 2, -t.scaled(24), 0)
        p.drawText(rect, Qt.AlignmentFlag.AlignVCenter, self._sub_text)
        p.end()


class _RedButton(QPushButton):
    """QPainter 自绘正圆关闭灯 (stylesheet border-radius 喺细 widget 上会渲染成方)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        t.fixed_w(self, 14)
        t.fixed_h(self, 14)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("关闭")
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.color("traffic_red")))
        p.drawEllipse(QRectF(0, 0, self.width(), self.height()))
        p.end()


class _ExpandButton(QPushButton):
    """右下角模式切换 (紧凑展开 / 展开收窄).

    2026-11-24 Quinn 反饋: 裸箭頭浮喺角落完全唔貼風格 → 改圓形 ghost
    按鈕 (card 底 + border 勾邊, hover 提亮), 同 ⚙ / 紅燈同一風格語言.
    小 widget stylesheet border-radius 會渲染成方 (見 _RedButton), 圓底自繪.
    """

    def __init__(self, parent: QWidget | None = None, direction: str = "expand") -> None:
        super().__init__(parent)
        self._collapse = direction == "collapse"
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("收窄" if self._collapse else "展开 / 收窄")
        t.fixed_w(self, 28)
        t.fixed_h(self, 28)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 圓形 ghost 底 (inset 1px 畀 1px 勾邊)
        p.setPen(QPen(QColor(t.color("border")), 1))
        p.setBrush(QColor(t.color("card_hover" if self._hover else "card")))
        p.drawEllipse(QRectF(1, 1, self.width() - 2, self.height() - 2))
        pen = QPen(
            QColor(t.color("text_primary" if self._hover else "text_secondary")),
            max(1, t.scaled(2, floor=1)),
        )
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        c = self.rect().center()
        r, head = t.scaled(6), t.scaled(3, floor=2)
        if self._collapse:
            # ↘↖ : 两段由两角指向中心, head 在内端, 中间留空
            gap = t.scaled(3)
            p.drawLine(c.x() - r, c.y() - r, c.x() - gap, c.y() - gap)
            p.drawLine(c.x() - gap, c.y() - gap, c.x() - gap - head, c.y() - gap)
            p.drawLine(c.x() - gap, c.y() - gap, c.x() - gap, c.y() - gap - head)
            p.drawLine(c.x() + r, c.y() + r, c.x() + gap, c.y() + gap)
            p.drawLine(c.x() + gap, c.y() + gap, c.x() + gap + head, c.y() + gap)
            p.drawLine(c.x() + gap, c.y() + gap, c.x() + gap, c.y() + gap + head)
        else:
            p.drawLine(c.x() - r, c.y() - r, c.x() + r, c.y() + r)
            # ↖↘ : 箭头指向两端 (展开语义)
            p.drawLine(c.x() + r, c.y() + r, c.x() + r - head, c.y() + r)
            p.drawLine(c.x() + r, c.y() + r, c.x() + r, c.y() + r - head)
            p.drawLine(c.x() - r, c.y() - r, c.x() - r + head, c.y() - r)
            p.drawLine(c.x() - r, c.y() - r, c.x() - r, c.y() - r + head)
        p.end()


class PlayerPage(QWidget):
    """紧凑播放器页: 顶栏 / 模型+播放+时长 / 6 个硬件环.

    embedded=True 时只保留中段, 供展开模式 DashboardPage 内嵌复用.
    """

    startRequested = Signal()
    stopRequested = Signal()
    compactRequested = Signal(bool)
    closeRequested = Signal()
    borderColorChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None, embedded: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("PlayerPage")
        self.setStyleSheet("background: transparent; border: none;")
        self._embedded = embedded
        self._force_state: str | None = None
        self._last_key: str | None = None
        self._runningish = False
        self._start_ts: float | None = None
        self._compact = True

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        if not embedded:
            self._build_top_bar()
            root.addWidget(self._top_bar)  # 必须收纳 _DragBar widget 本身, 唔系只收内部 layout
        root.addLayout(self._build_middle())
        if not embedded:
            root.addLayout(self._build_gauges())
            self._expand_btn = _ExpandButton(self)
            self._expand_btn.clicked.connect(self._on_mode_clicked)
            self._place_expand_button()
        self._apply_compact_font()
        self._reposition_cap()
        QTimer.singleShot(0, self._reposition_cap)  # layout 完成後重擺一次

        # Space: 聚焦 combobox 时放行给下拉框 (见 _toggle 的焦点检查)
        self._space = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self._space.activated.connect(self._toggle)

        # 2026-11-24: 輪詢上收 MainWindow 單一數據源 — 緊湊/展開/內嵌
        # 三個實例各自 poll 會令狀態、邊框燈、硬件環數據互相唔同步.
        # 初始由 MainWindow._poll_shared() singleShot 推送.

    # ---------------- 构建 ----------------
    def _build_top_bar(self) -> None:
        self._top_bar = _DragBar()
        t.fixed_h(self._top_bar, t.COMPACT["topbar_height"])
        self._top_bar.setStyleSheet("background: transparent; border: none;")
        lay = QHBoxLayout(self._top_bar)
        lay.setContentsMargins(t.scaled(10), 0, t.scaled(10), 0)
        lay.setSpacing(t.scaled(6))

        self._title = QLabel("LlamaDeck")
        self._title.setStyleSheet(f"color: {t.color('text_primary')}; background: transparent;")
        lay.addWidget(self._title)

        lay.addStretch(1)

        # 净剩红灯 (QPainter 正圆) — 顶栏最右; 展开入口改右下角 _ExpandButton
        self._red_btn = _RedButton()
        self._red_btn.clicked.connect(lambda: self.closeRequested.emit())
        lay.addWidget(self._red_btn)

    def _build_middle(self) -> QHBoxLayout:
        lay = QHBoxLayout()
        lay.setContentsMargins(t.scaled(10), 0, t.scaled(10), 0)
        lay.setSpacing(t.scaled(10))

        # 左: 模型卡 — cap 用绝对定位贴 icon 上方, model_row 独立垂直居中
        model_col = QVBoxLayout()
        model_col.setSpacing(t.scaled(4))
        self._cap = QLabel("模型", self)  # 唔入 layout: 避免 cap 高度推低 icon 中线
        self._cap.setStyleSheet(f"color: {t.color('text_muted')}; background: transparent;")
        self._cap.show()
        model_col.addStretch(1)

        model_row = QHBoxLayout()
        model_row.setSpacing(t.scaled(6))
        model_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        icon_px = t.COMPACT["icon_size"]
        icon = QLabel()
        self._icon = icon
        t.fixed_w(icon, icon_px)
        t.fixed_h(icon, icon_px)
        # 真 icon: 开发机用 repo assets, onefile 用 PyInstaller 解包目录 (spec datas 已加)
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
        icon.setScaledContents(True)  # 跟随 t.scaled 后的实际 widget 尺寸, 避免 44px 原图被裁
        icon.setPixmap(QIcon(str(base / "assets" / "LlamaDeck.ico")).pixmap(icon_px, icon_px))
        model_row.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)

        self._combo = _SubtitleCombo()
        self._combo.setCursor(Qt.CursorShape.PointingHandCursor)
        t.fixed_h(self._combo, 44)
        self._combo.setStyleSheet(
            f"QComboBox {{ background-color: {t.color('input')}; color: {t.color('text_primary')}; "
            f"border: 1px solid {t.color('border')}; border-radius: {t.radius('md')}px; "
            f"padding-left: {t.scaled(8)}px; padding-bottom: {t.scaled(22)}px; }} "
            f"QComboBox::drop-down {{ width: {t.scaled(24)}px; border: none; }} "
            f"QComboBox::down-arrow {{ image: none; width: 0px; height: 0px; "
            f"border-left: {t.scaled(5, floor=3)}px solid transparent; "
            f"border-right: {t.scaled(5, floor=3)}px solid transparent; "
            f"border-top: {t.scaled(6, floor=4)}px solid {t.color('text_secondary')}; }} "
            f"QComboBox QAbstractItemView {{ background-color: {t.color('input')}; "
            f"color: {t.color('text_primary')}; border: 1px solid {t.color('border')}; "
            f"selection-background-color: {t.color('card_hover')}; "
            f"selection-color: {t.color('text_primary')}; }}"
        )
        self._combo.blockSignals(True)
        self._combo.addItems(backend_llama.list_models())
        active = backend_llama.get_active_model_filename()
        if active:
            idx = self._combo.findText(active)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
        self._combo.blockSignals(False)
        self._combo.currentIndexChanged.connect(self._on_model_changed)
        model_row.addWidget(self._combo, 1, Qt.AlignmentFlag.AlignVCenter)

        model_col.addLayout(model_row)
        model_col.addStretch(1)
        self._update_subtitle(self._combo.currentText())
        lay.addLayout(model_col, 3)
        lay.setAlignment(model_col, Qt.AlignmentFlag.AlignVCenter)

        # 中: 播放键 + 状态
        action = QHBoxLayout()
        action.setSpacing(t.scaled(8))
        self._play = _PlayButton()
        self._play.clicked.connect(self._toggle)
        action.addWidget(self._play, 0, Qt.AlignmentFlag.AlignVCenter)

        status_col = QVBoxLayout()
        status_row = QHBoxLayout()
        status_row.setSpacing(t.scaled(4))
        self._dot = QLabel("●")
        self._dot.setStyleSheet(f"color: {t.color('danger')}; background: transparent;")
        status_row.addWidget(self._dot)
        self._status_text = QLabel("待启动")
        status_row.addWidget(self._status_text)
        self._bars = _PulseBars()
        self._bars.hide()
        status_row.addWidget(self._bars)
        status_row.addStretch(1)
        status_col.addLayout(status_row)
        action.addLayout(status_col, 1)
        action.setAlignment(status_col, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(action, 2)
        lay.setAlignment(action, Qt.AlignmentFlag.AlignVCenter)

        # 右: 运行时长 — 标签紧贴大字上方, 整组垂直居中于播放键中线
        uptime_col = QVBoxLayout()
        uptime_col.setSpacing(t.scaled(4))
        uptime_col.addStretch(1)
        self._up_label = QLabel("运行时长")
        self._up_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self._up_label.setStyleSheet(f"color: {t.color('text_muted')}; background: transparent;")
        uptime_col.addWidget(self._up_label)
        self._uptime = QLabel("00:00:00")
        self._uptime.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._uptime.setStyleSheet(f"color: {t.color('text_primary')}; background: transparent;")
        uptime_col.addWidget(self._uptime)
        uptime_col.addStretch(1)
        lay.addLayout(uptime_col, 2)
        lay.setAlignment(uptime_col, Qt.AlignmentFlag.AlignVCenter)
        return lay

    def _build_gauges(self) -> QHBoxLayout:
        lay = QHBoxLayout()
        lay.setContentsMargins(t.scaled(10), t.scaled(4), t.scaled(44), t.scaled(6))
        lay.setSpacing(t.scaled(6))
        self._gauges: list[RingGauge] = []
        for label in ("CPU", "内存", "GPU0·核心", "GPU0·显存", "GPU1·核心", "GPU1·显存"):
            gauge = RingGauge(label)
            self._gauges.append(gauge)
            lay.addWidget(gauge, 1)  # 等效 stretch 均分, 窗口变窄时无挤压
        self._no_gpu = QLabel("未检测到 GPU")
        self._no_gpu.setStyleSheet(f"color: {t.color('text_muted')}; background: transparent;")
        self._no_gpu.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._no_gpu.hide()
        lay.addWidget(self._no_gpu)
        return lay

    # ---------------- 交互 ----------------
    def _apply_compact_font(self) -> None:
        """按当前 font_scale 以像素字号重设全部文字, 避免展开 scale 固化到 QLabel."""
        specs = [
            (self._cap, 14, True),
            (self._combo, 13, True),
            (self._dot, 11, False),
            (self._status_text, 11, False),
            (self._up_label, 13, True),
            (self._uptime, 24, True),
        ]
        if not self._embedded:
            specs.insert(0, (self._title, 15, True))  # embedded 无顶栏
        for widget, px, bold in specs:
            font = QFont()
            font.setPixelSize(t.scaled(px))
            font.setBold(bold)
            widget.setFont(font)
        mono = self._uptime.font()
        mono.setFamily(t.FONT_FAMILY_MONO.split(",")[0].strip('" '))
        self._uptime.setFont(mono)

    def _on_mode_clicked(self) -> None:
        self.compactRequested.emit(not self._compact)

    def set_compact_mode(self, compact: bool) -> None:
        """由 MainWindow 在模式切换后重算字号 (t.scaled 跟随当前 font_scale)."""
        self._compact = compact
        self._apply_compact_font()

    def _place_expand_button(self) -> None:
        btn = getattr(self, "_expand_btn", None)
        if btn is not None:
            m = t.scaled(12)
            btn.move(self.width() - btn.width() - m, self.height() - btn.height() - m)
            btn.raise_()

    def _reposition_cap(self) -> None:
        """「模型」贴 icon 上方 4px; icon 中线因此与播放键中线一致."""
        cap = getattr(self, "_cap", None)
        icon = getattr(self, "_icon", None)
        if cap is None or icon is None:
            return
        pos = icon.mapTo(self, QPoint(0, 0))
        cap.adjustSize()
        cap.move(pos.x(), pos.y() - cap.height() - t.scaled(4))
        cap.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_expand_button()
        self._reposition_cap()

    def _toggle(self) -> None:
        """Space / 播放键: 与 sidebar 共用同一状态源, 不自己调 backend."""
        focus = QApplication.focusWidget()
        # combobox 要留给下拉框; 按钮 focus 时也允许触发 (optimistic flag 已防重)
        if not self.isVisible() or isinstance(focus, QComboBox):
            return
        if self._runningish:
            self._start_ts = None
            self._runningish = False
            self._play.setRunning(False)
            self.stopRequested.emit()
        else:
            self._start_ts = time.time()
            self._runningish = True
            self._play.setRunning(True)
            self.startRequested.emit()

    def _on_model_changed(self, index: int) -> None:
        model = self._combo.currentText()
        if not model:
            return
        try:
            backend_llama.select_model_profile(model)
        except Exception:  # noqa: BLE001 — profile 读写失败不影响播放器显示
            pass
        self._update_subtitle(model)

    def _update_subtitle(self, model: str) -> None:
        """优先给出 参数·量化 摘要; 读不到则显示模型文件名."""
        stem = Path(model).stem
        params = re.search(r"(\d+(?:\.\d+)?)\s*[Bb]", stem)
        quant = re.search(
            r"(?i)(?:^|[-.])(\d*bit|iq\d+_[a-z]+|q\d+_k_[a-z]+|q\d+_\d+|q\d+|f16|bf16|f8_e\d+m\d+)",
            stem,
        )
        if params and quant:
            self._combo.setSubText(f"{params.group(1)}B 参数 · {quant.group(1)} 量化")
        else:
            self._combo.setSubText(stem or model)

    def mark_failed(self) -> None:
        """MainWindow 在 health 不可达时同步标记失败 (与 sidebar pill 同源).

        2026-11-24: force 狀態上收 MainWindow, 呢度只清快取畀下一次
        apply_shared 正確重繪 (MainWindow 會即刻推 shared).
        """
        self._last_key = None

    def border_color(self) -> str:
        return t.color(_BORDER_COLOR.get(self._last_key or "idle", "danger"))

    # ---------------- 刷新 ----------------
    def apply_shared(self, state: str, pid, force: str | None, hw) -> None:
        """MainWindow 單一數據源推送 — llama 狀態 + 硬件快照 (2026-11-24).

        緊湊頁 / 內嵌播放器共用同一份快照: 狀態燈、邊框色、uptime、
        硬件環全部同步, 唔再各自採樣.
        """
        key = _state_key(force or state)
        text, color_key, self._runningish = _STATE_VIEW[key]
        self._combo.setEnabled(not self._runningish)  # 运行中锁定模型选择
        if key != self._last_key:
            self._last_key = key
            self._dot.setStyleSheet(
                f"color: {t.color(color_key)}; background: transparent; border: none;"
            )
            self._status_text.setText(text)
            self._play.setRunning(key in ("running", "starting"))
            self._bars.setVisible(key == "running")
            self.borderColorChanged.emit(t.color(color_key))
        self._uptime.setText(self._uptime_text(state, pid))

        if self._embedded:  # Dashboard 自带 6 环, 内嵌播放器唔重复采样
            return
        try:
            cpu, ram, gpus = hw.cpu, hw.ram, hw.gpus if hw else (None, None, [])
        except Exception:  # noqa: BLE001
            cpu, ram, gpus = None, None, []
        self._apply_gauges(cpu, ram, gpus)

    def _apply_gauges(self, cpu, ram, gpus) -> None:
        """6 gauge → snapshot 字段映射见交付报告; 不足 2 GPU 的对应隐藏."""
        cpu_pct = float(getattr(cpu, "util_percent", 0) or 0) if cpu else 0.0
        self._gauges[0].setValue(cpu_pct, f"{cpu_pct:.0f}%", "CPU")

        used = float(getattr(ram, "used_gb", 0) or 0) if ram else 0.0
        cap = float(getattr(ram, "capacity_gb", 0) or 0) if ram else 0.0
        self._gauges[1].setValue(
            used / cap * 100 if cap else 0, f"{round(used / cap * 100) if cap else 0}%",
            f"{used:.1f}/{cap:.0f} GB",
        )

        for i in range(2):
            gpu = gpus[i] if i < len(gpus) else None
            util = float(getattr(gpu, "util_percent", 0) or 0) if gpu else 0.0
            self._gauges[2 + i * 2].setValue(util, f"{util:.0f}%", f"GPU{i}·核心")
            v_used = getattr(gpu, "vram_used_mb", 0) or 0
            v_total = getattr(gpu, "vram_total_mb", 0) or 0
            vram_pct = v_used / v_total * 100 if v_total else 0
            self._gauges[3 + i * 2].setValue(
                vram_pct, f"{vram_pct:.0f}%",
                f"{v_used / 1024:.1f}/{v_total / 1024:.0f} GB",
            )
        for i, gauge in enumerate(self._gauges[2:]):
            gauge.setVisible(i // 2 < len(gpus))  # 每 GPU 两个环: 0,1→GPU0  2,3→GPU1
        self._no_gpu.setVisible(not gpus)

    def _uptime_text(self, state: str, pid) -> str:
        """llama-server 实际 create_time (最早进程) → GUI 内部计时兜底.

        進程存在就顯示真實時長 — 唔 gate 喺 state (health 探測會抖動,
        令 uptime 喺 llama 時間同 GUI 時間之間跳)."""
        if pid or state == "running":
            created: list[float] = []
            pids: list[int] = []
            if pid:
                pids.append(int(pid))
            try:
                proc = backend_llama._find_process()  # 真 server (避开 launcher stub)
                if proc is not None:
                    pids.append(proc.pid)
            except Exception:  # noqa: BLE001
                pass
            for candidate in pids:
                try:
                    created.append(psutil.Process(candidate).create_time())
                except (psutil.NoSuchProcess, psutil.AccessDenied,
                        psutil.ZombieProcess, ValueError, TypeError):
                    continue
            if not created:
                # 最后兜底: 扫全部 llama*.exe, 攞最早 create_time
                try:
                    for p in psutil.process_iter(["pid", "create_time", "name"]):
                        pname = (p.info.get("name") or "")
                        # 排除 GUI 本體 (LlamaDeck.exe) 同 launcher stub — 淨計真 server
                        if pname.lower() == "llamadeck.exe":
                            continue
                        if backend_llama._LLAMA_PROCESS_PATTERN.match(pname):
                            ctime = p.info.get("create_time")
                            if ctime:
                                created.append(float(ctime))
                except Exception:  # noqa: BLE001
                    pass
            if created:
                return self._fmt_uptime(max(0, int(time.time() - min(created))))
        if self._runningish and self._start_ts:
            return self._fmt_uptime(max(0, int(time.time() - self._start_ts)))
        return "00:00:00"

    @staticmethod
    def _fmt_uptime(sec: int) -> str:
        return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"
