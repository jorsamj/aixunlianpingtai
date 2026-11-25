from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional, Mapping, Tuple
from pydantic import BaseModel, Field

class V46BatchDeleteImagesReq(BaseModel):
    image_ids: List[str]
    delete_source: Optional[bool] = None
    confirmation: str = ""


class ImagePatchReq(BaseModel):
    split: Optional[str] = None  # train / val / test
    dataset_id: Optional[str] = None


class BatchSplitReq(BaseModel):
    train: float = 0.7
    val: float = 0.2
    test: float = 0.1
    include_unannotated: bool = True


class BatchImageSplitReq(BaseModel):
    image_ids: List[str] = []
    split: str = "unassigned"
    dataset_id: Optional[str] = None
    filter: Optional[str] = None  # all / marked / unmarked / train / val / test
    scope: str = "selected"  # selected / filtered / dataset


class V52ReadyReq(BaseModel):
    image_ids: List[str]


class V47ImageEditReq(BaseModel):
    name: Optional[str] = None
