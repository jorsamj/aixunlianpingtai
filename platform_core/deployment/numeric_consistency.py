"""Offline PT/ONNX numerical comparison on identical real image tensors.

This is not a BMODEL hardware inference test or an accuracy evaluation.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path


PROTOCOL = "pt-onnx-raw-and-detection-v4"
RUNTIME_MODULES = ("torch", "ultralytics", "onnx", "onnxruntime", "numpy", "cv2")
DYNAMIC_INPUT_WITHOUT_FROZEN_CODE = "DYNAMIC_INPUT_WITHOUT_FROZEN_IMGSZ"
NON_RGB_INPUT_CODE = "NON_RGB_INPUT_NOT_COMPARABLE"
NUMERIC_STATUS_BY_VERDICT = {
    "consistent": "consistent",
    "difference_detected": "difference_detected",
    "not_comparable": "not_comparable",
    "contract_mismatch": "not_comparable",
    "unavailable": "unavailable",
}
PUBLICATION_STATUS_BY_NUMERIC = {
    "consistent": "numeric_consistent_delivery_evidence_incomplete",
    "difference_detected": "blocked_numeric_difference",
    "not_comparable": "blocked_numeric_not_comparable",
    "unavailable": "blocked_numeric_unavailable",
}
SCOPE_NOTE = ("同图规范化 RGB Letterbox 输入下对照原始张量，并在可识别的 YOLO 检测输出上比较阈值/NMS 后检测框，"
              "同时把输入坐标系检测框按预处理几何还原到原图像素。非规范化部署前处理未在本次执行；"
              "模拟器不代表板端实机或场景准确率。")


def runtime_versions() -> dict:
    """Actual imported runtime versions; failures are explicit nulls, never invented."""
    versions = {}
    for name in RUNTIME_MODULES:
        try:
            module = importlib.import_module(name)
        except Exception as error:  # noqa: BLE001 - evidence must record any failure
            versions[name] = {"version": None, "error": f"{type(error).__name__}: {error}"[:300]}
            continue
        version = getattr(module, "__version__", None)
        versions[name] = {
            "version": str(version) if version is not None else None,
            "error": None if version is not None else "模块未暴露 __version__，无法取得真实版本",
        }
    return versions


def compare_tensors(reference, converted, *, precision: str = "fp32") -> dict:
    import numpy as np

    a, b = np.asarray(reference), np.asarray(converted)
    if a.shape != b.shape or not a.size or not b.size:
        return {"comparable": False, "reason": "输出形状不一致或输出为空", "pt_shape": list(a.shape), "onnx_shape": list(b.shape)}
    if not np.issubdtype(a.dtype, np.number) or not np.issubdtype(b.dtype, np.number):
        return {"comparable": False, "reason": "输出包含非数值张量"}
    if not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        return {"comparable": False, "reason": "输出包含 NaN 或 Infinity"}
    x, y = a.astype(np.float64).ravel(), b.astype(np.float64).ravel()
    delta = np.abs(x - y)
    denominator = np.linalg.norm(x) * np.linalg.norm(y)
    cosine = float(np.dot(x, y) / denominator) if denominator > 0 else (1.0 if np.array_equal(x, y) else 0.0)
    normalized_mae = float(delta.mean() / max(float(np.mean(np.abs(x))), 1e-6))
    limit = {"fp32": 0.005, "fp16": 0.05, "bf16": 0.07}.get(str(precision).lower())
    if limit is None:
        return {"comparable": False, "reason": f"目标精度 {precision} 尚无可信数值容差协议，不得判定一致",
                "shape": list(a.shape), "element_count": int(a.size)}
    return {
        "comparable": True,
        "shape": list(a.shape), "element_count": int(a.size),
        "mean_abs_error": float(delta.mean()),
        "p95_abs_error": float(np.percentile(delta, 95)),
        "max_abs_error": float(delta.max()),
        "normalized_mae": normalized_mae,
        "cosine_similarity": cosine,
        "within_tolerance": normalized_mae <= limit and cosine >= 0.999,
        "normalized_mae_limit": limit,
    }


def _restore_box(box, *, adapt, geometry, original_size):
    """Reuse auto_label.adapt_coordinates; never a second geometry kernel."""
    if adapt is None or not geometry or not original_size:
        return None, "PREPROCESSING_GEOMETRY_UNAVAILABLE"
    try:
        width, height = int(original_size[0]), int(original_size[1])
        restored = adapt(list(map(float, box)), width=width, height=height,
                         coordinate_space="pixel", coordinate_order="xyxy",
                         coordinate_origin="top_left", geometry=dict(geometry))
    except (TypeError, ValueError) as error:
        code = str(error).split(":", 1)[0].strip() or "COORDINATE_CONVERSION_ERROR"
        return None, code
    return [round(float(value), 3) for value in restored], ""


def compare_yolo_detections(reference, converted, *, class_count: int, confidence: float = 0.25,
                            nms_iou: float = 0.7, match_iou: float = 0.95,
                            geometry: Mapping | None = None,
                            original_size: list | tuple | None = None) -> dict:
    """Compare detections after external class-aware NMS, not only diluted tensor means.

    Only the explicit YOLO11-style single-output XYWH + class-score contract is
    supported. Ambiguous/fused output formats remain unverified, never passed.
    When `geometry`/`original_size` are given, every retained box is restored
    from input pixels to original-image pixels via auto_label.adapt_coordinates.
    """
    import math
    import numpy as np

    a, b = np.asarray(reference), np.asarray(converted)
    unsupported = lambda reason: {"comparable": False, "reason": reason, "within_tolerance": False}
    if not isinstance(class_count, int) or isinstance(class_count, bool) or not 1 <= class_count <= 1000:
        return unsupported("缺少可信且有界的 YOLO 类别数量")
    if (not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                for value in (confidence, nms_iou, match_iou))
            or not 0 < confidence < 1 or not 0 < nms_iou < 1 or not 0 < match_iou <= 1):
        return unsupported("置信度、NMS 或匹配 IoU 不在有效范围内")
    if a.shape != b.shape or a.ndim != 3 or a.shape[0] != 1:
        return unsupported("不是相同形状的单输出 YOLO 检测张量")
    fields = 4 + class_count
    if (a.shape[1] == fields) == (a.shape[2] == fields):
        return unsupported("输出不是唯一可识别的 XYWH + 类别分数布局")
    if not np.issubdtype(a.dtype, np.number) or not np.issubdtype(b.dtype, np.number):
        return unsupported("输出不是数值张量")
    if not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        return unsupported("检测输出含非有限数值")
    lhs = a[0].T if a.shape[1] == fields else a[0]
    rhs = b[0].T if b.shape[1] == fields else b[0]

    adapt = None
    if isinstance(geometry, Mapping) and original_size:
        from platform_core.auto_label import adapt_coordinates
        adapt = adapt_coordinates

    def decode(rows):
        score = rows[:, 4:].max(axis=1)
        category = rows[:, 4:].argmax(axis=1)
        active = np.flatnonzero(score >= confidence)
        if active.size > 512:
            raise ValueError("超过单图 512 个候选框的安全比较上限")
        boxes = rows[active, :4].astype(np.float64)
        if np.any(boxes[:, 2:] <= 0):
            raise ValueError("检测框尺寸不是正数，无法按 XYWH 合同解码")
        # YOLO11 detection export emits center XYWH, not XYXY or embedded NMS.
        xyxy = np.column_stack((boxes[:, 0] - boxes[:, 2] / 2, boxes[:, 1] - boxes[:, 3] / 2,
                                boxes[:, 0] + boxes[:, 2] / 2, boxes[:, 1] + boxes[:, 3] / 2))
        order = np.argsort(-score[active], kind="stable")
        kept = []
        while order.size and len(kept) < 300:
            current = int(order[0]); kept.append(current)
            rest = order[1:]
            if not rest.size:
                order = rest
                break
            box = xyxy[current]
            others = xyxy[rest]
            top_left = np.maximum(box[:2], others[:, :2]); bottom_right = np.minimum(box[2:], others[:, 2:])
            intersection = np.prod(np.maximum(0.0, bottom_right - top_left), axis=1)
            area = np.prod(np.maximum(0.0, box[2:] - box[:2]))
            other_area = np.prod(np.maximum(0.0, others[:, 2:] - others[:, :2]), axis=1)
            iou = intersection / np.maximum(area + other_area - intersection, 1e-12)
            order = rest[(category[active][rest] != category[active][current]) | (iou <= nms_iou)]
        if order.size:
            raise ValueError("NMS 后超过 300 个框，禁止截断结果后冒称一致")
        return int(active.size), [(int(category[active][i]), float(score[active][i]), xyxy[i]) for i in kept]

    try:
        count_a, boxes_a = decode(lhs)
        count_b, boxes_b = decode(rhs)
    except ValueError as error:
        return unsupported(str(error))
    before_a = lhs[:, 4:].max(axis=1)
    before_b = rhs[:, 4:].max(axis=1)
    threshold_crossings = int(np.count_nonzero((before_a >= confidence) != (before_b >= confidence)))
    class_rows: dict[int, dict] = {}

    def class_row(category: int) -> dict:
        return class_rows.setdefault(category, {
            "class_id": category, "reference_boxes": 0, "converted_boxes": 0,
            "matched_pairs": 0, "unmatched_reference": 0, "unmatched_converted": 0,
            "_iou_sum": 0.0,
        })

    for category, _score, _box in boxes_b:
        class_row(category)["converted_boxes"] += 1
    used = set()
    unmatched_a = 0
    confidence_drifts = 0
    matched_pairs = 0
    matched_iou_sum = 0.0
    for category, score, box in boxes_a:
        row = class_row(category)
        row["reference_boxes"] += 1
        winner = None; winner_iou = -1.0
        for index, (other_category, other_score, other_box) in enumerate(boxes_b):
            if index in used or category != other_category:
                continue
            top_left = np.maximum(box[:2], other_box[:2]); bottom_right = np.minimum(box[2:], other_box[2:])
            intersection = float(np.prod(np.maximum(0.0, bottom_right - top_left)))
            area_a = float(np.prod(np.maximum(0.0, box[2:] - box[:2])))
            area_b = float(np.prod(np.maximum(0.0, other_box[2:] - other_box[:2])))
            iou = intersection / max(area_a + area_b - intersection, 1e-12)
            if iou >= match_iou and iou > winner_iou:
                winner = index; winner_iou = iou
        if winner is None:
            unmatched_a += 1
            row["unmatched_reference"] += 1
        else:
            used.add(winner)
            matched_pairs += 1
            matched_iou_sum += winner_iou
            row["matched_pairs"] += 1
            row["_iou_sum"] += winner_iou
            confidence_drifts += int(abs(score - boxes_b[winner][1]) > 0.02)
    unmatched_b = len(boxes_b) - len(used)
    for index, (category, _score, _box) in enumerate(boxes_b):
        if index not in used:
            class_row(category)["unmatched_converted"] += 1
    per_class = []
    for category in sorted(class_rows):
        row = class_rows[category]
        pairs = row["matched_pairs"]
        row["mean_matched_iou"] = round(row.pop("_iou_sum") / pairs, 6) if pairs else None
        per_class.append(row)

    def detection_row(category, score, box):
        input_box = [round(float(value), 3) for value in box]
        restored, error_code = _restore_box(box, adapt=adapt, geometry=geometry, original_size=original_size)
        return {
            "class_id": category,
            "confidence": round(score, 6),
            "box_xyxy": input_box,  # Backward-compatible input-space alias.
            "box_xyxy_input": input_box,
            "box_xyxy_original": restored,
            "coordinate_error": error_code,
        }

    reference_rows = [detection_row(*row) for row in boxes_a]
    converted_rows = [detection_row(*row) for row in boxes_b]
    mapped = sum(1 for row in reference_rows + converted_rows if row["box_xyxy_original"] is not None)
    total_boxes = len(reference_rows) + len(converted_rows)
    if not adapt:
        original_status = "unavailable"
    elif not total_boxes:
        original_status = "no_detections"
    elif mapped == total_boxes:
        original_status = "mapped"
    elif mapped:
        original_status = "partial"
    else:
        original_status = "unmapped"
    error_codes: dict[str, int] = {}
    for row in reference_rows + converted_rows:
        if row["coordinate_error"]:
            error_codes[row["coordinate_error"]] = error_codes.get(row["coordinate_error"], 0) + 1
    return {
        "comparable": True, "confidence_threshold": confidence, "nms_iou": nms_iou,
        "match_iou_threshold": match_iou,
        "before_nms_reference": count_a, "before_nms_converted": count_b,
        "after_nms_reference": len(boxes_a), "after_nms_converted": len(boxes_b),
        "threshold_crossings": threshold_crossings,
        "unmatched_reference": unmatched_a, "unmatched_converted": unmatched_b,
        "matched_pairs": matched_pairs,
        "mean_matched_iou": round(matched_iou_sum / matched_pairs, 6) if matched_pairs else None,
        "matched_confidence_drifts": confidence_drifts,
        "class_count": class_count,
        "per_class": per_class,
        "reference_detections": reference_rows[:50],
        "converted_detections": converted_rows[:50],
        "detections_truncated_for_display": len(boxes_a) > 50 or len(boxes_b) > 50,
        "original_coordinates": {
            "status": original_status,
            "mapped": mapped,
            "unmapped": total_boxes - mapped,
            "error_codes": error_codes,
            "original_size": [int(original_size[0]), int(original_size[1])] if original_size else None,
            "geometry": dict(geometry) if isinstance(geometry, Mapping) else None,
        },
        "within_tolerance": unmatched_a == 0 and unmatched_b == 0 and confidence_drifts == 0,
    }


def verify_label_identity(names, *, label_codes=None, label_schema=None) -> dict:
    """A matching class count alone cannot establish the deployed class order."""
    from platform_core.model_metadata import frozen_weight_labels

    frozen = {"label_codes": label_codes, "label_schema": label_schema}
    expected = frozen_weight_labels(frozen)
    if not expected:
        has_claim = bool(label_codes or label_schema)
        return {"status": "conflict" if has_claim else "unknown", "codes": [],
                "reason": "冻结类别顺序存在冲突" if has_claim else "版本缺少可信的冻结类别顺序"}
    if isinstance(names, dict) and set(names) == set(range(len(names))):
        actual = [names[i] for i in range(len(names))]
    elif isinstance(names, (list, tuple)):
        actual = list(names)
    else:
        actual = []
    actual = [str(value).strip() for value in actual]
    matched = actual == expected
    return {"status": "verified" if matched else "mismatch", "codes": expected,
            "model_names": actual, "reason": "" if matched else "源 PT 类别名称或顺序与冻结版本标签不一致",
            "mapping_sha256": hashlib.sha256(json.dumps(expected, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()}


def is_canonical_rgb_preprocessing(preprocessing: dict | None) -> bool:
    """Raw-tensor evidence is not deployment evidence for noncanonical inputs."""
    contract = preprocessing or {}

    def triple(field, defaults):
        value = contract.get(field, defaults)
        try:
            values = value.split(",") if isinstance(value, str) else list(value)
            return [float(v) for v in values] if len(values) == 3 else None
        except (TypeError, ValueError, OverflowError):
            return None

    mean, scale = triple("mean", [0, 0, 0]), triple("scale", [1 / 255] * 3)
    return (
        contract.get("letterbox", True) is True
        and contract.get("pixel_format", "rgb") == "rgb"
        and contract.get("pad_value", 114) == 114
        and contract.get("channel_format") == "nchw"
        and contract.get("resize_interpolation") == "opencv_linear"
        and contract.get("letterbox_mode") == "fixed_shape_center"
        and mean == [0.0, 0.0, 0.0]
        and scale is not None and all(abs(v - 1 / 255) <= 1e-9 for v in scale)
    )


def make_input_with_geometry(image_path: Path, height: int, width: int) -> dict:
    """Fixed-shape YOLO LetterBox with OpenCV INTER_LINEAR, RGB, 0..1, NCHW.

    Returns the tensor plus the exact preprocessing geometry (scale/pad/crop)
    needed to restore input-coordinate detections to original pixels.
    """
    import numpy as np
    from PIL import Image
    try:
        import cv2
    except ImportError as error:
        raise RuntimeError("缺少 OpenCV，无法按冻结的 opencv_linear 推理合同生成验证输入") from error

    with Image.open(image_path) as im:
        image = im.convert("RGB")
        original_w, original_h = image.size
        ratio = min(width / original_w, height / original_h)
        new_w = max(1, round(original_w * ratio))
        new_h = max(1, round(original_h * ratio))
        image = cv2.resize(np.asarray(image), (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        pixels = np.full((height, width, 3), 114, dtype=np.uint8)
        x = round((width - new_w) / 2 - 0.1)
        y = round((height - new_h) / 2 - 0.1)
        pixels[y:y + new_h, x:x + new_w] = image
    tensor = np.ascontiguousarray(pixels.transpose(2, 0, 1)[None].astype(np.float32) / 255.0)
    geometry = {
        "width": int(width), "height": int(height),
        "scale_x": float(new_w) / float(original_w), "scale_y": float(new_h) / float(original_h),
        "pad_x": float(x), "pad_y": float(y), "crop_x": 0.0, "crop_y": 0.0,
    }
    return {
        "tensor": tensor,
        "geometry": geometry,
        "original_size": [int(original_w), int(original_h)],
        "processed_size": [int(width), int(height)],
        "letterbox": {"ratio": float(ratio), "new_width": int(new_w), "new_height": int(new_h),
                      "pad_x": int(x), "pad_y": int(y)},
    }


def make_input(image_path: Path, height: int, width: int):
    """Fixed-shape YOLO LetterBox with OpenCV INTER_LINEAR, RGB, 0..1, NCHW."""
    return make_input_with_geometry(image_path, height, width)["tensor"]


def _primary_pt_output(value):
    if isinstance(value, (tuple, list)):
        value = value[0]
    if not hasattr(value, "detach"):
        raise ValueError("PT 模型没有返回可比较的原始数值张量")
    return value.detach().cpu().numpy()


def _simulate_bmodel(input_tensor, input_name: str, model: Path, python_path: str):
    """Use Sophon's official model_runner when present, not tpu hardware."""
    import numpy as np

    runner = Path(__file__).resolve().parents[2] / "conversion_sophon_offline_runner.py"
    executable = shutil.which(python_path) if python_path else None
    if not executable or not runner.is_file():
        raise RuntimeError("未配置本机可用的 Sophon SDK Python／模型模拟器")
    with tempfile.TemporaryDirectory(prefix="sophon-numeric-") as temp:
        directory = Path(temp)
        input_file, output_file = directory / "input.npz", directory / "output.npz"
        np.savez(input_file, **{input_name: input_tensor})
        process = subprocess.run(
            [executable, str(runner), "--model", str(model), "--input", str(input_file), "--output", str(output_file)],
            cwd=str(directory), capture_output=True, text=True, timeout=180, check=False,
        )
        if process.returncode or not output_file.is_file():
            raise RuntimeError("Sophon 官方离线模拟器不可用或执行失败：" + (process.stderr or process.stdout or "无输出")[-300:])
        with np.load(output_file, allow_pickle=False) as data:
            if len(data.files) != 1:
                raise ValueError("Sophon 模拟器返回多输出，当前无法安全映射到 ONNX 单输出")
            return data[data.files[0]].copy()


def validate_paths(source_path: Path, onnx_path: Path, images: list[Path], *, expected_source_sha: str = "", expected_onnx_sha: str = "") -> None:
    if source_path.suffix.lower() not in {".pt", ".pth"}:
        raise ValueError("源模型不是 PT，无法执行 PT／ONNX 双端数值比较")
    if onnx_path.suffix.lower() != ".onnx":
        raise ValueError("转换产物缺少 ONNX 中间模型")
    for path in [source_path, onnx_path, *images]:
        if not path.is_file():
            raise FileNotFoundError(f"验证输入已不存在：{path.name}")
    if not images:
        raise ValueError("至少选择一张真实图片进行数值验证")
    for candidate,expected,label in ((source_path, expected_source_sha, "源 PT"),(onnx_path,expected_onnx_sha,"ONNX")):
        if expected:
            hasher = hashlib.sha256()
            with candidate.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(block)
            if hasher.hexdigest() != expected:
                raise ValueError(f"{label} SHA256 不一致，拒绝对错误的模型出具报告")


def _frozen_shape(value) -> tuple[list[int] | None, str]:
    """Validate a caller-frozen [1,3,H,W] NCHW shape; dynamic/absent is explicit."""
    if value is None:
        return None, "frozen_input_shapes_missing"
    if isinstance(value, Mapping):
        value = [value]
    if not isinstance(value, (list, tuple)) or not value:
        return None, "frozen_input_shapes_invalid"
    if len(value) != 1:
        return None, "frozen_input_shapes_not_single_input"
    row = value[0]
    if not isinstance(row, (list, tuple)) or len(row) != 4:
        return None, "frozen_input_shapes_invalid"
    if any(type(dim) is not int or dim <= 0 for dim in row):
        return None, "frozen_input_shapes_dynamic"
    if row[0] != 1 or row[1] != 3:
        return None, "frozen_input_shapes_not_nchw_single_image"
    return [int(row[0]), int(row[1]), int(row[2]), int(row[3])], ""


def _frozen_imgsz(value) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    if any(type(dim) is not int or dim <= 0 for dim in value):
        return None
    return [int(value[0]), int(value[1])]


def _resolve_input_contract(input_meta, *, input_shapes, frozen_imgsz, frozen_batch=None) -> dict:
    """Resolve the real comparison size without ever faking a dynamic graph static."""
    shape = list(getattr(input_meta, "shape", []) or [])
    frozen, frozen_error = _frozen_shape(input_shapes)
    frozen_size = _frozen_imgsz(frozen_imgsz)
    contract = {
        "frozen_input_shapes": [frozen] if frozen else None,
        "frozen_input_shapes_status": "usable" if frozen else frozen_error,
        "frozen_imgsz": frozen_size,
        "frozen_batch": frozen_batch if type(frozen_batch) is int else None,
        "graph_input_shape": [dim if type(dim) is int else "dynamic" for dim in shape],
        "status": "resolved", "code": "", "reason": "",
        "dynamic_resolution": "static", "input_shape_source": "onnx_graph_static",
        "dynamic_resolution_reason": "",
        "resolved_input_shape": None,
    }
    if len(shape) != 4 or shape[1] != 3:
        raise ValueError("ONNX 输入不符合单图 NCHW 三通道合同")
    batch = shape[0]
    if type(batch) is int:
        if batch != 1:
            contract.update(status="not_comparable", code="NON_SINGLE_IMAGE_BATCH",
                            dynamic_resolution="not_comparable",
                            reason="ONNX 输入 batch 不是固定单图，禁止伪造成单图核验")
            return contract
    elif type(frozen_batch) is not int or frozen_batch != 1:
        contract.update(status="not_comparable", code="DYNAMIC_BATCH_WITHOUT_FROZEN_BATCH",
                        dynamic_resolution="not_comparable",
                        reason="ONNX 输入 batch 为动态且调用方未冻结 batch=1，禁止按单图冒充核验")
        return contract
    else:
        contract["batch_source"] = "frozen_batch"
    spatial_static = all(type(dim) is int and dim > 0 for dim in shape[2:])
    if spatial_static:
        static_size = [int(shape[2]), int(shape[3])]
        if frozen and [frozen[2], frozen[3]] != static_size:
            contract.update(status="not_comparable", code="INPUT_SHAPE_CONFLICT",
                            reason="调用方冻结的 input_shapes 与 ONNX 静态输入尺寸冲突")
            return contract
        if frozen and frozen_size and frozen_size != [frozen[2], frozen[3]]:
            contract.update(status="not_comparable", code="INPUT_SHAPE_CONFLICT",
                            reason="调用方冻结的 imgsz 与 input_shapes 冻结尺寸冲突")
            return contract
        resolved = [frozen[2], frozen[3]] if frozen else static_size
        contract.update(
            input_shape_source="frozen_manifest" if frozen else "onnx_graph_static",
            resolved_input_shape=[1, 3, *resolved],
        )
        if not frozen:
            contract["input_shape_source"] = "onnx_graph_static"
            contract["frozen_evidence_note"] = "调用方未提供冻结 input_shapes，采用 ONNX 图静态尺寸（动态图不会走到此分支）"
    else:
        # Dynamic spatial dimensions: only an explicitly frozen size may be used.
        if frozen and frozen_size and frozen_size != [frozen[2], frozen[3]]:
            contract.update(status="not_comparable", code="INPUT_SHAPE_CONFLICT",
                            reason="调用方冻结的 imgsz 与 input_shapes 冻结尺寸冲突")
            return contract
        if frozen and frozen_size:
            resolved = frozen_size
        elif frozen:
            resolved = [frozen[2], frozen[3]]
        elif frozen_size:
            resolved = frozen_size
        else:
            contract.update(
                status="not_comparable", code=DYNAMIC_INPUT_WITHOUT_FROZEN_CODE,
                reason="ONNX 输入含动态空间维度，但未冻结 imgsz/input_shapes；禁止静默回退 640",
                dynamic_resolution="not_comparable", input_shape_source="none",
            )
            return contract
        contract.update(
            dynamic_resolution="frozen_imgsz",
            input_shape_source="frozen_manifest" if frozen else "frozen_imgsz",
            resolved_input_shape=[1, 3, *resolved],
            dynamic_resolution_reason="ONNX 输入空间维度为动态；按转换请求/清单冻结的输入尺寸比较，未把动态图伪装成静态",
        )
    height, width = contract["resolved_input_shape"][2:]
    if not (32 <= height <= 4096 and 32 <= width <= 4096):
        contract.update(status="not_comparable", code="INPUT_SIZE_OUT_OF_RANGE",
                        reason="冻结/静态输入尺寸不在可安全验证范围内（32..4096）")
    return contract


def _empty_result(*, precision: str, input_color_space: str, runtime: dict, input_contract: dict,
                  code: str, reason: str) -> dict:
    return {
        "protocol": PROTOCOL,
        "raw_verdict": "not_comparable", "verdict": "not_comparable",
        "detection_status": "unavailable",
        "comparison_confidence": None, "comparison_nms_iou": None,
        "status": "completed", "sample_count": 0, "precision": precision,
        "source": "PT", "compared": "ONNX",
        "bmodel_verified": False, "hardware_verified": False, "ground_truth_used": False,
        "bmodel_numeric_status": "not_applicable", "bmodel_detection_status": "not_applicable",
        "bmodel_numeric_error": "",
        "deployment_preprocessing_aligned": None,
        "label_count_matched": None, "label_identity": None,
        "input_color_space": input_color_space,
        "input_contract": input_contract,
        "input_shapes": input_contract.get("frozen_input_shapes"),
        "dynamic_resolution": input_contract.get("dynamic_resolution", "not_comparable"),
        "dynamic_resolution_reason": input_contract.get("reason", ""),
        "runtime_versions": runtime,
        "rejection": {"code": code, "reason": reason},
        "scope_note": SCOPE_NOTE,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "images": [],
    }


def verify_images(source_path: Path, onnx_path: Path, images: list[Path], *, precision: str, expected_source_sha: str = "", expected_onnx_sha: str = "", input_color_order: str = "rgb", preprocessing: dict | None = None, label_codes: list[str] | None = None, label_schema: list[dict] | None = None, confidence: float = 0.25, nms_iou: float = 0.7, bmodel_path: Path | None = None, bmodel_sha256: str = "", bmodel_expected: bool = False, sophon_python: str = "", input_shapes: list | None = None, frozen_imgsz: list | None = None, frozen_batch: int | None = None, progress=None) -> dict:
    validate_paths(source_path, onnx_path, images, expected_source_sha=expected_source_sha, expected_onnx_sha=expected_onnx_sha)
    color = str(input_color_order or "rgb").strip().lower()
    if color != "rgb":
        # Keep the existing refusal; record the explicit reason code instead of
        # silently reinterpreting the same tensor as RGB.
        return _empty_result(
            precision=precision, input_color_space=color, runtime=runtime_versions(),
            input_contract={"status": "not_comparable", "code": NON_RGB_INPUT_CODE,
                            "input_color_space": color, "frozen_input_shapes": None,
                            "dynamic_resolution": "not_comparable"},
            code=NON_RGB_INPUT_CODE,
            reason="该产物使用非 RGB 输入颜色适配；当前原始张量核验仅支持 RGB 同输入，不能冒充通过",
        )
    bmodel_error = ""
    if bmodel_path and bmodel_path.is_file():
        if bmodel_sha256:
            digest = hashlib.sha256()
            with bmodel_path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != bmodel_sha256:
                raise ValueError("BMODEL SHA256 与转换产物不一致，不能出具数值报告")
    import numpy as np
    import onnxruntime as ort
    import torch
    from ultralytics import YOLO

    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    inputs = session.get_inputs()
    if len(inputs) != 1 or len(session.get_outputs()) != 1:
        raise ValueError("ONNX 输入／输出不是单张量；暂不能进行可靠的原始输出对齐")
    input_meta = inputs[0]
    input_contract = _resolve_input_contract(input_meta, input_shapes=input_shapes, frozen_imgsz=frozen_imgsz,
                                             frozen_batch=frozen_batch)
    if input_contract["status"] != "resolved":
        return _empty_result(
            precision=precision, input_color_space=color, runtime=runtime_versions(),
            input_contract=input_contract,
            code=str(input_contract.get("code") or "INPUT_CONTRACT_NOT_COMPARABLE"),
            reason=str(input_contract.get("reason") or "输入尺寸合同无法安全确定"),
        )
    height, width = input_contract["resolved_input_shape"][2:]
    detector = YOLO(str(source_path))
    pt = detector.model.cpu().eval().float()
    names = getattr(detector, "names", None) or getattr(pt, "names", None)
    class_count = len(names) if isinstance(names, (dict, list, tuple)) else 0
    if isinstance(names, dict) and set(names) != set(range(class_count)):
        class_count = 0
    label_identity = verify_label_identity(names, label_codes=label_codes, label_schema=label_schema)
    label_count_matched = None if label_identity["status"] == "unknown" else label_identity["status"] == "verified"
    if label_identity["status"] in {"mismatch", "conflict"}:
        class_count = 0
    # Legacy jobs without a frozen preprocessing contract remain unknown, not
    # implicitly verified as matching today's canonical RGB defaults.
    canonical_preprocessing = is_canonical_rgb_preprocessing(preprocessing) if preprocessing else None
    versions = runtime_versions()
    results = []
    simulator_error = "BMODEL 文件不存在或未在当前转换产物目录中" if (bmodel_expected or bmodel_path) and (not bmodel_path or not bmodel_path.is_file()) else bmodel_error
    for i, image in enumerate(images):
        prepared = make_input_with_geometry(image, height, width)
        tensor = prepared["tensor"]
        with torch.inference_mode():
            reference = _primary_pt_output(pt(torch.from_numpy(tensor)))
        dtype = np.float16 if input_meta.type == "tensor(float16)" else np.float32
        converted = session.run(None, {input_meta.name: tensor.astype(dtype)})[0]
        metrics = compare_tensors(reference, converted, precision=precision)
        metrics["detection"] = compare_yolo_detections(
            reference, converted, class_count=class_count,
            confidence=confidence, nms_iou=nms_iou,
            geometry=prepared["geometry"], original_size=prepared["original_size"],
        )
        metrics["input_geometry"] = prepared["geometry"]
        metrics["letterbox_geometry"] = prepared["letterbox"]
        metrics["input_size"] = prepared["processed_size"]
        metrics["original_size"] = prepared["original_size"]
        if bmodel_path and bmodel_path.is_file() and not simulator_error:
            try:
                bmodel_output = _simulate_bmodel(tensor, input_meta.name, bmodel_path, sophon_python)
                metrics["onnx_bmodel"] = compare_tensors(converted, bmodel_output, precision=precision)
                metrics["onnx_bmodel_detection"] = compare_yolo_detections(
                    converted, bmodel_output, class_count=class_count,
                    confidence=confidence, nms_iou=nms_iou,
                    geometry=prepared["geometry"], original_size=prepared["original_size"])
            except Exception as error:
                simulator_error = str(error)
        results.append({"image": image.name, **metrics})
        if progress:
            progress(i + 1, len(images))
    compatible = all(row.get("comparable") for row in results)
    matching = compatible and all(row.get("within_tolerance") for row in results)
    detection_comparable = all(row["detection"].get("comparable") for row in results)
    detection_matching = detection_comparable and all(row["detection"].get("within_tolerance") for row in results)
    bmodel_requested = bool(bmodel_expected or bmodel_path)
    bmodel_compared = bool(bmodel_path and bmodel_path.is_file()) and all(row.get("onnx_bmodel", {}).get("comparable") for row in results)
    bmodel_matching = bmodel_compared and all(row["onnx_bmodel"].get("within_tolerance") for row in results)
    bmodel_detection_comparable = bmodel_compared and all(row.get("onnx_bmodel_detection", {}).get("comparable") for row in results)
    bmodel_detection_matching = bmodel_detection_comparable and all(row["onnx_bmodel_detection"].get("within_tolerance") for row in results)
    # A raw-tensor pass alone cannot be labelled a detection-consistency pass.
    if label_identity["status"] in {"conflict", "mismatch"}:
        verdict = "contract_mismatch"
    elif (compatible and not matching) or (detection_comparable and not detection_matching):
        verdict = "difference_detected"
    elif not compatible or not detection_comparable:
        verdict = "not_comparable"
    else:
        verdict = "consistent"
    return {
        "protocol": PROTOCOL,
        "raw_verdict": "consistent" if matching else ("difference_detected" if compatible else "not_comparable"),
        "verdict": verdict,
        "detection_status": "consistent" if detection_matching else ("difference_detected" if detection_comparable else "unavailable"),
        "comparison_confidence": confidence, "comparison_nms_iou": nms_iou,
        "status": "completed", "sample_count": len(results), "precision": precision,
        "source": "PT", "compared": "ONNX", "bmodel_verified": False,
        "hardware_verified": False, "ground_truth_used": False,
        "bmodel_numeric_status": "consistent" if bmodel_matching else ("difference_detected" if bmodel_compared else "unavailable" if bmodel_requested else "not_applicable"),
        "bmodel_detection_status": "consistent" if bmodel_detection_matching else ("difference_detected" if bmodel_detection_comparable else "unavailable" if bmodel_requested else "not_applicable"),
        "bmodel_numeric_error": simulator_error,
        "deployment_preprocessing_aligned": canonical_preprocessing,
        "label_count_matched": label_count_matched,
        "label_identity": label_identity,
        "input_color_space": color,
        "input_contract": input_contract,
        "input_shapes": input_contract.get("frozen_input_shapes"),
        "dynamic_resolution": input_contract.get("dynamic_resolution", "static"),
        "dynamic_resolution_reason": input_contract.get("dynamic_resolution_reason", ""),
        "runtime_versions": versions,
        "rejection": None,
        "scope_note": SCOPE_NOTE,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "images": results,
    }


def _write_json_atomic(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def project_numeric_status(directory: Path, receipt: dict, result: dict) -> dict:
    """Project the verdict into the existing conversion job JSON (no new store).

    The conversion job remains the single Owner of its own record; this only
    adds the existing `numeric_status`/`publication_status` JSON fields, which
    the conversion-history asset view already reads.
    """
    directory = Path(directory)
    job_id = str(receipt.get("conversion_job_id") or "").strip()
    project_id = str(receipt.get("project_id") or "").strip()
    if not job_id:
        return {"status": "skipped", "reason": "验证请求未冻结所属转换任务"}
    numeric_root = directory.parent
    if numeric_root.name != "numeric-validations":
        return {"status": "unavailable", "reason": "验证目录不在既有转换任务布局内，未写回状态"}
    job_path = numeric_root.parent / "jobs" / job_id / "job.json"
    if not job_path.is_file():
        return {"status": "unavailable", "reason": "所属转换任务记录不存在，未写回状态"}
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {"status": "unavailable", "reason": f"转换任务记录无法读取：{error}"}
    if not isinstance(job, dict) or str(job.get("id") or "") != job_id:
        return {"status": "unavailable", "reason": "转换任务记录身份与验证请求不一致，拒绝写回"}
    if project_id and str(job.get("project_id") or "") != project_id:
        return {"status": "unavailable", "reason": "转换任务项目身份与验证请求不一致，拒绝写回"}
    failed = str(result.get("status") or "completed") != "completed"
    verdict = "unavailable" if failed else str(result.get("verdict") or "not_comparable")
    numeric_status = NUMERIC_STATUS_BY_VERDICT.get(verdict, "unavailable")
    publication_status = PUBLICATION_STATUS_BY_NUMERIC[numeric_status]
    numeric_validation = {
        "verification_id": str(receipt.get("id") or directory.name),
        "status": "completed" if not failed else "failed",
        "verdict": verdict,
        "raw_verdict": str(result.get("raw_verdict") or ""),
        "detection_status": str(result.get("detection_status") or ""),
        "sample_count": result.get("sample_count"),
        "protocol": str(result.get("protocol") or ""),
        "precision": str(result.get("precision") or ""),
        "hardware_verified": False,
        "ground_truth_used": False,
        "completed_at": str(result.get("completed_at") or datetime.now(timezone.utc).isoformat()),
        "result_ref": "numeric-validations/" + directory.name + "/result.json",
        "error": str(result.get("error") or "")[:512],
    }
    job.update({
        "numeric_status": numeric_status,
        "publication_status": publication_status,
        "numeric_validation": numeric_validation,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    _write_json_atomic(job_path, job)
    return {"status": "projected", "job_id": job_id, "numeric_status": numeric_status,
            "publication_status": publication_status,
            "result_ref": numeric_validation["result_ref"]}


def run_verification_directory(directory: Path) -> None:
    request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
    result_path = directory / "result.json"

    def record(value):
        result_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def progress(done, total):
        record({"status": "running", "progress": round(100 * done / total, 2), "stage": f"正在比较 {done}/{total} 张图片"})

    try:
        record({"status": "running", "progress": 2, "stage": "加载 PT 和 ONNX 推理运行时"})
        result = verify_images(
            Path(request["source_path"]), Path(request["onnx_path"]),
            [directory / "images" / name for name in request["image_names"]],
            precision=request["precision"], expected_source_sha=request.get("source_sha256", ""),
            expected_onnx_sha=request.get("onnx_sha256", ""),
            input_color_order=request.get("input_color_order", "rgb"),
            preprocessing=request.get("preprocessing"),
            label_codes=request.get("label_codes"),
            label_schema=request.get("label_schema"),
            confidence=float(request.get("confidence", 0.25)),
            nms_iou=float(request.get("nms_iou", 0.7)),
            input_shapes=request.get("input_shapes"),
            frozen_imgsz=request.get("frozen_imgsz"),
            frozen_batch=request.get("frozen_batch"),
            bmodel_path=Path(request["bmodel_path"]) if request.get("bmodel_path") else None,
            bmodel_sha256=request.get("bmodel_sha256", ""), bmodel_expected=bool(request.get("bmodel_expected")),
            sophon_python=request.get("sophon_python", ""),
            progress=progress,
        )
        try:
            projection = project_numeric_status(directory, request, result)
        except Exception as error:  # A projection failure must not hide the evidence.
            projection = {"status": "failed", "reason": f"状态写回失败：{error}"[:500]}
        record({**result, "status_projection": projection, "progress": 100, "stage": "数值比较已完成"})
    except Exception as error:
        failure = {"status": "failed", "progress": 100, "stage": "验证无法完成", "error": str(error),
                   "verdict": "unavailable", "bmodel_verified": False, "hardware_verified": False,
                   "runtime_versions": runtime_versions(),
                   "completed_at": datetime.now(timezone.utc).isoformat()}
        try:
            projection = project_numeric_status(directory, request, failure)
        except Exception as projection_error:
            projection = {"status": "failed", "reason": f"状态写回失败：{projection_error}"[:500]}
        record({**failure, "status_projection": projection})
        raise
