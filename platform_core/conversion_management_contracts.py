from __future__ import annotations
from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel

class ModelExportReq(BaseModel):
    model_name: str
    model_source: str = "project"
    local_path: Optional[str] = ""
    algorithm_id: Optional[str] = ""
    version_id: Optional[str] = ""
    deployment_target: str = "platform_package"  # platform_package / paddledet_weight / paddledet_infer / ultralytics_onnx / sophon_prepare
    export_config: Optional[Dict[str, Any]] = None
    include_report: bool = True
    include_dataset_labels: bool = True
    try_convert: bool = False


class DeployResourceReq(BaseModel):
    name: str
    kind: str  # ultralytics / paddle / tensorrt / sophon / ascend / rockchip
    mode: Literal["local", "remote", "agent"] = "local"
    base_url: str = ""
    api_key: str = ""
    python_path: str = ""
    ultralytics_python: str = ""
    paddledet_dir: str = ""
    paddle2onnx_path: str = ""
    tool_root: str = ""
    trtexec_path: str = ""
    atc_path: str = ""
    env_script: str = ""
    remark: str = ""


class DeployJobReq(BaseModel):
    source_id: str
    target: str  # onnx / paddle_inference / tensorrt / sophon / ascend / rockchip
    resource_id: str
    params: Dict[str, Any] = {}
    dataset_id: str = "default"
    calibration_split: str = "train"
    calibration_count: int = 100
    request_id: str = ""  # Optional client idempotency identity; legacy callers unchanged.
