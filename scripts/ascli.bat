@echo off
setlocal
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0..;%PYTHONPATH%"
if not exist "%~dp0..\.venv\Scripts\python.exe" (
  echo Missing project virtualenv. Run scripts\install.bat python first. 1>&2
  exit /b 1
)
"%~dp0..\.venv\Scripts\python.exe" -X utf8 -m AutoScriptor.cli %*
set "ASCLI_EXIT=%ERRORLEVEL%"
exit /b %ASCLI_EXIT%
