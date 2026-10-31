"""Stateless YOLO difficulty signals and frozen Test contamination guard.

This is deliberately not a second CandidateStore, AnnotationRepository or Task owner.
Signals are review hints, never verified false positives/false negatives without GT.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


class HardSampleSafetyError(ValueError):
    pass


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frozen_test_identifiers(project_path: str | Path) -> tuple[set[str], set[str]]:
    """Read one immutable snapshot-owned Test identity projection, never persist it."""
    test_ids: set[str] = set()
    test_hashes: set[str] = set()
    directory = Path(project_path) / "snapshots"
    if not directory.exists():
        return test_ids, test_hashes
    for file in sorted(directory.glob("*.json")):
        try:
            snapshot = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as error:
            raise HardSampleSafetyError("HARD_SAMPLE_SNAPSHOT_UNREADABLE") from error
        if not isinstance(snapshot, dict):
            raise HardSampleSafetyError("HARD_SAMPLE_SNAPSHOT_INVALID")
        roles = snapshot.get("ids") if isinstance(snapshot.get("ids"), dict) else {}
        frozen_ids = set(str(v) for v in (snapshot.get("test_image_ids") or roles.get("test") or []))
        test_ids.update(frozen_ids)
        if not frozen_ids:
            continue
        for row in snapshot.get("images") or []:
            if isinstance(row, dict) and str(row.get("image_id") or "") in frozen_ids:
                digest = str(row.get("content_sha256") or "").lower().strip()
                if digest:
                    test_hashes.add(digest)
    return test_ids, test_hashes


def assert_not_frozen_test(
    project_path: str | Path,
    image_ids: Sequence[str],
    content_hashes: Mapping[str, str] | None = None,
) -> None:
    """Block frozen Test IDs and exact byte duplicates at submit and commit."""
    selected = {str(value) for value in image_ids if str(value)}
    if not selected:
        raise HardSampleSafetyError("HARD_SAMPLE_EMPTY_SELECTION")
    test_ids, test_hashes = frozen_test_identifiers(project_path)
    if selected & test_ids:
        raise HardSampleSafetyError("HARD_SAMPLE_FROZEN_TEST_FORBIDDEN")
    hashes = {
        str(value).strip().lower() for key, value in (content_hashes or {}).items()
        if str(key) in selected and str(value).strip()
    }
    if hashes & test_hashes:
        raise HardSampleSafetyError("HARD_SAMPLE_FROZEN_TEST_DUPLICATE_FORBIDDEN")


def difficulty_signals(
    predictions: Sequence[Mapping[str, Any]],
    *,
    width: int,
    height: int,
    uncertain_conf: float = 0.5,
) -> dict[str, Any]:
    """Extract measurable signals; 'no prediction' is NOT a verified FN."""
    if width <= 0 or height <= 0:
        raise ValueError("invalid source dimensions")
    signals: list[str] = []
    confidence_values = []
    small_targets = 0
    for row in predictions:
        confidence = float(row.get("confidence") or 0)
        coords = row.get("box") or []
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("non-finite model confidence")
        if len(coords) != 4 or not all(math.isfinite(float(value)) for value in coords):
            raise ValueError("invalid prediction bounding box")
        x1, y1, x2, y2 = (float(value) for value in coords)
        if x2 <= x1 or y2 <= y1:
            raise ValueError("invalid prediction box geometry")
        confidence_values.append(confidence)
        if ((x2 - x1) * (y2 - y1)) / (width * height) < 0.01:
            small_targets += 1
    if not predictions:
        signals.append("no_detection_unverified")
    if confidence_values and min(confidence_values) < uncertain_conf:
        signals.append("low_confidence")
    if small_targets:
        signals.append("small_target")
    if len(predictions) >= 5:
        signals.append("dense_targets")
    return {
        "signals": signals,
        "review_priority": min(100, 10 + 35 * int("low_confidence" in signals)
                               + 20 * int("small_target" in signals)
                               + 15 * int("dense_targets" in signals)
                               + 10 * int("no_detection_unverified" in signals)),
        "root_cause_confirmed": False,
        "ground_truth_compared": False,
    }



def compare_formal_gt(
    predictions: Sequence[Mapping[str, Any]],
    formal_boxes: Sequence[Mapping[str, Any]],
    *,
    operating_conf: float = 0.25,
    matching_iou: float = 0.5,
) -> dict[str, int]:
    """Confidence-first one-to-one GT comparison on already-reviewed training data."""
    def overlap(a, b):
        x1, y1 = max(a[0], b[0]), max(a[1], b[1])
        x2, y2 = min(a[2], b[2]), min(a[3], b[3])
        intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        aa = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
        bb = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
        return intersection / max(1e-12, aa + bb - intersection)

    truth = [
        {"label": str(box.get("label") or ""),
         "box": [float(box[k]) for k in ("x1", "y1", "x2", "y2")]}
        for box in formal_boxes
        if all(k in box for k in ("x1", "y1", "x2", "y2"))
    ]
    operating = sorted(
        [row for row in predictions if float(row.get("confidence") or 0) >= operating_conf],
        key=lambda row: -float(row.get("confidence") or 0),
    )
    matched = set()
    tp = 0
    for prediction in operating:
        label = str(prediction.get("label") or "")
        best, best_iou = None, -1.0
        for i, gt in enumerate(truth):
            if i in matched or gt["label"] != label:
                continue
            candidate = overlap(prediction["box"], gt["box"])
            if candidate >= matching_iou and candidate > best_iou:
                best, best_iou = i, candidate
        if best is not None:
            matched.add(best)
            tp += 1
    return {"true_positive": tp, "false_positive": len(operating)-tp,
            "false_negative": len(truth)-tp}


def inspect_formal_annotation(
    project_path: str | Path,
    image_id: str,
    predictions: Sequence[Mapping[str, Any]],
    label_scope: Sequence[str],
    initial_signals: Mapping[str, Any],
) -> dict[str, Any]:
    """Read formal training GT only after inference; incomplete scopes stay unverified."""
    from .annotation_repository import AnnotationRepository
    record = AnnotationRepository(project_path).get(str(image_id))
    if not isinstance(record, dict):
        return dict(initial_signals)
    scope = set(str(v) for v in record.get("annotation_scope") or [])
    state = str(record.get("annotation_state") or "").lower()
    if state not in {"annotated", "confirmed_empty"} or (
        "*" not in scope and not set(label_scope).issubset(scope)
    ):
        return dict(initial_signals)
    stats = compare_formal_gt(predictions, record.get("boxes") or [])
    signals = list(initial_signals.get("signals") or [])
    if stats["false_positive"]:
        signals.append("gt_disagreement_fp")
    if stats["false_negative"]:
        signals.append("gt_disagreement_fn")
    if not predictions and stats["false_negative"] == 0:
        signals = [code for code in signals if code != "no_detection_unverified"]
    return {
        **dict(initial_signals),
        "signals": list(dict.fromkeys(signals)),
        "review_priority": min(100, int(initial_signals.get("review_priority") or 0)
                               + 25 * int(bool(stats["false_positive"]))
                               + 30 * int(bool(stats["false_negative"]))),
        "ground_truth_compared": True,
        "gt_comparison": stats,
        "root_cause_confirmed": False,
    }


def infer_with_frozen_yolo(request: dict[str, Any], image: Mapping[str, Any]) -> dict[str, Any]:
    """Worker-only inference on a locally available, SHA-frozen trained PT.

    Explicitly requires a CUDA Worker: never load YOLO on a light controller
    merely because the control plane can enqueue AI_ANNOTATION jobs.
    """
    model_path = Path(str(request.get("mining_model_path") or ""))
    model_hash = str(request.get("mining_model_sha256") or "").lower()
    if model_path.suffix.lower() != ".pt" or not model_path.is_file() or model_path.name.lower() == "last.pt":
        raise HardSampleSafetyError("HARD_SAMPLE_MODEL_UNAVAILABLE_ON_WORKER")
    if not request.get("_hard_sample_model_verified"):
        if len(model_hash) != 64 or sha256_file(model_path) != model_hash:
            raise HardSampleSafetyError("HARD_SAMPLE_MODEL_IDENTITY_CHANGED")
        request["_hard_sample_model_verified"] = True
    import torch
    if not torch.cuda.is_available():
        raise HardSampleSafetyError("HARD_SAMPLE_CUDA_WORKER_REQUIRED")
    from ultralytics import YOLO

    detector = request.get("_hard_sample_detector")
    if detector is None:
        detector = YOLO(str(model_path))
        request["_hard_sample_detector"] = detector
    allowed = {str(value) for value in request.get("labels") or []}
    names = detector.names
    if isinstance(names, list):
        names = dict(enumerate(names))
    names = {int(k): str(v) for k, v in dict(names).items()}
    if not names or any(not code or code not in allowed for code in names.values()):
        raise HardSampleSafetyError("HARD_SAMPLE_MODEL_LABEL_MAPPING_REQUIRED")
    path = Path(str(image.get("path") or ""))
    if not path.is_file():
        raise HardSampleSafetyError("HARD_SAMPLE_MATERIAL_MISSING")
    results = detector.predict(source=str(path), conf=0.05, imgsz=640, device=0,
                               max_det=300, save=False, verbose=False)
    if not results:
        raise HardSampleSafetyError("HARD_SAMPLE_INFERENCE_RESULT_MISSING")
    result = results[0]
    boxes = getattr(result, "boxes", None)
    predictions = []
    candidates = []
    if boxes is not None:
        coordinates = boxes.xyxy.cpu().tolist()
        scores = boxes.conf.cpu().tolist()
        classes = boxes.cls.cpu().tolist()
        for index, (coord, conf, cls) in enumerate(zip(coordinates, scores, classes)):
            class_id = int(cls)
            if class_id not in names:
                raise HardSampleSafetyError("HARD_SAMPLE_UNKNOWN_MODEL_CLASS")
            x1, y1, x2, y2 = [float(value) for value in coord]
            label = names[class_id]
            row = {"box": [x1, y1, x2, y2], "confidence": float(conf), "label": label}
            predictions.append(row)
            candidates.append({
                "id": hashlib.sha256(f"{image.get('id')}:{index}:{model_hash}".encode()).hexdigest()[:16],
                "label": label, "x1": round(x1, 2), "y1": round(y1, 2),
                "x2": round(x2, 2), "y2": round(y2, 2),
                "confidence": round(float(conf), 6),
                "source": "ai_candidate",
            })
    signals = difficulty_signals(predictions, width=int(image.get("width") or 0),
                                 height=int(image.get("height") or 0))
    if request.get("_project_dir"):
        signals = inspect_formal_annotation(
            str(request["_project_dir"]), str(image.get("id") or ""),
            predictions, list(names.values()), signals,
        )
    return {
        "boxes": candidates,
        "provider": "ultralytics",
        "model": str(request.get("mining_version_id") or ""),
        "hard_sample_signals": signals["signals"],
        "hard_sample_priority": signals["review_priority"],
        "ground_truth_compared": bool(signals["ground_truth_compared"]),
        "gt_comparison": signals.get("gt_comparison"),
        "root_cause_confirmed": False,
    }


def reviewed_mining_feedback_evidence(*, task_id: str, request: Mapping[str, Any],
        candidate: Mapping[str, Any], material: Mapping[str, Any],
        annotation: Mapping[str, Any], commit_summary: Mapping[str, Any]) -> dict[str, Any]:
    """Project reviewed task/journal and current formal GT into feedback evidence.

    Callers must require a successful task and recheck frozen Test identities.
    Candidate boxes are mutable during review, so cannot prove original predictions.
    The journal lacks a GT hash/version; compare every available journal field and
    bind the current formal annotation digest into the immutable preview identity.
    """
    from .online_feedback import validate_prediction_evidence

    def sha(value, field):
        value = str(value or "").strip().lower()
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError(f"reviewed mining {field} must be SHA256")
        return value

    task_id = str(task_id or "").strip()
    image_id = str(candidate.get("image_id") or "")
    if (not task_id or len(task_id) > 200 or not image_id
        or request.get("mode") != "hard_sample_yolo"
        or candidate.get("accepted") is not True
        or candidate.get("status") not in {"success", "empty"}
        or image_id not in list(request.get("image_ids") or [])
        or str(material.get("id") or "") != image_id):
        raise ValueError("reviewed mining requires accepted task-owned material")
    input_sha = sha((request.get("source_hashes") or {}).get(image_id), "source hash")
    if sha(material.get("content_sha256"), "material hash") != input_sha:
        raise ValueError("reviewed mining material content changed")
    annotation_state = str(annotation.get("annotation_state") or "")
    annotation_hash = sha(annotation.get("content_digest"), "annotation hash")
    boxes = list(annotation.get("boxes") or [])
    if annotation_state not in {"annotated", "confirmed_empty"}:
        raise ValueError("reviewed mining requires formal annotation truth")
    if (annotation_state == "annotated") != bool(boxes):
        raise ValueError("reviewed mining annotation state disagrees with formal boxes")
    labels = sorted({str(box.get("label") or "") for box in boxes})
    if (not isinstance(commit_summary, Mapping)
        or commit_summary.get("image_id") != image_id
        or commit_summary.get("box_count") != len(boxes)
        or sorted(commit_summary.get("labels") or []) != labels
        or commit_summary.get("annotation_state") != annotation_state
        or commit_summary.get("annotation_origin") != annotation.get("annotation_origin")):
        raise ValueError("reviewed mining formal annotation no longer matches commit journal")
    # Future journals may carry stronger identity; honor it if present.
    for field, current in (("content_digest", annotation_hash), ("annotation_hash", annotation_hash),
                           ("version", annotation.get("version"))):
        if field in commit_summary and commit_summary[field] != current:
            raise ValueError("reviewed mining annotation identity changed")
    model_sha = sha(request.get("mining_model_sha256"), "model hash")
    identity = {"task_id":task_id, "image_id":image_id, "model_sha256":model_sha,
        "input_sha256":input_sha, "annotation_hash":annotation_hash, "annotation_state":annotation_state}
    canonical = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    prediction_hash = hashlib.sha256(canonical(identity).encode()).hexdigest()
    evidence = validate_prediction_evidence({
        "schema_version":1, "prediction_id":"hmreview_" + prediction_hash[:55],
        "algorithm_id":request.get("mining_algorithm_id"), "version_id":request.get("mining_version_id"),
        "model_sha256":model_sha, "input_sha256":input_sha,
        "width":material.get("width"), "height":material.get("height"),
        "original_filename":material.get("filename"), "detections":[], "engine":"ultralytics",
        "source_channel":"hard_sample_review", "external_source":task_id, "external_sample_id":image_id,
        "prediction_evidence_status":"unavailable_review_boxes_mutable",
    })
    digest = hashlib.sha256(canonical({"evidence":evidence, **identity,
        "commit_summary":dict(commit_summary)}).encode()).hexdigest()
    return {"evidence":evidence, "candidate_digest":digest,
        "annotation_hash":annotation_hash, "annotation_state":annotation_state}
