@echo off
chcp 65001 >nul 2>&1
title 造笔 - 释放占用
cd /d "%~dp0"

echo [*] 释放 5000 端口及本仓库下相关进程（需 powershell）...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\release_autoscriptor_locks.ps1"
echo.
pause
