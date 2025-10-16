@echo off
setlocal
rem 规范化为仓库根目录（当前文件位于 AutoScriptor\installer）
set SCRIPT_DIR=%~dp0
pushd "%SCRIPT_DIR%..\.." >nul
set ROOT=%CD%\

rem 优先使用已有 .venv，否则由编排器自动创建
set VENV_PY=%ROOT%.venv\Scripts\python.exe

rem 选择目标（默认 webui，可传入 webui/cli/install-only）
set TARGET=%1
if "%TARGET%"=="" set TARGET=webui

rem 若存在 venv 则直接用 venv 运行安装器；否则尝试用系统 Python 启动，由安装器创建 venv
if exist "%VENV_PY%" (
  "%VENV_PY%" AutoScriptor\installer\installer.py %TARGET%
) else (
  where py >nul 2>nul && ( py -3 AutoScriptor\installer\installer.py %TARGET% ) || ( python AutoScriptor\installer\installer.py %TARGET% )
)

set EXITCODE=%ERRORLEVEL%
popd >nul
exit /b %EXITCODE%