"""Frozen version model facts shared by canonical assets and external delivery.

This module reads immutable version/Snapshot evidence only; it owns no storage or queue.
"""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Dict

def yolo_architecture(version: Mapping[str, Any], algorithm: Mapping[str, Any] | None = None) -> str:
    """Resolve exact YOLO generation AND scale from immutable training lineage.

    Fine-tuned versions commonly use best.pt as their base, so walk their
    explicit base_version_id chain, never guess a scale from v11 alone.
    """
    versions = {
        str(row.get("id") or ""): row
        for row in (algorithm or {}).get("versions", [])
        if isinstance(row, Mapping) and str(row.get("id") or "")
    }
    seen: set[str] = set()
    current: Mapping[str, Any] = version
    for _ in range(len(versions) + 1):
        current_id = str(current.get("id") or "")
        if current_id:
            if current_id in seen:
                break
            seen.add(current_id)
        lineage = current.get("training_lineage") or {}
        lineage = lineage if isinstance(lineage, Mapping) else {}
        base = lineage.get("base") or {}
        base = base if isinstance(base, Mapping) else {}
        for candidate in (current.get("yolo_version"), base.get("model")):
            name = Path(str(candidate or "").replace("\\", "/")).name
            name = re.sub(r"\.pt$", "", name, flags=re.IGNORECASE)
            match = re.fullmatch(r"yolo(?:v)?(\d+)([nsmlx])", name, re.IGNORECASE)
            if match:
                return f"YOLOv{match.group(1)}{match.group(2).lower()}"
        parent_id = str(
            current.get("base_version_id")
            or base.get("version_id")
            or ""
        ).strip()
        if not parent_id or parent_id in seen or parent_id not in versions:
            break
        current = versions[parent_id]
    return ""


def frozen_weight_labels(version: Mapping[str, Any]) -> list[str] | None:
    """The model classes are frozen at training, not today's project catalog."""
    codes = version.get("label_codes")
    schema = version.get("label_schema")
    frozen_codes: list[str] | None = None
    if isinstance(schema, list) and schema:
        if not all(isinstance(row, Mapping) and str(row.get("code") or "").strip() for row in schema):
            return None
        try:
            ids = [
                int(row["class_id"]) if type(row.get("class_id")) in (int, str) else -1
                for row in schema
            ]
            if sorted(ids) != list(range(len(schema))):
                return None
            ordered = sorted(schema, key=lambda row: int(row["class_id"]))
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        frozen_codes = [str(row["code"]).strip() for row in ordered]
        if len(set(frozen_codes)) != len(frozen_codes):
            return None
    if isinstance(codes, list) and codes:
        if not all(isinstance(code, str) and code.strip() for code in codes):
            return None
        declared = [code.strip() for code in codes]
        if len(set(declared)) != len(declared):
            return None
        if frozen_codes is not None and declared != frozen_codes:
            return None
        return frozen_codes if frozen_codes is not None else declared
    return frozen_codes


def snapshot_weight_labels(data_dir: Path, version: Mapping[str, Any]) -> list[str] | None:
    """Only recover labels from a hash-verified task Snapshot of this version."""
    if version.get("label_schema") or version.get("label_codes"):
        return None
    lineage = version.get("training_lineage") or {}
    if not isinstance(lineage, Mapping):
        return None
    task_id = str(lineage.get("task_id") or "").strip()
    snapshot_id = str(lineage.get("snapshot_id") or "").strip()
    version_snapshot_id = str(version.get("snapshot_id") or "").strip()
    if (
        not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", task_id)
        or task_id in {".", ".."}
        or not re.fullmatch(r"[0-9a-f]{64}", snapshot_id)
        or (version_snapshot_id and version_snapshot_id != snapshot_id)
    ):
        return None
    root = (Path(data_dir) / "task_runtime" / "artifacts").resolve()
    try:
        path = (root / task_id / "snapshot.json").resolve(strict=True)
        if root not in path.parents:
            return None
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(snapshot, dict) or snapshot.get("snapshot_id") != snapshot_id:
            return None
        revision = str(version.get("dataset_revision_id") or "").strip()
        if revision and snapshot.get("dataset_revision_id") != revision:
            return None
        signed = {key: value for key, value in snapshot.items() if key not in ("snapshot_id", "created_at")}
        digest = hashlib.sha256(
            json.dumps(signed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if digest != snapshot_id:
            return None
        return frozen_weight_labels({"label_schema": snapshot.get("label_schema")})
    except (OSError, TypeError, ValueError, RuntimeError):
        return None


def weight_model_metadata(
    version: Mapping[str, Any],
    conversion_params: Mapping[str, Any] | None = None,
    *,
    algorithm: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Resolve weight facts from the frozen training and conversion contracts."""
    result: Dict[str, Any] = {}
    lineage = version.get("training_lineage") or {}
    lineage = lineage if isinstance(lineage, Mapping) else {}
    parameters = lineage.get("parameters") or {}
    parameters = parameters if isinstance(parameters, Mapping) else {}
    actual = parameters.get("actual") or {}
    actual = actual if isinstance(actual, Mapping) else {}
    if conversion_params is None:
        raw_shape = actual.get("imgsz")
        if isinstance(raw_shape, (list, tuple)) and len(raw_shape) == 2:
            height, width = raw_shape
        else:
            width = height = raw_shape
    else:
        params = conversion_params
        width = params.get("input_width")
        height = params.get("input_height")
        if width is None and height is None:
            size = params.get("input_size")
            if isinstance(size, (list, tuple)) and len(size) == 2:
                height, width = size
            else:
                width = height = size
    try:
        if any(type(value) not in (int, str) or not str(value).isdigit() for value in (width, height)):
            raise ValueError('input shape is not an exact integer pair')
        width, height = int(width), int(height)
        if 32 <= width <= 8192 and 32 <= height <= 8192:
            result.update(image_width=width, image_height=height)
    except (TypeError, ValueError, OverflowError):
        pass

    architecture = yolo_architecture(version, algorithm)
    if architecture:
        result["yolo_version"] = architecture
    labels = frozen_weight_labels(version)
    if labels:
        result["tags"] = labels
    return result


def model_metadata(data_dir, version, conversion_params=None, *, algorithm=None):
    result = weight_model_metadata(version, conversion_params, algorithm=algorithm)
    labels = frozen_weight_labels(version)
    source = "version_frozen"
    if not labels:
        labels = snapshot_weight_labels(Path(data_dir), version)
        source = "verified_snapshot"
    conflict = bool(version.get("label_codes") or version.get("label_schema")) and not labels
    result.update(label_source=source if labels else "unknown",
                  label_validation_status="VERIFIED" if labels else "CONFLICT" if conflict else "UNKNOWN",
                  label_error="冻结label_codes与class_id/schema不一致或无效" if conflict else "" if labels else "缺少可信冻结类别或可验证Snapshot",
                  label_version_id=str(version.get("id") or ""))
    if labels:
        result["tags"] = list(labels)
        result["class_mapping"] = [{"class_id":i,"code":code} for i,code in enumerate(labels)]
    params = conversion_params if isinstance(conversion_params, Mapping) else None
    if params is not None:
        result["conversion_params"] = {key:params[key] for key in ("chip","soc_version","precision","input_width","input_height","input_size","batch","num_core","dynamic","opset","simplify","preprocessing","workspace_mb","target_environment","calibration_snapshot_id") if key in params}
        if params.get("precision"):
            result["precision"] = params["precision"]
    for key in ("snapshot_id", "task_id", "framework", "framework_version", "finished_at"):
        if version.get(key): result[key] = version[key]
    lineage = version.get("training_lineage")
    parameters = lineage.get("parameters") if isinstance(lineage, Mapping) else None
    actual = parameters.get("actual") if isinstance(parameters, Mapping) else None
    training_precision = actual.get("precision") if isinstance(actual, Mapping) else None
    result["training_precision"] = training_precision if isinstance(training_precision,str) and training_precision in {"fp32","fp16","bf16"} else None
    result["class_count"] = len(labels) if labels else None
    for key in ("image_width","image_height","yolo_version","framework_version","precision"):
        result.setdefault(key, None)
    return result
