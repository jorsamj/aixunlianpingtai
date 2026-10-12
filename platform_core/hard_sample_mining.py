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
            row = {"box": [x1, y1, x2, y2], "confidence": float(conf)}
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
    return {
        "boxes": candidates,
        "provider": "ultralytics",
        "model": str(request.get("mining_version_id") or ""),
        "hard_sample_signals": signals["signals"],
        "hard_sample_priority": signals["review_priority"],
        "ground_truth_compared": False,
        "root_cause_confirmed": False,
    }
