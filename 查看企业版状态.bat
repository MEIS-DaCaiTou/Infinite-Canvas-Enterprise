@echo off
cd /d "%~dp0"

set "PYEXE=%~dp0python\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"
set "APP_ROOT=%~dp0."

"%PYEXE%" -m enterprise.runtime.cli status --app-root "%APP_ROOT%"
exit /b %errorlevel%
