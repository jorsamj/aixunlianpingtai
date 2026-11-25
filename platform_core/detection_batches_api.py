"""HTTP adapters registered at their original positions to retain matching order."""
from typing import Callable
from fastapi import APIRouter, Query
from .detection_batches_service import DetectionBatchesService
from .detection_batches_contracts import DetectionBatchReviewReq



def create_detection_batches_router_1(service: Callable[[], DetectionBatchesService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v64/projects/{project_id}/detection-batches')
    def list_detection_batches(project_id: str, limit: int=Query(default=12, ge=1, le=50)):
        return service().list_detection_batches(project_id, limit)

    @router.get('/api/v64/projects/{project_id}/detection-batches/{batch_id}')
    def get_detection_batch(project_id: str, batch_id: str):
        return service().get_detection_batch(project_id, batch_id)

    @router.post('/api/v64/projects/{project_id}/detection-batches/{batch_id}/items/{item_index}/review')
    def review_detection_batch_item(project_id: str, batch_id: str, item_index: int, payload: DetectionBatchReviewReq):
        return service().review_detection_batch_item(project_id, batch_id, item_index, payload)

    return router
