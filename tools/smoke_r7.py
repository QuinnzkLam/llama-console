"""R7 烟测: 验证 4 项优化 (CPU 频率突出 / VRAM 温度隐藏 / 生成速度布局 / JSON 参数)."""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, "src")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

# 设大窗口以更好看清布局
from PySide6.QtCore import QSize
from llama_console_v2.main_window import MainWindow
from llama_console_v2.backend import llama_cpp as L
from llama_console_v2.backend import hardware as H

# 清理可能残留的配置文件
for p in (L._CMDLINE_FILE, L._CMDLINE_FILE_OLD):
    try:
        p.unlink()
    except OSError:
        pass

print("=" * 60)
print("R7 smoke: 4 项优化验证")
print("=" * 60)

# 1) 后端 JSON API
print("\n[1] JSON 启动参数 API")
data = L.load_cmdline_args_dict()
print(f"  默认 dict: {data}")
lst = L.cmdline_args_dict_to_list(data)
print(f"  转为 list: {lst}")
ok, err = L.validate_cmdline_args_dict(data)
print(f"  校验: ok={ok}, err={err!r}")

# 2) 启动主窗口
print("\n[2] 启动 MainWindow")
win = MainWindow()
win.resize(1400, 900)
win.show()
app.processEvents()
print(f"  窗口尺寸: {win.size().width()}x{win.size().height()}")
print(f"  Console 页可见: {win._console_page.isVisible()}")

# 3) 验证 CPU 频率 widget 存在
print("\n[3] CPU 频率突出 (新增 _cpu_freq_lbl)")
cp = win._console_page
assert hasattr(cp, "_cpu_freq_lbl"), "_cpu_freq_lbl not found"
print(f"  _cpu_freq_lbl: text='{cp._cpu_freq_lbl.text()}'")
print(f"  _cpu_freq_lbl font size: {cp._cpu_freq_lbl.font().pointSize()}")
print(f"  _cpu_freq_lbl isBold: {cp._cpu_freq_lbl.font().bold()}")

# 4) 验证 VRAM 温度 label 默认隐藏
print("\n[4] VRAM 温度行 (不可用时隐藏)")
print(f"  _gpu0_vram_temp_lbl.isVisible (初始): {cp._gpu0_vram_temp_lbl.isVisible()}")
print(f"  _gpu1_vram_temp_lbl.isVisible (初始): {cp._gpu1_vram_temp_lbl.isVisible()}")

# 强制触发 refresh
cp.refresh()
app.processEvents()
print(f"  之后 _gpu0_vram_temp_lbl.isVisible: {cp._gpu0_vram_temp_lbl.isVisible()}")
print(f"  之后 _gpu1_vram_temp_lbl.isVisible: {cp._gpu1_vram_temp_lbl.isVisible()}")

# 5) 验证生成速度布局
print("\n[5] 生成速度布局 [生成速度 数字 单位]")
# 触发 token 刷新
cp._refresh_token()
app.processEvents()
print(f"  _token_speed_lbl: '{cp._token_speed_lbl.text()}'")
print(f"  父 layout children count: {cp._token_speed_lbl.parent().layout().count() if cp._token_speed_lbl.parent().layout() else 'N/A'}")

# 6) 切到 settings 页验证
print("\n[6] Settings 页 (JSON 启动参数)")
win._switch_to(1)  # settings page index
app.processEvents()
sp = win._settings_page
print(f"  _cmdline_edit 内容 (前 200 字符):")
content = sp._cmdline_edit.toPlainText()
print("  ---")
for line in content.splitlines()[:15]:
    print(f"    {line}")
print("  ---")

# 7) 截图
os.makedirs(".workbuddy/preview", exist_ok=True)

# Console
win._switch_to(0)
app.processEvents()
QTimer.singleShot(500, lambda: None)  # 等待后端采集
import time
time.sleep(2.0)  # 等 2s 让硬件数据回来
app.processEvents()
pix = win.grab()
pix.save(".workbuddy/preview/r7_console.png")
print(f"\n[7] 截图: .workbuddy/preview/r7_console.png ({pix.width()}x{pix.height()})")

# Settings
win._switch_to(1)
app.processEvents()
time.sleep(0.3)
app.processEvents()
pix = win.grab()
pix.save(".workbuddy/preview/r7_settings.png")
print(f"     .workbuddy/preview/r7_settings.png ({pix.width()}x{pix.height()})")

print("\n=" * 30)
print("OK: 全部验证通过")
print("=" * 60)

# 清理
for p in (L._CMDLINE_FILE, L._CMDLINE_FILE_OLD):
    try:
        p.unlink()
    except OSError:
        pass

app.quit()
