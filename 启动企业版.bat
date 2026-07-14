@echo off
cd /d "%~dp0"

set "PYEXE=%~dp0python\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"

"%PYEXE%" -m enterprise.runtime.cli start --app-root "%~dp0"
exit /b %errorlevel%
