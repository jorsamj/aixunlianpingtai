from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

class ProjectCreate(BaseModel):
    name: str
    labels: Optional[List[Any]] = None
    description: Optional[str] = ""
    label_meta: Optional[List[Dict[str, Any]]] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
