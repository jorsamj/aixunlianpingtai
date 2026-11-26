from __future__ import annotations
from typing import Optional, List, Literal, Callable
from fastapi import APIRouter, Query, Request
from .material_catalog_contracts import DatasetReq
from .material_catalog_service import MaterialCatalogService


def create_material_reader_router(service: Callable[[], MaterialCatalogService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v61/projects/{project_id}/materials')
    def list_materials_v61(project_id: str, cursor: Optional[str]=None, limit: int=100, page: Optional[int]=None, page_size: Optional[int]=None, query: str='', storage_source_id: Optional[List[str]]=Query(default=None), processing_status: Optional[str]=None, label: Optional[List[str]]=Query(default=None), annotated: Optional[bool]=None, annotation_state: Optional[Literal['unannotated', 'annotated', 'confirmed_empty', 'partial', 'needs_review']]=None, source_batch_id: Optional[str]=None, quality_status: Optional[Literal['pending_decision', 'processed', 'issue']]=None, created_from: Optional[str]=None, created_to: Optional[str]=None, reader_view: bool=False):
        return service().list_materials_v61(project_id, cursor, limit, page, page_size, query, storage_source_id, processing_status, label, annotated, annotation_state, source_batch_id, quality_status, created_from, created_to, reader_view)

    @router.get('/api/v61/projects/{project_id}/materials/ids')
    def list_material_ids_v61(project_id: str, cursor: Optional[str]=None, limit: int=1000, query: str='', storage_source_id: Optional[List[str]]=Query(default=None), processing_status: Optional[str]=None, label: Optional[List[str]]=Query(default=None), annotated: Optional[bool]=None, annotation_state: Optional[Literal['unannotated', 'annotated', 'confirmed_empty', 'partial', 'needs_review']]=None, source_batch_id: Optional[str]=None, quality_status: Optional[Literal['pending_decision', 'processed', 'issue']]=None, created_from: Optional[str]=None, created_to: Optional[str]=None, narrow: bool=False, expected_revision: Optional[int]=None):
        return service().list_material_ids_v61(project_id, cursor, limit, query, storage_source_id, processing_status, label, annotated, annotation_state, source_batch_id, quality_status, created_from, created_to, narrow, expected_revision)

    @router.get('/api/v61/projects/{project_id}/materials/status-counts')
    def material_status_counts_v61(project_id: str, storage_source_id: Optional[List[str]]=Query(default=None)):
        return service().material_status_counts_v61(project_id, storage_source_id)

    @router.get('/api/v61/projects/{project_id}/materials/{image_id}/content')
    def material_content_v61(project_id: str, image_id: str, expected_sha256: Optional[str]=None):
        return service().material_content_v61(project_id, image_id, expected_sha256)


    return router


def create_dataset_directory_router(service: Callable[[], MaterialCatalogService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/projects/{project_id}/datasets')
    def list_datasets(project_id: str):
        return service().list_datasets(project_id)

    @router.post('/api/projects/{project_id}/datasets')
    def create_dataset(project_id: str, payload: DatasetReq):
        return service().create_dataset(project_id, payload)

    @router.put('/api/projects/{project_id}/datasets/{dataset_id}')
    def update_dataset(project_id: str, dataset_id: str, payload: DatasetReq):
        return service().update_dataset(project_id, dataset_id, payload)

    return router


def create_legacy_material_reader_router(service: Callable[[], MaterialCatalogService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/projects/{project_id}/images')
    def list_images(project_id: str, dataset_id: Optional[str]=None):
        return service().list_images(project_id, dataset_id)

    return router


def create_label_directory_router(service: Callable[[], MaterialCatalogService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v12/projects/{project_id}/labels')
    def v12_list_labels(project_id: str):
        return service().v12_list_labels(project_id)

    return router


def create_dataset_quality_router(service: Callable[[], MaterialCatalogService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v17/projects/{project_id}/datasets/{dataset_id}/quality')
    def v17_dataset_quality(project_id: str, dataset_id: str, include_empty: bool=False):
        return service().v17_dataset_quality(project_id, dataset_id, include_empty)

    return router


def create_dataset_summary_router(service: Callable[[], MaterialCatalogService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v12/projects/{project_id}/datasets/{dataset_id}/summary')
    def v12_dataset_summary(project_id: str, dataset_id: str):
        return service().v12_dataset_summary(project_id, dataset_id)

    return router


def create_material_thumbnail_router(service: Callable[[], MaterialCatalogService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v61/projects/{project_id}/materials/{image_id}/content/thumbnail')
    def material_thumbnail_v61(project_id: str, image_id: str, request: Request, edge: int=Query(384, ge=16, le=1024)):
        """Read-derived cache only. Keep the verified bytes locked through delivery."""
        return service().material_thumbnail_v61(project_id, image_id, request, edge)

    return router
