from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
import pytest

import platform_core.video_tasks as video_tasks
from platform_core.material_repository import MaterialRepository
from platform_core.storage.models import ObjectMetadata
from platform_core.task_runtime import (
    ArtifactStore,
    ExecutionFencedError,
    FencedTaskRepository,
    TaskKind,
    TaskRecord,
    WorkerContext,
)
from platform_core.video_tasks import ExtractedFrame, VideoExtractionResult, VideoFrameHandler


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_context(tmp_path: Path):
    data_dir = tmp_path / "data"
    repository = FencedTaskRepository(data_dir / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(data_dir / "task_runtime" / "artifacts")
    task_id = "video-commit-fencing"
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
    source = artifacts.artifact_path(task_id, "inputs/source.avi")
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"fake-video")
    repository.create(
        TaskRecord.new(
            task_id,
            "project-1",
            TaskKind.VIDEO_FRAMES,
            "payload.json",
            "cpu:video",
        )
    )
    lease = repository.claim_next("video-worker", [TaskKind.VIDEO_FRAMES], set())
    assert lease is not None
    return data_dir, repository, WorkerContext(lease.task, lease, repository, artifacts)


def _fake_extraction(tmp_path: Path) -> VideoExtractionResult:
    frame_dir = tmp_path / "fake-frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for index in range(3):
        path = frame_dir / f"frame-{index}.jpg"
        assert cv2.imwrite(str(path), np.full((16, 16, 3), index * 40, dtype=np.uint8))
        frames.append(
            ExtractedFrame(
                path=str(path),
                source_frame_index=index,
                timestamp_seconds=float(index),
                sha256=_sha256(path),
                size_bytes=path.stat().st_size,
            )
        )
    return VideoExtractionResult(
        source="fake-video",
        output_dir=str(frame_dir),
        backend="opencv",
        duration_seconds=3.0,
        expected_frames=3,
        extracted_frames=3,
        frames=tuple(frames),
    )


def _install_fake_extraction(monkeypatch, extraction: VideoExtractionResult) -> None:
    monkeypatch.setattr(video_tasks, "extract_video", lambda *args, **kwargs: extraction)


def test_video_commit_stops_before_second_upload_after_cancel(tmp_path: Path, monkeypatch):
    data_dir, repository, context = _make_context(tmp_path)
    extraction = _fake_extraction(tmp_path)
    _install_fake_extraction(monkeypatch, extraction)
    uploads: list[str] = []

    def upload_and_cancel(self, source_id, object_key, source, *, content_type="application/octet-stream"):
        source_path = Path(source)
        uploads.append(object_key)
        if len(uploads) == 1:
            repository.request_cancel(context.task.task_id)
        return ObjectMetadata(
            key=object_key,
            size_bytes=source_path.stat().st_size,
            etag=f"etag-{len(uploads)}",
            content_type=content_type,
            sha256=_sha256(source_path),
        )

    monkeypatch.setattr(video_tasks.StorageManager, "upload_object", upload_and_cancel)

    with pytest.raises(InterruptedError, match="cancel"):
        VideoFrameHandler(data_dir).run(context)

    assert len(uploads) == 1
    materials = MaterialRepository(data_dir / "projects" / "project-1").read().rows
    assert materials == []
    assert not context._artifact_store.artifact_path(context.task.task_id, "result.json").exists()


def test_video_commit_stale_execution_cannot_continue_business_writes(tmp_path: Path, monkeypatch):
    data_dir, _repository, context = _make_context(tmp_path)
    extraction = _fake_extraction(tmp_path)
    _install_fake_extraction(monkeypatch, extraction)
    uploads: list[str] = []

    def upload_and_fence(self, source_id, object_key, source, *, content_type="application/octet-stream"):
        source_path = Path(source)
        uploads.append(object_key)
        if len(uploads) == 1:
            context.mark_lease_lost()
        return ObjectMetadata(
            key=object_key,
            size_bytes=source_path.stat().st_size,
            etag=f"etag-{len(uploads)}",
            content_type=content_type,
            sha256=_sha256(source_path),
        )

    monkeypatch.setattr(video_tasks.StorageManager, "upload_object", upload_and_fence)

    with pytest.raises(ExecutionFencedError):
        VideoFrameHandler(data_dir).run(context)

    assert len(uploads) == 1
    materials = MaterialRepository(data_dir / "projects" / "project-1").read().rows
    assert materials == []
    annotations = data_dir / "projects" / "project-1" / "annotations"
    assert not annotations.exists() or list(annotations.glob("*.json")) == []
    assert not context._artifact_store.artifact_path(context.task.task_id, "result.json").exists()
