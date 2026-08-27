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
from PySide6.QtCore import Qt, QRect, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import theme as t
from .pages.console import ConsolePage
from .pages.settings import SettingsPage
from .widgets.server_control import ServerControlSidebar
from .backend import llama_cpp as backend_llama


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


class MainWindow(QMainWindow):
    """Main window: sidebar + stacked Console/Settings pages."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("llama-server")

        # 窗口大小：固定窗口模式 (R12 18:10 用户要求: 默认完整显示不滚动 + 不可拖拽调节)
        # 固定尺寸按主屏「可用区」(扣除任务栏, 已含 DPI 缩放) 的比例计算, 并 clamp 到经验
        # 安全区间 [1200x760, 1440x900], 保证:
        #   - 任意屏幕分辨率/系统缩放下都不超出屏幕 (如用户 2560x1440 不会因 DPI 放大而溢出)
        #   - 内容完整显示不滚动 (tools/measure_window.py 验证该区间内均 NO-SCROLL)
        #   - 字体 scale 受宽度限制, 卡片清晰; setFixedSize 锁定尺寸, 禁用拖拽调节/最大化.
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
        t.set_font_scale(t.compute_font_scale(win_w, win_h) * 0.93)
        self.resize(win_w, win_h)
        self.setFixedSize(win_w, win_h)
        self.setStyleSheet(f"background-color: {t.color('bg')};")

        # Central widget
        central = QWidget()
        central.setObjectName("Central")
        central.setStyleSheet("background: transparent; border: none;")
        self.setCentralWidget(central)

        # Root layout = sidebar + stacked
        layout = QHBoxLayout(central)
        layout.setContentsMargins(
            t.scaled(t.space("6")), t.scaled(t.space("6")),
            t.scaled(t.space("6")), t.scaled(t.space("6"))
        )
        layout.setSpacing(t.scaled(t.space("4")))

        # --- Sidebar ---
        sidebar = self._build_sidebar()
        layout.addWidget(sidebar)

        # --- Stacked content (Console | Settings) ---
        self._stack = QStackedWidget()
        self._stack.setObjectName("Content")
        self._stack.setStyleSheet("background: transparent; border: none;")

        self._console_page = ConsolePage()
        self._settings_page = SettingsPage()
        # v2 fix (Quinn 14:15): back_clicked signal removed from SettingsPage
        # Navigation controlled by sidebar, no back button

        self._stack.addWidget(self._console_page)  # index 0
        self._stack.addWidget(self._settings_page)  # index 1
        layout.addWidget(self._stack, 1)

        # Default to console
        self._switch_to(0)

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

        # Nav items (Console / Settings)
        self._nav_buttons: list[SidebarButton] = []
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        nav_items = [("控制台", "📈"), ("设置", "⚙")]
        for i, (label, icon) in enumerate(nav_items):
            btn = SidebarButton(label, icon_char=icon)
            btn.clicked.connect(lambda _checked, idx=i: self._switch_to(idx))
            self._nav_group.addButton(btn, i)
            self._nav_buttons.append(btn)
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
        if not ok:
            print(f"[main_window] start failed: {err}")
            return
        # 切到控制台 + 多次刷新 (启动 → loading → running)
        self._switch_to(0)
        self._server_ctrl.refresh()  # 立即更新 pill 到 loading
        QTimer.singleShot(0, self._console_page.refresh)
        QTimer.singleShot(1500, self._console_page.refresh)
        QTimer.singleShot(4000, self._console_page.refresh)
        QTimer.singleShot(7000, self._console_page.refresh)

    def _on_sidebar_stop(self) -> None:
        """侧边栏「停止」按钮."""
        backend_llama.stop()
        self._server_ctrl.refresh()  # 立即更新 pill 到 stopped
        QTimer.singleShot(0, self._console_page.refresh)
        QTimer.singleShot(1500, self._console_page.refresh)
        QTimer.singleShot(3500, self._console_page.refresh)

    def _switch_to(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_buttons):
            btn.set_active(i == index)
        # Refresh when switching to console
        if index == 0:
            self._console_page.refresh()

    def resizeEvent(self, event) -> None:
        """窗口尺寸变化时, 防抖重算并应用字体 + 几何缩放。

        Quinn 09:30 (第四轮): 原实现每帧 (拖动期间 ~60fps) 遍历所有 widget 重设字号
        + 调 _force_relayout, 极大卡顿. 改为:
        1) 100ms 防抖 — 拖动期间不重算
        2) scale 阈值 0.05 — 缩放变化 < 5% 不触发 (减少反复微小调整)
        3) rescale 用 QTimer.singleShot, 不阻塞 paint
        """
        super().resizeEvent(event)
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
