@echo off
set "SCRIPT_DIR=%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%update.ps1" %*
exit /b %ERRORLEVEL%
