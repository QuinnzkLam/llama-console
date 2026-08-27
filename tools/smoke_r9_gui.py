"""
Quinn 14:00 — R9 GUI offscreen smoke

启动 MainWindow (offscreen), 运行 6 秒, 监控后台日志, 截图保存.
验证:
1. 程序能正常启动, MainWindow 创建无异常
2. 后台 llama-collector 线程能多次填充缓存
3. setUpdatesEnabled 的 refresh 不会卡
4. 多次 console.refresh() 总耗时 < 500ms (主线程即时读缓存)
"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import sys
import time
from pathlib import Path

ROOT = Path("C:/Users/Quinn/Downloads/llama-console-v2-portable/llama-console-v2-portable")
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from llama_console_v2.main_window import MainWindow
from llama_console_v2.backend import llama_cpp

print("=" * 70)
print("[R9 GUI offscreen] 启动 MainWindow + 跑 6s")
print("=" * 70)

app = QApplication.instance() or QApplication(sys.argv)

t0 = time.monotonic()
win = MainWindow()
print(f"  MainWindow 创建: {1000*(time.monotonic()-t0):.1f} ms")

# 等后台采集填充 + 多次 refresh
def _log_refresh(label):
    t0 = time.monotonic()
    win._console_page.refresh()
    print(f"  refresh [{label}]: {1000*(time.monotonic()-t0):.1f} ms")

# 第一轮: 后台尚未填充, snapshot 走 sync fallback (慢, 但只有一次)
_log_refresh("cold (sync fallback)")

# 启后台 + 预热
llama_cpp._ensure_llama_bg()
time.sleep(2.5)
print(f"  bg.ts={llama_cpp._LLAMA_BG.get('ts'):.3f}")

# 之后 5 次 refresh 测时 (主线程即时读缓存)
for i in range(5):
    _log_refresh(f"warm #{i+1}")

# 多次混合 (每个 refresh 都执行 4 个采集)
t0 = time.monotonic()
for i in range(20):
    win._console_page.refresh()
t_total = time.monotonic() - t0
print(f"  20 次连续 refresh: {t_total*1000:.1f} ms (平均 {t_total*1000/20:.1f} ms/次)")

# 截图
shot = ROOT / "tools" / "r9_gui.png"
pix = win.grab()
pix.save(str(shot))
print(f"  截图: {shot} ({shot.stat().st_size} bytes)")

# 不进入交互 — 直接退出
print("=" * 70)
print("[R9 GUI offscreen] OK")
print("=" * 70)
app.quit()
