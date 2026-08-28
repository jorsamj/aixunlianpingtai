@echo off
chcp 65001 > nul
setlocal EnableExtensions
cd /d "%~dp0"

echo ===============================================
echo 畅联云算法远程训练服务器 v42.12.0
echo ===============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] 未检测到 Python。
  pause
  exit /b 1
)

if "%MC_REMOTE_TRAIN_PYTHON%"=="" (
  for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)"') do set "MC_REMOTE_TRAIN_PYTHON=%%i"
)

echo [1/4] 检查训练 Python: %MC_REMOTE_TRAIN_PYTHON%
"%MC_REMOTE_TRAIN_PYTHON%" -c "import torch,torchvision,ultralytics; print('torch=',torch.__version__,'torchvision=',torchvision.__version__,'ultralytics=',ultralytics.__version__,'cuda=',torch.cuda.is_available(),'gpu_count=',torch.cuda.device_count())"
if errorlevel 1 (
  echo.
  echo [ERROR] 该 Python 不能用于 Ultralytics 训练。
  echo 请先在训练服务器准备好 PyTorch/Ultralytics 环境，然后设置：
  echo set MC_REMOTE_TRAIN_PYTHON=D:\your_env\Scripts\python.exe
  echo 再运行本脚本。平台不会自动覆盖你的 CUDA / PyTorch 环境。
  pause
  exit /b 2
)

if not exist .remote_web_venv (
  echo [2/4] 创建远程服务 Web 环境...
  python -m venv .remote_web_venv
) else (
  echo [2/4] 使用远程服务 Web 环境...
)
call .remote_web_venv\Scripts\activate.bat

echo [3/4] 安装远程服务依赖（不会安装/覆盖 Torch）...
python -m pip install -r remote_web_requirements.txt
if errorlevel 1 (
  echo [ERROR] Web 服务依赖安装失败。
  pause
  exit /b 3
)

echo [4/4] 启动远程训练服务 http://0.0.0.0:8020
python -m uvicorn remote_train_server:app --host 0.0.0.0 --port 8020
pause
endlocal
