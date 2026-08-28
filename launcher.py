from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
def _read_platform_version() -> str:
    vf = BASE_DIR / "VERSION.txt"
    try:
        v = vf.read_text(encoding="utf-8", errors="ignore").strip()
        if v:
            return v
    except Exception:
        pass
    return os.environ.get("MC_PLATFORM_VERSION", "42.14.0").strip() or "42.14.0"

VERSION = _read_platform_version()
PORT = int(os.environ.get("MC_PORT", "8010"))
HOST = os.environ.get("MC_HOST", "0.0.0.0")
REQ = BASE_DIR / "requirements.txt"
TORCH_VERSION = "2.12.1"
TORCHVISION_VERSION = "0.27.1"
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"


def say(text=""):
    print(text, flush=True)


def runtime_dir() -> Path:
    custom = os.environ.get("MC_TRAIN_VENV_DIR", "").strip()
    if custom:
        return Path(custom).expanduser()
    py_tag = f"py{sys.version_info.major}{sys.version_info.minor}"
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        # Separate runtime per patch release so a broken previous env can never poison startup.
        return root / "XJAlgo" / "runtime" / "v42_0_0" / py_tag
    return Path.home() / ".cache" / "xj-algo" / "runtime" / "v42_0_0" / py_tag


def venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def req_hash() -> str:
    return hashlib.sha256(REQ.read_bytes()).hexdigest()


def get_version(url: str, timeout=1.2):
    try:
        with urllib.request.urlopen(url + "/api/system/version", timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
            return str(data.get("version") or ""), data
    except Exception:
        return "", None




def api_json(url: str, path: str, method: str = "GET", payload=None, timeout: float = 3.0):
    try:
        data=None; headers={"Accept":"application/json"}
        if payload is not None:
            data=json.dumps(payload,ensure_ascii=False).encode("utf-8"); headers["Content-Type"]="application/json"
        req=urllib.request.Request(url+path,data=data,headers=headers,method=method)
        with urllib.request.urlopen(req,timeout=timeout) as r:return json.loads(r.read().decode("utf-8","ignore") or "{}")
    except Exception:return None

def wait_bootstrap(url: str, proc=None, timeout_seconds: int = 900):
    say("[5/5] 预加载平台数据与训练环境...")
    api_json(url,"/api/v53/bootstrap/start",method="POST",payload={"force":False},timeout=3.0)
    deadline=time.time()+timeout_seconds; last=None
    while time.time()<deadline:
        if proc is not None and proc.poll() is not None:raise RuntimeError(f"服务进程已退出，退出码 {proc.returncode}")
        st=api_json(url,"/api/v53/bootstrap/status",timeout=2.0)
        if st:
            status=str(st.get("status") or ""); progress=int(st.get("progress") or 0); stage=str(st.get("stage") or "正在准备"); message=str(st.get("message") or ""); key=(status,progress,stage,message)
            if key!=last:say(f"      [{progress:3d}%] {stage}"+(f"：{message}" if message else "")); last=key
            if status=="ready":say("[OK] 数据、标注索引、算法版本与训练环境已加载完成。"); return st
            if status=="failed":raise RuntimeError("平台数据预加载失败："+(message or str(st.get("error") or "未知错误")))
        time.sleep(.45)
    raise RuntimeError("平台数据预加载超时，请查看上方具体阶段。")

def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def run_check(py: Path, name: str, code: str, timeout=90):
    try:
        cp = subprocess.run(
            [str(py), "-c", code],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
        out = (cp.stdout or "").strip()
        err = (cp.stderr or "").strip()
        return cp.returncode == 0, out, err
    except Exception as e:
        return False, "", repr(e)


def diagnostic_checks(py: Path, verbose=True) -> bool:
    checks = [
        ("FastAPI", "import fastapi; print(fastapi.__version__)"),
        ("Uvicorn", "import uvicorn; print(uvicorn.__version__)"),
        ("Pillow", "import PIL; print(PIL.__version__)"),
        ("PyYAML", "import yaml; print(yaml.__version__)"),
        ("Requests", "import requests; print(requests.__version__)"),
        ("OpenCV", "import cv2; print(cv2.__version__)"),
        ("PyTorch", "import torch; x=torch.rand(2,2); print(torch.__version__, x.shape)"),
        ("TorchVision", "import torch, torchvision; from torchvision.ops import nms; b=torch.tensor([[0.,0.,10.,10.],[1.,1.,9.,9.]]); s=torch.tensor([.9,.8]); print(torchvision.__version__, nms(b,s,.5).tolist())"),
        ("Ultralytics", "import ultralytics; from ultralytics import YOLO; print(ultralytics.__version__)"),
        ("ONNX", "import onnx; print(onnx.__version__)"),
        ("ONNXSlim", "import onnxslim; print(getattr(onnxslim,'__version__','OK'))"),
    ]
    ok_all = True
    for name, code in checks:
        ok, out, err = run_check(py, name, code)
        if ok:
            if verbose:
                say(f"  [OK] {name}: {out.splitlines()[-1] if out else 'OK'}")
        else:
            ok_all = False
            say(f"  [FAIL] {name}")
            details = err or out or "未知导入错误"
            # Keep console readable while still exposing the real root cause.
            lines = details.splitlines()
            for line in lines[-12:]:
                say(f"         {line}")
    return ok_all


def _pip_common(py: Path):
    return [
        str(py), "-m", "pip", "install",
        "--disable-pip-version-check",
        "--prefer-binary",
        "--retries", os.environ.get("MC_PIP_RETRIES", "3"),
        "--timeout", os.environ.get("MC_PIP_TIMEOUT", "30"),
    ]


def _run_install(cmd, label: str) -> bool:
    say(f"      -> {label}")
    try:
        subprocess.check_call(cmd, cwd=str(BASE_DIR))
        return True
    except subprocess.CalledProcessError as e:
        say(f"         [WARN] {label}失败，退出码：{e.returncode}")
        return False


def _torch_pair_ready(py: Path) -> bool:
    code = (
        "import torch, torchvision; "
        f"assert torch.__version__.split('+')[0]=='{TORCH_VERSION}', torch.__version__; "
        f"assert torchvision.__version__.split('+')[0]=='{TORCHVISION_VERSION}', torchvision.__version__; "
        "from torchvision.ops import nms; print(torch.__version__, torchvision.__version__)"
    )
    ok, out, _ = run_check(py, "PyTorch", code, timeout=60)
    if ok:
        say(f"      PyTorch 已可用，跳过重复下载：{out.splitlines()[-1] if out else 'OK'}")
    return ok


def install_known_good_torch(py: Path):
    # PyTorch is large. Reuse an already-good installation first, especially after a previous
    # startup failed later while installing small web dependencies.
    if _torch_pair_ready(py):
        return

    say(f"      安装稳定 PyTorch CPU 组合：torch {TORCH_VERSION} + torchvision {TORCHVISION_VERSION}")
    base = _pip_common(py) + ["--upgrade", "--force-reinstall"]
    packages = [f"torch=={TORCH_VERSION}", f"torchvision=={TORCHVISION_VERSION}"]

    attempts = [
        ("PyTorch 官方 CPU 源", base + packages + ["--index-url", TORCH_CPU_INDEX]),
        # Some Windows/enterprise networks perform TLS interception. A second try against the
        # same official hosts with pip's trusted-host compatibility mode is safer than switching
        # PyTorch binaries to an unrelated third-party mirror.
        (
            "PyTorch 官方 CPU 源（TLS 兼容模式）",
            base + packages + [
                "--index-url", TORCH_CPU_INDEX,
                "--trusted-host", "download.pytorch.org",
                "--trusted-host", "download-r2.pytorch.org",
            ],
        ),
    ]
    for label, cmd in attempts:
        if _run_install(cmd, label) and _torch_pair_ready(py):
            return

    raise RuntimeError(
        "PyTorch CPU 组件下载失败。请检查代理/防火墙是否拦截 download.pytorch.org，"
        "或稍后重新运行 start.bat；已下载成功的文件会继续使用 pip 缓存。"
    )


def install_requirements(py: Path):
    # Install the known-good torch pair first. requirements.txt pins the same versions, so pip
    # will keep them satisfied instead of downloading them again.
    install_known_good_torch(py)

    base = _pip_common(py) + ["-r", str(REQ)]
    custom = os.environ.get("MC_PIP_INDEX_URL", "").strip()
    attempts = []
    if custom:
        attempts.append(("自定义 Python 包源", base + ["--index-url", custom]))

    # First honor the user's/system pip configuration. Then fail over to two HTTPS mirrors.
    attempts.extend([
        ("默认 Python 包源", base),
        ("阿里云 PyPI 镜像", base + ["--index-url", "https://mirrors.aliyun.com/pypi/simple/"]),
        ("清华 TUNA PyPI 镜像", base + ["--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple/"]),
    ])

    for label, cmd in attempts:
        if _run_install(cmd, label):
            return

    raise RuntimeError(
        "平台 Python 依赖安装失败：默认 PyPI、阿里云镜像、清华镜像均不可用。"
        "这通常是当前网络、代理、防火墙或 HTTPS/TLS 拦截导致，不是 FastAPI 版本不存在。"
    )


def ensure_runtime() -> Path:
    if not ((3, 10) <= sys.version_info[:2] <= (3, 12)):
        say(f"[ERROR] 当前 Python {sys.version_info.major}.{sys.version_info.minor} 不在本平台验证范围 3.10-3.12。")
        say("请安装 64 位 Python 3.12 后重新运行 start.bat。")
        raise SystemExit(2)

    if os.environ.get("MC_SKIP_VENV") == "1":
        py = Path(sys.executable)
        say("[1/5] 使用当前 Python（MC_SKIP_VENV=1）")
        say("[2/5] 跳过虚拟环境安装。")
        say("[3/5] 校验核心组件...")
        if not diagnostic_checks(py, verbose=True):
            raise SystemExit(3)
        return py

    root = runtime_dir()
    py = venv_python(root)
    marker = root / ".requirements.sha256"
    created = False
    if not py.exists():
        say(f"[1/5] 创建短路径运行环境：{root}")
        root.parent.mkdir(parents=True, exist_ok=True)
        venv.EnvBuilder(with_pip=True, clear=False).create(root)
        created = True
    else:
        say(f"[1/5] 使用运行环境：{root}")

    expected = req_hash()
    marker_ok = marker.exists() and marker.read_text(encoding="utf-8", errors="ignore").strip() == expected

    if marker_ok:
        say("[2/5] 平台依赖版本记录已存在，先进行实际可用性检测。")
        say("[3/5] 校验核心组件...")
        if diagnostic_checks(py, verbose=True):
            return py
        say("[WARN] 现有环境检测失败，将自动重建运行环境并修复，不需要手工删除。")
        try:
            shutil.rmtree(root)
        except Exception as e:
            say(f"[ERROR] 无法自动删除损坏运行环境：{e}")
            say(f"请关闭占用该目录的程序后删除：{root}")
            raise SystemExit(3)
        root.parent.mkdir(parents=True, exist_ok=True)
        venv.EnvBuilder(with_pip=True, clear=False).create(root)
        py = venv_python(root)
        created = True

    say("[2/5] 安装/修复平台依赖（支持网络失败自动换源；已安装 PyTorch 会直接复用）...")
    try:
        install_requirements(py)
    except (subprocess.CalledProcessError, RuntimeError) as e:
        say(f"[ERROR] 依赖安装失败：{e}")
        say(f"运行环境：{root}")
        say("提示：无需删除已经下载成功的 PyTorch；修复网络后重新运行即可继续。")
        raise SystemExit(2)

    say("[3/5] 校验核心组件...")
    if not diagnostic_checks(py, verbose=True):
        say()
        say("[ERROR] 依赖已安装，但至少一个组件无法真正导入。上面已显示具体失败组件和原始错误。")
        say(f"运行环境：{root}")
        say("如果失败项是 PyTorch 且包含 DLL load failed / WinError 126，请安装 Microsoft Visual C++ 2015-2022 x64 运行库后重试。")
        raise SystemExit(3)

    marker.write_text(expected, encoding="utf-8")
    return py


def main():
    say("===============================================")
    say(f"Changlian Cloud Algorithm Training v{VERSION}")
    say("===============================================")
    say()

    url = f"http://127.0.0.1:{PORT}"
    if port_open(PORT):
        ver, _ = get_version(url)
        if ver == VERSION:
            say(f"[INFO] v{VERSION} 已在运行：{url}")
            wait_bootstrap(url, proc=None)
            webbrowser.open(url + f"/?v={VERSION}")
            return 0
        if ver:
            say(f"[ERROR] 端口 {PORT} 正被旧平台 v{ver} 占用。")
            say("请关闭旧版启动窗口后重新运行本版本，避免浏览器看到旧界面。")
        else:
            say(f"[ERROR] 端口 {PORT} 已被其他程序占用。可设置 MC_PORT 后再启动。")
        return 4

    py = ensure_runtime()
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["MC_PLATFORM_VERSION"] = VERSION

    say(f"[4/5] 启动服务：{url}")
    say("转换入口：左侧菜单 → 部署中心 → 部署转换")
    proc = subprocess.Popen([
        str(py), "-m", "uvicorn", "app:app", "--host", HOST, "--port", str(PORT)
    ], cwd=str(BASE_DIR), env=env)
    try:
        deadline = time.time() + 35
        mismatch_seen = 0
        while time.time() < deadline:
            ver, _ = get_version(url, timeout=1.0)
            if ver == VERSION:
                say(f"[OK] 服务已启动：{url}")
                wait_bootstrap(url, proc=proc)
                webbrowser.open(url + f"/?v={VERSION}")
                break
            if ver:
                mismatch_seen += 1
                if mismatch_seen >= 3:
                    raise RuntimeError(
                        f"服务已经启动，但版本不一致：启动器 v{VERSION}，服务端 v{ver}。"
                        "请确认当前目录文件来自同一个版本，或重新解压完整发布包。"
                    )
            if proc.poll() is not None:
                raise RuntimeError(f"服务进程已退出，退出码 {proc.returncode}")
            time.sleep(0.5)
        else:
            raise RuntimeError("服务启动超时，请查看上方 Uvicorn 日志。")
        return proc.wait()
    except KeyboardInterrupt:
        say("\n正在停止服务...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        return 0
    except Exception as e:
        say(f"[ERROR] {e}")
        if proc.poll() is None:
            proc.terminate()
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
