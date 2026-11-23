"""backend/lhm.py - GUI 侧只读 LHM 子进程写出嘅 JSON 缓存.

LHM (pythonnet + Ring0 driver) 喺独立子进程跑 (见 lhm_worker.py), 原生 crash
唔会杀死 GUI. 本模块唔 import clr, 唔直接碰 LibreHardwareMonitorLib.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

_JSON = Path(tempfile.gettempdir()) / "llamadeck_lhm.json"
_STALE_S = 10.0
_FIELDS = (
    "cpu_temp", "cpu_power", "cpu_freq_lhm",
    "gpu0_hotspot", "gpu0_power", "gpu0_vram_temp",
    "gpu1_hotspot", "gpu1_power", "gpu1_vram_temp",
    "total_power",
)
_PROC: subprocess.Popen | None = None
_LAST_ERROR: str | None = None


def _empty() -> SimpleNamespace:
    snap = SimpleNamespace(**{name: None for name in _FIELDS})
    snap.error = _LAST_ERROR
    return snap


def _spawn() -> None:
    global _PROC, _LAST_ERROR
    try:
        if getattr(sys, "frozen", False):
            args = [sys.executable, "--lhm-worker"]
        else:
            args = [sys.executable, "-m", "llama_console_v2", "--lhm-worker"]
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        _PROC = subprocess.Popen(args, **kwargs)
        _LAST_ERROR = "LHM worker 启动中…"
    except Exception as exc:  # noqa: BLE001
        _LAST_ERROR = f"LHM worker 启动失败: {exc}"


def lhm_snapshot() -> SimpleNamespace:
    """主线程即时读 JSON; 文件缺失/陈旧自动 respawn worker; 绝不 throw."""
    global _LAST_ERROR
    try:
        age = time.time() - _JSON.stat().st_mtime
        if age > _STALE_S:
            _LAST_ERROR = f"LHM 缓存陈旧 ({age:.0f}s)"
            if _PROC is None or _PROC.poll() is not None:
                _spawn()
            return _empty()
        data = json.loads(_JSON.read_text(encoding="utf-8"))
        snap = SimpleNamespace(**{name: data.get(name) for name in _FIELDS})
        snap.error = data.get("error")
        return snap
    except FileNotFoundError:
        _LAST_ERROR = "LHM worker 尚未产出数据"
        if _PROC is None or _PROC.poll() is not None:
            _spawn()
        return _empty()
    except Exception as exc:  # noqa: BLE001
        _LAST_ERROR = f"读取 LHM 缓存失败: {exc}"
        return _empty()
