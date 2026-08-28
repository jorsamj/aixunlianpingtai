@echo off
chcp 65001 > nul
REM 这是示例脚本：如果你的 human_service.py 放在 D:\lab\yolosuanfa 下，可以直接用。
REM 如果路径不一样，请修改下面这一行。
cd /d D:\lab\yolosuanfa
where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 没有检测到 Python。
  pause
  exit /b 1
)
python -m uvicorn human_service:app --host 127.0.0.1 --port 8801
pause
