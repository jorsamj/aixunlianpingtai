import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_task_worker_import_does_not_import_fastapi_app():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys,task_worker; print('app' in sys.modules)",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_task_worker_check_uses_shared_data_root_without_web(tmp_path):
    data_dir = tmp_path / "worker data with spaces"
    environment = os.environ.copy()
    environment["MC_TRAIN_DATA_DIR"] = str(data_dir)
    result = subprocess.run(
        [sys.executable, "task_worker.py", "--check", "--roles", "video"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert Path(report["data_dir"]) == data_dir.resolve()
    assert Path(report["database"]).is_file()
    assert report["web_imported"] is False
