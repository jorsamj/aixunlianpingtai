"""HTTP router for reviewable online inference feedback (v63).

Moved out of ``app.py``. The host application injects its infra dependencies
explicitly; request parsing/response envelopes live here, business rules live in
:class:`platform_core.online_feedback_service.OnlineFeedbackService`.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel

from .online_feedback_service import CORRECTION_KINDS, OnlineFeedbackService


OnlineFeedbackCorrectionKind = Literal[
    "", "missed_detection", "wrong_class", "inaccurate_box", "partial_correction", "other",
]


class OnlineFeedbackCreateReq(BaseModel):
    prediction_id: str
    feedback_type: Literal["correct", "false_positive", "needs_correction"]
    note: str = ""
    # Optional, additive defect kind. Only "needs_correction" may carry one and
    # such feedback can only become reviewed candidate data, never direct GT.
    correction_kind: OnlineFeedbackCorrectionKind = ""


class OnlineFeedbackConfirmReq(BaseModel):
    expected_feedback_type: Literal["correct", "false_positive", "needs_correction"]
    dataset_id: str = "default"
    confirm_all_labels_absent: bool = False
    # Stable optional operation identity: a client that lost the response can
    # retry the exact review and read back the same persisted GT receipt.
    request_id: str = ""


class OnlineFeedbackDismissReq(BaseModel):
    expected_feedback_type: Literal["correct", "false_positive", "needs_correction"]
    reason: str = ""


def create_online_feedback_router(service: OnlineFeedbackService) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v63/projects/{project_id}/online-feedback")
    def list_online_feedback(project_id: str, status: str = "", limit: int = 100):
        return {"ok": True, "items": service.list_feedback(project_id, status=status, limit=limit)}

    @router.get("/api/v63/projects/{project_id}/online-feedback/{feedback_id}")
    def get_online_feedback(project_id: str, feedback_id: str):
        return {"ok": True, "feedback": service.feedback_detail(project_id, feedback_id)}

    @router.post("/api/v63/projects/{project_id}/online-feedback", status_code=201)
    def create_online_feedback(project_id: str, payload: OnlineFeedbackCreateReq):
        idempotent, feedback = service.stage_feedback(
            project_id,
            prediction_id=payload.prediction_id,
            feedback_type=payload.feedback_type,
            note=payload.note,
            correction_kind=payload.correction_kind,
        )
        return {"ok": True, "idempotent": idempotent, "feedback": feedback}

    @router.post("/api/v63/projects/{project_id}/online-feedback/external-intake", status_code=201)
    async def create_external_online_feedback(
        project_id: str,
        algorithm_id: str = Form(...),
        version_id: str = Form(...),
        model_sha256: str = Form(...),
        external_source: str = Form(...),
        external_sample_id: str = Form(...),
        feedback_type: Literal["correct", "false_positive", "needs_correction"] = Form(...),
        detections_json: str = Form("[]"),
        confidence: float = Form(0.25),
        note: str = Form(""),
        correction_kind: OnlineFeedbackCorrectionKind = Form(""),
        file: UploadFile = File(...),
    ):
        idempotent, feedback = await service.stage_external_feedback(
            project_id,
            algorithm_id=algorithm_id,
            version_id=version_id,
            model_sha256=model_sha256,
            external_source=external_source,
            external_sample_id=external_sample_id,
            feedback_type=feedback_type,
            detections_json=detections_json,
            confidence=confidence,
            note=note,
            correction_kind=correction_kind,
            upload=file,
        )
        return {"ok": True, "idempotent": idempotent, "feedback": feedback}

    @router.post("/api/v63/projects/{project_id}/online-feedback/{feedback_id}/confirm")
    def confirm_online_feedback(
        project_id: str, feedback_id: str, payload: OnlineFeedbackConfirmReq,
        request: Request,
    ):
        idempotent, feedback = service.confirm_feedback(project_id, feedback_id, payload, request)
        return {"ok": True, "idempotent": idempotent, "feedback": feedback}

    @router.post("/api/v63/projects/{project_id}/online-feedback/{feedback_id}/dismiss")
    def dismiss_online_feedback(
        project_id: str, feedback_id: str, payload: OnlineFeedbackDismissReq,
    ):
        idempotent, feedback = service.dismiss_feedback(project_id, feedback_id, payload)
        return {"ok": True, "idempotent": idempotent, "feedback": feedback}

    return router
