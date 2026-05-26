@echo off
setlocal enabledelayedexpansion
REM 获取脚本所在目录
set SCRIPT_DIR=%~dp0

:LOOP
REM 使用 Bypass 执行策略运行 PowerShell 脚本，并传递 -l 参数
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%launcher.ps1" cli -l %*
set ERRORLEVEL_BAK=%ERRORLEVEL%

REM 如果 PowerShell 脚本报错，提示用户按任意键继续，不直接退出
if NOT "%ERRORLEVEL_BAK%"=="0" (
    echo.
    echo [!] Press Any Key to Continue...
    pause >nul
    goto LOOP
) else (
    endlocal
    exit /b 0
)
