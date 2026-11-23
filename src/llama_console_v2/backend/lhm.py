"""backend/lhm.py - LibreHardwareMonitor 传感器快照 (pythonnet, 2s 后台采样).

PoC 验证过: CPU Package / CPU Package Power / GPU Hot Spot / GPU Package Power /
GPU Memory Junction 全部有数. 唔依赖其他 backend 文件.
没有 clr / DLL 时全部字段返 None, GUI 显示「—」, 绝不 throw.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

try:
    import clr  # type: ignore
except Exception:  # noqa: BLE001 — Mac / 未装 pythonnet
    clr = None  # type: ignore

_DLL = r"D:\services\lhm\LibreHardwareMonitorLib.dll"
_COMPUTER = None
_GPU_GROUPS: list[list] = []
_LOCK = threading.Lock()
_CACHE: dict[str, object] = {"snap": None, "ts": 0.0}
_STARTED = False


def _empty() -> SimpleNamespace:
    names = (
        "cpu_temp", "cpu_power", "cpu_freq_lhm",
        "gpu0_hotspot", "gpu0_power", "gpu0_vram_temp",
        "gpu1_hotspot", "gpu1_power", "gpu1_vram_temp",
        "total_power",
    )
    return SimpleNamespace(**{n: None for n in names})


def _init_computer() -> bool:
    """开启 LHM Computer 一次 (module-level 单例)."""
    global _COMPUTER, _GPU_GROUPS
    if _COMPUTER is not None:
        return True
    if clr is None:
        return False
    import sys
    dll = Path(getattr(sys, "_MEIPASS", "")) / "LibreHardwareMonitorLib.dll"
    if not dll.is_file():
        dll = Path(_DLL)
    if not dll.is_file():
        return False
    clr.AddReference(str(dll))
    from LibreHardwareMonitor.Hardware import Computer  # type: ignore
    computer = Computer()
    computer.IsCpuEnabled = True
    computer.IsGpuEnabled = True
    computer.IsMemoryEnabled = True
    computer.IsMotherboardEnabled = True
    computer.Open()
    _COMPUTER = computer
    _GPU_GROUPS = []
    for hw in getattr(computer, "Hardware", []) or []:
        htype = str(getattr(hw, "HardwareType", "")).lower()
        if "gpu" not in htype:
            continue
        sensors: list = []
        for node in _walk(hw):
            sensors.extend(list(getattr(node, "Sensors", []) or []))
        _GPU_GROUPS.append(sensors)
    return True


def _walk(hw):
    yield hw
    for sub in getattr(hw, "SubHardware", []) or []:
        yield from _walk(sub)


def _find(sensors, needles: tuple[str, ...], sensor_type: str | None = None):
    for s in sensors:
        name = (getattr(s, "Name", "") or "").lower()
        ident = (getattr(s, "Identifier", "") or "").lower()
        if sensor_type and sensor_type not in str(getattr(s, "SensorType", "")).lower():
            continue
        if any(n in name or n in ident for n in needles):
            value = getattr(s, "Value", None)
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def _collect() -> SimpleNamespace:
    """调用 Update() 后读当前传感器值."""
    all_sensors: list = []
    for hw in getattr(_COMPUTER, "Hardware", []) or []:
        for node in _walk(hw):
            all_sensors.extend(list(getattr(node, "Sensors", []) or []))

    def gpu(i: int, needles: tuple[str, ...], stype: str):
        return _find(_GPU_GROUPS[i], needles, stype) if i < len(_GPU_GROUPS) else None

    snap = SimpleNamespace(
        cpu_temp=_find(all_sensors, ("cpu package",), "temperature"),
        cpu_power=_find(all_sensors, ("cpu package power",), "power"),
        cpu_freq_lhm=_find(all_sensors, ("core max", "clock"), "clock"),
        gpu0_hotspot=gpu(0, ("hot spot", "hotspot"), "temperature"),
        gpu0_power=gpu(0, ("package power", "gpu power"), "power"),
        gpu0_vram_temp=gpu(0, ("memory junction", "memory temp"), "temperature"),
        gpu1_hotspot=gpu(1, ("hot spot", "hotspot"), "temperature"),
        gpu1_power=gpu(1, ("package power", "gpu power"), "power"),
        gpu1_vram_temp=gpu(1, ("memory junction", "memory temp"), "temperature"),
    )
    powers = [snap.cpu_power, snap.gpu0_power, snap.gpu1_power]
    snap.total_power = sum(powers) if all(p is not None for p in powers) else None
    return snap


def _worker() -> None:
    while True:
        try:
            if _init_computer():
                # pythonnet binding: Computer 冇 Update(), Update 喺每個 Hardware 上
                for hw in _COMPUTER.Hardware:
                    hw.Update()
                with _LOCK:
                    _CACHE["snap"] = _collect()
                    _CACHE["ts"] = time.monotonic()
        except Exception:  # noqa: BLE001 — 单次采样失败唔杀死线程
            pass
        time.sleep(2.0)


def lhm_snapshot() -> SimpleNamespace:
    """主线程即时读缓存 (2s 后台采样), 无 LHM 时全部字段 None."""
    global _STARTED
    if not _STARTED and clr is not None:
        _STARTED = True
        threading.Thread(target=_worker, name="lhm-collector", daemon=True).start()
    with _LOCK:
        snap = _CACHE.get("snap")
    return snap if snap is not None else _empty()
