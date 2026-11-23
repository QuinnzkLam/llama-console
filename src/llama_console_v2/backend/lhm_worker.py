"""LHM 独立子进程 — 喺 GUI 进程外跑 pythonnet; 崩潰唔会杀死 GUI.

入口: __main__.py 见到 "--lhm-worker" 就调 run().
每 2s 写 JSON 到 %TEMP%/llamadeck_lhm.json (atomic .tmp → replace).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

JSON_PATH = Path(tempfile.gettempdir()) / "llamadeck_lhm.json"
_INTERVAL = 2.0
_FIELDS = (
    "cpu_temp", "cpu_power", "cpu_freq_lhm",
    "gpu0_hotspot", "gpu0_power", "gpu0_vram_temp",
    "gpu1_hotspot", "gpu1_power", "gpu1_vram_temp",
    "total_power",
)

_COMPUTER = None
_GPU_GROUPS: list[list] = []


def _dll_path() -> Path:
    from_meipass = Path(getattr(sys, "_MEIPASS", "")) / "LibreHardwareMonitorLib.dll"
    return from_meipass if from_meipass.is_file() else Path(r"D:\services\lhm\LibreHardwareMonitorLib.dll")


def _walk(hw):
    yield hw
    for sub in getattr(hw, "SubHardware", []) or []:
        yield from _walk(sub)


def _find(sensors, needles: tuple[str, ...], sensor_type: str | None = None):
    for s in sensors:
        name = (getattr(s, "Name", "") or "").lower()
        ident = str(getattr(s, "Identifier", "") or "").lower()
        stype = str(getattr(s, "SensorType", "")).split(".")[-1].lower()
        if sensor_type and sensor_type != stype:
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


def _open() -> None:
    global _COMPUTER, _GPU_GROUPS
    if _COMPUTER is not None:
        return
    import clr  # type: ignore
    clr.AddReference(str(_dll_path()))
    from LibreHardwareMonitor.Hardware import Computer  # type: ignore
    computer = Computer()
    computer.IsCpuEnabled = True
    computer.IsGpuEnabled = True
    computer.IsMemoryEnabled = True
    computer.IsMotherboardEnabled = True
    computer.Open()
    _COMPUTER = computer
    for hw in getattr(computer, "Hardware", []) or []:
        if "gpu" not in str(getattr(hw, "HardwareType", "")).split(".")[-1].lower():
            continue
        sensors: list = []
        for node in _walk(hw):
            sensors.extend(list(getattr(node, "Sensors", []) or []))
        _GPU_GROUPS.append(sensors)


def _collect() -> dict:
    all_sensors: list = []
    for hw in getattr(_COMPUTER, "Hardware", []) or []:
        for node in _walk(hw):
            all_sensors.extend(list(getattr(node, "Sensors", []) or []))

    def gpu(i: int, needles: tuple[str, ...], stype: str):
        return _find(_GPU_GROUPS[i], needles, stype) if i < len(_GPU_GROUPS) else None

    data = {
        "cpu_temp": _find(all_sensors, ("cpu package",), "temperature"),
        "cpu_power": _find(all_sensors, ("cpu package",), "power"),
        "cpu_freq_lhm": _find(all_sensors, ("core max", "clock"), "clock"),
        "gpu0_hotspot": gpu(0, ("hot spot", "hotspot"), "temperature"),
        "gpu0_power": gpu(0, ("gpu package",), "power"),
        "gpu0_vram_temp": gpu(0, ("memory junction", "memory temp"), "temperature"),
        "gpu1_hotspot": gpu(1, ("hot spot", "hotspot"), "temperature"),
        "gpu1_power": gpu(1, ("gpu package",), "power"),
        "gpu1_vram_temp": gpu(1, ("memory junction", "memory temp"), "temperature"),
    }
    powers = [data["cpu_power"], data["gpu0_power"], data["gpu1_power"]]
    data["total_power"] = sum(powers) if all(p is not None for p in powers) else None
    return data


def _write(data: dict) -> None:
    tmp = JSON_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, JSON_PATH)


def run() -> None:
    """无限采样循环; 任何未捕获异常会杀死本子进程, GUI 不受影响."""
    while True:
        try:
            _open()
            for hw in _COMPUTER.Hardware:
                hw.Update()
            _write(_collect())
        except Exception as exc:  # noqa: BLE001 — 写低错误状态, 下一轮重试
            _write({name: None for name in _FIELDS} | {"error": f"LHM worker: {exc}"})
        time.sleep(_INTERVAL)
