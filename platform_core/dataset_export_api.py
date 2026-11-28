"""HTTP adapters registered at their original positions to retain matching order."""
from typing import Callable
from fastapi import APIRouter
from .dataset_export_service import DatasetExportService
from .dataset_export_contracts import BuildDatasetReq, BuildPaddleDatasetReq



def create_dataset_export_router_1(service: Callable[[], DatasetExportService]) -> APIRouter:
    router = APIRouter()

    @router.post('/api/projects/{project_id}/dataset/build')
    def build_dataset(project_id: str, payload: BuildDatasetReq):
        return service().build_dataset(project_id, payload)

    @router.get('/api/projects/{project_id}/dataset/download')
    def download_dataset(project_id: str):
        return service().download_dataset(project_id)

    @router.post('/api/projects/{project_id}/dataset/build_paddle')
    def build_paddle_dataset(project_id: str, payload: BuildPaddleDatasetReq):
        return service().build_paddle_dataset(project_id, payload)

    @router.get('/api/projects/{project_id}/dataset/download_paddle')
    def download_paddle_dataset(project_id: str):
        return service().download_paddle_dataset(project_id)

    return router


def create_dataset_export_router_2(service: Callable[[], DatasetExportService]) -> APIRouter:
    router = APIRouter()

    @router.post('/api/v12/projects/{project_id}/dataset/build')
    def v12_build_dataset(project_id: str, payload: BuildDatasetReq):
        return service().v12_build_dataset(project_id, payload)

    return router


def create_dataset_export_router_3(service: Callable[[], DatasetExportService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v12/projects/{project_id}/datasets/{dataset_id}/export/{fmt}')
    def v12_export_dataset(project_id: str, dataset_id: str, fmt: str):
        return service().v12_export_dataset(project_id, dataset_id, fmt)

    return router
