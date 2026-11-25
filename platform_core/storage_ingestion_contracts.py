from __future__ import annotations
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field
from pydantic import model_validator
from platform_core.storage.zip_import import ServerZipImportError, safe_member_path

class StorageImportScanReq(BaseModel):
    mode: Literal["storage_scan", "directory_scan", "server_zip"] = "storage_scan"
    execution_mode: Literal["local", "agent"] = "local"
    storage_source_id: str
    prefix: str = ""
    recursive: bool = True
    zip_path: Optional[str] = None
    target_prefix: str = ""
    import_format: Literal['auto', 'images', 'yolo', 'coco', 'voc'] = 'images'
    dataset_yaml: Optional[str] = None

    @model_validator(mode="after")
    def validate_mode_fields(self):
        if self.import_format in {'coco', 'voc'} and not (
            self.execution_mode == "agent"
            and self.mode in {"storage_scan", "server_zip"}
        ):
            raise ValueError('COCO/VOC 当前仅支持远程 Agent 的对象存储目录或服务器 ZIP 导入')
        if self.dataset_yaml:
            value = self.dataset_yaml.replace('\\', '/')
            if value.startswith('/') or ':' in value or '..' in value.split('/'):
                raise ValueError('dataset_yaml 必须是存储源内的相对路径')
            if self.import_format != 'yolo':
                raise ValueError('只有 YOLO 模式可以提交 dataset_yaml')
        zip_path = str(self.zip_path or "").strip()
        target_prefix = str(self.target_prefix or "").strip()
        if self.execution_mode == "agent":
            if self.mode not in {"server_zip", "storage_scan"}:
                raise ValueError("Agent 素材导入仅支持对象存储扫描或服务器 ZIP 模式")
            allowed_formats = {"images", "yolo", "coco", "voc"}
            if self.import_format not in allowed_formats:
                raise ValueError("Agent 当前模式不支持所选素材格式")
            if self.import_format == "images" and self.dataset_yaml:
                raise ValueError("Agent 仅图片模式不接受 dataset_yaml")
            if self.dataset_yaml:
                try:
                    safe_member_path(str(self.dataset_yaml)).as_posix()
                except ServerZipImportError as error:
                    raise ValueError("Agent dataset_yaml 必须是扫描目录或 ZIP 根内的安全相对路径") from error
        if self.mode == "server_zip":
            if not zip_path:
                raise ValueError("服务器 ZIP 模式必须选择 ZIP 文件")
            if not target_prefix:
                raise ValueError("服务器 ZIP 模式必须填写目标目录")
            if str(self.prefix or "").strip():
                raise ValueError("服务器 ZIP 模式不能同时提交扫描目录")
        elif zip_path:
            raise ValueError("非服务器 ZIP 模式不能提交 ZIP 文件")
        elif target_prefix:
            raise ValueError("非服务器 ZIP 模式不能提交 ZIP 目标目录")
        return self


class StorageImportConfirmReq(BaseModel):
    object_keys: Optional[List[str]] = None
    label_mapping: Dict[str, str] = Field(default_factory=dict)
    create_labels: List[str] = Field(default_factory=list)
    accept_quality_report: bool = False


class StorageRescanCreateReq(BaseModel):
    execution_mode: Literal["local", "agent"] = "local"
    import_format: Literal["images", "yolo", "coco", "voc"] = "images"
    dataset_yaml: str = ""

    @model_validator(mode="after")
    def validate_rescan_format(self):
        self.dataset_yaml = str(self.dataset_yaml or "").strip().replace("\\", "/")
        if self.import_format != "yolo" and self.dataset_yaml:
            raise ValueError("dataset_yaml 仅适用于 YOLO 重新扫描")
        return self


class StorageRescanConfirmReq(BaseModel):
    new: Literal['import', 'ignore'] = 'import'
    missing: Literal['mark_unavailable', 'ignore'] = 'mark_unavailable'
    changed: Literal['update', 'ignore'] = 'update'
    annotation_changed: Literal['update', 'ignore'] = 'update'
    annotation_removed: Literal['clear', 'keep'] = 'keep'
    annotation_conflicts: Literal['overwrite', 'keep'] = 'keep'
    label_mapping: Dict[str, str] = Field(default_factory=dict)
    create_labels: List[str] = Field(default_factory=list)
    accept_quality_report: bool = False
