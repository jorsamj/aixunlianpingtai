"""HTTP adapters registered at their original positions to retain matching order."""
from typing import Callable
from fastapi import APIRouter, Request
from .training_management_service import TrainingManagementService
from .training_management_contracts import V48TrainingBatchDeleteReq

from fastapi.responses import PlainTextResponse


def create_training_management_router_1(service: Callable[[], TrainingManagementService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/projects/{project_id}/jobs')
    def list_jobs(project_id: str, summary_only: bool=False):
        return service().list_jobs(project_id, summary_only)

    @router.get('/api/v64/projects/{project_id}/training-events')
    async def v64_training_events(project_id: str, request: Request):
        return await service().v64_training_events(project_id, request)

    @router.get('/api/projects/{project_id}/jobs/{job_id}')
    def job_status(project_id: str, job_id: str, include_history: bool=False):
        return service().job_status(project_id, job_id, include_history)

    @router.get('/api/projects/{project_id}/jobs/{job_id}/log', response_class=PlainTextResponse)
    def job_log(project_id: str, job_id: str):
        return service().job_log(project_id, job_id)

    @router.post('/api/projects/{project_id}/jobs/{job_id}/stop')
    def stop_job(project_id: str, job_id: str):
        return service().stop_job(project_id, job_id)

    return router


def create_training_management_router_2(service: Callable[[], TrainingManagementService]) -> APIRouter:
    router = APIRouter()

    @router.post('/api/v48/projects/{project_id}/jobs/{job_id}/promote')
    def v48_promote_job(project_id: str, job_id: str):
        return service().v48_promote_job(project_id, job_id)

    @router.post('/api/v48/projects/{project_id}/jobs/{job_id}/pause')
    def v48_pause_job(project_id: str, job_id: str):
        return service().v48_pause_job(project_id, job_id)

    @router.post('/api/v48/projects/{project_id}/jobs/{job_id}/resume')
    def v48_resume_job(project_id: str, job_id: str):
        return service().v48_resume_job(project_id, job_id)

    @router.post('/api/v48/projects/{project_id}/jobs/{job_id}/stop')
    def v48_stop_job(project_id: str, job_id: str):
        return service().v48_stop_job(project_id, job_id)

    @router.post('/api/v48/projects/{project_id}/jobs/batch-delete')
    def v48_batch_delete_jobs(project_id: str, payload: V48TrainingBatchDeleteReq):
        return service().v48_batch_delete_jobs(project_id, payload)

    @router.delete('/api/v12/projects/{project_id}/jobs/{job_id}')
    def v12_delete_job(project_id: str, job_id: str):
        return service().v12_delete_job(project_id, job_id)

    return router
