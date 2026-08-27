"""
R8 单元验证 - Quinn 12:00 第八轮 4 项优化内部测试
"""
import os
import sys
sys.path.insert(0, "src")

from llama_console_v2.backend import llama_cpp as L


# ============================================================
# 1. Schema - key 已经没有 -- 前缀
# ============================================================
print("=" * 60)
print("1. Schema - key 已经没有 -- 前缀")
print("=" * 60)
schema = L.get_cmdline_schema()
for item in schema:
    assert not item["key"].startswith("--"), f"schema key 仍带 --: {item['key']!r}"
    print(f"  {item['key']:18s} type={item['type']:6s} default={item['default']}")
print("[OK]\n")


# ============================================================
# 2. 清理旧配置 + load 默认
# ============================================================
for p in (L._CMDLINE_FILE, L._CMDLINE_FILE_OLD):
    try: p.unlink()
    except OSError: pass

print("=" * 60)
print("2. load 默认 dict (key 无 --)")
print("=" * 60)
data = L.load_cmdline_args_dict()
for k, v in data.items():
    assert not k.startswith("--"), f"loaded key 仍带 --: {k!r}"
    print(f"  {k:18s} = {v}")
print("[OK]\n")


# ============================================================
# 3. cmdline_args_dict_to_list 启动时自动加 --
# ============================================================
print("=" * 60)
print("3. cmdline_args_dict_to_list 启动时自动加 --")
print("=" * 60)
args = L.cmdline_args_dict_to_list(data)
print("   ", args)
flags = [a for a in args if a.startswith("--")]
values = [a for a in args if not a.startswith("--")]
assert all(a.startswith("--") for a in flags)
assert all(not a.startswith("--") for a in values)
print(f"  flags: {flags}")
print(f"  values: {values}")
print("[OK]\n")


# ============================================================
# 4. 旧 JSON 文件兼容 (key 含 --)
# ============================================================
print("=" * 60)
print("4. 旧 JSON 文件兼容 (key 含 --)")
print("=" * 60)
import json
legacy = {
    "--temp": 0.7,
    "--top-p": 0.85,
    "--top-k": 30,
    "--repeat-penalty": 1.15,
    "--metrics": True,
}
L._CMDLINE_FILE.write_text(json.dumps(legacy, indent=2), encoding="utf-8")
loaded = L.load_cmdline_args_dict()
for k, v in loaded.items():
    assert not k.startswith("--"), f"loaded key 仍带 --: {k!r}"
    print(f"  {k:18s} = {v}")
# 启动转换
args2 = L.cmdline_args_dict_to_list(loaded)
print("  ", args2)
assert "--temp" in args2
assert "0.7" in args2
assert "--repeat-penalty" in args2
assert "1.15" in args2
print("[OK]\n")


# ============================================================
# 5. save + reload 完整往返 (JSON 文件无 --)
# ============================================================
print("=" * 60)
print("5. save + reload 完整往返 (JSON 文件无 --)")
print("=" * 60)
try: L._CMDLINE_FILE.unlink()
except OSError: pass
L.save_cmdline_args_dict({"temp": 0.55, "top-p": 0.92, "metrics": True})
file_text = L._CMDLINE_FILE.read_text(encoding="utf-8")
print("  写入磁盘文件:")
for line in file_text.splitlines():
    print(f"    {line}")
parsed = json.loads(file_text)
for k in parsed.keys():
    assert not k.startswith("--"), f"JSON 文件含 -- : {k!r}"
reloaded = L.load_cmdline_args_dict()
for k, v in reloaded.items():
    assert not k.startswith("--"), f"reload key 含 -- : {k!r}"
print("  reload 后:")
for k, v in reloaded.items():
    print(f"    {k:18s} = {v}")
print("[OK]\n")


# ============================================================
# 6. validate 兼容写法 (--temp 也能识别)
# ============================================================
print("=" * 60)
print("6. validate 兼容写法 (--temp 也能识别)")
print("=" * 60)
ok, err = L.validate_cmdline_args_dict({"--temp": 0.7})
print(f"  --temp: ok={ok}, err={err}")
assert ok
ok, err = L.validate_cmdline_args_dict({"temp": 0.7})
assert ok
ok, err = L.validate_cmdline_args_dict({"--unknown": 1})
assert not ok
print("[OK]\n")


# ============================================================
# 7. start() 启动命令行 (用 monkey-patch 拦截 Popen)
# ============================================================
print("=" * 60)
print("7. start() 启动命令行 (Popen 拦截验证 -- 前缀)")
print("=" * 60)
# 准备 dummy exe + model
os.makedirs("D:/services/llama-server", exist_ok=True)
dummy = "D:/services/llama-server/llama-server.exe"
with open(dummy, "w") as f: f.write("@echo off")
os.makedirs("D:/llama-console/models", exist_ok=True)
mdl = "D:/llama-console/models/dummy.gguf"
with open(mdl, "wb") as f: f.write(b"GGUF\x00\x00dummy")

import subprocess
captured = []
class FakePopen:
    def __init__(self, args, **kw):
        captured.append(args)
        self.pid = 99999
    def __getattr__(self, name): return None
    def __enter__(self): return self
    def __exit__(self, *a): return False

import llama_console_v2.backend.llama_cpp as mod
mod.subprocess.Popen = FakePopen

captured.clear()
r = L.start(extra_args_dict=data)
print(f"  start() ok={r.get('ok')}")
print(f"  内置 args (含自动加 --): {r.get('args')}")
assert r["ok"], "start() failed"
assert "--temp" in r["args"]
assert "0.6" in r["args"]
assert "--metrics" in r["args"]
print("[OK]\n")

# cleanup (用 try 保护, 不让任何异常影响测试结果)
for p in (L._CMDLINE_FILE, L._CMDLINE_FILE_OLD):
    try: p.unlink()
    except OSError: pass
try: os.unlink(dummy)
except OSError: pass
try: os.unlink(mdl)
except OSError: pass

print()
print("[ALL 7 OK]")
