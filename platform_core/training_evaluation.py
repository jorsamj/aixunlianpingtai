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
EVALUATION_BENCHMARK_SCOPE_SCHEMA_VERSION = 1
EVALUATION_PROTOCOL_SCHEMA_VERSION = 1
ITERATION_DECISION_SCHEMA_VERSION = 1
_EVALUATION_METRICS = (
    "metrics/precision(B)",
    "metrics/recall(B)",
    "metrics/mAP50(B)",
    "metrics/mAP50-95(B)",
)
_DECISION_METRIC_KEYS = {
    "map50": "metrics/mAP50(B)",
    "map50-95": "metrics/mAP50-95(B)",
    "map50_95": "metrics/mAP50-95(B)",
    "map5095": "metrics/mAP50-95(B)",
    "precision": "metrics/precision(B)",
    "recall": "metrics/recall(B)",
}


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

    # Model class catalog is needed even when a class has ZERO positives
    # and ZERO predictions. Otherwise a 97% macro mAP can hide an untested
    # class because the old loop only saw observed ground truth/predictions.
    catalog_ids: set[int] = set()
    if isinstance(names, Mapping):
        for key in names:
            try:
                class_id = int(key)
            except (TypeError, ValueError, OverflowError):
                continue
            if 0 <= class_id < 10000:
                catalog_ids.add(class_id)
    elif isinstance(names, Sequence) and not isinstance(names, (str, bytes)):
        catalog_ids = set(range(min(len(names), 10000)))
    observed_ids = {int(row["class_id"]) for row in targets} | {
        int(row["class_id"]) for row in predictions
    }
    class_ids = sorted(catalog_ids | observed_ids)
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
                # Without any positive test ground truth, recall and AP are
                # undefined (not a measured zero or measured 100%).
                "evaluation_status": "evaluated" if class_targets else "no_test_ground_truth",
                "precision": round(precision, 6) if class_targets else None,
                "recall": round(recall, 6) if class_targets else None,
                "map50": round(aps[0] if aps else 0.0, 6) if class_targets else None,
                "map50_95": round(_mean(aps), 6) if class_targets else None,
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
    class_coverage = {
        "schema_version": 1,
        "source": "declared_model_names" if catalog_ids else "observed_only",
        "total_classes": len(class_ids),
        "scored_class_ids": [row["class_id"] for row in scored],
        "class_ids_without_test_ground_truth": [
            row["class_id"] for row in per_class
            if row["ground_truth_count"] == 0
        ],
        "macro_average_class_count": len(scored),
    }
    error_samples: list[dict[str, Any]] = []
    operating_predictions = [
        row for row in predictions if float(row["confidence"]) >= float(operating_conf)
    ]
    predictions_by_image: dict[str, list[dict[str, Any]]] = defaultdict(list)
    targets_by_image: dict[str, list[dict[str, Any]]] = defaultdict(list)
    confusion_counts: dict[tuple[int | None, int | None], int] = defaultdict(int)
    confusion_images: dict[tuple[int | None, int | None], set[str]] = defaultdict(set)
    for row in operating_predictions:
        predictions_by_image[str(row["image"])].append(row)
    for row in targets:
        targets_by_image[str(row["image"])].append(row)
    for image_path in images:
        image_name = image_path.name
        image_predictions = predictions_by_image.get(image_name, [])
        image_targets = targets_by_image.get(image_name, [])
        # Class-agnostic spatial matching is a separate diagnostic protocol:
        # wrong-class overlaps belong off diagonal, not fabricated from TP/FP/FN.
        spatial_used: set[int] = set()
        for prediction in sorted(image_predictions, key=lambda item: -item['confidence']):
            overlaps = [(_iou(prediction['box'], target['box']), index)
                        for index, target in enumerate(image_targets) if index not in spatial_used]
            best = max(overlaps, default=(0., -1))
            target_class = None
            if best[0] >= 0.5:
                spatial_used.add(best[1])
                target_class = int(image_targets[best[1]]['class_id'])
            key = (target_class, int(prediction['class_id']))
            confusion_counts[key] += 1
            if len(confusion_images[key]) < 200:
                confusion_images[key].add(image_name)
        for index, target in enumerate(image_targets):
            if index not in spatial_used:
                key = (int(target['class_id']), None)
                confusion_counts[key] += 1
                if len(confusion_images[key]) < 200:
                    confusion_images[key].add(image_name)
        # Keep visual FP/FN evidence identical to the class-level scorer:
        # confidence-first, highest-IoU unmatched GT of the same class.
        # IoU-first pairing can disagree with _match_flags and hide true errors.
        matched_predictions: set[int] = set()
        matched_targets: set[int] = set()
        for prediction_index in sorted(
            range(len(image_predictions)),
            key=lambda index: -float(image_predictions[index]["confidence"]),
        ):
            prediction = image_predictions[prediction_index]
            best_target = -1
            best_overlap = -1.0
            for target_index, target in enumerate(image_targets):
                if target_index in matched_targets or int(prediction["class_id"]) != int(target["class_id"]):
                    continue
                overlap = _iou(prediction["box"], target["box"])
                if overlap >= 0.5 and overlap > best_overlap:
                    best_overlap = overlap
                    best_target = target_index
            if best_target >= 0:
                matched_predictions.add(prediction_index)
                matched_targets.add(best_target)
        fp = [row for index, row in enumerate(image_predictions) if index not in matched_predictions]
        fn = [row for index, row in enumerate(image_targets) if index not in matched_targets]
        if fp or fn:
            width, height = dimensions[image_name]
            error_samples.append({
                "image": image_name,
                "image_id": image_path.stem,
                "image_width": width,
                "image_height": height,
                "fp_count": len(fp),
                "fn_count": len(fn),
                "fp_labels": sorted({_label_name(names, int(row["class_id"])) for row in fp}),
                "fn_labels": sorted({_label_name(names, int(row["class_id"])) for row in fn}),
                # Keep lightweight per-image evidence until severity ranking.
                # Only the top 200 images need costly box serialization.
                "_matched_predictions": sorted(matched_predictions),
                "_matched_targets": sorted(matched_targets),
            })
    # The old first-200 traversal hid later, more serious failures and reported
    # a false total. Keep all counts, persist only a bounded severity-ranked view.
    error_sample_count = len(error_samples)
    error_samples.sort(key=lambda row: (-row["fn_count"], -row["fp_count"], row["image"]))
    error_samples = error_samples[:200]
    def evidence_box(row: Mapping[str, Any], matched: bool, kind: str) -> dict[str, Any]:
        return {
            "class_id": int(row["class_id"]),
            "label": _label_name(names, int(row["class_id"])),
            "box": [round(float(value), 3) for value in row["box"]],
            "matched": bool(matched),
            "kind": kind,
            **({"confidence": round(float(row["confidence"]), 6)} if kind == "prediction" else {}),
        }
    for sample in error_samples:
        name = sample["image"]
        digest = hashlib.sha256()
        with (image_root / name).open('rb') as image_file:
            for chunk in iter(lambda: image_file.read(1024 * 1024), b''):
                digest.update(chunk)
        sample['image_content_sha256'] = digest.hexdigest()
        pred = predictions_by_image.get(name, [])
        truth = targets_by_image.get(name, [])
        matched_pred = set(sample.pop("_matched_predictions"))
        matched_gt = set(sample.pop("_matched_targets"))
        sample["pred_boxes"] = [evidence_box(row, index in matched_pred, "prediction")
                                for index, row in enumerate(pred[:120])]
        sample["gt_boxes"] = [evidence_box(row, index in matched_gt, "ground_truth")
                              for index, row in enumerate(truth[:120])]
        sample["boxes_truncated"] = len(pred) > 120 or len(truth) > 120

    weak_label_threshold = 0.75
    confidence_curves = []
    for class_id in class_ids[:100]:
        class_predictions = sorted(
            (row for row in predictions if int(row['class_id']) == class_id),
            key=lambda row: -row['confidence'],
        )
        class_targets = [row for row in targets if int(row['class_id']) == class_id]
        flags = _match_flags(class_predictions, class_targets, 0.5)
        points = []
        for index in range(21):
            threshold = index / 20
            selected = [flag for prediction, flag in zip(class_predictions, flags)
                        if prediction['confidence'] >= threshold]
            tp = sum(selected)
            precision = tp / len(selected) if selected else 0.
            recall = tp / len(class_targets) if class_targets else 0.
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.
            points.append({'confidence': threshold, 'precision': round(precision, 6),
                           'recall': round(recall, 6), 'f1': round(f1, 6)})
        confidence_curves.append({'class_id': class_id, 'label': _label_name(names, class_id), 'points': points})
    weak_labels = [
        str(row["label"])
        for row in sorted(scored, key=lambda row: (float(row["recall"]), float(row["map50"])))
        if int(row["ground_truth_count"]) > 0
        and (float(row["recall"]) < weak_label_threshold or float(row["map50"]) < weak_label_threshold)
    ]
    return {
        "status": "succeeded",
        "metrics": metrics,
        "per_class": per_class,
        "class_coverage": class_coverage,
        "weak_labels": weak_labels[:100],
        "error_samples": error_samples,
        "error_sample_count": error_sample_count,
        "confusion_matrix": {
            'protocol': 'confidence_first_class_agnostic_iou_0.5',
            'operating_conf': float(operating_conf),
            'cells': [{'actual': key[0], 'predicted': key[1], 'count': count,
                       'images': sorted(confusion_images[key])}
                      for key, count in confusion_counts.items()],
        },
        'confidence_curves': confidence_curves,
        'confidence_curve_protocol': 'same_class_confidence_first_iou_0.5_grid_0.05',
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


def build_evaluation_benchmark_scope(
    snapshot: Mapping[str, Any] | None,
    dataset_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze the exact Snapshot v3 test cohort and ground-truth identity.

    Legacy snapshots remain readable but cannot claim strict benchmark
    comparability because they do not contain the complete content/annotation
    truth required by this scope.
    """
    raw = dict(snapshot) if isinstance(snapshot, Mapping) else {}
    try:
        snapshot_schema = int(raw.get("schema_version") or 0)
    except (TypeError, ValueError, OverflowError):
        return {}
    if snapshot_schema < 3:
        return {}

    raw_ids = raw.get("test_image_ids")
    if raw_ids is None and isinstance(raw.get("ids"), Mapping):
        raw_ids = raw["ids"].get("test")
    if not isinstance(raw_ids, list):
        raise ValueError("benchmark scope requires Snapshot v3 test_image_ids")
    test_ids = [str(value or "").strip() for value in raw_ids]
    if any(not value for value in test_ids) or len(set(test_ids)) != len(test_ids):
        raise ValueError("benchmark scope test_image_ids are invalid")
    if not test_ids:
        return {}

    records: dict[str, dict[str, Any]] = {}
    for raw_record in list(raw.get("images") or []):
        if not isinstance(raw_record, Mapping):
            continue
        image_id = str(raw_record.get("image_id") or "").strip()
        if not image_id:
            continue
        if image_id in records:
            raise ValueError("benchmark scope contains duplicate image truth")
        records[image_id] = dict(raw_record)

    label_schema = []
    seen_codes = set()
    seen_classes = set()
    for raw_label in list(raw.get("label_schema") or []):
        if not isinstance(raw_label, Mapping):
            continue
        code = str(raw_label.get("code") or "").strip()
        if not code:
            continue
        try:
            class_id = int(raw_label.get("class_id"))
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("benchmark scope label schema class_id is invalid") from error
        if class_id < 0 or code in seen_codes or class_id in seen_classes:
            raise ValueError("benchmark scope label schema is ambiguous")
        seen_codes.add(code)
        seen_classes.add(class_id)
        label_schema.append({"class_id": class_id, "code": code})
    label_schema.sort(key=lambda row: (row["class_id"], row["code"]))
    label_schema_digest = hashlib.sha256(json.dumps(
        label_schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()

    content_truth = []
    ground_truth = []
    for image_id in sorted(test_ids):
        record = records.get(image_id)
        if record is None:
            raise ValueError(f"benchmark test image {image_id} is missing from snapshot truth")
        role = str(record.get("role") or "").strip()
        if role and role != "test":
            raise ValueError(f"benchmark image {image_id} is not frozen as test")
        content_sha = _sha256_identity(record.get("content_sha256"), "benchmark content_sha256")
        annotation_hash = _sha256_identity(record.get("annotation_hash"), "benchmark annotation_hash")
        if not content_sha or not annotation_hash:
            raise ValueError("benchmark scope requires content and annotation SHA256 truth")
        annotation_state = str(record.get("annotation_state") or "").strip()
        if annotation_state not in {"annotated", "confirmed_empty", "unannotated"}:
            raise ValueError("benchmark scope annotation_state is invalid")
        content_truth.append({"image_id": image_id, "content_sha256": content_sha})
        ground_truth.append({
            "image_id": image_id,
            "annotation_hash": annotation_hash,
            "annotation_state": annotation_state,
        })

    content_digest = hashlib.sha256(json.dumps(
        content_truth, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    ground_truth_digest = hashlib.sha256(json.dumps(
        {"label_schema_digest": label_schema_digest, "items": ground_truth},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    binding_level = "snapshot_truth"
    evaluation_input_digest = ""
    training_input_policy = ""
    manifest = dict(dataset_manifest) if isinstance(dataset_manifest, Mapping) else {}
    if manifest:
        try:
            manifest_schema = int(manifest.get("schema_version") or 0)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("benchmark dataset manifest schema is invalid") from error
        if manifest_schema < 3:
            raise ValueError("benchmark dataset manifest is too old for strict comparison")
        snapshot_id = str(raw.get("snapshot_id") or "").strip()
        manifest_snapshot_id = str(manifest.get("snapshot_id") or "").strip()
        if snapshot_id and manifest_snapshot_id and snapshot_id != manifest_snapshot_id:
            raise ValueError("benchmark dataset manifest belongs to a different snapshot")
        raw_splits = manifest.get("splits")
        test_members = raw_splits.get("test") if isinstance(raw_splits, Mapping) else None
        if not isinstance(test_members, list):
            raise ValueError("benchmark dataset manifest test split is missing")
        manifest_policy = str(manifest.get("training_input_policy") or "").strip()
        input_truth = []
        seen_manifest_ids = set()
        for raw_member in test_members:
            if not isinstance(raw_member, Mapping):
                raise ValueError("benchmark dataset manifest test member is invalid")
            image_id = str(raw_member.get("image_id") or "").strip()
            if not image_id or image_id in seen_manifest_ids:
                raise ValueError("benchmark dataset manifest test IDs are invalid")
            seen_manifest_ids.add(image_id)
            if image_id not in records:
                raise ValueError("benchmark dataset manifest contains an unknown test image")
            source_sha = _sha256_identity(
                raw_member.get("source_content_sha256"),
                "benchmark manifest source_content_sha256",
            )
            if source_sha != _sha256_identity(
                records[image_id].get("content_sha256"),
                "benchmark snapshot content_sha256",
            ):
                raise ValueError("benchmark dataset manifest source image differs from snapshot truth")
            training_sha = _sha256_identity(
                raw_member.get("content_sha256"),
                "benchmark manifest content_sha256",
            )
            label_sha = _sha256_identity(
                raw_member.get("label_sha256"),
                "benchmark manifest label_sha256",
            )
            member_policy = str(
                raw_member.get("training_input_policy") or manifest_policy
            ).strip()
            if not training_sha or not label_sha or not member_policy:
                raise ValueError("benchmark dataset manifest test identity is incomplete")
            input_truth.append({
                "image_id": image_id,
                "content_sha256": training_sha,
                "label_sha256": label_sha,
                "training_input_policy": member_policy,
            })
        if seen_manifest_ids != set(test_ids):
            raise ValueError("benchmark dataset manifest test cohort differs from snapshot truth")
        policies = {row["training_input_policy"] for row in input_truth}
        if len(policies) != 1:
            raise ValueError("benchmark dataset manifest uses mixed training input policies")
        training_input_policy = next(iter(policies))
        if manifest_policy and training_input_policy != manifest_policy:
            raise ValueError("benchmark dataset manifest input policy is inconsistent")
        evaluation_input_digest = hashlib.sha256(json.dumps(
            sorted(input_truth, key=lambda row: row["image_id"]),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        binding_level = "bundle_verified"

    identity = {
        "schema_version": EVALUATION_BENCHMARK_SCOPE_SCHEMA_VERSION,
        "test_image_count": len(test_ids),
        "content_digest": content_digest,
        "ground_truth_digest": ground_truth_digest,
        "label_schema_digest": label_schema_digest,
        "binding_level": binding_level,
        **(
            {
                "evaluation_input_digest": evaluation_input_digest,
                "training_input_policy": training_input_policy,
            }
            if binding_level == "bundle_verified"
            else {}
        ),
    }
    scope_id = hashlib.sha256(json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return {**identity, "scope_id": scope_id}


def build_evaluation_truth(
    result: Mapping[str, Any] | None,
    *,
    task_id: Any,
    snapshot_id: Any = "",
    dataset_revision_id: Any = "",
    model_sha256: Any = "",
    finished_at: Any = "",
    benchmark_scope: Mapping[str, Any] | None = None,
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
        no_test_gt = str(row.get("evaluation_status") or "") == "no_test_ground_truth"
        per_class.append({
            "class_id": int(row.get("class_id") or 0),
            "label": str(row.get("label") or "")[:1000],
            "evaluation_status": (
                "no_test_ground_truth" if no_test_gt
                else "evaluated" if row.get("evaluation_status") == "evaluated"
                else "legacy_unknown"
            ),
            "precision": None if no_test_gt else round(_finite(row.get("precision")), 6),
            "recall": None if no_test_gt else round(_finite(row.get("recall")), 6),
            "map50": None if no_test_gt else round(_finite(row.get("map50")), 6),
            "map50_95": None if no_test_gt else round(_finite(row.get("map50_95")), 6),
            "true_positive": max(0, int(row.get("true_positive") or 0)),
            "false_positive": max(0, int(row.get("false_positive") or 0)),
            "false_negative": max(0, int(row.get("false_negative") or 0)),
            "ground_truth_count": max(0, int(row.get("ground_truth_count") or 0)),
            "prediction_count": max(0, int(row.get("prediction_count") or 0)),
        })
    raw_coverage = raw.get("class_coverage") if isinstance(raw.get("class_coverage"), Mapping) else {}
    class_coverage = {}
    if raw_coverage and int(raw_coverage.get("schema_version") or 0) == 1:
        class_coverage = {
            "schema_version": 1,
            "source": (
                "declared_model_names"
                if raw_coverage.get("source") == "declared_model_names"
                else "observed_only"
            ),
            "total_classes": len(per_class),
            "macro_average_class_count": sum(row["ground_truth_count"] > 0 for row in per_class),
            "scored_class_ids": sorted(
                row["class_id"] for row in per_class if row["ground_truth_count"] > 0
            ),
            "class_ids_without_test_ground_truth": sorted(
                row["class_id"] for row in per_class if row["ground_truth_count"] == 0
            ),
        }
    weak_labels = [str(value)[:1000] for value in list(raw.get("weak_labels") or [])[:100] if str(value or "").strip()]
    error_samples = []
    for row in list(raw.get("error_samples") or [])[:200]:
        if not isinstance(row, Mapping):
            continue
        def bounded_boxes(key: str, kind: str) -> list[dict[str, Any]]:
            clean = []
            for item in list(row.get(key) or [])[:120]:
                if not isinstance(item, Mapping):
                    continue
                coords = item.get("box")
                if not isinstance(coords, (list, tuple)) or len(coords) != 4:
                    continue
                try:
                    numbers = [float(x) for x in coords]
                except (TypeError, ValueError):
                    continue
                if not all(math.isfinite(x) for x in numbers):
                    continue
                entry = {
                    "class_id": int(item.get("class_id") or 0),
                    "label": str(item.get("label") or "")[:100],
                    "box": [round(x, 3) for x in numbers],
                    "matched": item.get("matched") is True,
                    "kind": kind,
                }
                if kind == "prediction":
                    entry["confidence"] = round(min(1., max(0., _finite(item.get("confidence")))), 6)
                clean.append(entry)
            return clean
        error_samples.append({
            "image": Path(str(row.get("image") or "")).name[:240],
            "image_id": str(row.get('image_id') or '')[:240],
            "image_content_sha256": _sha256_identity(row.get('image_content_sha256'), 'image_content_sha256'),
            "image_width": max(0, int(row.get("image_width") or 0)),
            "image_height": max(0, int(row.get("image_height") or 0)),
            "fp_count": max(0, int(row.get("fp_count") or 0)),
            "fn_count": max(0, int(row.get("fn_count") or 0)),
            "fp_labels": [str(value)[:1000] for value in list(row.get("fp_labels") or [])[:100]],
            "fn_labels": [str(value)[:1000] for value in list(row.get("fn_labels") or [])[:100]],
            "pred_boxes": bounded_boxes("pred_boxes", "prediction"),
            "gt_boxes": bounded_boxes("gt_boxes", "ground_truth"),
            "boxes_truncated": row.get("boxes_truncated") is True,
        })
    protocol_raw = raw.get("protocol") if isinstance(raw.get("protocol"), Mapping) else {}
    protocol = {
        "mode": str(protocol_raw.get("mode") or "")[:200],
        "operating_conf": round(_finite(protocol_raw.get("operating_conf")), 6),
        "matching_iou": round(_finite(protocol_raw.get("matching_iou"), 0.5), 6),
        "weak_label_threshold": round(_finite(protocol_raw.get("weak_label_threshold"), 0.75), 6),
        "iou_thresholds": [round(_finite(value), 6) for value in list(protocol_raw.get("iou_thresholds") or [])[:20]],
    }
    # Only new evaluations that actually record their inference settings
    # include these fields in the protocol ID. Historic reports remain
    # readable but are not assumed equivalent to 640/800 evaluations.
    if protocol_raw.get("predict_imgsz") is not None:
        predict_imgsz = int(protocol_raw["predict_imgsz"])
        if predict_imgsz < 128:
            raise ValueError("evaluation predict_imgsz is invalid")
        protocol["predict_imgsz"] = predict_imgsz
    for parameter in ("predict_conf", "predict_nms_iou"):
        if protocol_raw.get(parameter) is not None:
            value = float(protocol_raw[parameter])
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"evaluation {parameter} is invalid")
            protocol[parameter] = round(value, 6)
    evaluation_protocol_identity = {
        "schema_version": EVALUATION_PROTOCOL_SCHEMA_VERSION,
        "protocol": protocol,
    }
    evaluation_protocol_id = hashlib.sha256(json.dumps(
        evaluation_protocol_identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()
    scope = {}
    if isinstance(benchmark_scope, Mapping) and benchmark_scope:
        try:
            scope_schema = int(benchmark_scope.get("schema_version") or 0)
            test_image_count = max(0, int(benchmark_scope.get("test_image_count") or 0))
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("evaluation benchmark scope is invalid") from error
        if scope_schema != EVALUATION_BENCHMARK_SCOPE_SCHEMA_VERSION or test_image_count <= 0:
            raise ValueError("evaluation benchmark scope schema/count is invalid")
        binding_level = str(benchmark_scope.get("binding_level") or "snapshot_truth").strip()
        if binding_level not in {"snapshot_truth", "bundle_verified"}:
            raise ValueError("evaluation benchmark binding level is invalid")
        scope = {
            "schema_version": scope_schema,
            "scope_id": _sha256_identity(benchmark_scope.get("scope_id"), "benchmark scope_id"),
            "test_image_count": test_image_count,
            "content_digest": _sha256_identity(benchmark_scope.get("content_digest"), "benchmark content_digest"),
            "ground_truth_digest": _sha256_identity(benchmark_scope.get("ground_truth_digest"), "benchmark ground_truth_digest"),
            "label_schema_digest": _sha256_identity(benchmark_scope.get("label_schema_digest"), "benchmark label_schema_digest"),
            "binding_level": binding_level,
        }
        if binding_level == "bundle_verified":
            scope["evaluation_input_digest"] = _sha256_identity(
                benchmark_scope.get("evaluation_input_digest"),
                "benchmark evaluation_input_digest",
            )
            scope["training_input_policy"] = str(
                benchmark_scope.get("training_input_policy") or ""
            ).strip()[:200]
        if not all(scope.get(key) for key in ("scope_id", "content_digest", "ground_truth_digest", "label_schema_digest")):
            raise ValueError("evaluation benchmark scope identity is incomplete")
        if binding_level == "bundle_verified" and not all(
            scope.get(key) for key in ("evaluation_input_digest", "training_input_policy")
        ):
            raise ValueError("evaluation benchmark bundle binding is incomplete")
        if status == "succeeded" and max(0, int(raw.get("image_count") or 0)) != test_image_count:
            raise ValueError("evaluation image_count does not match frozen benchmark scope")
    identity = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "status": status,
        "task_id": task,
        "snapshot_id": str(snapshot_id or "").strip(),
        "dataset_revision_id": revision,
        "model_sha256": model_digest,
        "metrics": metrics,
        "per_class": per_class,
        **({"class_coverage": class_coverage} if class_coverage else {}),
        "weak_labels": weak_labels,
        "error_samples": error_samples,
        "error_sample_count": max(len(error_samples), int(raw.get("error_sample_count") or 0)),
        "image_count": max(0, int(raw.get("image_count") or 0)),
        "ground_truth_box_count": max(0, int(raw.get("ground_truth_box_count") or 0)),
        "prediction_box_count": max(0, int(raw.get("prediction_box_count") or 0)),
        "protocol": protocol,
        "evaluation_protocol_version": EVALUATION_PROTOCOL_SCHEMA_VERSION,
        "evaluation_protocol_id": evaluation_protocol_id,
        **({"benchmark_scope": scope} if scope else {}),
    }
    # Optional vNext evidence. Old reports remain honest missing-data states.
    matrix = raw.get('confusion_matrix')
    if isinstance(matrix, Mapping) and matrix.get('protocol') == 'confidence_first_class_agnostic_iou_0.5':
        identity['confusion_matrix'] = {
            'protocol': matrix['protocol'], 'operating_conf': _finite(matrix.get('operating_conf')),
            'cells': [{'actual': int(cell['actual']) if cell.get('actual') is not None else None,
                       'predicted': int(cell['predicted']) if cell.get('predicted') is not None else None,
                       'count': max(0, int(cell.get('count') or 0)),
                       'images': [Path(str(name)).name[:240] for name in list(cell.get('images') or [])[:200]]}
                      for cell in list(matrix.get('cells') or [])[:10000] if isinstance(cell, Mapping)],
        }
    if raw.get('confidence_curve_protocol') == 'same_class_confidence_first_iou_0.5_grid_0.05':
        identity['confidence_curve_protocol'] = raw['confidence_curve_protocol']
        identity['confidence_curves'] = [
            {'class_id': int(curve.get('class_id') or 0), 'label': str(curve.get('label') or '')[:1000],
             'points': [{key: round(min(1., max(0., _finite(point.get(key)))), 6)
                        for key in ('confidence', 'precision', 'recall', 'f1')}
                       for point in list(curve.get('points') or [])[:21] if isinstance(point, Mapping)]}
            for curve in list(raw.get('confidence_curves') or [])[:100] if isinstance(curve, Mapping)
        ]
    evaluation_id = hashlib.sha256(json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return {
        **identity,
        "evaluation_id": evaluation_id,
        "finished_at": str(finished_at or "").strip(),
        "failure_reason": "evaluation_failed" if status == "failed" else "",
    }


def build_training_metric_credibility(
    training_report: Mapping[str, Any] | None,
    evaluation: Mapping[str, Any] | None,
    *,
    input_quality: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Advisory evidence for unusually high Val mAP, NOT a fraud detector.

    Val scores are model-selection metrics; independent blind Test is a
    different measurement. Lack of data is never interpreted as passing a
    reliability threshold. This only inspects already persisted evidence.
    """
    report = training_report if isinstance(training_report, Mapping) else {}
    test = evaluation if isinstance(evaluation, Mapping) else {}
    quality = input_quality if isinstance(input_quality, Mapping) else {}
    val = report.get("metrics") if isinstance(report.get("metrics"), Mapping) else {}
    test_metrics = test.get("metrics") if isinstance(test.get("metrics"), Mapping) else {}
    split = quality.get("class_coverage") if isinstance(quality.get("class_coverage"), Mapping) else {}
    coverage = test.get("class_coverage") if isinstance(test.get("class_coverage"), Mapping) else {}
    admission = quality.get("annotation_admission") if isinstance(quality.get("annotation_admission"), Mapping) else {}
    source_admission = quality.get("source_ground_truth_admission") if isinstance(quality.get("source_ground_truth_admission"), Mapping) else {}

    def score(values: Mapping[str, Any], key: str) -> float | None:
        try:
            raw = values.get(key)
            if raw is None or isinstance(raw, bool):
                return None
            result = float(raw)
            if not math.isfinite(result) or result < 0 or result > 1:
                return None
            return round(result, 6)
        except (TypeError, ValueError, OverflowError):
            return None

    def count(value: Any) -> int | None:
        try:
            if value is None or isinstance(value, bool):
                return None
            number = int(value)
            return number if number >= 0 else None
        except (TypeError, ValueError, OverflowError):
            return None

    val_map = score(val, "metrics/mAP50(B)")
    test_map = score(test_metrics, "metrics/mAP50(B)")
    val_map95 = score(val, "metrics/mAP50-95(B)")
    test_map95 = score(test_metrics, "metrics/mAP50-95(B)")
    test_status = str(test.get("status") or "not_requested").strip().lower()
    benchmark = test.get("benchmark_scope") if isinstance(test.get("benchmark_scope"), Mapping) else {}
    binding_level = (
        str(benchmark.get("binding_level"))
        if test_status == "succeeded"
        and benchmark.get("binding_level") in {"snapshot_truth", "bundle_verified"}
        else "unavailable"
    )
    is_high_val = val_map is not None and val_map >= 0.95
    gap = (
        round(val_map - test_map, 6)
        if val_map is not None and test_map is not None and test_status == "succeeded"
        else None
    )
    reasons: list[str] = []
    actions: list[str] = []

    def flag(reason: str, action: str) -> None:
        if reason not in reasons:
            reasons.append(reason)
        if action not in actions:
            actions.append(action)

    if is_high_val:
        if test_status != "succeeded":
            flag("independent_test_unavailable", "run_independent_blind_test")
        elif test_map is None or count(test.get("image_count")) in (None, 0):
            flag("independent_test_metric_or_samples_missing", "inspect_test_execution_truth")
        if gap is not None and gap >= 0.10:
            flag("validation_test_map50_gap_at_least_10pp", "inspect_val_test_distribution_and_protocol")
        if not coverage or coverage.get("source") != "declared_model_names":
            flag("test_class_coverage_unverified", "verify_model_class_catalog_and_test_gt")
        else:
            if not coverage.get("scored_class_ids") or (
                count(coverage.get("macro_average_class_count")) in (None, 0)
            ):
                flag("independent_test_no_scored_positive_classes", "inspect_test_gt_positive_support")
            if coverage.get("class_ids_without_test_ground_truth"):
                flag("independent_test_classes_without_gt", "add_independent_test_positive_samples")
        if not split:
            flag("frozen_split_coverage_unavailable", "inspect_frozen_split_and_provenance")
        else:
            missing_val = split.get("train_labels_without_validation_positive") or []
            missing_test = split.get("train_labels_without_test_positive") or []
            if missing_val:
                flag("validation_classes_without_gt", "review_validation_class_coverage")
            if missing_test:
                flag("split_test_classes_without_gt", "review_independent_test_class_coverage")
            frozen_labels = split.get("active_label_codes")
            test_declared_count = count(coverage.get("total_classes"))
            if (isinstance(frozen_labels, (list, tuple))
                    and test_declared_count is not None
                    and len(frozen_labels) != test_declared_count):
                flag("model_class_catalog_differs_from_frozen_training_labels", "inspect_model_class_mapping")
            known_by_role = split.get("role_known_source_image_counts")
            unknown_by_role = split.get("role_unknown_source_image_counts")
            if isinstance(known_by_role, Mapping) and isinstance(unknown_by_role, Mapping):
                known_test = count(known_by_role.get("test"))
                unknown_test = count(unknown_by_role.get("test"))
                actual_test_count = count(test.get("image_count"))
                if (known_test is not None and unknown_test is not None
                        and test_status == "succeeded"
                        and actual_test_count != known_test + unknown_test):
                    flag("test_scored_images_differ_from_frozen_selection", "inspect_test_materialization_completeness")
            if not isinstance(unknown_by_role, Mapping):
                flag("capture_source_evidence_missing", "review_capture_source_metadata")
            elif any((count(value) or 0) > 0 for value in unknown_by_role.values()):
                flag("capture_source_partly_unknown", "review_capture_source_metadata")
            components = split.get("label_independent_component_counts")
            test_components = components.get("test") if isinstance(components, Mapping) else None
            if not isinstance(test_components, Mapping):
                flag("test_independent_component_counts_missing", "review_independent_test_groups")
            elif any((count(value) or 0) < 3 for value in test_components.values()):
                # A heuristic warning only: it is NOT a statistical p-value.
                flag("test_class_fewer_than_three_independent_groups", "expand_test_group_diversity")
            image_counts = split.get("label_image_counts")
            test_images_by_class = image_counts.get("test") if isinstance(image_counts, Mapping) else None
            if not isinstance(test_images_by_class, Mapping):
                flag("test_positive_image_support_missing", "review_test_positive_image_counts")
            elif any((count(value) or 0) < 5 for value in test_images_by_class.values()):
                flag("test_class_fewer_than_five_positive_images", "expand_test_positive_coverage")

        protocol = test.get("protocol") if isinstance(test.get("protocol"), Mapping) else {}
        if test_status == "succeeded" and (
            protocol.get("mode") != "blind_image_only_inference_then_hidden_ground_truth_scoring"
            or not all(protocol.get(key) is not None for key in (
                "predict_imgsz", "predict_conf", "predict_nms_iou",
            ))
        ):
            flag("independent_test_inference_protocol_incomplete", "verify_prediction_settings")
        if test_status == "succeeded" and binding_level != "bundle_verified":
            flag("independent_test_input_binding_unverified", "verify_immutable_test_input_binding")

        for audit in (admission, source_admission):
            severity = audit.get("severity_counts") if isinstance(audit.get("severity_counts"), Mapping) else {}
            if (count(severity.get("manual_review")) or 0) > 0:
                flag("source_or_projected_gt_needs_review", "review_training_annotation_issues")

    # A 97% Val mAP is a trigger for scrutiny, not a conclusion of data
    # leakage or model accuracy. Even complete held-out evidence does not
    # verify business event precision or out-of-distribution generalization.
    status = (
        "review_required" if is_high_val and reasons
        else "held_out_evidence_present" if is_high_val
        else "val_metric_unavailable" if val_map is None
        else "not_high_val_trigger"
    )
    details = {
        "schema_version": 1,
        "status": status,
        "metric_kind": "object_detection_map_not_event_accuracy",
        "validation_map50": val_map,
        "validation_map50_95": val_map95,
        "independent_test_map50": test_map if test_status == "succeeded" else None,
        "independent_test_map50_95": test_map95 if test_status == "succeeded" else None,
        "val_minus_test_map50": gap,
        "test_status": test_status,
        # One server-owned, persisted evidence level for every report UI.
        # The browser never infers a binding from a high Test mAP score.
        "independent_test_binding_level": binding_level,
        "test_image_count": count(test.get("image_count")),
        "high_val_threshold": 0.95,
        "val_test_gap_review_threshold": 0.10,
        "high_val_triggered": bool(is_high_val),
        "reason_codes": reasons,
        "recommended_actions": actions,
        "leakage_conclusion": "not_determined",
        "production_accuracy_verified": False,
        "automatic_execution": False,
    }
    encoded = json.dumps(details, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {
        **details,
        "diagnostic_id": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    }


def build_iteration_decision(
    evaluation: Mapping[str, Any] | None,
    *,
    quality_gate: Mapping[str, Any] | None = None,
    metric_credibility: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one advisory, version-owned next-step decision from evaluation truth.

    This function never schedules work. It snapshots the existing training
    quality-gate semantics so frontend and backend cannot infer different
    conclusions from the same persisted evaluation.
    """
    value = dict(evaluation) if isinstance(evaluation, Mapping) else {}
    gate = dict(quality_gate) if isinstance(quality_gate, Mapping) else {}
    evaluation_status = str(value.get("status") or "not_requested").strip().lower()
    metric_name = str(gate.get("metric") or "map50").strip().lower().replace(" ", "")
    metric_key = _DECISION_METRIC_KEYS.get(metric_name)
    metrics = value.get("metrics") if isinstance(value.get("metrics"), Mapping) else {}
    metric_value = None
    if metric_key and metrics.get(metric_key) is not None:
        metric_value = round(_finite(metrics.get(metric_key)), 6)

    continue_threshold = max(0.0, _finite(gate.get("continue_threshold")))
    stop_threshold = max(0.0, _finite(gate.get("stop_threshold")))
    weak_labels = list(dict.fromkeys(
        str(label)[:1000]
        for label in list(value.get("weak_labels") or [])
        if str(label or "").strip()
    ))
    per_class = [row for row in list(value.get("per_class") or []) if isinstance(row, Mapping)]
    class_coverage = value.get("class_coverage") if isinstance(value.get("class_coverage"), Mapping) else {}
    missing_test_classes = tuple(class_coverage.get("class_ids_without_test_ground_truth") or ())
    total_fp = sum(max(0, int(row.get("false_positive") or 0)) for row in per_class)
    total_fn = sum(max(0, int(row.get("false_negative") or 0)) for row in per_class)
    error_sample_count = max(0, int(value.get("error_sample_count") or 0), len(value.get("error_samples") or []))

    diagnoses: list[dict[str, Any]] = []
    critical_labels: list[str] = []
    for row in per_class:
        label = str(row.get("label") or row.get("class_id") or "-")
        gt = max(0, int(row.get("ground_truth_count") or 0))
        tp = max(0, int(row.get("true_positive") or 0))
        fp = max(0, int(row.get("false_positive") or 0))
        fn = max(0, int(row.get("false_negative") or 0))
        recall_value = _finite(row.get("recall"))
        ap_value = _finite(row.get("map50"))
        if gt > 0 and tp == 0 and fn > 0:
            code, level = "zero_true_positives", "critical"
            critical_labels.append(label)
            next_steps = ["inspect_class_mapping", "inspect_prediction_threshold", "review_fp_fn_samples"]
        elif gt > 0 and (recall_value < 0.75 or ap_value < 0.75):
            code, level = "class_detection_below_reference", "warning"
            next_steps = ["review_fp_fn_samples", "inspect_annotations", "review_training_coverage"]
        elif gt == 0 and fp > 0:
            code, level = "predicted_class_without_test_gt", "review"
            next_steps = ["inspect_class_mapping", "review_fp_fn_samples"]
        else:
            continue
        diagnoses.append({
            "label": label, "class_id": int(row.get("class_id") or 0),
            "code": code, "severity": level,
            "true_positive": tp, "false_positive": fp, "false_negative": fn,
            "ground_truth_count": gt,
            "recall": round(recall_value, 6), "map50": round(ap_value, 6),
            "recommended_actions": next_steps,
            "root_cause_confirmed": False,
        })
    diagnoses.sort(key=lambda item: (0 if item["severity"] == "critical" else 1,
                                     -item["false_negative"], item["label"]))

    reasons: list[str] = []
    actions: list[str] = []
    if evaluation_status == "not_requested":
        decision = "review_required"
        reasons.append("evaluation_not_requested")
        actions.append("configure_independent_test_split")
    elif evaluation_status == "failed":
        decision = "review_required"
        reasons.append("evaluation_failed")
        actions.append("inspect_evaluation_failure")
    elif metric_key is None or metric_value is None:
        decision = "review_required"
        reasons.append("decision_metric_unavailable")
        actions.append("review_evaluation_configuration")
    elif critical_labels:
        # A class with real GT and zero TP must never be sent directly to
        # a supplement-data/ready-for-business flow without diagnosis.
        decision = "review_required"
        reasons.append("critical_class_zero_true_positives")
        actions.extend(("inspect_class_mapping", "inspect_prediction_threshold", "review_fp_fn_samples"))
    elif missing_test_classes:
        decision = "review_required"
        reasons.append("independent_test_class_coverage_incomplete")
        actions.extend(("review_training_coverage", "expand_independent_test_data"))
    elif (isinstance(metric_credibility, Mapping)
          and metric_credibility.get("high_val_triggered") is True
          and metric_credibility.get("status") == "review_required"):
        # Only new results pass this advisory. Legacy iteration decisions
        # replay unchanged when metric_credibility is absent.
        decision = "review_required"
        reasons.append("high_validation_map_evidence_needs_review")
        actions.extend(("inspect_metric_credibility", "review_independent_test_evidence"))
    elif weak_labels:
        decision = "needs_data"
        reasons.append("weak_labels_present")
        actions.extend(("review_fp_fn_samples", "inspect_annotations", "review_training_coverage",
                        "supplement_weak_label_data"))
        if continue_threshold > 0 and metric_value < continue_threshold:
            reasons.append("metric_below_continue_threshold")
    elif continue_threshold > 0 and metric_value < continue_threshold:
        decision = "needs_data"
        reasons.append("metric_below_continue_threshold")
        actions.extend(("supplement_training_data", "review_fp_fn_samples"))
    elif stop_threshold > 0 and metric_value >= stop_threshold:
        decision = "ready_for_business_validation"
        reasons.append("stop_threshold_reached")
        actions.append("proceed_to_business_validation")
    elif stop_threshold > 0:
        decision = "continue_training"
        reasons.append("metric_below_stop_threshold")
        actions.append("continue_from_current_version")
    else:
        decision = "review_required"
        reasons.append("stop_threshold_not_configured")
        actions.append("configure_quality_gate")

    if (total_fp or total_fn) and "review_fp_fn_samples" not in actions:
        actions.append("review_fp_fn_samples")
    identity = {
        "schema_version": ITERATION_DECISION_SCHEMA_VERSION,
        "evaluation_id": str(value.get("evaluation_id") or ""),
        "decision": decision,
        "quality_gate": {
            "metric": metric_name,
            "metric_key": metric_key or "",
            "metric_value": metric_value,
            "continue_threshold": round(continue_threshold, 6),
            "stop_threshold": round(stop_threshold, 6),
        },
        "weak_labels": weak_labels,
        "class_diagnostics": diagnoses[:100],
        "critical_labels": critical_labels[:100],
        "signals": {
            "false_positive": total_fp,
            "false_negative": total_fn,
            "error_sample_count": error_sample_count,
        },
        "reason_codes": reasons,
        "recommended_actions": list(dict.fromkeys(actions)),
        "automatic_execution": False,
        "requires_confirmation": True,
    }
    decision_id = hashlib.sha256(json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return {**identity, "decision_id": decision_id}


FEEDBACK_ADOPTION_OUTCOME_SCHEMA_VERSION = 1


def _evaluation_class_map(value: Mapping[str, Any] | None) -> tuple[dict[Any, dict[str, Any]], bool, bool]:
    rows = value.get("per_class") if isinstance(value, Mapping) else []
    prepared = [dict(raw) for raw in list(rows or [])[:10000] if isinstance(raw, Mapping)]
    has_legacy = any(raw.get('class_id') is None for raw in prepared)
    result: dict[Any, dict[str, Any]] = {}
    ambiguous = False
    for raw in prepared:
        label = str(raw.get("label") or "").strip()
        if has_legacy:
            key = ('label', label) if label else None
        else:
            class_id = raw.get('class_id')
            key = ('id', str(class_id)) if class_id is not None else None
        if key is None or key in result:
            ambiguous = True
            continue
        result[key] = raw
    return result, has_legacy, ambiguous


def compare_evaluations(source: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
    """Strict same-benchmark comparison of existing evaluation truth."""
    reasons = []
    for value in (source, new):
        if value.get('status') != 'succeeded' or not value.get('evaluation_id'):
            reasons.append('evaluation_missing')
    source_scope, new_scope = source.get('benchmark_scope') or {}, new.get('benchmark_scope') or {}
    for key in ('scope_id', 'content_digest', 'ground_truth_digest', 'label_schema_digest', 'evaluation_input_digest'):
        if not source_scope.get(key) or not new_scope.get(key):
            reasons.append('benchmark_evidence_missing')
        elif source_scope[key] != new_scope[key]:
            reasons.append('benchmark_scope_mismatch')
    if source_scope.get('binding_level') != 'bundle_verified' or new_scope.get('binding_level') != 'bundle_verified':
        reasons.append('benchmark_input_binding_missing')
    if not source.get('evaluation_protocol_id') or source.get('evaluation_protocol_id') != new.get('evaluation_protocol_id'):
        reasons.append('evaluation_protocol_mismatch')
    if reasons:
        return {'comparable': False, 'reason_codes': sorted(set(reasons)), 'metrics': {}, 'classes': []}
    metrics = {}
    for key in _EVALUATION_METRICS:
        before, after = (source.get('metrics') or {}).get(key), (new.get('metrics') or {}).get(key)
        if before is not None and after is not None:
            metrics[key] = {'before': before, 'after': after, 'delta': round(_finite(after)-_finite(before), 6)}
    before_classes, before_legacy, before_ambiguous = _evaluation_class_map(source)
    after_classes, after_legacy, after_ambiguous = _evaluation_class_map(new)
    if before_ambiguous or after_ambiguous:
        return {'comparable': False, 'reason_codes': ['class_identity_ambiguous'], 'metrics': {}, 'classes': []}
    if before_legacy != after_legacy:
        # A mixed old/new comparison is safe only when both sides have unique
        # display names; rebuild both maps by that explicitly bounded fallback.
        def legacy_fallback(value):
            mapped = {}
            for raw in list((value or {}).get('per_class') or [])[:10000]:
                if not isinstance(raw, Mapping):
                    continue
                label = str(raw.get('label') or '').strip()
                if not label or label in mapped:
                    return None
                mapped[label] = dict(raw)
            return mapped
        before_fallback, after_fallback = legacy_fallback(source), legacy_fallback(new)
        if before_fallback is None or after_fallback is None:
            return {'comparable': False, 'reason_codes': ['class_identity_ambiguous'], 'metrics': {}, 'classes': []}
        before_classes = {('label', key): value for key, value in before_fallback.items()}
        after_classes = {('label', key): value for key, value in after_fallback.items()}
    classes = []
    labels = [str(row.get('label') or '') for row in list((source or {}).get('per_class') or []) + list((new or {}).get('per_class') or [])]
    duplicate_labels = {label for label in labels if label and labels.count(label) > 2}
    for identity in sorted(set(before_classes) | set(after_classes), key=str):
        before, after = before_classes.get(identity), after_classes.get(identity)
        label = str((after or before or {}).get('label') or identity[-1])
        class_id = (after or before or {}).get('class_id')
        if before is None or after is None:
            classes.append({'class_id': class_id, 'label': label, 'comparable': False})
            continue
        row = {'class_id': class_id, 'label': label, 'comparable': True, 'metrics': {
            key: {'before': before.get(key), 'after': after.get(key),
                  'delta': round(_finite(after[key])-_finite(before[key]), 6)}
            for key in ('precision', 'recall', 'map50', 'map50_95', 'false_positive', 'false_negative')
            if key in before and key in after and before.get(key) is not None and after.get(key) is not None
        }}
        row['regressed'] = any(row['metrics'].get(key, {}).get('delta', 0) < 0 for key in ('recall', 'map50'))
        classes.append(row)
    regressed = [row for row in classes if row.get('comparable') and row.get('regressed')]
    return {'comparable': True, 'reason_codes': [], 'metrics': metrics, 'classes': classes,
            'regressed_class_ids': [row['class_id'] for row in regressed if row.get('class_id') is not None],
            'regressed_labels': [f"{row['label']} · ID {row['class_id']}" if row['label'] in duplicate_labels else row['label']
                                 for row in regressed]}


def build_feedback_adoption_outcome(
    source_evaluation: Mapping[str, Any] | None,
    new_evaluation: Mapping[str, Any] | None,
    supplement_provenance: Mapping[str, Any] | None,
    *,
    source_version_id: Any,
    new_version_id: Any,
) -> dict[str, Any]:
    """Describe before/after effectiveness for one feedback-backed training adoption.

    This is persisted descriptive truth only. It never schedules training or
    mutates feedback/candidate/dataset owners.
    """
    provenance = dict(supplement_provenance) if isinstance(supplement_provenance, Mapping) else {}
    if not provenance:
        return {}
    if int(provenance.get("schema_version") or 0) != 1:
        raise ValueError("supplement provenance schema is unsupported")

    source_version = str(source_version_id or "").strip()
    new_version = str(new_version_id or "").strip()
    provenance_version = str(provenance.get("version_id") or "").strip()
    if not source_version or not new_version or not provenance_version:
        raise ValueError("feedback adoption outcome requires source and new version identity")
    if source_version != provenance_version:
        raise ValueError("supplement provenance source version does not match training base version")

    candidate_set_id = _sha256_identity(provenance.get("candidate_set_id"), "candidate_set_id")
    adoption_id = _sha256_identity(provenance.get("adoption_id"), "adoption_id")
    action_id = _sha256_identity(provenance.get("action_id"), "action_id")
    if not candidate_set_id or not adoption_id or not action_id:
        raise ValueError("supplement provenance identity is incomplete")

    source = dict(source_evaluation) if isinstance(source_evaluation, Mapping) else {}
    new = dict(new_evaluation) if isinstance(new_evaluation, Mapping) else {}
    source_eval_id = _sha256_identity(source.get("evaluation_id"), "source_evaluation_id")
    new_eval_id = _sha256_identity(new.get("evaluation_id"), "new_evaluation_id")

    reasons: list[str] = []
    if not source_eval_id:
        reasons.append("source_evaluation_missing")
    if not new_eval_id:
        reasons.append("new_evaluation_missing")
    if str(source.get("status") or "").strip().lower() != "succeeded":
        reasons.append("source_evaluation_not_succeeded")
    if str(new.get("status") or "").strip().lower() != "succeeded":
        reasons.append("new_evaluation_not_succeeded")

    source_scope = source.get("benchmark_scope") if isinstance(source.get("benchmark_scope"), Mapping) else {}
    new_scope = new.get("benchmark_scope") if isinstance(new.get("benchmark_scope"), Mapping) else {}
    source_scope_id = _sha256_identity(source_scope.get("scope_id"), "source benchmark scope_id")
    new_scope_id = _sha256_identity(new_scope.get("scope_id"), "new benchmark scope_id")
    source_binding_level = str(source_scope.get("binding_level") or "").strip()
    new_binding_level = str(new_scope.get("binding_level") or "").strip()
    source_protocol_id = _sha256_identity(source.get("evaluation_protocol_id"), "source evaluation_protocol_id")
    new_protocol_id = _sha256_identity(new.get("evaluation_protocol_id"), "new evaluation_protocol_id")
    comparison_reasons: list[str] = []
    if not reasons:
        if not source_scope_id or not new_scope_id:
            comparison_reasons.append("benchmark_scope_missing")
        elif source_scope_id != new_scope_id:
            comparison_reasons.append("benchmark_scope_mismatch")
        if (
            source_scope_id
            and new_scope_id
            and (
                source_binding_level != "bundle_verified"
                or new_binding_level != "bundle_verified"
            )
        ):
            comparison_reasons.append("benchmark_input_binding_missing")
        if not source_protocol_id or not new_protocol_id:
            comparison_reasons.append("evaluation_protocol_missing")
        elif source_protocol_id != new_protocol_id:
            comparison_reasons.append("evaluation_protocol_mismatch")
    strictly_comparable = not reasons and not comparison_reasons
    comparison_mode = (
        "strict"
        if strictly_comparable
        else "descriptive"
        if not reasons
        else "unavailable"
    )

    overall: dict[str, Any] = {}
    if not reasons:
        source_metrics = source.get("metrics") if isinstance(source.get("metrics"), Mapping) else {}
        new_metrics = new.get("metrics") if isinstance(new.get("metrics"), Mapping) else {}
        for key in _EVALUATION_METRICS:
            if source_metrics.get(key) is None or new_metrics.get(key) is None:
                continue
            before = round(_finite(source_metrics.get(key)), 6)
            after = round(_finite(new_metrics.get(key)), 6)
            overall[key] = {
                "before": before,
                "after": after,
                "delta": round(after - before, 6),
            }

    def unique_label_rows(value):
        rows = {}
        duplicates = set()
        for raw in list((value or {}).get('per_class') or [])[:10000]:
            if not isinstance(raw, Mapping):
                continue
            label = str(raw.get('label') or '').strip()
            if not label:
                continue
            if label in rows:
                duplicates.add(label)
            else:
                rows[label] = dict(raw)
        for label in duplicates:
            rows.pop(label, None)
        return rows
    source_classes = unique_label_rows(source)
    new_classes = unique_label_rows(new)
    weak_labels = list(dict.fromkeys(
        str(value)[:1000]
        for value in list(source.get("weak_labels") or [])[:100]
        if str(value or "").strip()
    ))
    weak_label_effects: list[dict[str, Any]] = []
    if not reasons:
        for label in weak_labels:
            before_row = source_classes.get(label)
            after_row = new_classes.get(label)
            if not before_row or not after_row:
                weak_label_effects.append({
                    "label": label,
                    "comparable": False,
                    "reason": "label_missing_from_evaluation",
                })
                continue
            metric_rows = {}
            for public_key, raw_key in (
                ("precision", "precision"),
                ("recall", "recall"),
                ("map50", "map50"),
                ("map50_95", "map50_95"),
            ):
                before = round(_finite(before_row.get(raw_key)), 6)
                after = round(_finite(after_row.get(raw_key)), 6)
                metric_rows[public_key] = {
                    "before": before,
                    "after": after,
                    "delta": round(after - before, 6),
                }
            weak_before = min(metric_rows["recall"]["before"], metric_rows["map50"]["before"])
            weak_after = min(metric_rows["recall"]["after"], metric_rows["map50"]["after"])
            weak_delta = round(weak_after - weak_before, 6)
            weak_label_effects.append({
                "label": label,
                "comparable": True,
                "direction": "improved" if weak_delta > 0 else "declined" if weak_delta < 0 else "unchanged",
                "weak_signal": {
                    "before": round(weak_before, 6),
                    "after": round(weak_after, 6),
                    "delta": weak_delta,
                },
                "metrics": metric_rows,
                "false_positive": {
                    "before": max(0, int(before_row.get("false_positive") or 0)),
                    "after": max(0, int(after_row.get("false_positive") or 0)),
                },
                "false_negative": {
                    "before": max(0, int(before_row.get("false_negative") or 0)),
                    "after": max(0, int(after_row.get("false_negative") or 0)),
                },
            })

    identity = {
        "schema_version": FEEDBACK_ADOPTION_OUTCOME_SCHEMA_VERSION,
        "status": "comparable" if not reasons else "not_comparable",
        "source_version_id": source_version,
        "new_version_id": new_version,
        "candidate_set_id": candidate_set_id,
        "adoption_id": adoption_id,
        "action_id": action_id,
        "source_evaluation_id": source_eval_id,
        "new_evaluation_id": new_eval_id,
        "source_candidate_count": max(0, int(provenance.get("source_candidate_count") or 0)),
        "adopted_candidate_count": max(0, int(provenance.get("adopted_candidate_count") or 0)),
        "adopted_feedback_ids": [
            str(value)[:240]
            for value in list(provenance.get("adopted_feedback_ids") or [])[:500]
            if str(value or "").strip()
        ],
        "overall_metrics": overall,
        "source_weak_labels": weak_labels,
        "weak_label_effects": weak_label_effects,
        "reason_codes": list(dict.fromkeys(reasons)),
        "comparison_mode": comparison_mode,
        "strictly_comparable": strictly_comparable,
        "comparison_reason_codes": list(dict.fromkeys(comparison_reasons)),
        "source_benchmark_scope_id": source_scope_id,
        "new_benchmark_scope_id": new_scope_id,
        "source_benchmark_binding_level": source_binding_level,
        "new_benchmark_binding_level": new_binding_level,
        "source_evaluation_protocol_id": source_protocol_id,
        "new_evaluation_protocol_id": new_protocol_id,
        "descriptive_only": True,
        "automatic_execution": False,
    }
    outcome_id = hashlib.sha256(json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return {**identity, "outcome_id": outcome_id}
