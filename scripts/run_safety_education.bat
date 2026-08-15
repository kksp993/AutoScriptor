@echo off
set "SCRIPT_DIR=%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run_safety_education.ps1" %*
exit /b %ERRORLEVEL%
