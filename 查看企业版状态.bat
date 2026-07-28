@echo off
setlocal
chcp 65001 >nul
set "PYEXE=%~dp0python\python.exe"
if exist "%PYEXE%" goto python_ready
echo {"code":"PORTABLE_PYTHON_MISSING","status":"blocked"}
exit /b 2
:python_ready
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONNOUSERSITE=1"
"%PYEXE%" -I -B "%~dp0enterprise\runtime\launcher.py" portable status
exit /b %errorlevel%
