"""Unchanged request contracts for the existing v12 algorithm catalog API."""
from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel

class AlgorithmReq(BaseModel):
    name: str
    remark: Optional[str] = ""
    industry: Optional[str] = ""
    algorithm_type: Optional[str] = ""


class AlgorithmVersionReq(BaseModel):
    model_name: str
    model_source: str = "project"  # project / local
    local_path: Optional[str] = ""
    job_id: Optional[str] = ""
    version_name: Optional[str] = ""
    remark: Optional[str] = ""


class VersionPatchReq(BaseModel):
    version_name: Optional[str] = None
    remark: Optional[str] = None


class AlgorithmVersionRollbackReq(BaseModel):
    # Product contract: rollback means deleting the current version.
    delete_current_version: Literal[True] = True
    expected_current_version_id: Optional[str] = None

