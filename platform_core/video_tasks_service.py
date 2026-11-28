"""Domain orchestration over the existing persistence, worker and receipt owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional
from fastapi import HTTPException

import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from fastapi import File, Form, UploadFile
from fastapi.responses import JSONResponse
from filelock import FileLock, Timeout
from starlette.concurrency import run_in_threadpool
from platform_core.task_runtime import TaskKind, TaskRecord, WorkerInstanceService
from platform_core.task_runtime.repository import TERMINAL_STATUSES
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

    @staticmethod
    def _creation_task_id(project_id: str, actor_id: str, request_id: str) -> str:
        if not actor_id or not re.fullmatch(r"[A-Za-z0-9_-]{12,80}", request_id):
            raise HTTPException(422, detail="切帧创建请求 ID 不合法")
        scope = json.dumps([project_id, actor_id, request_id], ensure_ascii=False, separators=(",", ":"))
        return "video_" + hashlib.sha256(scope.encode()).hexdigest()

    def v33_find_video_task(self, project_id: str, actor_id: str, request_id: str, recovery: bool = False):
        task_id = self._creation_task_id(project_id, actor_id, request_id)
        if not recovery:
            return {"request_id": request_id, "task": self.v33_get_video_task(project_id, task_id)}
        self.dependencies.get_project(project_id)
        artifacts = self.dependencies.shared_task_artifacts()
        repository = self.dependencies.shared_task_repository()
        result = {"request_id": request_id}
        lock_path = artifacts.artifact_path(task_id, "create.lock")

        def registered():
            task = repository.get(task_id)
            if task is not None:
                if task.project_id != project_id or task.kind is not TaskKind.VIDEO_FRAMES:
                    raise HTTPException(409, detail="原切帧请求身份不一致")
                state = "TERMINAL" if task.status in TERMINAL_STATUSES else "ACCEPTED"
                return {**result, "state": state, "task": self._public_video_task(task)}
            deleted = repository.deleted_task_identity(task_id)
            if deleted is not None:
                if deleted["project_id"] != project_id or deleted["kind"] != TaskKind.VIDEO_FRAMES.value:
                    raise HTTPException(409, detail="原切帧请求身份不一致")
                return {**result, "state": "RETIRED"}

        if not lock_path.parent.exists():
            return registered() or {**result, "state": "UNREGISTERED"}
        try:
            with FileLock(str(lock_path), timeout=0):
                outcome = registered()
                if outcome is not None:
                    return outcome
                payload = artifacts.read_json(task_id, "payload.json")
                if payload is not None:
                    return {**result, "state": "STAGED"}
                if self._legacy_published_video(artifacts, task_id):
                    return {**result, "state": "UNVERIFIED_INPUT"}
                return {**result, "state": "UNREGISTERED"}
        except Timeout:
            return registered() or {**result, "state": "IN_FLIGHT"}
        except FileNotFoundError:
            # Retention may have removed the directory while the read acquired the lock.
            outcome = registered()
            if outcome is not None and outcome["state"] == "RETIRED":
                return outcome
            raise

    @staticmethod
    def _legacy_published_video(artifacts, task_id: str) -> bool:
        return any(path.is_file() and path.suffix != ".upload"
                   for path in artifacts.artifact_path(task_id, "inputs").glob("*"))

    @staticmethod
    def _published_video_matches(video_path: Path, expected_sha: str, expected_size: int) -> bool:
        if video_path.stat().st_size != expected_size:
            return False
        digest = hashlib.sha256()
        with video_path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest() == expected_sha

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
        *,
        request_id: str = "",
        actor_id: str = "",
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
        task_id = self._creation_task_id(project_id, actor_id, request_id) if request_id else uuid.uuid4().hex[:12]
        source_ref = f"inputs/{filename}"
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
        artifacts = self.dependencies.shared_task_artifacts()
        repository = self.dependencies.shared_task_repository()
        if request_id and repository.is_deleted(task_id):
            raise HTTPException(410, detail="原切帧任务已退役")
        video_path = artifacts.artifact_path(task_id, source_ref)
        video_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = artifacts.artifact_path(task_id, "create.lock")
        proposed = TaskRecord.new(
            task_id, project_id, TaskKind.VIDEO_FRAMES, "payload.json", "cpu:video",
            priority=priority, required_capabilities=("opencv",),
        )
        digest = hashlib.sha256()
        size = 0
        temp_path = None
        try:
            # Multipart parsing precedes this handler. The nonblocking lock
            # covers copying that request's bytes and publishing its immutable input.
            with FileLock(str(lock_path), timeout=0):
                if request_id and repository.is_deleted(task_id):
                    raise HTTPException(410, detail="原切帧任务已退役")
                with tempfile.NamedTemporaryFile(dir=video_path.parent, suffix=".upload", delete=False) as fp:
                    temp_path = Path(fp.name)
                    while chunk := await video.read(1024 * 1024):
                        fp.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                    if request_id:
                        fp.flush()
                        os.fsync(fp.fileno())
                if not size:
                    raise HTTPException(400, detail="上传的视频为空")

                evidence = {**payload, "input_sha256": digest.hexdigest(), "input_size": size,
                            "initial_priority": proposed.priority}
                record = repository.get(task_id) if request_id else None
                if record is not None:
                    existing = artifacts.read_json(task_id, record.payload_ref, default={})
                    if (record.project_id != project_id or record.kind is not TaskKind.VIDEO_FRAMES
                            or existing != evidence):
                        raise HTTPException(409, detail="同一切帧请求的源视频或参数不一致")
                else:
                    if request_id:
                        frozen = artifacts.read_json(task_id, "payload.json")
                        if frozen is not None:
                            if frozen != evidence:
                                raise HTTPException(409, detail="同一切帧请求的源视频或参数不一致")
                        else:
                            if self._legacy_published_video(artifacts, task_id):
                                raise HTTPException(409, detail="原视频缺少冻结参数证据，请核对后台记录")
                            artifacts.atomic_write_json(task_id, "payload.json", evidence)
                        if video_path.exists():
                            matches = await run_in_threadpool(
                                self._published_video_matches, video_path, evidence["input_sha256"], size,
                            )
                            if not matches:
                                raise HTTPException(409, detail="已暂存视频摘要与原请求不一致")
                        else:
                            temp_path.replace(video_path)
                    else:
                        temp_path.replace(video_path)
                        artifacts.atomic_write_json(task_id, "payload.json", payload)
                    record = repository.create(proposed, artifacts=artifacts)
        except Timeout:
            raise HTTPException(409, detail="原切帧请求正在登记，请核对原请求") from None
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        return JSONResponse(status_code=202, content={**self._public_video_task(record), **({"request_id": request_id} if request_id else {})})

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
