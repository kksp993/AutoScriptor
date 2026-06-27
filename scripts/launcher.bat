@echo off
set "SCRIPT_DIR=%~dp0"

call "%SCRIPT_DIR%run.bat" %*
exit /b %ERRORLEVEL%
