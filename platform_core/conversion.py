import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SUPPORTED_ROCKCHIP_CHIPS = frozenset({"rk3568", "rk3576"})


class ConversionError(RuntimeError):
    def __init__(self, code: str, message: str, *, solution: str):
        super().__init__(message)
        self.code = code
        self.solution = solution


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path, *, relative_to: Path | None = None) -> dict[str, Any]:
    resolved = Path(path).resolve()
    if not resolved.is_file() or resolved.stat().st_size <= 0:
        raise ValueError(f"转换产物不存在或为空：{resolved.name}")
    name = str(resolved.relative_to(relative_to.resolve())) if relative_to else resolved.name
    return {
        "name": name.replace("\\", "/"),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }



def derive_version_conversion_defaults(
    version: Mapping[str, Any],
    training_job: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve verified training defaults; PT checkpoint dtype alone is not evidence."""
    lineage = version.get("training_lineage") or {}
    parameters = (lineage.get("parameters") or {}) if isinstance(lineage, Mapping) else {}
    actual = (parameters.get("actual") or {}) if isinstance(parameters, Mapping) else {}
    requested = (parameters.get("requested") or {}) if isinstance(parameters, Mapping) else {}
    job = training_job if isinstance(training_job, Mapping) else {}
    job_actual = job.get("actual_train_params") or {}
    actual = actual if isinstance(actual, Mapping) else {}
    requested = requested if isinstance(requested, Mapping) else {}
    job_actual = job_actual if isinstance(job_actual, Mapping) else {}

    size, size_source = 640, "历史版本未记录图片尺寸，使用兼容默认值"
    for label, raw in (
        ("训练版本实际参数", actual.get("imgsz")),
        ("训练任务实际参数", job_actual.get("imgsz")),
        ("训练任务配置", job.get("imgsz")),
        ("训练版本请求参数", requested.get("imgsz")),
    ):
        try:
            candidate = int(raw)
            if 32 <= candidate <= 4096:
                size, size_source = candidate, label
                break
        except (TypeError, ValueError, OverflowError):
            pass

    # Requested precision and AMP preference are not observed runtime facts.
    # Historical versions without actual evidence must remain explicitly unknown.
    precision, precision_source = None, "历史版本未记录实际训练精度"
    for label, raw in (
        ("训练任务实际运行精度", job.get("runtime_precision")),
        ("训练版本实际参数", actual.get("effective_precision") or actual.get("precision")),
        ("训练任务实际参数", job_actual.get("effective_precision") or job_actual.get("precision")),
    ):
        value = str(raw or "").strip().lower()
        if value in {"fp32", "fp16"}:
            precision, precision_source = value, label
            break

    return {
        "input_size": size,
        "training_precision": precision,
        "input_size_source": size_source,
        "precision_source": precision_source,
        "source_job_id": str(version.get("job_id") or version.get("task_id") or ""),
    }


def validate_target(kind: str, params: Mapping[str, Any]) -> dict[str, Any]:
    target = str(kind or "").strip().lower()
    values = dict(params or {})
    precision = str(values.get("precision") or "fp16").strip().lower()
    if target in {"rockchip", "rknn"}:
        chip = str(values.get("chip") or "").strip().lower()
        if chip not in SUPPORTED_ROCKCHIP_CHIPS:
            raise ValueError("当前产品瑞芯微转换只支持 rk3568 或 rk3576")
        values.update({"kind": "rockchip", "chip": chip, "precision": precision})
    elif target in {"ascend", "atlas"}:
        soc = str(values.get("soc_version") or "").strip()
        if not soc:
            raise ValueError("Atlas 转换必须填写与部署硬件一致的 soc_version")
        values.update({"kind": "ascend", "soc_version": soc, "precision": precision})
    elif target == "tensorrt":
        if precision not in {"fp32", "fp16", "int8"}:
            raise ValueError("TensorRT precision 必须为 fp32、fp16 或 int8")
        environment = str(values.get("target_environment") or "").strip()
        if not environment:
            raise ValueError("TensorRT 转换必须记录 target_environment（GPU、CUDA、TensorRT 环境）")
        values.update({"kind": "tensorrt", "precision": precision, "target_environment": environment})
    elif target == "onnx":
        values.update({"kind": "onnx"})
    else:
        values.update({"kind": target})
    if precision == "int8" and not str(values.get("calibration_snapshot") or "").strip():
        raise ValueError("INT8 转换必须关联不可变 calibration_snapshot")
    return values


def build_manifest(
    *,
    source: Mapping[str, Any],
    target: Mapping[str, Any],
    tool: Mapping[str, Any],
    outputs: Sequence[Mapping[str, Any]],
    hardware_verified: bool,
    onnx: Mapping[str, Any] | None = None,
    parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    output_records = [dict(item) for item in outputs]
    if not output_records:
        raise ValueError("转换 manifest 必须包含至少一个真实产物")
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "hardware_verified" if hardware_verified else "converted_unverified",
        "hardware_verified": bool(hardware_verified),
        "source": dict(source),
        "onnx": dict(onnx or {}),
        "target": dict(target),
        "parameters": dict(parameters or {}),
        "tool": dict(tool),
        "outputs": output_records,
    }
