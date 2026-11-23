"""MainWindow - Sidebar + QStackedWidget (Console / Settings)

v2 layout (matches console_v2_mock.html V3):
- 3-col grid: sidebar (220) | engine (380) | hardware (1fr)
- MainWindow: Sidebar nav + Stack (Console/Settings)

v2.3 (Quinn 17:53): 侧边栏底部加 "方案" 区段, 替代原 console 启动控制卡.

Quinn 09:30 (第四轮): resize 性能优化
- resizeEvent 100ms 防抖 (拖动期间不每帧重设字体, 仅最后一次)
- scale 阈值 0.02 → 0.05 (减少不必要 rescale)
- _rescale_fonts 用 QTimer.singleShot 延迟, 避免阻塞 UI
"""
from PySide6.QtCore import Qt, QRect, QSettings, QSize, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from llama_console_v2 import theme as t
from llama_console_v2.pages.console import ConsolePage
from llama_console_v2.pages.dashboard import DashboardPage
from llama_console_v2.pages.player import PlayerPage
from llama_console_v2.pages.settings import SettingsPage
from llama_console_v2.pages.settings_dialog import SettingsDialog
from llama_console_v2.widgets.server_control import ServerControlSidebar
from llama_console_v2.backend import llama_cpp as backend_llama
from llama_console_v2.backend import frp as backend_frp  # 2026-08-31 (B1): GUI 启停同步启停 frp


class SidebarButton(QPushButton):
    """Sidebar nav button with active state."""

    def __init__(self, text: str, icon_char: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("SidebarButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        t.fixed_h(self, t.FORM["sidebar_item_height"])
        font = QFont()
        font.setPointSize(t.FONT_SIZE["sm"])
        self.setFont(font)
        if icon_char:
            self.setText(f"  {icon_char}   {text}")
        self._apply_style(False)

    def _apply_style(self, active: bool) -> None:
        if active:
            self.setStyleSheet(
                f"""
                QPushButton#SidebarButton {{
                    background-color: rgba(255, 255, 255, 0.10);
                    color: {t.color('primary')};
                    border: none;
                    border-left: {t.scaled(3)}px solid {t.color('primary')};
                    text-align: left;
                    padding-left: {t.scaled(20)}px;
                    font-weight: 500;
                }}
                """
            )
        else:
            self.setStyleSheet(
                f"""
                QPushButton#SidebarButton {{
                    background-color: transparent;
                    color: {t.color('text_secondary')};
                    border: none;
                    border-left: {t.scaled(3)}px solid transparent;
                    text-align: left;
                    padding-left: {t.scaled(23)}px;
                }}
                QPushButton#SidebarButton:hover {{
                    background-color: {t.color('card_hover')};
                    color: {t.color('text_primary')};
                }}
                """
            )

    def set_active(self, active: bool) -> None:
        self.setChecked(active)
        self._apply_style(active)


class _CompactFrame(QWidget):
    """紧凑模式主体: 自绘圆角背景 + 状态色 2px 边框 (光晕由 drop shadow 提供)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._border = t.color("danger")
        self.setStyleSheet("background: transparent; border: none;")

    def set_border_color(self, color_hex: str) -> None:
        if color_hex == self._border:
            return
        self._border = color_hex
        effect = self.graphicsEffect()
        if isinstance(effect, QGraphicsDropShadowEffect):
            effect.setColor(QColor(color_hex))
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = t.scaled(t.COMPACT["frame_margin"])
        rect = self.rect().adjusted(m, m, -m, -m)
        radius = t.scaled(t.COMPACT["radius"])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(t.color("card"))))
        p.drawRoundedRect(rect, radius, radius)
        pen = QPen(QColor(self._border), t.scaled(t.COMPACT["border_width"], floor=1))
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)
        p.end()


class MainWindow(QMainWindow):
    """Main window: sidebar + stacked Console/Settings pages."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LlamaDeck")
        self._normal_flags = self.windowFlags()

        # 窗口大小：双模式均固定不可拖拽调节 (R12 18:10 用户要求)
        #   - 紧凑模式: set_compact(True) 固定为 t.scaled(980 x 280)
        #   - 展开模式: set_compact(False) 固定为 t.recommended_window_size()
        # 下面基线按主屏「可用区」(扣除任务栏, 已含 DPI 缩放) 比例算并 clamp 到
        # [1200x760, 1440x900], 仅用于初始化字体 scale; 实际尺寸锁定在 set_compact().
        #   - 内容完整显示不滚动 (tools/measure_window.py 验证该区间内均 NO-SCROLL)
        #   - 字体 scale 受宽度限制, 卡片清晰; 固定尺寸禁用拖拽调节/最大化.
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
        else:
            avail = QRect(0, 0, 2560, 1440)
        avail_w, avail_h = avail.width(), avail.height()
        win_w = int(min(avail_w * 0.50, 1440))
        win_h = int(min(avail_h * 0.62, 900))
        win_w = max(win_w, 1200)
        win_h = max(win_h, 760)
        # 固定窗口字体 scale: 在屏幕比例算出的基础上再乘 0.93 收紧一点点.
        # 原因: offscreen 下窗口尺寸=client 高度, 但 Windows 真机的标题栏/边框会额外
        # 占用 client 高度 (~30-40px), 导致同尺寸下真机内容比模拟多一截而触发滚动条.
        # 乘 0.93 让内容整体缩小约 7%, 抵消该占用并留出垂直余量, 真机不再出现滚动条.
        # 记住展开 scale 的基线, set_compact(False) 用同一算法还原
        self._expanded_scale_base = (win_w, win_h)
        t.set_font_scale(t.compute_font_scale(win_w, win_h) * 0.93)
        self.resize(win_w, win_h)
        self.setStyleSheet(f"background-color: {t.color('bg')};")

        # Central widget
        central = QWidget()
        central.setObjectName("Central")
        central.setStyleSheet("background: transparent; border: none;")
        self.setCentralWidget(central)

        # Quinn T1-D: 中央 widget 改为 VBox — 顶部预留 error banner,
        # 下面才是原来的 sidebar + stack HBox. banner 平时 hide(), 出错时 show().
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # --- Error banner (顶部, 默认隐藏) ---
        self._error_banner = self._build_error_banner()
        self._error_banner.hide()
        root_layout.addWidget(self._error_banner)

        # Body container: 包住原来的 sidebar + stack HBox, 保留原 margin
        self._body = QWidget()
        self._body.setObjectName("CentralBody")
        self._body.setStyleSheet("background: transparent; border: none;")
        root_layout.addWidget(self._body, 1)

        # Root layout = sidebar + stacked
        layout = QHBoxLayout(self._body)
        self._body_layout = layout
        layout.setContentsMargins(
            t.scaled(t.space("6")), t.scaled(t.space("6")),
            t.scaled(t.space("6")), t.scaled(t.space("6"))
        )
        layout.setSpacing(t.scaled(t.space("4")))

        # --- Sidebar ---
        sidebar = self._build_sidebar()
        layout.addWidget(sidebar)

        # --- Stacked content (Console | Settings | Player) ---
        self._stack = QStackedWidget()
        self._stack.setObjectName("Content")
        self._stack.setStyleSheet("background: transparent; border: none;")

        self._console_page = ConsolePage()
        self._settings_page = SettingsPage()
        self._player_page = PlayerPage()
        # v2 fix (Quinn 14:15): back_clicked signal removed from SettingsPage
        # Navigation controlled by sidebar, no back button

        self._stack.addWidget(self._console_page)  # index 0
        self._stack.addWidget(self._settings_page)  # index 1
        self._stack.addWidget(self._player_page)    # index 2
        self._body_layout.addWidget(self._stack, 1)

        # --- Compact frameless frame (与 body 互斥, stack 在两模式间移动) ---
        self._compact_frame = _CompactFrame()
        shadow = QGraphicsDropShadowEffect(self._compact_frame)
        shadow.setBlurRadius(t.scaled(t.COMPACT["shadow_blur"]))
        shadow.setColor(QColor(t.color("danger")))
        shadow.setOffset(0, 0)
        self._compact_frame.setGraphicsEffect(shadow)
        self._frame_layout = QVBoxLayout(self._compact_frame)
        inset = t.scaled(t.COMPACT["frame_margin"]) + t.scaled(t.COMPACT["border_width"], floor=1)
        self._frame_layout.setContentsMargins(inset, inset, inset, inset)
        self._frame_layout.setSpacing(0)
        root_layout.addWidget(self._compact_frame, 1)

        # 展开模式: 单页 Dashboard (旧 sidebar + stack 保留作状态机回调, 不再显示)
        self._dashboard_page = DashboardPage()
        root_layout.addWidget(self._dashboard_page, 1)
        self._dashboard_page.hide()

        # 播放键 / Space 与 sidebar 共用同一组 start/stop 回调
        self._player_page.startRequested.connect(self._on_sidebar_start)
        self._player_page.stopRequested.connect(self._on_sidebar_stop)
        self._player_page.compactRequested.connect(self.set_compact)
        self._player_page.closeRequested.connect(self.close)
        self._player_page.borderColorChanged.connect(self._compact_frame.set_border_color)
        self._dashboard_page.compactRequested.connect(self.set_compact)
        self._dashboard_page.closeRequested.connect(self.close)
        self._dashboard_page.settingsRequested.connect(self._open_settings)
        self._dashboard_page.startRequested.connect(self._on_sidebar_start)
        self._dashboard_page.stopRequested.connect(self._on_sidebar_stop)
        esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        esc_shortcut.activated.connect(lambda: self.set_compact(True) if self._compact else None)

        # Default to player (LlamaDeck 主页); 随后按 QSettings 进入上次模式
        self._switch_to(2)
        self._settings = QSettings("Quinn", "LlamaDeck")
        self._compact: bool | None = None
        self.set_compact(bool(self._settings.value("compact_mode", True, type=bool)))

    def _build_sidebar(self) -> QWidget:
        """Sidebar: 与窗口同高的独立侧边栏页面元素.

        Quinn 09:00 反馈 (三轮):
        - 上一轮去掉了 border/radius/box-shadow 但底色仍是 card 色 → 看起来还是卡片
        - 本轮: 改用 page bg 色, 与卡片区隔; 加 1px 右边框作为视觉边界
        - 高度撑满: SizePolicy(Fixed, Expanding), 在 HBox 中垂直撑满
        - 方案区段删除, 改为「启动/停止」简洁按钮 (Quinn 09:00 三轮反馈)
        """
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        # Quinn 09:00 三轮: 删方案后宽度恢复 260→220, 避免右侧大面积空白
        t.fixed_w(sidebar, 220)
        sidebar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        sidebar.setStyleSheet(
            f"""
            QFrame#Sidebar {{
                background-color: {t.color('bg')};
                border: none;
                border-right: 1px solid {t.color('border')};
            }}
            """
        )

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, t.scaled(t.space("5")), 0, t.scaled(t.space("4")))
        layout.setSpacing(0)

        # Logo / Title
        title = QLabel("llama-server")
        font_t = QFont()
        font_t.setPointSize(t.FONT_SIZE["lg"])
        font_t.setBold(True)
        title.setFont(font_t)
        title.setStyleSheet(
            f"color: {t.color('primary')}; background: transparent; border: none; padding-left: {t.scaled(20)}px;"
        )
        layout.addWidget(title)

        layout.addSpacing(t.scaled(t.space("7")))

        # Nav items (Player / Console / Settings) — 按钮顺序即 stack index 顺序
        self._nav_buttons: list[SidebarButton] = []
        self._nav_indices: list[int] = []
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        nav_items = [("播放器", "▶", 2), ("控制台", "📈", 0), ("设置", "⚙", 1)]
        for label, icon, idx in nav_items:
            btn = SidebarButton(label, icon_char=icon)
            btn.clicked.connect(lambda _checked, i=idx: self._switch_to(i))
            self._nav_group.addButton(btn, idx)
            self._nav_buttons.append(btn)
            self._nav_indices.append(idx)
            layout.addWidget(btn)

        # Quinn 09:00 三轮: Server 控制 (启动/停止) 区段代替原方案区段, 无分隔线无标题
        self._server_ctrl = ServerControlSidebar()
        self._server_ctrl.on_start(self._on_sidebar_start)
        self._server_ctrl.on_stop(self._on_sidebar_stop)
        layout.addWidget(self._server_ctrl, 1)  # stretch=1 让 nav 在顶, ctrl 在中, footer 在底

        # Footer (Quinn 09:00 三轮: 删版本号, 只保留空 spacer, 与 ServerCtrl 一致)
        layout.addSpacing(t.scaled(t.space("4")))

        return sidebar

    def _on_sidebar_start(self) -> None:
        """侧边栏「启动」按钮: 读 JSON 配置 dict 作为 extra_args 启动.

        Quinn 11:35: 启动参数改 JSON 格式后, 用 extra_args_dict 走新路径,
        后端 start() 自动展平 dict 为 ["--flag", "value", ...].

        Quinn T1-D: 当 backend start() return ok=True 但 health_reachable=False
        (即 launcher stub 起咗但 llama-server 真系死咩), 弹出顶部 error banner
        告知用户检查 log. 之前呢种 case 完全静默, 状态 pill 永远「未启动」,
        用户唔知道咩事.

        2026-08-31 (B1): start() 成功 (ok=True) 后自动调 backend_frp.start_frpc()
        — 同步起 frpc tunnel. 幂等: frpc 已经在跑 → no-op. 错误全捕获
        (frp.start_frpc 唔 throw), 所以 frp 失败都唔会 crash GUI.
        """
        try:
            extra_args_dict = backend_llama.load_cmdline_args_dict()
        except Exception:
            extra_args_dict = None
        # 先停旧实例避免端口冲突
        backend_llama.stop()
        result = backend_llama.start(extra_args_dict=extra_args_dict)
        ok = result.get("ok", False)
        err = result.get("error")
        health_reachable = result.get("health_reachable", True)
        log_path = result.get("log_path") or "unknown"
        if not ok:
            # 后端明确报错 — 显示 banner 后唔继续 refresh (后台其实已停)
            print(f"[main_window] start failed: {err}")
            self._show_error_banner(log_path, err or "start returned ok=False")
            # 通知 sidebar pill 切到 failed (override)
            self._server_ctrl.refresh()
            return
        # B1: llama-server start ok → 同步起 frpc (幂等, 安全)
        frp_res = backend_frp.start_frpc()
        if frp_res.get("ok"):
            if frp_res.get("already_running"):
                print(f"[main_window] FRP 已在运行 (pid {frp_res.get('pid')})")
            else:
                print(f"[main_window] FRP 已启动 (pid {frp_res.get('pid')})")
        else:
            # frp 失败唔影响 llama-server 启动结果, 只 log 提醒
            print(f"[main_window] FRP 启动失败: {frp_res.get('error')}")
        if not health_reachable:
            # T1-B 新语义: launcher 起咗但 health endpoint 3s 内唔 ready
            # → 用户必须睇 log 知咩事
            print(f"[main_window] start ok but health unreachable, log: {log_path}")
            self._show_error_banner(log_path, err or "health endpoint not reachable in 3s")
            self._server_ctrl.mark_failed()  # 立即 pill 切到「启动失败」
            self._player_page.mark_failed()  # 播放器边框/状态点同步失败态
        # 切到控制台 + 多次刷新 (启动 → loading → running); 紧凑模式保持播放器页
        if not self._compact:
            self._switch_to(0)
        self._server_ctrl.refresh()  # 立即更新 pill 到 loading
        QTimer.singleShot(0, self._console_page.refresh)
        QTimer.singleShot(1500, self._console_page.refresh)
        QTimer.singleShot(4000, self._console_page.refresh)
        QTimer.singleShot(7000, self._console_page.refresh)

    def _on_sidebar_stop(self) -> None:
        """侧边栏「停止」按钮.

        2026-08-31 (B1): stop() llama-server 之后自动调 backend_frp.stop_frpc()
        — 同步收 frpc tunnel. 幂等: 冇 frpc 喺跑 → ok=True, killed=[].

        2026-09-01 (Franky): 修复「停唔到非自己 spawn 嘅 llama」—
        - 检查 backend_llama.stop() 返回值 (elevated/residual), 唔再静默.
        - 若 stop 失败 / 仍有 llama 残留 (schtask 起嘅 elevated 实例),
          弹错误 banner 明确告知用户, 并提示需要 UAC 授权.
        - elevated=True 时提示「已通过管理员授权停止」.
        """
        try:
            stop_res = backend_llama.stop()
        except Exception as e:
            print(f"[main_window] stop exception: {e}")
            stop_res = {"ok": False, "error": str(e)}
        stop_ok = stop_res.get("ok", True)
        residual = stop_res.get("residual", False)
        elevated = stop_res.get("elevated", False)
        stop_err = stop_res.get("error") or ""
        # 停 llama-server 失败 / 仍有残留 → 明确提示 (唔再静默)
        if not stop_ok or residual:
            msg = stop_err or "无法停止 llama-server"
            if elevated:
                msg = "已发起管理员授权停止, 但 llama-server 仍未能终止, 请检查"
            elif residual:
                msg = ("llama-server 由计划任务以管理员权限启动, 普通权限无法停止; "
                       "请在系统弹窗中允许管理员授权")
            print(f"[main_window] stop issue: {msg}")
            self._show_error_banner("", msg)
        elif elevated:
            # 通过 UAC 提升才停到 — 提示用户已用管理员权限
            print("[main_window] stop done via UAC elevation")
            self._show_error_banner("", "已通过管理员授权停止 llama-server")
        # B1: 同步停 frpc
        frp_res = backend_frp.stop_frpc()
        if frp_res.get("ok"):
            killed = frp_res.get("killed") or []
            if killed:
                print(f"[main_window] FRP 已停止 (killed pids: {killed})")
            else:
                print("[main_window] FRP 未运行, 无需停止")
        else:
            print(f"[main_window] FRP 停止失败: {frp_res.get('error')}")
        self._server_ctrl.refresh()  # 立即更新 pill 到 stopped
        QTimer.singleShot(0, self._console_page.refresh)
        QTimer.singleShot(1500, self._console_page.refresh)
        QTimer.singleShot(3500, self._console_page.refresh)

    # ============================================================
    # Quinn T1-D: Error banner (顶部失败提示)
    # ============================================================
    def _build_error_banner(self) -> QFrame:
        """构建顶部红色错误 banner (QFrame). 平时 hide(), 出错才 show().

        Layout: [⚠] [消息]  [stretch]  [log path]  [✕]
        Hover 整个 banner 显示完整 log path tooltip.
        """
        banner = QFrame()
        banner.setObjectName("ErrorBanner")
        banner.setFrameShape(QFrame.Shape.NoFrame)
        banner.setStyleSheet(
            f"""
            QFrame#ErrorBanner {{
                background-color: {t.color('danger')};
                border: none;
                border-bottom: 1px solid rgba(0, 0, 0, 0.25);
            }}
            QFrame#ErrorBanner QLabel {{
                color: #ffffff;
                background: transparent;
                border: none;
            }}
            QFrame#ErrorBanner QPushButton {{
                background: transparent;
                color: #ffffff;
                border: none;
                padding: 0 {t.scaled(6)}px;
                font-weight: 700;
                font-size: {t.FONT_SIZE["md"]}pt;
            }}
            QFrame#ErrorBanner QPushButton:hover {{
                background-color: rgba(0, 0, 0, 0.20);
                border-radius: {t.radius("sm")}px;
            }}
            """
        )
        t.fixed_h(banner, 36, floor=32)

        lay = QHBoxLayout(banner)
        lay.setContentsMargins(
            t.scaled(t.space("4")), 0,
            t.scaled(t.space("3")), 0,
        )
        lay.setSpacing(t.scaled(t.space("3")))

        icon = QLabel("\u26a0")  # ⚠
        icon_font = QFont()
        icon_font.setPointSize(t.FONT_SIZE["md"])
        icon_font.setBold(True)
        icon.setFont(icon_font)
        lay.addWidget(icon)

        self._error_banner_text = QLabel("llama-server 启动失败")
        text_font = QFont()
        text_font.setPointSize(t.FONT_SIZE["sm"])
        text_font.setBold(True)
        self._error_banner_text.setFont(text_font)
        lay.addWidget(self._error_banner_text)

        lay.addStretch(1)

        self._error_banner_log = QLabel("")
        log_font = QFont()
        log_font.setPointSize(t.FONT_SIZE["xs"])
        self._error_banner_log.setFont(log_font)
        # log path 允许多行 + ellipsis (过窄时省略中间)
        self._error_banner_log.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._error_banner_log.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        # log label 本身都有独立 tooltip = 完整路径
        lay.addWidget(self._error_banner_log, 1)

        # banner 本身作为 hover target — install event filter 让整个 banner 都显示
        # log path tooltip. 较简单做法: 直接喺 _show_error_banner 里调
        # self._error_banner.setToolTip(log_path) (拎住个 QFrame), 已够.

        close_btn = QPushButton("\u2715")  # ✕
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setFixedSize(t.scaled(24), t.scaled(24))
        close_btn.setToolTip("关闭")
        close_btn.clicked.connect(self._hide_error_banner)
        lay.addWidget(close_btn)

        return banner

    def _show_error_banner(self, log_path: str, error_msg: str) -> None:
        """顶部 banner 显示启动失败信息 + log path. Idempotent: 重複调冇问题.

        Quinn T1-D: 配合 backend return dict 新 key `health_reachable=False` 调用.
        """
        log_path = log_path or "unknown"
        # banner 主文本拼上 error_msg (如果有)
        if error_msg and error_msg != "unknown":
            self._error_banner_text.setText(
                f"llama-server 启动失败: {error_msg}"
            )
        else:
            self._error_banner_text.setText("llama-server 启动失败, 请检查 log")
        # log path label: 仅显示文件名 (太长会占满), hover 完整路径
        short = log_path
        if len(short) > 60:
            # 留前 30 + … + 后 27
            short = short[:30] + "…" + short[-27:]
        self._error_banner_log.setText(f"log: {short}")
        # tooltip: 整条 banner 都看得见完整路径
        self._error_banner_log.setToolTip(log_path)
        self._error_banner_text.setToolTip(log_path)
        self._error_banner.setToolTip(log_path)
        self._error_banner_log.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._error_banner.show()

    def _hide_error_banner(self) -> None:
        self._error_banner.hide()

    def _switch_to(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        for idx, btn in zip(self._nav_indices, self._nav_buttons):
            btn.set_active(idx == index)
        # Refresh when switching to console
        if index == 0:
            self._console_page.refresh()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self)
        dlg.exec()

    def set_compact(self, compact: bool) -> None:
        """紧凑 frameless 播放器 ↔ 展开单页 Dashboard."""
        if self._compact == compact:
            return
        was_visible = self.isVisible()
        self._compact = compact
        self._settings.setValue("compact_mode", compact)
        if compact:
            # compact 用固定 0.80 缩放, 免得大屏展开的 scale 挤爆 980×300 布局
            t.set_font_scale(t.COMPACT["font_scale"])
            t.rescale_all_geometries()
            self._compact_frame.set_border_color(self._player_page.border_color())
            if self._stack.parent() is not self._compact_frame:
                self._body_layout.removeWidget(self._stack)
                self._frame_layout.addWidget(self._stack, 1)
            self._dashboard_page.hide()
            self._body.hide()
            self._error_banner.hide()
            self._compact_frame.show()
            self._stack.setCurrentIndex(2)
            self.setWindowFlags(self._normal_flags | Qt.WindowType.FramelessWindowHint)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setStyleSheet("background: transparent;")
            self.setFixedSize(t.scaled(t.COMPACT["width"]), t.scaled(t.COMPACT["height"]))
        else:
            # Option A: 展开显示单页 Dashboard; sidebar + stack 唔再显示
            self._compact_frame.hide()
            self._body.hide()
            self._dashboard_page.show()
            self.setWindowFlags(self._normal_flags)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
            self.setStyleSheet(f"background-color: {t.color('bg')};")
            self.setMinimumSize(QSize(0, 0))
            self.setMaximumSize(QSize(16_777_215, 16_777_215))
            ew, eh = self._expanded_scale_base
            t.set_font_scale(t.compute_font_scale(ew, eh) * 0.93)  # 同 __init__ 算法还原
            t.rescale_all_geometries()
            w, h = t.recommended_window_size()
            self.resize(w, h)
            self.setFixedSize(w, h)  # R12: 展开模式同样禁用拖拽调节
        self._player_page.set_compact_mode(compact)
        if was_visible:
            self.show()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._rescale_ready = True

    def resizeEvent(self, event) -> None:
        """窗口尺寸变化时, 防抖重算并应用字体 + 几何缩放。

        Quinn 09:30 (第四轮): 原实现每帧 (拖动期间 ~60fps) 遍历所有 widget 重设字号
        + 调 _force_relayout, 极大卡顿. 改为:
        1) 100ms 防抖 — 拖动期间不重算
        2) scale 阈值 0.05 — 缩放变化 < 5% 不触发 (减少反复微小调整)
        3) rescale 用 QTimer.singleShot, 不阻塞 paint
        """
        super().resizeEvent(event)
        # 初始化 resize 尚未 show() 时跳过, 保留 app.py 设定并经 0.93 收紧的字体缩放
        if not getattr(self, "_rescale_ready", False):
            return
        # R12 (18:10): 固定窗口模式 — 尺寸锁定 (min==max), 不会因用户拖拽变化,
        #   跳过字体重算, 避免异常 geometry (如 offscreen 初始尺寸) 误触发缩放导致内容溢出
        if self.minimumWidth() == self.maximumWidth() and \
                self.minimumHeight() == self.maximumHeight():
            return
        # 每次 resize 都启动/重置防抖 timer
        if not hasattr(self, "_resize_timer"):
            self._resize_timer = QTimer(self)
            self._resize_timer.setSingleShot(True)
            self._resize_timer.setInterval(150)  # 150ms 节流
            self._resize_timer.timeout.connect(self._apply_rescale)
        self._resize_timer.start()

    def _apply_rescale(self) -> None:
        """防抖后真正执行: 缩放 + 重算 + 重布局."""
        new_scale = t.compute_font_scale(self.width(), self.height())
        old_scale = t.get_font_scale()
        if abs(new_scale - old_scale) < 0.05:
            return  # Quinn 09:30: 阈值 0.02 → 0.05, 减少微小 resize 反复触发
        ratio = new_scale / old_scale
        t.set_font_scale(new_scale)
        # 1) 重算并应用所有已注册 widget 的几何（min/max/fixed height/width）
        t.rescale_all_geometries()
        # 2) 重算并应用所有显式设置了字号的字体（兼容已 setFont 的 widget）
        self._rescale_fonts(self, ratio)
        # 3) 触发子页面重新布局
        if hasattr(self, "_console_page") and self._console_page is not None:
            self._console_page._force_relayout()

    @staticmethod
    def _rescale_fonts(widget, ratio: float) -> None:
        """按比例 ratio 重设所有显式设置了字号的自绘控件字体。

        Quinn 09:30: 用 iter 替代 list + 拼接, 减少对象创建.
        """
        for w in (widget, *widget.findChildren(QWidget)):
            f = w.font()
            ps = f.pointSize()
            if ps > 0:
                f.setPointSize(max(6, int(round(ps * ratio))))
                w.setFont(f)
