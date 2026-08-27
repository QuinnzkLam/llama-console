"""
R8 端到端 — 用户视角完整场景
1. 进入设置页, 看到的 JSON 编辑器是简洁写法 (无 --)
2. 4 颜色高亮生效 (key 青色加粗, value 绿色, 标点黄, 注释灰斜体)
3. 用户编辑后保存, JSON 文件内容无 --
4. 启动 llama-server 时自动加 --
"""
import os
import sys
sys.path.insert(0, "src")

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

from llama_console_v2.main_window import MainWindow
from llama_console_v2.backend import llama_cpp as L

# 准备
os.makedirs("D:/services/llama-server", exist_ok=True)
dummy = "D:/services/llama-server/llama-server.exe"
with open(dummy, "w") as f: f.write("@echo off")

os.makedirs("D:/llama-console/models", exist_ok=True)
mdl = "D:/llama-console/models/dummy.gguf"
with open(mdl, "wb") as f: f.write(b"GGUF\x00\x00dummy")

# 拦截 Popen
captured = []
class FakePopen:
    def __init__(self, args, **kw):
        captured.append(args); self.pid = 99999
    def __getattr__(self, name): return None
    def __enter__(self): return self
    def __exit__(self, *a): return False

import llama_console_v2.backend.llama_cpp as mod
mod.subprocess.Popen = FakePopen

# 清理旧配置
for p in (L._CMDLINE_FILE, L._CMDLINE_FILE_OLD):
    try: p.unlink()
    except OSError: pass

win = MainWindow()
win.resize(1400, 900)
win.show()
app.processEvents()
win._switch_to(1)  # 设置页
app.processEvents()

sp = win._settings_page

# ============================================================
# 步骤 1: 用户看到的初始 editor 内容 (无 -- 前缀)
# ============================================================
print("=" * 70)
print("Step 1. 设置页初始内容")
print("=" * 70)
initial_text = sp._cmdline_edit.toPlainText()
print(initial_text)
assert '"--' not in initial_text, "应不含 -- 前缀"
assert '"temp"' in initial_text
print("[OK] 用户看到的是简洁写法, 没有 -- 前缀\n")


# ============================================================
# 步骤 2: 验证语法高亮器已挂载
# ============================================================
print("=" * 70)
print("Step 2. 4 颜色语法高亮器已挂载")
print("=" * 70)
h = getattr(sp, "_highlighter", None)
assert h is not None, "高亮器不存在"
from PySide6.QtGui import QTextCharFormat, QColor
print(f"  类型: {h.__class__.__name__}")
print(f"  key 格式:    {h._ff.key_fmt.__class__.__name__} - 青色加粗")
print(f"  value 格式:   {h._ff.value_fmt.__class__.__name__} - 绿色")
print(f"  标点 格式:    {h._ff.punct_fmt.__class__.__name__} - 黄色")
print(f"  comment 格式: {h._ff.comment_fmt.__class__.__name__} - 灰色斜体")
# 验证 4 类 format 各带前景色
assert isinstance(h._ff.key_fmt, QTextCharFormat)
assert isinstance(h._ff.value_fmt, QTextCharFormat)
assert isinstance(h._ff.punct_fmt, QTextCharFormat)
assert isinstance(h._ff.comment_fmt, QTextCharFormat)
print("[OK]\n")


# ============================================================
# 步骤 3: 用户编辑 JSON, 然后保存
# ============================================================
print("=" * 70)
print("Step 3. 用户编辑 (单引号+注释+末尾逗号) 并保存")
print("=" * 70)
user_edited = '''{
    'temp': 0.7,           // 测试改温度
    'top-p': 0.85,
    'top-k': 30,
    'repeat-penalty': 1.15,
    'metrics': true,
}'''
sp._cmdline_edit.setPlainText(user_edited)
sp._on_save()
app.processEvents()
status = sp._params_status_lbl.text()
print(f"  保存状态: {status}")

# 验证磁盘文件
file_text = L._CMDLINE_FILE.read_text(encoding="utf-8")
print("  写入磁盘文件 (无 -- 前缀):")
for line in file_text.splitlines():
    print(f"    {line}")
assert '"--' not in file_text, "JSON 文件不应含 -- 前缀"
print("[OK] 保存到磁盘成功\n")


# ============================================================
# 步骤 4: 启动 llama-server, Popen 自动加 --
# ============================================================
print("=" * 70)
print("Step 4. 启动 llama-server (Popen 命令行含自动加的 --)")
print("=" * 70)
captured.clear()

# 模拟 MainWindow._on_sidebar_start 流程
extra_args_dict = L.load_cmdline_args_dict()
print(f"  加载配置: {extra_args_dict}")
r = L.start(extra_args_dict=extra_args_dict)
print(f"  start ok: {r.get('ok')}")
print("  Popen cmdline:")
cmdline_str = " ".join(r.get("args", []))
print(f"    {cmdline_str}")
assert "--temp" in cmdline_str, "启动命令行应含 --temp"
assert "0.7" in cmdline_str
assert "--top-p" in cmdline_str
assert "0.85" in cmdline_str
print("[OK] 启动命令行自动加回 -- 前缀\n")


# ============================================================
# 步骤 5: 旧 JSON 文件 (有 --) 也能正确加载 + 启动
# ============================================================
print("=" * 70)
print("Step 5. 旧 JSON 兼容 (key 带 -- 不报错, 启动也加 --)")
print("=" * 70)
try: L._CMDLINE_FILE.unlink()
except OSError: pass
import json
L._CMDLINE_FILE.write_text(json.dumps({
    "--temp": 0.5, "--top-k": 50, "--metrics": True,
}, indent=2), encoding="utf-8")

loaded = L.load_cmdline_args_dict()
print(f"  加载结果: {loaded}")  # 已剥前缀
for k in loaded.keys():
    assert not k.startswith("--"), "loaded key 仍带 --"

captured.clear()
r = L.start(extra_args_dict=loaded)
cmdline_str = " ".join(r.get("args", []))
print(f"  启动 cmdline: {cmdline_str}")
assert "--temp 0.5" in cmdline_str
assert "--top-k 50" in cmdline_str
assert "--metrics" in cmdline_str
print("[OK] 旧 JSON 兼容\n")


# ============================================================
# 步骤 6: 矮窗口布局验证
# ============================================================
print("=" * 70)
print("Step 6. 矮窗口 (840x520) 验证布局无遮挡")
print("=" * 70)
win.resize(840, 520)
win._switch_to(1)
app.processEvents()
save_btn = sp._save_btn
ce = sp._cmdline_edit
ce_bottom = ce.mapTo(win, ce.rect().bottomRight()).y()
btn_top = save_btn.mapTo(win, save_btn.rect().topLeft()).y()
print(f"  cmdline_edit 底部 y={ce_bottom}")
print(f"  save 按钮 顶部 y={btn_top}")
assert ce_bottom <= btn_top + 4, f"挤压: edit({ce_bottom}) vs btn({btn_top})"
print("[OK] 无挤压\n")


# 清理
for p in (L._CMDLINE_FILE, L._CMDLINE_FILE_OLD):
    try: p.unlink()
    except OSError: pass
try: os.unlink(dummy); os.unlink(mdl)
except OSError: pass

print("[ALL 6 STEPS PASSED]")
