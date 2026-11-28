from __future__ import annotations
from typing import Optional
from pydantic import BaseModel

class BuildDatasetReq(BaseModel):
    train_ratio: float = 0.8
    include_empty: bool = False
    dataset_id: Optional[str] = None


class BuildPaddleDatasetReq(BaseModel):
    train_ratio: float = 0.8
    include_empty: bool = False
