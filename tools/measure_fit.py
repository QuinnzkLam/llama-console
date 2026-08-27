"""R13.1: 测量固定窗口各候选尺寸下控制台页内容是否溢出 (offscreen 模拟).

解锁 setFixedSize, 手动设尺寸 + scale + relayout, 读取 QScrollArea vScroll.max.
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication, QScrollArea

sys.path.insert(0, "src")
import llama_console_v2.theme as t
from llama_console_v2.main_window import MainWindow

app = QApplication(sys.argv)
win = MainWindow()
# 解锁固定尺寸, 以便模拟任意窗口大小
win.setMinimumSize(0, 0)
win.setMaximumSize(16777215, 16777215)
win.show()
app.processEvents()

candidates = [
    (1280, 862),   # 2560x1440 / 100% 缩放, avail 扣任务栏后约此值
    (1280, 900),
    (1200, 760),   # offscreen fallback 当前值
    (1366, 768),
    (1440, 900),
    (1707, 927),   # 2560x1440 / 150% 缩放逻辑屏
    (1280, 790),   # 偏矮
]

for (w, h) in candidates:
    scale = t.compute_font_scale(w, h)
    t.set_font_scale(scale)
    t.rescale_all_geometries()
    win.resize(w, h)
    app.processEvents()
    page = win._console_page
    sas = page.findChildren(QScrollArea)
    vmax = max((sa.verticalScrollBar().maximum() for sa in sas), default=0)
    flag = "NO-SCROLL" if vmax == 0 else f"SCROLL(+{vmax})"
    print(f"{w}x{h}  scale={scale:.3f}  vmax={vmax:4d}  -> {flag}")
