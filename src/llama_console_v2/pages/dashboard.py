"""DashboardPage - 展开模式单页 Dashboard (Quinn 确认 Option A).

上至下: 播放器卡 (内嵌 PlayerPage) / 6 环行 / FRP+Token 双卡 / 硬件详情行.
所有数据直接来自 backend, 不经 ConsolePage widget.
"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from llama_console_v2 import theme as t
from llama_console_v2.backend import frp as backend_frp
from llama_console_v2.backend import hardware as backend_hw
from llama_console_v2.backend import llama_cpp as backend_llama
from llama_console_v2.pages.player import PlayerPage
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


def _card() -> QFrame:
    card = QFrame()
    card.setStyleSheet(
        f"QFrame {{ background-color: {t.color('card')}; "
        f"border: 1px solid {t.color('border')}; "
        f"border-radius: {t.scaled(t.DASH['radius'])}px; }}"
    )
    return card


class DashboardPage(QWidget):
    """展开模式主页; 经信号通知 MainWindow 收窄 / 关闭 / 开设置 / 启停."""

    compactRequested = Signal(bool)
    closeRequested = Signal()
    settingsRequested = Signal()
    startRequested = Signal()
    stopRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DashboardPage")
        self.setStyleSheet(f"background-color: {t.color('bg')};")

        root = QVBoxLayout(self)
        m = t.scaled(t.DASH["margin"])
        root.setContentsMargins(m, t.scaled(12), m, m)
        root.setSpacing(t.scaled(t.DASH["card_gap"]))
        root.addLayout(self._build_top_bar())
        root.addWidget(self._build_player_card(), 1)
        root.addWidget(self._build_gauge_card())
        root.addLayout(self._build_info_row())
        root.addWidget(self._build_hardware_card())
        root.addStretch(1)

        self._poll = QTimer(self)
        self._poll.setInterval(2000)
        self._poll.timeout.connect(self._refresh)
        self._poll.start()
        self._refresh()

    # ---------------- 构建 ----------------
    def _build_top_bar(self) -> QHBoxLayout:
        lay = QHBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(t.scaled(8))
        lay.addWidget(_lbl("LlamaDeck", t.DASH["title_px"], True))
        lay.addStretch(1)

        # 展开模式入口: 收窄 / 设置 / 关闭
        collapse = QPushButton("⤡")
        settings = QPushButton("⚙")
        close_btn = QPushButton()
        for btn, tip in ((collapse, "收窄"), (settings, "设置"), (close_btn, "关闭")):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tip)
        for btn in (collapse, settings):
            btn.setStyleSheet(
                f"QPushButton {{ color: {t.color('text_secondary')}; background: transparent; "
                f"border: none; font-size: {t.scaled(16)}px; }}"
            )
        t.fixed_w(close_btn, 12)
        t.fixed_h(close_btn, 12)
        close_btn.setStyleSheet(
            f"QPushButton {{ background-color: {t.color('traffic_red')}; border: none; "
            f"border-radius: {t.scaled(6)}px; }}"
        )
        collapse.clicked.connect(lambda: self.compactRequested.emit(True))
        settings.clicked.connect(lambda: self.settingsRequested.emit())
        close_btn.clicked.connect(lambda: self.closeRequested.emit())
        lay.addWidget(collapse)
        lay.addWidget(settings)
        lay.addWidget(close_btn)
        return lay

    def _build_player_card(self) -> QFrame:
        self._player_card = _card()
        lay = QVBoxLayout(self._player_card)
        m = t.scaled(t.DASH["margin"])
        lay.setContentsMargins(m, t.scaled(14), m, t.scaled(14))
        self._player = PlayerPage(embedded=True)
        self._player.startRequested.connect(self.startRequested)
        self._player.stopRequested.connect(self.stopRequested)
        self._player.borderColorChanged.connect(self._set_player_border)
        lay.addWidget(self._player, 1)
        self._set_player_border(self._player.border_color())
        return self._player_card

    def _set_player_border(self, color_hex: str) -> None:
        self._player_card.setStyleSheet(
            f"QFrame {{ background-color: {t.color('card')}; "
            f"border: {t.scaled(t.COMPACT['border_width'], floor=1)}px solid {color_hex}; "
            f"border-radius: {t.scaled(t.DASH['radius'])}px; }}"
        )

    def _build_gauge_card(self) -> QFrame:
        card = _card()
        lay = QHBoxLayout(card)
        m = t.scaled(t.DASH["margin"])
        lay.setContentsMargins(m, t.scaled(14), m, t.scaled(14))
        lay.setSpacing(t.scaled(8))
        self._gauges: list[RingGauge] = []
        for label in ("CPU", "内存", "GPU0·核心", "GPU0·显存", "GPU1·核心", "GPU1·显存"):
            gauge = RingGauge(label)
            self._gauges.append(gauge)
            lay.addWidget(gauge, 1)
        return card

    def _build_info_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(t.scaled(t.DASH["card_gap"]))

        frp_card = _card()
        fl = QVBoxLayout(frp_card)
        fl.setContentsMargins(t.scaled(16), t.scaled(12), t.scaled(16), t.scaled(12))
        fl.setSpacing(t.scaled(4))
        head = QHBoxLayout()
        head.addWidget(_lbl("FRP 隧道", t.DASH["title_px"], True))
        self._frp_dot = _lbl("●", t.DASH["body_px"], True, "text_muted")
        head.addWidget(self._frp_dot)
        head.addStretch(1)
        fl.addLayout(head)
        self._frp_lines = [_lbl("—", t.DASH["body_px"], color="text_secondary") for _ in range(4)]
        for line in self._frp_lines:
            fl.addWidget(line)
        row.addWidget(frp_card, 1)

        tok_card = _card()
        tl = QVBoxLayout(tok_card)
        tl.setContentsMargins(t.scaled(16), t.scaled(12), t.scaled(16), t.scaled(12))
        tl.setSpacing(t.scaled(4))
        tl.addWidget(_lbl("Token 統計", t.DASH["title_px"], True))
        self._tok_line = _lbl("— tokens", t.DASH["body_px"], color="text_secondary")
        self._tok_total = _lbl("0", 22, True)
        self._tok_rate = _lbl("—", t.DASH["muted_px"], color="text_muted")
        tl.addWidget(self._tok_line)
        tl.addWidget(self._tok_total)
        tl.addWidget(self._tok_rate)
        row.addWidget(tok_card, 1)
        return row

    def _build_hardware_card(self) -> QFrame:
        card = _card()
        lay = QHBoxLayout(card)
        m = t.scaled(t.DASH["margin"])
        lay.setContentsMargins(m, t.scaled(14), m, t.scaled(14))
        lay.setSpacing(t.scaled(8))
        self._hw_values: list[QLabel] = []
        for name in ("CPU 溫度", "CPU 頻率", "RAM", "GPU0 溫度", "GPU1 溫度", "風扇"):
            col = QVBoxLayout()
            col.setSpacing(t.scaled(4))
            col.addWidget(_lbl(name, t.DASH["muted_px"], color="text_muted"))
            val = _lbl("—", 16, True)
            col.addWidget(val)
            self._hw_values.append(val)
            lay.addLayout(col, 1)
        return card

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

        temps = [f"{int(getattr(g, 'temp_c', 0) or 0)}°C" if i < len(gpus) else "—"
                 for i, g in enumerate(gpus)]
        vals = [
            f"{int(getattr(cpu, 'temp_c', 0) or 0)}°C" if cpu and getattr(cpu, "temp_c", None) else "—",
            f"{getattr(cpu, 'freq_mhz', 0) or 0} MHz" if cpu and getattr(cpu, "freq_mhz", 0) else "—",
            f"{used:.1f} / {cap:.0f} GB",
            temps[0] if len(temps) > 0 else "—",
            temps[1] if len(temps) > 1 else "—",
            "—",
        ]
        for lab, val in zip(self._hw_values, vals):
            lab.setText(val)

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
