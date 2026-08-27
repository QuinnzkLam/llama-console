"""Quinn 11:04 第六轮验证脚本 — 检查三个修复点的实际渲染结果.

1. CPU 频率换 GHz
2. GPU 数据采集 (nvidia-smi 解析 N/A 容错)
3. 按钮文字垂直对齐 (setIcon 矢量几何图 + setText)
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, "src")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from llama_console_v2 import theme as t

app = QApplication.instance() or QApplication(sys.argv)
app.setStyle("Fusion")


def shot(widget, w: int, h: int, name: str) -> str:
    """Resize, show, save PNG."""
    sc = t.compute_font_scale(w, h)
    t.set_font_scale(sc)
    t.rescale_all_geometries()
    widget.resize(w, h)
    widget.show()
    app.processEvents()
    app.processEvents()
    out = os.path.join(".workbuddy", "preview", f"r6_{name}.png")
    widget.grab().save(out)
    print(f"  saved: {out}  ({w}x{h} scale={sc:.2f})")
    return out


# ========== 1) 按钮对齐 — 单独截 SidebarActionButton ==========
print("=== 1) Sidebar 按钮对齐验证 ===")
from llama_console_v2.widgets.server_control import _SidebarActionButton

wrap = _SidebarActionButton(text="启动", icon_kind="play", style="primary")
wrap.resize(280, 50)
wrap.show()
app.processEvents()

# 单按钮截图
pix = wrap.grab()
pix.save(".workbuddy/preview/r6_btn_start.png")
print(f"  saved: r6_btn_start.png  (单独启动按钮)")

wrap2 = _SidebarActionButton(text="停止", icon_kind="stop", style="outline")
wrap2.resize(280, 50)
wrap2.show()
app.processEvents()
wrap2.grab().save(".workbuddy/preview/r6_btn_stop.png")
print(f"  saved: r6_btn_stop.png   (单独停止按钮)")

# 对比两个按钮文字 + 图标的纵向像素分布
# 验证: 同一 Y 坐标处的图标和文字都在按钮中央
print("\n  验证图标垂直中心 ≈ 文字垂直中心:")
import struct

def analyze_vertical(pix, name):
    """统计图片水平方向的非透明像素 Y 分布"""
    from PySide6.QtGui import QImage
    img = pix.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    # 对每行, 计算非透明像素数
    rows = []
    for y in range(h):
        count = 0
        for x in range(w):
            px = img.pixel(x, y)
            alpha = (px >> 24) & 0xff
            if alpha > 30:
                count += 1
        rows.append(count)
    # 找中心 (最大非透明行附近)
    if not any(rows):
        print(f"    {name}: 全透明?")
        return None
    mid = h // 2
    center_rows = [r for r in rows[mid-3:mid+4]]
    avg = sum(center_rows) / len(center_rows) if center_rows else 0
    print(f"    {name}: img {w}x{h}, 中央 6 行平均非透明像素={avg:.1f}")
    # 找内容上下边界
    nz = [(y, c) for y, c in enumerate(rows) if c > 0]
    if nz:
        y_min = nz[0][0]
        y_max = nz[-1][0]
        center_y = (y_min + y_max) // 2
        print(f"    内容 Y 范围: {y_min}..{y_max}, 实际中心={center_y}, 画布中心={mid}, 偏差={center_y - mid}")

analyze_vertical(pix, "start btn")
analyze_vertical(wrap2.grab(), "stop btn")

# ========== 2) 全窗口截图 (看 GPU 数据是否到位) ==========
print("\n=== 2) 全窗口控制台截图 ===")
from llama_console_v2.main_window import MainWindow

win = MainWindow()
win.resize(1400, 900)
win.show()
app.processEvents()
win._switch_to(0)  # 控制台页
app.processEvents()
win._console_page.refresh()
app.processEvents()

# 等后端线程 3s 后再次 refresh
from PySide6.QtCore import QTimer
QTimer.singleShot(3000, win._console_page.refresh)
import time
# 同步等 3.5s
end = time.monotonic() + 3.5
while time.monotonic() < end:
    app.processEvents()

# 再 refresh 一次拿到真实数据
win._console_page.refresh()
app.processEvents()
app.processEvents()

shot(win, 1400, 900, "console_1400x900")
shot(win, 1100, 720, "console_1100x720")
shot(win, 840, 520, "console_840x520")

# ========== 3) 打印实际 cpu freq 显示文本 ==========
print("\n=== 3) CPU 频率显示文本 ===")
cpu_text = win._console_page._cpu_cores_lbl.text()
print(f"  CPU info: {cpu_text!r}")
if "GHz" in cpu_text:
    print(f"  ✓ 已换 GHz 显示")
elif "MHz" in cpu_text:
    print(f"  ⚠ 仍是 MHz (可能在 fallback 路径)")

# ========== 4) 打印实际 GPU 数据 ==========
print("\n=== 4) GPU 数据采集 ===")
from llama_console_v2.backend import hardware as h
gpus = h._get_gpus()
print(f"  nvidia-smi 路径: {len(gpus)} 张卡")
for g in gpus:
    name = g['name']
    vram = g['vram_total_mb']
    temp = g['temp_c']
    vtemp = g['vram_temp_c']
    util = g['util_percent']
    print(f"    - {name}  VRAM={vram}MB  util={util}%  T_core={temp}°C  T_vram={vtemp}°C")

wmi = h._get_gpus_wmi()
print(f"  WMI 兜底路径: {len(wmi)} 张卡")
for g in wmi:
    print(f"    - {g['name']}  VRAM={g['vram_total_mb']}MB  drv={g['driver_version']}")

# 显示 UI 文本
g0 = win._console_page._gpu0_model_lbl.text()
g1 = win._console_page._gpu1_model_lbl.text()
print(f"\n  UI 显示:")
print(f"    GPU 0 标签: {g0!r}")
print(f"    GPU 1 标签: {g1!r}")

print("\n[OK] smoke_r6 完成")
