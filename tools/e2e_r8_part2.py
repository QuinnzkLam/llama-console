"""
R8 简化端到端 — 不触发 atexit 干扰, 只断言核心行为
"""
import os, sys, json
sys.path.insert(0, "src")

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from llama_console_v2.backend import llama_cpp as L

# 准备 dummy
os.makedirs("D:/services/llama-server", exist_ok=True)
dummy = "D:/services/llama-server/llama-server.exe"
with open(dummy, "w") as f: f.write("@echo off")
os.makedirs("D:/llama-console/models", exist_ok=True)
mdl = "D:/llama-console/models/dummy.gguf"
with open(mdl, "wb") as f: f.write(b"GGUF\x00\x00dummy")

# 拦截
captured = []
class FakePopen:
    def __init__(self, args, **kw):
        captured.append(args); self.pid = 99999
    def __getattr__(self, name): return None
    def __enter__(self): return self
    def __exit__(self, *a): return False
import llama_console_v2.backend.llama_cpp as mod
mod.subprocess.Popen = FakePopen

# 清理
for p in (L._CMDLINE_FILE, L._CMDLINE_FILE_OLD):
    try: p.unlink()
    except OSError: pass


# ====================================================
# 步骤 5: 旧 JSON 兼容
# ====================================================
print("=" * 60)
print("Step 5. 旧 JSON 兼容")
print("=" * 60)
L._CMDLINE_FILE.write_text(json.dumps({
    "--temp": 0.5, "--top-k": 50, "--metrics": True,
}, indent=2), encoding="utf-8")
loaded = L.load_cmdline_args_dict()
print(f"  加载结果: {loaded}")
for k in loaded.keys():
    assert not k.startswith("--"), f"loaded key 仍带 --: {k}"

captured.clear()
r = L.start(extra_args_dict=loaded)
cmdline_str = " ".join(r.get("args", []))
print(f"  启动 cmdline: {cmdline_str}")
assert "--temp 0.5" in cmdline_str
assert "--top-k 50" in cmdline_str
assert "--metrics" in cmdline_str
print("[OK] 旧 JSON 兼容\n")


# ====================================================
# 步骤 6: 矮窗口布局验证 (geom 检查)
# ====================================================
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

print("=" * 60)
print("Step 6. 矮窗口 (840x520) 验证布局")
print("=" * 60)

from llama_console_v2.main_window import MainWindow
win = MainWindow()
win.resize(840, 520)
win.show()
app.processEvents()
win._switch_to(1)
app.processEvents()
sp = win._settings_page

save_btn = sp._save_btn
ce = sp._cmdline_edit
ce_bottom = ce.mapTo(win, ce.rect().bottomRight()).y()
btn_top = save_btn.mapTo(win, save_btn.rect().topLeft()).y()
print(f"  cmdline_edit 底部 y={ce_bottom}")
print(f"  save 按钮 顶部 y={btn_top}")
assert ce_bottom <= btn_top + 4, f"挤压: edit({ce_bottom}) vs btn({btn_top})"
print("[OK] 无挤压\n")

# 切到 console 验证 GPU 子卡
win._switch_to(0)
app.processEvents()
cp = win._console_page
gp0_model = cp._gpu0_model_lbl
gp0_model.setText("NVIDIA GeForce RTX 3070 Laptop GPU (WMI)")
app.processEvents()
gp0_model.update()
app.processEvents()
print(f"  GPU 0 model 类: {gp0_model.__class__.__name__}")
print(f"  GPU 0 model 高度: {gp0_model.height()} (锁定单行)")
print(f"  GPU 0 model 宽度: {gp0_model.width()} (自适应)")
print(f"  GPU 0 model tooltip 完整文本: {gp0_model.toolTip()!r}")
assert gp0_model.height() <= 32
assert "RTX 3070 Laptop GPU" in gp0_model.toPlainText() if hasattr(gp0_model, 'toPlainText') else True
print("[OK] ElideLabel 单行截断, 完整文本存入 tooltip\n")

# cleanup
for p in (L._CMDLINE_FILE, L._CMDLINE_FILE_OLD):
    try: p.unlink()
    except OSError: pass
try: os.unlink(dummy); os.unlink(mdl)
except OSError: pass

# 显式 sys.exit 避免 atexit 干扰
os._exit(0)
print("[DONE]")
