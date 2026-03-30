@echo off
chcp 65001 >nul 2>&1
title AutoScriptor

set "ROOT=%~dp0"
cd /d "%ROOT%webapp"

where npm >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] npm not found. Please install Node.js first.
    echo         https://nodejs.org/
    pause
    exit /b 1
)

if not exist "node_modules\" (
    echo Installing dependencies...
    call npm install
    if %ERRORLEVEL% neq 0 (
        echo.
        echo [ERROR] npm install failed.
        pause
        exit /b 1
    )
)

echo Starting AutoScriptor...
> "%TEMP%\_as_launch.vbs" echo CreateObject("WScript.Shell").Run "cmd /c cd /d ""%CD%"" && npm start", 0, False
wscript "%TEMP%\_as_launch.vbs"
del "%TEMP%\_as_launch.vbs" 2>nul
exit 0
