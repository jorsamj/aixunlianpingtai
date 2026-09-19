from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from PIL import Image

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
_DEFAULT_IOUS = tuple(round(0.5 + index * 0.05, 2) for index in range(10))
EVALUATION_SCHEMA_VERSION = 1
_EVALUATION_METRICS = (
    "metrics/precision(B)",
    "metrics/recall(B)",
    "metrics/mAP50(B)",
    "metrics/mAP50-95(B)",
)


def _sha256_identity(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    if text and (len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text)):
        raise ValueError(f"{field} must be a SHA256 hex digest")
    return text


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _label_name(names: Mapping[int | str, str] | Sequence[str] | None, class_id: int) -> str:
    if isinstance(names, Mapping):
        return str(names.get(class_id, names.get(str(class_id), str(class_id))))
    if isinstance(names, Sequence) and not isinstance(names, (str, bytes)) and class_id < len(names):
        return str(names[class_id])
    return str(class_id)


def _iou(a: Sequence[float], b: Sequence[float]) -> float:
    x1 = max(float(a[0]), float(b[0]))
    y1 = max(float(a[1]), float(b[1]))
    x2 = min(float(a[2]), float(b[2]))
    y2 = min(float(a[3]), float(b[3]))
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, float(a[2]) - float(a[0])) * max(0.0, float(a[3]) - float(a[1]))
    area_b = max(0.0, float(b[2]) - float(b[0])) * max(0.0, float(b[3]) - float(b[1]))
    return inter / max(1e-12, area_a + area_b - inter)


def _read_ground_truth(path: Path, width: int, height: int, image_name: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"hidden blind-test ground truth is missing: {path.name}")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        class_id = int(float(parts[0]))
        cx, cy, bw, bh = map(float, parts[1:5])
        rows.append(
            {
                "image": image_name,
                "class_id": class_id,
                "box": [
                    (cx - bw / 2) * width,
                    (cy - bh / 2) * height,
                    (cx + bw / 2) * width,
                    (cy + bh / 2) * height,
                ],
            }
        )
    return rows


def _normalize_prediction(image_name: str, value: Mapping[str, Any]) -> dict[str, Any]:
    box = value.get("box") or value.get("xyxy")
    if not isinstance(box, (list, tuple)) or len(box) < 4:
        raise ValueError("blind test prediction requires an xyxy box")
    return {
        "image": image_name,
        "class_id": int(value.get("class_id", value.get("cls", 0))),
        "confidence": float(value.get("confidence", value.get("conf", 0.0))),
        "box": [float(box[0]), float(box[1]), float(box[2]), float(box[3])],
    }


def _match_flags(predictions: Sequence[Mapping[str, Any]], targets: Sequence[Mapping[str, Any]], iou_threshold: float) -> list[bool]:
    by_image: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for target in targets:
        by_image[str(target["image"])].append(target)
    used: dict[str, set[int]] = defaultdict(set)
    flags: list[bool] = []
    for prediction in predictions:
        image = str(prediction["image"])
        candidates = by_image.get(image, [])
        best_index = -1
        best_iou = -1.0
        for index, target in enumerate(candidates):
            if index in used[image]:
                continue
            overlap = _iou(prediction["box"], target["box"])
            if overlap >= iou_threshold and overlap > best_iou:
                best_iou = overlap
                best_index = index
        matched = best_index >= 0
        if matched:
            used[image].add(best_index)
        flags.append(matched)
    return flags


def _average_precision(flags: Sequence[bool], target_count: int) -> float:
    if target_count <= 0:
        return 0.0
    if not flags:
        return 0.0
    tp = 0
    fp = 0
    recalls: list[float] = []
    precisions: list[float] = []
    for matched in flags:
        if matched:
            tp += 1
        else:
            fp += 1
        recalls.append(tp / target_count)
        precisions.append(tp / max(1, tp + fp))
    values = []
    for index in range(101):
        recall_level = index / 100
        values.append(max((p for r, p in zip(recalls, precisions) if r >= recall_level), default=0.0))
    return sum(values) / len(values)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def evaluate_blind_detection(
    test_images_dir: str | Path,
    ground_truth_dir: str | Path,
    predict: Callable[[Path], Sequence[Mapping[str, Any]]],
    *,
    names: Mapping[int | str, str] | Sequence[str] | None = None,
    operating_conf: float = 0.25,
    iou_thresholds: Sequence[float] = _DEFAULT_IOUS,
) -> dict[str, Any]:
    """Run image-only inference first, then score against hidden YOLO ground truth.

    `predict` receives only an image path. Ground-truth files are not opened until
    prediction collection for every test image has finished.
    """
    image_root = Path(test_images_dir).resolve()
    ground_truth_root = Path(ground_truth_dir).resolve()
    images = [path for path in sorted(image_root.iterdir()) if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES] if image_root.is_dir() else []
    if not images:
        return {
            "status": "not_requested",
            "metrics": {},
            "per_class": [],
            "weak_labels": [],
            "error_samples": [],
            "error_sample_count": 0,
            "protocol": {"mode": "blind_image_only_inference_then_hidden_ground_truth_scoring"},
            "image_count": 0,
        }

    predictions: list[dict[str, Any]] = []
    dimensions: dict[str, tuple[int, int]] = {}
    for image_path in images:
        with Image.open(image_path) as image:
            dimensions[image_path.name] = (int(image.width), int(image.height))
        for value in predict(image_path) or ():
            predictions.append(_normalize_prediction(image_path.name, value))

    # Deliberate phase boundary: only the scorer reads the hidden answers.
    targets: list[dict[str, Any]] = []
    for image_path in images:
        width, height = dimensions[image_path.name]
        targets.extend(
            _read_ground_truth(
                ground_truth_root / f"{image_path.stem}.txt",
                width,
                height,
                image_path.name,
            )
        )

    class_ids = sorted({int(row["class_id"]) for row in targets} | {int(row["class_id"]) for row in predictions})
    per_class: list[dict[str, Any]] = []
    thresholds = tuple(float(value) for value in iou_thresholds) or _DEFAULT_IOUS
    for class_id in class_ids:
        class_targets = [row for row in targets if int(row["class_id"]) == class_id]
        class_predictions = sorted(
            (row for row in predictions if int(row["class_id"]) == class_id),
            key=lambda row: float(row["confidence"]),
            reverse=True,
        )
        aps = [_average_precision(_match_flags(class_predictions, class_targets, threshold), len(class_targets)) for threshold in thresholds]
        operating = [row for row in class_predictions if float(row["confidence"]) >= float(operating_conf)]
        operating_flags = _match_flags(operating, class_targets, 0.5)
        true_positive = sum(1 for value in operating_flags if value)
        false_positive = max(0, len(operating) - true_positive)
        false_negative = max(0, len(class_targets) - true_positive)
        precision = true_positive / len(operating) if operating else 0.0
        recall = true_positive / len(class_targets) if class_targets else 0.0
        per_class.append(
            {
                "class_id": class_id,
                "label": _label_name(names, class_id),
                "precision": round(precision, 6),
                "recall": round(recall, 6),
                "map50": round(aps[0] if aps else 0.0, 6),
                "map50_95": round(_mean(aps), 6),
                "true_positive": true_positive,
                "false_positive": false_positive,
                "false_negative": false_negative,
                "ground_truth_count": len(class_targets),
                "prediction_count": len(class_predictions),
                "operating_prediction_count": len(operating),
            }
        )

    scored = [row for row in per_class if int(row["ground_truth_count"]) > 0]
    metrics = {
        "metrics/precision(B)": round(_mean([float(row["precision"]) for row in scored]), 6),
        "metrics/recall(B)": round(_mean([float(row["recall"]) for row in scored]), 6),
        "metrics/mAP50(B)": round(_mean([float(row["map50"]) for row in scored]), 6),
        "metrics/mAP50-95(B)": round(_mean([float(row["map50_95"]) for row in scored]), 6),
    }
    error_samples: list[dict[str, Any]] = []
    operating_predictions = [
        row for row in predictions if float(row["confidence"]) >= float(operating_conf)
    ]
    predictions_by_image: dict[str, list[dict[str, Any]]] = defaultdict(list)
    targets_by_image: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in operating_predictions:
        predictions_by_image[str(row["image"])].append(row)
    for row in targets:
        targets_by_image[str(row["image"])].append(row)
    for image_path in images:
        image_name = image_path.name
        image_predictions = predictions_by_image.get(image_name, [])
        image_targets = targets_by_image.get(image_name, [])
        pairs = []
        for prediction_index, prediction in enumerate(image_predictions):
            for target_index, target in enumerate(image_targets):
                if int(prediction["class_id"]) != int(target["class_id"]):
                    continue
                overlap = _iou(prediction["box"], target["box"])
                if overlap >= 0.5:
                    pairs.append((overlap, prediction_index, target_index))
        matched_predictions: set[int] = set()
        matched_targets: set[int] = set()
        for _overlap, prediction_index, target_index in sorted(pairs, reverse=True):
            if prediction_index in matched_predictions or target_index in matched_targets:
                continue
            matched_predictions.add(prediction_index)
            matched_targets.add(target_index)
        fp = [row for index, row in enumerate(image_predictions) if index not in matched_predictions]
        fn = [row for index, row in enumerate(image_targets) if index not in matched_targets]
        if fp or fn:
            error_samples.append({
                "image": image_name,
                "fp_count": len(fp),
                "fn_count": len(fn),
                "fp_labels": sorted({_label_name(names, int(row["class_id"])) for row in fp}),
                "fn_labels": sorted({_label_name(names, int(row["class_id"])) for row in fn}),
            })
        if len(error_samples) >= 200:
            break

    weak_label_threshold = 0.75
    weak_labels = [
        str(row["label"])
        for row in sorted(per_class, key=lambda row: (float(row["recall"]), float(row["map50"])))
        if int(row["ground_truth_count"]) > 0
        and (float(row["recall"]) < weak_label_threshold or float(row["map50"]) < weak_label_threshold)
    ]
    return {
        "status": "succeeded",
        "metrics": metrics,
        "per_class": per_class,
        "weak_labels": weak_labels[:100],
        "error_samples": error_samples,
        "error_sample_count": len(error_samples),
        "image_count": len(images),
        "ground_truth_box_count": len(targets),
        "prediction_box_count": len(predictions),
        "protocol": {
            "mode": "blind_image_only_inference_then_hidden_ground_truth_scoring",
            "operating_conf": float(operating_conf),
            "iou_thresholds": list(thresholds),
            "matching_iou": 0.5,
            "weak_label_threshold": weak_label_threshold,
        },
    }


def build_evaluation_truth(
    result: Mapping[str, Any] | None,
    *,
    task_id: Any,
    snapshot_id: Any = "",
    dataset_revision_id: Any = "",
    model_sha256: Any = "",
    finished_at: Any = "",
) -> dict[str, Any]:
    """Normalize one post-training blind-test result into version-owned truth."""
    raw = dict(result) if isinstance(result, Mapping) else {}
    status = str(raw.get("status") or "not_requested").strip().lower()
    # Result schema v1 stores one canonical success value. "passed" is the
    # pre-v1 training-result spelling still present in durable historical jobs.
    if status == "passed":
        status = "succeeded"
    if status not in {"succeeded", "not_requested", "failed"}:
        raise ValueError("evaluation status is invalid")
    task = str(task_id or "").strip()
    if not task:
        raise ValueError("evaluation requires task_id")
    revision = _sha256_identity(dataset_revision_id, "dataset_revision_id")
    model_digest = _sha256_identity(model_sha256, "model_sha256")
    raw_metrics = raw.get("metrics") if isinstance(raw.get("metrics"), Mapping) else {}
    metrics = {
        key: round(_finite(raw_metrics.get(key)), 6)
        for key in _EVALUATION_METRICS if raw_metrics.get(key) is not None
    }
    per_class = []
    for row in list(raw.get("per_class") or [])[:10000]:
        if not isinstance(row, Mapping):
            continue
        per_class.append({
            "class_id": int(row.get("class_id") or 0),
            "label": str(row.get("label") or "")[:1000],
            "precision": round(_finite(row.get("precision")), 6),
            "recall": round(_finite(row.get("recall")), 6),
            "map50": round(_finite(row.get("map50")), 6),
            "map50_95": round(_finite(row.get("map50_95")), 6),
            "true_positive": max(0, int(row.get("true_positive") or 0)),
            "false_positive": max(0, int(row.get("false_positive") or 0)),
            "false_negative": max(0, int(row.get("false_negative") or 0)),
            "ground_truth_count": max(0, int(row.get("ground_truth_count") or 0)),
            "prediction_count": max(0, int(row.get("prediction_count") or 0)),
        })
    weak_labels = [str(value)[:1000] for value in list(raw.get("weak_labels") or [])[:100] if str(value or "").strip()]
    error_samples = []
    for row in list(raw.get("error_samples") or [])[:200]:
        if not isinstance(row, Mapping):
            continue
        error_samples.append({
            "image": Path(str(row.get("image") or "")).name[:240],
            "fp_count": max(0, int(row.get("fp_count") or 0)),
            "fn_count": max(0, int(row.get("fn_count") or 0)),
            "fp_labels": [str(value)[:1000] for value in list(row.get("fp_labels") or [])[:100]],
            "fn_labels": [str(value)[:1000] for value in list(row.get("fn_labels") or [])[:100]],
        })
    protocol_raw = raw.get("protocol") if isinstance(raw.get("protocol"), Mapping) else {}
    protocol = {
        "mode": str(protocol_raw.get("mode") or "")[:200],
        "operating_conf": round(_finite(protocol_raw.get("operating_conf")), 6),
        "matching_iou": round(_finite(protocol_raw.get("matching_iou"), 0.5), 6),
        "weak_label_threshold": round(_finite(protocol_raw.get("weak_label_threshold"), 0.75), 6),
        "iou_thresholds": [round(_finite(value), 6) for value in list(protocol_raw.get("iou_thresholds") or [])[:20]],
    }
    identity = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "status": status,
        "task_id": task,
        "snapshot_id": str(snapshot_id or "").strip(),
        "dataset_revision_id": revision,
        "model_sha256": model_digest,
        "metrics": metrics,
        "per_class": per_class,
        "weak_labels": weak_labels,
        "error_samples": error_samples,
        "image_count": max(0, int(raw.get("image_count") or 0)),
        "ground_truth_box_count": max(0, int(raw.get("ground_truth_box_count") or 0)),
        "prediction_box_count": max(0, int(raw.get("prediction_box_count") or 0)),
        "protocol": protocol,
    }
    evaluation_id = hashlib.sha256(json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return {
        **identity,
        "evaluation_id": evaluation_id,
        "finished_at": str(finished_at or "").strip(),
        "failure_reason": "evaluation_failed" if status == "failed" else "",
    }
