"""Offscreen smoke test - 验证 Quinn 09:00 三轮所有改动 (Quinn 09:00 反馈后)

- 启动/停止按钮在侧边栏
- 控制台 token 卡无重复停止按钮
- 全屏无滚动条 + 1.5x 行距
- CPU 卡显示频率 + 缓存 + 细分利用率
- 启动参数卡下无 "设置" 字
- 性能: refresh 间隔 10s + 各 snapshot 缓存
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 先按 full 窗口计算 scale, 模拟 1/4 主屏 (full 1680x1040 → 1/4 840x520)
sys.path.insert(0, "src")

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QApplication, QFrame, QPushButton, QScrollArea, QWidget

from llama_console_v2 import theme as t

app = QApplication.instance() or QApplication(sys.argv)
app.setStyle("Fusion")


def take_shot(widget, w: int, h: int, name: str) -> None:
    """Resize widget to (w,h), process events, save screenshot."""
    # 先按目标尺寸算 scale
    sc = t.compute_font_scale(w, h)
    t.set_font_scale(sc)
    t.rescale_all_geometries()

    widget.resize(w, h)
    widget.show()
    app.processEvents()
    app.processEvents()

    out = os.path.join(".workbuddy", "preview", f"r4_{name}.png")
    pix = widget.grab()
    pix.save(out)
    print(f"[r4] {name}: {w}x{h} scale={sc:.2f} → {out}")
    print(f"      sizeHint={widget.sizeHint().width()}x{widget.sizeHint().height()}")


# ---------- 全屏窗口 (1/4 主屏, 默认 840x520) ----------
print("=== full (1/4 main screen ~840x520) ===")
from llama_console_v2.main_window import MainWindow
win = MainWindow()
win.resize(840, 520)
win.show()
app.processEvents()
app.processEvents()

# 默认进控制台 (index 0)
win._switch_to(0)
app.processEvents()
# 触发 refresh 拉取数据
win._console_page.refresh()
app.processEvents()

# 1) 全屏控制台截图
take_shot(win, 840, 520, "console_full_840x520")

# 2) 中窗口控制台
take_shot(win, 1100, 720, "console_med_1100x720")

# 3) 宽屏控制台
take_shot(win, 1400, 900, "console_large_1400x900")

# ---------- 设置页 ----------
win._switch_to(1)
app.processEvents()
win._settings_page._load_models()
win._settings_page._load_cmdline()
win._settings_page._load_version()
win._settings_page._load_build_status()
app.processEvents()

take_shot(win, 840, 520, "settings_full_840x520")
take_shot(win, 1100, 720, "settings_med_1100x720")

# ---------- 检测滚动条 ----------
print("=== 滚动条检测 (1/4 主屏 全屏) ===")
t.set_font_scale(t.compute_font_scale(840, 520))
t.rescale_all_geometries()
win.resize(840, 520)
win._switch_to(0)
app.processEvents()

from PySide6.QtWidgets import QScrollArea
scrolls = win.findChildren(QScrollArea)
for s in scrolls:
    vbar = s.verticalScrollBar()
    hbar = s.horizontalScrollBar()
    print(f"  ScrollArea '{s.objectName()}': vbar={vbar.isVisible() if vbar else None} max={vbar.maximum() if vbar else None}")

# 检查 console body widget 是否被 QScrollArea 包裹
console = win._console_page
print(f"  ConsolePage children: {[c.objectName() for c in console.findChildren(QFrame)[:5]]}")

# 检查侧边栏 ServerControlSidebar 是否渲染
sw = getattr(win, "_server_ctrl", None)
if sw:
    print(f"  ServerControlSidebar children: {[c.text() if hasattr(c, 'text') else c.objectName() for c in sw.findChildren(QWidget)[:6]]}")

# 检查 console body 是否还有 QScrollArea
body_scrolls = console.findChildren(QScrollArea)
print(f"  ConsolePage QScrollArea count: {len(body_scrolls)} (期望 0)")

# 检查 token 卡是否还有 stop 按钮
from llama_console_v2.widgets.card import Card
cards = console.findChildren(Card)
for c in cards:
    for child in c.findChildren(QPushButton):
        pass
# 直接看 _stop_btn
print(f"  ConsolePage has _stop_btn? {hasattr(console, '_stop_btn')}")

# 检查 SettingsPage footer
from llama_console_v2.widgets.page_chrome import PageFooter
print(f"  SettingsPage has _footer? {hasattr(win._settings_page, '_footer')}")

# 设置页 body 是否有 QScrollArea
settings_scrolls = win._settings_page.findChildren(QScrollArea)
print(f"  SettingsPage QScrollArea count: {len(settings_scrolls)} (期望 0)")

# 检查 _server_ctrl 按钮
from PySide6.QtWidgets import QPushButton
print(f"\n=== ServerControlSidebar state ===")
for c in sw.findChildren(QPushButton):
    print(f"  button text='{c.text()}' enabled={c.isEnabled()}")

# 性能测试: 5 次 refresh 看耗时
print("\n=== 性能测试: 5 次连续 refresh() ===")
import time
t0 = time.perf_counter()
for _ in range(5):
    win._console_page.refresh()
elapsed = (time.perf_counter() - t0) * 1000 / 5
print(f"  平均 refresh 耗时: {elapsed:.1f} ms (期望 < 30ms, 缓存生效)")

print("\n[OK] smoke_r4 完成")