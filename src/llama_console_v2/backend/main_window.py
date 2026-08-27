"""MainWindow - Sidebar + QStackedWidget (Console / Settings)

v2 layout (matches console_v2_mock.html V3):
- 3-col grid: sidebar (220) | engine (380) | hardware (1fr)
- MainWindow: Sidebar nav + Stack (Console/Settings)
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import theme as t
from .pages.console import ConsolePage
from .pages.settings import SettingsPage


class SidebarButton(QPushButton):
    """Sidebar nav button with active state."""

    def __init__(self, text: str, icon_char: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("SidebarButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        self.setFixedHeight(t.FORM["sidebar_item_height"])
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
                    border-left: 3px solid {t.color('primary')};
                    text-align: left;
                    padding-left: 20px;
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
                    border-left: 3px solid transparent;
                    text-align: left;
                    padding-left: 23px;
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
        self.resize(t.FORM["width"], t.FORM["height"])
        self.setMinimumSize(t.FORM.get("min_window_width", 1280), t.FORM.get("min_window_height", 760))
        self.setStyleSheet(f"background-color: {t.color('bg')};")

        # Central widget
        central = QWidget()
        central.setObjectName("Central")
        central.setStyleSheet("background: transparent; border: none;")
        self.setCentralWidget(central)

        # Root layout = sidebar + stacked
        layout = QHBoxLayout(central)
        layout.setContentsMargins(t.space("6"), t.space("6"), t.space("6"), t.space("6"))
        layout.setSpacing(t.space("4"))

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
        """Sidebar: 220 wide, fixed width, rounded card."""
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(t.FORM["sidebar_width"])
        sidebar.setStyleSheet(
            f"""
            QFrame#Sidebar {{
                background-color: {t.color('card')};
                border: 1px solid {t.color('border')};
                border-radius: {t.radius('xl')}px;
            }}
            """
        )

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, t.space("5"), 0, t.space("4"))
        layout.setSpacing(0)

        # Logo / Title
        title = QLabel("llama-server")
        font_t = QFont()
        font_t.setPointSize(t.FONT_SIZE["lg"])
        font_t.setBold(True)
        title.setFont(font_t)
        title.setStyleSheet(
            f"color: {t.color('primary')}; background: transparent; border: none; padding-left: 20px;"
        )
        layout.addWidget(title)

        layout.addSpacing(t.space("7"))

        # Nav items (Console / Settings) - ASCII labels
        self._nav_buttons: list[SidebarButton] = []
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        # Quinn 14:30 feedback: sidebar hard Chinese, 唔用 ASCII fallback
        nav_items = [("控制台", "[C]"), ("设置", "[S]")]
        for i, (label, icon) in enumerate(nav_items):
            btn = SidebarButton(label, icon_char=icon)
            btn.clicked.connect(lambda _checked, idx=i: self._switch_to(idx))
            self._nav_group.addButton(btn, i)
            self._nav_buttons.append(btn)
            layout.addWidget(btn)

        layout.addStretch(1)

        # Footer
        footer = QLabel("v2.0.0")
        font_f = QFont()
        font_f.setPointSize(t.FONT_SIZE["xs"])
        footer.setFont(font_f)
        footer.setStyleSheet(
            f"color: {t.color('text_secondary')}; background: transparent; border: none; padding-left: 20px;"
        )
        layout.addWidget(footer)

        return sidebar

    def _switch_to(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_buttons):
            btn.set_active(i == index)
        # Refresh when switching to console
        if index == 0:
            self._console_page.refresh()
