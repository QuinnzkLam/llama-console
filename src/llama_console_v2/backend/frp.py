"""v2 backend/frp.py - FRP tunnel 状态查询 (独立于 v1).

架构独立: 直接读 D:\\frp\\frpc.toml + psutil 检查 frpc.exe。
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import psutil

DEFAULT_LLAMA_PORT = 18605
FRP_PROCESS_NAMES = ("frpc", "frpc.exe")
FRP_CONFIG_PATH = Path("D:/frp/frpc.toml")


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
