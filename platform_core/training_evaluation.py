from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from PIL import Image

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
_DEFAULT_IOUS = tuple(round(0.5 + index * 0.05, 2) for index in range(10))


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
        precision = true_positive / len(operating) if operating else 0.0
        recall = true_positive / len(class_targets) if class_targets else 0.0
        if isinstance(names, Mapping):
            label = names.get(class_id, names.get(str(class_id), str(class_id)))
        elif isinstance(names, Sequence) and not isinstance(names, (str, bytes)) and class_id < len(names):
            label = names[class_id]
        else:
            label = str(class_id)
        per_class.append(
            {
                "class_id": class_id,
                "label": str(label),
                "precision": round(precision, 6),
                "recall": round(recall, 6),
                "map50": round(aps[0] if aps else 0.0, 6),
                "map50_95": round(_mean(aps), 6),
                "ground_truth_count": len(class_targets),
                "prediction_count": len(class_predictions),
            }
        )

    scored = [row for row in per_class if int(row["ground_truth_count"]) > 0]
    metrics = {
        "metrics/precision(B)": round(_mean([float(row["precision"]) for row in scored]), 6),
        "metrics/recall(B)": round(_mean([float(row["recall"]) for row in scored]), 6),
        "metrics/mAP50(B)": round(_mean([float(row["map50"]) for row in scored]), 6),
        "metrics/mAP50-95(B)": round(_mean([float(row["map50_95"]) for row in scored]), 6),
    }
    return {
        "status": "succeeded",
        "metrics": metrics,
        "per_class": per_class,
        "image_count": len(images),
        "ground_truth_box_count": len(targets),
        "prediction_box_count": len(predictions),
        "protocol": {
            "mode": "blind_image_only_inference_then_hidden_ground_truth_scoring",
            "operating_conf": float(operating_conf),
            "iou_thresholds": list(thresholds),
        },
    }
