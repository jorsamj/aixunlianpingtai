from __future__ import annotations
from typing import List, Literal
from pydantic import BaseModel, Field

class SupplementFeedbackCandidateSelection(BaseModel):
    feedback_id: str
    candidate_digest: str


class FreezeSupplementFeedbackCandidatesReq(BaseModel):
    candidates: List[SupplementFeedbackCandidateSelection] = Field(min_length=1, max_length=500)


class EvaluationReviewReq(BaseModel):
    expected_evaluation_id: str
    image_id: str
    observation: str = ''
    note: str = ''


class ReviewedMiningSelection(BaseModel):
    image_id: str
    candidate_digest: str


class FreezeReviewedMiningReq(BaseModel):
    candidates: List[ReviewedMiningSelection]
    confirmed: bool = False


class HardSampleMiningCreateReq(BaseModel):
    image_ids: List[str]
    source: Literal["existing", "upload"] = "existing"
    request_key: str = ""
