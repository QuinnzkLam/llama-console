"""PlayerPage - LlamaDeck v3 紧凑播放器主页 (单窗口双模式的内容体).

状态源与 sidebar 相同: backend_llama.snapshot().state (+ pid).
硬件环数据来自 backend_hardware.snapshot() 的 2s 缓存, 不另开采样线程.
播放键 / Space 与 sidebar 启动/停止共用同一组 MainWindow 回调.
"""
import re
import time
from pathlib import Path

import psutil
from PySide6.QtCore import Qt, QPoint, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QKeySequence, QLinearGradient, QMouseEvent,
    QPainter, QPainterPath, QPen, QRectF, QShortcut,
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
    "failed":   ("启动失败", "danger",  False),
}
_BORDER_COLOR = {
    "idle": "danger", "failed": "danger", "starting": "warning", "running": "success",
}


def _state_key(state: str) -> str:
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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._running = False
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        t.fixed_w(self, t.COMPACT["play_diameter"])
        t.fixed_h(self, t.COMPACT["play_diameter"])

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


class PlayerPage(QWidget):
    """紧凑播放器页: 顶栏 / 模型+播放+时长 / 6 个硬件环."""

    startRequested = Signal()
    stopRequested = Signal()
    compactRequested = Signal(bool)
    borderColorChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PlayerPage")
        self.setStyleSheet("background: transparent; border: none;")
        self._force_state: str | None = None
        self._last_key: str | None = None
        self._runningish = False
        self._start_ts: float | None = None
        self._compact = True

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(self._build_top_bar())
        root.addLayout(self._build_middle())
        root.addLayout(self._build_gauges())

        # Space: 聚焦 combobox 时放行给下拉框 (见 _toggle 的焦点检查)
        self._space = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self._space.activated.connect(self._toggle)

        self._poll = QTimer(self)
        self._poll.setInterval(1000)
        self._poll.timeout.connect(self._refresh)
        self._poll.start()
        self._refresh()

    # ---------------- 构建 ----------------
    def _build_top_bar(self) -> QHBoxLayout:
        self._top_bar = _DragBar()
        t.fixed_h(self._top_bar, t.COMPACT["topbar_height"])
        self._top_bar.setStyleSheet("background: transparent; border: none;")
        lay = QHBoxLayout(self._top_bar)
        lay.setContentsMargins(t.scaled(10), 0, t.scaled(10), 0)
        lay.setSpacing(t.scaled(4))

        title = QLabel("LlamaDeck")
        f = QFont()
        f.setPointSize(t.FONT_SIZE["md"])
        f.setBold(True)
        title.setFont(f)
        lay.addWidget(title)

        sub = QLabel("本地推理")
        sub.setStyleSheet(f"color: {t.color('text_muted')}; background: transparent;")
        sub_f = QFont()
        sub_f.setPointSize(t.FONT_SIZE["xs"])
        sub.setFont(sub_f)
        lay.addWidget(sub)
        lay.addStretch(1)

        self._gpu_badge = QLabel("")
        self._gpu_badge.setStyleSheet(
            f"color: {t.color('text_secondary')}; background-color: {t.color('card_hover')}; "
            f"border-radius: {t.radius('xl')}px; padding: {t.scaled(3)}px {t.scaled(8)}px;"
        )
        badge_f = QFont()
        badge_f.setPointSize(t.FONT_SIZE["xs"])
        self._gpu_badge.setFont(badge_f)
        self._gpu_badge.hide()
        lay.addWidget(self._gpu_badge)

        self._mode_btn = QPushButton("⤢")
        self._mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mode_btn.setToolTip("展开 / 收窄")
        self._mode_btn.setStyleSheet(
            f"QPushButton {{ color: {t.color('text_secondary')}; background: transparent; "
            f"border: none; font-size: {t.FONT_SIZE['lg']}pt; }} "
            f"QPushButton:hover {{ color: {t.color('text_primary')}; }}"
        )
        self._mode_btn.clicked.connect(self._on_mode_clicked)
        lay.addWidget(self._mode_btn)
        return lay

    def _build_middle(self) -> QHBoxLayout:
        lay = QHBoxLayout()
        lay.setContentsMargins(t.scaled(10), 0, t.scaled(10), 0)
        lay.setSpacing(t.scaled(10))

        # 左: 模型卡
        model_col = QVBoxLayout()
        cap = QLabel("模型")
        cap.setStyleSheet(f"color: {t.color('text_muted')}; background: transparent;")
        cap_f = QFont()
        cap_f.setPointSize(t.FONT_SIZE["xs"])
        cap.setFont(cap_f)
        model_col.addWidget(cap)

        model_row = QHBoxLayout()
        model_row.setSpacing(t.scaled(6))
        icon = QLabel()
        t.fixed_w(icon, t.COMPACT["icon_size"])
        t.fixed_h(icon, t.COMPACT["icon_size"])
        icon.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
            f"stop:0 {t.COMPACT['icon_start']}, stop:1 {t.COMPACT['icon_end']}); "
            f"border-radius: {t.scaled(10)}px;"
        )
        model_row.addWidget(icon)

        combo_col = QVBoxLayout()
        combo_col.setSpacing(0)
        self._combo = QComboBox()
        self._combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._combo.blockSignals(True)
        self._combo.addItems(backend_llama.list_models())
        active = backend_llama.get_active_model_filename()
        if active:
            idx = self._combo.findText(active)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
        self._combo.blockSignals(False)
        self._combo.currentIndexChanged.connect(self._on_model_changed)
        combo_f = QFont()
        combo_f.setPointSize(t.FONT_SIZE["sm"])
        combo_f.setBold(True)
        self._combo.setFont(combo_f)
        combo_col.addWidget(self._combo)

        self._subtitle = QLabel("")
        self._subtitle.setStyleSheet(f"color: {t.color('text_muted')}; background: transparent;")
        sub_f = QFont()
        sub_f.setPointSize(t.FONT_SIZE["xs"])
        self._subtitle.setFont(sub_f)
        combo_col.addWidget(self._subtitle)
        model_row.addLayout(combo_col, 1)
        model_col.addLayout(model_row)
        self._update_subtitle(self._combo.currentText())
        lay.addLayout(model_col, 3)

        # 中: 播放键 + 状态
        action = QHBoxLayout()
        action.setSpacing(t.scaled(8))
        self._play = _PlayButton()
        self._play.clicked.connect(self._toggle)
        action.addWidget(self._play)

        status_col = QVBoxLayout()
        status_row = QHBoxLayout()
        status_row.setSpacing(t.scaled(4))
        self._dot = QLabel("●")
        self._dot.setStyleSheet(f"color: {t.color('danger')}; background: transparent;")
        dot_f = QFont()
        dot_f.setPointSize(t.FONT_SIZE["sm"])
        self._dot.setFont(dot_f)
        status_row.addWidget(self._dot)
        self._status_text = QLabel("待启动")
        status_f = QFont()
        status_f.setPointSize(t.FONT_SIZE["sm"])
        self._status_text.setFont(status_f)
        status_row.addWidget(self._status_text)
        self._bars = _PulseBars()
        self._bars.hide()
        status_row.addWidget(self._bars)
        status_row.addStretch(1)
        status_col.addLayout(status_row)
        action.addLayout(status_col, 1)
        lay.addLayout(action, 2)

        # 右: 运行时长
        uptime_col = QVBoxLayout()
        uptime_col.setSpacing(0)
        up_label = QLabel("运行时长")
        up_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        up_label.setStyleSheet(f"color: {t.color('text_muted')}; background: transparent;")
        up_f = QFont()
        up_f.setPointSize(t.FONT_SIZE["xs"])
        up_label.setFont(up_f)
        uptime_col.addWidget(up_label)
        self._uptime = QLabel("00:00:00")
        self._uptime.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._uptime.setStyleSheet(f"color: {t.color('text_primary')}; background: transparent;")
        big_f = QFont()
        big_f.setPointSize(t.FONT_SIZE["2xl"])
        big_f.setBold(True)
        big_f.setFamily(t.FONT_FAMILY_MONO.split(",")[0].strip('" '))
        self._uptime.setFont(big_f)
        uptime_col.addWidget(self._uptime)
        lay.addLayout(uptime_col, 2)
        return lay

    def _build_gauges(self) -> QHBoxLayout:
        lay = QHBoxLayout()
        lay.setContentsMargins(t.scaled(10), t.scaled(4), t.scaled(10), t.scaled(6))
        lay.setSpacing(t.scaled(6))
        self._gauges: list[RingGauge] = []
        for label in ("CPU", "内存", "GPU0·核心", "GPU0·显存", "GPU1·核心", "GPU1·显存"):
            gauge = RingGauge(label)
            self._gauges.append(gauge)
            lay.addWidget(gauge)
        self._no_gpu = QLabel("未检测到 GPU")
        self._no_gpu.setStyleSheet(f"color: {t.color('text_muted')}; background: transparent;")
        self._no_gpu.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._no_gpu.hide()
        lay.addWidget(self._no_gpu)
        return lay

    # ---------------- 交互 ----------------
    def _on_mode_clicked(self) -> None:
        self.compactRequested.emit(not self._compact)

    def set_compact_mode(self, compact: bool) -> None:
        """由 MainWindow 在模式切换后同步展开/收窄按钮图标."""
        self._compact = compact
        self._mode_btn.setText("⤢" if compact else "⤡")

    def _toggle(self) -> None:
        """Space / 播放键: 与 sidebar 共用同一状态源, 不自己调 backend."""
        focus = QApplication.focusWidget()
        # combobox 要留给下拉框, 按钮要留给自身 Space 激活, 避免双触发
        if not self.isVisible() or isinstance(focus, (QComboBox, QPushButton)):
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
            self._subtitle.setText(f"{params.group(1)}B 参数 · {quant.group(1)} 量化")
        else:
            self._subtitle.setText(stem or model)

    def mark_failed(self) -> None:
        """MainWindow 在 health 不可达时同步标记失败 (与 sidebar pill 同源)."""
        self._force_state = "failed"
        self._last_key = None
        self._refresh()

    def border_color(self) -> str:
        return t.color(_BORDER_COLOR.get(self._last_key or "idle", "danger"))

    # ---------------- 刷新 ----------------
    def _refresh(self) -> None:
        try:
            snap = backend_llama.snapshot()
            state, pid = snap.state, snap.pid
        except Exception:  # noqa: BLE001
            state, pid = "stopped", None

        force = self._force_state
        if force == "failed" and state == "running":
            self._force_state = None
            force = None
        key = _state_key(force or state)
        text, color_key, self._runningish = _STATE_VIEW[key]
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

        try:
            hw = backend_hw.snapshot()
            cpu, ram, gpus = hw.cpu, hw.ram, hw.gpus
        except Exception:  # noqa: BLE001
            cpu, ram, gpus = None, None, []
        self._gpu_badge.setText(f"{len(gpus)} × GPU")
        self._gpu_badge.setVisible(bool(gpus))
        self._apply_gauges(cpu, ram, gpus)

    def _apply_gauges(self, cpu, ram, gpus) -> None:
        """6 gauge → snapshot 字段映射见交付报告; 不足 2 GPU 的对应隐藏."""
        cpu_pct = float(getattr(cpu, "util_percent", 0) or 0) if cpu else 0.0
        self._gauges[0].setValue(cpu_pct, f"{cpu_pct:.0f}%")

        used = float(getattr(ram, "used_gb", 0) or 0) if ram else 0.0
        cap = float(getattr(ram, "capacity_gb", 0) or 0) if ram else 0.0
        self._gauges[1].setValue(used / cap * 100 if cap else 0, f"{used:.1f}/{cap:.0f}")

        for i in range(2):
            gpu = gpus[i] if i < len(gpus) else None
            util = float(getattr(gpu, "util_percent", 0) or 0) if gpu else 0.0
            self._gauges[2 + i * 2].setValue(util, f"{util:.0f}%")
            v_used = getattr(gpu, "vram_used_mb", 0) or 0
            v_total = getattr(gpu, "vram_total_mb", 0) or 0
            vram_pct = v_used / v_total * 100 if v_total else 0
            self._gauges[3 + i * 2].setValue(
                vram_pct, f"{v_used / 1024:.1f}/{v_total / 1024:.0f}"
            )
        for i, gauge in enumerate(self._gauges[2:]):
            gauge.setVisible(i < len(gpus))
        self._no_gpu.setVisible(not gpus)

    def _uptime_text(self, state: str, pid) -> str:
        """优先 process create_time; 进程读不到时回退 GUI 内部计时."""
        if state == "running" and pid:
            try:
                sec = int(time.time() - psutil.Process(int(pid)).create_time())
                return self._fmt_uptime(max(0, sec))
            except (psutil.NoSuchProcess, psutil.AccessDenied,
                    psutil.ZombieProcess, ValueError, TypeError):
                pass
        if self._runningish and self._start_ts:
            return self._fmt_uptime(max(0, int(time.time() - self._start_ts)))
        return "00:00:00"

    @staticmethod
    def _fmt_uptime(sec: int) -> str:
        return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"
