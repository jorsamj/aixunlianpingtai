"""HTTP adapters registered in original order; shared legacy selection types are injected."""
from typing import Callable, Optional
from fastapi import APIRouter, Query
from .cleaning_management_service import CleaningManagementService
from .cleaning_management_contracts import V47CleanConfirmReq, V47CleanReq, V47CleanRuntimeReq



def create_cleaning_management_router_1(service: Callable[[], CleaningManagementService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v47/projects/{project_id}/clean-tasks')
    def v47_list_clean_tasks(project_id: str):
        return service().v47_list_clean_tasks(project_id)

    @router.post('/api/v47/projects/{project_id}/clean-runtime/preflight')
    def v47_clean_runtime_preflight(project_id: str, payload: V47CleanRuntimeReq):
        return service().v47_clean_runtime_preflight(project_id, payload)

    @router.post('/api/v47/projects/{project_id}/clean-tasks')
    def v47_create_clean_task(project_id: str, payload: V47CleanReq):
        return service().v47_create_clean_task(project_id, payload)

    return router


def create_cleaning_management_router_2(service: Callable[[], CleaningManagementService]) -> APIRouter:
    router = APIRouter()

    @router.post('/api/v47/projects/{project_id}/clean-tasks/{task_id}/stop')
    def v47_stop_clean_task(project_id: str, task_id: str):
        return service().v47_stop_clean_task(project_id, task_id)

    @router.get('/api/v47/projects/{project_id}/clean-tasks/{task_id}/result')
    def v47_clean_result(project_id: str, task_id: str):
        return service().v47_clean_result(project_id, task_id)

    @router.get('/api/v47/projects/{project_id}/clean-tasks/{task_id}/annotation-audit')
    def v47_clean_annotation_audit(project_id: str, task_id: str, cursor: str='', limit: int=100, page: Optional[int]=Query(default=None, ge=1), page_size: int=Query(default=20, ge=1, le=100)):
        return service().v47_clean_annotation_audit(project_id, task_id, cursor, limit, page, page_size)

    @router.post('/api/v47/projects/{project_id}/clean-tasks/{task_id}/confirm')
    def v47_confirm_clean(project_id: str, task_id: str, payload: V47CleanConfirmReq):
        return service().v47_confirm_clean(project_id, task_id, payload)

    return router
