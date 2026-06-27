@echo off
set "SCRIPT_DIR=%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run.ps1" %*
exit /b %ERRORLEVEL%
