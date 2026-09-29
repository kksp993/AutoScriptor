@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0..\.."

echo.
echo   QQ notification setup - run this once.
echo.

if not exist ".venv\Scripts\python.exe" (
    echo   Missing .venv Python. Run scripts\install.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -X utf8 "scripts\qq-notify\setup.py" %*
set "RESULT=%ERRORLEVEL%"

echo.
if not "%RESULT%"=="0" echo   Setup did not finish. Read the message above.
pause
exit /b %RESULT%
