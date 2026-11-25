from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel

class PrelabelServiceReq(BaseModel):
    name: str
    detect_url: str
    health_url: Optional[str] = ""
    request_mode: str = "json_base64"  # json_base64 / multipart_file
    image_field: str = "image"
    threshold: float = 0.5
    target_label: str = "person"


class V35ModelConfigReq(BaseModel):
    name: str
    provider_type: str = "local"  # local / cloud
    provider_adapter: Optional[str] = ""
    api_protocol: Literal["auto", "chat_completions", "responses"] = "auto"
    structured_output: Literal["auto", "json_schema", "json_object", "prompt"] = "auto"
    coordinate_space: Literal["pixel", "normalized_01", "normalized_1000"] = "pixel"
    coordinate_order: Literal["xyxy", "yxyx"] = "xyxy"
    output_protocol: Literal["json_boxes"] = "json_boxes"
    coordinate_origin: Literal["top_left", "bottom_left"] = "top_left"
    coordinate_image_space: Literal["original_input", "processed_image"] = "original_input"
    coordinate_contract_version: Literal[1] = 1
    model_kind: str = "vision_detect"  # vision_detect / vlm / custom_http
    base_url: Optional[str] = ""
    detect_url: Optional[str] = ""
    health_url: Optional[str] = ""
    api_key: Optional[str] = ""
    model_name: Optional[str] = ""
    request_mode: str = "json_base64"  # json_base64 / multipart_file
    image_field: str = "image"
    prompt_field: str = "prompt"
    threshold_field: str = "threshold"
    headers_json: Optional[Dict[str, Any]] = None
    remark: Optional[str] = ""
    # v42.7: keep ordinary-user workflows simple; the system uses these templates automatically.
    annotation_prompt_template: Optional[str] = ""
    # Native WeVisOne detection query for each durable class code; not a chat prompt.
    wevisone_label_queries: Optional[Dict[str, str]] = None
    training_intervention_prompt: Optional[str] = ""
    default_for_annotation: bool = False
    default_for_training_ai: bool = False
    enabled: bool = True


class V35PromptTemplateReq(BaseModel):
    name: str
    framework: str = "ultralytics"  # ultralytics / paddle / common
    task_type: str = "目标检测"
    labels: Optional[List[str]] = None
    prompt: str
    output_schema: str = "bbox_json"
    model_config_id: Optional[str] = ""
    threshold: float = 0.5
    save_format: str = "internal"  # internal / yolo / paddle
    overwrite: bool = False
    remark: Optional[str] = ""


class V35PromptPreviewReq(BaseModel):
    prompt: str
    labels: Optional[List[Dict[str, Any]]] = None
    image_width: int = 640
    image_height: int = 480
    business_instruction: str = ""


class V35ModelAvailabilityReq(BaseModel):
    enabled: bool


class V35CoordinateSampleReq(BaseModel):
    image_base64: str
    labels: List[str]
    operation: Literal["detect", "segment", "matting"] = "detect"


class V35CoordinateConfirmationReq(BaseModel):
    receipt: str
    config_revision: str
    sample_sha256: str
    positions_confirmed: Literal[True]
