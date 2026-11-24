"""v2 backend/hardware.py - WMI/psutil/nvidia-smi 汇总, snapshot() 返回 namespace.

架构独立: 唔依赖 v1 backend。直接 call psutil / WMI / nvidia-smi。

Quinn 09:30 (第四轮):
- CPU 实时频率改用 win32pdh 性能计数器 (% Processor Performance * MaxClockSpeed),
  取代会卡在基础频率的 psutil.cpu_freq + WMI CurrentClockSpeed
- GPU 数据采集增加 Win32_VideoController 兜底 (集成显卡/老 N 卡) + 空态标识

Quinn 10:15 (第五轮): 修复刷新卡顿
- 原 1.5s TTL 缓存方案下, refresh(10s) > TTL(1.5s) 导致每次 refresh 都是冷采集
  (nvidia-smi subprocess 241ms + WMI 88ms + COM 初始化 ≈ 1.2s), 主线程周期性阻塞.
- 改为后台 daemon 线程每 2s 采集并写缓存, 主线程 snapshot() 即时读缓存, 采集耗时不再阻塞 UI.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
import time
from types import SimpleNamespace
from typing import Any

import psutil


# nvidia-smi 优先 PATH, fallback D:\\Program Files\\NVIDIA Corporation\\NVSMI
_NV_SMI = "D:\\Program Files\\NVIDIA Corporation\\NVSMI\\nvidia-smi.exe"
# Quinn 14:40: 核弹机实际无 nvidia-smi, 多尝试几条路径
_NV_SMI_ALT = [
    "C:\\Program Files\\NVIDIA Corporation\\NVSMI\\nvidia-smi.exe",
    "C:\\Windows\\System32\\nvidia-smi.exe",
]


def _wmi_query(query: str) -> list[dict[str, Any]]:
    """WMI query via win32com (fallback: wmic command)."""
    try:
        import win32com.client  # type: ignore
        wmi = win32com.client.GetObject("winmgmts:")
        result = wmi.ExecQuery(query)
        return [{prop.Name: prop.Value for prop in r.Properties_} for r in result]
    except Exception:
        return []


def _get_cpu_model() -> str | None:
    rows = _wmi_query("SELECT Name FROM Win32_Processor")
    return rows[0]["Name"].strip() if rows else None


def _get_cpu_clock_mhz() -> int:
    """Return live CPU clock speed in MHz (WMI Win32_Processor.CurrentClockSpeed).

    Quinn 09:00 反馈: 除 psutil.cpu_freq() 外增加 WMI 来源, 覆盖更多机器
    Quinn 09:30: WMI CurrentClockSpeed 在 Windows 上经常返回标称频率而非实时.
    实际可用的实时频率改用 win32pdh 性能计数器, 见 _get_cpu_live_mhz_pdh()
    """
    rows = _wmi_query("SELECT CurrentClockSpeed FROM Win32_Processor")
    if rows:
        try:
            mhz = int(rows[0].get("CurrentClockSpeed") or 0)
            if mhz > 0:
                return mhz
        except (ValueError, TypeError):
            pass
    return 0


# ============================================================
# Quinn 09:30: 实时 CPU 频率 = MaxClockSpeed × (% Processor Performance / 100)
# 用 win32pdh 性能计数器采样, 真正反映 CPU 升降频 (boost / idle)
# ============================================================
_PDH_HANDLE: dict[str, Any] = {"query": None, "counter": None, "last_perf": None, "last_ts": 0.0}
_PDH_LOCK = threading.Lock()


def _get_cpu_live_mhz_pdh(max_mhz: int) -> int:
    """Return live CPU clock in MHz via win32pdh.

    perf counter: \\Processor Information(_Total)\\% Processor Performance
    该计数器值 = 当前频率 / 基础频率 × 100.  乘 max_mhz 得实时 MHz.
    限制: 1) 需 1s 间隔采样 (PDH 内部需要时间累计); 2) max_mhz 必须 > 0.
    """
    if max_mhz <= 0:
        return 0
    try:
        import win32pdh  # type: ignore
    except Exception:
        return 0

    with _PDH_LOCK:
        try:
            if _PDH_HANDLE["query"] is None:
                hq = win32pdh.OpenQuery()
                hco = win32pdh.AddCounter(
                    hq, r"\Processor Information(_Total)\% Processor Performance"
                )
                _PDH_HANDLE["query"] = hq
                _PDH_HANDLE["counter"] = hco
            hq = _PDH_HANDLE["query"]
            hco = _PDH_HANDLE["counter"]
            win32pdh.CollectQueryData(hq)
            now = time.monotonic()
            last_ts = _PDH_HANDLE["last_ts"]
            if now - last_ts < 0.9:  # 至少 1s 一次 (PDH 数据需要 2 次 sample)
                # 返回上次缓存值
                cached = _PDH_HANDLE["last_perf"]
                if cached is not None:
                    return int(max_mhz * cached / 100.0)
                return 0
            win32pdh.CollectQueryData(hq)
            raw = win32pdh.GetFormattedCounterValue(hco, win32pdh.PDH_FMT_LONG)
            perf = int(raw[1])
            _PDH_HANDLE["last_perf"] = perf
            _PDH_HANDLE["last_ts"] = now
            return int(max_mhz * perf / 100.0)
        except Exception:
            return 0


# ==== Quinn 2026-11-23: PDH 直接频率计数器 (Processor Frequency), 直接返 MHz ====
# 唔使乘 WMI MaxClockSpeed (部分机只返标称基频 → 基准错); 模式复制自 _get_cpu_live_mhz_pdh.
_PDH_FREQ_HANDLE: dict[str, Any] = {"query": None, "counter": None, "last_mhz": None, "last_ts": 0.0}
_PDH_FREQ_LOCK = threading.Lock()


def _get_cpu_live_mhz_pdh_freq() -> int:
    """Return live CPU clock in MHz via PDH direct frequency counter.

    counter: \\Processor Information(_Total)\\Processor Frequency
    该计数器直接返回 MHz, 不依赖 WMI MaxClockSpeed 基准 (部分机器只返回标称基频).
    限制: 需 1s 间隔采样 (PDH 内部需要 2 次 sample 先有值).
    """
    try:
        import win32pdh  # type: ignore
    except Exception:
        return 0

    with _PDH_FREQ_LOCK:
        try:
            if _PDH_FREQ_HANDLE["query"] is None:
                hq = win32pdh.OpenQuery()
                hco = win32pdh.AddCounter(
                    hq, r"\Processor Information(_Total)\Processor Frequency"
                )
                _PDH_FREQ_HANDLE["query"] = hq
                _PDH_FREQ_HANDLE["counter"] = hco
            hq = _PDH_FREQ_HANDLE["query"]
            hco = _PDH_FREQ_HANDLE["counter"]
            win32pdh.CollectQueryData(hq)
            now = time.monotonic()
            last_ts = _PDH_FREQ_HANDLE["last_ts"]
            if now - last_ts < 0.9:  # 至少 1s 一次 (PDH 数据需要 2 次 sample)
                cached = _PDH_FREQ_HANDLE["last_mhz"]
                return int(cached) if cached is not None else 0
            win32pdh.CollectQueryData(hq)
            raw = win32pdh.GetFormattedCounterValue(hco, win32pdh.PDH_FMT_LONG)
            mhz = int(raw[1])
            _PDH_FREQ_HANDLE["last_mhz"] = mhz
            _PDH_FREQ_HANDLE["last_ts"] = now
            return mhz
        except Exception:
            return 0


def _get_cpu_max_mhz() -> int:
    """Return CPU max clock speed in MHz (WMI Win32_Processor.MaxClockSpeed)."""
    rows = _wmi_query("SELECT MaxClockSpeed FROM Win32_Processor")
    if rows:
        try:
            mhz = int(rows[0].get("MaxClockSpeed") or 0)
            return mhz
        except (ValueError, TypeError):
            pass
    return 0


def _get_cpu_cache_mb() -> str:
    """Return 'L2 / L3' cache sizes in MB.

    Quinn 09:00: WMI Win32_CacheMemory 拿 L2/L3 大小
    注: CacheType=5=Unified, 真正区分靠 Level 字段 (1=L1, 2=L1d, 3=L2?, 4=L3?, 5=L4?)
    实测 AMD: Level=3→512KB L1, Level=4→4MB L2, Level=5→16MB L3
    Intel/AMD 通用: Level=3→L1, Level=4→L2, Level=5→L3 (本机器实测)
    """
    try:
        rows = _wmi_query(
            "SELECT CacheType, InstalledSize, Level FROM Win32_CacheMemory"
        )
        l1_kb = l2_kb = l3_kb = 0
        for r in rows:
            sz_kb = int(r.get("InstalledSize") or 0)
            level = int(r.get("Level") or 0)
            if level == 3:
                l1_kb = max(l1_kb, sz_kb)
            elif level == 4:
                l2_kb = max(l2_kb, sz_kb)
            elif level == 5:
                l3_kb = max(l3_kb, sz_kb)
        parts = []
        if l1_kb:
            parts.append(f"L1 {l1_kb}KB" if l1_kb < 1024 else f"L1 {l1_kb//1024}MB")
        if l2_kb:
            parts.append(f"L2 {l2_kb}KB" if l2_kb < 1024 else f"L2 {l2_kb//1024}MB")
        if l3_kb:
            parts.append(f"L3 {l3_kb}KB" if l3_kb < 1024 else f"L3 {l3_kb//1024}MB")
        return " · ".join(parts) if parts else ""
    except Exception:
        return ""


def _get_cpu_breakdown() -> dict[str, float] | None:
    """CPU 利用率细分 (user/system/idle/iowait/irq/softirq/nice), 百分比.

    Quinn 09:00: 在总利用率之外显示细分, 排查系统是否 IO bound / 中断密集
    返回 None 表示不支持 (Windows 下 psutil 的 cpu_times_percent 实现近似)
    """
    try:
        times = psutil.cpu_times_percent(interval=0.0, percpu=False)
    except Exception:
        return None
    # Windows: user/system/idle 可能 + interrupt/dpc (Win10+)
    parts = {
        "user":    getattr(times, "user", 0.0),
        "system":  getattr(times, "system", 0.0),
        "iowait":  getattr(times, "iowait", 0.0),
        "irq":     getattr(times, "interrupt", 0.0),
        "softirq": getattr(times, "dpc", 0.0),
    }
    return parts


def _get_cpu_temp() -> float | None:
    """CPU 温度多源采集 (Quinn 17:53 反馈: UI 显 "温度 -", 检查数据采集)

    顺序:
    1. root\\wmi::MSAcpi_ThermalZoneTemperature (Dell/HP 商务机常见)
    2. CIM_GenericSensor / MSAcpi default 命名空间 (UltraBook/部分 OEM)
    3. LibreHardwareMonitor / OpenHardwareMonitor 第三方 sensor 服务
       (需用户安装 LHM/OHM, 暴露 CPU Package/CPU Core 温度)
    4. Win32_TemperatureProbe (极少见 OEM)
    5. Win32_PerfFormattedData_Counters_ThermalZoneInformation

    全部失败 -> None (UI 显"未检测到温度传感器")
    """
    # ---- 1) root\wmi::MSAcpi_ThermalZoneTemperature ----
    try:
        import win32com.client  # type: ignore
        wmi = win32com.client.GetObject(r"winmgmts:root\wmi")
        # 先尝试精筛 CurrentTemperature
        for r in wmi.ExecQuery("SELECT CurrentTemperature FROM MSAcpi_ThermalZoneTemperature"):
            t_raw = getattr(r, "CurrentTemperature", None)
            if t_raw and t_raw > 0:
                return round((t_raw / 10.0) - 273.15, 1)
    except Exception:
        pass

    # ---- 2) 默认命名空间的 MSAcpi (部分 OEM) ----
    try:
        import win32com.client  # type: ignore
        wmi = win32com.client.GetObject("winmgmts:")
        for r in wmi.ExecQuery("SELECT CurrentTemperature FROM MSAcpi_ThermalZoneTemperature"):
            t_raw = getattr(r, "CurrentTemperature", None)
            if t_raw and t_raw > 0:
                return round((t_raw / 10.0) - 273.15, 1)
    except Exception:
        pass

    # ---- 3) LibreHardwareMonitor / OpenHardwareMonitor (第三方 sensor 服务) ----
    #   Sensor.Identifier 形如 "/amdcpu/0", Sensor.SensorType == "Temperature"
    #   Sensor.Value 就是摄氏度
    for ns in ("root\\LibreHardwareMonitor", "root\\OpenHardwareMonitor"):
        try:
            import win32com.client  # type: ignore
            wmi = win32com.client.GetObject(f"winmgmts:{ns}")
            # 取所有 Temperature 传感器, 优先 CPU Package/CPU Core
            best: tuple[int, float] | None = None  # (priority, value)
            for s in wmi.ExecQuery(
                "SELECT Name, Value, SensorType FROM Sensor WHERE SensorType='Temperature'"
            ):
                name = str(getattr(s, "Name", "")) or ""
                val = float(getattr(s, "Value", 0) or 0)
                if val <= -100 or val > 150:
                    # 明显不是 CPU 温度 (可能是电压/风扇)
                    continue
                ln = name.lower()
                priority = 99
                if "cpu package" in ln or "package" in ln:
                    priority = 0
                elif "cpu" in ln and "core" in ln:
                    priority = 1
                elif ln.startswith("cpu"):
                    priority = 2
                elif "gpu" in ln:
                    priority = 50
                else:
                    continue  # 跳过主板/水冷/风扇等
                if best is None or priority < best[0]:
                    best = (priority, val)
            if best is not None:
                return round(best[1], 1)
        except Exception:
            continue

    # ---- 4) Win32_TemperatureProbe (极少 OEM 用) ----
    try:
        for r in _wmi_query("SELECT CurrentReading FROM Win32_TemperatureProbe"):
            v = r.get("CurrentReading")
            if v and 0 < v < 200:
                # Win32_TemperatureProbe.CurrentReading 单位同样是 Kelvin*10
                return round((v / 10.0) - 273.15, 1)
    except Exception:
        pass

    # 全部失败
    return None


def _get_ram_info() -> dict[str, Any]:
    """Return {type, capacity_mb, frequency_mhz, manufacturer, part_number}."""
    rows = _wmi_query("SELECT MemoryType, SMBIOSMemoryType, Capacity, Speed, Manufacturer, PartNumber FROM Win32_PhysicalMemory")
    if not rows:
        return {"type": None, "capacity_mb": 0, "frequency_mhz": None, "manufacturer": None, "part_number": None}
    smbios_type_map = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 30: "DDR5", 34: "DDR5", 35: "DDR5", 36: "DDR5"}
    ddr_type_map = {17: "DDR", 20: "DDR2", 21: "DDR2 FB-DIMM", 24: "DDR3", 26: "DDR4", 30: "DDR5", 34: "DDR5"}
    # Sum capacity across ALL sticks (was only first stick)
    cap_bytes = sum(int(r.get("Capacity", 0) or 0) for r in rows)
    cap_mb = cap_bytes // (1024 * 1024)
    r0 = rows[0]
    smbios_t = r0.get("SMBIOSMemoryType") or 0
    mem_t = r0.get("MemoryType") or 0
    # Quinn 14:40: 优先 SMBIOSMemoryType (有返 34=DDR5), fallback MemoryType
    if smbios_t and smbios_t in smbios_type_map:
        mem_type_str = smbios_type_map[smbios_t]
    elif mem_t and mem_t in ddr_type_map:
        mem_type_str = ddr_type_map[mem_t]
    else:
        # 频率 ≥ 4800 → DDR5 经验法则
        speed = int(r0.get("Speed", 0) or 0)
        mem_type_str = "DDR5" if speed >= 4800 else "DDR4" if speed >= 2133 else "Unknown"
    return {
        "type": mem_type_str,
        "capacity_mb": cap_mb,
        "frequency_mhz": int(r0.get("Speed", 0) or 0) or None,
        "manufacturer": r0.get("Manufacturer"),
        "part_number": r0.get("PartNumber"),
    }


def _get_gpus() -> list[dict[str, Any]]:
    # Quinn 14:40: 核弹机 nvidia-smi 路径可能喺多处, 都 try
    import os
    candidates = []
    p = shutil.which("nvidia-smi")
    if p: candidates.append(p)
    if os.path.isfile(_NV_SMI): candidates.append(_NV_SMI)
    for alt in _NV_SMI_ALT:
        if os.path.isfile(alt): candidates.append(alt)
    if not candidates:
        return []
    try:
        # Quinn 09:00 (第二轮): 加 temperature.memory 字段拿 VRAM 显存温度
        # Worker 2026-08-28 17:59: 加 creationflags=CREATE_NO_WINDOW，避免后台采集线程
        #   每 2s spawn nvidia-smi 时弹出黑底白字 console 窗口（与 llama_cpp.py 约定一致）。
        kwargs = dict(capture_output=True, text=True, timeout=5)
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(
            [candidates[0],
             "--query-gpu=index,name,memory.total,memory.used,utilization.gpu,"
             "temperature.gpu,temperature.memory",
             "--format=csv,noheader,nounits"],
            **kwargs,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
    except Exception:
        return []
    # Quinn 09:30: 模拟 nvidia-smi 字段常见 N/A 占位 (老驱动/不支持的字段)
    #   e.g. RTX 3070 的 temperature.memory 实际输出 "N/A" (不是 [Not Supported])
    #   之前只过滤 "[Not Supported]"/"" -> int("N/A") 抛 ValueError -> 整行被 except skip
    #   损失所有 GPU 数据. 这里收紧容错, 并改用字段级 try, 避免一处失败拖垮整行.
    _NA_TOKENS = frozenset({
        "[Not Supported]", "Not Supported",
        "N/A", "[N/A]", "n/a", "NA",
        "-", "null", "None", "?",
    })

    def _safe_int(s: str) -> int | None:
        """nvidia-smi 单元 -> int. 无效/不支持 -> None (不抛异常)."""
        if s is None:
            return None
        s = s.strip()
        if not s or s in _NA_TOKENS:
            return None
        try:
            return int(s)
        except (ValueError, TypeError):
            return None

    gpus: list[dict[str, Any]] = []
    for line in result.stdout.strip().splitlines():
        # index, name, total, used, gpu_util, temp_gpu, temp_memory  (7 columns)
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 7:
            continue
        # 字段级独立解析: 任一字段失败不影响其余字段入库
        idx       = _safe_int(parts[0])
        vram_tot  = _safe_int(parts[2])
        vram_used = _safe_int(parts[3])
        gpu_util  = _safe_int(parts[4])
        temp_gpu  = _safe_int(parts[5])
        temp_mem  = _safe_int(parts[6])
        if idx is None or vram_tot is None:
            continue  # 关键字段缺失, 这行确实无效
        # Quinn 17:30: 修复 VRAM 百分比算法 - 100% ≠ 用满显存
        # 改用已用/总量比例, 与任务管理器 / nvidia-smi memory 栏一致.
        vram_pct = (
            round(vram_used / vram_tot * 100)
            if (vram_used is not None and vram_tot > 0) else 0
        )
        gpus.append({
            "index": idx,
            "name": parts[1] or f"GPU{idx}",
            "vram_total_mb": vram_tot,
            "vram_used_mb": vram_used,
            "util_percent": gpu_util if gpu_util is not None else 0,
            # 仍然保留字段名 (UI 仍用 vram_util_percent 渲染进度条)
            "vram_util_percent": vram_pct,
            "temp_c": temp_gpu,
            # Quinn 09:00 (第二轮): VRAM 显存温度 (部分 GPU 报 [Not Supported])
            "vram_temp_c": temp_mem,
            # Quinn 09:30: 标记数据源
            "source": "nvidia-smi",
        })
    return gpus


def _get_gpus_wmi() -> list[dict[str, Any]]:
    """WMI Win32_VideoController 兜底: 集成显卡 / 老 N 卡 / 无 nvidia-smi 时仍能拿到基础信息.

    返回字段与 nvidia-smi 对齐 (但缺温度/利用率, 用 None 占位).
    Quinn 09:30: 主要用于在没 nvidia-smi 的机器显示 GPU 名称 + 驱动版本.

    过滤规则: 跳过虚拟显示适配器 (ToDesk / GameViewer / Parsec 等远程工具),
    跳过 "Microsoft Basic Display Adapter" 占位设备.
    """
    rows = _wmi_query(
        "SELECT Name, DriverVersion, AdapterRAM, VideoProcessor "
        "FROM Win32_VideoController"
    )
    # 虚拟/占位设备的特征关键字 (远程工具, 兼容显示, 系统占位)
    _SKIP_KEYWORDS = (
        "virtual", "todesk", "gameviewer", "parsec", "anydesk",
        "teamviewer", "basic display", "microsoft basic", "remote",
    )
    out: list[dict[str, Any]] = []
    real_idx = 0  # 过滤后重新编号, 避免显示"GPU 2/4 是虚拟的"
    for r in rows:
        name = r.get("Name") or "Unknown"
        ln = name.lower()
        if not name or any(kw in ln for kw in _SKIP_KEYWORDS):
            continue  # 跳过虚拟/远程/基本显示适配器
        vram_bytes = r.get("AdapterRAM") or 0
        # 注意: WMI AdapterRAM 32-bit 有 4GB 上限, 大显存会溢出 (变负数). 这里仅粗略展示
        vram_total_mb = int(vram_bytes) // (1024 * 1024) if vram_bytes > 0 else 0
        out.append({
            "index": real_idx,
            "name": name,
            "vram_total_mb": vram_total_mb,
            "vram_used_mb": None,
            "util_percent": None,
            "vram_util_percent": None,
            "temp_c": None,
            "vram_temp_c": None,
            "source": "wmi",
            "driver_version": r.get("DriverVersion") or "",
            "video_processor": r.get("VideoProcessor") or "",
        })
        real_idx += 1
    return out


def _get_gpus_combined() -> list[dict[str, Any]]:
    """GPU 数据合并: 优先 nvidia-smi, fallback WMI VideoController.

    Quinn 09:30: 原机器 (AMD 5900HS + Radeon) 走 WMI 路径, 显集成显卡基础信息.
    纯无显卡机器返回空, UI 显示"未检测到 GPU".
    """
    nvidia = _get_gpus()
    if nvidia:
        return nvidia
    return _get_gpus_wmi()


def _get_cpu() -> SimpleNamespace:
    """CPU snapshot (Quinn 09:00 三轮: 加 WMI 实时频率 + 缓存 + 细分利用率)

    Quinn 09:30 (第四轮): live_mhz 改用 win32pdh 性能计数器 (% Processor Performance * MaxClockSpeed),
    真正反映 boost / idle 实时频率. fallback: psutil + WMI CurrentClockSpeed.

    性能: 调用方需自行加 TTL 缓存 (console 5s/10s 刷新本身已是节流)
    """
    pct = psutil.cpu_percent(interval=0.0)
    max_mhz = _get_cpu_max_mhz()
    # 优先 PDH 直接频率, 再 PDH % Processor Performance × max_mhz, 最后 psutil + WMI
    pdh_freq_mhz = _get_cpu_live_mhz_pdh_freq()
    pdh_mhz = _get_cpu_live_mhz_pdh(max_mhz)
    if pdh_freq_mhz > 0:
        live_mhz = pdh_freq_mhz
    elif pdh_mhz > 0:
        live_mhz = pdh_mhz
    else:
        freq = psutil.cpu_freq()
        psutil_mhz = int(freq.current) if freq else 0
        wmi_mhz = _get_cpu_clock_mhz()
        live_mhz = max(psutil_mhz, wmi_mhz) if (psutil_mhz or wmi_mhz) else 0
    return SimpleNamespace(
        model=_get_cpu_model() or "Unknown",
        cores_physical=psutil.cpu_count(logical=False) or 0,
        cores_logical=psutil.cpu_count(logical=True) or 0,
        freq_mhz=live_mhz,
        max_mhz=max_mhz,
        cache_text=_get_cpu_cache_mb(),  # Quinn 09:30: UI 暂不展示, 保留供 debug
        util_breakdown=_get_cpu_breakdown(),  # 同上
        util_percent=float(pct),
        temp_c=_get_cpu_temp(),
        # Quinn 09:30: 标记频率是否真动态
        freq_source=(
            "pdh_freq" if pdh_freq_mhz > 0
            else "pdh" if pdh_mhz > 0
            else "static"
        ),
    )


def _get_ram() -> SimpleNamespace:
    v = psutil.virtual_memory()
    info = _get_ram_info()
    return SimpleNamespace(
        type=info["type"] or "Unknown",
        capacity_gb=info["capacity_mb"] / 1024.0,
        used_gb=v.used / (1024 ** 3),
        util_percent=float(v.percent),
        freq_mhz=info["frequency_mhz"],
    )


def _get_gpus_ns() -> list[SimpleNamespace]:
    """Quinn 09:30: 合并 nvidia-smi + WMI VideoController, 标记数据源."""
    return [
        SimpleNamespace(
            model=g["name"],
            vram_total_mb=g["vram_total_mb"],
            vram_used_mb=g.get("vram_used_mb"),
            util_percent=g.get("util_percent"),
            vram_util_percent=g.get("vram_util_percent"),
            temp_c=g.get("temp_c"),
            # Quinn 09:00 (第二轮): VRAM 显存温度 (nvidia-smi temperature.memory)
            vram_temp_c=g.get("vram_temp_c"),
            # Quinn 09:30: 数据源 ("nvidia-smi" / "wmi"), 供 UI 决定是否显示进度条
            source=g.get("source", "unknown"),
            driver_version=g.get("driver_version", ""),
            video_processor=g.get("video_processor", ""),
        )
        for g in _get_gpus_combined()
    ]


# ============================================================
# 顶层 snapshot — 后台线程采集, 主线程只读缓存 (Quinn 10:15 第五轮修复卡顿)
#
# 原 1.5s TTL 方案的问题: refresh 间隔 10s > 缓存 TTL 1.5s,
#   每次 refresh 都是冷采集 -> nvidia-smi subprocess(241ms) + WMI(88ms) + COM 初始化
#   -> 主线程每次阻塞 ~1.2s, 表现为周期性卡顿.
# 新方案: 专门的后台 daemon 线程每 2s 采集一次并写入缓存; 主线程 snapshot() 即时读缓存,
#   彻底解耦数据采集与 UI 渲染, 任意采集耗时都不影响界面.
# ============================================================
_SNAPSHOT_CACHE: dict[str, tuple[float, SimpleNamespace]] = {}
_SNAPSHOT_LOCK = threading.Lock()
_BG_THREAD: threading.Thread | None = None
_BG_INTERVAL = 2.0          # 秒; 后台采集周期 (PDH 需要 >0.9s 采样间隔, 2s 安全)
_BG_STALE_LIMIT = 5.0       # 秒; 缓存允许的最大陈旧度, 超过则降级为同步采集
_BG_STARTED = False


def _collect_snapshot() -> SimpleNamespace:
    """执行一次完整硬件采集 (原 snapshot() 的主体)."""
    return SimpleNamespace(
        cpu=_get_cpu(),
        ram=_get_ram(),
        gpus=_get_gpus_ns(),
    )


def _bg_worker() -> None:
    """后台采集线程: 每 _BG_INTERVAL 秒刷新一次缓存."""
    # Quinn 10:15: WMI/win32com 需要 COM 单元, 后台线程自行初始化 (STA)
    try:
        import pythoncom  # type: ignore
        pythoncom.CoInitialize()
    except Exception:
        pass
    while True:
        try:
            snap = _collect_snapshot()
            with _SNAPSHOT_LOCK:
                _SNAPSHOT_CACHE["main"] = (time.monotonic(), snap)
        except Exception:
            # 单次采集失败不应杀死线程
            pass
        time.sleep(_BG_INTERVAL)


def _ensure_bg() -> None:
    """懒启动后台采集线程 (仅一次)."""
    global _BG_THREAD, _BG_STARTED
    if _BG_STARTED:
        return
    _BG_STARTED = True
    _BG_THREAD = threading.Thread(target=_bg_worker, name="hw-collector", daemon=True)
    _BG_THREAD.start()


def _default_snapshot() -> SimpleNamespace:
    """轻量默认快照 (不触发任何 subprocess / WMI, 主线程即时可用).

    Quinn 10:15: 启动早期后台线程尚未产出真实数据时使用, 避免主线程阻塞导致"打开卡".
    字段结构与 _collect_snapshot() 对齐, 占位值用 None/0, 页面渲染时显 "-" 或 "?" 占位.
    """
    return SimpleNamespace(
        cpu=SimpleNamespace(
            model=None,
            cores_physical=psutil.cpu_count(logical=False) or 0,
            cores_logical=psutil.cpu_count(logical=True) or 0,
            freq_mhz=0,
            max_mhz=0,
            cache_text="",
            util_breakdown=None,
            util_percent=0.0,
            temp_c=None,
            freq_source="static",
        ),
        ram=SimpleNamespace(
            type=None,
            capacity_gb=0.0,
            used_gb=0.0,
            util_percent=0.0,
            freq_mhz=None,
        ),
        gpus=[],
    )


def snapshot() -> SimpleNamespace:
    """返回 SimpleNamespace(cpu=..., ram=..., gpus=[...]).

    Quinn 10:15 第五轮: 后台线程采集 + 主线程读缓存, 消除刷新卡顿.
    后台线程未就绪时返回轻量默认 (不阻塞主线程), 真实数据由后台线程每 2s 刷新后即时可读.
    """
    _ensure_bg()
    with _SNAPSHOT_LOCK:
        cached = _SNAPSHOT_CACHE.get("main")
    if cached is not None and (time.monotonic() - cached[0]) < _BG_STALE_LIMIT:
        return cached[1]
    # 后台未就绪 (启动早期): 返回轻量默认, 主线程不阻塞; 后台线程将在 ~1-2s 内填充真实数据
    return _default_snapshot()
