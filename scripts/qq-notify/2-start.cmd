@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0..\.."

rem Starts the robot in the background with a quick login (no QR code), so the
rem window can be closed. It is independent of AutoScriptor and of the emulator.
".venv\Scripts\python.exe" -X utf8 "scripts\qq-notify\start.py" %*
set "RESULT=%ERRORLEVEL%"

if not "%RESULT%"=="0" (
    echo.
    echo   Could not start. Read the message above.
    pause
)
exit /b %RESULT%
