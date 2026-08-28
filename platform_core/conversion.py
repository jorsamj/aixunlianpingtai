import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


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


def validate_target(kind: str, params: Mapping[str, Any]) -> dict[str, Any]:
    target = str(kind or "").strip().lower()
    values = dict(params or {})
    precision = str(values.get("precision") or "fp16").strip().lower()
    if target in {"rockchip", "rknn"}:
        chip = str(values.get("chip") or "").strip().lower()
        if chip not in {"rk3588", "rk3568"}:
            raise ValueError("瑞芯微转换必须明确选择 rk3588 或 rk3568")
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
