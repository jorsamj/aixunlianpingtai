import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository, TaskStatus


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


def test_task_worker_process_completes_real_video_without_http_server(tmp_path):
    data_dir = tmp_path / "standalone data"
    project_dir = data_dir / "projects" / "project-1"
    (project_dir / "uploads").mkdir(parents=True)
    (project_dir / "annotations").mkdir(parents=True)
    repository = TaskRepository(data_dir / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(data_dir / "task_runtime" / "artifacts")
    task_id = "standalone-video"
    source = artifacts.artifact_path(task_id, "inputs/source.avi")
    source.parent.mkdir(parents=True)
    writer = cv2.VideoWriter(
        str(source),
        cv2.VideoWriter_fourcc(*"MJPG"),
        5.0,
        (32, 24),
    )
    assert writer.isOpened()
    for index in range(8):
        writer.write(np.full((24, 32, 3), index * 20, dtype=np.uint8))
    writer.release()
    artifacts.atomic_write_json(
        task_id,
        "payload.json",
        {
            "source_ref": "inputs/source.avi",
            "original_name": "source.avi",
            "mode": "fixed_count",
            "fixed_count": 3,
            "dataset_id": "default",
            "split": "unassigned",
            "backend": "opencv",
        },
    )
    repository.create(
        TaskRecord.new(
            task_id,
            "project-1",
            TaskKind.VIDEO_FRAMES,
            "payload.json",
            "cpu:video",
            required_capabilities=("opencv",),
        )
    )
    result = subprocess.run(
        [
            sys.executable,
            "task_worker.py",
            "--data-dir",
            str(data_dir),
            "--roles",
            "video",
            "--once",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    completed = repository.get(task_id)
    assert completed.status is TaskStatus.SUCCEEDED
    assert artifacts.read_json(task_id, completed.result_ref)["extracted_frames"] == 3
