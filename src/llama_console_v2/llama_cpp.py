"""v2 backend/llama_cpp.py - llama-server 进程/启动/停止 + version + update check.

架构独立: 唔依赖 v1 backend。直接用 psutil + httpx + subprocess + GitHub API。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import psutil

LLAMA_PROCESS_NAME = "llama-server.exe"
DEFAULT_PORT = 18605
DEFAULT_HOST = "0.0.0.0"
DEFAULT_CTX = 262144
GITHUB_API = "https://api.github.com/repos/ggerganov/llama.cpp/releases/latest"

# v2 local compiled binary location
_V2_BIN_DIR = Path("D:/llama-console/src/llama.cpp/build/bin/Release")
# v1 precompiled fallback (Quinn's existing setup)
_V1_FALLBACK = Path("D:/services/llama-server/llama-server.exe")
# v2 models dir
_MODELS_DIR = Path("D:/llama-console/models")

# Quinn 16:35: cache llama.cpp version to avoid every-refresh subprocess stall
_VERSION_CACHE: dict[str, float | str] = {"ts": 0.0, "value": ""}
_VERSION_TTL = 30.0   # seconds


# ============================================================
# Binary location + version
# ============================================================

def get_llama_server_exe() -> Path | None:
    """Priority: v2 local build > v1 precompiled fallback > None."""
    if os.name == "nt":
        candidates = [
            _V2_BIN_DIR / "llama-server.exe",
            _V1_FALLBACK,
        ]
    else:
        candidates = [_V2_BIN_DIR / "llama-server", _V1_FALLBACK.with_name("llama-server")]
    for c in candidates:
        if c.is_file():
            return c
    return None


def get_current_version() -> str:
    """Read built-in version string from llama-server binary."""
    exe = get_llama_server_exe()
    if exe is None:
        return "not built"
    try:
        result = subprocess.run(
            [str(exe), "--version"],
            capture_output=True, text=True, timeout=5,
        )
        out = (result.stdout + result.stderr).strip()
        m = re.search(r"version[:\s]+(\S+)", out, re.IGNORECASE)
        if m:
            return m.group(1)
        return out.splitlines()[0] if out else "unknown"
    except Exception:
        return "unknown"


def cached_current_version() -> str:
    """Return current llama.cpp version with 30s cache (avoid every-refresh stall)."""
    now = time.time()
    if now - float(_VERSION_CACHE["ts"]) < _VERSION_TTL:
        return str(_VERSION_CACHE["value"])
    v = get_current_version()
    _VERSION_CACHE["ts"] = now
    _VERSION_CACHE["value"] = v
    return v


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
    for p in psutil.process_iter(["name", "pid", "create_time"]):
        try:
            if p.info["name"] and p.info["name"].lower() == LLAMA_PROCESS_NAME.lower():
                return p
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def _format_uptime(sec: int) -> str:
    if sec <= 0:
        return "-"
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h}h {m:02d}m {s:02d}s"


def _get_model_info() -> tuple[str | None, str | None, int | None]:
    """Return (model_name, quant, ctx_size) by reading process cmdline."""
    proc = _find_process()
    if proc is None:
        return None, None, None
    try:
        cmdline = proc.cmdline()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return None, None, None
    model = None
    quant = None
    ctx = None
    for i, arg in enumerate(cmdline):
        if arg == "-m" and i + 1 < len(cmdline):
            model = Path(cmdline[i + 1]).name
        elif arg == "--port" and i + 1 < len(cmdline):
            try: ctx = int(cmdline[i + 1])
            except ValueError: pass
    if model and "-" in model:
        # Detect quant from filename like "Qwen3.8-27B-Q8_0.gguf"
        m = re.search(r"-(Q\d+_\d+|[Ff]\d+|[Kk]\-[Ss]+|[Ii]Q\d+_[A-Z]+)", model)
        if m:
            quant = m.group(1)
    return model, quant, ctx


def get_status() -> SimpleNamespace:
    """Return SimpleNamespace(state, model_name, quant, ctx_size, port, pid, uptime, bind, public_url, local_url, llama_cpp_version)."""
    proc = _find_process()
    port = DEFAULT_PORT
    if proc is None:
        return SimpleNamespace(
            state="stopped", model_name=None, quant=None, ctx_size=None,
            port=port, pid=None, uptime="-", bind=f"{DEFAULT_HOST}:{port}",
            public_url=None, local_url=None,
            llama_cpp_version=cached_current_version(),
        )
    try:
        uptime_sec = int(time.time() - proc.create_time)
    except Exception:
        uptime_sec = 0
    model, quant, ctx = _get_model_info()
    # Probe /health to determine running vs loading
    state = "loading"
    try:
        with httpx.Client(timeout=2.0) as c:
            r = c.get(f"http://127.0.0.1:{port}/health")
            if r.status_code == 200 and r.json().get("status") == "ok":
                state = "running"
    except Exception:
        pass
    return SimpleNamespace(
        state=state, model_name=model, quant=quant, ctx_size=ctx,
        port=port, pid=proc.pid, uptime=_format_uptime(uptime_sec),
        bind=f"{DEFAULT_HOST}:{port}",
        public_url=f"http://frp.example.com:{port}/v1",  # populated by frp.snapshot()
        local_url=f"http://127.0.0.1:{port}",
        llama_cpp_version=cached_current_version(),
    )


def snapshot() -> SimpleNamespace:
    """Alias for get_status() — v2 console.py uses snapshot()."""
    return get_status()


# ============================================================
# Start / Stop
# ============================================================

def start(model_path: str | None = None, port: int = DEFAULT_PORT,
          host: str = DEFAULT_HOST, ctx_size: int = DEFAULT_CTX,
          ngl: int = 99, extra_args: list[str] | None = None) -> dict:
    """Start llama-server via Popen. Returns {ok, pid, error}."""
    exe = get_llama_server_exe()
    if exe is None:
        return {"ok": False, "pid": None, "error": "llama-server.exe not found"}
    if model_path is None:
        models = list(_MODELS_DIR.rglob("*.gguf"))
        main = [m for m in models if "mmproj" not in m.name.lower()]
        if not main:
            return {"ok": False, "pid": None, "error": "no main model .gguf in models/"}
        model_path = str(main[0])
    args = [str(exe), "-m", model_path, "--port", str(port), "--host", host,
            "-c", str(ctx_size), "-ngl", str(ngl)]
    model_dir = Path(model_path).parent
    mmprojs = list(model_dir.glob("mmproj*.gguf"))
    if mmprojs:
        args.extend(["--mmproj", str(mmprojs[0])])
    if extra_args:
        args.extend(extra_args)
    try:
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW
            proc = subprocess.Popen(args, cwd=str(model_dir),
                                    creationflags=creationflags,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            proc = subprocess.Popen(args, cwd=str(model_dir),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    start_new_session=True)
        return {"ok": True, "pid": proc.pid, "error": None, "exe": str(exe)}
    except Exception as e:
        return {"ok": False, "pid": None, "error": str(e)}


def stop() -> dict:
    """Stop all llama-server processes. Returns {ok, killed, error}."""
    killed = []
    try:
        if os.name == "nt":
            result = subprocess.run(["taskkill", "/F", "/IM", LLAMA_PROCESS_NAME],
                                    capture_output=True, text=True, timeout=10)
            killed = [LLAMA_PROCESS_NAME] if result.returncode == 0 else []
        else:
            result = subprocess.run(["pkill", "-f", "llama-server"], capture_output=True, text=True, timeout=10)
            killed = [LLAMA_PROCESS_NAME] if result.returncode == 0 else []
        return {"ok": True, "killed": killed, "error": None}
    except Exception as e:
        return {"ok": False, "killed": killed, "error": str(e)}


# ============================================================
# Settings page API (called by pages/settings.py)
# ============================================================

_CMDLINE_FILE = Path("D:/llama-console/cmdline_args.txt")
_DEFAULT_CMDLINE = [
    "-ngl 99",
    "-c 262144",
    "--temp 0.6",
    "--top-p 0.95",
    "--top-k 20",
    "--repeat-penalty 1.1",
]


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
    """Return full path of currently selected main model (or None)."""
    models = list_models()
    if not models:
        return None
    # Default = first one (matches _load_models)
    return str(_MODELS_DIR / models[0])


def current_cmdline_args() -> list[str]:
    """Return currently persisted cmdline args (one per line)."""
    if not _CMDLINE_FILE.is_file():
        return list(_DEFAULT_CMDLINE)
    try:
        text = _CMDLINE_FILE.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return list(_DEFAULT_CMDLINE)
    args = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return args or list(_DEFAULT_CMDLINE)


def save_cmdline_args(args: list[str]) -> None:
    """Persist cmdline args to disk."""
    _CMDLINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CMDLINE_FILE.write_text("\n".join(args) + "\n", encoding="utf-8")


def default_cmdline_args() -> list[str]:
    """Return factory default cmdline args (reset)."""
    return list(_DEFAULT_CMDLINE)


def get_version() -> str:
    """Alias for get_current_version() — v2 settings.py uses get_version()."""
    return get_current_version()


def check_latest_version() -> str:
    """Return latest GitHub release tag (or empty on error)."""
    rel = get_latest_github_release()
    return rel.get("version", "") if rel.get("ok") else ""

