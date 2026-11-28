from __future__ import annotations
from typing import Literal
from pydantic import BaseModel

class DetectionBatchReviewReq(BaseModel):
    review: Literal["correct", "missed", "false_positive", "box_inaccurate", "wrong_class"]
    note: str = ""
