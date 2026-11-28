import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SUPPORTED_SOPHON_CHIPS = frozenset({"bm1684x", "bm1688"})


# The immutable source-manifest contract. Only these fields participate in the
# canonical digest; delivery/validation state written later (board verification,
# status, timestamps, numeric evidence) must never invalidate model identity.
SOURCE_MANIFEST_SCHEMA_VERSION = 1
SOURCE_MANIFEST_MUTABLE_FIELDS = frozenset({
    "status", "hardware_verified", "hardware_verification", "validation_status",
    "runtime_verified", "created_at", "updated_at", "completed_at", "job_id",
    "manifest_digest", "manifest_integrity", "legacy_manifest", "numeric_status",
    "numeric_validation", "publication_status", "execution_evidence",
    "sophon_validation",
})


def canonical_json_bytes(value: Any) -> bytes:
    """Stable canonical JSON for manifest identity (sorted, compact, UTF-8).

    NaN/Infinity are rejected: a manifest that cannot be re-encoded faithfully
    must never be reported as a trustworthy digest.
    """
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError(f"manifest 含无法规范编码的字段：{error}") from error


def _sha256_text(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise ValueError(f"{field} 必须是 64 位 SHA256 摘要")
    return text


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} 必须是正整数")
    return value


def _bounded_json(value: Any, *, limit: int = 65536) -> Any:
    """Keep a JSON value only while it stays bounded; otherwise freeze its digest."""
    if value is None:
        return None
    try:
        encoded = canonical_json_bytes(value)
    except ValueError:
        return {"status": "unserializable"}
    if len(encoded) <= limit:
        return json.loads(encoded.decode("utf-8"))
    keys = sorted(str(key) for key in value)[:32] if isinstance(value, Mapping) else []
    return {
        "status": "truncated",
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "size_bytes": len(encoded),
        "keys": keys,
    }


def _bounded_list(value: Any, limit: int, *, item) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    for entry in list(value)[:limit]:
        normalized = item(entry)
        if normalized is None:
            continue
        result.append(normalized)
    return result


def _shape_records(value: Any) -> list[list[Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    records = []
    for row in list(value)[:8]:
        if not isinstance(row, (list, tuple)):
            continue
        records.append([int(dim) if type(dim) is int else str(dim) for dim in list(row)[:8]])
    return records


def _floating_types(value: Any) -> list[str]:
    return _bounded_list(value, 16, item=lambda entry: str(entry) if isinstance(entry, str) else None)


def _opset_imports(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    result = {}
    for domain, version in list(value.items())[:16]:
        if type(version) is int:
            result[str(domain)] = version
    return result


def _outputs_block(outputs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records = list(outputs or [])
    if not records:
        raise ValueError("source manifest 必须包含至少一个真实产物")
    if len(records) > 512:
        raise ValueError("产物数量超过 source manifest 的安全上限（512）")
    result = []
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("source manifest 产物记录必须是 JSON object")
        name = str(record.get("name") or "").replace("\\", "/").strip()
        if not name:
            raise ValueError("source manifest 产物缺少文件名称")
        result.append({
            "name": name,
            "sha256": _sha256_text(record.get("sha256"), f"outputs[{name}].sha256"),
            "size_bytes": _positive_int(record.get("size_bytes"), f"outputs[{name}].size_bytes"),
        })
    return result


def build_source_manifest(
    *,
    source: Mapping[str, Any],
    export: Mapping[str, Any],
    tool: Mapping[str, Any],
    outputs: Sequence[Mapping[str, Any]],
    onnx: Mapping[str, Any] | None = None,
    schema_version: int = SOURCE_MANIFEST_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Freeze the immutable model-source identity for one conversion task.

    This is the single Owner of the source-manifest schema. Mutable delivery
    state is deliberately not part of this document, so `manifest_digest`
    stays stable after board verification or validation-state writebacks.
    """
    if not isinstance(source, Mapping):
        raise ValueError("source manifest 缺少 source 合同")
    if not isinstance(export, Mapping):
        raise ValueError("source manifest 缺少 export 合同")
    if not isinstance(tool, Mapping):
        raise ValueError("source manifest 缺少 tool 合同")
    tool_name = str(tool.get("name") or "").strip()
    if not tool_name:
        raise ValueError("source manifest tool.name 缺失")
    source_block = {
        "sha256": _sha256_text(source.get("sha256"), "source.sha256"),
        "size_bytes": _positive_int(source.get("size_bytes"), "source.size_bytes"),
        "file_name": str(source.get("file_name") or Path(str(source.get("file_path") or "")).name).strip(),
        "algorithm_id": str(source.get("algorithm_id") or ""),
        "version_id": str(source.get("version_id") or ""),
        "artifact_id": str(source.get("artifact_id") or ""),
    }
    if not source_block["file_name"]:
        raise ValueError("source manifest source.file_name 缺失")
    label_codes = _bounded_list(source.get("label_codes"), 1000,
                                item=lambda entry: entry.strip() if isinstance(entry, str) else None)
    label_schema = _bounded_list(
        source.get("label_schema"), 512,
        item=lambda entry: _bounded_json(entry, limit=2048) if isinstance(entry, Mapping)
        else ({"code": str(entry)} if isinstance(entry, str) else None),
    )
    if label_codes:
        source_block["label_codes"] = label_codes
    if label_schema:
        source_block["label_schema"] = label_schema
    if source.get("label_binding") is not None:
        source_block["label_binding"] = _bounded_json(source.get("label_binding"), limit=4096)
    if source.get("preprocessing_contract") is not None:
        source_block["preprocessing_contract"] = _bounded_json(
            source.get("preprocessing_contract"), limit=4096
        )
    if source.get("output_contract") is not None:
        source_block["output_contract"] = _bounded_json(
            source.get("output_contract"), limit=4096
        )
    if source.get("training_lineage") is not None:
        source_block["training_lineage"] = _bounded_json(source.get("training_lineage"))
    recheck = source.get("sha256_recheck")
    if isinstance(recheck, Mapping):
        source_block["sha256_recheck"] = {
            "status": str(recheck.get("status") or ""),
            "recorded_sha256": str(recheck.get("recorded_sha256") or ""),
            "reason": str(recheck.get("reason") or "")[:512],
        }
    export_block = {}
    for key in ("opset", "dynamic", "simplify", "batch", "imgsz", "precision", "half"):
        if key not in export:
            raise ValueError(f"source manifest export 缺少字段：{key}")
        value = export.get(key)
        if key == "imgsz" and value is not None:
            if (not isinstance(value, (list, tuple)) or len(value) != 2
                    or any(type(dim) is not int or dim <= 0 for dim in value)):
                raise ValueError("source manifest export.imgsz 必须是两个正整数")
            value = [int(dim) for dim in value]
        elif key == "batch" and value is not None and type(value) is not int:
            raise ValueError("source manifest export.batch 必须是整数")
        export_block[key] = value
    export_block["reused_existing_onnx"] = bool(export.get("reused_existing_onnx", False))
    tool_block = {
        "name": tool_name,
        "version": str(tool.get("version") or ""),
        "python_path": str(tool.get("python_path") or ""),
        "dependencies": _bounded_json(tool.get("dependencies") or {}, limit=8192),
    }
    onnx_block: dict[str, Any]
    if onnx is None:
        onnx_block = {"status": "not_available", "reason": "该转换目标不经过 ONNX 中间模型"}
    elif not isinstance(onnx, Mapping):
        raise ValueError("source manifest onnx 合同必须是 JSON object")
    else:
        onnx_block = {
            "status": "verified",
            "name": str(onnx.get("name") or "").replace("\\", "/"),
            "sha256": _sha256_text(onnx.get("sha256"), "onnx.sha256"),
            "size_bytes": _positive_int(onnx.get("size_bytes"), "onnx.size_bytes"),
            "opset_imports": _opset_imports(onnx.get("opset_imports")),
            "input_shapes": _shape_records(onnx.get("input_shapes")),
            "input_types": _bounded_list(onnx.get("input_types"), 8, item=lambda entry: str(entry)),
            "input_names": _bounded_list(onnx.get("input_names"), 8, item=lambda entry: str(entry)),
            "output_shapes": _shape_records(onnx.get("output_shapes")),
            "output_types": _bounded_list(onnx.get("output_types"), 8, item=lambda entry: str(entry)),
            "output_names": _bounded_list(onnx.get("output_names"), 16, item=lambda entry: str(entry)),
            "output_inferred_shapes": _shape_records(onnx.get("output_inferred_shapes")),
            "output_dtypes": _bounded_list(onnx.get("output_dtypes"), 16, item=lambda entry: str(entry)),
            "floating_tensor_types": _floating_types(onnx.get("floating_tensor_types")),
        }
    document = {
        "schema_version": int(schema_version),
        "source": source_block,
        "export": export_block,
        "tool": tool_block,
        "onnx": onnx_block,
        "outputs": _outputs_block(outputs),
    }
    # The document must survive canonical encoding before it may be digested.
    canonical_json_bytes(document)
    return document


def source_manifest_digest(manifest: Mapping[str, Any]) -> str:
    """Digest only the immutable projection; mutable delivery state is excluded."""
    if not isinstance(manifest, Mapping):
        raise ValueError("source manifest 必须是 JSON object")
    projection = {
        key: value for key, value in manifest.items()
        if key not in SOURCE_MANIFEST_MUTABLE_FIELDS
    }
    return hashlib.sha256(canonical_json_bytes(projection)).hexdigest()


def verify_source_manifest_digest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute the frozen digest; missing digests are legacy, never verified."""
    recorded = str((manifest or {}).get("manifest_digest") or "").strip().lower()
    if not recorded:
        return {
            "present": False, "valid": False, "recorded": "", "recomputed": "",
            "reason": "manifest 缺少不可变 manifest_digest，只能按旧历史合同显式标记为未验证",
        }
    try:
        recomputed = source_manifest_digest(manifest)
    except ValueError as error:
        return {"present": True, "valid": False, "recorded": recorded,
                "recomputed": "", "reason": f"manifest 不可变字段无法重算：{error}"}
    valid = recomputed == recorded
    return {
        "present": True, "valid": valid, "recorded": recorded, "recomputed": recomputed,
        "reason": "" if valid else "manifest_digest 与不可变字段重算结果不一致，拒绝采信该 manifest",
    }


def source_manifest_summary(manifest: Mapping[str, Any], *, max_outputs: int = 64) -> dict[str, Any]:
    """Bounded copy for artifact metadata; never a second source of truth."""
    if not isinstance(manifest, Mapping):
        return {}
    source = manifest.get("source") if isinstance(manifest.get("source"), Mapping) else {}
    export = manifest.get("export") if isinstance(manifest.get("export"), Mapping) else {}
    tool = manifest.get("tool") if isinstance(manifest.get("tool"), Mapping) else {}
    onnx = manifest.get("onnx") if isinstance(manifest.get("onnx"), Mapping) else {}
    outputs = []
    for record in list(manifest.get("outputs") or [])[:max_outputs]:
        if isinstance(record, Mapping):
            outputs.append({key: record[key] for key in ("name", "sha256", "size_bytes") if key in record})
    summary = {
        "schema_version": manifest.get("schema_version"),
        "manifest_digest": str(manifest.get("manifest_digest") or ""),
        "source": {key: source[key] for key in ("sha256", "size_bytes", "file_name", "algorithm_id", "version_id") if key in source},
        "export": {key: export[key] for key in ("opset", "dynamic", "simplify", "batch", "imgsz", "precision", "half", "reused_existing_onnx") if key in export},
        "tool": {key: tool[key] for key in ("name", "version") if key in tool},
        "onnx": {key: onnx[key] for key in ("status", "name", "sha256", "size_bytes", "opset_imports", "input_shapes",
                                            "input_types", "output_shapes", "output_types", "floating_tensor_types") if key in onnx},
        "outputs": outputs,
        "outputs_truncated": len(list(manifest.get("outputs") or [])) > max_outputs,
    }
    return {key: value for key, value in summary.items() if value not in (None, {}, [])}


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



def conversion_input_shape(params: Mapping[str, Any]) -> tuple[int, int]:
    """Return exact NCHW spatial dimensions; a partial explicit pair is invalid."""
    h, w = params.get("input_height"), params.get("input_width")
    if h is None and w is None:
        value = params.get("input_size", 640)
        h, w = value if isinstance(value, (list, tuple)) and len(value) == 2 else (value, value)
    if any(type(v) not in (int, str) or not str(v).isdigit() for v in (h, w)):
        raise ValueError("输入宽高必须为完整的整数尺寸")
    h, w = int(h), int(w)
    if not all(32 <= v <= 8192 and v % 32 == 0 for v in (h, w)):
        raise ValueError("输入宽高必须为32的倍数，范围32到8192")
    return h, w


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
            if isinstance(raw, (list, tuple)) and len(raw) == 2:
                height, width = conversion_input_shape({"input_size": raw})
                size, size_source = [height, width], label
                break
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
        "input_height": size[0] if isinstance(size, list) else size,
        "input_width": size[1] if isinstance(size, list) else size,
        "training_precision": precision,
        "input_size_source": size_source,
        "precision_source": precision_source,
        "source_job_id": str(version.get("job_id") or version.get("task_id") or ""),
    }


def validate_target(kind: str, params: Mapping[str, Any], *, require_calibration: bool = True) -> dict[str, Any]:
    target = str(kind or "").strip().lower()
    values = dict(params or {})
    precision = str(values.get("precision") or "fp16").strip().lower()
    # Explicit opt-in: never reinterpret historical conversion jobs as RGB.
    from .color_adapter import color_contract
    color = color_contract(values)
    if color:
        if target == "paddle_inference" and color["source_color_order"] != color["input_color_order"]:
            raise ValueError("Paddle Inference直出不经过ONNX，暂不支持变更输入颜色")
        values.update(color)
    if target in {"rockchip", "rknn"}:
        chip = str(values.get("chip") or "").strip().lower()
        import re
        if chip not in SUPPORTED_ROCKCHIP_CHIPS and not (values.get("constraint_id")=="rknn-verified" and re.fullmatch(r"rk\d{4}",chip)):
            raise ValueError("当前产品瑞芯微转换只支持 rk3568 或 rk3576")
        values.update({"kind": "rockchip", "chip": chip, "precision": precision})
        import math
        for key,default in (("mean","0,0,0"),("rknn_std","255,255,255")):
            raw=values.get(key,default)
            try:
                parts=raw.split(",") if isinstance(raw,str) else list(raw)
                if len(parts)!=3 or any(isinstance(v,bool) or not math.isfinite(float(v)) for v in parts):
                    raise ValueError()
                if key=="rknn_std" and any(float(v)<=0 for v in parts):
                    raise ValueError()
            except (TypeError,ValueError,OverflowError):
                raise ValueError(f"RKNN {key}必须包含3个有效数值；Std须大于0")
            values[key]=",".join(str(v) for v in parts)
    elif target == "sophon":
        chip = str(values.get("chip") or "").strip().lower()
        import re
        from .sophon_runtime import SOPHON_1302_FLOAT_RULES
        if not re.fullmatch(r"[a-z][a-z0-9]{2,31}", chip):
            raise ValueError("Sophon必须明确选择有效SDK芯片编码，不使用默认芯片")
        if chip not in SUPPORTED_SOPHON_CHIPS and values.get("constraint_id") != "tpu-mlir-1.30.2":
            raise ValueError("Sophon新芯片缺少已验证的约束引用")
        allowed = SOPHON_1302_FLOAT_RULES.get(chip, [])
        if precision not in allowed or (chip in SUPPORTED_SOPHON_CHIPS and precision != "fp16" and values.get("constraint_id") != "tpu-mlir-1.30.2"):
            raise ValueError("Sophon芯片精度缺少兼容证据；INT8须完成冻结校准与质量验收后启用")
        for field in ("batch", "num_core"):
            if type(values.get(field, 1)) not in (int, str) or str(values.get(field, 1)) != "1":
                raise ValueError(f"Sophon首期{field}必须为1")
        if values.get("dynamic") not in (None, False):
            raise ValueError("Sophon首期仅支持静态输入")
        if values.get("opset", 12) != 12 or values.get("simplify", False) is not False:
            raise ValueError("Sophon export requires opset=12 and simplify=false")
        height, width = conversion_input_shape(values)
        preprocessing = dict(values.get("preprocessing") or {})
        for field,expected in (("pad_value",114),("channel_format","nchw"),("nms","external"),("fuse_preprocess",False),
                               ("resize_interpolation","opencv_linear")):
            if field in preprocessing and (type(preprocessing[field]) is not type(expected) or preprocessing[field]!=expected):
                raise ValueError(f"Sophon {field}与当前Adapter支持的预处理/后处理合同不一致")
        if preprocessing.get("owner", "caller") != "caller":
            raise ValueError("Sophon首期预处理由caller执行，不重复融合到ONNX或BMODEL")
        # A changed input color is an ONNX graph adaptation, not a mere label.
        # Keep runtime-facing pixel_format synchronized with the selected contract.
        if color:
            preprocessing["pixel_format"] = color["input_color_order"]
        pixel = str(preprocessing.get("pixel_format", values.get("pixel_format", "rgb"))).lower()
        if pixel not in {"rgb", "bgr"}:
            raise ValueError("Sophon pixel_format必须为rgb或bgr")
        import math
        for key, default in (("mean", [0.0]*3), ("scale", [1.0/255]*3)):
            raw = preprocessing.get(key, values.get(key, default))
            raw = raw.split(",") if isinstance(raw, str) else raw
            try:
                if len(raw) != 3 or any(isinstance(v, bool) or not math.isfinite(float(v)) for v in raw):
                    raise ValueError()
                preprocessing[key] = [float(v) for v in raw]
            except (TypeError, ValueError, OverflowError):
                raise ValueError(f"Sophon {key}必须包含3个有限数值")
        letterbox = preprocessing.get("letterbox", values.get("keep_aspect_ratio", True))
        if type(letterbox) is not bool:
            raise ValueError("Sophon letterbox必须为布尔值")
        letterbox_mode = "fixed_shape_center" if letterbox else "stretch"
        if preprocessing.get("letterbox_mode", letterbox_mode) != letterbox_mode:
            raise ValueError("Sophon LetterBox 模式与缩放策略不一致")
        preprocessing.update(owner="caller", pixel_format=pixel, letterbox=letterbox,
                             pad_value=114, channel_format="nchw", nms="external", fuse_preprocess=False,
                             resize_interpolation="opencv_linear", letterbox_mode=letterbox_mode)
        values.update(kind="sophon", chip=chip, precision=precision, batch=1, num_core=1,
                      dynamic=False, input_height=height, input_width=width, preprocessing=preprocessing,
                      opset=12, simplify=False)
    elif target in {"ascend", "atlas"}:
        soc = str(values.get("soc_version") or "").strip()
        if not soc:
            raise ValueError("Atlas 转换必须填写与部署硬件一致的 soc_version")
        modes = {"fp32": "force_fp32", "fp16": "allow_fp32_to_fp16"}
        if precision not in modes:
            raise ValueError("Ascend precision must be fp16 or fp32")
        mode = modes[precision]
        selected_mode = values.get("precision_mode", mode)
        allowed_modes = {mode} if precision == "fp32" else {mode, "must_keep_origin_dtype", "allow_mix_precision"}
        if selected_mode not in allowed_modes:
            raise ValueError("precision_mode conflicts with requested precision")
        values.update(kind="ascend", soc_version=soc, precision=precision, precision_mode=selected_mode)
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
    if target in {"rockchip","rknn","ascend","atlas"}:
        height,width=conversion_input_shape(values)
        values.update(input_height=height,input_width=width)
    if require_calibration and precision == "int8" and not str(values.get("calibration_snapshot") or "").strip():
        raise ValueError("INT8 转换必须关联不可变 calibration_snapshot")
    if "csc" in values:
        from .conversion_csc import resolve_csc_params
        resolved_csc = resolve_csc_params(values, str(values.get('kind') or target),
            input_color_order=values.get('input_color_order') or (values.get('preprocessing') or {}).get('pixel_format') or 'rgb')
        values['csc'] = resolved_csc['requested']
        values['csc_contract'] = resolved_csc
    else:
        values.pop('csc_contract', None)  # An untrusted derived field cannot stand alone.
    # Freeze the manifest-identity schema on every new conversion request. A
    # pre-upgrade in-flight job lacks this marker and must take the explicit
    # legacy compatibility path instead of being treated as digest-verified.
    values.setdefault("source_manifest_schema", SOURCE_MANIFEST_SCHEMA_VERSION)
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
