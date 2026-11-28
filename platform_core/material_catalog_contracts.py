from __future__ import annotations
from typing import Optional
from pydantic import BaseModel

class DatasetReq(BaseModel):
    name: str
    description: Optional[str] = ""

