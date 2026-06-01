@echo off
cd /d "%~dp0"

echo ============================================================
echo   Stop Infinite Canvas Enterprise
echo ============================================================
echo.

for /f "tokens=5" %%P in ('netstat -ano -p tcp ^| findstr /R /C:":8000 .*LISTENING" /C:":3001 .*LISTENING"') do (
  echo Stopping PID %%P
  taskkill /PID %%P /F >nul 2>&1
)

echo.
echo Done. If no PID was shown, no enterprise service was listening.
echo Press any key to close this window...
pause >nul
exit /b 0
