import json
import shutil
from pathlib import Path

import cv2
import numpy as np

import platform_core.video_tasks as video_tasks
from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_store import MaterialStore
from platform_core.task_runtime import (
    ArtifactStore,
    Scheduler,
    TaskKind,
    TaskRecord,
    TaskRepository,
    TaskStatus,
    WorkerContext,
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

    annotations = AnnotationRepository(project_dir)
    first_annotations = [annotations.get(row["id"]) for row in rows.rows]
    assert all(item["annotation_state"] == "unannotated" for item in first_annotations)
    assert all(item["version"] == 1 for item in first_annotations)
    assert list((project_dir / "annotations").glob("*.json")) == []

    repository.retry(task_id)
    assert scheduler.run_once() is True
    recovered = MaterialStore(project_dir / "images.json").read()
    assert recovered.revision == 1
    assert {row["id"] for row in recovered.rows} == {row["id"] for row in rows.rows}
    recovered_annotations = [annotations.get(row["id"]) for row in recovered.rows]
    assert all(item["annotation_state"] == "unannotated" for item in recovered_annotations)
    assert all(item["version"] == 1 for item in recovered_annotations)
    assert list((project_dir / "annotations").glob("*.json")) == []


def test_worker_retry_resumes_extraction_checkpoint_without_rewriting_prefix(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    project_dir = data_dir / "projects" / "project-1"
    (project_dir / "uploads").mkdir(parents=True)
    repository = TaskRepository(data_dir / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(data_dir / "task_runtime" / "artifacts")
    source = tmp_path / "resume-source.avi"
    create_video(source)
    task_id = "video-resume-1"
    task_source = artifacts.artifact_path(task_id, "inputs/source.avi")
    task_source.parent.mkdir(parents=True)
    shutil.copy2(source, task_source)
    artifacts.atomic_write_json(
        task_id,
        "payload.json",
        {
            "source_ref": "inputs/source.avi",
            "original_name": "resume-source.avi",
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

    original_save_checkpoint = WorkerContext.save_checkpoint
    crashed = {"value": False}

    def crash_after_second_frame(self, value):
        original_save_checkpoint(self, value)
        if (
            not crashed["value"]
            and value.get("stage") == "extracting"
            and int(value.get("extracted_frames") or 0) == 2
        ):
            crashed["value"] = True
            raise RuntimeError("simulated worker crash after frame checkpoint")

    monkeypatch.setattr(WorkerContext, "save_checkpoint", crash_after_second_frame)
    assert scheduler.run_once() is True
    failed = repository.get(task_id)
    assert failed.status is TaskStatus.FAILED
    checkpoint = artifacts.read_json(task_id, "checkpoints/worker.json")
    assert checkpoint["stage"] == "extracting"
    assert checkpoint["extracted_frames"] == 2
    frames_dir = artifacts.artifact_path(task_id, "frames")
    existing = sorted(frames_dir.glob("frame_*.jpg"))
    assert len(existing) == 2
    existing_bytes = {path.name: path.read_bytes() for path in existing}

    monkeypatch.setattr(WorkerContext, "save_checkpoint", original_save_checkpoint)
    original_imwrite = video_tasks.cv2.imwrite
    resumed_writes = []

    def tracking_imwrite(path, frame):
        resumed_writes.append(Path(path).name)
        return original_imwrite(path, frame)

    monkeypatch.setattr(video_tasks.cv2, "imwrite", tracking_imwrite)
    repository.retry(task_id)
    assert scheduler.run_once() is True

    completed = repository.get(task_id)
    assert completed.status is TaskStatus.SUCCEEDED
    assert len(resumed_writes) == 3
    assert {path.name: path.read_bytes() for path in existing} == existing_bytes
    result = artifacts.read_json(task_id, completed.result_ref)
    assert result["extracted_frames"] == 5
    assert MaterialStore(project_dir / "images.json").count() == 5
    final_checkpoint = artifacts.read_json(task_id, "checkpoints/worker.json")
    assert final_checkpoint["stage"] == "committed"
    assert final_checkpoint["extracted_frames"] == 5


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
