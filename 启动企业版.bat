@echo off
cd /d "%~dp0"

set "PYEXE=%~dp0python\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"

"%PYEXE%" "%~dp0enterprise\launcher.py"
exit /b %errorlevel%
