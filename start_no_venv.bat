@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "MC_SKIP_VENV=1"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
python launcher.py
if errorlevel 1 pause
endlocal
