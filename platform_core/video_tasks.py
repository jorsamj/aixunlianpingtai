from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

import cv2

from .annotations import annotation_summary, atomic_write_json
from .annotation_repository import AnnotationRepository
from .material_repository import MaterialRepository
from .materials import initial_processing_status
from .storage import StorageManager
from .task_runtime import TaskKind, TaskStatus


class SamplingMode(str, Enum):
    INTERVAL_SECONDS = "interval_seconds"
    FPS = "fps"
    FIXED_COUNT = "fixed_count"


@dataclass(frozen=True)
class VideoSampleRequest:
    mode: SamplingMode
    interval_seconds: float | None = None
    extract_fps: float | None = None
    fixed_count: int | None = None
    max_frames: int | None = None

    def __post_init__(self) -> None:
        supplied = sum(
            value is not None
            for value in (self.interval_seconds, self.extract_fps, self.fixed_count)
        )
        if supplied != 1:
            raise ValueError("exactly one sampling value is required")
        selected = {
            SamplingMode.INTERVAL_SECONDS: self.interval_seconds,
            SamplingMode.FPS: self.extract_fps,
            SamplingMode.FIXED_COUNT: self.fixed_count,
        }[self.mode]
        if selected is None or float(selected) <= 0:
            raise ValueError("sampling value must be positive")
        if self.max_frames is not None and int(self.max_frames) <= 0:
            raise ValueError("max_frames must be positive")


@dataclass(frozen=True)
class VideoProbe:
    total_frames: int
    fps: float
    duration_seconds: float
    width: int
    height: int
    backend: str


@dataclass(frozen=True)
class ExtractedFrame:
    path: str
    source_frame_index: int
    timestamp_seconds: float
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class VideoExtractionResult:
    source: str
    output_dir: str
    backend: str
    duration_seconds: float
    expected_frames: int
    extracted_frames: int
    frames: tuple[ExtractedFrame, ...]


def _safe_component(value: str, field: str) -> str:
    text = str(value)
    if not text or text in {".", ".."} or "/" in text or "\\" in text or ":" in text:
        raise ValueError(f"{field} must be one safe path component")
    return text


def plan_frame_indices(
    total_frames: int,
    source_fps: float,
    request: VideoSampleRequest,
) -> list[int]:
    total = max(0, int(total_frames))
    if total == 0:
        return []
    fps = float(source_fps)
    if fps <= 0:
        raise ValueError("source video fps must be positive")

    if request.mode is SamplingMode.FIXED_COUNT:
        count = min(total, int(request.fixed_count or 0))
        if count == 1:
            indices = [0]
        elif count == total:
            indices = list(range(total))
        else:
            indices = [round(index * (total - 1) / (count - 1)) for index in range(count)]
    else:
        if request.mode is SamplingMode.INTERVAL_SECONDS:
            step = fps * float(request.interval_seconds or 0)
        else:
            step = fps / min(fps, float(request.extract_fps or 0))
        step = max(1.0, step)
        indices = []
        position = 0.0
        while round(position) < total:
            frame_index = min(total - 1, round(position))
            if not indices or indices[-1] != frame_index:
                indices.append(frame_index)
            position += step

    if request.max_frames is not None:
        indices = indices[: int(request.max_frames)]
    return indices


def probe_video(source: str | Path, backend: str = "auto") -> VideoProbe:
    selected = "opencv" if backend == "auto" else str(backend).lower()
    if selected != "opencv":
        raise EnvironmentError(f"video backend is unavailable: {selected}")
    path = Path(source)
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError("video file does not exist or is empty")
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError("video cannot be opened")
        total_frames = int(round(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
        height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        if total_frames <= 0 or fps <= 0 or width <= 0 or height <= 0:
            raise ValueError("video metadata is invalid")
        return VideoProbe(
            total_frames=total_frames,
            fps=fps,
            duration_seconds=total_frames / fps,
            width=width,
            height=height,
            backend=selected,
        )
    finally:
        capture.release()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_video(
    source: str | Path,
    output_dir: str | Path,
    request: VideoSampleRequest,
    *,
    backend: str = "auto",
    progress: Callable[[int, int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> VideoExtractionResult:
    source_path = Path(source).resolve()
    probe = probe_video(source_path, backend=backend)
    indices = plan_frame_indices(probe.total_frames, probe.fps, request)
    if not indices:
        raise ValueError("video sampling produced no frames")
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    targets = set(indices)
    frames: list[ExtractedFrame] = []
    capture = cv2.VideoCapture(str(source_path))
    try:
        if not capture.isOpened():
            raise ValueError("video cannot be opened")
        frame_index = 0
        while frame_index < probe.total_frames and len(frames) < len(indices):
            if cancelled is not None and cancelled():
                raise InterruptedError("video extraction cancelled")
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index in targets:
                final_path = destination / (
                    f"frame_{len(frames) + 1:06d}_src_{frame_index:09d}.jpg"
                )
                temporary_path = final_path.with_name(f".{final_path.name}.tmp.jpg")
                if not cv2.imwrite(str(temporary_path), frame):
                    raise OSError(f"failed to write extracted frame {frame_index}")
                os.replace(temporary_path, final_path)
                frames.append(
                    ExtractedFrame(
                        path=str(final_path),
                        source_frame_index=frame_index,
                        timestamp_seconds=frame_index / probe.fps,
                        sha256=_sha256(final_path),
                        size_bytes=final_path.stat().st_size,
                    )
                )
                if progress is not None:
                    progress(len(frames), len(indices), frame_index)
            frame_index += 1
    finally:
        capture.release()

    if len(frames) != len(indices):
        raise ValueError(
            f"video ended before planned frames were extracted: {len(frames)}/{len(indices)}"
        )
    return VideoExtractionResult(
        source=str(source_path),
        output_dir=str(destination),
        backend=probe.backend,
        duration_seconds=probe.duration_seconds,
        expected_frames=len(indices),
        extracted_frames=len(frames),
        frames=tuple(frames),
    )


class VideoFrameHandler:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir).resolve()

    def _project_dir(self, project_id: str) -> Path:
        return self.data_dir / "projects" / _safe_component(project_id, "project id")

    @staticmethod
    def _request(payload: dict) -> VideoSampleRequest:
        return VideoSampleRequest(
            mode=SamplingMode(str(payload["mode"])),
            interval_seconds=payload.get("interval_seconds"),
            extract_fps=payload.get("extract_fps"),
            fixed_count=payload.get("fixed_count"),
            max_frames=payload.get("max_frames"),
        )

    @staticmethod
    def _material_id(task_id: str, source_frame_index: int) -> str:
        return hashlib.sha256(
            f"{task_id}:{int(source_frame_index)}".encode("utf-8")
        ).hexdigest()[:16]

    def _already_committed(self, context) -> str | None:
        result = context.artifacts.read_json(
            context.task.task_id,
            "result.json",
            default=None,
        )
        if not isinstance(result, dict):
            return None
        project_dir = self._project_dir(context.task.project_id)
        materials_repository = MaterialRepository(project_dir)
        manager = StorageManager(
            data_dir=self.data_dir,
            project_id=context.task.project_id,
            materials=materials_repository,
        )
        rows = materials_repository.read().rows
        by_id = {str(row.get("id")): row for row in rows}
        materials = result.get("materials") or []
        if not materials:
            return None
        for item in materials:
            image_id = str(item.get("image_id") or "")
            if image_id not in by_id:
                return None
            path = manager.materialize(by_id[image_id]).path
            if not path.is_file() or _sha256(path) != item.get("sha256"):
                return None
        return "result.json"

    def run(self, context):
        payload = context.artifacts.read_json(
            context.task.task_id,
            context.task.payload_ref,
            default={},
        )
        source_ref = str(payload.get("source_ref") or "")
        source = context.artifacts.artifact_path(context.task.task_id, source_ref)
        frames_dir = context.artifacts.artifact_path(context.task.task_id, "frames")

        def report_progress(done: int, total: int, current: int) -> None:
            context.repository.heartbeat(
                context.task.task_id,
                context.lease.lease_token,
                progress=round(done / max(1, total) * 90, 2),
                stage="extracting",
                current_item=str(current),
            )

        extraction = extract_video(
            source,
            frames_dir,
            self._request(payload),
            backend=str(payload.get("backend") or "auto"),
            progress=report_progress,
            cancelled=context.cancel_requested,
        )
        context.save_checkpoint(
            {
                "stage": "extracted",
                "extracted_frames": extraction.extracted_frames,
            }
        )
        project_dir = self._project_dir(context.task.project_id)
        annotations = project_dir / "annotations"
        annotations.mkdir(parents=True, exist_ok=True)
        annotation_repository = AnnotationRepository(project_dir)
        materials_repository = MaterialRepository(project_dir)
        manager = StorageManager(
            data_dir=self.data_dir,
            project_id=context.task.project_id,
            materials=materials_repository,
        )
        original_stem = Path(str(payload.get("original_name") or "video")).stem
        records = []
        result_materials = []
        created_at = context.task.created_at or datetime.now(timezone.utc).isoformat()
        for extracted in extraction.frames:
            image_id = self._material_id(
                context.task.task_id,
                extracted.source_frame_index,
            )
            stored_name = f"{image_id}.jpg"
            object_key = f"uploads/{stored_name}"
            metadata = manager.upload_object(
                "default_local",
                object_key,
                Path(extracted.path),
                content_type="image/jpeg",
            )
            if metadata.sha256 != extracted.sha256:
                raise OSError("stored frame checksum mismatch")
            annotation_path = annotations / f"{image_id}.json"
            if not annotation_path.exists() and annotation_repository.get(image_id)['version'] == 0:
                annotation_repository.upsert(image_id, [], 'unannotated')
            records.append(
                {
                    "id": image_id,
                    "filename": (
                        f"{original_stem}_frame_{extracted.source_frame_index:09d}.jpg"
                    ),
                    "stored_name": stored_name,
                    "url": f"/api/v61/projects/{context.task.project_id}/materials/{image_id}/content",
                    "storage_source_id": "default_local",
                    "storage_type": "local",
                    "object_key": object_key,
                    "width": 0,
                    "height": 0,
                    "source_type": "video_frame",
                    "source_ref": context.task.task_id,
                    "video_task_id": context.task.task_id,
                    "frame_index": extracted.source_frame_index,
                    "frame_time_seconds": round(extracted.timestamp_seconds, 6),
                    "content_sha256": extracted.sha256,
                    "dataset_id": str(payload.get("dataset_id") or "default"),
                    "split": str(payload.get("split") or "unassigned"),
                    "processing_status": initial_processing_status(False),
                    "size_bytes": metadata.size_bytes,
                    "etag": metadata.etag,
                    "created_at": created_at,
                    **annotation_summary([]),
                }
            )
            result_materials.append(
                {
                    "image_id": image_id,
                    "stored_name": stored_name,
                    "sha256": extracted.sha256,
                    "source_frame_index": extracted.source_frame_index,
                }
            )
        if records:
            first_image = cv2.imread(str(Path(extraction.frames[0].path)))
            if first_image is None:
                raise OSError("extracted frame cannot be decoded after copy")
            height, width = first_image.shape[:2]
            for record in records:
                record["width"] = int(width)
                record["height"] = int(height)
        materials_repository.upsert_many(records)
        context.repository.heartbeat(
            context.task.task_id,
            context.lease.lease_token,
            progress=98,
            stage="committing",
            current_item=str(len(records)),
        )
        result = {
            "schema_version": 1,
            "backend": extraction.backend,
            "duration_seconds": extraction.duration_seconds,
            "expected_frames": extraction.expected_frames,
            "extracted_frames": extraction.extracted_frames,
            "output_ref": "frames",
            "materials": result_materials,
        }
        context.artifacts.atomic_write_json(context.task.task_id, "result.json", result)
        context.save_checkpoint(
            {
                "stage": "committed",
                "extracted_frames": extraction.extracted_frames,
                "result_ref": "result.json",
            }
        )
        return TaskStatus.SUCCEEDED, "result.json"

    def recover(self, context):
        committed = self._already_committed(context)
        if committed is not None:
            return TaskStatus.SUCCEEDED, committed
        return self.run(context)


def worker_registration(data_dir: Path):
    return {
        "handlers": {TaskKind.VIDEO_FRAMES: VideoFrameHandler(data_dir)},
        "capabilities": {"opencv"},
    }
