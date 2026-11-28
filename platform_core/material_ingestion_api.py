"""HTTP adapters registered at their original positions to retain matching order."""
from typing import Callable, List, Optional
from fastapi import APIRouter, Query, Request
from .material_ingestion_service import MaterialIngestionService
from .material_ingestion_contracts import V19ImportStartReq, V19MultipartUploadReq, V36SourceImportScanReq, V36SourceImportStartReq, V55UploadDecisionsReq

from fastapi import File, Form, UploadFile


def create_material_ingestion_router_1(service: Callable[[], MaterialIngestionService]) -> APIRouter:
    router = APIRouter()

    @router.post('/api/projects/{project_id}/images')
    async def upload_images(project_id: str, files: List[UploadFile]=File(...), dataset_id: str=Form('default'), storage_source_id: str=Form('default_local'), upload_request_id: Optional[str]=Form(None), mining_algorithm_id: str=Form(''), mining_version_id: str=Form('')):
        return await service().upload_images(project_id, files, dataset_id, storage_source_id, upload_request_id, mining_algorithm_id, mining_version_id)

    return router


def create_material_ingestion_router_2(service: Callable[[], MaterialIngestionService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v19/projects/{project_id}/import/jobs/{job_id}/unannotated')
    def v19_unannotated_import_page(project_id: str, job_id: str, cursor: int=0, limit: int=150):
        """Materialized ZIP subset, bounded pages; never send all 10k IDs to UI."""
        return service().v19_unannotated_import_page(project_id, job_id, cursor, limit)

    @router.get('/api/v19/projects/{project_id}/import/jobs/{job_id}/folders')
    def v19_import_folders(project_id: str, job_id: str, offset: int=Query(0, ge=0), limit: int=Query(50, ge=1, le=100)):
        return service().v19_import_folders(project_id, job_id, offset, limit)

    @router.post('/api/v19/projects/{project_id}/import/jobs/{job_id}/retry-folder-classification')
    def v19_retry_folder_classification(project_id: str, job_id: str):
        return service().v19_retry_folder_classification(project_id, job_id)

    @router.post('/api/v19/projects/{project_id}/datasets/{dataset_id}/import/uploads')
    def v19_create_multipart_upload(project_id: str, dataset_id: str, payload: V19MultipartUploadReq):
        return service().v19_create_multipart_upload(project_id, dataset_id, payload)

    @router.put('/api/v19/projects/{project_id}/import/uploads/{upload_id}/parts/{part_number}')
    async def v19_upload_multipart_part(project_id: str, upload_id: str, part_number: int, request: Request):
        return await service().v19_upload_multipart_part(project_id, upload_id, part_number, request)

    @router.post('/api/v19/projects/{project_id}/import/uploads/{upload_id}/pause')
    def v19_pause_multipart_upload(project_id: str, upload_id: str):
        return service().v19_pause_multipart_upload(project_id, upload_id)

    @router.post('/api/v19/projects/{project_id}/import/uploads/{upload_id}/cancel')
    def v19_cancel_multipart_upload(project_id: str, upload_id: str):
        return service().v19_cancel_multipart_upload(project_id, upload_id)

    @router.post('/api/v19/projects/{project_id}/import/uploads/{upload_id}/complete')
    def v19_complete_multipart_upload(project_id: str, upload_id: str):
        return service().v19_complete_multipart_upload(project_id, upload_id)

    @router.post('/api/v19/projects/{project_id}/datasets/{dataset_id}/import/jobs')
    async def v19_create_import_job(project_id: str, dataset_id: str, file: UploadFile=File(...), folder_confirmation: bool=Form(False)):
        return await service().v19_create_import_job(project_id, dataset_id, file, folder_confirmation)

    @router.post('/api/v19/projects/{project_id}/import/jobs/{job_id}/cancel')
    def v19_cancel_import_job(project_id: str, job_id: str):
        return service().v19_cancel_import_job(project_id, job_id)

    @router.post('/api/v19/projects/{project_id}/import/jobs/{job_id}/stop')
    def v19_stop_import_job(project_id: str, job_id: str):
        return service().v19_stop_import_job(project_id, job_id)

    @router.post('/api/v19/projects/{project_id}/import/jobs/{job_id}/start')
    def v19_start_import_job(project_id: str, job_id: str, payload: V19ImportStartReq):
        return service().v19_start_import_job(project_id, job_id, payload)

    @router.get('/api/v19/projects/{project_id}/import/jobs/{job_id}/classes/{class_id}/samples')
    def v19_label_samples(project_id: str, job_id: str, class_id: str):
        return service().v19_label_samples(project_id, job_id, class_id)

    @router.get('/api/v19/projects/{project_id}/import/jobs/{job_id}/classes/{class_id}/sample-content')
    def v19_label_sample_content(project_id: str, job_id: str, class_id: str, index: int=Query(ge=0, le=11)):
        return service().v19_label_sample_content(project_id, job_id, class_id, index)

    @router.get('/api/v19/projects/{project_id}/import/jobs')
    def v19_list_import_jobs(project_id: str):
        return service().v19_list_import_jobs(project_id)

    @router.get('/api/v19/projects/{project_id}/import/jobs/{job_id}')
    def v19_get_import_job(project_id: str, job_id: str, include_images: bool=False, image_limit: int=500):
        return service().v19_get_import_job(project_id, job_id, include_images, image_limit)

    @router.delete('/api/v19/projects/{project_id}/import/jobs')
    def v19_clear_terminal_import_jobs(project_id: str, job_ids: str=''):
        return service().v19_clear_terminal_import_jobs(project_id, job_ids)

    @router.delete('/api/v19/projects/{project_id}/import/jobs/{job_id}')
    def v19_delete_import_job(project_id: str, job_id: str):
        return service().v19_delete_import_job(project_id, job_id)

    return router


def create_material_ingestion_router_3(service: Callable[[], MaterialIngestionService]) -> APIRouter:
    router = APIRouter()

    @router.post('/api/v36/projects/{project_id}/datasets/{dataset_id}/source-import/scan')
    def v36_scan_source_import(project_id: str, dataset_id: str, payload: V36SourceImportScanReq):
        return service().v36_scan_source_import(project_id, dataset_id, payload)

    @router.get('/api/v36/projects/{project_id}/datasets/{dataset_id}/source-import/jobs')
    def v36_list_source_import_jobs(project_id: str, dataset_id: str):
        return service().v36_list_source_import_jobs(project_id, dataset_id)

    @router.post('/api/v36/projects/{project_id}/datasets/{dataset_id}/source-import/jobs')
    def v36_start_source_import_job(project_id: str, dataset_id: str, payload: V36SourceImportStartReq):
        return service().v36_start_source_import_job(project_id, dataset_id, payload)

    return router


def create_material_ingestion_router_4(service: Callable[[], MaterialIngestionService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v55/projects/{project_id}/upload-batches/{batch_id}')
    def v55_get_upload_batch(project_id: str, batch_id: str):
        return service().v55_get_upload_batch(project_id, batch_id)

    @router.post('/api/v55/projects/{project_id}/upload-batches/{batch_id}/decisions')
    def v55_apply_upload_batch_decisions(project_id: str, batch_id: str, payload: V55UploadDecisionsReq):
        return service().v55_apply_upload_batch_decisions(project_id, batch_id, payload)

    return router


def create_material_ingestion_router_5(service: Callable[[], MaterialIngestionService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v52/projects/{project_id}/import/jobs/{job_id}/review')
    def v52_import_review(project_id: str, job_id: str):
        return service().v52_import_review(project_id, job_id)

    return router
