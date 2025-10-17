@echo off
REM 获取脚本所在目录
set SCRIPT_DIR=%~dp0

REM 使用 Bypass 执行策略运行 PowerShell 脚本
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%launcher.ps1" %*

REM 将 PowerShell 脚本的退出码传递给批处理
exit /b %ERRORLEVEL%
