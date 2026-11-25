from __future__ import annotations
from typing import List
from pydantic import BaseModel, Field

class V48TrainingBatchDeleteReq(BaseModel):
    job_ids: List[str] = Field(default_factory=list)
