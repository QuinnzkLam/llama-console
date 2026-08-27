# 前端数据 ↔ 后端采集配置映射文档

> 用途：记录控制台页 / 设置页 / 侧边栏每个 UI 字段由哪个后端函数采集、采集方式、配置点（硬编码常量 / 配置文件 / 外部进程），方便后续关联配置与排错。
> 适用范围：`llama-console-v2-portable`（commit a668e46 之后结构）
> 最后校对：2026-08-26

---

## 0. 后端模块一览

| 模块 | 职责 | 关键函数 |
|------|------|----------|
| `backend/hardware.py` | CPU / RAM / GPU 采集 | `snapshot()` → `cpu` / `ram` / `gpus` |
| `backend/llama_cpp.py` | llama-server 进程/状态/启动/停止/版本/token/方案 | `snapshot()` `get_status()` `start()` `stop()` `get_token_stats()` `list_schemes()` `list_models()` `current_cmdline_args()` |
| `backend/frp.py` | FRP 隧道状态（读 toml + 进程探测） | `snapshot()` = `get_frp_status()` |
| `backend/status.py` | **占位 stub，无任何实现**，`console.py` 仅 import 不调用 | — |

**刷新机制**
- 控制台页：`ConsolePage` 内 `QTimer` 每 **5000ms** 调 `refresh()`，依次触发 `_refresh_llama` / `_refresh_token` / `_refresh_hardware` / `_refresh_frp`（见 `pages/console.py:160-164`）。
- 设置页：数据仅在 `__init__` 时一次性加载（`_load_models` / `_load_cmdline` / `_load_version` / `_load_build_status`），无定时刷新。

---

## 1. 控制台页（Console）—— 引擎列（Engine）

### 1.1 llama-server 状态卡（Card "llama-server 状态"）

数据源：`backend_llama.snapshot()` = `get_status()`（`backend/llama_cpp.py:146`）

| UI 字段 | 后端字段 / 函数 | 采集方式 | 配置点 / 备注 |
|---------|----------------|----------|---------------|
| 状态 pill（已停止 / 加载中 / 运行中 / 错误） | `snap.state` | 先 `psutil` 找 `llama-server.exe` 进程；找到后 HTTP `GET http://127.0.0.1:{port}/health`，返回 200 且 `status=="ok"` 即 `running`，否则 `loading` | 端口 = `DEFAULT_PORT = 18605`（`llama_cpp.py:19`，硬编码） |
| 模型名 | `snap.model_name` | `_get_model_info()` 读进程 `cmdline` 的 `-m` 参数 → 取文件名 | 仅当进程存在时有效 |
| 副信息（quant · llama.cpp 版本） | `snap.quant` + `getattr(snap,"llama_cpp_version",None)` | `quant` 由文件名正则匹配（`Q8_0` 等）；"llama.cpp 版本" 期望来自 `llama_cpp_version` | ⚠️ **`get_status()` 未返回 `llama_cpp_version` 字段**，故版本号**实际永不显示**（见 §5.2） |
| 运行时间 | `snap.uptime` | `time.time() - proc.create_time` → `_format_uptime()` | — |
| PID | `snap.pid` | 进程 PID | — |
| 监听地址 | `snap.bind` | 硬编码 `f"{DEFAULT_HOST}:{port}"` = `0.0.0.0:18605` | `DEFAULT_HOST="0.0.0.0"`（`llama_cpp.py:20`） |
| 外网地址 | `snap.public_url` | **硬编码占位** `f"http://frp.example.com:{port}/v1"` | ⚠️ **非真实 FRP 地址**，未由 `frp.snapshot()` 填充（见 §5.3） |
| 局域网地址 | `snap.local_url` | `f"http://127.0.0.1:{port}"` | — |

绑定代码：`pages/console.py:629`（`_refresh_llama`）。

### 1.2 FRP 隧道卡（Card "FRP 隧道"）

数据源：`backend_frp.snapshot()` = `get_frp_status()`（`backend/frp.py:98`）

| UI 字段 | 后端字段 / 函数 | 采集方式 | 配置点 / 备注 |
|---------|----------------|----------|---------------|
| 状态 pill（已连接 / 未连接） | `snap.connected` | `frpc.exe` 进程存在 **且** toml 中匹配到 `local_port==18605` 的 `remote_port` | `FRP_CONFIG_PATH = D:/frp/frpc.toml`（`frp.py:15`，硬编码） |
| 隧道名 | `snap.tunnel_name` | 解析 toml `[[proxy]]` 块，匹配 `local_port==18605` 的 `name` | 找不到时退化为 `"frpc"`（若进程在跑） |
| 远程端口 | `snap.remote_port` | toml `remoteport` | — |
| 本地端口 | `snap.local_port` | toml `localport`；缺失时回退 `llama_port`(18605) | — |
| 公网地址 | `snap.public_url` | `f"http://{server_addr}:{remote_port}/v1"`（来自 toml `serveraddr`） | **这是真实外网地址**，与状态卡里硬编码的占位不同 |

绑定代码：`pages/console.py:748`（`_refresh_frp`）。

> 注意：FRP 的 `enabled` / `remote_port` / `exe` 也出现在 `config.yaml`，但 **`frp.py` 不读 `config.yaml`**，只读硬编码的 `D:/frp/frpc.toml`。

### 1.3 Token 统计卡（Card "Token 统计"）

数据源：`backend_llama.get_token_stats()`（`backend/llama_cpp.py:347`）

| UI 字段 | 后端字段 / 函数 | 采集方式 | 配置点 / 备注 |
|---------|----------------|----------|---------------|
| 输入总 Token | `snap.prompt_tokens` | 解析 `http://127.0.0.1:{port}/metrics` 的 `llamacpp:prompt_tokens_total`（兼容旧名 `prompt_tokens_processed_total`） | 需服务器以 **`--metrics`** 启动；4s 缓存 |
| 输出总 Token | `snap.predicted_tokens` | `llamacpp:tokens_predicted_total`（兼容 `tokens_predicted_generated_total`） | 同上 |
| 生成速度（tok/s） | `snap.predicted_tps` | `llamacpp:predicted_tokens_seconds`（累计秒，全时均值） | 同上 |
| 底部「停止 llama-server」按钮 | — | 调 `backend_llama.stop()`（`taskkill /F /IM llama-server.exe`） | 服务未启时禁用 |
| 引导/提示文本 | `snap.available` | 不可用：若 `state==stopped` 提示去侧边栏启动；否则提示未开 `--metrics` | — |

绑定代码：`pages/console.py:760`（`_refresh_token`）。

> ⚠️ **关键依赖缺口**：`get_token_stats()` 依赖 `/metrics`，而 `/metrics` 仅在 llama-server 带 `--metrics` 时暴露。`_DEFAULT_CMDLINE` 含 `--metrics`（`llama_cpp.py:246`），但 `start()`（`llama_cpp.py:188`）**自行拼参，不读取 `_DEFAULT_CMDLINE`，也不读取保存的启动参数**，因此经本 GUI「方案」侧边栏启动的实例**默认不含 `--metrics`**，Token 卡会显示"未启用 --metrics"。详见 §5.4。

---

## 2. 控制台页（Console）—— 硬件列（Hardware）

数据源：`backend_hardware.snapshot()`（`backend/hardware.py:251`）→ `cpu` / `ram` / `gpus`

### 2.1 CPU 卡（Card "CPU"）

| UI 字段 | 后端字段 / 函数 | 采集方式 | 配置点 / 备注 |
|---------|----------------|----------|---------------|
| 型号 | `cpu.model` | WMI `Win32_Processor.Name`（`_get_cpu_model`） | — |
| 物理/逻辑核心数 · 频率 | `cpu.cores_physical` `cpu.cores_logical` `cpu.freq_mhz` | `psutil.cpu_count()` / `psutil.cpu_freq().current` | — |
| 利用率 | `cpu.util_percent` | `psutil.cpu_percent(interval=0.0)` | 进度条配色见 `_util_color()`（`console.py:43`） |
| 温度 | `cpu.temp_c` | `_get_cpu_temp()` 4 级 fallback（见下） | 为 `None` 时 UI 显"未检测到传感器" |

`_get_cpu_temp()` 采集顺序（`hardware.py:40`）：
1. `root\wmi::MSAcpi_ThermalZoneTemperature`（Dell/HP 商务机）
2. 默认命名空间 `MSAcpi_ThermalZoneTemperature`
3. `root\LibreHardwareMonitor` / `root\OpenHardwareMonitor` 第三方服务（按 "CPU Package > CPU Core > CPU" 优先级）
4. `Win32_TemperatureProbe`
5. （代码注释含）`Win32_PerfFormattedData_Counters_ThermalZoneInformation`
全部失败 → 返回 `None`。

### 2.2 内存 RAM 卡（Card "内存 RAM"）

| UI 字段 | 后端字段 / 函数 | 采集方式 | 配置点 / 备注 |
|---------|----------------|----------|---------------|
| 类型 · 容量 · 频率（单行合并） | `ram.type` `ram.capacity_gb` `ram.freq_mhz` | WMI `Win32_PhysicalMemory`：`SMBIOSMemoryType`/`MemoryType` 映射 DDR 代，容量按**所有插槽求和**，频率取 `Speed` | 类型映射表见 `hardware.py:131-147`；频率 ≥4800 经验判 DDR5 |
| 利用率 | `ram.util_percent` | `psutil.virtual_memory().percent` | — |
| 已用 / 总量 | `ram.used_gb` / `ram.capacity_gb` | `psutil.virtual_memory().used` / WMI 容量 | — |

### 2.3 GPU 卡（Card "GPU 信息"，含 GPU0 / GPU1 子卡）

数据源：`hardware.snapshot().gpus`（`_get_gpus()`，`hardware.py:157`）

| UI 字段 | 后端字段 / 函数 | 采集方式 | 配置点 / 备注 |
|---------|----------------|----------|---------------|
| 型号 | `gpu.model` | `nvidia-smi --query-gpu=name` | nvidia-smi 路径候选：`PATH` → `D:/Program Files/NVIDIA Corporation/NVSMI/nvidia-smi.exe` → 另两条 alt（`hardware.py:16-21`） |
| 核心利用率 | `gpu.util_percent` | `utilization.gpu` | — |
| VRAM 利用率 | `gpu.vram_util_percent` | **`memory.used / memory.total * 100`**（已修复，非 `utilization.memory`） | `hardware.py:193` 修复点：旧 `utilization.memory` 是带宽占用率 |
| VRAM 已用 / 总 | `gpu.vram_used_mb` / `gpu.vram_total_mb` | `memory.used` / `memory.total` | UI 显 `"{used:.1f} / {total:.1f}G"`（`console.py:719`） |
| 温度 | `gpu.temp_c` | `temperature.gpu`（不支持则为 `None`） | — |

> 无 GPU 或 nvidia-smi 不可达时 `gpus=[]`，子卡显示 "-"。

---

## 3. 设置页（Settings）

### 3.1 运行环境卡（Card "运行环境"，3 段）

| UI 字段 | 后端字段 / 函数 | 采集方式 | 配置点 / 备注 |
|---------|----------------|----------|---------------|
| 模型选择（下拉） | `list_models()` | 扫描 `_MODELS_DIR/**/*.gguf`（排除 `mmproj*`） | `_MODELS_DIR = D:/llama-console/models`（`llama_cpp.py:29`，硬编码） |
| 模型路径 | `current_model_path()` | 取 `list_models()[0]` 的完整路径 | — |
| llama-server 版本（当前） | `get_version()` = `get_current_version()` | 运行 `llama-server.exe --version` 并正则提取 | 取 exe 见 `get_llama_server_exe()` |
| 最新版本 | `check_latest_version()` | GitHub API `api.github.com/repos/ggerganov/llama.cpp/releases/latest`（需联网） | `GITHUB_API`（`llama_cpp.py:22`） |
| 检查更新按钮 | `_on_check_update` | 仅写入"最新版本"标签；**未做新版比对提示** | 小功能缺口 |
| 二进制路径 | `get_llama_server_exe()` | 优先级：v2 本地构建 `D:/llama-console/src/llama.cpp/build/bin/Release/llama-server.exe` → v1 预编译 `D:/services/llama-server/llama-server.exe` | `llama_cpp.py:25-27`，硬编码 |
| 构建状态 | `get_current_version()` | `"not built"` → "未构建"；否则 "已构建 · {ver}" | — |
| 模型目录 | 直接 `Path("D:/llama-console/models")` | 统计 `.gguf` 数量 | 与 `_MODELS_DIR` 同源但**独立硬编码**，不一致风险 |

绑定代码：`pages/settings.py:383-442`。

### 3.2 启动参数卡（Card "启动参数"）

| UI 字段 | 后端字段 / 函数 | 采集方式 | 配置点 / 备注 |
|---------|----------------|----------|---------------|
| 参数输入框 | `current_cmdline_args()` | 读 `_CMDLINE_FILE = D:/llama-console/cmdline_args.txt`；不存在则用 `_DEFAULT_CMDLINE` | `llama_cpp.py:244, 246` |
| 保存参数 | `save_cmdline_args()` | 写回 `cmdline_args.txt` | — |
| 恢复默认 | `default_cmdline_args()` | 返回 `_DEFAULT_CMDLINE` | — |

⚠️ **致命缺口**：`start()` / `start_with_scheme()` **完全不读取** `current_cmdline_args()` 或 `_DEFAULT_CMDLINE`，而是自行拼 `-m/-c/-ngl/--port/--host` + 方案 `extra_args`。因此：
- 用户在「启动参数」卡里编辑/保存的内容**对实际启动毫无影响**（纯展示）。
- `--metrics`、`--temp`、`--top-p` 等参数不会被传入启动实例（直接原因：Token 卡 §1.3 缺口）。

---

## 4. 侧边栏「方案」区段（Schemes）

数据源：`backend_llama.list_schemes()`（`llama_cpp.py:400`，内置 4 个，非配置驱动）

| UI 元素 | 后端 | 行为 |
|---------|------|------|
| 默认 / 快速 / 长文 / 调试 4 个方案按钮 | `list_schemes()` 返回 `id/name/description/icon/extra_args` | 点击 → `start_with_scheme(id)` → 先 `stop()` 再 `start(extra_args=...)` |
| 方案 `extra_args` | 内置字典 | `default=[]`；`fast=[--ctx-size 8192,--parallel 4,--batch-size 512]`；`long=[--ctx-size 524288,--no-warmup]`；`debug=[--log-level debug,--verbose]` |

> 注释提到"未来可读取 `~/.llama_console_v2/schemes.yaml`"，目前**未实现**，方案完全硬编码。

---

## 5. ⚠️ 已发现的数据 / 配置不一致（重要，建议优先修）

### 5.1 `config.yaml` 是死配置，后端完全没加载
- `config.yaml` 含 `llama_server.exe / model_dir / cmdline_args / port`、`frp.*`、`ui.*` 等，但 `backend/hardware.py`、`backend/llama_cpp.py`、`backend/frp.py` **均不读取它**，全部用模块级硬编码常量（`D:/llama-console/...`、`D:/services/...`、`D:/frp/...`、`18605` 等）。
- `README-laptop.md` 第 60-68 行声称"改 config.yaml 即可解耦配置"，与代码实际行为**不符**，会误导后续维护。
- 影响： portable 包换机器后，这些 `D:/` 路径大多不存在，GUI 能起但 llama-server 无法启动 / 模型找不到 / FRP 不连。

### 5.2 状态卡"llama.cpp 版本"永不显示
- `console.py:646` 读取 `getattr(snap, "llama_cpp_version", None)`，但 `get_status()`（`llama_cpp.py:146`）的返回值里**没有该字段**，故恒为 `None`，版本号那一段永远拼不出来。
- 修复：在 `get_status()` 返回时补 `llama_cpp_version=get_current_version()`（带 30s 缓存，避免每次 refresh 起 subprocess）。

### 5.3 状态卡"外网地址"是硬编码占位，非真实 FRP 地址
- `get_status()` 把 `public_url` 写死成 `http://frp.example.com:18605/v1`（`llama_cpp.py:174`）。
- 真实公网地址由 `frp.snapshot().public_url` 提供（见 §1.2）。两处 UI 显示的"外网地址"不一致，状态卡那个是假的。
- 修复：状态卡刷新时从 `backend_frp.snapshot().public_url` 取，或让 `get_status()` 调用 frp 模块填充。

### 5.4 「启动参数」保存后不被启动逻辑采用 → Token 统计依赖的 `--metrics` 缺位
- 详见 §3.2、§1.3。根因：`start()` 自行拼参，未合并 `current_cmdline_args()`。
- 后果：① 用户在设置页改的参数无效；② 经 GUI 启动的实例默认无 `/metrics`，Token 卡即使服务在跑也显示"未启用 --metrics"。

### 5.5 其它小项
- `get_status()` 解析 `ctx_size` 仅读 `-m`/`--port`（`_get_model_info`，`llama_cpp.py:120`），实际 `ctx_size` 永远为 `None`（UI 已按需求移除显示，无影响）。
- `设置页`「检查更新」只写"最新版本"标签，未提示"是否有新版本可更"（与 `is_update_available()` 未联动）。

---

## 6. `start_v2.bat` 一键部署检查

### 6.1 现有能力（bat 实际做的）
```
1. chcp 65001                      → 控制台 UTF-8（中文正常）
2. where python                    → 仅检查 python 是否存在（不校验版本）
3. 若不存在 .venv\Scripts\python.exe：
      python -m venv .venv         → 建隔离环境
      pip install -e .             → 安装包 + 依赖(PySide6/psutil/httpx/pywin32)
4. set PYTHONPATH=%CD%\src         → 源码路径入环境
5. .venv\Scripts\python.exe -m llama_console_v2  → 启动 GUI
6. if errorlevel 1 pause           → 仅 GUI 报错时暂停
```
结论：**它能一键把"GUI 应用本身"跑起来**（含建 venv、装依赖），属于"一键启动 GUI"。

### 6.2 缺失项（不构成"完整一键部署"）
| 缺失 | 说明 | 后果 |
|------|------|------|
| **不校验 Python 版本** | `where python` 不查 `>=3.10` | 机器若装了老 Python，`pip install -e .` 直接失败 |
| **不构建/下载 llama.cpp 二进制** | 后端 exe 优先级指向 `D:/llama-console/...` 与 `D:/services/...`，bat 不提供 | 新机器上 `llama-server.exe not found`，GUI 能开但启不了服务（§5.1 同源） |
| **不准备模型文件** | `_MODELS_DIR = D:/llama-console/models` 由 bat 不创建/不下载 | 模型下拉为空，无模型可载 |
| **不安装/配置 frpc** | `FRP_CONFIG_PATH = D:/frp/frpc.toml` 不在 bat 范围 | FRP 卡恒显"未连接" |
| **不加载 config.yaml** | bat 不传配置路径，后端也不读（§5.1） | "改 config.yaml 解耦"承诺失效 |
| **venv 损坏无自愈** | 仅当 `.venv\Scripts\python.exe` 缺失才重建；若 venv 存在但依赖不全，会直接 `ImportError` 崩 | 首次安装中断后复跑不修复 |
| **PYTHONPATH 与 editable 安装冗余** | `pip install -e .` 已让包可导入，再 `set PYTHONPATH=%CD%\src` 多余（无害） | 仅代码洁癖问题 |
| **README 与实现不符** | README 称 config.yaml 可解耦，实际不可 | 误导维护者 |

### 6.3 是否"完整一键部署"——结论
**否。** 当前 `start_v2.bat` 只是 **GUI 的一键启动器**（venv + 依赖 + 运行），并**未部署 llama-console 真正依赖的外部资源**（llama.cpp 二进制、模型、frpc、以及应被读取的 `config.yaml`）。要在任意机器"开箱即用"，还需补：
1. Python 版本校验（`python --version` ≥ 3.10，否则提示）。
2. 让后端真正加载 `config.yaml`（并修正 README 描述），把 `D:/...` 硬编码改为相对/可配置。
3. 在启动前校验/自动定位 `llama-server.exe` 与模型目录；缺失时给出明确引导而非静默失败。
4. 把 `start()` 与 `current_cmdline_args()` / `_DEFAULT_CMDLINE` 打通（修 §5.4），让保存的参数与 `--metrics` 生效。
5. venv 损坏自愈（删除 `.venv` 重建，或 `pip install -e .` 强制重装）。

---

## 7. 快速索引（文件:行号）

| 关注点 | 位置 |
|--------|------|
| 引擎状态 | `backend/llama_cpp.py:146` `get_status`；`pages/console.py:629` `_refresh_llama` |
| FRP 状态 | `backend/frp.py:98` `get_frp_status`；`pages/console.py:748` `_refresh_frp` |
| Token 统计 | `backend/llama_cpp.py:347` `get_token_stats`；`pages/console.py:760` `_refresh_token` |
| 硬件采集 | `backend/hardware.py:251` `snapshot`；`pages/console.py:666` `_refresh_hardware` |
| 启动/方案 | `backend/llama_cpp.py:188` `start`；`:400` `list_schemes`；`:447` `start_with_scheme` |
| 启动参数(死配置) | `backend/llama_cpp.py:244` `_CMDLINE_FILE`；`:278` `current_cmdline_args` |
| 硬编码路径 | `backend/llama_cpp.py:25-29,244`；`backend/frp.py:15`；`backend/hardware.py:16-21` |
| bat 启动器 | `start_v2.bat` |
| 配置(死) | `config.yaml`（任何 backend 均未读取） |
