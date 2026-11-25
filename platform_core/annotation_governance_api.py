"""HTTP adapters, registered in original groups to preserve route precedence."""
from __future__ import annotations
from typing import Any, Callable, Dict, List, Literal, Optional, Mapping, Tuple
from fastapi import APIRouter, Body, Query, Request
from .annotation_governance_service import AnnotationGovernanceService
from .annotation_governance_contracts import AddLabelReq, AnnotationSave, LabelUpdateReq, V52LabelRemapReq, V54LabelUnifyReq, V54LabelsUnifyPreviewReq, V54LabelsUnifyReq


def create_annotation_governance_router_1(service: Callable[[], AnnotationGovernanceService]) -> APIRouter:
    router = APIRouter()

    @router.post('/api/projects/{project_id}/labels')
    def add_label(project_id: str, payload: AddLabelReq):
        return service().add_label(project_id, payload)

    return router


def create_annotation_governance_router_2(service: Callable[[], AnnotationGovernanceService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/projects/{project_id}/annotations/{image_id}')
    def get_annotation(project_id: str, image_id: str, reader_view: bool=False):
        return service().get_annotation(project_id, image_id, reader_view)

    @router.post('/api/projects/{project_id}/annotations/{image_id}')
    def save_annotation(project_id: str, image_id: str, payload: AnnotationSave):
        return service().save_annotation(project_id, image_id, payload)

    return router


def create_annotation_governance_router_3(service: Callable[[], AnnotationGovernanceService]) -> APIRouter:
    router = APIRouter()

    @router.put('/api/v12/projects/{project_id}/labels/{class_id}')
    def v12_update_label(project_id: str, class_id: int, payload: LabelUpdateReq):
        return service().v12_update_label(project_id, class_id, payload)

    @router.delete('/api/v12/projects/{project_id}/labels/{class_id}')
    def v12_delete_label(project_id: str, class_id: int):
        return service().v12_delete_label(project_id, class_id)

    return router


def create_annotation_governance_router_4(service: Callable[[], AnnotationGovernanceService]) -> APIRouter:
    router = APIRouter()

    @router.post('/api/v52/projects/{project_id}/labels/remap')
    def v52_remap_import_labels(project_id: str, payload: V52LabelRemapReq):
        return service().v52_remap_import_labels(project_id, payload)

    return router


def create_annotation_governance_router_5(service: Callable[[], AnnotationGovernanceService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v54/projects/{project_id}/label-schema')
    def v54_label_schema(project_id: str):
        return service().v54_label_schema(project_id)

    @router.post('/api/v54/projects/{project_id}/labels/unify/preview')
    def v54_preview_unify_labels(project_id: str, payload: V54LabelsUnifyPreviewReq):
        return service().v54_preview_unify_labels(project_id, payload)

    @router.post('/api/v54/projects/{project_id}/labels/unify')
    def v54_unify_labels(project_id: str, payload: V54LabelsUnifyReq):
        return service().v54_unify_labels(project_id, payload)

    @router.post('/api/v54/projects/{project_id}/labels/{class_id}/unify')
    def v54_unify_label(project_id: str, class_id: int, payload: V54LabelUnifyReq):
        return service().v54_unify_label(project_id, class_id, payload)

    return router
