@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found.
  pause
  exit /b 1
)
echo [1/2] Installing/checking remote web service dependencies in the CURRENT vendor Python...
python -m pip install --prefer-binary -r remote_web_requirements.txt
if errorlevel 1 (
  echo [ERROR] Remote web dependencies installation failed.
  pause
  exit /b 1
)
echo [2/2] Starting deployment conversion service on port 8030...
python -m uvicorn remote_deploy_server:app --host 0.0.0.0 --port 8030
pause
endlocal
