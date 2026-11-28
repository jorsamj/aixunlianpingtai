from __future__ import annotations
from typing import Any, Dict, Optional
from pydantic import BaseModel

class StorageSourceCreateReq(BaseModel):
    id: Optional[str] = None
    name: str
    type: str
    config: Dict[str, Any] = {}
    credentials: Dict[str, str] = {}
    enabled: bool = True


class StorageSourceUpdateReq(BaseModel):
    name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    credentials: Optional[Dict[str, str]] = None
    clear_credentials: bool = False
    enabled: Optional[bool] = None
