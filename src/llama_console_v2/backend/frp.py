"""v2 backend/frp.py - FRP tunnel 状态查询 (独立于 v1).

架构独立: 直接读 D:\\frp\\frpc.toml + psutil 检查 frpc.exe。

2026-08-31 (B1): 加 start_frpc() / stop_frpc() — GUI 启停 llama-server 时
同步启停 frpc tunnel, 避免按钮状态唔同步。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import psutil

DEFAULT_LLAMA_PORT = 18605
FRP_PROCESS_NAMES = ("frpc", "frpc.exe")
FRP_EXE_PATH = Path("D:/frp/frpc.exe")
FRP_CONFIG_PATH = Path("D:/frp/frpc.toml")
FRP_CWD = Path("D:/frp")

# Windows subprocess creationflags — DETACHED_PROCESS 脱离父进程控制
# (nlama.exe 关咗都唔会拉 frpc 陪葬), CREATE_NO_WINDOW 唔弹黑窗.
# Non-Windows 落空 (start_frpc 会照样 spawn, 但 macOS/Linux 无 frpc 业务场景).
if sys.platform == "win32":
    _FRP_CREATIONFLAGS = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NO_WINDOW", 0
    )
else:
    _FRP_CREATIONFLAGS = 0


def _is_frpc_running() -> bool:
    for p in psutil.process_iter(["name"]):
        try:
            pname = (p.info["name"] or "").lower()
            for target in FRP_PROCESS_NAMES:
                if pname == target.lower() or pname == target.lower() + ".exe":
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def _parse_proxy_for_port(path: Path, target_port: int) -> tuple[str, int | None, int | None, str | None]:
    """Parse TOML-like config to find proxy matching target local_port.
    Returns (tunnel_name, remote_port, local_port, server_addr).

    Quinn 16:11 (R12): top-level `serverAddr` 读取后保存为 `top_server_addr`,
    进入 [[proxies]] block 时从 `top_server_addr` 取, 避免 `cur_server = server_addr`
    (此时外层 server_addr 还是 None) 清掉 top-level 值.
    """
    tunnel_name = "-"
    remote_port: int | None = None
    local_port: int | None = None
    server_addr: str | None = None
    if not path.is_file():
        return tunnel_name, remote_port, local_port, server_addr

    in_proxies = False
    cur_name = "-"
    cur_local: int | None = None
    cur_remote: int | None = None
    cur_type: str | None = None
    # Quinn 16:11: 顶部 serverAddr 独立保存, proxy block 切换时从这里继承
    top_server_addr: str | None = None
    cur_server = top_server_addr

    def _flush() -> None:
        nonlocal tunnel_name, remote_port, local_port, server_addr
        if cur_local == target_port and cur_remote is not None:
            tunnel_name = cur_name
            remote_port = cur_remote
            local_port = cur_local
            server_addr = cur_server

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return tunnel_name, remote_port, local_port, server_addr

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[[") and line.endswith("]]"):
            # New proxy block
            if cur_local is not None:
                _flush()
            cur_name = line.strip("[]")
            cur_local = None
            cur_remote = None
            cur_type = None
            # Quinn 16:11: 顶部 serverAddr 继承, 不要清掉
            cur_server = top_server_addr
            in_proxies = True
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip().lower()
        v = v.strip().strip('"').strip("'")
        if k == "type":
            cur_type = v
        elif k == "localport":
            try: cur_local = int(v)
            except ValueError: pass
        elif k == "remoteport":
            try: cur_remote = int(v)
            except ValueError: pass
        elif k == "name":
            cur_name = v
        elif k == "serveraddr":
            # Quinn 16:11: 顶部 serverAddr 同时保存到 top_server_addr 和 cur_server
            top_server_addr = v
            cur_server = v
    if cur_local is not None:
        _flush()
    return tunnel_name, remote_port, local_port, server_addr


def get_frp_status(llama_port: int = DEFAULT_LLAMA_PORT) -> SimpleNamespace:
    """Return SimpleNamespace(connected, frpc_running, tunnel_name, remote_port,
    local_port, server_addr, public_url)."""
    frpc_running = _is_frpc_running()
    tunnel_name, remote_port, local_port, server_addr = _parse_proxy_for_port(FRP_CONFIG_PATH, llama_port)
    if tunnel_name == "-" and frpc_running:
        tunnel_name = "frpc"
    connected = frpc_running and remote_port is not None
    public_url = None
    if connected and server_addr and remote_port:
        public_url = f"http://{server_addr}:{remote_port}/v1"
    return SimpleNamespace(
        connected=connected,
        frpc_running=frpc_running,
        tunnel_name=tunnel_name,
        remote_port=remote_port,
        local_port=local_port if local_port else llama_port,
        server_addr=server_addr,
        public_url=public_url,
    )


def snapshot(llama_port: int = DEFAULT_LLAMA_PORT) -> SimpleNamespace:
    """Alias for get_frp_status() with 1.5s TTL cache (Quinn 09:00 性能优化)."""
    import time
    now = time.monotonic()
    cached = _SNAPSHOT_CACHE.get("frp")
    if cached and now - cached[0] < _SNAPSHOT_TTL:
        return cached[1]
    result = get_frp_status(llama_port)
    _SNAPSHOT_CACHE["frp"] = (now, result)
    return result


_SNAPSHOT_CACHE: dict[str, tuple[float, SimpleNamespace]] = {}
_SNAPSHOT_TTL = 1.5


# ============================================================
# 2026-08-31 (B1): FRP 启停 — 供 MainWindow 调, 让 GUI 启停 llama-server 时
# 同步起 / 收 frpc tunnel。 幂等 + 全错误捕获 (唔准 throw 出嚟 crash GUI)。
# ============================================================
def _find_frpc_pids() -> list[int]:
    """返所有 frpc.exe 嘅 pid. psutil.AccessDenied / NoSuchProcess 都吞."""
    pids: list[int] = []
    for p in psutil.process_iter(["name", "pid"]):
        try:
            pname = (p.info["name"] or "").lower()
            for target in FRP_PROCESS_NAMES:
                if pname == target.lower() or pname == target.lower() + ".exe":
                    pids.append(int(p.info["pid"]))
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return pids


def start_frpc() -> dict:
    """Start frpc.exe 喺 D:/frp (detached, 唔弹黑窗). 幂等.

    Returns: {"ok": bool, "already_running": bool, "pid": int|None,
              "error": str|None}
    错误全捕获, 唔 throw — caller 唔需要 try/except.
    """
    try:
        # 1. 幂等: 已经喺跑就直接返 (唔重新 spawn, 避免端口冲突)
        existing = _find_frpc_pids()
        if existing:
            return {"ok": True, "already_running": True, "pid": existing[0], "error": None}

        # 2. 前置检查
        if not FRP_EXE_PATH.is_file():
            return {"ok": False, "already_running": False, "pid": None,
                    "error": f"frpc.exe not found: {FRP_EXE_PATH}"}
        if not FRP_CONFIG_PATH.is_file():
            return {"ok": False, "already_running": False, "pid": None,
                    "error": f"frpc.toml not found: {FRP_CONFIG_PATH}"}

        # 3. Spawn (detached, no console window)
        proc = subprocess.Popen(
            [str(FRP_EXE_PATH), "-c", str(FRP_CONFIG_PATH)],
            cwd=str(FRP_CWD),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=_FRP_CREATIONFLAGS,
            close_fds=True,
        )
        return {"ok": True, "already_running": False, "pid": int(proc.pid), "error": None}
    except Exception as e:
        return {"ok": False, "already_running": False, "pid": None, "error": f"{type(e).__name__}: {e}"}


def stop_frpc() -> dict:
    """Stop 所有 frpc.exe 进程 (terminate -> 唔俾机会 grace period,
    frpc 本身就系短命 CLI 进程, 强制 kill 安全). 幂等: 冇 frpc 喺跑
    就返 ok=True, killed=[].

    Returns: {"ok": bool, "killed": list[int], "error": str|None}
    错误全捕获, 唔 throw.
    """
    killed: list[int] = []
    try:
        for p in psutil.process_iter(["name", "pid"]):
            try:
                pname = (p.info["name"] or "").lower()
                is_frpc = False
                for target in FRP_PROCESS_NAMES:
                    if pname == target.lower() or pname == target.lower() + ".exe":
                        is_frpc = True
                        break
                if not is_frpc:
                    continue
                pid = int(p.info["pid"])
                try:
                    p_obj = psutil.Process(pid)
                    p_obj.terminate()
                    killed.append(pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # 进程已经死咗 / 权限唔够 — 试下 psutil kill 作 fallback
                    try:
                        p_obj.kill()
                        killed.append(pid)
                    except Exception:
                        pass
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return {"ok": True, "killed": killed, "error": None}
    except Exception as e:
        return {"ok": False, "killed": killed, "error": f"{type(e).__name__}: {e}"}
