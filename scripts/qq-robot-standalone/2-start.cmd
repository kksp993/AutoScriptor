@echo off
setlocal
echo Starting the standalone QQ robot. Keep this window open.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0robot.ps1" -Action start
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%
