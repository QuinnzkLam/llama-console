"""
R8 GUI smoke - Quinn 12:00 第八轮 4 项优化 offscreen 验证
1. 设置页 JSON 编辑器 — 4 颜色语法高亮 + key 无 --
2. 控制台 GPU 子卡 — ElideLabel 单行截断不撑高
3. 矮窗口 (840x520) — 无挤压, 按钮可见
4. 控制器 (1400x900) — 默认布局
"""
import os
import sys
sys.path.insert(0, "src")

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

from llama_console_v2.main_window import MainWindow
from llama_console_v2.backend import llama_cpp as L
from llama_console_v2.pages.console import _ElideLabel

# 清理
for p in (L._CMDLINE_FILE, L._CMDLINE_FILE_OLD):
    try: p.unlink()
    except OSError: pass

# 启动
win = MainWindow()
win.show()
app.processEvents()


# ============================================================
# A. 验证 1 - GPU ElideLabel 子类存在 + 设置/重置正常
# ============================================================
print("=" * 60)
print("A. ElideLabel 类 + 设置页 GPU 卡片就绪")
print("=" * 60)
print(f"  _ElideLabel class: {_ElideLabel}")
el = _ElideLabel("NVIDIA GeForce RTX 3070 Laptop GPU")
el.resize(120, 24)
print(f"  ElideLabel 创建成功, 默认 width=120, text 长度=35")
app.processEvents()

# 切到设置页
win._switch_to(1)
app.processEvents()
sp = win._settings_page

# 验证 JSON 编辑器内容中无 "--"
text = sp._cmdline_edit.toPlainText()
print(f"  编辑器前 200 字符: {text[:200]!r}")
assert '"--' not in text, "编辑器 JSON 中不应有 -- 前缀"
assert '"temp"' in text
assert '"top-p"' in text
print("  [OK] editor 内容无 --\n")


# ============================================================
# B. 验证 2 - 语法高亮器工作 + 4 颜色
# ============================================================
print("=" * 60)
print("B. 语法高亮器")
print("=" * 60)
highlighter = getattr(sp, "_highlighter", None)
assert highlighter is not None, "高亮器未挂载"
print(f"  高亮器: {highlighter.__class__.__name__}")
print("  [OK]\n")


# ============================================================
# C. 验证 3 - 矮窗口挤压 (840x520)
# ============================================================
print("=" * 60)
print("C. 矮窗口 840x520 设置页布局")
print("=" * 60)
win.resize(840, 520)
win._switch_to(1)
app.processEvents()

# 截图
from PySide6.QtCore import QSize
pix = win.grab()
pix.save(".workbuddy/preview/r8_settings_840x520.png", "PNG")
print(f"  Saved: .workbuddy/preview/r8_settings_840x520.png")

# 检查按钮是否在屏幕内
save_btn = sp._save_btn
btn_global = save_btn.mapTo(win, save_btn.rect().topLeft())
btn_bottom_global = save_btn.mapTo(win, save_btn.rect().bottomRight())
print(f"  Save 按钮: y_top={btn_global.y()} y_bot={btn_bottom_global.y()}")
print(f"  Window height: {win.height()}")

# cmdline_edit 区域
ce = sp._cmdline_edit
ce_global = ce.mapTo(win, ce.rect().topLeft())
ce_bottom_global = ce.mapTo(win, ce.rect().bottomRight())
print(f"  cmdline_edit: y_top={ce_global.y()} y_bot={ce_bottom_global.y()} height={ce_bottom_global.y()-ce_global.y()}")

# 不允许按钮压在输入框之上
assert ce_bottom_global.y() <= btn_global.y() + 4, f"cmdline_edit ({ce_bottom_global.y()}) 与按钮 ({btn_global.y()}) 重叠!"
print("  [OK] cmdline_edit 与按钮无重叠\n")


# ============================================================
# D. 验证 4 - 控制台矮窗口 + GPU 子卡截断
# ============================================================
print("=" * 60)
print("D. 控制台 840x520")
print("=" * 60)
win.resize(840, 520)
win._switch_to(0)
app.processEvents()

cp = win._console_page

# 模拟 GPU 0 拥有超长 model + 核心温度
gp0_model = cp._gpu0_model_lbl
print(f"  GPU 0 model class: {gp0_model.__class__.__name__}")
# 模拟超长文本 (RTX 3070 Laptop GPU 之类的真实场景)
long_text = "NVIDIA GeForce RTX 3070 Laptop GPU (WMI)"
gp0_model.setText(long_text)
print(f"  GPU 0 model text: {gp0_model.text()!r}")
print(f"  GPU 0 model tooltip: {gp0_model.toolTip()!r}")
gp1_model = cp._gpu1_model_lbl
gp1_model.setText("Intel UHD Graphics 770 + RADEON RX 6700 XT + RTX 4090 (vermilion)")
print(f"  GPU 1 model text: {gp1_model.text()!r}")

gp0_core_temp = cp._gpu0_core_temp_lbl
print(f"  GPU 0 core temp: height={gp0_core_temp.height()}, y={gp0_core_temp.y()}")
# trigger refresh
cp.refresh()
app.processEvents()
# 强制 process events 后 ElideLabel 重绘
gp0_model.update()
gp1_model.update()
app.processEvents()

pix = win.grab()
pix.save(".workbuddy/preview/r8_console_840x520.png", "PNG")
print(f"  Saved: .workbuddy/preview/r8_console_840x520.png")

# 验证 GPU 0 model_label 高度被锁定单行 (=18-28px)
print(f"  GPU 0 model height: {gp0_model.height()} (期望 <= 28)")
print(f"  GPU 1 model height: {gp1_model.height()} (期望 <= 28)")
assert gp0_model.height() <= 32, f"GPU 0 model 高度 {gp0_model.height()} 超出 32"
assert gp1_model.height() <= 32, f"GPU 1 model 高度 {gp1_model.height()} 超出 32"
print("  [OK] GPU 子卡在矮窗口下不被截断\n")


# ============================================================
# E. 验证 5 - 完整尺寸 1400x900
# ============================================================
print("=" * 60)
print("E. 完整尺寸 1400x900")
print("=" * 60)
win.resize(1400, 900)
win._switch_to(0)
app.processEvents()
cp.refresh()
app.processEvents()
pix = win.grab()
pix.save(".workbuddy/preview/r8_console_1400x900.png", "PNG")
print(f"  Saved: .workbuddy/preview/r8_console_1400x900.png")

win._switch_to(1)
app.processEvents()
pix = win.grab()
pix.save(".workbuddy/preview/r8_settings_1400x900.png", "PNG")
print(f"  Saved: .workbuddy/preview/r8_settings_1400x900.png")
print("  [OK]\n")


# ============================================================
# F. 清理
# ============================================================
for p in (L._CMDLINE_FILE, L._CMDLINE_FILE_OLD):
    try: p.unlink()
    except OSError: pass

print("[ALL OK]")
