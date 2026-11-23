"""DashboardPage - 展开模式单页 Dashboard (Option A, FINAL-v4 seamless).

无大卡框: 各区块直接放 page 上, 区间用分隔线. 硬件矩阵用 stat chip (LHM 数据).
"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from llama_console_v2 import theme as t
from llama_console_v2.backend import frp as backend_frp
from llama_console_v2.backend import hardware as backend_hw
from llama_console_v2.backend import lhm as backend_lhm
from llama_console_v2.backend import llama_cpp as backend_llama
from llama_console_v2.pages.player import PlayerPage, _ExpandButton, _RedButton
from llama_console_v2.widgets.ring_gauge import RingGauge


def _lbl(text: str, px: int, bold: bool = False,
         color: str = "text_primary") -> QLabel:
    lab = QLabel(text)
    f = QFont()
    f.setPixelSize(t.scaled(px))
    f.setBold(bold)
    lab.setFont(f)
    lab.setStyleSheet(f"color: {t.color(color)}; background: transparent; border: none;")
    return lab


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"color: {t.DASH['divider']}; background-color: {t.DASH['divider']}; border: none;")
    line.setFixedHeight(max(1, t.scaled(2, floor=1)))
    return line


def _temp_color(value: float | None) -> str:
    if value is None:
        return "text_muted"
    if value < 60:
        return "success"
    if value <= 75:
        return "warning"
    return "danger"


class _StatChip(QFrame):
    """色点 + 名称 + 大值 + 单位; 温度按阈值着色, 功率用金色."""

    def __init__(self, name: str, unit: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatChip")
        self._dot = _lbl("●", 10, True, "text_muted")
        self._name = _lbl(name, t.DASH["muted_px"], color="text_muted")
        self._value = _lbl("—", 16, True)
        self._unit = _lbl(unit, t.DASH["muted_px"], color="text_muted")
        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(t.scaled(3))
        value_row.addWidget(self._value)
        value_row.addWidget(self._unit)
        value_row.addStretch(1)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self._name)
        col.addLayout(value_row)
        row = QHBoxLayout(self)
        row.setContentsMargins(t.scaled(10), t.scaled(6), t.scaled(10), t.scaled(6))
        row.setSpacing(t.scaled(6))
        row.addWidget(self._dot)
        row.addLayout(col, 1)
        self.setValue(None, "text_muted")

    def setValue(self, text: str | None, color_key: str) -> None:
        color_hex = t.DASH["gold"] if color_key == "gold" else t.color(color_key)
        self._value.setText(text or "—")
        self._value.setStyleSheet(f"color: {color_hex}; background: transparent; border: none;")
        self._dot.setStyleSheet(f"color: {color_hex}; background: transparent; border: none;")
        self.setStyleSheet(
            f"QFrame#StatChip {{ background-color: {t.DASH['card2']}; "
            f"border: 1px solid {color_hex}; "
            f"border-radius: {t.scaled(t.DASH['chip_radius'])}px; }}"
        )


class DashboardPage(QWidget):
    """展开模式主页; 经信号通知 MainWindow 收窄 / 关闭 / 开设置 / 启停."""

    compactRequested = Signal(bool)
    closeRequested = Signal()
    settingsRequested = Signal()
    borderColorChanged = Signal(str)
    startRequested = Signal()
    stopRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DashboardPage")
        self.setStyleSheet("background: transparent;")

        root = QVBoxLayout(self)
        m = t.scaled(t.DASH["margin"])
        root.setContentsMargins(m, t.scaled(10), m, m)
        root.setSpacing(t.scaled(t.DASH["card_gap"]))
        root.addLayout(self._build_top_bar())
        root.addWidget(_divider())

        # b. 播放器区 (无框)
        self._player = PlayerPage(embedded=True)
        self._player.startRequested.connect(self.startRequested)
        self._player.stopRequested.connect(self.stopRequested)
        root.addWidget(self._player, 1)
        root.addWidget(_divider())

        # c. 6 环行 (无框)
        root.addLayout(self._build_gauges())
        root.addWidget(_divider())

        # d. 硬件矩阵
        root.addLayout(self._build_hardware_matrix())
        root.addWidget(_divider())

        # e. FRP + Token 无框双栏
        root.addLayout(self._build_info_row())
        root.addStretch(1)

        # 展开模式收窄入口: 右下角同款双向箭头按钮
        self._expand_btn = _ExpandButton(self, direction="collapse")
        self._expand_btn.setToolTip("收窄")
        self._expand_btn.clicked.connect(lambda: self.compactRequested.emit(True))
        self._place_expand_button()

        self._poll = QTimer(self)
        self._poll.setInterval(2000)
        self._poll.timeout.connect(self._refresh)
        self._poll.start()
        self._refresh()

    # ---------------- 构建 ----------------
    def _place_expand_button(self) -> None:
        btn = self._expand_btn
        m = t.scaled(8)
        btn.move(self.width() - btn.width() - m, self.height() - btn.height() - m)
        btn.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_expand_button()

    def _build_top_bar(self) -> QHBoxLayout:
        lay = QHBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(t.scaled(12))
        title = _lbl("LlamaDeck", t.DASH["title_px"], True)
        lay.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addStretch(1)
        settings = QPushButton("⚙")
        settings.setCursor(Qt.CursorShape.PointingHandCursor)
        settings.setToolTip("设置")
        t.fixed_w(settings, 20)
        t.fixed_h(settings, 14)  # 同 _RedButton 14px 高, 中心线对齐
        settings.setStyleSheet(
            f"QPushButton {{ color: {t.color('text_secondary')}; background: transparent; "
            f"border: none; font-size: {t.scaled(11)}px; }}"
        )
        close_btn = _RedButton()
        settings.clicked.connect(lambda: self.settingsRequested.emit())
        close_btn.clicked.connect(lambda: self.closeRequested.emit())
        lay.addWidget(settings, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        return lay

    def _build_gauges(self) -> QHBoxLayout:
        lay = QHBoxLayout()
        lay.setContentsMargins(0, t.scaled(6), 0, t.scaled(6))
        lay.setSpacing(t.scaled(8))
        self._gauges: list[RingGauge] = []
        for label in ("CPU", "内存", "GPU0·核心", "GPU0·显存", "GPU1·核心", "GPU1·显存"):
            gauge = RingGauge(label)
            self._gauges.append(gauge)
            lay.addWidget(gauge, 1)
        return lay

    def _build_hardware_matrix(self) -> QVBoxLayout:
        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(t.scaled(6))
        root.addWidget(_lbl("硬件状态", t.DASH["title_px"], True))
        self._chips: dict[str, _StatChip] = {}
        rows = (
            (("cpu_temp", "CPU 温度", "°C", "temp"),
             ("cpu_freq", "CPU 频率", "GHz", "plain"),
             ("cpu_power", "CPU 功率", "W", "power")),
            (("gpu0_hotspot", "GPU0 核心温度", "°C", "temp"),
             ("gpu0_power", "GPU0 功率", "W", "power"),
             ("gpu0_vram_temp", "GPU0 显存温度", "°C", "temp")),
            (("gpu1_hotspot", "GPU1 核心温度", "°C", "temp"),
             ("gpu1_power", "GPU1 功率", "W", "power"),
             ("gpu1_vram_temp", "GPU1 显存温度", "°C", "temp")),
            (("total_power", "整机功耗", "W", "power"),),
        )
        for specs in rows:
            row = QHBoxLayout()
            row.setSpacing(t.scaled(6))
            for key, name, unit, _kind in specs:
                chip = _StatChip(name, unit)
                self._chips[key] = chip
                row.addWidget(chip, 1)
            root.addLayout(row)
        return root

    def _build_info_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(t.scaled(t.DASH["margin"]))
        # FRP
        frp_col = QVBoxLayout()
        frp_col.setSpacing(t.scaled(4))
        head = QHBoxLayout()
        head.addWidget(_lbl("FRP 隧道", t.DASH["title_px"], True))
        self._frp_dot = _lbl("●", t.DASH["body_px"], True, "text_muted")
        head.addWidget(self._frp_dot)
        head.addStretch(1)
        frp_col.addLayout(head)
        self._frp_lines = [_lbl("—", t.DASH["body_px"], color="text_secondary") for _ in range(4)]
        for line in self._frp_lines:
            frp_col.addWidget(line)
        row.addLayout(frp_col, 1)
        # Token
        tok_col = QVBoxLayout()
        tok_col.setSpacing(t.scaled(4))
        tok_col.addWidget(_lbl("Token 統計", t.DASH["title_px"], True))
        self._tok_line = _lbl("— tokens", t.DASH["body_px"], color="text_secondary")
        self._tok_total = _lbl("0", 22, True)
        self._tok_rate = _lbl("—", t.DASH["muted_px"], color="text_muted")
        for w in (self._tok_line, self._tok_total, self._tok_rate):
            tok_col.addWidget(w)
        row.addLayout(tok_col, 1)
        return row

    # ---------------- 刷新 ----------------
    def _refresh(self) -> None:
        try:
            hw = backend_hw.snapshot()
            cpu, ram, gpus = hw.cpu, hw.ram, hw.gpus
        except Exception:  # noqa: BLE001
            cpu, ram, gpus = None, None, []

        cpu_pct = float(getattr(cpu, "util_percent", 0) or 0) if cpu else 0.0
        self._gauges[0].setValue(cpu_pct, f"{cpu_pct:.0f}%", "CPU")
        used = float(getattr(ram, "used_gb", 0) or 0) if ram else 0.0
        cap = float(getattr(ram, "capacity_gb", 0) or 0) if ram else 0.0
        ram_pct = used / cap * 100 if cap else 0
        self._gauges[1].setValue(ram_pct, f"{ram_pct:.0f}%", f"{used:.1f}/{cap:.0f} GB")
        for i in range(2):
            gpu = gpus[i] if i < len(gpus) else None
            util = float(getattr(gpu, "util_percent", 0) or 0) if gpu else 0.0
            self._gauges[2 + i * 2].setValue(util, f"{util:.0f}%", f"GPU{i}·核心")
            v_used = getattr(gpu, "vram_used_mb", 0) or 0
            v_total = getattr(gpu, "vram_total_mb", 0) or 0
            vp = v_used / v_total * 100 if v_total else 0
            self._gauges[3 + i * 2].setValue(
                vp, f"{vp:.0f}%", f"{v_used / 1024:.1f}/{v_total / 1024:.0f} GB"
            )
        for i, gauge in enumerate(self._gauges[2:]):
            gauge.setVisible(i // 2 < len(gpus))

        # LHM 硬件矩阵 (NULL 显示 —); CPU 频率沿用 PDH freq_mhz
        lhm = backend_lhm.lhm_snapshot()  # 无 LHM 时全部字段 None, 不 throw
        freq = getattr(cpu, "freq_mhz", 0) if cpu else 0

        def temp(key: str, value) -> None:
            self._chips[key].setValue(
                f"{value:.0f}" if value is not None else None, _temp_color(value)
            )

        def power(key: str, value) -> None:
            self._chips[key].setValue(
                f"{value:.1f}" if value is not None else None, "gold"
            )

        # LHM 优先; 温度缺数时 fallback 现有 hardware.snapshot() (WMI / nvidia-smi)
        cpu_temp = getattr(lhm, "cpu_temp", None)
        if cpu_temp is None and cpu is not None:
            cpu_temp = getattr(cpu, "temp_c", None)
        temp("cpu_temp", cpu_temp)
        self._chips["cpu_freq"].setValue(
            f"{freq / 1000:.2f}" if freq else None, "text_primary"
        )
        power("cpu_power", getattr(lhm, "cpu_power", None))  # 无 fallback
        for i in range(2):
            gpu = gpus[i] if i < len(gpus) else None
            hotspot = getattr(lhm, f"gpu{i}_hotspot", None)
            if hotspot is None and gpu is not None:
                hotspot = getattr(gpu, "temp_c", None)
            vram_temp = getattr(lhm, f"gpu{i}_vram_temp", None)
            if vram_temp is None and gpu is not None:
                vram_temp = getattr(gpu, "vram_temp_c", None)
            temp(f"gpu{i}_hotspot", hotspot)
            power(f"gpu{i}_power", getattr(lhm, f"gpu{i}_power", None))
            temp(f"gpu{i}_vram_temp", vram_temp)
        power("total_power", getattr(lhm, "total_power", None))

        # LHM 诊断原因: 显示 — 的 chip hover 可见 (Franky 可 SSH 读)
        error = getattr(lhm, "error", None)
        for chip in self._chips.values():
            chip.setToolTip(f"LHM 未就绪: {error}" if error and chip._value.text() == "—" else "")

        try:
            frp = backend_frp.snapshot()
        except Exception:  # noqa: BLE001
            frp = None
        connected = bool(getattr(frp, "connected", False))
        self._frp_dot.setStyleSheet(
            f"color: {t.color('success' if connected else 'text_muted')}; "
            f"background: transparent; border: none;"
        )
        frp_texts = [
            f"隧道: {getattr(frp, 'tunnel_name', None) or '—'}",
            f"服务: {getattr(frp, 'server_addr', None) or '—'}",
            f"远程端口: {getattr(frp, 'remote_port', None) or '—'}",
            f"公网: {getattr(frp, 'public_url', None) or '—'}",
        ] if frp else ["—"] * 4
        for lab, text in zip(self._frp_lines, frp_texts):
            lab.setText(text)

        try:
            tok = backend_llama.get_token_stats()
        except Exception:  # noqa: BLE001
            tok = None
        if tok is not None and getattr(tok, "available", False):
            total = (getattr(tok, "prompt_tokens", 0) or 0) + (getattr(tok, "predicted_tokens", 0) or 0)
            self._tok_total.setText(f"{total:,}")
            self._tok_rate.setText(
                f"輸出 {getattr(tok, 'predicted_tps', 0) or 0:.1f} tok/s · "
                f"輸入 {getattr(tok, 'prompt_tps', 0) or 0:.1f} tok/s"
            )
        else:
            self._tok_total.setText("—")
            self._tok_rate.setText("metrics 未就緒")
