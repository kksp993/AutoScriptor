@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0..\.."

".venv\Scripts\python.exe" -X utf8 "backend\core\qq_bot.py" stop
echo.
echo   Done. Run 2-start.cmd to start it again.
pause
exit /b 0
