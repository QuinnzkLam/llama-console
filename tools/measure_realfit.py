"""R13.1: 模拟真机 (窗口外尺寸固定, client = 外尺寸 - 标题栏/边框 ~40px) 是否滚动.

字体 scale 用代码实际算法 compute(w, winh) * 0.93; 渲染时把窗口高度设为 client 高度
(offscreen 无标题栏, resize 值即 client 值), 读取 QScrollArea vScroll.max.
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
win.setMinimumSize(0, 0)
win.setMaximumSize(16777215, 16777215)
win.show()
app.processEvents()

# (窗口外宽, 窗口外高, 标题栏+边框占用)
cases = [
    (1280, 862, 40),   # 2560x1440 / 100% 缩放
    (1440, 900, 40),
    (1707, 927, 40),   # 2560x1440 / 150% 缩放逻辑屏
    (1200, 760, 40),
    (1366, 768, 40),
    (1536, 864, 40),   # 常见 1920x1080 / 125% 缩放
    (1280, 790, 40),
]

all_ok = True
for (w, winh, dec) in cases:
    client_h = winh - dec
    scale = t.compute_font_scale(w, winh) * 0.93
    t.set_font_scale(scale)
    t.rescale_all_geometries()
    win.resize(w, client_h)
    app.processEvents()
    sas = win._console_page.findChildren(QScrollArea)
    vmax = max((sa.verticalScrollBar().maximum() for sa in sas), default=0)
    ok = vmax == 0
    all_ok = all_ok and ok
    print(f"win {w}x{winh} client={client_h} scale={scale:.3f} vmax={vmax:4d} "
          f"-> {'NO-SCROLL' if ok else 'SCROLL(+%d)' % vmax}")

print(f"\nRESULT: {'PASS' if all_ok else 'FAIL'}")
