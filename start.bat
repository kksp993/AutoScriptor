@echo off
chcp 65001 >nul 2>&1
title AutoScriptor

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "BRANCH=feat/launcher"

REM ── 检查 git ──
where git >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [WARN] git not found, skipping update.
    goto :START_APP
)

REM ── 拉取远程更新 ──
echo [*] Fetching updates from origin/%BRANCH% ...
git fetch origin %BRANCH% 2>nul
if %ERRORLEVEL% neq 0 (
    echo [WARN] git fetch failed, continuing with current version.
    goto :START_APP
)

REM ── 对比本地与远程 commit ──
for /f "delims=" %%i in ('git rev-parse HEAD 2^>nul') do set "LOCAL_SHA=%%i"
for /f "delims=" %%i in ('git rev-parse "origin/%BRANCH%" 2^>nul') do set "REMOTE_SHA=%%i"

if "%LOCAL_SHA%"=="%REMOTE_SHA%" (
    echo [*] Already up to date.
    goto :START_APP
)

echo [*] Updates available: %LOCAL_SHA:~0,8% -^> %REMOTE_SHA:~0,8%
echo [*] Stashing local changes...
git stash --quiet 2>nul

echo [*] Pulling latest code...
git pull --ff-only origin %BRANCH%
if %ERRORLEVEL% neq 0 (
    echo [WARN] pull --ff-only failed, trying reset...
    git reset --hard "origin/%BRANCH%"
)

echo [*] Restoring local changes...
git stash pop --quiet 2>nul

REM ── 更新 Python 依赖 ──
if exist ".venv\Scripts\pip.exe" (
    echo [*] Updating Python dependencies...
    .venv\Scripts\pip.exe install -r requirements.txt --quiet 2>nul
)

echo [*] Update complete.

:START_APP
REM ── 清理残留的 5000 端口占用（上次异常退出时可能残留 Python 进程） ──
echo [*] Checking port 5000...
set "_FOUND_STALE="
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":5000.*LISTENING"') do (
    if %%a NEQ 0 (
        set "_FOUND_STALE=1"
        echo [*] Killing stale process on port 5000 ^(PID: %%a^)
        taskkill /PID %%a /T /F >nul 2>&1
    )
)
if defined _FOUND_STALE (
    echo [*] Waiting for port release...
    timeout /t 1 /nobreak >nul 2>&1
)

cd /d "%ROOT%webapp"

where npm >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] npm not found. Please install Node.js first.
    echo         https://nodejs.org/
    pause
    exit /b 1
)

if not exist "node_modules\" (
    echo [*] Installing npm dependencies...
    call npm install
    if %ERRORLEVEL% neq 0 (
        echo.
        echo [ERROR] npm install failed.
        pause
        exit /b 1
    )
)

echo [*] Starting AutoScriptor...
> "%TEMP%\_as_launch.vbs" echo CreateObject("WScript.Shell").Run "cmd /c cd /d ""%CD%"" && npm start", 0, False
wscript "%TEMP%\_as_launch.vbs"
del "%TEMP%\_as_launch.vbs" 2>nul
exit 0
