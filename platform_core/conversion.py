import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SUPPORTED_SOPHON_CHIPS = frozenset({"bm1684x", "bm1688"})


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
        for field,expected in (("pad_value",114),("channel_format","nchw"),("nms","external"),("fuse_preprocess",False)):
            if field in preprocessing and (type(preprocessing[field]) is not type(expected) or preprocessing[field]!=expected):
                raise ValueError(f"Sophon {field}与当前Adapter支持的预处理/后处理合同不一致")
        if preprocessing.get("owner", "caller") != "caller":
            raise ValueError("Sophon首期预处理由caller执行，不重复融合到ONNX或BMODEL")
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
        preprocessing.update(owner="caller", pixel_format=pixel, letterbox=letterbox,
                             pad_value=114, channel_format="nchw", nms="external", fuse_preprocess=False)
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
