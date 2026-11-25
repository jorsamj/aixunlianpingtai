from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, StrictInt
from platform_core.annotation_candidates import CandidateDecision

class AnnotationTaskCreateReq(BaseModel):
    image_ids: List[str]
    # Opt-in ZIP origin; the server freezes the actual unannotated image list
    # without making the browser round-trip thousands of IDs.
    selection_ref: Optional[str] = None
    excluded_image_ids: List[str] = Field(default_factory=list, max_length=10000)
    source_batch_id: Optional[str] = None
    labels_text: str = ""
    reference_image_ids: Optional[List[str]] = None
    threshold: float = 0.45
    overwrite: bool = False
    task_name: str = "AI自动标注任务"
    provider_id: Optional[str] = None
    model_config_id: Optional[str] = None
    prompt_template_id: Optional[str] = None
    business_instruction: str = ""
    prompt_override: str = Field(default="", max_length=12000)
    preview_count: int = 0
    # Browser retries keep this stable until the confirmed configuration changes.
    # Older API callers may omit it and retain their original creation behavior.
    request_id: str = ""
    # Opt-in supplemental GT review. The server derives missing labels per
    # image from formal GT; the browser must not supply its own GT scopes.
    review_scope_policy: Literal["task_uniform_legacy", "per_image_required"] = "task_uniform_legacy"
    expected_material_revision: Optional[int] = None
    expected_annotation_revision: Optional[int] = None


class AnnotationDecisionReq(BaseModel):
    decisions: List[CandidateDecision]
    reject_unmentioned: bool = True
    accept_unmentioned: bool = False
    commit: bool = True
    # Human-confirmed partial formal GT commit; all other task candidates remain pending.
    commit_selected: bool = False
    label_mapping: Dict[str, str] = Field(default_factory=dict)
    # Opt-in isolated decision; older clients keep their batch/mapping behavior.
    single_candidate: bool = False
    # Optional durable review submission identity; legacy callers remain valid.
    request_id: str = ""
    review_revision: Optional[int] = Field(default=None, ge=0)
    expected_remaining: Optional[int] = Field(default=None, ge=0)


class AnnotationSelectionMembershipReq(BaseModel):
    selection_ref: str
    image_ids: List[str] = Field(default_factory=list, max_length=100)


class AnnotationComparisonReq(BaseModel):
    baseline: List[dict] = Field(default_factory=list, max_length=500)
    predictions: List[dict] = Field(default_factory=list, max_length=500)
    complete: bool = False
    image_width: Optional[int] = Field(default=None, gt=0)
    threshold: float = Field(default=0.5, gt=0, le=1)


class AnnotationDraftReq(BaseModel):
    boxes: List[Dict[str, Any]] = Field(default_factory=list, max_length=300)
    revision: int = Field(ge=0)
    request_id: str
    source_content_sha256: Optional[str] = None
    auto_resolution: bool = False


class AnnotationDraftBatchEntry(AnnotationDraftReq):
    image_id: str


class AnnotationDraftBatchReq(BaseModel):
    items: List[AnnotationDraftBatchEntry] = Field(min_length=1, max_length=25)


class BulkFormalIntentReq(BaseModel):
    request_id: str = Field(min_length=12, max_length=80)
    selection_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    review_revision: StrictInt = Field(ge=0)
    excluded_image_ids: list[str] = Field(default_factory=list, max_length=50000)


class AnnotationTransferReq(BaseModel):
    request_id: str
    image_ids: List[str] = Field(default_factory=list, max_length=200)
    selection_id: Optional[str] = None
    excluded_image_ids: List[str] = Field(default_factory=list, max_length=50000)
    category_ids: List[str] = Field(min_length=1, max_length=100)
    algorithm_id: str = ''
    confirm_absent: bool = False
    review_revision: Optional[int] = None
