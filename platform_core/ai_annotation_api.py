"""HTTP adapters registered in original order; shared legacy selection types are injected."""
from pydantic import BaseModel
from typing import Any, Callable, Dict, Literal, Optional
from fastapi import APIRouter, Body, Query, Request
from .ai_annotation_service import AiAnnotationService
from .ai_annotation_contracts import AnnotationComparisonReq, AnnotationDecisionReq, AnnotationDraftBatchReq, AnnotationDraftReq, AnnotationSelectionMembershipReq, AnnotationTaskCreateReq, AnnotationTransferReq, BulkFormalIntentReq



def create_ai_annotation_router_1(service: Callable[[], AiAnnotationService]) -> APIRouter:
    router = APIRouter()

    @router.post('/api/v60/projects/{project_id}/annotation-tasks')
    def create_annotation_task(project_id: str, payload: AnnotationTaskCreateReq):
        return service().create_annotation_task(project_id, payload)

    @router.get('/api/v60/projects/{project_id}/annotation-tasks/by-request/{request_id}')
    def get_annotation_task_by_create_request(project_id: str, request_id: str):
        return service().get_annotation_task_by_create_request(project_id, request_id)

    return router


def create_ai_annotation_router_2(service: Callable[[], AiAnnotationService], AnnotationSelectionReq: type[BaseModel]) -> APIRouter:
    router = APIRouter()

    @router.post('/api/v60/projects/{project_id}/annotation-selections')
    def freeze_annotation_selection(project_id: str, payload: AnnotationSelectionReq):
        return service().freeze_annotation_selection(project_id, payload)

    @router.post('/api/v60/projects/{project_id}/annotation-selections/summary')
    def annotation_selection_summary(project_id: str, payload: AnnotationSelectionReq):
        return service().annotation_selection_summary(project_id, payload)

    @router.post('/api/v60/projects/{project_id}/annotation-selections/membership')
    def annotation_selection_membership(project_id: str, payload: AnnotationSelectionMembershipReq):
        return service().annotation_selection_membership(project_id, payload)

    @router.post('/api/v60/projects/{project_id}/annotation-preview/compare')
    def compare_annotation_preview(project_id: str, payload: AnnotationComparisonReq):
        return service().compare_annotation_preview(project_id, payload)

    @router.post('/api/v60/projects/{project_id}/annotation-preview')
    def preview_annotation_image(project_id: str, payload: AnnotationTaskCreateReq):
        """Explicit one-image model dry run; never create a task, candidate or GT.

        Reuse the same frozen model, prompt, label contract and inference adapter as
        AI_ANNOTATION. A preview is deliberately bounded and opt-in because the
        configured provider may be remote and may charge for each inference.
        """
        return service().preview_annotation_image(project_id, payload)

    @router.get('/api/v60/projects/{project_id}/annotation-tasks')
    def list_annotation_tasks(project_id: str, limit: int=50, cursor: Optional[str]=None, status: str='', q: str='', retry_index: bool=False, reader_view: bool=False):
        return service().list_annotation_tasks(project_id, limit, cursor, status, q, retry_index, reader_view)

    @router.get('/api/v60/projects/{project_id}/annotation-tasks/{task_id}')
    def get_annotation_task(project_id: str, task_id: str, reader_view: bool=False):
        return service().get_annotation_task(project_id, task_id, reader_view)

    @router.get('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/gt-audit')
    def audit_annotation_task_gt(project_id: str, task_id: str, limit: int=50, cursor: Optional[str]=None):
        """Explicit, bounded read-only comparison; never infer a whole-task GT total."""
        return service().audit_annotation_task_gt(project_id, task_id, limit, cursor)

    @router.get('/api/v60/projects/{project_id}/annotation-material-states')
    def annotation_material_states(project_id: str, image_ids: str=''):
        return service().annotation_material_states(project_id, image_ids)

    @router.get('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/candidates')
    def get_annotation_candidates(project_id: str, task_id: str, limit: int=50, cursor: Optional[str]=None, filter: str='all', reader_view: bool=False, selection_id: Optional[str]=None, request: Request=None):
        return service().get_annotation_candidates(project_id, task_id, limit, cursor, filter, reader_view, selection_id, request)

    @router.get('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/candidates/{image_id}')
    def get_annotation_candidate(project_id: str, task_id: str, image_id: str):
        return service().get_annotation_candidate(project_id, task_id, image_id)

    @router.put('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/candidates/{image_id}/draft')
    def save_annotation_review_draft(project_id: str, task_id: str, image_id: str, payload: AnnotationDraftReq, request: Request):
        return service().save_annotation_review_draft(project_id, task_id, image_id, payload, request)

    @router.post('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/candidates/drafts-batch')
    def save_annotation_review_drafts_batch(project_id: str, task_id: str, payload: AnnotationDraftBatchReq, request: Request):
        """Batch transport only: reuse the original one-image lock, source and CAS contract."""
        return service().save_annotation_review_drafts_batch(project_id, task_id, payload, request)

    return router


def create_ai_annotation_router_3(service: Callable[[], AiAnnotationService], AnnotationSelectionReq: type[BaseModel]) -> APIRouter:
    router = APIRouter()

    @router.post('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/ambiguity/{request_id}/freeze-drafts')
    def freeze_ambiguity_task_drafts(project_id: str, task_id: str, request_id: str, request: Request):
        return service().freeze_ambiguity_task_drafts(project_id, task_id, request_id, request)

    @router.post('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/ambiguity/{request_id}/{phase}', status_code=202)
    def create_annotation_ambiguity_task(project_id: str, task_id: str, request_id: str, phase: Literal['plan', 'save'],
                                         request: Request, payload: dict = Body(...)):
        return service().annotation_ambiguity_task(project_id, task_id, request_id, phase, request, payload)

    @router.get('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/ambiguity/{request_id}/{phase}')
    def read_annotation_ambiguity_task(project_id: str, task_id: str, request_id: str, phase: Literal['plan', 'save'], request: Request):
        return service().annotation_ambiguity_task(project_id, task_id, request_id, phase, request)

    @router.post('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/review-selection')
    def create_annotation_review_selection(project_id: str, task_id: str, payload: AnnotationSelectionReq, request: Request):
        return service().create_annotation_review_selection(project_id, task_id, payload, request)

    @router.post('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/bulk-formal/intents')
    def accept_bulk_formal_intent(project_id: str, task_id: str, payload: BulkFormalIntentReq, request: Request):
        return service().accept_bulk_formal_intent(project_id, task_id, payload, request)

    @router.get('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/bulk-formal/intents/{request_id}')
    def read_bulk_formal_intent(project_id: str, task_id: str, request_id: str, request: Request):
        return service().read_bulk_formal_intent(project_id, task_id, request_id, request)

    @router.post('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/bulk-formal/intents/{request_id}/execute')
    def execute_bulk_formal_intent(project_id: str, task_id: str, request_id: str, request: Request):
        """Register the single execution task; never write GT inside this request."""
        return service().execute_bulk_formal_intent(project_id, task_id, request_id, request)

    @router.get('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/bulk-formal/intents/{request_id}/execution')
    def read_bulk_formal_execution(project_id: str, task_id: str, request_id: str, request: Request):
        return service().read_bulk_formal_execution(project_id, task_id, request_id, request)

    @router.post('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/bulk-formal/intents/{request_id}/execution/cancel')
    def cancel_bulk_formal_execution(project_id: str, task_id: str, request_id: str, request: Request):
        return service().cancel_bulk_formal_execution(project_id, task_id, request_id, request)

    @router.post('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/bulk-formal/intents/{request_id}/execution/recover')
    def recover_bulk_formal_execution(project_id: str, task_id: str, request_id: str, request: Request):
        """Re-verify persisted facts, then requeue a durable evidence block."""
        return service().recover_bulk_formal_execution(project_id, task_id, request_id, request)

    @router.get('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/review-selection/{selection_id}/candidates')
    def get_annotation_review_selection_candidates(project_id: str, task_id: str, selection_id: str, request: Request, cursor: int=0, limit: int=100, ambiguity_revision: int | None=Query(default=None, ge=0)):
        """Bounded read of the already frozen selection; no second cache or GT write."""
        return service().get_annotation_review_selection_candidates(project_id, task_id, selection_id, request, cursor, limit, ambiguity_revision=ambiguity_revision)

    @router.post('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/negative-transfer')
    def transfer_annotation_candidates(project_id: str, task_id: str, payload: AnnotationTransferReq, request: Request):
        return service().transfer_annotation_candidates(project_id, task_id, payload, request)

    @router.get('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/negative-transfers')
    def list_annotation_transfers(project_id: str, task_id: str, request: Request, cursor: str='', limit: int=Query(default=25, ge=1, le=50)):
        return service().list_annotation_transfers(project_id, task_id, request, cursor, limit)

    @router.get('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/negative-transfer/{request_id}')
    def get_annotation_transfer(project_id: str, task_id: str, request_id: str, request: Request, offset: int=Query(default=0, ge=0, le=50000), limit: int=Query(default=100, ge=1, le=200), own: bool=False):
        return service().get_annotation_transfer(project_id, task_id, request_id, offset, limit, request=request if own else None)

    @router.post('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/negative-transfer/{request_id}/undo')
    def undo_annotation_transfer(project_id: str, task_id: str, request_id: str, request: Request, own: bool=False):
        return service().undo_annotation_transfer(project_id, task_id, request_id, request, own=own)

    @router.post('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/negative-transfer-preview')
    def preview_annotation_transfer(project_id: str, task_id: str, payload: AnnotationTransferReq, request: Request):
        return service().preview_annotation_transfer(project_id, task_id, payload, request)

    @router.get('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/candidates/{image_id}/diagnostics')
    def get_annotation_candidate_diagnostics(project_id: str, task_id: str, image_id: str):
        return service().get_annotation_candidate_diagnostics(project_id, task_id, image_id)

    @router.post('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/decisions')
    def decide_annotation_candidates(project_id: str, task_id: str, payload: AnnotationDecisionReq, request: Request):
        return service().decide_annotation_candidates(project_id, task_id, payload, request)

    @router.get('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/decisions/by-request/{request_id}')
    def get_annotation_review_operation(project_id: str, task_id: str, request_id: str, request: Request):
        return service().get_annotation_review_operation(project_id, task_id, request_id, request)

    @router.post('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/cancel')
    def cancel_annotation_task(project_id: str, task_id: str):
        return service().cancel_annotation_task(project_id, task_id)

    @router.post('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/retry')
    def retry_annotation_task(project_id: str, task_id: str, retry_payload: Optional[Dict[str, Any]]=Body(default=None)):
        return service().retry_annotation_task(project_id, task_id, retry_payload)

    @router.post('/api/v60/projects/{project_id}/annotation-tasks/{task_id}/review-completed')
    def review_completed_annotation_task(project_id: str, task_id: str):
        """Recover already-persisted successes for human review, never formal GT."""
        return service().review_completed_annotation_task(project_id, task_id)

    return router
