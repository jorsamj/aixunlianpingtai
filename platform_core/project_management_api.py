"""HTTP adapters registered at their original positions to retain matching order."""
from typing import Callable
from fastapi import APIRouter
from .project_management_service import ProjectManagementService
from .project_management_contracts import ProjectCreate, ProjectUpdate



def create_project_management_router_1(service: Callable[[], ProjectManagementService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/projects')
    def list_projects():
        return service().list_projects()

    @router.put('/api/projects/{project_id}')
    def update_project(project_id: str, payload: ProjectUpdate):
        return service().update_project(project_id, payload)

    @router.delete('/api/projects/{project_id}')
    def delete_project(project_id: str):
        return service().delete_project(project_id)

    return router


def create_project_management_router_2(service: Callable[[], ProjectManagementService]) -> APIRouter:
    router = APIRouter()

    @router.post('/api/projects')
    def create_project(payload: ProjectCreate):
        return service().create_project(payload)

    @router.get('/api/projects/{project_id}')
    def read_project(project_id: str):
        return service().read_project(project_id)

    return router
