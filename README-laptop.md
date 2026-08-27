# llama-console v2 — Portable Package (Laptop Edition)

**打包时间：** 2026-08-25 15:15 GMT+8
**核弹机 commit:** a668e46 (RAM "r0" fix)

## ⚠️ v0.1.1 修复

旧 v0.1.0 zip 漏咗 12 个 .py (`__main__.py`/`app.py`/`__init__.py` + 9 个 widgets/pages/backend 模块)。错误信息:
```
No module named llama_console_v2.__main__; 'llama_console_v2' is a package and cannot be directly executed
```
**v0.1.1 已补全 22 个 .py, 用核弹机真源。**

## 🏗️ 架构 (核弹机真源)

```
llama-console-v2-portable/
├── pyproject.toml
├── start_v2.bat / .sh
├── config.yaml (decoupled)
├── README-laptop.md
└── src/llama_console_v2/
    ├── __init__.py         ← v0.1.1 added
    ├── __main__.py         ← v0.1.1 added (entry: from .app import main)
    ├── app.py              ← v0.1.1 added (QApplication + font + palette)
    ├── main_window.py      ← MainWindow class
    ├── theme.py            ← COLORS, FONT_SIZE, color/font helpers
    ├── llama_cpp.py        ← root-level (10744B) — 唔系 backend/llama_cpp.py!
    ├── backend/
    │   ├── __init__.py
    │   ├── hardware.py     ← CPU/RAM/GPU
    │   ├── llama_cpp.py    ← backend-level
    │   ├── frp.py
    │   ├── status.py
    │   └── main_window.py  ← (备援)
    ├── pages/
    │   ├── __init__.py     ← v0.1.1 added
    │   ├── console.py      ← 3-col 控制台
    │   └── settings.py     ← 设置页
    └── widgets/
        ├── __init__.py     ← v0.1.1 added
        ├── card.py
        ├── status_pill.py
        ├── progress_bar.py
        ├── key_value.py
        ├── buttons.py
        ├── stat_block.py
        ├── page_chrome.py  ← v0.1.1 added
```

## 🚀 运行

```bash
unzip llama-console-v2-portable.zip
cd llama-console-v2-portable
start_v2.bat
# 自动 venv + pip install -e . + python -m llama_console_v2
```

## 🔌 Decoupled 配置 (改 config.yaml)

| 字段 | 含义 | Laptop 默认 |
|------|------|------------|
| `llama_server.exe` | llama-server.exe 路径 | 改你自己路径或留空 (disable 启动按钮) |
| `llama_server.model_dir` | 模型目录 | 同上 |
| `frp.enabled` | FRP 远程端口 | `false` (laptop 唔需要) |
| `ui.window_default` | 窗口默认大小 | [1680, 1040] |

## 🎨 修改界面

| 想改咩 | 改边个文件 |
|--------|----------|
| 配色 / 字号 | `theme.py` |
| 控制台 3 列 | `pages/console.py` |
| 设置页 | `pages/settings.py` |
| 侧边栏 | `main_window.py` |
| 加新卡 | `widgets/card.py` |
| 硬件数据 | `backend/hardware.py` |
| 启停 llama-server | `backend/llama_cpp.py` |

## 🔄 改完 push 返核弹机

```bash
# laptop
git diff > my-ui.patch
# 复制 .patch 返核弹机
scp my-ui.patch quinn@192.168.50.167:/tmp/

# 核弹机 PowerShell
ssh quinn@192.168.50.167 'cd D:\llama-console && git apply /tmp/my-ui.patch'
```
