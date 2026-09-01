@echo off
REM ============================================================
REM  llama-console 启动器 (核弹机 v1)
REM  Franky 2026-08-24
REM
REM  双击此文件即可启动 GUI（无需开 PowerShell）
REM
REM  使用说明:
REM    1. 第一次运行会自动激活 venv
REM    2. 弹出 llama-server 控制台窗口
REM    3. 关闭窗口退出
REM ============================================================

setlocal

set "ROOT=D:\llama-console"
set "VENV=%ROOT%\.venv"
set "PY=%VENV%\Scripts\python.exe"

echo ============================================================
echo  llama-console v0.1.0
echo  Project: %ROOT%
echo  Python:  %PY%
echo ============================================================
echo.

REM Verify venv exists
if not exist "%PY%" (
    echo [ERROR] venv not found at %PY%
    echo Please run: cd /d D:\llama-console ^& uv sync
    pause
    exit /b 1
)

REM Verify config exists
if not exist "%ROOT%\config\server.json" (
    echo [WARN] config\server.json not found, will use defaults
)

REM Launch GUI
echo Starting GUI...
cd /d "%ROOT%"
"%PY%" -m llama_console

REM If exit code != 0, show error
if errorlevel 1 (
    echo.
    echo [ERROR] GUI exited with code %errorlevel%
    echo See logs in %ROOT%\logs\
    pause
)

endlocal
