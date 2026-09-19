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
from typing import Any, Mapping


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
