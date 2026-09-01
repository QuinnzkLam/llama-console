@echo off
REM ============================================================
REM  llama-console v2 launcher (核弹机，2026-08-25 11:50 fix)
REM
REM  关键修复:
REM    之前跑 `python -m llama_console` + PYTHONPATH=v2;src
REM    → Python 走 src\\llama_console\\ (v1) 一闪而过
REM    现在跑 `python -m llama_console_v2` (直接叫 v2 package)
REM
REM  v1 区别:
REM    - 源路径: src\llama_console_v2 (v2 独立目录)
REM    - 启动: Popen (不经 schtasks)
REM    - 架构独立性: 仅与 v1 共享 llama-server.exe
REM
REM  使用说明:
REM    1. 第一次运行 v2 GUI 会自动检测 v1 / v2 llama-server.exe
REM    2. 启动前 v1 必须先停 (port 18605 conflict)
REM    3. 关闭 GUI 不会自动停 llama-server，需手动用 GUI 停止按钮
REM ============================================================

setlocal

set "ROOT=D:\llama-console"
set "VENV=%ROOT%\.venv"
set "PY=%VENV%\Scripts\python.exe"
set "SRC=%ROOT%\src\llama_console_v2"

echo ============================================================
echo  llama-console v2 (Phase A 收尾, 2026-08-25)
echo  Project: %ROOT%
echo  Source:  %SRC%
echo  Python:  %PY%
echo  Port:    18605 (与 v1 共享 FRP/iMac config)
echo ============================================================
echo.

REM Verify venv exists
if not exist "%PY%" (
    echo [ERROR] venv not found at %PY%
    pause
    exit /b 1
)

REM Verify v2 source exists
if not exist "%SRC%\__main__.py" (
    echo [ERROR] v2 source not found at %SRC%
    echo Deploy draft/src/llama_console to %SRC% first
    pause
    exit /b 1
)

REM Verify v1 stopped
netstat -ano | findstr :18605 | findstr LISTENING >nul
if not errorlevel 1 (
    echo [WARN] port 18605 仲有进程 listen，可能 v1 未停
    echo        如要强制启动 v2, 请先 stop v1
    echo.
)

REM Launch v2 GUI (FIX: -m llama_console_v2, not -m llama_console)
echo Starting v2 GUI...
cd /d "%ROOT%"
"%PY%" -m llama_console_v2

REM If exit code != 0, show error
if errorlevel 1 (
    echo.
    echo [ERROR] v2 GUI exited with code %errorlevel%
    pause
)

endlocal
