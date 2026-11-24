"""v2 backend/llama_cpp.py - llama-server 进程/启动/停止 + version + update check.

架构独立: 唔依赖 v1 backend。直接用 psutil + httpx + subprocess + GitHub API。

Quinn 14:00 (本轮):
- _validate_pe(): 检查 MZ/PE 头 + Machine 字段, 识别 9 字节损坏占位文件
  (Windows 会把这种文件当 16 位 DOS 程序弹"不支持的 16 位应用程序"对话框).
- _BG_WORKER + _TOKEN_CACHE: 后台线程每 2s 拉一次 status + token_stats,
  主线程即时读缓存 — 彻底消除 httpx 2s 超时阻塞导致的 GUI 刷新卡顿.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import struct
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import psutil

# Quinn 11:11 (T1-A): process name detection fix.
# Stub launcher (D:/services/llama-server/llama-server.exe, 9216B) delegates
# 启动真 server, 真 server process 可能叫 llama-server-impl.exe 或其他
# llama* 开头嘅名。_find_process() 必须按 pattern 抓最新嗰个, 唔再 hardcode
# 单个 image name。
LLAMA_PROCESS_NAME = "llama-server.exe"  # 保留向后兼容 (其他模块可能 import)
# Known concrete names (tuple, ordered — first match wins on tie):
_LLAMA_PROCESS_NAMES: tuple[str, ...] = (
    "llama-server.exe",
    "llama-server-impl.exe",
)
# Forward-compat: llama-server 變體 (e.g. 未来改名叫 llama-server-cuda.exe)
# 2026-11-24 根因修復: 舊 pattern "^llama.*\.exe$" 連 GUI 自己 (LlamaDeck.exe)
# 都匹配 → stop() forward-compat scan taskkill 自己 (按停止=窗口關閉) +
# _find_process() 返 GUI pid (uptime 顯示 GUI 時間)。改精確匹配 llama-server*。
_LLAMA_PROCESS_PATTERN = re.compile(r"^llama-server(-impl)?\.exe$", re.IGNORECASE)
DEFAULT_PORT = 18605
DEFAULT_HOST = "0.0.0.0"
DEFAULT_CTX = 262144
GITHUB_API = "https://api.github.com/repos/ggerganov/llama.cpp/releases/latest"

# v2 local compiled binary location
_V2_BIN_DIR = Path("D:/llama-console/llama.cpp/build/bin")
# 2026-09-01 (搬迁): v1 rollback binary 原在 D:/services/llama-server/ (将移除),
# 不再引用该目录. 统一以 v2 本地编译二进制为唯一来源, fallback 指向同一 v2 路径
# (实际取第一个有效 PE, 不影响逻辑).
_V1_FALLBACK = Path("D:/llama-console/llama.cpp/build/bin/llama-server.exe")
# v2 models dir
_MODELS_DIR = Path("D:/llama-console/models")

# Quinn 23:18: 4.2 chat-template fix — v0.3.0 内建 default template 唔认 Qwen3.8-27B
# 嘅 chat format, /v1/chat/completions 返空。强制 bind 落官方 jinja
# (从 GGUF tokenizer.chat_template 抽出, 9993 bytes, 含 vision/developer/think/tool)。
# 启动时硬编码, 用户唔可以喺 settings page 误删。
_CHAT_TEMPLATE_FILE = Path("D:/llama-console/chat_templates/qwen.jinja")


# ============================================================
# Binary location + version + PE 完整性校验 (Quinn 14:00)
# ============================================================

# Quinn 14:00: 已知合法 Machine 字段值
_MACHINE_X64 = 0x8664
_MACHINE_X86 = 0x14c
_MACHINE_ARM64 = 0xaa64


def _validate_pe(path: Path) -> tuple[bool, str]:
    """校验 path 是否为合法 64/32 位 PE 可执行文件.

    Quinn 14:00: 发现 D:\\services\\llama-server\\llama-server.exe 实际是 9 字节
    占位文件 (内容 @echo off), Windows 看到非 PE 文件会弹"不支持的 16 位
    应用程序"对话框 (NTVDM 错误). 这里识别这种情况并返回 False.

    Returns:
        (ok, reason): ok=True 表示合法 PE; ok=False 时 reason 是失败原因.

    检测规则:
      1. 文件大小 < 1KB (基本 PE header 都要 ~1KB+)
      2. 头部 2 字节必须为 'MZ' (IMAGE_DOS_SIGNATURE)
      3. e_lfanew (offset 0x3c) 指向 IMAGE_NT_SIGNATURE ('PE\\0\\0')
      4. Machine 字段必须是 x64 / x86 / ARM64 之一 (拒绝 DOS MZ / 16 位 / 未识别)
    """
    try:
        if not path.is_file():
            return False, "文件不存在"
        size = path.stat().st_size
        if size < 1024:
            return False, f"文件过小 ({size} bytes), 不是合法 PE 可执行文件"
        with path.open("rb") as f:
            head = f.read(max(1024, size))
        if len(head) < 0x40:
            return False, "文件无法读取完整 DOS 头"
        # 1) MZ signature
        if head[:2] != b"MZ":
            return False, f"缺 MZ DOS 头 ({head[:4]!r})"
        # 2) e_lfanew offset -> PE signature
        if len(head) < 0x40:
            return False, "文件头长度不足"
        pe_offset = struct.unpack_from("<I", head, 0x3c)[0]
        if pe_offset < 0x40 or pe_offset + 24 > len(head):
            return False, f"e_lfanew 越界 ({pe_offset})"
        if head[pe_offset:pe_offset + 4] != b"PE\x00\x00":
            return False, "缺 PE\\0\\0 签名"
        # 3) Machine 字段 (offset 0x18 from PE signature)
        if pe_offset + 24 > len(head):
            return False, "文件头截断, 无法读 Machine"
        machine = struct.unpack_from("<H", head, pe_offset + 4)[0]
        if machine not in (_MACHINE_X64, _MACHINE_X86, _MACHINE_ARM64):
            return False, (
                f"Machine=0x{machine:X} 不是合法的 PE 类型 "
                "(预期 x64=0x8664 / x86=0x14C / ARM64=0xAA64)"
            )
        return True, "ok"
    except OSError as e:
        return False, f"读文件失败: {e}"
    except Exception as e:  # noqa: BLE001
        return False, f"校验异常: {e}"


def _format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def diagnose_llama_server_exe() -> dict:
    """诊断 llama-server.exe 状态 — 给 UI 状态面板或启动诊断提示用.

    Quinn 14:00: 修复弹"不支持的 16 位应用程序"对话框 — 提前识别损坏的
    占位文件, 给清晰错误, 避免用户面对 NTVDM 的"与 64 位 Windows 不兼容".

    Returns:
        {
            ok: bool,                     # 是否找到且 PE 合法
            path: str | None,             # 实际定位到的 exe 路径
            reason: str,                  # ok=False 时说明失败原因
            candidates: list[{path, exists, valid, size, reason}],  # 所有候选诊断
            error: str | None,            # 候选全部不可用时的汇总错误
        }
    """
    out = {
        "ok": False,
        "path": None,
        "reason": "",
        "candidates": [],
        "error": None,
    }
    if os.name == "nt":
        candidates = [_V2_BIN_DIR / "llama-server.exe", _V1_FALLBACK]
    else:
        candidates = [_V2_BIN_DIR / "llama-server", _V1_FALLBACK.with_name("llama-server")]
    for c in candidates:
        info = {
            "path": str(c),
            "exists": c.is_file(),
            "valid": False,
            "size": 0,
            "reason": "文件不存在",
        }
        if info["exists"]:
            info["size"] = c.stat().st_size
            valid, reason = _validate_pe(c)
            info["valid"] = valid
            info["reason"] = reason
        out["candidates"].append(info)
    # 找第一个有效的
    for info in out["candidates"]:
        if info["valid"]:
            out["ok"] = True
            out["path"] = info["path"]
            out["reason"] = "ok"
            return out
    # 全部不可用 — 汇总原因
    reasons = []
    for info in out["candidates"]:
        if info["exists"]:
            reasons.append(
                f"{info['path']} ({_format_size(info['size'])}): {info['reason']}"
            )
        else:
            reasons.append(f"{info['path']}: 不存在")
    out["error"] = "llama-server.exe 无法启动. 排查:\n  - " + "\n  - ".join(reasons)
    out["reason"] = "no valid PE binary found"
    return out


def get_llama_server_exe() -> Path | None:
    """Priority: v2 local build > v1 precompiled fallback > None.

    Quinn 14:00: 加 PE 校验 — 损坏占位文件 (如 9 字节的 @echo off 假 exe)
    直接跳过, 避免 Popen 后 Windows 弹"不支持的 16 位应用程序"对话框.
    """
    if os.name == "nt":
        candidates = [
            _V2_BIN_DIR / "llama-server.exe",
            _V1_FALLBACK,
        ]
    else:
        candidates = [_V2_BIN_DIR / "llama-server", _V1_FALLBACK.with_name("llama-server")]
    for c in candidates:
        if not c.is_file():
            continue
        ok, _ = _validate_pe(c)
        if ok:
            return c
        # 损坏的占位文件 — 跳过, 但记录日志方便诊断
        print(f"[llama_cpp] skip invalid PE: {c} ({_format_size(c.stat().st_size)})")
    return None


def get_current_version() -> str:
    """Read built-in version string from llama-server binary.

    Quinn 14:00: 加 PE 校验 — 损坏占位文件直接返回 "unknown", 不再
    等 5 秒 timeout 由用户干着急.
    """
    exe = get_llama_server_exe()
    if exe is None:
        # 再单独跑一次诊断 — 可能是候选存在但 PE 损坏
        diag = diagnose_llama_server_exe()
        if diag["candidates"] and any(c["exists"] for c in diag["candidates"]):
            return "binary invalid"
        return "not built"
    try:
        result = subprocess.run(
            [str(exe), "--version"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        out = (result.stdout + result.stderr).strip()
        m = re.search(r"version[:\s]+(\S+)", out, re.IGNORECASE)
        if m:
            return m.group(1)
        return out.splitlines()[0] if out else "unknown"
    except Exception:
        return "unknown"


def get_latest_github_release() -> dict:
    """Return {ok, version, url, error}."""
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.get(GITHUB_API, headers={"User-Agent": "llama-console-v2"})
            r.raise_for_status()
            data = r.json()
            return {"ok": True, "version": data.get("tag_name", ""), "url": data.get("html_url", ""), "error": None}
    except Exception as e:
        return {"ok": False, "version": "", "url": "", "error": str(e)}


def is_update_available() -> dict:
    """Return {available, current, latest, error}."""
    current = get_current_version()
    rel = get_latest_github_release()
    if not rel["ok"]:
        return {"available": False, "current": current, "latest": "", "error": rel["error"]}
    # Simple string compare (good enough for bNNNN format)
    return {
        "available": rel["version"] != current,
        "current": current,
        "latest": rel["version"],
        "error": None,
    }


# ============================================================
# Process status
# ============================================================

def _find_process() -> psutil.Process | None:
    """Find the most recently started llama* process.

    Quinn 11:11 (T1-A): stub launcher delegates to 真 server (impl.exe 或其他),
    唔再 hardcode "llama-server.exe" 单个名。改用 regex `^llama` + 按 create_time
    倒序排, 揀最新嗰个 — 兼容 stub launcher + 直 spawn 两种路径。
    """
    candidates: list[tuple[float, psutil.Process]] = []
    my_pid = os.getpid()
    for p in psutil.process_iter(["name", "pid", "create_time"]):
        try:
            if p.info["pid"] == my_pid:
                continue  # GUI 本體 (LlamaDeck.exe) 唔算 llama-server (2026-11-24)
            name = p.info["name"]
            if not name:
                continue
            lname = name.lower()
            # Match concrete known names OR any llama*.exe (forward-compat)
            if lname in _LLAMA_PROCESS_NAMES or _LLAMA_PROCESS_PATTERN.match(name):
                create_time = p.info["create_time"] or 0.0
                candidates.append((create_time, p))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    if not candidates:
        return None
    # Newest first (最大 create_time); tie-break by largest pid (更晚启嘅)
    candidates.sort(key=lambda cp: (cp[0], cp[1].info["pid"]), reverse=True)
    return candidates[0][1]


def _format_uptime(sec: int) -> str:
    if sec <= 0:
        return "-"
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h}h {m:02d}m {s:02d}s"


# Quinn 14:00: 检测局域网 IP (不发包, UDP connect trick).
# 用于 local_url 显示真实 LAN 地址 (e.g. http://192.168.50.167:18605),
# 取代硬编码 127.0.0.1.
_LAN_IP_CACHE: dict = {"ip": None, "ts": 0.0}
_LAN_IP_TTL = 300.0  # s (5 分钟缓存)
_LAN_IP_TIMEOUT = 0.3  # s


def _get_lan_ip() -> str | None:
    """返回本机局域网 IP (UDP socket connect trick, 不发包).

    Quinn 14:00: 核弹机实测返回 192.168.50.167.
    """
    now = time.monotonic()
    cached_ip = _LAN_IP_CACHE.get("ip")
    cached_ts = _LAN_IP_CACHE.get("ts", 0.0)
    if cached_ip and now - cached_ts < _LAN_IP_TTL:
        return cached_ip
    import socket
    ip = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(_LAN_IP_TIMEOUT)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        except Exception:
            pass
        finally:
            s.close()
    except Exception:
        pass
    # 即使本次失败也更新 ts, 避免反复尝试
    _LAN_IP_CACHE["ts"] = now
    if ip:
        _LAN_IP_CACHE["ip"] = ip
        return ip
    # 失败: 返回上次缓存值 (可能为 None, 也可能为旧值)
    return cached_ip


def _probe_health(port: int) -> str:
    """Probe /health to determine state. Returns "running" | "loading".

    Quinn 14:00: timeout 2.0 -> 0.4s (localhost loopback 通常 < 5ms, 400ms
    已经足够给慢启动留余量; server 完全 down 时快速失败不阻塞主线程).

    2026-08-31 (A1): 加 trust_env=False — loopback httpx 唔可以走系统代理.
    背景: Windows 系统代理 (127.0.0.1:33210) 会劫持 127.0.0.1:18605 嘅请求,
    导致 GUI 永远「加载中」(probe 等到 timeout 先 fallback).
    加 trust_env 后 httpx 直接连 socket, 唔查 HTTP_PROXY/HTTPS_PROXY env.
    """
    try:
        with httpx.Client(timeout=0.4, trust_env=False) as c:
            r = c.get(f"http://127.0.0.1:{port}/health")
            if r.status_code == 200 and r.json().get("status") == "ok":
                return "running"
    except Exception:
        pass
    return "loading"


_QUANT_RE = re.compile(r"[-.](Q\d+_\d+|[Ff]\d+|[Kk]\-[Ss]+|[Ii]Q\d+_[A-Z]+)$")


def _display_model_name(name: str) -> str:
    """从原始 .gguf 文件名剥出干净显示名 (去掉 .gguf + 尾部 quant token).

    Quinn 16:11: 显示给用户看的 title 要简洁 — "Qwen3.8-27B-Q8_0.gguf" -> "Qwen3.8-27B".
    Examples:
        "Qwen3.8-27B-Q8_0.gguf"             -> "Qwen3.8-27B"
        "Llama-3.1-8B-Instruct.Q8_0.gguf"   -> "Llama-3.1-8B-Instruct"
        "model.gguf"                         -> "model"
    """
    if not name:
        return name
    n = name
    # 先去 .gguf 后缀 (大小写不敏感)
    if n.lower().endswith(".gguf"):
        n = n[:-5]
    # 尾部 quant token 匹配 (使用现有 quant regex, 但锚定到尾部 $)
    m = _QUANT_RE.search(n)
    if m:
        n = n[: m.start()]
    return n


def _get_model_info_from_props(port: int = DEFAULT_PORT) -> tuple[str | None, str | None, int | None]:
    """Fallback: read model info from /props HTTP API (0.4s short timeout).

    Franky 2026-09-02 (Bug 1/2 修复): 当 llama-server 由 Windows 定时任务
    (schtasks, RunLevel=HighestAvailable) 启动时, 该实例为 admin integrity (High),
    NLM.exe 以普通用户 (Medium) 运行读唔到进程 cmdline → cmdline 解析失败
    → model/ctx 显示 "-"。但 /props、/health、/metrics 全部 HTTP 200 可达。

    这里 fallback 到 /props 攞 model_path / model_ftype / n_ctx / model_alias,
    与 _probe_health 同策略: trust_env=False (bypass 系统代理) + 0.4s 短超时。
    """
    try:
        with httpx.Client(timeout=0.4, trust_env=False) as c:
            r = c.get(f"http://127.0.0.1:{port}/props")
            if r.status_code != 200:
                return None, None, None
            data = r.json()
    except Exception:
        return None, None, None
    if not isinstance(data, dict):
        return None, None, None
    display_name = None
    quant = None
    ctx = None
    raw_model = data.get("model_path")
    if raw_model:
        raw_model = Path(str(raw_model)).name
        display_name = _display_model_name(raw_model)
        if "-" in raw_model:
            stem = raw_model[:-5] if raw_model.lower().endswith(".gguf") else raw_model
            m = _QUANT_RE.search(stem)
            if m:
                quant = m.group(1).lstrip("-").lstrip(".")
    try:
        ctx = int(data.get("n_ctx"))
    except (TypeError, ValueError):
        ctx = None
    if ctx is None:
        # /props 的 n_ctx 可能嵌套喺 default_generation_settings 里
        dgs = data.get("default_generation_settings")
        if isinstance(dgs, dict):
            try:
                ctx = int(dgs.get("n_ctx"))
            except (TypeError, ValueError):
                ctx = None
    # model_path 解析唔到 / 唔存在 → 用 alias 兜底 (如 "qwen3.8-27b")
    if not display_name and data.get("model_alias"):
        display_name = str(data["model_alias"])
    return display_name, quant, ctx


def _get_model_info() -> tuple[str | None, str | None, int | None]:
    """Return (display_name, quant, ctx_size) by reading process cmdline.

    Quinn 16:11: display_name 已剥掉 .gguf + 尾部 quant, 形如 "Qwen3.8-27B".

    Franky 2026-09-02 (Bug 1/2): cmdline 读唔到 (AccessDenied, 定时任务 elevated
    启动) 或 cmdline 扒唔到 model/ctx → fallback 到 /props HTTP API, 确保状态卡
    喺两种启动路径下显示一致 (model name + ctx)。
    """
    proc = _find_process()
    if proc is None:
        return None, None, None
    try:
        cmdline = proc.cmdline()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        # 定时任务 (elevated) 启动 → 普通用户读唔到 cmdline → /props fallback
        return _get_model_info_from_props()
    raw_model = None
    quant = None
    ctx = None
    for i, arg in enumerate(cmdline):
        if arg == "-m" and i + 1 < len(cmdline):
            raw_model = Path(cmdline[i + 1]).name
        # ctx-size 有两种写法: "--ctx-size <N>" 或 "-c <N>" (短选项)
        elif arg in ("--ctx-size", "-c") and i + 1 < len(cmdline):
            try:
                ctx = int(cmdline[i + 1])
            except ValueError:
                pass
    # cmdline 可读但扒唔到 model/ctx (e.g. 特殊启动方式) → 防御性 fallback
    if raw_model is None and ctx is None:
        return _get_model_info_from_props()
    display_name = _display_model_name(raw_model) if raw_model else None
    if raw_model and "-" in raw_model:
        # Detect quant from filename like "Qwen3.8-27B-Q8_0.gguf"
        # 先剥 .gguf 再匹配尾部 quant (避免 .gguf 干扰 $ 错位)
        stem = raw_model[:-5] if raw_model.lower().endswith(".gguf") else raw_model
        m = _QUANT_RE.search(stem)
        if m:
            quant = m.group(1).lstrip("-").lstrip(".")
    return display_name, quant, ctx


def get_status() -> SimpleNamespace:
    """Return SimpleNamespace(state, model_name, quant, ctx_size, port, pid, uptime,
    bind, public_url, local_url).

    Quinn 14:00: /health 检测改走 0.4s 短超时 — server down / 卡住时不再
    阻塞主线程 2 秒. 主线程一般通过 snapshot() 走后台缓存, get_status()
    只在手动调用或 sync fallback 时执行.
    """
    proc = _find_process()
    port = DEFAULT_PORT
    if proc is None:
        return SimpleNamespace(
            state="stopped", model_name=None, quant=None, ctx_size=None,
            port=port, pid=None, uptime="-", bind=f"{DEFAULT_HOST}:{port}",
            public_url=None, local_url=None,
        )
    try:
        uptime_sec = int(time.time() - proc.create_time())
    except Exception:
        uptime_sec = 0
    model, quant, ctx = _get_model_info()
    return SimpleNamespace(
        state=_probe_health(port),  # 0.4s 短超时, server down 时快速失败
        model_name=model, quant=quant, ctx_size=ctx,
        port=port, pid=proc.pid, uptime=_format_uptime(uptime_sec),
        bind=f"{DEFAULT_HOST}:{port}",
        public_url=None,  # populated by console layer merging frp snapshot
        local_url=f"http://{_get_lan_ip() or '127.0.0.1'}:{port}",
    )


# ============================================================
# 主线程缓存 + 后台线程采集 (Quinn 14:00: 消除 httpx 阻塞主线程导致的 GUI 卡顿)
#
# 问题: 原 snapshot() 走 1.5s TTL cache, 但 console.refresh() 间隔 10s > TTL,
#       每次 refresh 都是冷调用 → httpx.get(/health) 2s 超时阻塞主线程,
#       console 表现"刷一次卡一次". get_token_stats() 同理.
#
# 方案: 后台 daemon 线程每 2s 跑一次 (status + token_stats) 并写缓存.
#       主线程 snapshot()/get_token_stats() 改为即时读缓存.
# ============================================================
_LLAMA_BG: dict = {
    "status": None,         # 上次 status SimpleNamespace
    "token_stats": None,    # 上次 token_stats SimpleNamespace
    "ts": 0.0,              # monotonic 上次采集完成时间
}
_LLAMA_BG_LOCK = threading.Lock()
_LLAMA_BG_THREAD: threading.Thread | None = None
_LLAMA_BG_INTERVAL = 2.0       # s (与 hardware.py 一致)
_LLAMA_BG_STARTED = False
_LLAMA_BG_STALE_LIMIT = 5.0    # s (冷启动 / 后台挂时降级为同步)


def _llama_bg_worker() -> None:
    """后台线程: 每 2s 同步采集 status + token_stats."""
    while True:
        try:
            try:
                status = get_status()
            except Exception:
                status = _find_llama_status_minimal()
            try:
                tok = _collect_token_stats_now()
            except Exception:
                tok = SimpleNamespace(
                    prompt_tokens=None, predicted_tokens=None,
                    prompt_tps=None, predicted_tps=None,
                    available=False, stale=False, stale_ts=None,
                )
            with _LLAMA_BG_LOCK:
                _LLAMA_BG["status"] = status
                _LLAMA_BG["token_stats"] = tok
                _LLAMA_BG["ts"] = time.monotonic()
        except Exception:
            # 单次失败不应杀死线程
            pass
        time.sleep(_LLAMA_BG_INTERVAL)


def _find_llama_status_minimal() -> SimpleNamespace:
    """冷启动期 fallback — BG 线程尚未产出缓存时用.

    Franky 2026-09-02 (Bug 2 修复): 之前硬编码 state="loading" 即使 llama-server
    已就绪. 主线程首次 refresh() 落入此 fallback 时, 永远显示「加载中」直到
    BG 线程第一次完成 (~1-2s 后). 改为: proc 存在时调 _probe_health(port)
    (0.4s 短超时 + trust_env=False) 拿真实 state. server 真 down 时回退
    到 "loading". 此函数仅在主线程冷启动早期被调一次, 后续都走 BG 缓存.
    """
    proc = _find_process()
    port = DEFAULT_PORT
    if proc is None:
        return SimpleNamespace(
            state="stopped", model_name=None, quant=None, ctx_size=None,
            port=port, pid=None, uptime="-",
            bind=f"{DEFAULT_HOST}:{port}",
            public_url=None, local_url=None,
        )
    try:
        uptime_sec = int(time.time() - proc.create_time())
    except Exception:
        uptime_sec = 0
    model, quant, ctx = _get_model_info()
    return SimpleNamespace(
        state=_probe_health(port),  # Franky 2026-09-02 Bug 2: 探 /health 拿真实 state
        model_name=model, quant=quant, ctx_size=ctx,
        port=port, pid=proc.pid, uptime=_format_uptime(uptime_sec),
        bind=f"{DEFAULT_HOST}:{port}",
        public_url=None,
        local_url=f"http://{_get_lan_ip() or '127.0.0.1'}:{port}",
    )


def _ensure_llama_bg() -> None:
    """懒启动后台采集线程 (仅一次)."""
    global _LLAMA_BG_THREAD, _LLAMA_BG_STARTED
    if _LLAMA_BG_STARTED:
        return
    _LLAMA_BG_STARTED = True
    _LLAMA_BG_THREAD = threading.Thread(
        target=_llama_bg_worker, name="llama-collector", daemon=True,
    )
    _LLAMA_BG_THREAD.start()


def snapshot() -> SimpleNamespace:
    """返回 llama-server 状态 (Quinn 14:00: 后台线程采集, 主线程 0 阻塞).

    流程:
      - 后台线程未就绪: 同步走 _find_llama_status_minimal() (sub-ms, 不调 httpx)
      - 后台线程已就绪: 即时读缓存; 缓存 5s 内有效
      - 缓存陈旧 (>5s): 同步 _find_llama_status_minimal() 兜底; 主线程不会卡
        死 (httpx 已挪到后台)
    """
    _ensure_llama_bg()
    with _LLAMA_BG_LOCK:
        cached = _LLAMA_BG.get("status")
        ts = _LLAMA_BG.get("ts", 0.0)
    now = time.monotonic()
    if cached is not None and 0 < now - ts < _LLAMA_BG_STALE_LIMIT:
        return cached
    # 冷启动早期或后台挂掉: 同步 fallback (无 httpx, < 50ms)
    try:
        return _find_llama_status_minimal()
    except Exception:
        return SimpleNamespace(
            state="stopped", model_name=None, quant=None, ctx_size=None,
            port=DEFAULT_PORT, pid=None, uptime="-",
            bind=f"{DEFAULT_HOST}:{DEFAULT_PORT}",
            public_url=None, local_url=None,
        )


# ============================================================
# Start / Stop
# ============================================================

def start(model_path: str | None = None, port: int = DEFAULT_PORT,
          host: str = DEFAULT_HOST, ctx_size: int = DEFAULT_CTX,
          ngl: int = 99, extra_args: list[str] | None = None,
          extra_args_dict: dict | None = None) -> dict:
    """Start llama-server via Popen. Returns {ok, pid, error}.

    Quinn 12:00: extra_args / extra_args_dict 二选一.
    - extra_args (旧 list[str]): 直接附加到 cmdline, 形如 ["--port", "8080", "--temp", "0.6"]
    - extra_args_dict (新 dict): key 不含 "--" 前缀 (简洁写法),
      后端自动加 "--" 展平为 ["--temp", "0.6", ...]. None/空串 跳过;
      bool=True -> 仅加 flag, bool=False 跳过. key 已带 "--" 也兼容 (legacy 迁移).

    Quinn 14:00: Popen 前增加 PE 校验 — 损坏占位文件直接给清晰错误,
    避免 Windows 弹"不支持的 16 位应用程序"对话框 (NTVDM 错误).
    """
    # 2026-09-01 (T3 fix): 先把 config 层的 positional keys 拆出来映射,
    # 防止 model/mmproj/ngl/ctx_size/image_min_tokens 被当成 --model/--ngl 直通
    cfg_model: str | None = None
    cfg_mmproj: str | None = None
    if extra_args_dict is not None:
        extra_args_dict, _pos = _split_positional_keys(extra_args_dict)
        if _pos.get("model"):
            cfg_model = str(_pos["model"])
        if _pos.get("mmproj"):
            cfg_mmproj = str(_pos["mmproj"])
        if _pos.get("ngl") is not None:
            try:
                ngl = int(_pos["ngl"])
            except (TypeError, ValueError):
                pass
        if _pos.get("ctx_size") is not None:
            try:
                ctx_size = int(_pos["ctx_size"])
            except (TypeError, ValueError):
                pass
        if _pos.get("image_min_tokens") is not None:
            try:
                extra_args_dict = dict(extra_args_dict)
                extra_args_dict["image-min-tokens"] = int(_pos["image_min_tokens"])
            except (TypeError, ValueError):
                pass
    exe = get_llama_server_exe()
    if exe is None:
        # 区分"文件不存在" vs "PE 损坏" — 调用方据此提示用户修哪条路径
        diag = diagnose_llama_server_exe()
        if diag.get("error"):
            return {"ok": False, "pid": None, "error": diag["error"]}
        return {"ok": False, "pid": None, "error": "llama-server.exe not found"}
    # 2026-09-01 (T3 fix): config "model" 字段 -> -m 路径 (支持裸文件名或绝对路径)
    if model_path is None and cfg_model:
        _cm = Path(cfg_model)
        if not _cm.is_absolute():
            _cm = _MODELS_DIR / cfg_model
        if _cm.is_file():
            model_path = str(_cm)
    if model_path is None:
        models = list(_MODELS_DIR.rglob("*.gguf"))
        main = [m for m in models if "mmproj" not in m.name.lower()]
        if not main:
            return {"ok": False, "pid": None, "error": "no main model .gguf in models/"}
        model_path = str(main[0])
    args = [str(exe), "-m", model_path, "--port", str(port), "--host", host,
            "-c", str(ctx_size), "-ngl", str(ngl)]
    # Quinn 23:18 (4.2): 强制 --chat-template-file, 唔可以 miss
    # 4.1b smoke 发现: --jinja 用 v0.3.0 内建 default 唔认 Qwen3.8-27B → content 空
    if _CHAT_TEMPLATE_FILE.is_file():
        args.extend(["--chat-template-file", str(_CHAT_TEMPLATE_FILE)])
    model_dir = Path(model_path).parent
    # 2026-09-01 (T3 fix): config "mmproj" 字段优先, 否则 glob 第一个
    _mmproj_pick: str | None = None
    if cfg_mmproj:
        _cp = Path(cfg_mmproj)
        if not _cp.is_absolute():
            _cp = _MODELS_DIR / cfg_mmproj
        if _cp.is_file():
            _mmproj_pick = str(_cp)
    if _mmproj_pick is None:
        mmprojs = list(model_dir.glob("mmproj*.gguf"))
        if mmprojs:
            _mmproj_pick = str(mmprojs[0])
    if _mmproj_pick:
        args.extend(["--mmproj", _mmproj_pick])
    if extra_args_dict is not None:
        for k, v in extra_args_dict.items():
            if v is None or v == "":
                continue
            flag = _ensure_flag_prefix(k)
            if isinstance(v, bool):
                if v:
                    args.append(flag)
                continue
            args.append(flag)
            args.append(str(v))
    elif extra_args:
        args.extend(extra_args)
    # 2026-09-01 (bug fix): GUI 自 spawn 的 llama-server 也写 stderr log, 供真失败
    # (bad arg / 端口冲突 / 加载 abort) 时用户睇到具体报错. 位置同搬迁后 bat 的 log 一致.
    log_file = None
    log_path = None
    try:
        _log_dir = Path("D:/llama-console/logs")
        _log_dir.mkdir(parents=True, exist_ok=True)
        log_path = str(_log_dir / "llama_win_gui.log")
        log_file = open(log_path, "w", encoding="utf-8", errors="replace")
    except Exception:
        log_file = None
        log_path = None
    try:
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW
            proc = subprocess.Popen(args, cwd=str(model_dir),
                                    creationflags=creationflags,
                                    stdout=log_file or subprocess.DEVNULL,
                                    stderr=subprocess.STDOUT)
        else:
            proc = subprocess.Popen(args, cwd=str(model_dir),
                                    stdout=log_file or subprocess.DEVNULL,
                                    stderr=subprocess.STDOUT,
                                    start_new_session=True)
        return {"ok": True, "pid": proc.pid, "error": None, "exe": str(exe),
                "args": args, "log_path": log_path,
                "health_reachable": True}
    except Exception as e:
        if log_file is not None:
            try:
                log_file.close()
            except Exception:
                pass
        return {"ok": False, "pid": None, "error": str(e), "log_path": log_path,
                "health_reachable": False}


def _elevated_kill_llama() -> bool:
    """Kill an elevated (admin-integrity) llama-server via UAC elevation.

    2026-09-01 (Franky): 根因 — schtask \\Hedanji-Llama-Start 用
    RunLevel=HighestAvailable 起 llama-server, 该实例为 admin integrity
    (High). GUI (NLM.exe) 以普通用户 (Medium) 运行, taskkill /F 对 High
    进程返回 Access Denied → 「无法暂停」. 这里用 Start-Process -Verb RunAs
    触发一次 UAC 提升, 由 taskkill 以管理员身份结束残留的 elevated llama.

    Returns:
        True 若成功发起 (UAC 已被接受 / 无需确认); False 若失败或用户取消.
    """
    try:
        # -Verb RunAs 触发 UAC; taskkill /T 同时结束进程树
        ps = (
            'powershell -NoProfile -ExecutionPolicy Bypass -Command '
            '"Start-Process -FilePath taskkill.exe '
            '-ArgumentList \'/F\',\'/IM\',\'llama-server.exe\',\'/T\' '
            '-Verb RunAs -WindowStyle Hidden"'
        )
        # creationflags=CREATE_NO_WINDOW: 避免 shell=True 借 cmd.exe 宿主弹黑窗。
        # -Verb RunAs 本身由 powershell 触发 UAC, 不会另开可见 console。
        subprocess.run(ps, shell=True, timeout=25, capture_output=True, text=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        # Start-Process -Verb RunAs 本身返回即代表用户已接受 UAC
        return True
    except Exception:
        return False


def stop() -> dict:
    """Stop all llama-server processes. Returns {ok, killed, error, elevated, residual}.

    2026-09-01 (Franky): 修复「GUI 停唔到非自己 spawn 嘅 llama-server」.
    - schtask 以 HighestAvailable 起嘅 llama 是 admin integrity (High),
      Medium GUI 嘅 taskkill /F 会 Access Denied.
    - 先做普通 taskkill (可杀 Medium llama); 若仍有 llama 残留 (elevated),
      再触发一次 UAC 提升的 taskkill (elevated fallback).
    - 返回字段: killed=[已杀 image name], elevated=bool 是否用了 UAC 提升,
      residual=bool 是否仍有 llama 残留 (GUI 可据此提示).
    """
    killed = []
    elevated = False
    try:
        if os.name == "nt":
            # Quinn 11:11 (T1-A): taskkill 唔支持 glob, 必须列出具体 image name。
            # 先 kill 已知名字 (impl.exe 可能由 stub spawn), 再 fallback 到主名。
            for name in _LLAMA_PROCESS_NAMES:
                result = subprocess.run(
                    ["taskkill", "/F", "/IM", name],
                    capture_output=True, text=True, timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                # taskkill returncode 0 = 杀到, 128 = 搵唔到 (仍算 OK)
                if result.returncode == 0:
                    killed.append(name)
            # Forward-compat: 如果当时有其他 llama*.exe 跑紧, 主动探一下并 kill
            my_pid = os.getpid()
            for p in psutil.process_iter(["name"]):
                try:
                    if p.info["pid"] == my_pid:
                        continue  # 唔好自殺 — GUI 本體都匹配 llama* pattern (2026-11-24)
                    pname = p.info["name"]
                    if pname and _LLAMA_PROCESS_PATTERN.match(pname) and pname not in killed:
                        result = subprocess.run(
                            ["taskkill", "/F", "/IM", pname],
                            capture_output=True, text=True, timeout=10,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                        if result.returncode == 0:
                            killed.append(pname)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        else:
            # POSIX: pkill -f 支持 regex, 直接用
            result = subprocess.run(["pkill", "-f", "llama-server"], capture_output=True, text=True, timeout=10)
            killed = [LLAMA_PROCESS_NAME] if result.returncode == 0 else []
        # --- Elevated fallback (2026-09-01 v2): 只有确认 llama 真系卡住先 UAC ---
        # taskkill /F 对 27B 模型需数秒释放 VRAM/上下文先真正退出; 对 elevated
        # (High) 实例则直接 AccessDenied (killed 为空). 所以唔好依赖 killed 是否非空,
        # 统一轮询 _find_process() 最多 ~8s:
        #   - 8s 内退出 → 正常关停, 唔弹 UAC
        #   - 8s 后仍在 → 疑似 elevated / 卡死 → 触发 UAC 提升再 kill
        residual = False
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if _find_process() is None:
                break
            time.sleep(1.0)
        else:
            residual = True
        if residual:
            elevated = _elevated_kill_llama()
            # 再等一次让 elevated taskkill 生效
            time.sleep(2.0)
            if _find_process() is None:
                residual = False
                if "llama-server.exe (elevated)" not in killed:
                    killed.append("llama-server.exe (elevated)")
        return {"ok": True, "killed": killed, "elevated": elevated,
                "residual": residual, "error": None}
    except Exception as e:
        return {"ok": False, "killed": killed, "elevated": elevated,
                "residual": True, "error": str(e)}


# ============================================================
# Settings page API (called by pages/settings.py)
# Quinn 11:35: 启动参数改 JSON 格式 — 每项有 name/key/description/default,
#              后端在 start() 时把 dict 展平为 ["--key", "value", ...]
# ============================================================

# JSON 配置文件路径 (取代旧 cmdline_args.txt)
_CMDLINE_FILE = Path("D:/llama-console/config/qwen3.8-27b.json")
# 旧版纯文本配置 (用于首次启动时自动迁移)
_CMDLINE_FILE_OLD = Path("D:/llama-console/cmdline_args.txt")


# 参数定义 schema (Quinn 12:00: key 不带 "--" 前缀, 启动时后端自动加)
# - key:   GUI 配置名 (e.g. "temp"), 后端启动时加 "--" -> "--temp"
# - name:  GUI 显示的中文名
# - type:  bool / int / float / str
# - default: 默认值 (None = 不传该 flag)
# - description: 作用说明
_CMDLINE_SCHEMA: list[dict] = [
    # --- 采样/思考组 (Unsloth Qwen3.8-27B 思考模式推荐) ---
    {"key": "temp",          "name": "温度系数",
     "type": "float", "default": 1.0,
     "description": "采样温度. Unsloth Qwen3.8 思考模式=1.0 / 指令模式=0.7."},
    {"key": "top-p",         "name": "Top-P",
     "type": "float", "default": 0.95,
     "description": "核采样概率累计阈值. Unsloth Qwen3.8 思考=0.95 / 指令=0.80."},
    {"key": "top-k",         "name": "Top-K",
     "type": "int",   "default": 20,
     "description": "仅从概率最高的 K 个 token 中采样. Unsloth Qwen3.8 推荐 20."},
    {"key": "min-p",         "name": "Min-P",
     "type": "float", "default": 0.0,
     "description": "最小概率阈值. Unsloth Qwen3.8 推荐 0.0."},
    {"key": "presence-penalty", "name": "存在惩罚",
     "type": "float", "default": 0.0,
     "description": "抑制已出现 token. Unsloth Qwen3.8 思考=0.0 / 指令=1.5."},
    {"key": "repeat-penalty", "name": "重复惩罚",
     "type": "float", "default": 1.0,
     "description": "抑制重复输出. Unsloth Qwen3.8 推荐 1.0."},
    {"key": "chat-template-kwargs", "name": "推理力度",
     "type": "str",   "default": '{\"reasoning_effort\":\"medium\"}',
     "description": "JSON 字符串透传给聊天模板. reasoning_effort: xhigh/medium/low/none (官方默认 xhigh)."},
    {"key": "metrics",       "name": "启用 metrics 端点",
     "type": "bool",  "default": True,
     "description": "暴露 /metrics 端点, 用于控制台采集 token 统计. 关掉后无法显示速度."},
    # --- 硬件必需组 (2x3090 48GB 跑 262K 上下文, 删除会爆 VRAM/RAM) ---
    {"key": "split-mode",    "name": "层切分模式",
     "type": "str",   "default": "tensor",
     "description": "多 GPU 层切分方式, 核弹机 2x3090 用 tensor."},
    {"key": "fit",            "name": "参数自动适配",
     "type": "str",   "default": "off",
     "description": "--fit on/off. v0.3.0 默认 on, 对 tensor 模式会 abort "
                     "(llama_params_fit is not implemented for SPLIT_MODE_TENSOR). "
                     "必须 off 才能用 tensor 启动."},
    {"key": "flash-attn",    "name": "Flash Attention",
     "type": "str",   "default": "on",
     "description": "闪存注意力 on/off/auto, 开咗省速省时."},
    {"key": "parallel",      "name": "并发 slot 数",
     "type": "int",   "default": 1,
     "description": "同时处理请求的 slot 数 -np, 1 最慳 VRAM."},
    {"key": "spec-type",     "name": "投机解码",
     "type": "str",   "default": "draft-mtp",
     "description": "投机解码类型: draft-mtp (自带 MTP 头, Unsloth 已启用) / draft-dflash (外部 DFlash2 draft 模型, 需配 spec-draft-model)."},
    {"key": "spec-draft-model", "name": "Draft 模型",
     "type": "str",   "default": "",
     "description": "投机解码外部 draft 模型文件 (-md), 相对 models/ 目录. draft-dflash 必填 (如 Qwen3.8-27B-DFlash2-Q8_0.gguf); draft-mtp 留空."},
    {"key": "spec-draft-n-max", "name": "Draft 最大 token 数",
     "type": "int",   "default": 7,
     "description": "每步投机 draft token 数上限 (--spec-draft-n-max). DFlash2 硬上限 7 (block_size-1, 超出被静默钳制); MTP 推荐 3."},
    {"key": "cache-type-k",  "name": "KV cache K 量化",
     "type": "str",   "default": "q8_0",
     "description": "KV cache K 量化 q8_0. 262K 上下文必须, 否则 KV 爆 VRAM."},
    {"key": "cache-type-v",  "name": "KV cache V 量化",
     "type": "str",   "default": "q8_0",
     "description": "KV cache V 量化 q8_0. 262K 上下文必须, 否则 KV 爆 VRAM."},
    {"key": "cache-ram",     "name": "KV cache RAM 上限",
     "type": "int",   "default": 0,
     "description": "禁止 KV cache 溢出到宿主 RAM (0=禁用)."},
    {"key": "no-cache-idle-slots", "name": "空闲 slot 不保留 KV",
     "type": "bool",  "default": True,
     "description": "空闲 slot 不保留 KV cache, 省内存."},

    # --- 模型命名组 ---
    {"key": "alias",         "name": "模型别名",
     "type": "str", "default": "qwen3.8-27b",
     "description": "llama-server --alias, 决定 /v1/models 返回的 model id (默认 qwen3.8-27b)."},
]


def _ensure_flag_prefix(key: str) -> str:
    """确保 key 以 '--' 开头 (用于启动 cmdline). schema 已不带前缀, 这里统一加回.

    兼容: 旧 JSON 文件可能写 "--temp", 直接保留.
    """
    s = str(key).strip()
    if s.startswith("--"):
        return s
    if s.startswith("-"):
        # 单 '-' (短选项) 跳过补全, 避免破坏短选项
        return s
    return f"--{s}"


def _strip_flag_prefix(key: str) -> str:
    """启动 cmdline key 反序列化到配置 dict 时用 — 去掉 '--' 前缀以便与 schema 对齐.

    配置层统一无 '--'; 调用方 start() 时再用 _ensure_flag_prefix 加回.
    """
    s = str(key).strip()
    if s.startswith("--"):
        return s[2:]
    return s


def _schema_defaults_dict() -> dict:
    """从 schema 生成默认参数 dict (key -> default)."""
    return {item["key"]: item["default"] for item in _CMDLINE_SCHEMA}


def _coerce_value(value, type_str: str):
    """根据 schema type 转换 value, 失败抛 ValueError."""
    if value is None:
        return None
    if type_str == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            s = value.strip().lower()
            if s in ("true", "1", "yes", "on"):
                return True
            if s in ("false", "0", "no", "off"):
                return False
        if isinstance(value, (int, float)):
            return bool(value)
        raise ValueError(f"无法识别为 bool: {value!r}")
    if type_str == "int":
        if isinstance(value, bool):
            raise ValueError(f"int 不能是 bool: {value!r}")
        return int(value)
    if type_str == "float":
        if isinstance(value, bool):
            raise ValueError(f"float 不能是 bool: {value!r}")
        return float(value)
    if type_str == "str":
        return str(value)
    raise ValueError(f"未知类型: {type_str}")


# 2026-09-01 (T3 fix): GUI 配置层的 positional keys — 有语义映射, 不能当 "--key value"
# 直通传给 llama-server (旧逻辑把 config 里的 model/ngl/ctx_size 等变成 --model/--ngl/
# --ctx_size, 其中 --ngl 被 llama-server v0.3.0 拒绝: "error: invalid argument: --ngl";
# 白名单校验也对 "model" 报 "unknown parameter: 'model'").
# 映射: model -> -m 路径; mmproj -> --mmproj; ngl -> -ngl; ctx_size -> -c;
#       image_min_tokens -> --image-min-tokens.
_POSITIONAL_KEYS = {"model": str, "mmproj": str, "ngl": int, "ctx_size": int, "image_min_tokens": int}


def _split_positional_keys(data: dict) -> tuple[dict, dict]:
    """拆出 positional config keys. 返回 (flag_keys, positional_dict).

    flag_keys 保留原始 key 写法 (交给原 extra_args_dict 展平逻辑);
    positional_dict 的 key 已剥前缀并按 _POSITIONAL_KEYS 归类.
    """
    flags: dict = {}
    pos: dict = {}
    for k, v in data.items():
        kk = _strip_flag_prefix(k)
        if kk in _POSITIONAL_KEYS:
            pos[kk] = v
        else:
            flags[k] = v
    return flags, pos


def _migrate_from_legacy_text() -> dict | None:
    """从旧 cmdline_args.txt 迁移到 JSON. 成功返回 dict, 失败/无文件返回 None.

    Quinn 12:00: 旧 txt 中 key 含 "--" (e.g. "--temp"), 而 schema 已统一无前缀;
    这里统一剥前缀成 dict (key 形如 "temp"), 并按 schema 类型 coerce.
    """
    if not _CMDLINE_FILE_OLD.is_file():
        return None
    try:
        text = _CMDLINE_FILE_OLD.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    # 旧格式: 每行 "-ngl 99" / "--temp 0.6" (flag + value)
    args = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        # 拆分 flag 和 value (e.g. "--temp 0.6" -> ["--temp", "0.6"])
        parts = s.split(maxsplit=1)
        if not parts:
            continue
        if not parts[0].startswith("-"):
            continue
        if len(parts) == 2:
            args.append((_strip_flag_prefix(parts[0]), parts[1]))
        else:
            # 仅 flag 无 value (e.g. "--metrics") -> metrics=True
            args.append((_strip_flag_prefix(parts[0]), True))
    # 合并到默认 dict, 同时按 schema 做类型 coerce
    out = _schema_defaults_dict()
    schema_map = {it["key"]: it for it in _CMDLINE_SCHEMA}
    for k, v in args:
        if k in out and k in schema_map:
            try:
                out[k] = _coerce_value(v, schema_map[k]["type"])
            except (ValueError, TypeError):
                out[k] = v  # coerce 失败保留原值
    return out


def load_cmdline_args_dict() -> dict:
    """读取 JSON 配置, 不存在则从旧 txt 迁移或返回默认.

    Quinn 12:00: 返回 dict 的 key 一律不带 "--" 前缀 (与 schema 对齐).
    旧 JSON 文件可能写带前缀, 加载时统一剥掉.

    Returns:
        dict: {key: value, ...}. value 类型由 schema 决定 (int/float/bool/str).
    """
    if _CMDLINE_FILE.is_file():
        try:
            data = json.loads(_CMDLINE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # 按 schema 做类型 coerce (JSON 文件可能被手编, 类型可能错)
                return _coerce_dict(data)
        except (OSError, json.JSONDecodeError):
            pass
    # 尝试从旧 txt 迁移
    migrated = _migrate_from_legacy_text()
    if migrated is not None:
        save_cmdline_args_dict(migrated)
        return migrated
    # 返回默认
    return _schema_defaults_dict()


def _coerce_dict(data: dict) -> dict:
    """按 schema 转换 dict 各 value 类型. 未知 key 保留原值.

    Quinn 12:00: key 进来后统一剥前缀, 避免 JSON 里手编 "--temp" 与 schema "temp" 不匹配.
    """
    schema_map = {it["key"]: it for it in _CMDLINE_SCHEMA}
    out: dict = {}
    for raw_k, v in data.items():
        k = _strip_flag_prefix(raw_k)  # 兼容旧写法 "--temp" -> "temp"
        if k in schema_map:
            try:
                out[k] = _coerce_value(v, schema_map[k]["type"])
                continue
            except (ValueError, TypeError):
                pass
        out[k] = v
    return out


def save_cmdline_args_dict(data: dict) -> None:
    """写入 JSON 配置. Quinn 12:00: key 一律剥前缀, 启动时再加回."""
    _CMDLINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    norm = {_strip_flag_prefix(k): v for k, v in data.items()}
    _CMDLINE_FILE.write_text(
        json.dumps(norm, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def reset_cmdline_args_dict() -> dict:
    """重置为 schema 默认, 并落盘."""
    data = _schema_defaults_dict()
    save_cmdline_args_dict(data)
    return data


def cmdline_args_dict_to_list(data: dict) -> list[str]:
    """把 dict 转换为 ["--flag", "value", ...] 列表, 后端 cmdline 兼容格式.

    Quinn 12:00: 启动时自动给 key 加 "--" 前缀, 用户配置里写简洁的 "temp".
    - 跳过 schema 中不存在的 key (宽容, 用户写错也不报错)
    - None / 空串跳过
    - bool=True  -> 仅加 flag, bool=False 跳过
    - bool str  ("true"/"false") 同样处理
    - 其他      -> [--flag, str(value)]
    """
    out: list[str] = []
    for item in _CMDLINE_SCHEMA:
        raw_k = item["key"]
        if raw_k not in data:
            continue
        flag = _ensure_flag_prefix(raw_k)
        v = data[raw_k]
        if v is None or v == "":
            continue
        if item["type"] == "bool":
            if isinstance(v, bool):
                if v:
                    out.append(flag)
                continue
            # 容忍 str
            s = str(v).strip().lower()
            if s in ("true", "1", "yes", "on"):
                out.append(flag)
            # else: 视为 false 跳过
            continue
        out.append(flag)
        out.append(str(v))
    return out


def get_cmdline_schema() -> list[dict]:
    """返回 schema 副本 (供 settings.py 渲染注释用)."""
    return [dict(item) for item in _CMDLINE_SCHEMA]


def validate_cmdline_args_dict(data: dict) -> tuple[bool, str]:
    """校验 dict, 返回 (ok, error_msg).

    Quinn 12:00: 已知 keys 用无前缀形式; 旧写法 "--temp" 自动剥前缀比较.
    """
    if not isinstance(data, dict):
        return False, f"根必须是 JSON object, 当前是 {type(data).__name__}"
    known = {item["key"] for item in _CMDLINE_SCHEMA} | set(_POSITIONAL_KEYS)
    schema_map = {item["key"]: item for item in _CMDLINE_SCHEMA}
    for raw_k, v in data.items():
        k = _strip_flag_prefix(raw_k)
        if k not in known:
            return False, f"未知参数: {raw_k!r} (白名单: {', '.join(sorted(known))})"
        # 2026-09-01 (T3 fix): positional keys 用自身类型校验, 不再报 unknown parameter
        if k in _POSITIONAL_KEYS:
            t = _POSITIONAL_KEYS[k]
            if t is int and (isinstance(v, bool) or not isinstance(v, int)):
                return False, f"{raw_k} 需为整数, 当前 {v!r}"
            if t is str and not isinstance(v, str):
                return False, f"{raw_k} 需为字符串, 当前 {v!r}"
            continue
        try:
            _coerce_value(v, schema_map[k]["type"])
        except (ValueError, TypeError) as e:
            return False, f"{raw_k} 值无效: {e}"
    return True, ""


# ----------------------------------------------------------------
# 2026-11-20 Quinn 需求: GUI 模型选择绑定 —— active model / profile 切换
# ----------------------------------------------------------------
def get_active_model_filename() -> str | None:
    """读取当前生效主 JSON (_CMDLINE_FILE) 的 "model" 文件名.

    2026-11-20 Quinn 需求: 供 settings 下拉定位当前项 + current_model_path 解析路径.
    文件不存在 / JSON 损坏 / 无 model 字段 → None.
    """
    if not _CMDLINE_FILE.is_file():
        return None
    try:
        data = json.loads(_CMDLINE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    model = data.get("model")
    if model is None or model == "":
        return None
    return str(model)


def select_model_profile(model_filename: str) -> dict:
    """切换模型: 加载 config/models/<stem>.json profile 覆盖主 JSON 配置.

    2026-11-20 Quinn 需求, 三分支:
      1) profile 存在且 validate_cmdline_args_dict 通过 → 用 profile 全部参数写回主 JSON
      2) profile 存在但校验失败 → 保留主 JSON 现有参数, 仅更新 model 字段 (安全回退)
      3) profile 不存在 → 主 JSON 仅更新 model 字段
    返回最终 dict (调用时已写回主 JSON, GUI 端据此刷新编辑器).
    """
    stem = Path(model_filename).stem
    profile = _CMDLINE_FILE.parent / "models" / (stem + ".json")
    base = load_cmdline_args_dict()  # 主 JSON 现状 (已剥前缀 + 类型 coerce)

    final: dict
    if profile.is_file():
        try:
            profile_data = json.loads(profile.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            profile_data = None
        if isinstance(profile_data, dict):
            ok, _err = validate_cmdline_args_dict(profile_data)
            if ok:
                # 分支 1: profile 合法 → 全部参数覆盖
                final = _coerce_dict(profile_data)
            else:
                # 分支 2: profile 校验失败 → 保留主 JSON 参数, 仅换 model
                final = dict(base)
        else:
            # profile 读不进来 → 等同不存在 (分支 3)
            final = dict(base)
    else:
        # 分支 3: 无 profile → 仅换 model
        final = dict(base)

    # 无论哪一支, 生效 model 必须与下拉选择一致
    final["model"] = model_filename
    save_cmdline_args_dict(final)
    return final


# ----------------------------------------------------------------
# 向后兼容: 旧 list[str] API 仍可用, 但底层走 JSON 配置
# ----------------------------------------------------------------
def list_models() -> list[str]:
    """Return all main .gguf model basenames in models dir (excludes mmproj)."""
    if not _MODELS_DIR.is_dir():
        return []
    out: list[str] = []
    for gguf in sorted(_MODELS_DIR.rglob("*.gguf")):
        if "mmproj" in gguf.name.lower():
            continue
        out.append(gguf.name)
    return out


def current_model_path() -> str | None:
    """Return full path of currently active main model (or None).

    2026-11-20 Quinn 需求: 优先读 _CMDLINE_FILE 的 model 字段解析 active model
    (_MODELS_DIR / filename); 找不到才 fallback 旧逻辑 (list_models()[0]).
    """
    active = get_active_model_filename()
    if active:
        candidate = Path(active)
        if not candidate.is_absolute():
            candidate = _MODELS_DIR / active
        if candidate.is_file():
            return str(candidate)
    # fallback: 第一个 main model (与旧 _load_models 行为一致)
    models = list_models()
    if not models:
        return None
    return str(_MODELS_DIR / models[0])


def current_cmdline_args() -> list[str]:
    """向后兼容: 返回 list[str] (one per element, "--key value" 形式).

    Quinn 11:35: 底层走 JSON 配置, 这里是给旧 callers 的便捷包装.
    """
    data = load_cmdline_args_dict()
    return cmdline_args_dict_to_list(data)


def save_cmdline_args(args: list[str]) -> None:
    """向后兼容: 接受 list[str] (形如 ["--temp", "0.6", "--metrics"]) 写入 JSON.

    Quinn 12:00: key 形如 "--temp" 自动剥前缀成 "temp" 落盘; 配置层无 "--".
    """
    data = _schema_defaults_dict()
    i = 0
    while i < len(args):
        k = args[i]
        if not k.startswith("-"):
            i += 1
            continue
        k_norm = _strip_flag_prefix(k)  # "--temp" -> "temp"
        if k_norm in data:
            sch = next(it for it in _CMDLINE_SCHEMA if it["key"] == k_norm)
            if sch["type"] == "bool":
                # 单独 flag (无 value) -> True, 或下一个值是 -flag -> True
                if i + 1 >= len(args) or args[i + 1].startswith("-"):
                    data[k_norm] = True
                    i += 1
                else:
                    s = str(args[i + 1]).strip().lower()
                    if s in ("true", "1", "yes", "on"):
                        data[k_norm] = True
                    else:
                        data[k_norm] = False
                    i += 2
            else:
                if i + 1 < len(args):
                    try:
                        data[k_norm] = _coerce_value(args[i + 1], sch["type"])
                    except (ValueError, TypeError):
                        data[k_norm] = sch["default"]
                    i += 2
                else:
                    i += 1
        else:
            # 未知 key, 跳过
            i += 1
    save_cmdline_args_dict(data)


def default_cmdline_args() -> list[str]:
    """向后兼容: 返回默认 list[str]."""
    return cmdline_args_dict_to_list(_schema_defaults_dict())


def get_version() -> str:
    """Alias for get_current_version() — v2 settings.py uses get_version()."""
    return get_current_version()


def check_latest_version() -> str:
    """Return latest GitHub release tag (or empty on error)."""
    rel = get_latest_github_release()
    return rel.get("version", "") if rel.get("ok") else ""


# ============================================================
# Token / 性能统计 (Quinn 17:53 反馈)
# 解析 llama-server /metrics Prometheus 端点 (需以 --metrics 启动)
#
# Quinn 14:00: 同样改后台线程采集 + 主线程即时读缓存 (消除 2s httpx 阻塞).
# _collect_token_stats_now() 是实际采集函数, 由后台 llama_bg_worker 调用.
# ============================================================

def _parse_metrics(text: str) -> dict[str, float]:
    """解析 Prometheus 文本格式 -> {metric_name: value}."""
    out: dict[str, float] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "{" in line:
            # 带 label 暂时忽略 (e.g. llamacpp:n_tokens_max{slot_id="0"} ... value)
            name_label, _, value = line.partition(" ")
            out.setdefault(name_label.strip(), _safe_float(value))
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        out.setdefault(parts[0], _safe_float(parts[-1]))
    return out


def _safe_float(s: str) -> float:
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


# Quinn 16:11 (R12): token 统计持久化 — 服务关闭后能继续显示上一次数字.
_TOKEN_STATE_FILE = Path("D:/llama-console/token_stats_state.json")


def _save_token_state(ns: SimpleNamespace) -> None:
    """把当前 token 统计快照写盘 (供服务关闭后读取显示). 写盘失败只 pass."""
    try:
        _TOKEN_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "prompt_tokens": ns.prompt_tokens,
            "predicted_tokens": ns.predicted_tokens,
            "prompt_tps": ns.prompt_tps,
            "predicted_tps": ns.predicted_tps,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),  # ISO8601 local time
        }
        _TOKEN_STATE_FILE.write_text(
            json.dumps(payload, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def _load_token_state() -> dict | None:
    """读上次的 token 统计快照. 失败返 None."""
    if not _TOKEN_STATE_FILE.is_file():
        return None
    try:
        data = json.loads(_TOKEN_STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return None


def _collect_token_stats_now(port: int = DEFAULT_PORT) -> SimpleNamespace:
    """实际执行一次 /metrics 拉取 + 解析 (后台线程调用, 用 0.4s 短超时).

    Quinn 14:00: 与 snapshot() 同策略 — 真正昂贵的 httpx 调用挪到后台,
    主线程拿到的是缓存的 SimpleNamespace, 不再阻塞 2 秒.

    Quinn 16:11 (R12): 新增 stale / stale_ts 字段 — 服务关闭后还能显示上一次数字.
      - available=True  : stale=False, stale_ts=None
      - available=False : 若盘上有 state → 带旧数字 + stale=True + stale_ts=ISO 串
                          若盘上无 state → 全 None + stale=False, stale_ts=None

    Franky 2026-09-02 (Bug 1): 连接判定改为纯 HTTP (/metrics + /health 兜底),
    唔依赖「有冇成功读到进程 cmdline」。定时任务 (elevated) 启动嘅 llama-server,
    NLM 读唔到 cmdline, 但 /metrics /health 都 HTTP 200。
    - /metrics 200 → 正常采集, available=True
    - /metrics 抛异常/非 200 → 探 /health:
        * /health ok → 服务确实连着, 只是 /metrics 暂不可达 → available=True
          (唔会误报「服务未连接」)
        * /health 唔 ok → 服务真 down → 读上次快照标 stale
    """
    ns = SimpleNamespace(
        prompt_tokens=None, predicted_tokens=None,
        prompt_tps=None, predicted_tps=None,
        available=False, stale=False, stale_ts=None,
    )

    def _health_ok() -> bool:
        try:
            with httpx.Client(timeout=0.4, trust_env=False) as c:
                hr = c.get(f"http://127.0.0.1:{port}/health")
                if hr.status_code == 200 and hr.json().get("status") == "ok":
                    return True
        except Exception:
            pass
        return False

    try:
        with httpx.Client(timeout=0.4, trust_env=False) as c:
            r = c.get(f"http://127.0.0.1:{port}/metrics")
            if r.status_code != 200:
                # /metrics 不可用但服务可能仍连着 → 用 /health 判定
                if _health_ok():
                    ns.available = True
                return ns
            metrics = _parse_metrics(r.text)
            ns.prompt_tokens = int(
                metrics.get("llamacpp:prompt_tokens_total", 0)
                or metrics.get("llamacpp:prompt_tokens_processed_total", 0)
                or 0
            )
            ns.predicted_tokens = int(
                metrics.get("llamacpp:tokens_predicted_total", 0)
                or metrics.get("llamacpp:tokens_predicted_generated_total", 0)
                or 0
            )
            ns.prompt_tps = float(metrics.get("llamacpp:prompt_tokens_seconds", 0) or 0)
            ns.predicted_tps = float(metrics.get("llamacpp:predicted_tokens_seconds", 0) or 0)
            ns.available = True
            ns.stale = False
            ns.stale_ts = None
            # Quinn 16:11: 写盘以便后续关闭后能继续显示
            _save_token_state(ns)
    except Exception:
        # 连接失败 / 服务器未启 /metrics — 先探 /health 区分「服务连着」vs「真 down」
        if _health_ok():
            # 服务连着, 只是 /metrics 请求异常 → 视为已连接 (唔误报「服务未连接」)
            ns.available = True
            ns.stale = False
            ns.stale_ts = None
            return ns
        # 服务真 down → 尝试读上次的快照
        saved = _load_token_state()
        if saved:
            ns.prompt_tokens = saved.get("prompt_tokens")
            ns.predicted_tokens = saved.get("predicted_tokens")
            ns.prompt_tps = saved.get("prompt_tps")
            ns.predicted_tps = saved.get("predicted_tps")
            ns.available = False
            ns.stale = True
            ns.stale_ts = saved.get("ts")
    return ns


def get_token_stats(port: int = DEFAULT_PORT, use_cache: bool = True) -> SimpleNamespace:
    """读 llama-server /metrics 端点 (Quinn 14:00: 后台采集 + 主线程 0 阻塞).

    返回 SimpleNamespace(
        prompt_tokens,        # 输入 token 累积 (None 表示 /metrics 不可达)
        predicted_tokens,     # 输出 token 累积
        prompt_tps,           # 输入吞吐 (tokens/s, 全时均值)
        predicted_tps,        # 输出吞吐 (tokens/s, 全时均值)  ← 速度
        available,            # bool: 端点可用且 --metrics 已开
    )

    流程:
      - 后台线程已就绪: 即时读缓存
      - 后台未就绪 (启动早期): 同步 fallback (走 0.4s 短超时, 不会卡 2s)

    use_cache=False 时走同步路径, 仅供调试. 内部默认 True (强制使用缓存).
    """
    if use_cache:
        _ensure_llama_bg()
        with _LLAMA_BG_LOCK:
            cached = _LLAMA_BG.get("token_stats")
            ts = _LLAMA_BG.get("ts", 0.0)
        now = time.monotonic()
        if cached is not None and 0 < now - ts < _LLAMA_BG_STALE_LIMIT:
            return cached
        # 后台未就绪: 同步 fallback (0.4s 超时, 仍不卡)
        return _collect_token_stats_now(port)
    # use_cache=False: 同步直读 (调试用, 不推荐)
    return _collect_token_stats_now(port)


# ============================================================
# 启动方案 (Quinn 17:53 反馈: 启动控制改方案侧边栏)
# ============================================================

def list_schemes() -> list[dict]:
    """返回预设启动方案列表.

    每项:
        id, name, description, icon, extra_args (启动时附加参数)
        model (None 表示用当前选择)
    """
    # 内置 4 个常用方案. 未来可读取配置文件 ~/.llama_console_v2/schemes.yaml 扩展
    return [
        {
            "id": "default",
            "name": "默认",
            "description": "标准 Q8_0 + ctx 256K",
            "icon": "⚙",
            "extra_args": [],
        },
        {
            "id": "fast",
            "name": "快速",
            "description": "小 ctx + 高并发",
            "icon": "⚡",
            "extra_args": ["--ctx-size", "8192", "--parallel", "4", "--batch-size", "512"],
        },
        {
            "id": "long",
            "name": "长文",
            "description": "上下文最大",
            "icon": "📖",
            "extra_args": ["--ctx-size", "524288", "--no-warmup"],
        },
        {
            "id": "debug",
            "name": "调试",
            "description": "详细日志 + 流式",
            "icon": "🔍",
            "extra_args": ["--log-level", "debug", "--verbose"],
        },
    ]


def get_scheme(scheme_id: str) -> dict | None:
    for s in list_schemes():
        if s["id"] == scheme_id:
            return s
    return None


def start_with_scheme(scheme_id: str, model_path: str | None = None) -> dict:
    """按指定方案启动 llama-server (替换当前运行实例)."""
    scheme = get_scheme(scheme_id)
    if scheme is None:
        return {"ok": False, "pid": None, "error": f"unknown scheme: {scheme_id}"}
    # 方案启动前先停旧实例, 避免端口冲突
    stop()
    return start(model_path=model_path, extra_args=scheme["extra_args"])

