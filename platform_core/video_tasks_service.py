"""Domain orchestration over the existing persistence, worker and receipt owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional
from fastapi import HTTPException

import uuid
from pathlib import Path
from fastapi import File, Form, UploadFile
from fastapi.responses import JSONResponse
from platform_core.task_runtime import TaskKind, TaskRecord, WorkerInstanceService
from platform_core.video_tasks import SamplingMode, VideoSampleRequest

@dataclass(frozen=True)
class VideoTasksDependencies:
    VIDEO_EXTS_V33: Callable[..., Any]
    _public_task: Callable[..., Any]
    _require_shared_task: Callable[..., Any]
    ensure_project_dirs: Callable[..., Any]
    get_project: Callable[..., Any]
    safe_filename: Callable[..., Any]
    shared_task_artifacts: Callable[..., Any]
    shared_task_repository: Callable[..., Any]


class VideoTasksService:
    def __init__(self, dependencies: VideoTasksDependencies):
        self.dependencies = dependencies

    def v33_list_video_tasks(self, project_id: str, limit: int = 50, cursor: Optional[str] = None):
        self.dependencies.get_project(project_id)
        repository = self.dependencies.shared_task_repository()
        page = repository.list(
            project_id=project_id,
            kinds={TaskKind.VIDEO_FRAMES},
            limit=max(1, min(100, int(limit))),
            cursor=cursor,
        )
        worker_runtime = WorkerInstanceService(repository).list_runtime()
        queued_candidates = repository.queued_candidates()
        return {
            "items": [
                self._public_video_task(
                    task,
                    worker_runtime=worker_runtime,
                    queued_candidates=queued_candidates,
                )
                for task in page.items
            ],
            "next_cursor": page.next_cursor,
        }

    def v33_get_video_task(self, project_id: str, task_id: str):
        self.dependencies.get_project(project_id)
        task = self.dependencies._require_shared_task(project_id, task_id, TaskKind.VIDEO_FRAMES)
        return self._public_video_task(task)

    def v33_stop_video_task(self, project_id: str, task_id: str):
        self.dependencies.get_project(project_id)
        self.dependencies._require_shared_task(project_id, task_id, TaskKind.VIDEO_FRAMES)
        return self.dependencies._public_task(self.dependencies.shared_task_repository().request_cancel(task_id))

    async def v33_create_video_task(self,
        project_id: str,
        video: UploadFile = File(...),
        dataset_id: str = Form("default"),
        split: str = Form("unassigned"),
        mode: str = Form("interval_seconds"),
        interval_seconds: Optional[float] = Form(None),
        extract_fps: Optional[float] = Form(None),
        fixed_count: Optional[int] = Form(None),
        max_frames: Optional[int] = Form(None),
        backend: str = Form("auto"),
        priority: int = Form(50),
    ):
        self.dependencies.get_project(project_id)
        self.dependencies.ensure_project_dirs(project_id)
        filename = self.dependencies.safe_filename(video.filename or "video.mp4")
        ext = Path(filename).suffix.lower()
        if ext not in self.dependencies.VIDEO_EXTS_V33():
            raise HTTPException(status_code=400, detail="仅支持 mp4、avi、mov、mkv、flv、wmv、webm 等常见视频格式")
        try:
            sampling_mode = SamplingMode(mode)
            request = VideoSampleRequest(
                mode=sampling_mode,
                interval_seconds=interval_seconds if sampling_mode is SamplingMode.INTERVAL_SECONDS else None,
                extract_fps=extract_fps if sampling_mode is SamplingMode.FPS else None,
                fixed_count=fixed_count if sampling_mode is SamplingMode.FIXED_COUNT else None,
                max_frames=max_frames if max_frames and max_frames > 0 else None,
            )
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        task_id = uuid.uuid4().hex[:12]
        source_ref = f"inputs/{filename}"
        video_path = self.dependencies.shared_task_artifacts().artifact_path(task_id, source_ref)
        video_path.parent.mkdir(parents=True, exist_ok=True)
        with video_path.open("wb") as fp:
            while True:
                chunk = await video.read(1024 * 1024)
                if not chunk:
                    break
                fp.write(chunk)
        if video_path.stat().st_size <= 0:
            video_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="上传的视频为空")
        payload = {
            "source_ref": source_ref,
            "original_name": filename,
            "dataset_id": dataset_id or "default",
            "split": split or "unassigned",
            "mode": request.mode.value,
            "interval_seconds": request.interval_seconds,
            "extract_fps": request.extract_fps,
            "fixed_count": request.fixed_count,
            "max_frames": request.max_frames,
            "backend": str(backend or "auto").lower(),
        }
        self.dependencies.shared_task_artifacts().atomic_write_json(task_id, "payload.json", payload)
        record = self.dependencies.shared_task_repository().create(
            TaskRecord.new(
                task_id,
                project_id,
                TaskKind.VIDEO_FRAMES,
                "payload.json",
                "cpu:video",
                priority=priority,
                required_capabilities=("opencv",),
            )
        )
        return JSONResponse(status_code=202, content=self._public_video_task(record))

    def _public_video_task(self, task: TaskRecord, *, worker_runtime=None, queued_candidates=None) -> Dict[str, Any]:
        response = self.dependencies._public_task(
            task,
            worker_runtime=worker_runtime,
            queued_candidates=queued_candidates,
        )
        payload = self.dependencies.shared_task_artifacts().read_json(
            task.task_id,
            task.payload_ref,
            default={},
        )
        if isinstance(payload, dict):
            response.update(
                {
                    "video_name": payload.get("original_name"),
                    "dataset_id": payload.get("dataset_id") or "default",
                    "split": payload.get("split") or "unassigned",
                    "mode": payload.get("mode"),
                    "interval_seconds": payload.get("interval_seconds"),
                    "extract_fps": payload.get("extract_fps"),
                    "fixed_count": payload.get("fixed_count"),
                    "max_frames": payload.get("max_frames"),
                    "backend": payload.get("backend"),
                }
            )
        if task.result_ref:
            response["result"] = self.dependencies.shared_task_artifacts().read_json(
                task.task_id,
                task.result_ref,
                default={},
            )
        return response
