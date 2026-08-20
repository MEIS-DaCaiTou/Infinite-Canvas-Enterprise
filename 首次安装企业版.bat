@echo off
setlocal
chcp 65001 >nul
set "PYEXE=%~dp0python\python.exe"
if exist "%PYEXE%" goto python_ready
echo {"code":"INSTALL_PYTHON_MISSING","status":"blocked"}
set "RESULT=2"
goto finish
:python_ready
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0enterprise\runtime\fixed_python_preflight.ps1" -AppRoot "%~dp0." -Command start
if not errorlevel 1 goto run_installer
set "RESULT=%ERRORLEVEL%"
goto finish
:run_installer
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONNOUSERSITE=1"
"%PYEXE%" -I -B "%~dp0enterprise\install_cli.py"
set "RESULT=%ERRORLEVEL%"
:finish
if "%RESULT%"=="0" (
  echo 首次安装已完成。请从安装目录使用“启动企业版.bat”。
) else (
  echo 首次安装未完成。请查看上方稳定错误码后重试。
)
echo 按任意键关闭此窗口。
pause >nul
exit /b %RESULT%
