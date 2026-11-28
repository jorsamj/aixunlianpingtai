from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional, Mapping, Tuple
from pydantic import BaseModel, Field, PrivateAttr

class AddLabelReq(BaseModel):
    label: str
    display_name: Optional[str] = ""
    color: Optional[str] = ""
    aliases: Optional[List[str]] = None


class AnnotationSave(BaseModel):
    _review_actor: str = PrivateAttr(default="")
    _review_codes: List[str] = PrivateAttr(default_factory=list)
    boxes: List[Dict[str, Any]]
    annotation_state: Optional[Literal["unannotated", "annotated", "confirmed_empty"]] = None
    expected_version: Optional[int] = None
    source_content_sha256: Optional[str] = None
    reviewed_label_codes: List[str] = Field(default_factory=list)


class LabelUpdateReq(BaseModel):
    code: Optional[str] = None
    display_name: Optional[str] = None
    color: Optional[str] = None
    hotkey: Optional[str] = None
    aliases: Optional[List[str]] = None


class V52LabelRemapReq(BaseModel):
    image_ids: List[str]
    source_label: str
    target_label: str


class V54LabelUnifyReq(BaseModel):
    target_label: str


class V54LabelsUnifyReq(BaseModel):
    source_class_ids: List[int] = Field(default_factory=list)
    target_label: str


class V54LabelsUnifyPreviewReq(BaseModel):
    source_class_ids: List[int] = Field(default_factory=list)
