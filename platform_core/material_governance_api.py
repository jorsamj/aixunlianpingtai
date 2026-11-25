"""HTTP adapters, registered in original groups to preserve route precedence."""
from __future__ import annotations
from typing import Any, Callable, Dict, List, Literal, Optional, Mapping, Tuple
from fastapi import APIRouter, Body, Query, Request
from .material_governance_service import MaterialGovernanceService
from .material_governance_contracts import BatchImageSplitReq, BatchSplitReq, ImagePatchReq, V46BatchDeleteImagesReq, V52ReadyReq


def create_material_governance_router_1(service: Callable[[], MaterialGovernanceService]) -> APIRouter:
    router = APIRouter()

    @router.delete('/api/projects/{project_id}/datasets/{dataset_id}')
    def delete_dataset(project_id: str, dataset_id: str):
        return service().delete_dataset(project_id, dataset_id)

    return router


def create_material_governance_router_2(service: Callable[[], MaterialGovernanceService]) -> APIRouter:
    router = APIRouter()

    @router.delete('/api/projects/{project_id}/images/{image_id}')
    def delete_image(project_id: str, image_id: str, delete_source: Optional[bool]=None, confirmation: str=''):
        return service().delete_image(project_id, image_id, delete_source, confirmation)

    @router.post('/api/v46/projects/{project_id}/images/batch-delete')
    def v46_batch_delete_images(project_id: str, payload: V46BatchDeleteImagesReq):
        return service().v46_batch_delete_images(project_id, payload)

    return router


def create_material_governance_router_3(service: Callable[[], MaterialGovernanceService]) -> APIRouter:
    router = APIRouter()

    @router.patch('/api/v12/projects/{project_id}/images/{image_id}')
    def v12_patch_image(project_id: str, image_id: str, payload: ImagePatchReq):
        return service().v12_patch_image(project_id, image_id, payload)

    @router.post('/api/v20/projects/{project_id}/images/batch_split')
    def v20_batch_image_split(project_id: str, payload: BatchImageSplitReq):
        return service().v20_batch_image_split(project_id, payload)

    @router.post('/api/v12/projects/{project_id}/datasets/{dataset_id}/auto_split')
    def v12_auto_split(project_id: str, dataset_id: str, payload: BatchSplitReq):
        return service().v12_auto_split(project_id, dataset_id, payload)

    return router


def create_material_governance_router_4(service: Callable[[], MaterialGovernanceService]) -> APIRouter:
    router = APIRouter()

    @router.post('/api/v52/projects/{project_id}/images/mark-ready')
    def v52_mark_ready(project_id: str, payload: V52ReadyReq):
        return service().v52_mark_ready(project_id, payload)

    return router


def create_material_governance_router_5(service: Callable[[], MaterialGovernanceService]) -> APIRouter:
    router = APIRouter()

    @router.post('/api/v49/projects/{project_id}/images/mark-processed')
    def v49_mark_processed(project_id: str, payload: V46BatchDeleteImagesReq):
        return service().v49_mark_processed(project_id, payload)

    return router
