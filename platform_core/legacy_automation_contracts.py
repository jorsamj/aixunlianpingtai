from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel

class V42AlgorithmBlueprintReq(BaseModel):
    name: str
    remark: Optional[str] = ""
    industry: Optional[str] = ""
    algorithm_type: Optional[str] = "yolo_ultralytics"
    template_id: Optional[str] = "custom"
    labels: List[str] = []
    focus_scenes: Optional[str] = ""
    negative_scenes: Optional[str] = ""


class V42SourceReq(BaseModel):
    name: str
    type: str = 'folder'  # folder / rtsp / http_json
    source: str
    headers_json: Optional[str] = ''
    items_path: Optional[str] = 'items'
    image_url_field: Optional[str] = 'image_url'
    enabled: bool = True
    collect_mode: str = 'manual'  # manual / auto
    schedule_type: str = 'interval'  # interval / daily
    schedule_value: str = '60'  # minutes for interval; HH:MM for daily
    dataset_id: str = 'default'
    max_items: int = 50
    interval_seconds: float = 2.0
    remark: Optional[str] = ''


class V42CollectReq(BaseModel):
    dataset_id: str = 'default'
    max_items: int = 50
    interval_seconds: float = 2.0
