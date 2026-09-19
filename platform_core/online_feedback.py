"""Reviewable online inference feedback.

This repository owns only feedback evidence/status. Material bytes remain owned by
MaterialRepository/StorageManager and annotation truth remains owned by
AnnotationRepository.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
FEEDBACK_TYPES = {"correct", "false_positive", "needs_correction"}
TERMINAL_STATUSES = {"confirmed", "dismissed"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS online_feedback (
    id TEXT PRIMARY KEY,
    prediction_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    feedback_type TEXT NOT NULL,
    algorithm_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    model_sha256 TEXT NOT NULL,
    input_sha256 TEXT NOT NULL,
    material_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    confirmed_at TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_online_feedback_status
    ON online_feedback(status, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS ix_online_feedback_version
    ON online_feedback(algorithm_id, version_id, created_at DESC);
"""


def _text(value: object, limit: int = 1000) -> str:
    return str(value or "").strip()[:limit]


def _sha(value: object, field: str) -> str:
    value = _text(value, 128).lower()
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{field} must be a SHA256 identity")
    return value


def _canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )


def _number(value: object, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{field} must be numeric") from error
    if result != result or result in {float("inf"), float("-inf")}:
        raise ValueError(f"{field} must be finite")
    return result


def validate_prediction_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or int(value.get("schema_version") or 0) != 1:
        raise ValueError("prediction evidence schema is invalid")
    prediction_id = _text(value.get("prediction_id"), 64)
    if (
        not prediction_id
        or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in prediction_id)
    ):
        raise ValueError("prediction_id is invalid")
    algorithm_id = _text(value.get("algorithm_id"), 200)
    version_id = _text(value.get("version_id"), 200)
    if not algorithm_id or not version_id:
        raise ValueError("prediction evidence must reference an algorithm version")
    width = int(value.get("width") or 0)
    height = int(value.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ValueError("prediction image dimensions are invalid")
    detections = list(value.get("detections") or [])
    if len(detections) > 10000:
        raise ValueError("prediction evidence contains too many detections")
    normalized = []
    for index, row in enumerate(detections):
        if not isinstance(row, Mapping):
            raise ValueError("prediction detection must be an object")
        x1 = _number(row.get("x1"), "x1")
        y1 = _number(row.get("y1"), "y1")
        x2 = _number(row.get("x2"), "x2")
        y2 = _number(row.get("y2"), "y2")
        confidence = _number(row.get("confidence"), "confidence")
        if (
            not (0 <= x1 < x2 <= width)
            or not (0 <= y1 < y2 <= height)
            or not (0 <= confidence <= 1)
        ):
            raise ValueError("prediction detection is outside image bounds")
        label = _text(row.get("label"), 200)
        if not label:
            raise ValueError("prediction detection label is empty")
        normalized.append({
            "index": index,
            "class_id": int(row.get("class_id") or 0),
            "label": label,
            "confidence": confidence,
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        })
    result = {
        "schema_version": 1,
        "prediction_id": prediction_id,
        "algorithm_id": algorithm_id,
        "version_id": version_id,
        "model_sha256": _sha(value.get("model_sha256"), "model_sha256"),
        "input_sha256": _sha(value.get("input_sha256"), "input_sha256"),
        "original_filename": _text(value.get("original_filename"), 240),
        "input_file": _text(value.get("input_file"), 240),
        "width": width,
        "height": height,
        "confidence": _number(value.get("confidence") or 0, "confidence threshold"),
        "engine": _text(value.get("engine"), 100),
        "detections": normalized,
        "created_at": _text(value.get("created_at"), 100),
    }
    source_channel = _text(value.get("source_channel"), 100)
    external_source = _text(value.get("external_source"), 200)
    external_sample_id = _text(value.get("external_sample_id"), 200)
    if source_channel:
        result["source_channel"] = source_channel
    if external_source:
        result["external_source"] = external_source
    if external_sample_id:
        result["external_sample_id"] = external_sample_id
    return result


def public_feedback(value: Mapping[str, Any], *, compact: bool = False) -> dict[str, Any]:
    row = dict(value)
    payload = row.get("payload")
    if not isinstance(payload, Mapping):
        raw = row.get("payload_json")
        payload = json.loads(raw) if isinstance(raw, str) and raw else {}
    source = dict(payload.get("source") or {})
    source.pop("input_file", None)
    if compact:
        source["detection_count"] = len(source.pop("detections", []) or [])
    return {
        "schema_version": SCHEMA_VERSION,
        "id": str(row.get("id") or ""),
        "prediction_id": str(row.get("prediction_id") or ""),
        "status": str(row.get("status") or ""),
        "feedback_type": str(row.get("feedback_type") or ""),
        "algorithm_id": str(row.get("algorithm_id") or ""),
        "version_id": str(row.get("version_id") or ""),
        "model_sha256": str(row.get("model_sha256") or ""),
        "input_sha256": str(row.get("input_sha256") or ""),
        "material_id": str(row.get("material_id") or ""),
        "created_at": str(row.get("created_at") or ""),
        "confirmed_at": str(row.get("confirmed_at") or ""),
        "note": _text(payload.get("note"), 1000),
        "source": source,
        "result": dict(payload.get("result") or {}),
    }


def build_supplement_candidate(
    feedback: Mapping[str, Any],
    material: Mapping[str, Any] | None,
    annotation: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Project one confirmed feedback record onto current material/annotation truth."""
    public = public_feedback(feedback)
    if public["status"] != "confirmed":
        raise ValueError("supplement candidate requires confirmed feedback")
    material_id = str(public.get("material_id") or "")
    material = dict(material or {})
    annotation = dict(annotation or {})
    reasons: list[str] = []
    if not material_id or str(material.get("id") or "") != material_id:
        reasons.append("MATERIAL_MISSING")
    input_sha = _sha(public.get("input_sha256"), "input_sha256")
    material_sha = str(material.get("content_sha256") or "").strip().lower()
    if material_id and material and material_sha != input_sha:
        reasons.append("MATERIAL_CONTENT_CHANGED")

    annotation_state = str(
        annotation.get("annotation_state")
        or material.get("annotation_state")
        or "unannotated"
    )
    annotation_hash = str(
        annotation.get("content_digest")
        or material.get("annotation_hash")
        or ""
    ).strip().lower()
    if annotation_state in {"annotated", "confirmed_empty"} and (
        len(annotation_hash) != 64
        or any(ch not in "0123456789abcdef" for ch in annotation_hash)
    ):
        reasons.append("ANNOTATION_HASH_MISSING")

    feedback_type = str(public.get("feedback_type") or "")
    if feedback_type == "correct" and annotation_state != "annotated":
        reasons.append("ANNOTATION_TRUTH_REQUIRED")
    elif feedback_type == "false_positive" and annotation_state != "confirmed_empty":
        reasons.append("NEGATIVE_TRUTH_CHANGED")
    elif feedback_type == "needs_correction" and annotation_state not in {"annotated", "confirmed_empty"}:
        reasons.append("ANNOTATION_REQUIRED")

    boxes = list(annotation.get("boxes") or [])
    labels = sorted({
        str(box.get("label") or box.get("code") or "").strip()
        for box in boxes
        if isinstance(box, Mapping) and str(box.get("label") or box.get("code") or "").strip()
    })
    scope = sorted({
        str(value).strip()
        for value in list(annotation.get("annotation_scope") or material.get("annotation_scope") or [])
        if str(value).strip()
    })
    if not labels and annotation_state == "confirmed_empty":
        labels = list(scope)

    source = dict(public.get("source") or {})
    payload = {
        "schema_version": 1,
        "feedback_id": str(public["id"]),
        "feedback_type": feedback_type,
        "material_id": material_id,
        "algorithm_id": str(public["algorithm_id"]),
        "version_id": str(public["version_id"]),
        "model_sha256": _sha(public.get("model_sha256"), "model_sha256"),
        "input_sha256": input_sha,
        "confirmed_at": str(public.get("confirmed_at") or ""),
        "annotation_state": annotation_state,
        "annotation_hash": annotation_hash,
        "annotation_scope": scope,
        "labels": labels,
        "source_channel": _text(source.get("source_channel") or "platform_prediction", 100),
        "external_source": _text(source.get("external_source"), 200),
        "external_sample_id": _text(source.get("external_sample_id"), 200),
        "needs_manual_annotation": feedback_type == "needs_correction"
        and annotation_state not in {"annotated", "confirmed_empty"},
        "eligible": not reasons,
        "reason_codes": sorted(set(reasons)),
    }
    digest_payload = {key: value for key, value in payload.items() if key != "eligible"}
    return {
        **payload,
        "candidate_digest": hashlib.sha256(_canonical(digest_payload).encode("utf-8")).hexdigest(),
    }


def build_supplement_candidate_set(
    action: Mapping[str, Any],
    candidates: list[Mapping[str, Any]],
    *,
    frozen_at: str,
) -> dict[str, Any]:
    if (
        not isinstance(action, Mapping)
        or str(action.get("status") or "") != "confirmed"
        or str(action.get("action") or "") != "supplement_data"
    ):
        raise ValueError("supplement candidate set requires a confirmed supplement_data action")
    source = dict(action.get("source") or {})
    action_id = _sha(action.get("action_id"), "action_id")
    algorithm_id = _text(source.get("algorithm_id"), 200)
    version_id = _text(source.get("version_id"), 200)
    if not algorithm_id or not version_id:
        raise ValueError("supplement_data action source is incomplete")
    selected = sorted(
        (dict(row) for row in candidates),
        key=lambda row: str(row.get("feedback_id") or ""),
    )
    if not selected or len(selected) > 500:
        raise ValueError("select between 1 and 500 feedback candidates")
    feedback_ids: list[str] = []
    material_ids: list[str] = []
    normalized = []
    for row in selected:
        if row.get("eligible") is not True:
            raise ValueError("ineligible feedback cannot be frozen into supplement data")
        if (
            str(row.get("algorithm_id") or "") != algorithm_id
            or str(row.get("version_id") or "") != version_id
        ):
            raise ValueError("feedback candidate does not belong to the supplement action version")
        feedback_id = _text(row.get("feedback_id"), 100)
        material_id = _text(row.get("material_id"), 100)
        digest = _sha(row.get("candidate_digest"), "candidate_digest")
        if not feedback_id or not material_id:
            raise ValueError("feedback candidate identity is incomplete")
        feedback_ids.append(feedback_id)
        material_ids.append(material_id)
        normalized.append({
            "feedback_id": feedback_id,
            "feedback_type": _text(row.get("feedback_type"), 100),
            "material_id": material_id,
            "candidate_digest": digest,
            "annotation_hash": _sha(row.get("annotation_hash"), "annotation_hash"),
            "annotation_state": _text(row.get("annotation_state"), 100),
            "labels": sorted({_text(v, 200) for v in list(row.get("labels") or []) if _text(v, 200)}),
            "model_sha256": _sha(row.get("model_sha256"), "model_sha256"),
            "input_sha256": _sha(row.get("input_sha256"), "input_sha256"),
            "confirmed_at": _text(row.get("confirmed_at"), 100),
        })
    if len(set(feedback_ids)) != len(feedback_ids):
        raise ValueError("feedback candidate selection contains duplicates")
    identity = {
        "schema_version": 1,
        "action_id": action_id,
        "algorithm_id": algorithm_id,
        "version_id": version_id,
        "feedback_ids": feedback_ids,
        "material_ids": material_ids,
        "candidates": normalized,
    }
    return {
        **identity,
        "candidate_set_id": hashlib.sha256(_canonical(identity).encode("utf-8")).hexdigest(),
        "status": "confirmed",
        "frozen_at": _text(frozen_at, 100),
        "automatic_execution": False,
    }


def build_supplement_training_provenance(
    candidate_set: Mapping[str, Any],
    selected_material_ids: Iterable[object],
    truth_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Freeze and verify the feedback subset actually used by one training snapshot."""
    if not isinstance(candidate_set, Mapping) or str(candidate_set.get("status") or "") != "confirmed":
        raise ValueError("supplement training provenance requires a confirmed candidate set")
    try:
        schema_version = int(candidate_set.get("schema_version") or 0)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("supplement candidate set schema_version is invalid") from error
    if schema_version != 1:
        raise ValueError("unsupported supplement candidate set schema_version")

    action_id = _sha(candidate_set.get("action_id"), "action_id")
    candidate_set_id = _sha(candidate_set.get("candidate_set_id"), "candidate_set_id")
    algorithm_id = _text(candidate_set.get("algorithm_id"), 200)
    version_id = _text(candidate_set.get("version_id"), 200)
    raw_candidates = [
        dict(row) for row in list(candidate_set.get("candidates") or [])
        if isinstance(row, Mapping)
    ]
    if not algorithm_id or not version_id or not raw_candidates or len(raw_candidates) > 500:
        raise ValueError("supplement candidate set identity is incomplete")

    source_identity = {
        "schema_version": schema_version,
        "action_id": action_id,
        "algorithm_id": algorithm_id,
        "version_id": version_id,
        "feedback_ids": [str(value) for value in list(candidate_set.get("feedback_ids") or [])],
        "material_ids": [str(value) for value in list(candidate_set.get("material_ids") or [])],
        "candidates": raw_candidates,
    }
    expected_candidate_set_id = hashlib.sha256(
        _canonical(source_identity).encode("utf-8")
    ).hexdigest()
    if expected_candidate_set_id != candidate_set_id:
        raise ValueError("supplement candidate set identity does not match its frozen contents")

    selected = {str(value) for value in selected_material_ids if str(value)}
    truths: dict[str, dict[str, Any]] = {}
    for raw in truth_rows:
        row = dict(raw)
        material_id = str(
            row.get("material_id") or row.get("image_id") or row.get("id") or ""
        )
        if material_id:
            truths[material_id] = row

    adopted = []
    for raw in raw_candidates:
        material_id = _text(raw.get("material_id"), 100)
        if material_id not in selected:
            continue
        truth = truths.get(material_id)
        if truth is None:
            raise ValueError(f"supplement material {material_id} is missing from training truth")
        input_sha = _sha(raw.get("input_sha256"), "input_sha256")
        current_sha = _sha(truth.get("content_sha256"), "content_sha256")
        if current_sha != input_sha:
            raise ValueError(f"supplement material {material_id} content changed after candidate freeze")
        annotation_hash = _sha(raw.get("annotation_hash"), "annotation_hash")
        current_annotation_hash = _sha(
            truth.get("annotation_hash") or truth.get("content_digest"),
            "current annotation_hash",
        )
        if current_annotation_hash != annotation_hash:
            raise ValueError(f"supplement material {material_id} annotation changed after candidate freeze")
        annotation_state = _text(raw.get("annotation_state"), 100)
        current_state = _text(truth.get("annotation_state"), 100)
        if current_state != annotation_state:
            raise ValueError(f"supplement material {material_id} annotation state changed after candidate freeze")
        adopted.append({
            "feedback_id": _text(raw.get("feedback_id"), 100),
            "feedback_type": _text(raw.get("feedback_type"), 100),
            "material_id": material_id,
            "candidate_digest": _sha(raw.get("candidate_digest"), "candidate_digest"),
            "annotation_hash": annotation_hash,
            "annotation_state": annotation_state,
            "model_sha256": _sha(raw.get("model_sha256"), "model_sha256"),
            "input_sha256": input_sha,
        })

    if not adopted:
        raise ValueError("supplement candidate set has no material in the final training selection")
    adopted = sorted(adopted, key=lambda row: (row["material_id"], row["feedback_id"]))
    adoption_identity = {
        "schema_version": 1,
        "candidate_set_id": candidate_set_id,
        "action_id": action_id,
        "algorithm_id": algorithm_id,
        "version_id": version_id,
        "adopted_candidates": adopted,
    }
    return {
        **adoption_identity,
        "adoption_id": hashlib.sha256(
            _canonical(adoption_identity).encode("utf-8")
        ).hexdigest(),
        "source_candidate_count": len(raw_candidates),
        "adopted_candidate_count": len(adopted),
        "adopted_material_count": len({row["material_id"] for row in adopted}),
        "adopted_feedback_ids": [row["feedback_id"] for row in adopted],
        "adopted_material_ids": sorted({row["material_id"] for row in adopted}),
        "automatic_execution": False,
    }


class OnlineFeedbackRepository:
    def __init__(self, project_path: str | Path):
        self.project_path = Path(project_path)
        self.project_path.mkdir(parents=True, exist_ok=True)
        self.path = self.project_path / "online_feedback.sqlite3"
        with closing(self._connect()) as db:
            db.executescript(_SCHEMA)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    @staticmethod
    def _decode(row) -> dict[str, Any] | None:
        if row is None:
            return None
        value = dict(row)
        value["payload"] = json.loads(value.pop("payload_json"))
        return value

    def get(self, feedback_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as db:
            return self._decode(db.execute(
                "SELECT * FROM online_feedback WHERE id=?", (str(feedback_id),)
            ).fetchone())

    def get_many(self, feedback_ids) -> list[dict[str, Any]]:
        ids = list(dict.fromkeys(str(value) for value in feedback_ids if str(value)))
        if len(ids) > 500:
            raise ValueError("feedback batch lookup is limited to 500 IDs")
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        with closing(self._connect()) as db:
            rows = db.execute(
                f"SELECT * FROM online_feedback WHERE id IN ({marks})", ids
            ).fetchall()
        by_id = {str(row["id"]): self._decode(row) for row in rows}
        return [by_id[value] for value in ids if value in by_id]

    def list_confirmed_for_version(
        self, algorithm_id: str, version_id: str, *, limit: int = 500,
    ) -> tuple[list[dict[str, Any]], int]:
        limit = min(500, max(1, int(limit)))
        with closing(self._connect()) as db:
            total = int(db.execute(
                "SELECT COUNT(*) FROM online_feedback "
                "WHERE status='confirmed' AND algorithm_id=? AND version_id=?",
                (str(algorithm_id), str(version_id)),
            ).fetchone()[0])
            rows = db.execute(
                "SELECT * FROM online_feedback "
                "WHERE status='confirmed' AND algorithm_id=? AND version_id=? "
                "ORDER BY confirmed_at DESC,id DESC LIMIT ?",
                (str(algorithm_id), str(version_id), limit),
            ).fetchall()
        return [self._decode(row) for row in rows], total

    def list(self, *, status: str = "", limit: int = 100) -> list[dict[str, Any]]:
        limit = min(500, max(1, int(limit)))
        with closing(self._connect()) as db:
            if status:
                rows = db.execute(
                    "SELECT * FROM online_feedback WHERE status=? "
                    "ORDER BY created_at DESC,id DESC LIMIT ?",
                    (str(status), limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM online_feedback ORDER BY created_at DESC,id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._decode(row) for row in rows]

    def stage(
        self,
        evidence: Mapping[str, Any],
        *,
        feedback_type: str,
        note: str,
        created_at: str,
    ) -> tuple[dict[str, Any], bool]:
        source = validate_prediction_evidence(evidence)
        feedback_type = str(feedback_type or "").strip()
        if feedback_type not in FEEDBACK_TYPES:
            raise ValueError("feedback_type is invalid")
        identity = {
            "prediction_id": source["prediction_id"],
            "input_sha256": source["input_sha256"],
            "algorithm_id": source["algorithm_id"],
            "version_id": source["version_id"],
        }
        feedback_id = "feedback_" + hashlib.sha256(json.dumps(
            identity, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()[:24]
        payload = {
            "schema_version": SCHEMA_VERSION,
            "source": source,
            "note": _text(note, 1000),
            "result": {},
        }
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                existing = db.execute(
                    "SELECT * FROM online_feedback WHERE prediction_id=?",
                    (source["prediction_id"],),
                ).fetchone()
                if existing is not None:
                    current = self._decode(existing)
                    if current["status"] in TERMINAL_STATUSES:
                        if current["feedback_type"] == feedback_type:
                            db.execute("COMMIT")
                            return current, True
                        raise ValueError("prediction feedback is already finalized")
                    db.execute(
                        "UPDATE online_feedback SET feedback_type=?,payload_json=? WHERE id=?",
                        (
                            feedback_type,
                            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                            current["id"],
                        ),
                    )
                    row = db.execute(
                        "SELECT * FROM online_feedback WHERE id=?", (current["id"],)
                    ).fetchone()
                    db.execute("COMMIT")
                    return self._decode(row), True
                db.execute(
                    """INSERT INTO online_feedback
                       (id,prediction_id,status,feedback_type,algorithm_id,version_id,
                        model_sha256,input_sha256,material_id,created_at,confirmed_at,payload_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        feedback_id, source["prediction_id"], "pending_review", feedback_type,
                        source["algorithm_id"], source["version_id"], source["model_sha256"],
                        source["input_sha256"], "", str(created_at), "",
                        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    ),
                )
                row = db.execute(
                    "SELECT * FROM online_feedback WHERE id=?", (feedback_id,)
                ).fetchone()
                db.execute("COMMIT")
                return self._decode(row), False
            except Exception:
                db.execute("ROLLBACK")
                raise

    def finalize(
        self,
        feedback_id: str,
        *,
        expected_feedback_type: str,
        material_id: str,
        result: Mapping[str, Any],
        confirmed_at: str,
        status: str = "confirmed",
    ) -> tuple[dict[str, Any], bool]:
        if status not in TERMINAL_STATUSES:
            raise ValueError("feedback terminal status is invalid")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT * FROM online_feedback WHERE id=?", (str(feedback_id),)
                ).fetchone()
                current = self._decode(row)
                if current is None:
                    raise KeyError("feedback not found")
                if current["feedback_type"] != str(expected_feedback_type):
                    raise ValueError("feedback type changed; refresh before confirming")
                if current["status"] in TERMINAL_STATUSES:
                    db.execute("COMMIT")
                    return current, True
                payload = dict(current["payload"])
                payload["result"] = dict(result)
                db.execute(
                    "UPDATE online_feedback SET status=?,material_id=?,confirmed_at=?,payload_json=? "
                    "WHERE id=?",
                    (
                        status, str(material_id or ""), str(confirmed_at),
                        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                        current["id"],
                    ),
                )
                row = db.execute(
                    "SELECT * FROM online_feedback WHERE id=?", (current["id"],)
                ).fetchone()
                db.execute("COMMIT")
                return self._decode(row), False
            except Exception:
                db.execute("ROLLBACK")
                raise
