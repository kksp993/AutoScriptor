@echo off
setlocal
echo Standalone QQ robot setup - run this on the ROBOT computer.
echo Requires administrator rights for a single-IP firewall rule.
echo Third-party QQ automation has account risks. Use a dedicated account.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0robot.ps1" -Action install %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" echo Installation failed. Read the error above.
pause
exit /b %RESULT%
