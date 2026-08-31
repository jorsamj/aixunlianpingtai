import json
import shutil
from pathlib import Path

import cv2
import numpy as np

from platform_core.material_store import MaterialStore
from platform_core.task_runtime import (
    ArtifactStore,
    Scheduler,
    TaskKind,
    TaskRecord,
    TaskRepository,
    TaskStatus,
)
from platform_core.video_tasks import VideoFrameHandler


def create_video(path: Path, frames=12, fps=6.0):
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        fps,
        (64, 48),
    )
    assert writer.isOpened()
    for index in range(frames):
        writer.write(np.full((48, 64, 3), index * 15, dtype=np.uint8))
    writer.release()


def test_worker_extracts_real_video_into_material_library_and_recovers_idempotently(tmp_path):
    data_dir = tmp_path / "data"
    project_dir = data_dir / "projects" / "project-1"
    (project_dir / "uploads").mkdir(parents=True)
    (project_dir / "annotations").mkdir(parents=True)
    repository = TaskRepository(data_dir / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(data_dir / "task_runtime" / "artifacts")
    source = tmp_path / "source.avi"
    create_video(source)
    task_id = "video-task-1"
    task_source = artifacts.artifact_path(task_id, "inputs/source.avi")
    task_source.parent.mkdir(parents=True)
    shutil.copy2(source, task_source)
    artifacts.atomic_write_json(
        task_id,
        "payload.json",
        {
            "source_ref": "inputs/source.avi",
            "original_name": "source.avi",
            "mode": "fixed_count",
            "fixed_count": 5,
            "interval_seconds": None,
            "extract_fps": None,
            "max_frames": None,
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
    scheduler = Scheduler(
        repository,
        artifacts,
        "video-worker",
        {TaskKind.VIDEO_FRAMES: VideoFrameHandler(data_dir)},
        {"opencv"},
    )

    assert scheduler.run_once() is True
    completed = repository.get(task_id)
    assert completed.status is TaskStatus.SUCCEEDED
    result = artifacts.read_json(task_id, completed.result_ref)
    assert result["extracted_frames"] == 5
    assert not Path(result["output_ref"]).is_absolute()
    rows = MaterialStore(project_dir / "images.json").read()
    assert rows.revision == 1
    assert len(rows.rows) == 5
    assert all((project_dir / "uploads" / row["stored_name"]).stat().st_size > 0 for row in rows.rows)
    assert all((project_dir / "annotations" / f"{row['id']}.json").is_file() for row in rows.rows)

    repository.retry(task_id)
    assert scheduler.run_once() is True
    recovered = MaterialStore(project_dir / "images.json").read()
    assert recovered.revision == 1
    assert {row["id"] for row in recovered.rows} == {row["id"] for row in rows.rows}


def test_corrupt_video_task_is_failed_with_no_material_rows(tmp_path):
    data_dir = tmp_path / "data"
    project_dir = data_dir / "projects" / "project-1"
    project_dir.mkdir(parents=True)
    repository = TaskRepository(data_dir / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(data_dir / "task_runtime" / "artifacts")
    task_id = "bad-video"
    source = artifacts.artifact_path(task_id, "inputs/bad.mp4")
    source.parent.mkdir(parents=True)
    source.write_bytes(b"broken")
    artifacts.atomic_write_json(
        task_id,
        "payload.json",
        {
            "source_ref": "inputs/bad.mp4",
            "original_name": "bad.mp4",
            "mode": "fixed_count",
            "fixed_count": 2,
            "dataset_id": "default",
            "split": "unassigned",
            "backend": "opencv",
        },
    )
    repository.create(
        TaskRecord.new(task_id, "project-1", TaskKind.VIDEO_FRAMES, "payload.json", "cpu:video")
    )
    Scheduler(
        repository,
        artifacts,
        "video-worker",
        {TaskKind.VIDEO_FRAMES: VideoFrameHandler(data_dir)},
        set(),
    ).run_once()
    failed = repository.get(task_id)
    assert failed.status is TaskStatus.FAILED
    assert "video" in failed.error.lower()
    assert MaterialStore(project_dir / "images.json").count() == 0
