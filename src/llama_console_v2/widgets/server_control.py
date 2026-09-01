"""ServerControlSidebar - 侧边栏底部 Server 控制区段 (Quinn 09:00 反馈).

设计：
- 仅 2 个按钮：「启动」「停止」(Quinn 09:00: 删 "快速/长文/调试" 方案, 启动参数从设置页 cmdline_args 读取)
- 当前 llama-server state 决定按钮 enabled 状态:
  - stopped/loading → 启动可点，停止禁用
  - running          → 启动禁用，停止可点
  - error            → 两者都可点 (允许强制重启)
- 启动参数：直接 current_cmdline_args() (用户在设置页保存的), 不再用内置方案
- 自动轮询 backend_llama.snapshot() (1.5s 间隔) 刷新按钮状态
- 信号: start_clicked / stop_clicked 由 MainWindow 捕获调 backend_llama.start() / stop()

Quinn 11:04 (第六轮): 按钮图标改为 setIcon(QIcon) 几何矢量渲染
- 原用 Unicode 字符 "▶"/"⏹" 直接拼进 QPushButton 文本 → 几何字符与文字 x-height
  基线错位 (▶ 视觉中心略偏上, ⏹ 居中), 看起来上下不齐
- 新方案: QPainter 画 QPixmap (居中三角形/正方形), 通过 setIcon() 设置,
  Qt 自动按统一 baseline 对齐图标 + 文字, 各按钮视觉中心一致
"""
import time

from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

# 2026-09-01 (bug fix): 启动后进程「真死」判定宽限期.
# 27B 模型加载 2-4 min, 期间进程一直活着 (snapshot.state=loading, pid 非空),
# 所以只要进程活着就绝不报失败. 这里只对「进程已消失」且已过宽限 (避免慢 spawn
# 误判) 才标 failed. 参数错/端口冲突等真失败进程会在 ~2s 内消失, 远小于宽限期.
_PENDING_GRACE_S = 15

from llama_console_v2 import theme as t
from llama_console_v2.backend import llama_cpp as backend_llama


# ============================================================
# Quinn 11:04: 按钮图标工厂 — 把 ▶ / ■ 用 QPainter 画成矢量 QPixmap,
# 让 QPushButton.setIcon() + setText() 由 Qt 内部统一垂直居中,
# 避免 Unicode 几何字符 (三角/方块) 与文字基线错位问题
# ============================================================
def _make_icon(kind: str, color_hex: str, px: int = 14) -> QIcon:
    """矢量几何图标: 'play' = ▶ 等腰三角形, 'stop' = ■ 实心正方形.

    Returns:
        QIcon 含 Normal (主色) + Disabled (半透明灰) 2 态, 跟随按钮 enabled.
    """
    icon = QIcon()
    # ---- Normal 态: 主色 ----
    pix = QPixmap(px, px)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color_hex))
    p.setPen(Qt.PenStyle.NoPen)
    if kind == "play":
        # 等腰三角形, 右侧尖端居中, 视觉重心在画布中央
        margin_x = max(2, int(px * 0.18))
        margin_y = max(2, int(px * 0.18))
        path = QPainterPath()
        path.moveTo(margin_x, margin_y)
        path.lineTo(px - margin_x, px / 2)
        path.lineTo(margin_x, px - margin_y)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "stop":
        # 实心正方形, 上下左右对称, 居中无歧义
        m = max(2, int(px * 0.20))
        p.drawRect(QRect(m, m, px - 2 * m, px - 2 * m))
    p.end()
    icon.addPixmap(pix, QIcon.Mode.Normal, QIcon.State.On)

    # ---- Disabled 态: 同样形状 + 半透明灰, 按钮禁用时图标也变灰 ----
    pix_dis = QPixmap(px, px)
    pix_dis.fill(Qt.GlobalColor.transparent)
    p2 = QPainter(pix_dis)
    p2.setRenderHint(QPainter.RenderHint.Antialiasing)
    gray = QColor(140, 145, 155, 180)  # text_muted 近似色
    p2.setBrush(gray)
    p2.setPen(Qt.PenStyle.NoPen)
    if kind == "play":
        margin_x = max(2, int(px * 0.18))
        margin_y = max(2, int(px * 0.18))
        path = QPainterPath()
        path.moveTo(margin_x, margin_y)
        path.lineTo(px - margin_x, px / 2)
        path.lineTo(margin_x, px - margin_y)
        path.closeSubpath()
        p2.drawPath(path)
    elif kind == "stop":
        m = max(2, int(px * 0.20))
        p2.drawRect(QRect(m, m, px - 2 * m, px - 2 * m))
    p2.end()
    icon.addPixmap(pix_dis, QIcon.Mode.Disabled, QIcon.State.On)
    return icon


# ============================================================
# Service control state badge (mini)
# ============================================================
def _state_to_key(state: str) -> str:
    return {
        "running":  "running",
        "loading":  "loading",
        "starting": "loading",
        "stopped":  "stopped",
        "error":    "error",
        "failed":   "failed",  # Quinn T1-D: backend start ok 但 health_reachable=False
    }.get(state, "stopped")


# ============================================================
# 主组件: ServerControlSidebar
# ============================================================
class ServerControlSidebar(QWidget):
    """侧边栏底部「启动/停止」区段, 无分隔线无标题 (Quinn 09:00 反馈)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ServerControlSidebar")
        self.setStyleSheet(
            f"""
            QWidget#ServerControlSidebar {{
                background: transparent;
                border: none;
            }}
            """
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            t.scaled(t.space("3")), t.scaled(t.space("2")),
            t.scaled(t.space("3")), t.scaled(t.space("2")),
        )
        # Quinn 09:00 (第二轮): 按钮间距 8→4, 紧凑
        layout.setSpacing(t.scaled(t.space("1")))
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetNoConstraint)

        # Quinn 09:30 (第四轮): 上方 stretch 把按钮推至侧边栏垂直中段
        layout.addStretch(2)

        # ---- 紧凑状态指示 (圆点 + 文本, 内联) ----
        # Quinn 09:00 (第二轮): 删除大框 "未启动" 框框 (140px+),
        # 改为圆点 + 文本, 高度 ~20px. 保留状态反馈价值 (运行中/加载中/未启动/错误)
        self._status_dot = QLabel("\u25cf")  # ●
        dot_font = QFont()
        dot_font.setPointSize(t.FONT_SIZE["xs"])
        dot_font.setBold(True)
        self._status_dot.setFont(dot_font)
        self._status_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_dot.setMinimumHeight(t.scaled(14, floor=12))
        self._status_dot.setStyleSheet(
            f"color: {t.color('text_muted')}; background: transparent; border: none;"
        )

        self._status_text = QLabel("未启动")
        text_font = QFont()
        text_font.setPointSize(t.FONT_SIZE["xs"])
        text_font.setBold(True)
        self._status_text.setFont(text_font)
        self._status_text.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._status_text.setMinimumHeight(t.scaled(14, floor=12))
        self._status_text.setStyleSheet(
            f"color: {t.color('text_secondary')}; background: transparent; border: none;"
        )

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(t.scaled(t.space("1")))
        status_row.setSizeConstraint(QHBoxLayout.SizeConstraint.SetNoConstraint)
        status_row.addStretch(1)
        status_row.addWidget(self._status_dot)
        status_row.addWidget(self._status_text)
        status_row.addStretch(1)
        layout.addLayout(status_row)

        # 状态指示与按钮间小间距
        layout.addSpacing(t.scaled(t.space("2")))

        # ---- Start 按钮 (实心 primary) ----
        # Quinn 11:04: 图标改用 _make_icon 矢量渲染, Qt setIcon + setText 自动对齐基线
        self._start_btn = _SidebarActionButton(
            text="启动",
            icon_kind="play",
            style="primary",
        )
        self._start_btn.clicked.connect(self._on_start_clicked)
        layout.addWidget(self._start_btn)

        # ---- Stop 按钮 (描边 outline) ----
        self._stop_btn = _SidebarActionButton(
            text="停止",
            icon_kind="stop",
            style="outline",
        )
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        layout.addWidget(self._stop_btn)

        # Quinn 09:30: 下方 stretch=2 与上方对称, 把启动/停止 + 状态指示
        # 一起推到侧边栏垂直中央.
        layout.addStretch(3)

        # ---- state 轮询 (1.5s 间隔) ----
        self._last_state: str | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self._refresh_state)
        self._timer.start()
        # 立即拉一次
        self._refresh_state()

    # ============================================================
    # Internal
    # ============================================================
    def _refresh_state(self) -> None:
        """读取 backend_llama.snapshot().state 切换按钮 enabled.

        Quinn T1-D: 如果有 _force_state 覆盖 (mark_failed 或 3s pending 触发),
        强制用它作状态去 render. 一旦 backend snapshot state 追上 (比如切到
        running 或 stopped), 清覆盖, 恢复按 backend 走.
        """
        try:
            snap = backend_llama.snapshot()
            backend_state = snap.state
        except Exception:
            backend_state = "stopped"

        # Quinn T1-D: _force_state override 仅作 UI 提示用, 一旦 backend 追上
        # (running/stopped/error) 就让 backend 接手.
        force = getattr(self, "_force_state", None)
        if force == "failed":
            # 2026-09-01 (bug fix): failed override 唔可以被 backend=stopped 清除。
            # 旧逻辑 "force and backend in (running,stopped,error) -> clear" 会把
            # 刚启动就死嘅进程 (stopped) 又显示成「未启动」, 令「启动失败」永远
            # 弹唔出。这里只有 backend 确认 running (真启动成功) 先清 failed;
            # backend=stopped 时保留 failed (启动后进程消失 = 启动失败, 唔算未启动)。
            if backend_state == "running":
                self._force_state = None
                force = None
        elif force and backend_state in ("running", "stopped", "error"):
            self._force_state = None
            force = None
        state = force or backend_state

        if state == self._last_state:
            return  # 无变化不刷 UI
        self._last_state = state

        # 按钮启用规则
        if state == "running":
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(True)
        elif state in ("loading", "starting"):
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(True)
        elif state == "failed":
            # Quinn T1-D: 启动失败 — 两者都可点 (允许强制重启 / 停止清理)
            self._start_btn.setEnabled(True)
            self._stop_btn.setEnabled(True)
        else:  # stopped / error / unknown
            self._start_btn.setEnabled(True)
            self._stop_btn.setEnabled(False)

        # pill 文案 + 颜色
        state_text_map = {
            "running":  ("运行中",   "success"),
            "loading":  ("加载中",   "warning"),
            "starting": ("加载中",   "warning"),
            "stopped":  ("未启动",   "text_muted"),
            "error":    ("错误",     "danger"),
            "failed":   ("启动失败", "danger"),  # Quinn T1-D
        }
        text, color_key = state_text_map.get(state, ("未启动", "text_muted"))
        color_hex = t.color(color_key)
        # 紧凑指示: 圆点反映状态色, 文本保持次要色 (避免整片高亮)
        self._status_text.setText(text)
        self._status_text.setStyleSheet(
            f"color: {t.color('text_secondary')}; background: transparent; border: none;"
        )
        self._status_dot.setStyleSheet(
            f"color: {color_hex}; background: transparent; border: none;"
        )

    def _on_start_clicked(self) -> None:
        """启动 llama-server: 读取 current_cmdline_args() 作为 extra_args.

        Quinn 2026-09-01 (bug fix): 移除「3s 强制 failed」误报。
        根因: 旧逻辑在点启动后 3s 单发 timer 检查, 若 snapshot 仍 loading 就
        force pill 为「启动失败」。但 27B 模型实际加载需 2-4 分钟, 3s 时进程
        明明活着只是 health 未 ready → 被误报成启动失败。

        新逻辑: 改为周期检查(每 2s), 只在「进程真死」(pid 消失且 health 不达)
        且过了短宽限(避免慢 spawn 误判) 后才报 failed; 进程存活期间永远保持
        「加载中」, 由 1.5s 轮询自然过渡到「运行中」。
        """
        cb = getattr(self, "_on_start_cb", None)
        if cb is not None:
            cb()
        else:
            print("[ServerControlSidebar] no start callback registered")
        # Arm pending check (repeating, 每 2s) — 只有进程真死先报 failed
        self._start_pending = True
        self._pending_start_ts = time.monotonic()
        timer = getattr(self, "_pending_fail_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.timeout.connect(self._check_pending_failure)
            self._pending_fail_timer = timer
        timer.setInterval(2000)
        timer.start()

    def _check_pending_failure(self) -> None:
        """周期检查: 区分「加载中」vs「真失败」.

        - running          → 启动成功, 清 pending
        - loading + 进程活  → 合法加载期 (2-4 min), 保持「加载中」, 唔报失败
        - stopped + 已过宽限 → 进程真死 (参数错/端口冲突/加载 abort), 报「启动失败」
        - stopped + 未过宽限 → 可能慢 spawn, 继续等
        """
        if not getattr(self, "_start_pending", False):
            self._stop_pending_timer()
            return
        try:
            snap = backend_llama.snapshot()
            cur_state = snap.state
            pid = snap.pid
        except Exception:
            cur_state = "stopped"
            pid = None
        if cur_state == "running":
            # 启动成功 (health 200) — 结束 pending
            self._start_pending = False
            self._force_state = None
            self._stop_pending_timer()
            return
        if cur_state in ("loading", "starting") and pid is not None:
            # 进程仍活着, 只是 health 未 ready — 合法加载期, 唔报失败
            return
        if cur_state == "stopped":
            # 进程已消失: 过了短宽限才算真失败 (避免慢 spawn 误判)
            if time.monotonic() - self._pending_start_ts < _PENDING_GRACE_S:
                return
            # 真失败 (bad arg / 端口冲突 / 加载 abort) → 报 failed
            self._start_pending = False
            self._stop_pending_timer()
            self._last_state = None
            self._force_state = "failed"
            self._refresh_state()
            return
        # error / 其他 — 保持原状, 等 refresh

    def _stop_pending_timer(self) -> None:
        timer = getattr(self, "_pending_fail_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()

    def _on_stop_clicked(self) -> None:
        cb = getattr(self, "_on_stop_cb", None)
        if cb is not None:
            cb()
        else:
            print("[ServerControlSidebar] no stop callback registered")
        # stop 后清 pending-failure, 避免停完又触发 failed 显示
        self._start_pending = False
        self._force_state = None
        self._stop_pending_timer()

    def mark_failed(self) -> None:
        """外部 (MainWindow) 调用: 启动返回 ok 但 health 失败时立即 pill 切到 failed.

        Quinn T1-D: 比 3s timer 更早让用户见到错误, 无需等 _refresh_state 轮询.
        """
        self._last_state = None
        self._force_state = "failed"
        self._start_pending = False
        self._refresh_state()

    # ============================================================
    # Public API
    # ============================================================
    def on_start(self, callback) -> None:
        """注册启动点击 callback: callback()."""
        self._on_start_cb = callback

    def on_stop(self, callback) -> None:
        """注册停止点击 callback: callback()."""
        self._on_stop_cb = callback

    def refresh(self) -> None:
        """外部强制刷新 (例如点启动后想立即看 pill 变 loading)."""
        self._last_state = None  # 让 _refresh_state 重跑
        self._refresh_state()


# ============================================================
# Action button (实心 / 描边)
# ============================================================
class _SidebarActionButton(QWidget):
    """侧边栏内的简易按钮: icon + label 居中, 高度固定.

    Quinn 11:04: 图标用矢量 QPainter 画到 QPixmap, Qt setIcon + setText 自动基线对齐.
    """

    def __init__(self, text: str, icon_kind: str = "", style: str = "primary",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QPushButton
        self._btn = QPushButton(self)
        self._btn.setObjectName(f"SidebarAction{style.capitalize()}")
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        t.fixed_h(self._btn, 40, floor=32)
        self._btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_font = QFont()
        btn_font.setPointSize(t.FONT_SIZE["sm"])
        btn_font.setBold(True)
        self._btn.setFont(btn_font)

        # 图标颜色: primary 按钮白文, outline 按钮主色文字
        icon_color = (
            t.color('text_on_primary') if style == "primary"
            else t.color('text_primary')
        )

        if style == "primary":
            self._btn.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {t.color('primary')};
                    color: {t.color('text_on_primary')};
                    border: none;
                    border-radius: {t.radius('md')}px;
                    padding: 0 {t.scaled(12)}px;
                }}
                QPushButton:hover {{
                    background-color: {t.color('primary_hover')};
                }}
                QPushButton:disabled {{
                    background-color: {t.color('surface_3')};
                    color: {t.color('text_muted')};
                }}
                """
            )
        else:  # outline
            self._btn.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: transparent;
                    color: {t.color('text_primary')};
                    border: 1px solid {t.color('border')};
                    border-radius: {t.radius('md')}px;
                    padding: 0 {t.scaled(12)}px;
                }}
                QPushButton:hover {{
                    background-color: {t.color('card_hover')};
                }}
                QPushButton:disabled {{
                    color: {t.color('text_muted')};
                    border-color: {t.color('border')};
                    background-color: transparent;
                }}
                """
            )

        # Quinn 11:04: 用 setIcon (QPixmap) + setText, Qt 内部统一 baseline 对齐
        if icon_kind:
            self._btn.setIcon(_make_icon(icon_kind, icon_color, px=14))
            self._btn.setIconSize(self._btn.iconSize())  # 默认大小由 Qt 决定
        self._btn.setText(text)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._btn)

    # delegate 属性访问, 让外层能直接 .clicked.connect / .setEnabled
    def __getattr__(self, name):
        return getattr(self._btn, name)