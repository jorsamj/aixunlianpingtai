from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel

class TrainingRobustnessPolicyReq(BaseModel):
    policy: Dict[str, Any]
    expected_revision: str


class LocalModelScanReq(BaseModel):
    roots: Optional[List[str]] = None
    max_results: int = 3000
    scope: Optional[Literal["directory", "full"]] = None


class UltralyticsEnvDetectReq(BaseModel):
    roots: Optional[List[str]] = None
    scope: Literal["auto", "fast", "full"] = "auto"


class TrainServerReq(BaseModel):
    name: str
    base_url: str
    api_key: Optional[str] = ""


class PaddleEnvReq(BaseModel):
    name: str = "本机飞桨"
    python_path: Optional[str] = ""
    paddledet_dir: Optional[str] = ""
    paddlex_dir: Optional[str] = ""


class PaddleDetectReq(BaseModel):
    roots: Optional[List[str]] = None
