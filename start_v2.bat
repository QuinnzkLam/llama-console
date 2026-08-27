@echo off
chcp 65001 >nul 2>&1
setlocal
pushd "%~dp0"

REM --- locate python (venv preferred, fallback to PATH) ---
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] No Python found. Install Python 3.11+ and re-run.
        pause
        exit /b 1
    )
    set "PY=python"
)

REM --- make the package importable regardless of cwd ---
set "PYTHONPATH=%~dp0src"

REM --- pre-flight diagnostic (Chinese printed by Python, safe encoding) ---
"%PY%" tools\preflight.py
echo.

REM --- launch GUI ---
"%PY%" -m llama_console_v2
if errorlevel 1 (
    echo [ERROR] llama-console exited with code %errorlevel%.
    pause
)

popd
endlocal
