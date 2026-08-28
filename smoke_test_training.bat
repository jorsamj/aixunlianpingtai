@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
for /f "delims=" %%i in ('python -c "import launcher; print(launcher.runtime_dir())"') do set "RT=%%i"
set "PY=%RT%\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] 平台运行环境不存在，请先成功运行一次 start.bat。
  pause
  exit /b 1
)
echo 正在执行1轮最小YOLO真实训练冒烟测试，请稍候...
"%PY%" smoke_test_training.py
if errorlevel 1 (
  echo.
  echo [FAIL] 训练冒烟测试失败，请把上面的完整错误发回。
  pause
  exit /b 2
)
echo.
echo [OK] 训练冒烟测试通过：真实完成了1轮训练并重新加载best.pt。
pause
endlocal
