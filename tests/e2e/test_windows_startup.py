import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def read_json(url: str, timeout: float = 2.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def test_windows_server_reaches_ready_and_serves_home(tmp_path: Path):
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "MC_TRAIN_DATA_DIR": str((tmp_path / "data").resolve()),
        "MC_PLATFORM_VERSION": "e2e-test",
        "MC_PORT": str(port),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        deadline = time.monotonic() + 90
        status = {}
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                raise AssertionError(f"server exited with {process.returncode}:\n{output}")
            try:
                status = read_json(f"{base_url}/api/v53/bootstrap/status")
                if status.get("status") == "ready":
                    break
                if status.get("status") == "failed":
                    raise AssertionError(status)
            except OSError:
                pass
            time.sleep(0.1)
        assert status.get("status") == "ready", status
        assert status.get("active_project_id")
        with urllib.request.urlopen(f"{base_url}/", timeout=3) as response:
            assert response.status == 200
            assert "畅联云算法训练" in response.read().decode("utf-8")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

