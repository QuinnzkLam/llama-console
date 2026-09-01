@echo off
echo [%date% %time%] === llama_with_frp START === >> D:\llama-console\logs\sync.log

REM 1) Ensure FRP client running (start only if not running)
tasklist | findstr /i "frpc.exe" >nul 2>&1
if %errorlevel%==1 (
    echo [%date% %time%] FRPC not running, starting... >> D:\llama-console\logs\sync.log
    start "" /b D:/frp/start_frpc.bat
) else (
    echo [%date% %time%] FRPC already running, skip >> D:\llama-console\logs\sync.log
)

REM 2) Start llama-server
echo [%date% %time%] Starting llama-server... >> D:\llama-console\logs\sync.log
cd /d D:\llama-console
call start_llama.bat


REM 3) Open nlama GUI (visible when user desktop session active)
start "" /b D:\llama-console\dist\nlama.exe
