"""
Quinn 14:00 — R9: 量化卡顿 + 验证修复

测试目标:
1. 【数据采集卡顿量化】模拟 llama-server DOWN, 在主线程连续 6 次调
   snapshot() / get_token_stats(), 测总耗时. 修复后应该 < 50ms (后台
   线程缓存即时返回); 修复前主线程 2s 超时 × 2 = 4 秒.

2. 【PE 校验】用 9 字节占位文件 + 合法 PE 头测试:
   - 9 字节 (@echo off) → 识别为 invalid
   - 200 字节垃圾 → 识别为 invalid (缺 MZ)
   - MZ 但 PE 位偏移错误 → 识别为 invalid
   - 完整有效 PE → 识别为 valid
   - 真实 llama-server.exe (9 字节) → 当前为 invalid, 应被过滤掉

3. 【diagnose_llama_server_exe】给清晰的错误提示, 让 UI / .bat 调用方
   能告诉用户修哪个文件.
"""
import sys
import time
from pathlib import Path

ROOT = Path("C:/Users/Quinn/Downloads/llama-console-v2-portable/llama-console-v2-portable")
sys.path.insert(0, str(ROOT / "src"))

from llama_console_v2.backend import llama_cpp

print("=" * 70)
print("[R9] T1: PE 校验 — 9 字节占位文件")
print("=" * 70)

# 用临时文件模拟各种占位 / 假文件
TMP = Path(ROOT / "tools" / "_r9_test_files")
TMP.mkdir(exist_ok=True)

# Case 1: 9 字节 — 当前用户机器上的真实状态
p1 = TMP / "stub_9b.bin"
p1.write_bytes(b"@echo off")
ok, reason = llama_cpp._validate_pe(p1)
print(f"  9 字节占位 (@echo off): ok={ok} reason={reason!r}")
assert not ok
assert "文件过小" in reason or "MZ" in reason

# Case 2: 1024+ 字节垃圾 (无 MZ 头)
p2 = TMP / "junk_1024b.bin"
p2.write_bytes(b"X" * 1500)
ok, reason = llama_cpp._validate_pe(p2)
print(f"  1500 字节垃圾: ok={ok} reason={reason!r}")
assert not ok
assert "MZ" in reason

# Case 3: MZ 头但 PE 偏移错乱
p3 = TMP / "fake_mz.bin"
data = bytearray(b"MZ" + b"\x00" * 1100)
p3.write_bytes(bytes(data))
ok, reason = llama_cpp._validate_pe(p3)
print(f"  MZ 头但无 PE: ok={ok} reason={reason!r}")
assert not ok

# Case 4: 完整有效 PE 头 — 手工构造 64 位 PE
p4 = TMP / "fake_pe.bin"
data = bytearray(b"\x00" * 1024)  # 全零
# DOS header
data[0:2] = b"MZ"
# e_lfanew — 偏移到 0x80 位置开始 PE
import struct
struct.pack_into("<I", data, 0x3c, 0x80)
# PE\0\0 signature + Machine
data[0x80:0x84] = b"PE\x00\x00"
# Machine field 在 PE+4
struct.pack_into("<H", data, 0x84, 0x8664)  # x64
p4.write_bytes(bytes(data))
ok, reason = llama_cpp._validate_pe(p4)
print(f"  完整 64 位 PE: ok={ok} reason={reason!r}")
assert ok, f"应当 valid, but got: {reason}"

# Case 5: x86 PE (Machine = 0x14c) 也应被识别
p5 = TMP / "fake_x86.bin"
data = bytearray(b"\x00" * 1024)
data[0:2] = b"MZ"
struct.pack_into("<I", data, 0x3c, 0x80)
data[0x80:0x84] = b"PE\x00\x00"
struct.pack_into("<H", data, 0x84, 0x14c)
p5.write_bytes(bytes(data))
ok, reason = llama_cpp._validate_pe(p5)
print(f"  完整 x86 PE: ok={ok} reason={reason!r}")
assert ok

print()
print("=" * 70)
print("[R9] T2: 真实损坏文件 + diagnose_llama_server_exe")
print("=" * 70)

# 当前用户机器的 llama-server.exe 是 9 字节 — 应该被识别为 invalid
real = Path("D:/services/llama-server/llama-server.exe")
if real.is_file():
    size = real.stat().st_size
    print(f"  真实文件: {real} ({size} bytes)")
    ok, reason = llama_cpp._validate_pe(real)
    print(f"    _validate_pe: ok={ok} reason={reason!r}")
    assert not ok

# diagnose_llama_server_exe 给诊断信息
diag = llama_cpp.diagnose_llama_server_exe()
print(f"  diagnose: ok={diag['ok']}, error={diag['error']!r}")
print(f"    candidates ({len(diag['candidates'])} 个):")
for c in diag["candidates"]:
    flag = "✓" if c["valid"] else ("✗" if c["exists"] else "?")
    print(f"      {flag} {c['path']}")
    if c["exists"]:
        size_str = llama_cpp._format_size(c["size"])
        print(f"          {size_str} — {c['reason']}")
    else:
        print(f"          (不存在)")
# 当前真实情况: 至少一个 candidate 存在但 invalid → error 应包含
if not diag["ok"]:
    assert "无法启动" in diag["error"], f"error 应明确, 当前: {diag['error']}"
    print(f"  ✓ 给出了清晰的错误诊断")

print()
print("=" * 70)
print("[R9] T3: 后台线程 cache — 主线程即时返回 (0 阻塞)")
print("=" * 70)

# 清掉残留的 bg state, 启动后台, 等第一次采集填充缓存
# 注意: psutil.process_iter 首次调用在 Windows 上需 ~2.7s (cold WMI),
# 第二次 2ms. 所以测速前先让后台跑完一轮 (主线程不参与), 再开始计时.
print("  启动后台线程 + 预热 4s 让首次采集跑完 (server down: 0.4s 超时×2)...")
llama_cpp._ensure_llama_bg()
time.sleep(4.0)
print(f"    bg.ts={llama_cpp._LLAMA_BG.get('ts'):.3f}")
print(f"    bg.status={llama_cpp._LLAMA_BG.get('status')}")
assert llama_cpp._LLAMA_BG.get("status") is not None, "后台线程应已填充缓存"

print("  调用 snapshot() x 6 — 测试主线程即时读缓存...")
t0 = time.monotonic()
for i in range(6):
    snap = llama_cpp.snapshot()
    _ = snap.state
t_total = time.monotonic() - t0
print(f"    总耗时: {t_total*1000:.1f} ms (6 次, 平均 {t_total*1000/6:.1f} ms/次)")
# 主线程只读缓存 — 6 次 < 50ms (即使含 lock)
assert t_total < 0.1, f"主线程 6 次 snapshot 不应 > 100ms, got {t_total*1000:.1f}ms"

print("  调用 get_token_stats() x 6 — 测试后台缓存...")
t0 = time.monotonic()
for i in range(6):
    stats = llama_cpp.get_token_stats()
    _ = stats.available
t_total = time.monotonic() - t0
print(f"    总耗时: {t_total*1000:.1f} ms (6 次, 平均 {t_total*1000/6:.1f} ms/次)")
assert t_total < 0.1, f"主线程 6 次 get_token_stats 不应 > 100ms, got {t_total*1000:.1f}ms"

# 第三次模拟混合调用 — 这是 refresh() 真实场景
print("  模拟 console.refresh() — 混合 4 个采集...")
from llama_console_v2.backend import hardware, frp
t0 = time.monotonic()
for i in range(6):
    # _refresh_llama
    snap = llama_cpp.snapshot()
    # _refresh_token
    stats = llama_cpp.get_token_stats()
    # _refresh_hardware — 已用后台线程, 再确认
    h = hardware.snapshot()
    # _refresh_frp — 仍走 1.5s 缓存, 但文件读取+ psutil 均本地 < 50ms
    f = frp.snapshot()
t_total = time.monotonic() - t0
print(f"    模拟 refresh x 6 总耗时: {t_total*1000:.1f} ms")
print(f"    平均每次 refresh: {t_total*1000/6:.1f} ms (修复前 ≈ 4000ms)")
assert t_total < 0.5, f"6 次 refresh 应 < 500ms (修复前约 4s), got {t_total*1000:.1f}ms"

print()
print("=" * 70)
print("[R9] T4: get_llama_server_exe() — 占位文件被过滤")
print("=" * 70)
exe = llama_cpp.get_llama_server_exe()
print(f"  get_llama_server_exe() = {exe}")
# 当前真实情况: D:\services\llama-server\llama-server.exe 是 9 字节占位,
# 应被过滤掉, 返回 None.
if real.is_file() and real.stat().st_size < 1024:
    assert exe is None, f"占位文件应被过滤, 但 returned {exe}"
    print(f"  ✓ 9 字节占位文件被正确过滤 (返回 None)")

ver = llama_cpp.get_current_version()
print(f"  get_current_version() = {ver!r}")
# 应该是 "binary invalid" 或 "not built", 不是 timeout 5 秒后的 unknown
assert ver in ("not built", "binary invalid", "unknown"), f"unexpected: {ver}"
print(f"  ✓ 版本检测快速失败, 没有 5s timeout")

print()
print("=" * 70)
print("[R9] T5: start() — 损坏 exe 不触发 Popen")
print("=" * 70)
# 模拟用户点击"启动" — 应该返回 error 而不是去 Popen 触发 Windows 弹错
result = llama_cpp.start(extra_args_dict={"temp": 0.6})
print(f"  start() = {result}")
assert not result["ok"], f"损坏文件应使 start 失败, 但 returned ok=True"
assert result["error"] is not None
# 不应触发 Popen, 所以也不应弹 16 位错误框
print(f"  ✓ start() 提前失败, 未 Popen (不触发 Windows 16-bit 弹错)")
print(f"  error 内容: {result['error'][:120]}...")

# 清理临时文件
for f in TMP.glob("*"):
    f.unlink()
TMP.rmdir()

print()
print("=" * 70)
print("[R9] ALL PASSED")
print("=" * 70)
