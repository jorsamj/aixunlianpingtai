"""HTTP adapters registered at their original positions to retain matching order."""
from typing import Callable, Optional
from fastapi import APIRouter
from .video_tasks_service import VideoTasksService

from fastapi import File, Form, UploadFile


def create_video_tasks_router_1(service: Callable[[], VideoTasksService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v33/projects/{project_id}/video-tasks')
    def v33_list_video_tasks(project_id: str, limit: int=50, cursor: Optional[str]=None):
        return service().v33_list_video_tasks(project_id, limit, cursor)

    @router.get('/api/v33/projects/{project_id}/video-tasks/{task_id}')
    def v33_get_video_task(project_id: str, task_id: str):
        return service().v33_get_video_task(project_id, task_id)

    @router.post('/api/v33/projects/{project_id}/video-tasks/{task_id}/stop')
    def v33_stop_video_task(project_id: str, task_id: str):
        return service().v33_stop_video_task(project_id, task_id)

    @router.post('/api/v33/projects/{project_id}/video-tasks')
    async def v33_create_video_task(project_id: str, video: UploadFile=File(...), dataset_id: str=Form('default'), split: str=Form('unassigned'), mode: str=Form('interval_seconds'), interval_seconds: Optional[float]=Form(None), extract_fps: Optional[float]=Form(None), fixed_count: Optional[int]=Form(None), max_frames: Optional[int]=Form(None), backend: str=Form('auto'), priority: int=Form(50)):
        return await service().v33_create_video_task(project_id, video, dataset_id, split, mode, interval_seconds, extract_fps, fixed_count, max_frames, backend, priority)

    return router
