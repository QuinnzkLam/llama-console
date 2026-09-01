@echo off
echo [%date% %time%] === llama_with_frp STOP === >> D:\llama-console\logs\sync.log

REM 1) Stop llama-server
echo [%date% %time%] Stopping llama-server... >> D:\llama-console\logs\sync.log
taskkill /F /IM llama-server.exe >nul 2>&1

REM 2) Stop FRP client
echo [%date% %time%] Stopping FRPC... >> D:\llama-console\logs\sync.log
taskkill /F /IM frpc.exe >nul 2>&1
