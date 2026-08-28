@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
python -c "import launcher; p=launcher.venv_python(launcher.runtime_dir()); print('Runtime:', p); print(); raise SystemExit(0 if p.exists() and launcher.diagnostic_checks(p, True) else 1)"
echo.
pause
endlocal
