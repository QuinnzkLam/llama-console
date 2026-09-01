# llama-console v0.1.0 — RDP 真机验证步骤

> **项目**：`D:\llama-console\`
> **启动**：`run_llama_console.bat`（双击）
> **技术栈**：Python 3.13 + PySide6 + uv

---

## 🚀 一分钟快速 verify

### 步骤 1：RDP 到核弹机
- 远程桌面 → `192.168.50.167`
- 用户 `quinn`

### 步骤 2：双击启动器
桌面 → 找到 **`run_llama_console.bat`** → 双击

或者手动 PowerShell：
```powershell
cd D:\llama-console
.\.venv\Scripts\python.exe -m llama_console
```

### 步骤 3：观察 GUI
- ✅ 1280x820 窗口弹出
- ✅ Dark theme（`#0b0c10` 背景）
- ✅ 中文正常显示（Microsoft YaHei）
- ✅ 左侧栏：`llama-server` 标题 + `控制台` / `设置` nav
- ✅ 控制台页：6 cards 按设计图布局

---

## 📋 验收清单

### 控制台页（6 cards）

| Card | 验收点 | 状态 |
|:-----|:-------|:----:|
| **llama-server 状态** | 右上 pill（运行中=绿 / 加载中=琥珀 / 已停止=灰）+ 运行时间 + PID + 监听地址 | ☐ |
| **CPU / RAM** | 两条进度条（绿=CPU / 蓝=RAM）+ 温度 + 核心数 + 可用 + 利用率 | ☐ |
| **FRP 隧道** | 右上 pill（已连接=绿 / 未连接=红）+ 隧道名 + 远程端口 + 本地端口 | ☐ |
| **GPU 0 / RTX 4090** | 24 GB 标签 + 核心利用率（绿）+ VRAM 利用率（蓝）+ 核心温度 + VRAM 温度 | ☐ |
| **GPU 1 / RTX 3090** | 同上 | ☐ |
| **启停控制** | 启动按钮（青色实心 + ▶）+ 暂停按钮（描边 + ⏸） | ☐ |

### 设置页（2 cards）

| Card | 验收点 | 状态 |
|:-----|:-------|:----:|
| **← 返回控制台 + 设置** | Header 返回链接 + 在线 pill | ☐ |
| **模型选择** | Dropdown 列出 `config/models/qwen3.8-27b.json` | ☐ |
| **启动参数** | Textarea 显示从 server.json 生成的 cmdline | ☐ |
| **保存 / 恢复默认** | 主按钮（青色）+ 描边按钮 | ☐ |

---

## 🐛 已知问题（v1）

1. **温度可能不显示** — Windows psutil 不取温度，需 WMI；v1 暂时 `-`
2. **VRAM 温度** — nvidia-smi 不暴露 vram 温度在 Windows；v1 暂时 `-`
3. **nvidia-smi 第一次延迟** — 1-2s 之后刷新就快

---

## 📞 出问题怎么办？

**A. 启动失败**
- 截图 cmd 窗口错误信息
- 发我 message

**B. GUI 弹出但 layout 怪**
- 截 1 张图
- 我即刻调 spacing / 颜色

**C. 启动 / 暂停按钮无反应**
- 检查 schtasks：`schtasks /Query | findstr Hedanji`
- 如果任务不在，fallback Popen start_llama.bat

**D. 中文乱码**
- 不可能：用了 Microsoft YaHei 真实字体
- 截图俾我

---

## 🔄 实时刷新

- 状态 / 硬件 / FRP：**每 5 秒** 自动刷新
- 无需手动按刷新

---

## 📦 下一步（你 OK 之后）

1. 你睇过 6 cards + 2 cards OK → 我做 PyInstaller 打包成 `llama-console.exe`
2. .exe 放 Desktop，双击运行（无需 console 窗口）
3. 跟 `llama-server-control.vbs` 一样零依赖

预计 5 分钟出 .exe。

**现在请你 RDP 上去 verify，把图发我 🚀**
