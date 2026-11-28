"""HTTP adapters registered at their original positions to retain matching order."""
from typing import Callable, Optional
import json
from fastapi import APIRouter, Request
from .video_tasks_service import VideoTasksService

from fastapi import File, Form, UploadFile


def create_video_tasks_router_1(service: Callable[[], VideoTasksService], actor_provider) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v33/projects/{project_id}/video-tasks')
    def v33_list_video_tasks(project_id: str, limit: int=50, cursor: Optional[str]=None):
        return service().v33_list_video_tasks(project_id, limit, cursor)

    def actor_scope(request: Request, project_id: str) -> str:
        actor = actor_provider(request, project_id)["actor_id"]
        claims = getattr(request.state, "changlian_user", None) or {}
        return json.dumps([claims.get("provider") or "changlian", actor], ensure_ascii=False)

    @router.get('/api/v33/projects/{project_id}/video-tasks/by-request/{request_id}')
    def v33_find_video_task(project_id: str, request_id: str, request: Request, recovery: bool = False):
        return service().v33_find_video_task(project_id, actor_scope(request, project_id), request_id, recovery)

    @router.get('/api/v33/projects/{project_id}/video-tasks/{task_id}')
    def v33_get_video_task(project_id: str, task_id: str):
        return service().v33_get_video_task(project_id, task_id)

    @router.post('/api/v33/projects/{project_id}/video-tasks/{task_id}/stop')
    def v33_stop_video_task(project_id: str, task_id: str):
        return service().v33_stop_video_task(project_id, task_id)

    @router.post('/api/v33/projects/{project_id}/video-tasks')
    async def v33_create_video_task(project_id: str, request: Request, video: UploadFile=File(...), dataset_id: str=Form('default'), split: str=Form('unassigned'), mode: str=Form('interval_seconds'), interval_seconds: Optional[float]=Form(None), extract_fps: Optional[float]=Form(None), fixed_count: Optional[int]=Form(None), max_frames: Optional[int]=Form(None), backend: str=Form('auto'), priority: int=Form(50), request_id: str=Form('')):
        return await service().v33_create_video_task(project_id, video, dataset_id, split, mode, interval_seconds, extract_fps, fixed_count, max_frames, backend, priority,
                                                    request_id=request_id, actor_id=actor_scope(request, project_id) if request_id else "")

    return router
