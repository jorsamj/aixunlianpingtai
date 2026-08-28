@echo off
chcp 65001 > nul
set BASE=D:\lab\yolosuanfa\Ultralytics
mkdir "%BASE%" 2>nul
cd /d "%BASE%"
where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 没有检测到 Python。
  pause
  exit /b 1
)
if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -U pip
pip install -U ultralytics -i https://pypi.tuna.tsinghua.edu.cn/simple
yolo checks
pause
