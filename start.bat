@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found. Install Python 3.10 - 3.12 first.
  pause
  exit /b 1
)
python launcher.py
if errorlevel 1 (
  echo.
  echo [ERROR] Platform startup failed. Review the message above.
  pause
)
endlocal
