"""Offline PT/ONNX numerical comparison on identical real image tensors.

This is not a BMODEL hardware inference test or an accuracy evaluation.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock, Timeout

from ..conversion import canonical_json_bytes, sha256_file, verify_source_manifest_digest


PROTOCOL = "pt-onnx-raw-and-detection-v4"
RUNTIME_MODULES = ("torch", "ultralytics", "onnx", "onnxruntime", "numpy", "cv2")
DYNAMIC_INPUT_WITHOUT_FROZEN_CODE = "DYNAMIC_INPUT_WITHOUT_FROZEN_IMGSZ"
NON_RGB_INPUT_CODE = "NON_RGB_INPUT_NOT_COMPARABLE"
# A BMODEL conversion's deliverable is the compiled BMODEL, not the ONNX
# intermediate. PT-vs-ONNX agreement alone never proves the BMODEL's outputs;
# when the frozen evidence says a BMODEL was expected, delivery admission must
# also see the recorded ONNX-vs-BMODEL numeric and detection verdicts.
BMODEL_EVIDENCE_NOT_ELIGIBLE_CODE = "BMODEL_EVIDENCE_NOT_ELIGIBLE"
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


def verify_images(source_path: Path, onnx_path: Path, images: list[Path], *, precision: str, expected_source_sha: str = "", expected_onnx_sha: str = "", input_color_order: str = "rgb", preprocessing: dict | None = None, label_codes: list[str] | None = None, label_schema: list[dict] | None = None, label_binding: dict | None = None, output_contract: dict | None = None, confidence: float = 0.25, nms_iou: float = 0.7, bmodel_path: Path | None = None, bmodel_sha256: str = "", bmodel_expected: bool = False, sophon_python: str = "", input_shapes: list | None = None, frozen_imgsz: list | None = None, frozen_batch: int | None = None, progress=None) -> dict:
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

    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    inputs = session.get_inputs()
    if len(inputs) != 1 or len(session.get_outputs()) != 1:
        raise ValueError("ONNX 输入／输出不是单张量；暂不能进行可靠的原始输出对齐")
    declared_layout = str((output_contract or {}).get("layout") or "").strip().lower()
    if declared_layout and declared_layout not in {
        "yolo", "yolo_v8", "yolo11", "ultralytics_yolo",
    }:
        return _empty_result(
            precision=precision, input_color_space=color, runtime=runtime_versions(),
            input_contract={"status": "not_comparable", "code": "OUTPUT_CONTRACT_UNSUPPORTED"},
            code="OUTPUT_CONTRACT_UNSUPPORTED",
            reason="转换 manifest 声明的输出布局不受当前解码器支持，不能以形状相似冒充一致",
        )
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
    # Load the PT model only after the ONNX session and its frozen input
    # contract are validated: a not-comparable input contract must be decidable
    # without requiring the torch/ultralytics stack.
    try:
        import torch  # noqa: F401
        from ultralytics import YOLO
    except ImportError as error:
        raise ValueError(
            "PT/ONNX 数值比较需要已配置的 torch/ultralytics 运行时: " + str(error)
        ) from error
    detector = YOLO(str(source_path))
    pt = detector.model.cpu().eval().float()
    names = getattr(detector, "names", None) or getattr(pt, "names", None)
    class_count = len(names) if isinstance(names, (dict, list, tuple)) else 0
    if isinstance(names, dict) and set(names) != set(range(class_count)):
        class_count = 0
    label_identity = verify_label_identity(names, label_codes=label_codes, label_schema=label_schema)
    label_count_matched = None if label_identity["status"] == "unknown" else label_identity["status"] == "verified"
    if isinstance(label_binding, Mapping) and label_binding:
        binding_status = _clean(label_binding.get("status"))
        if binding_status != "verified":
            label_identity = {
                "status": "conflict" if binding_status == "conflict" else "unknown",
                "codes": [], "mapping_sha256": "",
                "reason": "冻结 label_binding 不是 verified，不能由历史 label_schema 重新解释",
            }
            label_count_matched = False
        else:
            normalized = []
            try:
                normalized = sorted(
                    [dict(row, class_id=int(row.get("class_id")))
                     for row in (label_schema or [])],
                    key=lambda row: int(row.get("class_id")),
                )
            except (TypeError, ValueError):
                normalized = []
            codes = [str(code) for code in (label_codes or [])]
            if normalized:
                schema_ok = (
                    bool(codes)
                    and len(normalized) == len(codes)
                    and [int(row.get("class_id")) for row in normalized] == list(range(len(codes)))
                    and [str(row.get("code") or "") for row in normalized] == codes
                )
            else:
                # Trusted codes-only contracts are valid: the order is the class
                # id order and no historical schema is invented.
                schema_ok = bool(codes)
            mapping_sha = hashlib.sha256(
                json.dumps(codes, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            schema_sha = hashlib.sha256(
                json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
            ).hexdigest() if normalized else ""
            expected_schema_sha = str(label_binding.get("schema_sha256") or "")
            if (not schema_ok
                    or str(label_binding.get("mapping_sha256") or "") != mapping_sha
                    or expected_schema_sha != schema_sha
                    or (not normalized and expected_schema_sha)):
                label_identity = {
                    "status": "conflict", "codes": [], "mapping_sha256": "",
                    "reason": "label_binding 的类别顺序/摘要与验证请求不一致",
                }
                label_count_matched = False
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


# ---------------------------------------------------------------------------
# M10-C: every numeric verdict is bound to the conversion identity that produced
# it. Complete immutable evidence is persisted first; the mutable quality
# summary is then projected into the existing conversion record (job.json), the
# single Owner of numeric_status/publication_status. No second quality store or
# database table is created.
# ---------------------------------------------------------------------------
EVIDENCE_SCHEMA = "numeric-verification-evidence-v1"
STALE_VERIFICATION_CODE = "STALE_VERIFICATION_RESULT"
EVIDENCE_CONFLICT_CODE = "VERIFICATION_EVIDENCE_CONFLICT"
VERIFICATION_IDENTITY_FIELDS = (
    "project_id", "algorithm_id", "version_id", "conversion_job_id",
    "source_pt_sha256", "onnx_sha256", "target_artifact_sha256", "manifest_digest",
)
EVIDENCE_SUBDIRECTORY = "evidence"


class VerificationEvidenceConflict(ValueError):
    """A deterministic verification identity must never map to different evidence."""

    code = EVIDENCE_CONFLICT_CODE


def _clean(value) -> str:
    return str(value or "").strip()


def _canonical_digest(value) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _safe_digest(value) -> str:
    """A digest for evidence identity; non-canonical values stay explicitly empty."""
    try:
        return _canonical_digest(value)
    except (TypeError, ValueError):
        return ""


def _json_read(path, default=None):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return value


def _artifact_sha(path_text) -> tuple[str, bool]:
    """Streaming SHA256 of the actual artifact bytes; explicit unavailable on failure."""
    raw = _clean(path_text)
    if not raw:
        return "", False
    path = Path(raw)
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return "", False
        return sha256_file(path), True
    except OSError:
        return "", False


def _conversion_job_path(directory, job_id) -> Path | None:
    directory = Path(directory)
    numeric_root = directory.parent
    if numeric_root.name != "numeric-validations":
        return None
    job_id = _clean(job_id)
    if (not job_id or job_id in {".", ".."} or "/" in job_id or "\\" in job_id
            or ":" in job_id):
        return None
    return numeric_root.parent / "jobs" / job_id / "job.json"


def _target_artifact(job, receipt, *, actual_bmodel_sha, bmodel_present) -> dict:
    """Resolve the unique deliverable that is not the ONNX intermediate, if any."""
    result = {"name": "", "sha256": "", "expected_sha256": "", "kind": ""}
    target = _clean((job or {}).get("target")).lower()
    if target == "onnx":
        result["kind"] = "onnx"
        return result
    bmodel_path = _clean(receipt.get("bmodel_path"))
    if bmodel_path:
        result.update(name=Path(bmodel_path).name, kind=target or "bmodel",
                      expected_sha256=_clean(receipt.get("bmodel_sha256")).lower())
        if bmodel_present:
            result["sha256"] = actual_bmodel_sha
        return result
    candidates = []
    for row in (job or {}).get("outputs") or []:
        if not isinstance(row, Mapping):
            continue
        name = _clean(row.get("name") or Path(_clean(row.get("path"))).name)
        if not name or name.lower().endswith(".onnx"):
            continue
        candidates.append({
            "name": name,
            "path": _clean(row.get("path")),
            "sha256": _clean(row.get("sha256")).lower(),
        })
    if len(candidates) != 1:
        return result
    row = candidates[0]
    result.update(name=row["name"], kind=target or "converted", expected_sha256=row["sha256"])
    if row["path"]:
        observed, present = _artifact_sha(row["path"])
        if present:
            result["sha256"] = observed
    return result


def conversion_identity(directory, receipt) -> dict:
    """Current identity of the conversion record/artifact an evidence is bound to.

    The conversion record (job.json) and its frozen manifest stay the Owners of
    this identity. Missing evidence is recorded as an explicit ``""`` plus
    ``unavailable``; nothing is guessed. A conflicting record/product is marked
    ``conflict`` so publication can fail closed instead of overwriting a newer
    identity with stale evidence.
    """
    receipt = receipt if isinstance(receipt, Mapping) else {}
    directory = Path(directory)
    identity = {key: "" for key in VERIFICATION_IDENTITY_FIELDS}
    identity.update({
        "target_artifact_kind": "",
        "job_record_status": "",
        "manifest_integrity": {"status": "unavailable", "reason": "转换记录不可用"},
        "issues": [],
        "availability": {},
        "missing": [],
        "status": "unavailable",
        "identity_digest": "",
    })
    issues = identity["issues"]

    def issue(code, message, *, conflict=False, field=""):
        issues.append({"code": code, "message": str(message)[:300], "field": field,
                       "severity": "conflict" if conflict else "notice"})

    identity["project_id"] = _clean(receipt.get("project_id"))
    identity["conversion_job_id"] = _clean(receipt.get("conversion_job_id"))
    receipt_source_sha = _clean(receipt.get("source_sha256")).lower()
    receipt_onnx_sha = _clean(receipt.get("onnx_sha256")).lower()
    source_path = _clean(receipt.get("source_path"))
    onnx_path = _clean(receipt.get("onnx_path"))
    bmodel_path = _clean(receipt.get("bmodel_path"))
    actual_source_sha, source_present = _artifact_sha(source_path)
    actual_onnx_sha, onnx_present = _artifact_sha(onnx_path)
    actual_bmodel_sha, bmodel_present = _artifact_sha(bmodel_path)

    if source_present:
        identity["source_pt_sha256"] = actual_source_sha
        if receipt_source_sha and receipt_source_sha != actual_source_sha:
            issue("SOURCE_PT_SHA_MISMATCH", "源 PT 实际 SHA256 与冻结验证请求不一致",
                  conflict=True, field="source_pt_sha256")
    elif source_path:
        issue("SOURCE_PT_ARTIFACT_MISSING", "源 PT 文件不存在，无法重算 SHA256",
              field="source_pt_sha256")
    else:
        identity["source_pt_sha256"] = receipt_source_sha

    if onnx_present:
        identity["onnx_sha256"] = actual_onnx_sha
        if receipt_onnx_sha and receipt_onnx_sha != actual_onnx_sha:
            issue("ONNX_SHA_MISMATCH", "ONNX 实际 SHA256 与冻结验证请求不一致",
                  conflict=True, field="onnx_sha256")
    elif onnx_path:
        issue("ONNX_ARTIFACT_MISSING", "ONNX 文件不存在，无法重算 SHA256", field="onnx_sha256")
    else:
        identity["onnx_sha256"] = receipt_onnx_sha

    job_path = _conversion_job_path(directory, identity["conversion_job_id"])
    job = None
    if job_path is None:
        issue("CONVERSION_LAYOUT_UNAVAILABLE", "验证目录不在既有转换任务布局内")
    elif not job_path.is_file():
        issue("CONVERSION_JOB_RECORD_MISSING", "所属转换任务记录不存在")
    else:
        loaded = _json_read(job_path, None)
        if isinstance(loaded, dict):
            job = loaded
        else:
            issue("CONVERSION_JOB_RECORD_UNREADABLE", "所属转换任务记录无法读取")

    if job is not None:
        identity["job_record_status"] = _clean(job.get("status")).lower()
        job_id = _clean(job.get("id"))
        if job_id and identity["conversion_job_id"] and job_id != identity["conversion_job_id"]:
            issue("CONVERSION_JOB_ID_MISMATCH", "转换任务记录身份与验证请求不一致",
                  conflict=True, field="conversion_job_id")
        elif job_id and not identity["conversion_job_id"]:
            identity["conversion_job_id"] = job_id
        job_project = _clean(job.get("project_id"))
        if job_project and identity["project_id"] and job_project != identity["project_id"]:
            issue("CONVERSION_PROJECT_MISMATCH", "转换任务项目身份与验证请求不一致",
                  conflict=True, field="project_id")
        elif job_project and not identity["project_id"]:
            identity["project_id"] = job_project
        trace = job.get("source_trace") if isinstance(job.get("source_trace"), Mapping) else {}
        for key in ("algorithm_id", "version_id"):
            value = _clean(trace.get(key) or job.get(key))
            if value:
                identity[key] = value
        job_source_sha = _clean(trace.get("sha256")).lower()
        if job_source_sha:
            if identity["source_pt_sha256"] and job_source_sha != identity["source_pt_sha256"]:
                issue("SOURCE_PT_SHA_MISMATCH", "转换记录的源 PT SHA256 与验证绑定不一致",
                      conflict=True, field="source_pt_sha256")
            elif not identity["source_pt_sha256"]:
                identity["source_pt_sha256"] = job_source_sha
        job_manifest_digest = _clean(job.get("manifest_digest")).lower()
        manifest_path = Path(_clean(job.get("manifest_path"))) if job.get("manifest_path") else (
            job_path.parent / "artifacts" / "manifest.json")
        manifest = _json_read(manifest_path, None) if manifest_path.is_file() else None
        manifest_onnx_sha = ""
        manifest_outputs = []
        if isinstance(manifest, dict):
            integrity = verify_source_manifest_digest(manifest)
            recorded = _clean(integrity.get("recorded")).lower()
            if integrity.get("present") and not integrity.get("valid"):
                identity["manifest_integrity"] = {"status": "digest_mismatch",
                                                  "reason": _clean(integrity.get("reason"))[:300]}
                issue("MANIFEST_DIGEST_MISMATCH", "转换 manifest 不可变摘要重算不一致",
                      conflict=True, field="manifest_digest")
            elif integrity.get("present"):
                identity["manifest_digest"] = recorded
                identity["manifest_integrity"] = {"status": "digest_verified", "reason": ""}
            elif job_manifest_digest:
                identity["manifest_digest"] = job_manifest_digest
                identity["manifest_integrity"] = {"status": "job_record_only",
                                                  "reason": "manifest 缺少不可变摘要，采用转换记录摘要"}
            else:
                identity["manifest_integrity"] = {
                    "status": "legacy_unverified_digest",
                    "reason": _clean(integrity.get("reason"))[:300]}
            onnx_block = manifest.get("onnx") if isinstance(manifest.get("onnx"), Mapping) else {}
            manifest_onnx_sha = _clean(onnx_block.get("sha256")).lower()
            manifest_outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), list) else []
        elif job_manifest_digest:
            identity["manifest_digest"] = job_manifest_digest
            identity["manifest_integrity"] = {"status": "job_record_only",
                                              "reason": "转换 manifest 文件不可用，仅记录任务摘要"}
        else:
            identity["manifest_integrity"] = {"status": "manifest_unavailable",
                                              "reason": "转换 manifest 与任务记录均无摘要"}
        if job_manifest_digest:
            if identity["manifest_digest"] and identity["manifest_digest"] != job_manifest_digest:
                issue("MANIFEST_DIGEST_CONFLICT", "转换 manifest 摘要与转换记录摘要不一致",
                      conflict=True, field="manifest_digest")
            elif not identity["manifest_digest"] and identity["manifest_integrity"]["status"] not in {
                    "digest_mismatch"}:
                identity["manifest_digest"] = job_manifest_digest
        if manifest_onnx_sha:
            if identity["onnx_sha256"] and identity["onnx_sha256"] != manifest_onnx_sha:
                issue("ONNX_SHA_MISMATCH", "ONNX 实际 SHA256 与转换 manifest 不一致",
                      conflict=True, field="onnx_sha256")
            elif not identity["onnx_sha256"]:
                identity["onnx_sha256"] = manifest_onnx_sha
        target = _target_artifact(job, receipt, actual_bmodel_sha=actual_bmodel_sha,
                                  bmodel_present=bmodel_present)
        identity["target_artifact_kind"] = target["kind"]
        expected = target["expected_sha256"]
        observed = target["sha256"]
        if observed:
            identity["target_artifact_sha256"] = observed
            if expected and expected != observed:
                issue("TARGET_ARTIFACT_SHA_MISMATCH", "目标转换产物 SHA256 与转换记录不一致",
                      conflict=True, field="target_artifact_sha256")
        elif target["name"]:
            issue("TARGET_ARTIFACT_MISSING", "目标转换产物不存在，无法重算 SHA256",
                  field="target_artifact_sha256")
        elif expected:
            identity["target_artifact_sha256"] = expected
        if target["kind"] == "onnx":
            identity["target_artifact_sha256"] = identity["onnx_sha256"]
            identity["target_artifact_kind"] = "onnx"
        # The manifest is the frozen Owner of output digests; cross-check the
        # chosen deliverable by its exact file name instead of trusting the job
        # record alone (a suffix match could bind the wrong artifact).
        if observed and manifest_outputs and target["name"]:
            target_name = Path(target["name"]).name
            for row in manifest_outputs:
                if not isinstance(row, Mapping):
                    continue
                if Path(str(row.get("name") or "")).name != target_name:
                    continue
                row_sha = _clean(row.get("sha256")).lower()
                if row_sha and row_sha != observed:
                    issue("TARGET_ARTIFACT_SHA_MISMATCH", "目标转换产物 SHA256 与转换 manifest 不一致",
                          conflict=True, field="target_artifact_sha256")
                break

    for key in VERIFICATION_IDENTITY_FIELDS:
        identity["availability"][key] = "present" if identity[key] else "unavailable"
    identity["missing"] = [key for key in VERIFICATION_IDENTITY_FIELDS if not identity[key]]
    conflict = any(item["severity"] == "conflict" for item in issues)
    if conflict:
        identity["status"] = "conflict"
    elif (not identity["missing"]
          and identity["manifest_integrity"]["status"] in {
              "digest_verified", "job_record_only", "legacy_unverified_digest"}):
        identity["status"] = "verified"
    else:
        identity["status"] = "unavailable"
    identity["identity_digest"] = _safe_digest({
        "fields": {key: identity[key] for key in VERIFICATION_IDENTITY_FIELDS},
        "availability": identity["availability"],
        "manifest_integrity": identity["manifest_integrity"]["status"],
        "issues": sorted(item["code"] for item in issues),
    })
    return identity


def verification_sample_set(directory, receipt) -> dict:
    """Frozen sample identity: file names plus the real SHA256 of every image."""
    receipt = receipt if isinstance(receipt, Mapping) else {}
    names = receipt.get("image_names") if isinstance(receipt.get("image_names"), list) else []
    rows = []
    for name in names[:64]:
        file_name = _clean(name)
        # The receipt is written by the platform, but never let a frozen sample
        # name become a path outside the verification directory.
        if (not file_name or file_name in {".", ".."} or "/" in file_name
                or "\\" in file_name or ":" in file_name):
            continue
        path = Path(directory) / "images" / file_name
        sha, present = _artifact_sha(path)
        rows.append({"name": file_name, "sha256": sha})
    available = bool(rows) and all(row["sha256"] for row in rows)
    return {
        "count": len(rows),
        "images": rows,
        "digest": _safe_digest(rows) if rows else "",
        "status": "available" if available else ("partial" if rows else "unavailable"),
    }


def verification_parameters(receipt, result=None) -> dict:
    """The frozen comparison parameters that make this evidence reproducible."""
    receipt = receipt if isinstance(receipt, Mapping) else {}
    result = result if isinstance(result, Mapping) else {}
    contract = result.get("input_contract") if isinstance(result.get("input_contract"), Mapping) else {}
    resolved = contract.get("resolved_input_shape") if isinstance(contract.get("resolved_input_shape"), list) else None
    frozen_imgsz = receipt.get("frozen_imgsz") if isinstance(receipt.get("frozen_imgsz"), list) else None
    if resolved and len(resolved) == 4:
        imgsz = [resolved[2], resolved[3]]
    else:
        imgsz = [int(value) for value in frozen_imgsz] if frozen_imgsz else None
    params = {
        "protocol": PROTOCOL,
        "precision": _clean(receipt.get("precision") or result.get("precision")),
        "imgsz": imgsz,
        "confidence": receipt.get("confidence"),
        "nms_iou": receipt.get("nms_iou"),
        "batch": receipt.get("frozen_batch") if type(receipt.get("frozen_batch")) is int else None,
        "input_color_order": _clean(receipt.get("input_color_order")),
        "input_shapes": receipt.get("input_shapes") if isinstance(receipt.get("input_shapes"), list) else None,
        "frozen_imgsz": [int(value) for value in frozen_imgsz] if frozen_imgsz else None,
        "preprocessing": dict(receipt.get("preprocessing")) if isinstance(receipt.get("preprocessing"), Mapping) else {},
        "label_codes_digest": _safe_digest(receipt.get("label_codes")) if isinstance(receipt.get("label_codes"), list) else "",
        "label_schema_digest": _safe_digest(receipt.get("label_schema")) if isinstance(receipt.get("label_schema"), list) else "",
        "source_kind": "PT",
        "compared_kind": "ONNX",
        "bmodel_expected": bool(receipt.get("bmodel_expected")),
    }
    # Additive contract fields participate in the immutable verification identity
    # only when the request carries them. Historical receipts keep their exact
    # old digest instead of being invalidated by an empty new key.
    for key in ("label_binding", "preprocessing_contract", "output_contract"):
        value = receipt.get(key)
        if isinstance(value, Mapping) and value:
            params[key] = dict(value)
    params["digest"] = _safe_digest({key: value for key, value in params.items() if key != "digest"})
    return params


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def verification_summary(result) -> dict:
    """Bounded, JSON-safe summary of the measured verdict (no fabricated metrics)."""
    result = result if isinstance(result, Mapping) else {}
    images = result.get("images") if isinstance(result.get("images"), list) else []
    rows = [row for row in images if isinstance(row, Mapping)]
    detections = [row.get("detection") for row in rows if isinstance(row.get("detection"), Mapping)]

    def numbers(key):
        return [value for value in (_finite(row.get(key)) for row in rows) if value is not None]

    def summed(key):
        values = [value for value in (row.get(key) for row in detections) if type(value) is int]
        return sum(values) if values else None

    normalized = numbers("normalized_mae")
    cosine = numbers("cosine_similarity")
    detection_ious = [value for value in (_finite(row.get("mean_matched_iou")) for row in detections)
                      if value is not None]
    coordinate_status = {}
    for row in detections:
        coordinates = row.get("original_coordinates") if isinstance(row.get("original_coordinates"), Mapping) else {}
        status = _clean(coordinates.get("status"))
        if status:
            coordinate_status[status] = coordinate_status.get(status, 0) + 1
    metrics = {
        "normalized_mae_max": max(normalized) if normalized else None,
        "cosine_similarity_min": min(cosine) if cosine else None,
        "max_abs_error_max": max(numbers("max_abs_error")) if numbers("max_abs_error") else None,
        "within_tolerance": (all(row.get("within_tolerance") is True for row in rows)
                             if rows and all(isinstance(row.get("within_tolerance"), bool) for row in rows)
                             else None),
    }
    detection = {
        "matched_pairs": summed("matched_pairs"),
        "unmatched_reference": summed("unmatched_reference"),
        "unmatched_converted": summed("unmatched_converted"),
        "threshold_crossings": summed("threshold_crossings"),
        "mean_matched_iou_min": min(detection_ious) if detection_ious else None,
        "original_coordinates_status": coordinate_status,
        "within_tolerance": (all(row.get("within_tolerance") is True for row in detections)
                             if detections and all(isinstance(row.get("within_tolerance"), bool) for row in detections)
                             else None),
    }
    if not detections:
        detection["status"] = "unavailable"
    contract = result.get("input_contract") if isinstance(result.get("input_contract"), Mapping) else {}
    rejection = result.get("rejection")
    runtime_versions = result.get("runtime_versions") if isinstance(result.get("runtime_versions"), Mapping) else {}
    return {
        "status": _clean(result.get("status")),
        "verdict": _clean(result.get("verdict") or "unavailable"),
        "raw_verdict": _clean(result.get("raw_verdict")),
        "detection_status": _clean(result.get("detection_status") or "unavailable"),
        "sample_count": result.get("sample_count") if type(result.get("sample_count")) is int else None,
        "rejection": dict(rejection) if isinstance(rejection, Mapping) else None,
        "error": str(result.get("error") or "")[:512],
        "label_identity_status": _clean((result.get("label_identity") or {}).get("status"))
        if isinstance(result.get("label_identity"), Mapping) else "",
        "input_contract": {
            "status": _clean(contract.get("status")),
            "code": _clean(contract.get("code")),
            "resolved_input_shape": contract.get("resolved_input_shape")
            if isinstance(contract.get("resolved_input_shape"), list) else None,
            "input_shape_source": _clean(contract.get("input_shape_source")),
        },
        "dynamic_resolution": _clean(result.get("dynamic_resolution")),
        "deployment_preprocessing_aligned": (result.get("deployment_preprocessing_aligned")
                                             if isinstance(result.get("deployment_preprocessing_aligned"), bool)
                                             else None),
        "bmodel": {
            "numeric_status": _clean(result.get("bmodel_numeric_status")),
            "detection_status": _clean(result.get("bmodel_detection_status")),
            "error": str(result.get("bmodel_numeric_error") or "")[:300],
        },
        "metrics": metrics,
        "detection": detection,
        "hardware_verified": result.get("hardware_verified") is True,
        "ground_truth_used": result.get("ground_truth_used") is True,
        "runtime_versions_digest": _safe_digest(runtime_versions) if runtime_versions else "",
    }


def build_verification_evidence(directory, receipt, result, *, identity=None, samples=None) -> dict:
    """Complete evidence document: identity + params + sample identity + summary."""
    directory = Path(directory)
    receipt = receipt if isinstance(receipt, Mapping) else {}
    result = result if isinstance(result, Mapping) else {}
    identity = identity if isinstance(identity, Mapping) else conversion_identity(directory, receipt)
    samples = samples if isinstance(samples, Mapping) else verification_sample_set(directory, receipt)
    parameters = verification_parameters(receipt, result)
    summary = verification_summary(result)
    verification_id = "nv_" + hashlib.sha256(canonical_json_bytes({
        "schema": EVIDENCE_SCHEMA,
        "identity": {key: identity.get(key) or "" for key in VERIFICATION_IDENTITY_FIELDS},
        "identity_digest": identity.get("identity_digest") or "",
        "parameters_digest": parameters.get("digest") or "",
        "sample_set_digest": samples.get("digest") or "",
    })).hexdigest()[:32]
    content = {
        "schema": EVIDENCE_SCHEMA,
        "verification_id": verification_id,
        "identity": {key: identity.get(key) for key in VERIFICATION_IDENTITY_FIELDS} | {
            "target_artifact_kind": _clean(identity.get("target_artifact_kind")),
            "manifest_integrity": dict(identity.get("manifest_integrity") or {}),
            "availability": dict(identity.get("availability") or {}),
            "missing": list(identity.get("missing") or []),
            "issues": list(identity.get("issues") or []),
            "job_record_status": _clean(identity.get("job_record_status")),
            "status": _clean(identity.get("status")),
            "identity_digest": _clean(identity.get("identity_digest")),
        },
        "parameters": parameters,
        "sample_set": samples,
        "result_summary": summary,
        "runtime_versions": dict(result.get("runtime_versions")) if isinstance(result.get("runtime_versions"), Mapping) else {},
    }
    content["content_digest"] = _safe_digest(content)
    # The caller-specific request pointer is mutable metadata, not part of the
    # deterministic identity+parameters evidence digest: two concurrent
    # requests for the same conversion identity must stay idempotent.
    content["request_verification_id"] = _clean(receipt.get("id"))
    content["request_id"] = _clean(receipt.get("request_id"))
    document = dict(result)
    document["schema"] = EVIDENCE_SCHEMA
    document["verification"] = content
    return document


def _evidence_store(directory):
    from platform_core.task_runtime import ArtifactStore
    directory = Path(directory).resolve()
    return ArtifactStore(directory.parent), directory.name


def _evidence_ref(directory, verification_id) -> str:
    return f"numeric-validations/{Path(directory).name}/{EVIDENCE_SUBDIRECTORY}/{verification_id}.json"


def persist_verification_evidence(directory, document) -> dict:
    """Atomically persist complete evidence before any mutable state is written.

    The evidence file is named by the deterministic verification id and is
    immutable: an existing same-name file must carry the same content digest or
    the publication fails closed (no silent overwrite, no evidence deletion).
    """
    directory = Path(directory).resolve()
    verification = document.get("verification") if isinstance(document.get("verification"), Mapping) else None
    if not isinstance(verification, Mapping):
        raise ValueError("VERIFICATION_EVIDENCE_INCOMPLETE: 缺少验证证据绑定")
    verification_id = _clean(verification.get("verification_id"))
    content_digest = _clean(verification.get("content_digest"))
    if not verification_id or not content_digest:
        raise ValueError("VERIFICATION_EVIDENCE_INCOMPLETE: 缺少确定性 verification_id 或 content_digest")
    store, task_id = _evidence_store(directory)
    relative = f"{EVIDENCE_SUBDIRECTORY}/{verification_id}.json"
    try:
        existing = store.read_json(task_id, relative, default=None)
    except (OSError, ValueError) as error:
        raise VerificationEvidenceConflict(
            f"{EVIDENCE_CONFLICT_CODE}: 同名证据无法读取，拒绝覆盖：{error}") from error
    if existing is not None:
        existing_verification = existing.get("verification") if isinstance(existing, dict) else None
        if (not isinstance(existing_verification, Mapping)
                or _clean(existing_verification.get("verification_id")) != verification_id
                or _clean(existing_verification.get("content_digest")) != content_digest):
            raise VerificationEvidenceConflict(
                f"{EVIDENCE_CONFLICT_CODE}: 同名证据已存在但内容不一致，拒绝覆盖")
        return existing
    document = dict(document)
    document["verification"] = dict(verification)
    document["verification"]["evidence_ref"] = _evidence_ref(directory, verification_id)
    store.atomic_write_json(task_id, relative, document)
    return document


def _write_result_json(directory, value) -> None:
    directory = Path(directory).resolve()
    try:
        store, task_id = _evidence_store(directory)
        store.atomic_write_json(task_id, "result.json", value)
    except ValueError:
        _write_json_atomic(directory / "result.json", value)


def _receipt_identity(receipt) -> dict:
    """Legacy fallback: only the fields the frozen request itself states."""
    receipt = receipt if isinstance(receipt, Mapping) else {}
    identity = {key: "" for key in VERIFICATION_IDENTITY_FIELDS}
    identity["project_id"] = _clean(receipt.get("project_id"))
    identity["conversion_job_id"] = _clean(receipt.get("conversion_job_id"))
    identity["source_pt_sha256"] = _clean(receipt.get("source_sha256")).lower()
    identity["onnx_sha256"] = _clean(receipt.get("onnx_sha256")).lower()
    identity["status"] = "unavailable"
    identity["identity_digest"] = ""
    identity["availability"] = {}
    identity["missing"] = [key for key in VERIFICATION_IDENTITY_FIELDS if not identity[key]]
    return identity


def compare_verification_identity(bound, current) -> dict:
    """Fail-closed comparison of bound evidence identity vs the current record.

    Stale means the current conversion record/product can no longer prove the
    identity the evidence was produced for (changed value, lost value, or a
    recorded conflict). A bound field that is explicitly unavailable does not
    claim verification; it is reported as ``unavailable`` instead.
    """
    bound = bound if isinstance(bound, Mapping) else {}
    current = current if isinstance(current, Mapping) else {}
    checks = {}
    reasons = []
    stale = False
    for key in VERIFICATION_IDENTITY_FIELDS:
        left = _clean(bound.get(key)).lower()
        right = _clean(current.get(key)).lower()
        if left and right:
            status = "match" if left == right else "changed"
            if status == "changed":
                stale = True
                reasons.append(f"{key} 已变化")
        elif left and not right:
            status = "current_unavailable"
            stale = True
            reasons.append(f"{key} 当前不可确认")
        elif not left and right:
            status = "bound_unavailable"
        else:
            status = "unavailable"
        checks[key] = {"bound": left, "current": right, "status": status}
    bound_status = _clean(bound.get("status"))
    current_status = _clean(current.get("status"))
    if bound_status == "conflict":
        stale = True
        reasons.append("证据绑定的转换身份存在冲突")
    if current_status == "conflict":
        stale = True
        reasons.append("当前转换记录/产物身份存在冲突")
    if stale:
        binding_status = "stale"
    elif bound_status == "verified" and current_status == "verified":
        binding_status = "verified"
    else:
        binding_status = "unavailable"
    return {
        "stale": stale,
        "code": STALE_VERIFICATION_CODE if stale else "",
        "reason": "；".join(dict.fromkeys(reasons))[:1000],
        "checks": checks,
        "binding_status": binding_status,
        "bound_identity_status": bound_status,
        "current_identity_status": current_status,
    }


def _legacy_verification_id(directory, receipt, result) -> str:
    """Deterministic id for a legacy result without an evidence binding."""
    payload = {
        "schema": EVIDENCE_SCHEMA,
        "request_directory": Path(directory).name,
        "parameters": verification_parameters(receipt, result),
        "summary": verification_summary(result),
    }
    return "nv_" + (_safe_digest(payload) or hashlib.sha256(
        json.dumps({"verdict": _clean(result.get("verdict"))}, ensure_ascii=False).encode("utf-8")).hexdigest())[:32]


def project_numeric_status(directory: Path, receipt: dict, result: dict) -> dict:
    """Project the quality summary into the existing conversion job JSON.

    Contract: the caller has already persisted the complete evidence. This only
    adds the existing ``numeric_status``/``publication_status`` JSON fields (and
    the bounded summary/reference) after re-verifying the current conversion
    identity under a file lock. Stale identities are never overwritten.
    """
    directory = Path(directory)
    receipt = receipt if isinstance(receipt, Mapping) else {}
    result = result if isinstance(result, Mapping) else {}
    job_id = _clean(receipt.get("conversion_job_id"))
    project_id = _clean(receipt.get("project_id"))
    if not job_id:
        return {"status": "skipped", "reason": "验证请求未冻结所属转换任务"}
    numeric_root = directory.parent
    if numeric_root.name != "numeric-validations":
        return {"status": "unavailable", "reason": "验证目录不在既有转换任务布局内，未写回状态"}
    job_path = numeric_root.parent / "jobs" / job_id / "job.json"
    if not job_path.is_file():
        return {"status": "unavailable", "reason": "所属转换任务记录不存在，未写回状态"}
    lock = FileLock(str(job_path) + ".lock", timeout=30, thread_local=False)
    try:
        with lock:
            return _project_numeric_status_locked(directory, receipt, result, job_path, job_id, project_id)
    except Timeout:
        return {"status": "unavailable", "reason": "转换记录写入锁超时，未写回状态（证据已保留）"}


def _project_numeric_status_locked(directory, receipt, result, job_path, job_id, project_id) -> dict:
    job = _json_read(job_path, None)
    if not isinstance(job, dict) or _clean(job.get("id")) != job_id:
        return {"status": "unavailable", "reason": "转换任务记录身份与验证请求不一致，拒绝写回"}
    if project_id and _clean(job.get("project_id")) != project_id:
        return {"status": "unavailable", "reason": "转换任务项目身份与验证请求不一致，拒绝写回"}
    current_identity = conversion_identity(directory, receipt)
    verification = result.get("verification") if isinstance(result.get("verification"), Mapping) else {}
    bound_identity = verification.get("identity") if isinstance(verification.get("identity"), Mapping) else None
    if not isinstance(bound_identity, Mapping):
        bound_identity = _receipt_identity(receipt)
    comparison = compare_verification_identity(bound_identity, current_identity)
    existing_numeric = job.get("numeric_validation") if isinstance(job.get("numeric_validation"), Mapping) else {}
    existing_id = _clean(existing_numeric.get("verification_id"))
    if comparison["stale"]:
        return {
            "status": "stale",
            "code": STALE_VERIFICATION_CODE,
            "reason": comparison["reason"] or "当前转换记录/产物身份已变化，拒绝覆盖已发布摘要",
            "job_id": job_id,
            "checks": comparison["checks"],
            "current_identity_status": comparison["current_identity_status"],
            "preserved_verification_id": existing_id,
            "evidence_preserved": True,
        }
    failed = _clean(result.get("status") or "completed") != "completed"
    verdict = "unavailable" if failed else _clean(result.get("verdict") or "not_comparable")
    numeric_status = NUMERIC_STATUS_BY_VERDICT.get(verdict, "unavailable")
    publication_status = PUBLICATION_STATUS_BY_NUMERIC[numeric_status]
    verification_id = _clean(verification.get("verification_id")) or _legacy_verification_id(directory, receipt, result)
    content_digest = _clean(verification.get("content_digest"))
    if existing_id and existing_id == verification_id:
        existing_digest = _clean(existing_numeric.get("content_digest"))
        if content_digest and existing_digest and existing_digest != content_digest:
            return {"status": "conflict", "code": EVIDENCE_CONFLICT_CODE,
                    "reason": "同一验证身份的已发布摘要内容不一致，拒绝覆盖",
                    "job_id": job_id, "verification_id": verification_id}
        return {"status": "already_projected", "job_id": job_id, "verification_id": verification_id,
                "numeric_status": _clean(job.get("numeric_status")),
                "publication_status": _clean(job.get("publication_status")),
                "result_ref": _clean(existing_numeric.get("result_ref"))}
    parameters = verification.get("parameters") if isinstance(verification.get("parameters"), Mapping) else {}
    sample_set = verification.get("sample_set") if isinstance(verification.get("sample_set"), Mapping) else {}
    summary = verification.get("result_summary") if isinstance(verification.get("result_summary"), Mapping) else {}
    bound_fields = {key: _clean(bound_identity.get(key)) for key in VERIFICATION_IDENTITY_FIELDS}
    identity_status = "verified" if comparison["binding_status"] == "verified" else "unavailable"
    numeric_validation = {
        "verification_id": verification_id,
        "request_verification_id": _clean(receipt.get("id") or Path(directory).name),
        "status": "failed" if failed else "completed",
        "verdict": verdict,
        "raw_verdict": _clean(result.get("raw_verdict")),
        "detection_status": _clean(result.get("detection_status")),
        "sample_count": result.get("sample_count") if type(result.get("sample_count")) is int else None,
        "protocol": _clean(result.get("protocol")),
        "precision": _clean(result.get("precision")),
        "hardware_verified": False,
        "ground_truth_used": False,
        "completed_at": _clean(result.get("completed_at") or datetime.now(timezone.utc).isoformat()),
        "result_ref": "numeric-validations/" + Path(directory).name + "/result.json",
        "evidence_ref": _clean(verification.get("evidence_ref") or _evidence_ref(directory, verification_id)),
        "content_digest": content_digest,
        "identity_digest": _clean(bound_identity.get("identity_digest")),
        "identity_status": identity_status,
        "binding_status": comparison["binding_status"],
        "identity": {**bound_fields,
                     "status": _clean(bound_identity.get("status")),
                     "missing": list(bound_identity.get("missing") or [])
                     if isinstance(bound_identity.get("missing"), list) else []},
        "parameters": dict(parameters),
        "sample_set": {
            "count": sample_set.get("count") if type(sample_set.get("count")) is int else None,
            "digest": _clean(sample_set.get("digest")),
            "status": _clean(sample_set.get("status")),
        },
        "summary": dict(summary),
        "superseded_verification_id": existing_id,
        "error": str(result.get("error") or "")[:512],
    }
    job.update({
        "numeric_status": numeric_status,
        "publication_status": publication_status,
        "numeric_validation": numeric_validation,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    _write_json_atomic(job_path, job)
    return {
        "status": "projected", "job_id": job_id,
        "numeric_status": numeric_status, "publication_status": publication_status,
        "verification_id": verification_id,
        "binding_status": comparison["binding_status"],
        "result_ref": numeric_validation["result_ref"],
        "evidence_ref": numeric_validation["evidence_ref"],
    }


def _publish_persisted_evidence(directory, request, previous) -> dict:
    """Re-attempt only the idempotent publication of already-persisted evidence."""
    document = persist_verification_evidence(directory, previous)
    projection = project_numeric_status(directory, request, document)
    final = dict(document)
    final["status_projection"] = projection
    final["progress"] = 100
    final["stage"] = _clean(previous.get("stage")) or "数值比较已完成"
    _write_result_json(directory, final)
    return final


def reconcile_numeric_verification(directory, result=None) -> dict:
    """Reconcile an already-finished verification after a crash/retry.

    Idempotent: completed evidence is never recomputed and the publication is
    only re-attempted. Used by the durable MODEL_CONVERSION recovery path so a
    process death between evidence persistence and status publication converges.
    """
    directory = Path(directory)
    document = dict(result) if isinstance(result, Mapping) else _json_read(directory / "result.json", None)
    if not isinstance(document, dict) or not document:
        return {}
    if _clean(document.get("status")) not in {"completed", "failed"}:
        return document
    request = _json_read(directory / "request.json", None)
    request = request if isinstance(request, Mapping) else {}
    if not isinstance(document.get("verification"), Mapping):
        # Legacy result: derive the binding it never had, then publish once.
        document = build_verification_evidence(directory, request, document)
        document = persist_verification_evidence(directory, document)
    return _publish_persisted_evidence(directory, request, document)


def run_verification_directory(directory: Path) -> dict:
    """Verify, persist complete evidence, then publish the bound summary.

    Ordering is the contract: the complete verifiable result (identity, frozen
    parameters, sample identity, bounded summary) is atomically durable through
    the ArtifactStore before the mutable conversion quality state is written, so
    a failure between the two steps can never leave a published status without
    evidence. A restarted worker only re-attempts the idempotent publication.
    """
    directory = Path(directory)
    request = _json_read(directory / "request.json", None)
    if not isinstance(request, Mapping):
        raise ValueError("数值验证请求无法读取")
    result_path = directory / "result.json"
    previous = _json_read(result_path, None)
    if (isinstance(previous, dict) and _clean(previous.get("status")) == "completed"
            and isinstance(previous.get("verification"), Mapping)):
        return _publish_persisted_evidence(directory, request, previous)

    def record(value):
        _write_json_atomic(result_path, value)

    def progress(done, total):
        record({"status": "running", "progress": round(100 * done / total, 2),
                "stage": f"正在比较 {done}/{total} 张图片"})

    record({"status": "running", "progress": 2, "stage": "加载 PT 和 ONNX 推理运行时"})
    frozen_identity = conversion_identity(directory, request)
    frozen_samples = verification_sample_set(directory, request)
    try:
        result = verify_images(
            Path(request["source_path"]), Path(request["onnx_path"]),
            [directory / "images" / name for name in request["image_names"]],
            precision=request["precision"], expected_source_sha=request.get("source_sha256", ""),
            expected_onnx_sha=request.get("onnx_sha256", ""),
            input_color_order=request.get("input_color_order", "rgb"),
            preprocessing=request.get("preprocessing"),
            label_codes=request.get("label_codes"),
            label_schema=request.get("label_schema"),
            label_binding=request.get("label_binding"),
            output_contract=request.get("output_contract"),
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
    except Exception as error:
        failure = {"status": "failed", "progress": 100, "stage": "验证无法完成", "error": str(error),
                   "verdict": "unavailable", "bmodel_verified": False, "hardware_verified": False,
                   "runtime_versions": runtime_versions(),
                   "completed_at": datetime.now(timezone.utc).isoformat()}
        document = build_verification_evidence(directory, request, failure,
                                               identity=frozen_identity, samples=frozen_samples)
        document = persist_verification_evidence(directory, document)
        try:
            projection = project_numeric_status(directory, request, document)
        except Exception as publication_error:
            _write_result_json(directory, {
                **document, "progress": 100,
                "status_projection": {"status": "failed",
                                      "reason": f"状态写回失败：{publication_error}"[:500]},
            })
            raise error
        _write_result_json(directory, {**document, "status_projection": projection, "progress": 100})
        raise
    document = build_verification_evidence(directory, request, result,
                                           identity=frozen_identity, samples=frozen_samples)
    document = persist_verification_evidence(directory, document)
    try:
        projection = project_numeric_status(directory, request, document)
    except Exception as error:
        # Evidence is already durable. Record the publication failure in the
        # mutable wrapper and let the caller retry publication only.
        _write_result_json(directory, {
            **document, "progress": 100, "stage": "数值比较已完成（状态待发布）",
            "status_projection": {"status": "failed", "reason": f"状态写回失败：{error}"[:500]},
        })
        raise
    final = {**document, "status_projection": projection, "progress": 100,
             "stage": "数值比较已完成"}
    _write_result_json(directory, final)
    return final


# ---------------------------------------------------------------------------
# N5.2: read-only delivery-quality eligibility for publish/activation preflight.
# This never mutates state, never re-runs inference and never trusts the mutable
# ``numeric_status`` summary alone: everything is recomputed from the immutable
# evidence file and the current conversion-identity owner.
# ---------------------------------------------------------------------------
ELIGIBILITY_SCHEMA = "delivery-quality-eligibility-v1"
ELIGIBILITY_CONTENT_KEYS = (
    "schema", "verification_id", "identity", "parameters", "sample_set",
    "result_summary", "runtime_versions",
)
_SAFE_EVIDENCE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}")


def evidence_path_from_ref(data_dir, evidence_ref) -> Path | None:
    """Resolve ``numeric-validations/<dir>/evidence/<id>.json`` under data_dir.

    Any absolute path, backslash, traversal segment, unknown shape or escaped
    target is rejected; the caller treats ``None`` as unavailable, never as a
    fallback to another evidence file.
    """
    raw = _clean(evidence_ref)
    if not raw or "\\" in raw:
        return None
    parts = raw.split("/")
    if len(parts) != 4 or parts[0] != "numeric-validations" or parts[2] != EVIDENCE_SUBDIRECTORY:
        return None
    if not all(_SAFE_EVIDENCE_TOKEN.fullmatch(part) and part not in {".", ".."}
               for part in (parts[1], parts[3])):
        return None
    if not parts[3].endswith(".json"):
        return None
    try:
        root = Path(data_dir).resolve()
        path = (root / raw).resolve()
    except (OSError, RuntimeError):
        return None
    if not path.is_relative_to(root):
        return None
    return path


def _eligibility_identity_digest(identity: Mapping) -> str:
    integrity = identity.get("manifest_integrity") if isinstance(identity.get("manifest_integrity"), Mapping) else {}
    issues = identity.get("issues") if isinstance(identity.get("issues"), list) else []
    return _safe_digest({
        "fields": {key: _clean(identity.get(key)) for key in VERIFICATION_IDENTITY_FIELDS},
        "availability": dict(identity.get("availability") or {}),
        "manifest_integrity": _clean(integrity.get("status")),
        "issues": sorted(str(item.get("code")) for item in issues if isinstance(item, Mapping)),
    })


def assert_delivery_quality_eligibility(directory, *, expected_identity=None) -> dict:
    """Fail-closed, read-only delivery-quality eligibility verdict.

    ``eligible`` is returned only when the immutable evidence file is readable,
    its recomputed content/identity/verification digests match, every identity
    field is present and still equals the current conversion record/artifact
    bytes, the frozen sample set is unchanged, the frozen summary is an
    interpretable ``consistent`` PT/ONNX verdict, and the conversion record's
    published summary (when present) is bound to exactly this verification.

    When the bound deliverable is a compiled BMODEL (``bmodel_expected`` or a
    ``sophon``/``bmodel`` target artifact), the frozen ONNX-vs-BMODEL numeric and
    detection verdicts are part of the contract too: `unavailable` or
    `difference_detected` refuses formal delivery with
    ``BMODEL_EVIDENCE_NOT_ELIGIBLE``. The recorded PT/ONNX metrics, the evidence
    file and the artifact stay readable/downloadable; only the formal claim is
    refused, and re-running the verification where the official offline BMODEL
    runner is available is the recovery path.

    A ``numeric_status == "consistent"`` field on its own never influences the
    verdict: the function does not read that mutable field as evidence.
    """
    directory = Path(directory)
    verdict: dict = {
        "schema": ELIGIBILITY_SCHEMA,
        "eligible": False,
        "code": "",
        "reasons": [],
        "directory": "",
        "verification_id": "",
        "evidence_ref": "",
        "evidence_status": "unavailable",
        "evidence_digest_verified": False,
        "identity_status": "unavailable",
        "current_identity_status": "unavailable",
        "binding_status": "unavailable",
        "identity_complete": False,
        "missing_identity_fields": [],
        "sample_set_status": "unavailable",
        "projection_status": "missing",
        "numeric_status": "unavailable",
        "numeric_status_sufficient_for_eligibility": False,
        "verdict": "unavailable",
        "raw_verdict": "",
        "detection_status": "unavailable",
        "bmodel_required": False,
        "bmodel": {"numeric_status": "", "detection_status": "", "error": ""},
        "sample_count": None,
        "label_identity_status": "unknown",
        "label_contract_required": False,
        "hardware_verified": False,
        "ground_truth_used": False,
        "source_pt_sha256": "",
        "onnx_sha256": "",
        "target_artifact_sha256": "",
        "manifest_digest": "",
        "content_digest": "",
        "identity_digest": "",
        "evidence": {},
    }

    def refuse(code: str, reason: str, **extra) -> dict:
        verdict.update(extra)
        verdict["code"] = code
        verdict["reasons"].append(str(reason)[:500])
        return dict(verdict)

    try:
        resolved = directory.resolve()
    except (OSError, RuntimeError):
        return refuse("EVIDENCE_DIRECTORY_INVALID", "验证目录不可解析")
    verdict["directory"] = str(resolved)
    if resolved.parent.name != "numeric-validations":
        return refuse("EVIDENCE_DIRECTORY_INVALID", "验证目录不在既有 numeric-validations 布局内")
    request = _json_read(resolved / "request.json", None)
    if not isinstance(request, Mapping):
        return refuse("EVIDENCE_REQUEST_UNREADABLE", "冻结验证请求不可读取")
    result = _json_read(resolved / "result.json", None)
    if not isinstance(result, Mapping) or _clean(result.get("status")) != "completed":
        return refuse("EVIDENCE_RESULT_UNAVAILABLE", "验证结果未完成或不可读取")
    wrapper = result.get("verification") if isinstance(result.get("verification"), Mapping) else None
    if not isinstance(wrapper, Mapping):
        return refuse("EVIDENCE_BINDING_MISSING", "结果缺少不可变证据绑定，不能作为交付资格")
    verification_id = _clean(wrapper.get("verification_id"))
    if not _SAFE_EVIDENCE_TOKEN.fullmatch(verification_id):
        return refuse("EVIDENCE_ID_INVALID", "证据 verification_id 格式非法")
    verdict["verification_id"] = verification_id
    data_dir = resolved.parent.parent
    evidence_ref = _clean(wrapper.get("evidence_ref")) or _evidence_ref(resolved, verification_id)
    verdict["evidence_ref"] = evidence_ref
    path = evidence_path_from_ref(data_dir, evidence_ref)
    if path is None:
        return refuse("EVIDENCE_REF_UNSAFE", "证据引用路径越界或格式非法")
    if not path.is_file():
        return refuse("EVIDENCE_REF_UNREADABLE", "证据引用文件不存在")
    document = _json_read(path, None)
    stored = document.get("verification") if isinstance(document, Mapping) else None
    if not isinstance(stored, Mapping):
        return refuse("EVIDENCE_REF_UNREADABLE", "证据文件损坏或缺少 verification 块")
    if _clean(stored.get("schema")) != EVIDENCE_SCHEMA:
        return refuse("EVIDENCE_SCHEMA_UNSUPPORTED", "证据 schema 不受支持")
    if _clean(stored.get("verification_id")) != verification_id:
        return refuse("EVIDENCE_ID_MISMATCH", "证据文件身份与结果绑定不一致")
    content = {key: stored.get(key) for key in ELIGIBILITY_CONTENT_KEYS}
    content_digest = _safe_digest(content)
    if not content_digest or content_digest != _clean(stored.get("content_digest")):
        return refuse("EVIDENCE_DIGEST_MISMATCH", "证据内容摘要重算不一致（文件损坏或被修改）")
    verdict.update(content_digest=content_digest, evidence_status="readable",
                   evidence_digest_verified=True)
    if _clean(wrapper.get("content_digest")) and _clean(wrapper.get("content_digest")) != content_digest:
        return refuse("EVIDENCE_RESULT_MISMATCH", "结果包装内容摘要与证据文件不一致")
    identity = stored.get("identity") if isinstance(stored.get("identity"), Mapping) else {}
    verdict["evidence"] = {
        "schema": EVIDENCE_SCHEMA,
        "verification_id": verification_id,
        "content_digest": content_digest,
        "identity_status": _clean(identity.get("status")),
        "verdict": _clean((stored.get("result_summary") or {}).get("verdict"))
        if isinstance(stored.get("result_summary"), Mapping) else "",
    }
    missing = [key for key in VERIFICATION_IDENTITY_FIELDS if not _clean(identity.get(key))]
    verdict["missing_identity_fields"] = missing
    if missing:
        return refuse("IDENTITY_INCOMPLETE", "验证证据身份字段不完整：" + ", ".join(missing))
    verdict["identity_complete"] = True
    identity_digest = _eligibility_identity_digest(identity)
    if not identity_digest or identity_digest != _clean(identity.get("identity_digest")):
        return refuse("IDENTITY_DIGEST_MISMATCH", "证据身份摘要重算不一致")
    verdict["identity_digest"] = identity_digest
    parameters = stored.get("parameters") if isinstance(stored.get("parameters"), Mapping) else {}
    samples = stored.get("sample_set") if isinstance(stored.get("sample_set"), Mapping) else {}
    expected_verification_id = "nv_" + hashlib.sha256(canonical_json_bytes({
        "schema": EVIDENCE_SCHEMA,
        "identity": {key: _clean(identity.get(key)) for key in VERIFICATION_IDENTITY_FIELDS},
        "identity_digest": identity_digest,
        "parameters_digest": _clean(parameters.get("digest")),
        "sample_set_digest": _clean(samples.get("digest")),
    })).hexdigest()[:32]
    if expected_verification_id != verification_id:
        return refuse("EVIDENCE_ID_MISMATCH", "证据确定性身份重算不一致")
    current_identity = conversion_identity(resolved, request)
    comparison = compare_verification_identity(identity, current_identity)
    verdict.update(
        identity_status=_clean(identity.get("status")),
        current_identity_status=_clean(current_identity.get("status")),
        binding_status=comparison["binding_status"],
        source_pt_sha256=_clean(identity.get("source_pt_sha256")),
        onnx_sha256=_clean(identity.get("onnx_sha256")),
        target_artifact_sha256=_clean(identity.get("target_artifact_sha256")),
        manifest_digest=_clean(identity.get("manifest_digest")),
    )
    if comparison["stale"]:
        return refuse(STALE_VERIFICATION_CODE, comparison["reason"] or "当前转换记录/产物身份已变化")
    if comparison["binding_status"] != "verified":
        return refuse("EVIDENCE_IDENTITY_UNVERIFIED", "证据身份与当前转换记录不能证明为同一身份")
    if isinstance(expected_identity, Mapping):
        mismatch = [
            key for key in VERIFICATION_IDENTITY_FIELDS
            if _clean(expected_identity.get(key))
            and _clean(expected_identity.get(key)).lower() != _clean(identity.get(key)).lower()
        ]
        if mismatch:
            return refuse("IDENTITY_EXPECTATION_MISMATCH",
                          "证据身份与预检期望身份不一致：" + ", ".join(mismatch))
    samples_now = verification_sample_set(resolved, request)
    verdict["sample_set_status"] = _clean(samples_now.get("status"))
    if (_clean(samples.get("status")) != "available" or not _clean(samples.get("digest"))
            or _clean(samples_now.get("status")) != "available"
            or _clean(samples_now.get("digest")) != _clean(samples.get("digest"))):
        return refuse("EVIDENCE_SAMPLE_SET_CHANGED", "验证样本集摘要与当前冻结样本不一致或不可用")
    summary = stored.get("result_summary") if isinstance(stored.get("result_summary"), Mapping) else {}
    metrics = summary.get("metrics") if isinstance(summary.get("metrics"), Mapping) else {}
    detection = summary.get("detection") if isinstance(summary.get("detection"), Mapping) else {}
    bmodel = summary.get("bmodel") if isinstance(summary.get("bmodel"), Mapping) else {}
    label_status = _clean(summary.get("label_identity_status"))
    label_contract_required = bool(
        request.get("label_codes") or request.get("label_schema")
        or request.get("label_binding")
    )
    observed_verdict = _clean(summary.get("verdict"))
    observed_detection = _clean(summary.get("detection_status"))
    sample_count = summary.get("sample_count")
    # A compiled BMODEL is its own deliverable. The receipt/identity already
    # freeze whether one was expected, so delivery admission can require its
    # recorded comparison instead of silently treating PT/ONNX agreement as the
    # BMODEL's proof.
    bmodel_required = (
        parameters.get("bmodel_expected") is True
        or _clean(identity.get("target_artifact_kind")).lower() in {"sophon", "bmodel"}
    )
    verdict.update(
        verdict=observed_verdict or "unavailable",
        raw_verdict=_clean(summary.get("raw_verdict")),
        detection_status=observed_detection or "unavailable",
        bmodel_required=bmodel_required,
        bmodel={
            "numeric_status": _clean(bmodel.get("numeric_status")),
            "detection_status": _clean(bmodel.get("detection_status")),
            "error": str(bmodel.get("error") or "")[:300],
        },
        sample_count=sample_count if type(sample_count) is int else None,
        label_identity_status=label_status or "unknown",
        label_contract_required=label_contract_required,
        hardware_verified=summary.get("hardware_verified") is True,
        ground_truth_used=summary.get("ground_truth_used") is True,
    )
    failures: list[tuple[str, str]] = []
    if _clean(summary.get("status")) != "completed":
        failures.append(("VERDICT_STATUS_UNAVAILABLE", "冻结摘要状态不是 completed"))
    if observed_verdict not in NUMERIC_STATUS_BY_VERDICT:
        failures.append(("VERDICT_UNEXPLAINABLE", f"未知数值结论：{observed_verdict or '<empty>'}"))
    elif observed_verdict != "consistent":
        failures.append(("NUMERIC_VERDICT_NOT_ELIGIBLE", f"冻结数值结论不是 consistent：{observed_verdict}"))
    if _clean(summary.get("raw_verdict")) != "consistent":
        failures.append(("RAW_VERDICT_NOT_ELIGIBLE", "原始张量结论不是 consistent"))
    if observed_detection != "consistent":
        failures.append(("DETECTION_VERDICT_NOT_ELIGIBLE", "检测结果结论不是 consistent"))
    if metrics.get("within_tolerance") is not True:
        failures.append(("TENSOR_TOLERANCE_UNAVAILABLE", "冻结张量指标未证明在容差内"))
    if detection.get("within_tolerance") is not True:
        failures.append(("DETECTION_TOLERANCE_UNAVAILABLE", "冻结检测指标未证明在容差内"))
    if bmodel_required:
        bmodel_numeric = _clean(bmodel.get("numeric_status"))
        bmodel_detection = _clean(bmodel.get("detection_status"))
        if bmodel_numeric != "consistent" or bmodel_detection != "consistent":
            failures.append((
                BMODEL_EVIDENCE_NOT_ELIGIBLE_CODE,
                "该转换为 BMODEL 交付物，但 ONNX/BMODEL 数值或检测证据不是 consistent"
                f"（numeric={bmodel_numeric or '<empty>'}, detection={bmodel_detection or '<empty>'}）；"
                "PT/ONNX 一致不能代替 BMODEL 自身的比较证据",
            ))
    if type(sample_count) is not int or sample_count < 1:
        failures.append(("SAMPLE_COUNT_UNAVAILABLE", "冻结样本数为空或非法"))
    if summary.get("rejection") not in (None, {}):
        failures.append(("VERDICT_REJECTED", "冻结结论包含不可比拒绝原因"))
    if _clean(summary.get("label_identity_status")) in {"conflict", "mismatch"}:
        failures.append(("LABEL_IDENTITY_CONFLICT", "冻结标签身份冲突"))
    if label_contract_required and label_status != "verified":
        failures.append((
            "LABEL_IDENTITY_UNVERIFIED",
            "该转换冻结了类别合同，但验证证据未证明类别顺序/code 与源模型一致"
            f"（status={label_status or 'unknown'}）；类别 unknown 不能表述为验证通过",
        ))
    if summary.get("deployment_preprocessing_aligned") is not True:
        failures.append(("PREPROCESSING_ALIGNMENT_UNVERIFIED", "部署前处理未证明与比较合同一致"))
    if failures:
        verdict["reasons"].extend(reason for _, reason in failures)
        verdict["code"] = failures[0][0]
        verdict["failure_codes"] = [code for code, _ in failures]
        return dict(verdict)
    # The conversion record's published summary is the mutable projection of the
    # evidence. When present it must be bound to exactly this verification id and
    # content digest; a different (newer) summary means this evidence is not the
    # one delivery would be declaring.
    job_path = _conversion_job_path(resolved, _clean(identity.get("conversion_job_id")))
    job = _json_read(job_path, None) if job_path is not None else None
    projection = job.get("numeric_validation") if isinstance(job, Mapping) else None
    if isinstance(projection, Mapping):
        bound_id = _clean(projection.get("verification_id"))
        bound_digest = _clean(projection.get("content_digest"))
        if bound_id != verification_id or bound_digest != content_digest:
            return refuse(
                "PROJECTION_BINDING_MISMATCH",
                "转换记录当前数值摘要绑定了其他验证身份，不能把本证据用于正式交付",
            )
        if _clean(projection.get("identity_digest")) and \
                _clean(projection.get("identity_digest")) != identity_digest:
            return refuse("PROJECTION_IDENTITY_MISMATCH", "转换记录摘要的身份摘要与本证据不一致")
        if _clean(projection.get("verdict")) != observed_verdict:
            return refuse("PROJECTION_VERDICT_MISMATCH", "转换记录摘要结论与本证据不一致")
        if projection.get("status") != "completed":
            return refuse("PROJECTION_INCOMPLETE", "转换记录摘要不是 completed")
        verdict["projection_status"] = "bound"
    verdict.update(eligible=True, code="", numeric_status="consistent")
    return dict(verdict)
