"""HTTP adapters registered at their original positions to retain matching order."""
from typing import Callable, Optional
from fastapi import APIRouter, Query
from .storage_ingestion_service import StorageIngestionService
from .storage_ingestion_contracts import StorageImportConfirmReq, StorageImportScanReq, StorageRescanConfirmReq, StorageRescanCreateReq



def create_storage_ingestion_router_1(service: Callable[[], StorageIngestionService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v61/projects/{project_id}/storage-sources/{source_id}/rescans/preflight')
    def storage_rescan_preflight(project_id: str, source_id: str):
        return service().storage_rescan_preflight(project_id, source_id)

    @router.post('/api/v61/projects/{project_id}/storage-sources/{source_id}/rescans', status_code=202)
    def create_storage_rescan(project_id: str, source_id: str, payload: Optional[StorageRescanCreateReq]=None):
        return service().create_storage_rescan(project_id, source_id, payload)

    @router.get('/api/v61/projects/{project_id}/storage-rescans/{task_id}')
    def get_storage_rescan(project_id: str, task_id: str):
        return service().get_storage_rescan(project_id, task_id)

    @router.post('/api/v61/projects/{project_id}/storage-rescans/{task_id}/confirm', status_code=202)
    def confirm_storage_rescan(project_id: str, task_id: str, payload: StorageRescanConfirmReq):
        return service().confirm_storage_rescan(project_id, task_id, payload)

    @router.post('/api/v61/projects/{project_id}/storage-rescans/{task_id}/cancel')
    def cancel_storage_rescan(project_id: str, task_id: str):
        return service().cancel_storage_rescan(project_id, task_id)

    @router.post('/api/v61/projects/{project_id}/storage-imports/scan', status_code=202)
    def create_storage_import_scan(project_id: str, payload: StorageImportScanReq):
        return service().create_storage_import_scan(project_id, payload)

    @router.get('/api/v61/projects/{project_id}/storage-imports/{task_id}')
    def get_storage_import_scan(project_id: str, task_id: str):
        return service().get_storage_import_scan(project_id, task_id)

    @router.post('/api/v61/projects/{project_id}/storage-imports/{task_id}/confirm', status_code=202)
    def confirm_storage_import(project_id: str, task_id: str, payload: StorageImportConfirmReq):
        return service().confirm_storage_import(project_id, task_id, payload)

    @router.get('/api/v61/projects/{project_id}/label-review/{task_id}/classes/{class_id}/samples')
    def label_review_samples_v61(project_id: str, task_id: str, class_id: str, limit: int=Query(default=8, ge=1, le=12)):
        return service().label_review_samples_v61(project_id, task_id, class_id, limit)

    @router.get('/api/v61/projects/{project_id}/label-review/{task_id}/classes/{class_id}/sample-content')
    def label_review_sample_content_v61(project_id: str, task_id: str, class_id: str, object_key: str=Query(..., min_length=1, max_length=4096)):
        return service().label_review_sample_content_v61(project_id, task_id, class_id, object_key)

    return router
