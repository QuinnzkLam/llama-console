@echo off
REM ============================================================
REM register_schtask_limited.bat
REM 将 Hedanji-Llama-Start 由 HighestAvailable(High integrity) 降级为
REM LeastPrivilege(Medium), 根治 GUI(Medium) taskkill 被拒 -> UAC 弹窗.
REM
REM 必须以【管理员】运行:
REM   旧 task 以 HighestAvailable 注册, 属 High integrity, 普通权限
REM   schtasks /End /Delete 会 "Access Denied", 故本脚本需提权执行.
REM 提权只用于【删除/重建 task 这一次】, 重建后 task 本身跑 LeastPrivilege.
REM ============================================================

setlocal
set "TASK_NAME=Hedanji-Llama-Start"
REM XML 位置 (repo-relative): scripts\ops\Hedanji-Llama-Start-Limited.xml
set "TASK_XML=%~dp0ops\Hedanji-Llama-Start-Limited.xml"

echo === [1/3] Stop + delete old (elevated) task ===
schtasks /End /TN "%TASK_NAME%" >nul 2>&1
schtasks /Delete /TN "%TASK_NAME%" /F
echo.

echo === [2/3] Create least-privilege task from XML ===
schtasks /Create /TN "%TASK_NAME%" /XML "%TASK_XML%"
echo.

echo === [3/3] Verify (expect LeastPrivilege + InteractiveToken) ===
schtasks /Query /TN "%TASK_NAME%" /XML
echo.

echo Done.
echo 若 /Query 输出含 LeastPrivilege + InteractiveToken 即成功.
echo 旧的 High integrity llama-server 残留进程需先手动清一次 (见 docs/llamadeck-schtask-downgrade.md).
pause
