from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

class V47CleanReq(BaseModel):
    image_ids: Optional[List[str]] = None
    selection_spec: Optional[Dict[str, Any]] = None
    selection_mode: Optional[Literal['all', 'selected', 'labels']] = None
    clean_scope: Literal['all', 'annotated', 'unannotated', 'confirmed_empty', 'selected'] = 'all'
    execution_mode: Literal['local', 'agent'] = 'local'
    scheduling_mode: Literal['auto', 'node'] = 'auto'
    target_node_id: str = Field(default='', max_length=128)
    queue_policy: Literal['normal', 'front', 'preempt'] = 'normal'
    exact_duplicate: bool = True
    near_duplicate: bool = True
    near_duplicate_hamming: int = 5
    min_width: int = 320
    min_height: int = 240
    max_width: int = 10000
    max_height: int = 10000
    blur_check: bool = True
    blur_min_laplacian: float = 45.0
    brightness_check: bool = False
    brightness_min: float = 15.0
    brightness_max: float = 245.0
    corrupt_check: bool = True
    task_name: str = '自动清洗任务'


class V47CleanConfirmReq(BaseModel):
    delete_ids: List[str]
    skip_image_ids: List[str] = Field(default_factory=list)


class V47CleanRuntimeReq(BaseModel):
    image_ids: Optional[List[str]] = None
    selection_spec: Optional[Dict[str, Any]] = None
    selection_mode: Optional[Literal['all', 'selected', 'labels']] = None
    clean_scope: Literal['all', 'annotated', 'unannotated', 'confirmed_empty', 'selected'] = 'all'
