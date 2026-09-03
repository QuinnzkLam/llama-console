"""
Console 页 v2 - 3 列布局：侧栏 / 引擎信息 / 硬件信息
1) 引擎信息 (llama-server 状态 / FRP 隧道 / Token 统计)
2) 硬件信息 (CPU / RAM / GPU 父卡含 GPU0+GPU1)
- 3 列纵轴等高
- 温/占 3 档配色（低:green, 中:amber, 高:red）
- 卡片内行高 1.5 倍 + 收紧 padding (Quinn 09:00 反馈: 全屏无滚动条)

v3 (Quinn 09:00):
- 删除 token 卡底部的「停止」按钮 (已下沉到侧边栏, 与启动一起)
- 移除 body QScrollArea, 让卡片自适应撑满 (全屏不滚动)
- 收紧各卡片 spacing + min_h, 1.5x 行距
- performance: refresh 间隔 5s→10s; 仅在值变化时 setText/setStyleSheet

v4 (Quinn 12:00):
- GPU 子卡「型号」改 _ElideLabel 单行截断, 避免 wrap 撑高子卡

v5 (Quinn 16:11): 窗口模式响应式
- _ElideLabel 修复 color 丢失 (styleSheet 颜色直接画) + sizeHint 强制单行
- CPU 型号 / RAM 信息 / 状态卡模型名 改 _ElideLabel, 窄宽下省略号截断不换行
- theme.FONT_SCALE_MIN 0.65→0.55, 窄窗口下字号进一步缩小避免挤压
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from llama_console_v2 import theme as t
from llama_console_v2.widgets.card import Card
from llama_console_v2.widgets.chip_icon import ChipSvgIcon
from llama_console_v2.widgets.status_pill import StatusPill
from llama_console_v2.widgets.progress_bar import ProgressBar
from llama_console_v2.widgets.page_chrome import PageHeader, PageFooter
from llama_console_v2.backend import status as backend_status
from llama_console_v2.backend import hardware as backend_hardware
from llama_console_v2.backend import frp as backend_frp
from llama_console_v2.backend import llama_cpp as backend_llama


# ============================================================
# 3 档配色
# ============================================================
def _temp_color(temp_c: float | None) -> str:
    if temp_c is None:
        return "text_secondary"
    if temp_c < 60:
        return "success"
    if temp_c < 80:
        return "warning"
    return "danger"


def _util_color(percent: int) -> str:
    if percent < 60:
        return "success"
    if percent < 85:
        return "warning"
    return "danger"


# ============================================================
# 排版工具 (Quinn 14:08 反馈)
# ============================================================
def _font(point_size: int, bold: bool = False) -> QFont:
    """统一 QFont 构造，setPointSize + setBold"""
    f = QFont()
    f.setPointSize(point_size)
    f.setBold(bold)
    return f


# ============================================================
# 性能缓存 (Quinn 09:00 三轮: 仅在变化时调用 setText/setStyleSheet)
# ============================================================
# key = id(widget) -> 缓存值 (str or other)
_TEXT_CACHE: dict[int, str] = {}
_STYLE_CACHE: dict[int, str] = {}


def _set_if_diff(widget, text: str) -> None:
    """仅在文本与上次不同时调用 setText (避免不必要的重绘)."""
    wid = id(widget)
    cached = _TEXT_CACHE.get(wid)
    if cached == text:
        return
    widget.setText(text)
    _TEXT_CACHE[wid] = text


def _set_style_if_diff(widget, prop: str, css_rule: str) -> None:
    """仅在 css_rule 与上次不同时调用 setStyleSheet."""
    wid = id(widget)
    key = f"{wid}:{prop}"
    cached = _STYLE_CACHE.get(key)
    if cached == css_rule:
        return
    widget.setStyleSheet(css_rule)
    _STYLE_CACHE[key] = css_rule


def _label(text: str, kind: str = "body", bold: bool = False, color: str = "text_primary",
           word_wrap: bool = False) -> QLabel:
    """统一 QLabel 构造 (text, kind: title|sub|value|muted|info, ...)

    Quinn 17:30: 默认启用 word_wrap, 长文本超出 label 边界会自动换行而非被 Qt 截断/挤压.
    """
    lbl = QLabel(text)
    size_map = {
        "title":  t.FONT_SIZE["lg"],
        "subtitle": t.FONT_SIZE["xs"],
        "value": t.FONT_SIZE["base"],
        "muted": t.FONT_SIZE["xs"],
        "info":  t.FONT_SIZE["xs"],
    }
    lbl.setFont(_font(size_map.get(kind, t.FONT_SIZE["base"]), bold))
    # word_wrap 防止窄宽度下文本被压扁/裁掉
    lbl.setWordWrap(True)
    lbl.setStyleSheet(
        f"color: {t.color(color)}; background: transparent; border: none;"
    )
    return lbl


# ============================================================
# 单行 ElideRight label — 共享自 widgets.elide_label
#   Quinn 12:00 创建 (R9 GPU 型号防 wrap 撑高) + 16:11 修复 color/sizeHint
#   Quinn 16:11 (R11): 移到 widgets 包供 Card 等共享, 这里做 alias 别名.
# ============================================================
from llama_console_v2.widgets.elide_label import ElideLabel as _ElideLabel


# ============================================================
# Console Page
# ============================================================
class ConsolePage(QWidget):
    """3-column console: sidebar / engine / hardware. Stretches to window height."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ConsolePage")
        self.setStyleSheet("background: transparent; border: none;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- Header ---
        # Quinn 16:55: 关闭 show_online 删除右上角被挤压的状态元素
        self._header = PageHeader("llama-server 控制台 v2", show_online=False)
        outer.addWidget(self._header)

        # --- Body: QScrollArea 兜底 (R12 17:38: 窄/矮窗口下纵向滚动, 不挤压卡片) ---
        #   setWidgetResizable(True) → 内容够大时撑满不滚动 (全屏无滚动条),
        #   内容超视口高时纵向按需滚动条, 卡片保持自然高度不重叠.
        scroll = QScrollArea()
        scroll.setObjectName("ConsoleScroll")
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        outer.addWidget(scroll, 1)

        body = QWidget()
        body.setObjectName("ConsoleBody")
        body.setStyleSheet("background: transparent; border: none;")
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        scroll.setWidget(body)

        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(
            t.scaled(t.card_pad("inner_lr")), t.scaled(t.space("3")),
            t.scaled(t.card_pad("inner_lr")), t.scaled(t.space("3"))
        )
        body_layout.setSpacing(t.scaled(t.card_pad("col_gap")))
        body_layout.setSizeConstraint(QHBoxLayout.SizeConstraint.SetNoConstraint)

        self._engine_col = self._build_engine_col()
        self._hardware_col = self._build_hardware_col()
        # R12 (17:38): 引擎列改弹性 (stretch=1, 跟随窗口缩放), 硬件列占更大 (stretch=2)
        body_layout.addWidget(self._engine_col, 1)
        body_layout.addWidget(self._hardware_col, 2)

        QTimer.singleShot(0, self._force_relayout)

    def _force_relayout(self) -> None:
        """Window resize 后强制让所有 sub widget 重算 sizeHint, 防止 squeeze."""
        for card in [self._status_card, self._frp_card, self._token_card,
                     self._cpu_card, self._ram_card, self._gpu_card]:
            if hasattr(card, '_body'):
                card._body.updateGeometry()
        for attr in ['_cpu_bar', '_ram_bar', '_gpu0_core_bar', '_gpu0_vram_bar',
                     '_gpu1_core_bar', '_gpu1_vram_bar']:
            w = getattr(self, attr, None)
            if w is not None:
                w.updateGeometry()
        self._engine_col.updateGeometry()
        self._hardware_col.updateGeometry()
        self.updateGeometry()

        # --- Auto-refresh timer (Quinn 09:00 三轮: 5s→10s 减 CPU 占用) ---
        self._timer = QTimer(self)
        self._timer.setInterval(10000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        # Quinn 10:15: 启动期不阻塞 — 首帧用轻量默认快照 (即时),
        #   后台采集线程 ~1-2s 产出真实数据后, 再刷一次显真实数值.
        self.refresh()
        QTimer.singleShot(2000, self.refresh)

    # ========================================================================
    # Column builders
    # ========================================================================
    def _build_engine_col(self) -> QWidget:
        col = QWidget()
        col.setObjectName("EngineCol")
        col.setStyleSheet("background: transparent; border: none;")
        # Quinn 16:55 (二轮): 中间区域宽度不够, 用 min_w 注册到 scale 系统,
        # 这样窗口 resize 时 engine 列宽跟随 scale 自动调整.
        # R12 (17:38): 440→380, floor 360→320, 让引擎列在窄窗下更弹性不顶满
        t.min_w(col, 380, floor=320)
        col.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(col)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(t.scaled(t.card_pad("col_gap")))  # 16
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetNoConstraint)

        self._status_card = self._build_status_card()
        layout.addWidget(self._status_card, 1)

        self._frp_card = self._build_frp_card()
        layout.addWidget(self._frp_card, 1)

        # Quinn 17:53: 启动控制卡 → token 统计卡 (启动/停止功能下沉到侧边栏)
        self._token_card = self._build_token_card()
        layout.addWidget(self._token_card, 1)

        return col

    def _build_hardware_col(self) -> QWidget:
        col = QWidget()
        col.setObjectName("HardwareCol")
        col.setStyleSheet("background: transparent; border: none;")
        col.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(col)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(t.scaled(t.card_pad("col_gap")))  # 16
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetNoConstraint)

        # Quinn 16:55: CPU + RAM 改为同一行两个并排卡片
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(t.scaled(t.card_pad("col_gap")))  # 16
        top_row.setSizeConstraint(QHBoxLayout.SizeConstraint.SetNoConstraint)

        self._cpu_card = self._build_cpu_card()
        self._ram_card = self._build_ram_card()
        top_row.addWidget(self._cpu_card, 1)   # 等宽
        top_row.addWidget(self._ram_card, 1)
        layout.addLayout(top_row, 1)            # top_row 与 GPU 等高争空间

        self._gpu_card = self._build_gpu_card()
        layout.addWidget(self._gpu_card, 2)    # GPU 占更大 stretch

        return col

    # ========================================================================
    # Engine cards
    # ========================================================================
    def _build_status_card(self) -> Card:
        card = Card("llama-server 状态", icon="◉")
        self._status_pill = StatusPill("已停止", "stopped")
        card.set_pill(self._status_pill)

        body = card.body_layout  # 16:08: Card 内部已预装带 padding 的 QVBoxLayout
        # 16:08: padding 已由 Card.body_layout 内置，调用方无需再设
        # 16:08: spacing 由 Card.body_layout 内置覆盖

        # 模型名 (title) — Quinn 16:11: 改 _ElideLabel 单行省略, 窄宽下不换行挤压
        self._model_name_lbl = _ElideLabel("qwen3.8-27b", color=t.color("text_primary"))
        self._model_name_lbl.setFont(_font(t.FONT_SIZE["lg"], bold=True))
        self._model_name_lbl.setMaximumHeight(t.scaled(t.row_height("lg"), floor=22))
        self._model_name_lbl.setMinimumWidth(0)  # 允许被拉伸
        body.addWidget(self._model_name_lbl)

        # 模型副信息 — Quinn 16:11 (R12): 删掉 quant, 改 ctx + port
        self._model_sub_lbl = _label("ctx - · port -",
                                      "subtitle", color="text_secondary")
        t.min_h(self._model_sub_lbl, t.row_height("sm"))  # 30
        body.addWidget(self._model_sub_lbl)

        # gap (8)
        body.addSpacing(t.scaled(t.space("2")))

        # Key/Value grid (3 行)
        from llama_console_v2.widgets.key_value import KeyValueGrid
        self._status_grid = KeyValueGrid(
            [
                ("运行时间", "-"),
                ("PID", "-"),
                ("监听地址", "-"),
            ]
        )
        t.min_h(self._status_grid, 88)  # Quinn 09:00 三轮: 收紧让全屏无滚动
        body.addWidget(self._status_grid)
        # R12 (17:38): grid 与外网地址之间加视觉间距, 避免"监听地址/外网地址/局域网地址"挤成一团
        body.addSpacing(t.scaled(t.space("3")))

        # Quinn 16:55 (二轮): 砍掉冗余 "OpenAI 兼容 URL" 顶层 label,
        # 紧接两个 URL 块, 各自带"外网地址/局域网地址"小 label, 卡片整体更紧凑

        # 外网 URL 块
        public_title = _label("外网地址", "muted", color="text_secondary")
        t.min_h(public_title, t.row_height("sm"))  # 24
        body.addWidget(public_title)

        self._public_url_lbl = QLabel("-")
        self._public_url_lbl.setWordWrap(True)
        t.min_h(self._public_url_lbl, 32)
        self._public_url_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._public_url_lbl.setFont(_font(t.FONT_SIZE["xs"]))
        self._public_url_lbl.setStyleSheet(
            f"color: {t.color('info')}; background: rgba(96,165,250,0.08);"
            f" border-radius: {t.scaled(4)}px; padding: {t.scaled(6)}px {t.scaled(10)}px;"
        )
        body.addWidget(self._public_url_lbl)

        # 局域网 URL 块
        local_title = _label("局域网地址", "muted", color="text_secondary")
        t.min_h(local_title, t.row_height("sm"))  # 24
        body.addWidget(local_title)

        self._local_url_lbl = QLabel("-")
        self._local_url_lbl.setWordWrap(True)
        t.min_h(self._local_url_lbl, 32)
        self._local_url_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._local_url_lbl.setFont(_font(t.FONT_SIZE["xs"]))
        self._local_url_lbl.setStyleSheet(
            f"color: {t.color('info')}; background: rgba(96,165,250,0.08);"
            f" border-radius: {t.scaled(4)}px; padding: {t.scaled(6)}px {t.scaled(10)}px;"
        )
        body.addWidget(self._local_url_lbl)

        return card

    def _build_frp_card(self) -> Card:
        card = Card("FRP 隧道", icon="⚡")
        self._frp_pill = StatusPill("未连接", "disconnected")
        card.set_pill(self._frp_pill)

        body = card.body_layout  # 16:08: Card 内部已预装带 padding 的 QVBoxLayout
        # 16:08: padding 已由 Card.body_layout 内置，调用方无需再设
        # 16:08: spacing 由 Card.body_layout 内置覆盖

        from llama_console_v2.widgets.key_value import KeyValueGrid
        self._frp_grid = KeyValueGrid(
            [
                ("隧道名", "-"),
                ("远程端口", "-"),
                ("本地端口", "-"),
                ("公网地址", "-"),
            ]
        )
        # Quinn 16:55: 4 行 × 36 + 间距, 容纳 label/value 呼吸空间
        t.min_h(self._frp_grid, 140)
        body.addWidget(self._frp_grid)

        return card

    def _build_token_card(self) -> Card:
        """Token 统计卡 (Quinn 09:00 三轮反馈: 删除底部「停止」按钮, 已下沉侧边栏)

        - 输入总 token (prompt_tokens_total) - 大号数字
        - 输出总 token (tokens_predicted_total) - 大号数字
        - 速度 (predicted_tokens_seconds) - 实时 tok/s
        - 启动/停止功能已下沉到侧边栏 ServerControlSidebar
        """
        card = Card("Token 统计", icon="📊")
        body = card.body_layout

        # ---------- Row 1: 输入输出 token 并排 ----------
        from PySide6.QtWidgets import QFrame as _QFrame

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(t.scaled(t.card_pad("col_gap")))

        # 输入 token 卡 (mini)
        input_col = QVBoxLayout()
        input_col.setContentsMargins(0, 0, 0, 0)
        input_col.setSpacing(t.scaled(t.space("1")))
        input_title = _label("输入总 Token", "muted", color="text_secondary")
        t.min_h(input_title, t.row_height("sm"), floor=20)
        input_col.addWidget(input_title)
        self._token_in_lbl = _label("-", "title", bold=True, color="info")
        font_big = QFont()
        font_big.setPointSize(t.FONT_SIZE["3xl"])
        font_big.setBold(True)
        self._token_in_lbl.setFont(font_big)
        t.min_h(self._token_in_lbl, t.row_height("xl"), floor=36)
        input_col.addWidget(self._token_in_lbl)
        input_col.addStretch(1)
        input_row.addLayout(input_col, 1)

        # 垂直分隔
        vline = _QFrame()
        vline.setFrameShape(_QFrame.Shape.VLine)
        vline.setStyleSheet(f"color: {t.color('border')}; background: transparent;")
        vline.setFixedWidth(1)
        input_row.addWidget(vline)

        # 输出 token 卡 (mini)
        output_col = QVBoxLayout()
        output_col.setContentsMargins(0, 0, 0, 0)
        output_col.setSpacing(t.scaled(t.space("1")))
        output_title = _label("输出总 Token", "muted", color="text_secondary")
        t.min_h(output_title, t.row_height("sm"), floor=20)
        output_col.addWidget(output_title)
        self._token_out_lbl = _label("-", "title", bold=True, color="success")
        self._token_out_lbl.setFont(font_big)
        t.min_h(self._token_out_lbl, t.row_height("xl"), floor=36)
        output_col.addWidget(self._token_out_lbl)
        output_col.addStretch(1)
        input_row.addLayout(output_col, 1)

        body.addLayout(input_row)

        body.addSpacing(t.scaled(t.space("2")))

        # ---------- Row 2: 速度 (大条) ----------
        speed_row = QWidget()
        speed_row.setObjectName("TokenSpeedRow")
        speed_row.setStyleSheet(
            f"""
            QWidget#TokenSpeedRow {{
                background-color: rgba(96, 165, 250, 0.08);
                border: 1px solid rgba(96, 165, 250, 0.18);
                border-radius: {t.scaled(8, floor=6)}px;
            }}
            """
        )
        speed_lay = QHBoxLayout(speed_row)
        speed_lay.setContentsMargins(
            t.scaled(12, floor=8), t.scaled(6, floor=4),
            t.scaled(12, floor=8), t.scaled(6, floor=4),
        )
        speed_lay.setSpacing(t.scaled(t.space("2")))

        # Quinn 11:35: "生成速度" 文字 — 靠左, 整行不再 stretch
        speed_title = _label("生成速度", "muted", color="text_secondary", bold=True)
        speed_title.setStyleSheet(
            f"color: {t.color('text_secondary')}; background: transparent; border: none;"
            f" letter-spacing: 0.5px;"
        )
        speed_lay.addWidget(speed_title, 0, Qt.AlignmentFlag.AlignVCenter)

        # Quinn 11:35: 数字+单位 — 紧跟 "生成速度" 后面, 与 title 水平对齐
        # 之前用 stretch(1) 把数字推右, 单位又 AlignBottom, 不对齐也不直观
        self._token_speed_lbl = QLabel("-")
        f_speed = QFont()
        f_speed.setPointSize(t.FONT_SIZE["2xl"])
        f_speed.setBold(True)
        self._token_speed_lbl.setFont(f_speed)
        self._token_speed_lbl.setStyleSheet(
            f"color: {t.color('primary')}; background: transparent; border: none;"
            f" font-family: {t.FONT_FAMILY_MONO};"
        )
        speed_lay.addWidget(self._token_speed_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        speed_unit = _label("tok/s", "muted", color="text_secondary")
        speed_unit.setStyleSheet(
            f"color: {t.color('text_secondary')}; background: transparent; border: none;"
        )
        # 单位与 "生成速度" 水平对齐 (用 VCenter, 不要 Bottom)
        speed_lay.addWidget(speed_unit, 0, Qt.AlignmentFlag.AlignVCenter)

        # 右侧留白, 让 [生成速度 数字 单位] 整组靠左
        speed_lay.addStretch(1)

        body.addWidget(speed_row)

        body.addSpacing(t.scaled(t.space("2")))

        # ---------- Row 3: 总量 / 提示 (替代停止按钮) ----------
        self._token_total_lbl = _label(
            "等待 llama-server 启动 --metrics 暴露 token 统计 …",
            "muted", color="text_secondary",
        )
        self._token_total_lbl.setWordWrap(True)
        t.min_h(self._token_total_lbl, t.row_height("sm"), floor=20)
        body.addWidget(self._token_total_lbl)

        return card

    # ========================================================================
    # Hardware cards
    # ========================================================================
    def _build_cpu_card(self) -> Card:
        card = Card("CPU", icon="⚙")
        body = card.body_layout  # 16:08: Card 内部已预装带 padding 的 QVBoxLayout
        # 16:08: padding 已由 Card.body_layout 内置，调用方无需再设
        # 16:08: spacing 由 Card.body_layout 内置覆盖

        # CPU 型号 — Quinn 16:11: 改 _ElideLabel 单行省略, 窄宽下不换行挤压
        self._cpu_model_lbl = _ElideLabel("-", color=t.color("text_primary"))
        self._cpu_model_lbl.setFont(_font(t.FONT_SIZE["lg"], bold=True))
        self._cpu_model_lbl.setMaximumHeight(t.scaled(t.row_height("lg"), floor=22))
        body.addWidget(self._cpu_model_lbl)

        # Quinn 11:35: 核心/线程 小灰字 (低优先级副信息)
        self._cpu_cores_lbl = _label("-", "muted", color="text_secondary")
        t.min_h(self._cpu_cores_lbl, t.row_height("sm"), floor=18)
        body.addWidget(self._cpu_cores_lbl)

        # Quinn 11:35: 实时频率 — 单独突出显示, 大号 primary 色, 不与 cores 混在一行
        # 旧版在 cores 后追加 "· X.XX GHz" 太次要, 用户要频率成为视觉焦点
        self._cpu_freq_lbl = _label("-", "title", bold=True, color="info")
        f_freq = QFont()
        f_freq.setPointSize(t.FONT_SIZE["2xl"])  # 20pt 突出
        f_freq.setBold(True)
        self._cpu_freq_lbl.setFont(f_freq)
        self._cpu_freq_lbl.setStyleSheet(
            f"color: {t.color('primary')}; background: transparent; border: none;"
            f" font-family: {t.FONT_FAMILY_MONO};"
        )
        t.min_h(self._cpu_freq_lbl, 40, floor=32)
        body.addWidget(self._cpu_freq_lbl)

        # Quinn 09:30: 删除 L1/L2/L3 缓存行 (用户反馈: 不需要展示)
        # 原 _cpu_cache_lbl 整段移除

        # gap (收紧 8→6)
        body.addSpacing(t.scaled(t.space("1")))

        # 利用率进度条
        self._cpu_bar = ProgressBar("利用率", percent=0, color="success")
        t.min_h(self._cpu_bar, 40)  # Quinn 09:00 三轮: 紧凑 1.5x 行距
        body.addWidget(self._cpu_bar)

        # CPU 温度
        self._cpu_temp_lbl = _label("温度 -", "value", bold=True, color="text_secondary")
        t.min_h(self._cpu_temp_lbl, t.row_height("md"), floor=20)
        body.addWidget(self._cpu_temp_lbl)

        return card

    def _build_ram_card(self) -> Card:
        card = Card("内存 RAM", icon="🧠")
        body = card.body_layout  # 16:08: Card 内部已预装带 padding 的 QVBoxLayout
        # 16:08: padding 已由 Card.body_layout 内置，调用方无需再设
        # 16:08: spacing 由 Card.body_layout 内置覆盖

        # Quinn 16:55 (二轮): 类型/容量/频率 三行合并到一行, 避免信息分散
        # Quinn 16:11: 改 _ElideLabel 单行省略, 窄宽下不换行挤压
        self._ram_info_lbl = _ElideLabel("-", color=t.color("text_primary"))
        self._ram_info_lbl.setFont(_font(t.FONT_SIZE["lg"], bold=True))
        self._ram_info_lbl.setMaximumHeight(t.scaled(t.row_height("lg"), floor=22))
        body.addWidget(self._ram_info_lbl)

        # gap (8)
        body.addSpacing(t.scaled(t.space("2")))

        # 利用率进度条
        self._ram_bar = ProgressBar("利用率", percent=0, color="info")
        t.min_h(self._ram_bar, 40)  # Quinn 09:00 三轮: 紧凑
        body.addWidget(self._ram_bar)

        # RAM 已用/总量
        self._ram_used_lbl = _label("-", "muted", color="text_secondary")
        t.min_h(self._ram_used_lbl, t.row_height("sm"))  # 24
        body.addWidget(self._ram_used_lbl)

        return card

    def _build_gpu_card(self) -> Card:
        """GPU 父卡，内含 GPU0 / GPU1 2 个子卡（横向）

        Quinn 17:53: 父卡 icon 由 "◇" 字符改为 ChipSvgIcon 矢量芯片 SVG (跟随主题主色).
        """
        card = Card("GPU 信息", icon=ChipSvgIcon(color="primary"))
        body = card.body_layout  # 16:08: Card 内部已预装带 padding 的 QVBoxLayout
        # 16:08: padding 已由 Card.body_layout 内置，调用方无需再设
        # 16:08: GPU 父卡用 col_gap，调大
        body.setSizeConstraint(QVBoxLayout.SizeConstraint.SetNoConstraint)

        gpu_grid = QHBoxLayout()
        gpu_grid.setContentsMargins(0, 0, 0, 0)
        gpu_grid.setSpacing(t.scaled(t.card_pad("col_gap")))  # 16
        gpu_grid.setSizeConstraint(QHBoxLayout.SizeConstraint.SetNoConstraint)

        gpu0 = self._build_gpu_sub_card(0)
        gpu1 = self._build_gpu_sub_card(1)
        gpu_grid.addWidget(gpu0, 1)
        gpu_grid.addWidget(gpu1, 1)

        body.addLayout(gpu_grid, 1)
        return card

    def _build_gpu_sub_card(self, idx: int) -> QFrame:
        """GPU 子卡（0 或 1）— 5 段: 标题/型号/核心 bar/VRAM bar/VRAM 已用比/温度

        Quinn 16:55 (二轮):
        - 1.5x 行距: 减小 row_height 和 spacing (10→6)
        - VRAM 容量从独立一行移到 VRAM bar 下面, 显已用/总 (如 6.5 / 8G)
        - 整体更紧凑, 避免 GPU 父卡上下行距过大

        Quinn 12:00: 型号 label 改单行 ElideRight 自定义 QLabel 类, 避免
        (RTX 3070 Laptop GPU 之类) wrap 3 行撑高整张子卡, 导致矮窗口下
        GPU 父卡内容被压扁/截断.
        """
        frame = QFrame()
        frame.setObjectName(f"GpuSub{idx}")
        frame.setStyleSheet(
            f"""
            QFrame#GpuSub{idx} {{
                background-color: rgba(255,255,255,0.02);
                border: 1px solid {t.color('border')};
                border-radius: {t.radius('md')}px;
            }}
            """
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(
            t.scaled(t.space("3")), t.scaled(t.space("3")),
            t.scaled(t.space("3")), t.scaled(t.space("3"))
        )
        # Quinn 16:55 (二轮): 10→6, 1.5x 行距, 上下节奏更紧凑
        layout.setSpacing(t.scaled(6))
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetNoConstraint)

        # 标题 "GPU 0"
        title_lbl = _label(f"GPU {idx}", "title", bold=True, color="text_secondary")
        t.min_h(title_lbl, t.row_height("lg"))  # 32
        layout.addWidget(title_lbl)

        # Quinn 12:00: 型号 — 用 _ElideLabel (单行 ElideRight, 不撑高)
        model_lbl = _ElideLabel("-", color=t.color("text_primary"))
        model_lbl.setFont(_font(t.FONT_SIZE["base"]))
        model_lbl.setMaximumHeight(t.scaled(t.row_height("md"), floor=28))
        model_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(model_lbl)

        # 核心利用率
        core_bar = ProgressBar("核心", percent=0, color="success")
        t.min_h(core_bar, 36)  # 40→36 紧凑
        layout.addWidget(core_bar)

        # VRAM 利用率
        vram_bar = ProgressBar("VRAM", percent=0, color="info")
        t.min_h(vram_bar, 36)
        layout.addWidget(vram_bar)

        # Quinn 16:55 (二轮): VRAM 已用/总 (e.g. "6.5 / 8G")
        vram_used_lbl = _label("-", "muted", color="text_secondary")
        t.min_h(vram_used_lbl, t.row_height("sm"))  # 24
        layout.addWidget(vram_used_lbl)

        # 核心温度
        core_temp_lbl = _label("核心温度 -", "value", bold=True, color="text_secondary")
        t.min_h(core_temp_lbl, t.row_height("md"), floor=20)
        layout.addWidget(core_temp_lbl)

        # Quinn 11:35: VRAM 显存温度行 — 不可用时整行隐藏 (不创建 widget)
        # 旧版永远占位 "显存温度 -" 太丑, 删了
        # 占位 widget: refresh 时按数据决定 show/hide
        vram_temp_lbl = _label("显存温度", "value", bold=True, color="text_secondary")
        t.min_h(vram_temp_lbl, t.row_height("md"), floor=20)
        vram_temp_lbl.hide()  # 默认隐藏, 有数据再显
        layout.addWidget(vram_temp_lbl)

        # 存到 self
        setattr(self, f"_gpu{idx}_model_lbl", model_lbl)
        setattr(self, f"_gpu{idx}_vram_used_lbl", vram_used_lbl)
        setattr(self, f"_gpu{idx}_core_bar", core_bar)
        setattr(self, f"_gpu{idx}_vram_bar", vram_bar)
        setattr(self, f"_gpu{idx}_core_temp_lbl", core_temp_lbl)
        setattr(self, f"_gpu{idx}_vram_temp_lbl", vram_temp_lbl)
        return frame

    # ========================================================================
    # Actions (Quinn 09:00 三轮反馈: 启动/停止均下沉到侧边栏 ServerControlSidebar, 此处仅保留刷新逻辑)
    # ========================================================================
    def _on_stop(self) -> None:
        """保留兼容入口: 供 MainWindow 显式调用"""
        from llama_console_v2.backend import llama_cpp as backend_llama
        backend_llama.stop()

    # ========================================================================
    # Refresh
    # ========================================================================
    def refresh(self) -> None:
        """刷新全部 (Quinn 09:00 三轮: setUpdatesEnabled 批量重绘, 减卡顿)"""
        self.setUpdatesEnabled(False)
        try:
            try:
                self._refresh_llama()
            except Exception as e:  # noqa: BLE001
                print(f"[console] refresh llama error: {e}")
            try:
                self._refresh_token()
            except Exception as e:  # noqa: BLE001
                print(f"[console] refresh token error: {e}")
            try:
                self._refresh_hardware()
            except Exception as e:  # noqa: BLE001
                print(f"[console] refresh hardware error: {e}")
            try:
                self._refresh_frp()
            except Exception as e:  # noqa: BLE001
                print(f"[console] refresh frp error: {e}")
        finally:
            self.setUpdatesEnabled(True)

    def _refresh_llama(self) -> None:
        snap = backend_llama.snapshot()
        # Status
        state_map = {
            "stopped":  ("已停止", "stopped"),
            "starting": ("加载中", "loading"),
            "loading":  ("加载中", "loading"),
            "running":  ("运行中", "running"),
            "error":    ("错误", "error"),
            "failed":   ("启动失败", "failed"),  # Quinn T1-D
        }
        text, state = state_map.get(snap.state, (snap.state, "stopped"))
        self._status_pill.set_text(text)
        self._status_pill.set_state(state)

        # Model name
        _set_if_diff(self._model_name_lbl, snap.model_name or "-")
        # Quinn 16:11 (R12): 副标题改为 ctx + port (删除 quant)
        parts: list[str] = []
        if snap.ctx_size:
            parts.append(f"ctx {snap.ctx_size}")
        if snap.port:
            parts.append(f"port {snap.port}")
        _set_if_diff(self._model_sub_lbl, " · ".join(parts) if parts else "-")

        # Key/Value
        self._status_grid.set_value(0, snap.uptime or "-")
        self._status_grid.set_value(1, str(snap.pid) if snap.pid else "-")
        self._status_grid.set_value(2, snap.bind or "-")

        # URLs
        # Quinn 16:11 (R12): public_url 由 frp 快照合并 — llama backend 不再
        # 硬编码假地址; llama 运行中且 frp 已连接时显示真实公网地址
        public_url = snap.public_url
        if not public_url and snap.state in ("running", "starting", "loading"):
            try:
                _frp_snap = backend_frp.snapshot()
                if getattr(_frp_snap, "connected", False) and getattr(_frp_snap, "public_url", None):
                    public_url = _frp_snap.public_url
            except Exception:
                pass
        _set_if_diff(self._public_url_lbl, public_url or "-")
        _set_if_diff(self._local_url_lbl, snap.local_url or "-")

    def _refresh_hardware(self) -> None:
        """硬件刷新 (Quinn 09:00 三轮: 1) 缓存值仅在变化时 setText; 2) ProgressBar 缓存 color)"""
        h = backend_hardware.snapshot()

        # ---- CPU ----
        cpu_model = h.cpu.model or "-"
        _set_if_diff(self._cpu_model_lbl, cpu_model)

        # Quinn 11:35: 核心/线程 仅显示次要信息, 频率单独突出 (见 _cpu_freq_lbl)
        cores_text = f"{h.cpu.cores_physical}P / {h.cpu.cores_logical}L"
        _set_if_diff(self._cpu_cores_lbl, cores_text)

        # Quinn 11:35: 频率单独显示, 大号 primary 色 — 这是用户视觉焦点
        # 不再拼接 cores, 也不再有 (静态) 后缀 (静态值就是静态值, 用户能接受)
        def _fmt_freq(mhz: int) -> str:
            if mhz >= 1000:
                return f"{mhz / 1000:.2f} GHz"
            return f"{mhz} MHz"

        live_mhz = getattr(h.cpu, "freq_mhz", 0) or 0
        if live_mhz:
            freq_text = _fmt_freq(live_mhz)
        else:
            freq_text = "-"
        _set_if_diff(self._cpu_freq_lbl, freq_text)

        # Quinn 09:30: 删除 L1/L2/L3 行 (用户反馈)

        cpu_pct = int(h.cpu.util_percent) if h.cpu.util_percent is not None else 0
        self._cpu_bar.set_value(cpu_pct, color=_util_color(cpu_pct))

        if h.cpu.temp_c is None:
            temp_text = "温度 未检测到传感器"
            temp_color_key = "text_secondary"
        else:
            temp_text = f"温度 {h.cpu.temp_c:.0f} °C"
            temp_color_key = _temp_color(h.cpu.temp_c)
        _set_if_diff(self._cpu_temp_lbl, temp_text)
        _set_style_if_diff(self._cpu_temp_lbl, "color", f"color: {t.color(temp_color_key)};")

        # ---- RAM ----
        ram_parts = [h.ram.type or "?"]
        if h.ram.capacity_gb:
            ram_parts.append(f"{h.ram.capacity_gb:.1f} GB")
        if h.ram.freq_mhz:
            ram_parts.append(f"{h.ram.freq_mhz} MHz")
        _set_if_diff(self._ram_info_lbl, " · ".join(ram_parts))

        ram_pct = int(h.ram.util_percent) if h.ram.util_percent is not None else 0
        self._ram_bar.set_value(ram_pct, color=_util_color(ram_pct))
        ram_used_text = (
            f"已用 {h.ram.used_gb:.1f} GB / {h.ram.capacity_gb:.1f} GB"
            if h.ram.used_gb is not None and h.ram.capacity_gb else "-"
        )
        _set_if_diff(self._ram_used_lbl, ram_used_text)

        # ---- GPU ----
        # Quinn 09:30: 处理空态 (没显卡机器/无 nvidia-smi 都没数据)
        if not h.gpus:
            _set_if_diff(self._gpu0_model_lbl, "未检测到独立 GPU")
            _set_if_diff(self._gpu0_vram_used_lbl,
                         "本机无 NVIDIA GPU 或未安装 nvidia-smi")
            # 进度条清零
            self._gpu0_core_bar.set_value(0, color="text_muted")
            self._gpu0_vram_bar.set_value(0, color="text_muted")
            _set_if_diff(self._gpu0_core_temp_lbl, "核心温度 不支持")
            _set_style_if_diff(self._gpu0_core_temp_lbl, "color",
                               f"color: {t.color('text_muted')};")
            # Quinn 11:35: 无 GPU 时 VRAM 温度行也整行隐藏
            if self._gpu0_vram_temp_lbl.isVisible():
                self._gpu0_vram_temp_lbl.hide()
            # GPU1 同样处理
            _set_if_diff(self._gpu1_model_lbl, "-")
            _set_if_diff(self._gpu1_vram_used_lbl, "-")
            self._gpu1_core_bar.set_value(0, color="text_muted")
            self._gpu1_vram_bar.set_value(0, color="text_muted")
            _set_if_diff(self._gpu1_core_temp_lbl, "核心温度 -")
            _set_style_if_diff(self._gpu1_core_temp_lbl, "color",
                               f"color: {t.color('text_muted')};")
            if self._gpu1_vram_temp_lbl.isVisible():
                self._gpu1_vram_temp_lbl.hide()
            return

        for idx, gpu in enumerate(h.gpus[:2]):
            model_lbl = getattr(self, f"_gpu{idx}_model_lbl")
            vram_used_lbl = getattr(self, f"_gpu{idx}_vram_used_lbl")
            core_bar = getattr(self, f"_gpu{idx}_core_bar")
            vram_bar = getattr(self, f"_gpu{idx}_vram_bar")
            core_temp_lbl = getattr(self, f"_gpu{idx}_core_temp_lbl")
            vram_temp_lbl = getattr(self, f"_gpu{idx}_vram_temp_lbl")

            # GPU 名称 (WMI 来源时显驱动版本作 hint)
            gpu_label = gpu.model or "-"
            src = getattr(gpu, "source", "nvidia-smi")
            if src == "wmi":
                drv = getattr(gpu, "driver_version", "")
                if drv:
                    gpu_label = f"{gpu_label} (WMI)"
            _set_if_diff(model_lbl, gpu_label)

            if gpu.vram_total_mb and gpu.vram_used_mb is not None:
                used_gb = gpu.vram_used_mb / 1024
                total_gb = gpu.vram_total_mb / 1024
                vram_text = f"{used_gb:.1f} / {total_gb:.1f}G"
            elif gpu.vram_total_mb and gpu.vram_util_percent is not None:
                used_gb = (gpu.vram_total_mb * gpu.vram_util_percent / 100) / 1024
                total_gb = gpu.vram_total_mb / 1024
                vram_text = f"{used_gb:.1f} / {total_gb:.1f}G"
            elif gpu.vram_total_mb:
                # WMI 兜底场景: 只知总量, 不知已用
                vram_text = f"- / {gpu.vram_total_mb / 1024:.1f}G"
            else:
                vram_text = "-"
            _set_if_diff(vram_used_lbl, vram_text)

            # 利用率: WMI 兜底场景可能为 None
            core_pct = int(gpu.util_percent) if gpu.util_percent is not None else 0
            core_bar.set_value(core_pct, color=_util_color(core_pct) if gpu.util_percent is not None else "text_muted")
            vram_pct = int(gpu.vram_util_percent) if gpu.vram_util_percent is not None else 0
            vram_bar.set_value(vram_pct, color=_util_color(vram_pct) if gpu.vram_util_percent is not None else "text_muted")

            # 核心温度
            if gpu.temp_c is not None:
                ct_text = f"核心温度 {gpu.temp_c:.0f} °C"
                ct_col = _temp_color(gpu.temp_c)
            else:
                ct_text = "核心温度 不支持" if src == "wmi" else "核心温度 -"
                ct_col = "text_muted" if src == "wmi" else "text_secondary"
            _set_if_diff(core_temp_lbl, ct_text)
            _set_style_if_diff(core_temp_lbl, "color", f"color: {t.color(ct_col)};")

            # Quinn 11:35: VRAM 显存温度 — 有数据时显行, 无数据时整行 hide
            vram_temp_val = getattr(gpu, "vram_temp_c", None)
            if vram_temp_val is not None:
                vt_text = f"显存温度 {vram_temp_val:.0f} °C"
                vt_col = _temp_color(vram_temp_val)
                _set_if_diff(vram_temp_lbl, vt_text)
                _set_style_if_diff(vram_temp_lbl, "color", f"color: {t.color(vt_col)};")
                if not vram_temp_lbl.isVisible():
                    vram_temp_lbl.show()
            else:
                # Quinn 11:35: 不可用时整行隐藏 (而不是显 "不支持" / "-")
                if vram_temp_lbl.isVisible():
                    vram_temp_lbl.hide()

    def _refresh_frp(self) -> None:
        snap = backend_frp.snapshot()
        self._frp_pill.set_text("已连接" if snap.connected else "未连接")
        self._frp_pill.set_state("connected" if snap.connected else "disconnected")
        self._frp_grid.set_value(0, snap.tunnel_name or "-")
        self._frp_grid.set_value(1, str(snap.remote_port) if snap.remote_port else "-")
        self._frp_grid.set_value(2, str(snap.local_port) if snap.local_port else "-")
        self._frp_grid.set_value(3, snap.public_url or "-")

    # ========================================================================
    # Token 统计刷新 (Quinn 09:00 三轮: stop_btn 移除, 仅保留提示)
    # ========================================================================
    def _refresh_token(self) -> None:
        snap = backend_llama.get_token_stats()
        # 千分位格式化 token 数
        def _fmt(n: int | None) -> str:
            if n is None:
                return "-"
            if n < 1000:
                return str(n)
            if n < 1_000_000:
                return f"{n/1000:.1f}K"
            return f"{n/1_000_000:.2f}M"

        if snap.available:
            self._token_in_lbl.setText(_fmt(snap.prompt_tokens))
            self._token_out_lbl.setText(_fmt(snap.predicted_tokens))
            self._token_speed_lbl.setText(
                f"{snap.predicted_tps:.1f}" if snap.predicted_tps else "0.0"
            )
            # 总量提示 (统计启动后总流量)
            total = (snap.prompt_tokens or 0) + (snap.predicted_tokens or 0)
            self._token_total_lbl.setText(
                f"启动至今: 输入 {snap.prompt_tokens or 0:,} · 输出 {snap.predicted_tokens or 0:,} · 合计 {total:,} tokens"
            )
        else:
            # Quinn 16:11 (R12): 服务未运行时, 有 stale 值就显示最后统计
            has_stale = getattr(snap, "stale", False) and snap.prompt_tokens is not None
            if has_stale:
                self._token_in_lbl.setText(_fmt(snap.prompt_tokens))
                self._token_out_lbl.setText(_fmt(snap.predicted_tokens))
                self._token_speed_lbl.setText(
                    f"{snap.predicted_tps:.1f}" if snap.predicted_tps else "-"
                )
                # stale_ts ISO string "YYYY-MM-DDTHH:MM:SS" → 取 HH:MM:SS 部分
                stale_ts = getattr(snap, "stale_ts", "") or ""
                hh_mm_ss = stale_ts.split("T", 1)[1][:8] if "T" in stale_ts else stale_ts
                self._token_total_lbl.setText(
                    f"最后统计 {hh_mm_ss}"
                )
            else:
                # /metrics 不可用 且无历史快照 (首次启动 / 未服务过)
                self._token_in_lbl.setText("-")
                self._token_out_lbl.setText("-")
                self._token_speed_lbl.setText("-")
                # Quinn 16:11 (R11): 删掉「提示」文字 (按用户要求), 卡片只剩数字占位"
                self._token_total_lbl.setText("")
