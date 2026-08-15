@echo off
chcp 65001 >nul 2>&1
set "ROOT=%~dp0"

call "%ROOT%scripts\run.bat" electron
exit /b %ERRORLEVEL%
