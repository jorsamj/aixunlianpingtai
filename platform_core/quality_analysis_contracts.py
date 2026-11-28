from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel

class V44QualityReq(BaseModel):
    split: Optional[str] = None
    labels: Optional[List[str]] = None
    image_ids: Optional[List[str]] = None
    max_samples: int = 0
    snapshot_id: Optional[str] = None


class V45ErrorCauseReq(BaseModel):
    model_config_id: str
    limit: int = 12
