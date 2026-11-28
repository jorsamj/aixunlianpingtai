from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class V19ImportStartReq(BaseModel):
    source_scan_digest: str = ""
    folder_rules: Optional[List[Dict[str, Any]]] = None
    selected_paths: Optional[List[str]] = None
    label_mapping: Dict[str, str] = Field(default_factory=dict)
    create_labels: List[str] = Field(default_factory=list)
    sample_type: str = ""
    intended_label_codes: List[str] = Field(default_factory=list)
    negative_category_ids: List[str] = Field(default_factory=list)
    algorithm_id: str = ""


class V19MultipartUploadReq(BaseModel):
    folder_confirmation: bool = False
    file_name: str
    file_size: int = Field(gt=0)
    fingerprint: str = ""
    part_size: int = 8 * 1024 * 1024
    resume_upload_id: str = ""
    algorithm_id: str = ""


class V36SourceImportScanReq(BaseModel):
    source: str
    source_type: str = "auto"  # auto / local_path / url
    dataset_kind: str = "auto"  # auto / images / yolo / coco / voc


class V36SourceImportStartReq(BaseModel):
    source: str
    source_type: str = "auto"
    dataset_kind: str = "auto"
    task_name: Optional[str] = "地址读取导入"
    split_policy: str = "annotated_train_unannotated_test"  # source / annotated_train_unannotated_test / ratio
    train_ratio: float = 0.8
    val_ratio: float = 0.2
    test_ratio: float = 0.0
    copy_mode: str = "copy"  # reserved
    selected_paths: Optional[List[str]] = None


class V55UploadDecisionsReq(BaseModel):
    clean_image_ids: Optional[List[Any]] = None
    ready_image_ids: Optional[List[Any]] = None
