"""Control-plane verification and commit for remote material cleaning results.

The Agent performs image download/decoding and publishes metrics only. The control
plane owns rule evaluation and all durable MATERIAL_BATCH/CLEAN mutations.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from filelock import FileLock, Timeout

from .annotation_quality import audit_cleaning_annotations
from .cleaning import DurableHashIndex, clean_options, metric_issues
from .material_batches import BatchSelection, SELECTION_REF
from .material_repository import MaterialRepository
from .task_runtime.models import utc_now


MAX_REMOTE_CLEAN_ITEMS = 250_000
MAX_REMOTE_CLEAN_RESULT_BYTES = 512 * 1024 * 1024
MAX_REMOTE_CLEAN_LINE_BYTES = 256 * 1024


class RemoteCleaningError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409):
        self.code = str(code)
        self.status_code = int(status_code)
        super().__init__(str(message))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite(value: object, field: str, *, allow_none: bool = False) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool):
        raise RemoteCleaningError("REMOTE_CLEANING_METRICS_INVALID", f"{field} must be numeric", 422)
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise RemoteCleaningError("REMOTE_CLEANING_METRICS_INVALID", f"{field} must be numeric", 422) from error
    if not math.isfinite(number):
        raise RemoteCleaningError("REMOTE_CLEANING_METRICS_INVALID", f"{field} must be finite", 422)
    return number


def _metrics(value: object, expected_sha: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RemoteCleaningError("REMOTE_CLEANING_METRICS_INVALID", "analyzed item metrics must be an object", 422)
    try:
        width = int(value.get("width"))
        height = int(value.get("height"))
        dhash = int(value.get("dhash"))
    except (TypeError, ValueError) as error:
        raise RemoteCleaningError("REMOTE_CLEANING_METRICS_INVALID", "width/height/dhash are invalid", 422) from error
    digest = str(value.get("sha256") or "").strip().lower()
    if width <= 0 or height <= 0 or not (0 <= dhash < 2**64) or digest != expected_sha:
        raise RemoteCleaningError("REMOTE_CLEANING_METRICS_INVALID", "image metrics do not match durable source evidence", 409)
    brightness = _finite(value.get("brightness"), "brightness")
    if brightness is None or not (0.0 <= brightness <= 255.0):
        raise RemoteCleaningError("REMOTE_CLEANING_METRICS_INVALID", "brightness is outside 0..255", 422)
    blur_score = _finite(value.get("blur_score"), "blur_score", allow_none=True)
    entropy = _finite(value.get("entropy"), "entropy", allow_none=True)
    if blur_score is not None and blur_score < 0:
        raise RemoteCleaningError("REMOTE_CLEANING_METRICS_INVALID", "blur_score must be nonnegative", 422)
    if entropy is not None and entropy < 0:
        raise RemoteCleaningError("REMOTE_CLEANING_METRICS_INVALID", "entropy must be nonnegative", 422)
    return {
        "width": width,
        "height": height,
        "sha256": digest,
        "dhash": dhash,
        "blur_score": round(float(blur_score), 3) if blur_score is not None else None,
        "brightness": round(float(brightness), 3),
        "entropy": round(float(entropy), 3) if entropy is not None else None,
        "analysis_downsampled": bool(value.get("analysis_downsampled")),
    }


def _read_json_line(stream, *, label: str) -> dict[str, Any]:
    raw = stream.readline(MAX_REMOTE_CLEAN_LINE_BYTES + 1)
    if not raw:
        raise RemoteCleaningError("REMOTE_CLEANING_REVIEW_TRUNCATED", f"{label} is missing", 409)
    if len(raw) > MAX_REMOTE_CLEAN_LINE_BYTES:
        raise RemoteCleaningError("REMOTE_CLEANING_REVIEW_TOO_LARGE", f"{label} exceeds the line-size safety limit", 413)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RemoteCleaningError("REMOTE_CLEANING_REVIEW_INVALID", f"{label} is not valid JSON", 422) from error
    if not isinstance(value, dict):
        raise RemoteCleaningError("REMOTE_CLEANING_REVIEW_INVALID", f"{label} must be an object", 422)
    return value


def commit_remote_cleaning_review(
    *,
    artifacts,
    task,
    project_path: str | Path,
    payload: Mapping[str, Any],
    review_path: str | Path,
    execution_generation: int,
    expected_sha256: str,
    expected_size_bytes: int,
) -> dict[str, Any]:
    """Verify one Agent metrics review and commit existing MATERIAL_BATCH/CLEAN truth."""
    path = Path(review_path)
    expected_sha = str(expected_sha256 or "").strip().lower()
    expected_size = int(expected_size_bytes or 0)
    if (
        not path.is_file()
        or expected_size <= 0
        or expected_size > MAX_REMOTE_CLEAN_RESULT_BYTES
        or int(path.stat().st_size) != expected_size
        or _sha256(path) != expected_sha
    ):
        raise RemoteCleaningError(
            "REMOTE_CLEANING_REVIEW_CHANGED",
            "downloaded cleaning review does not match confirmed size/SHA256 evidence",
            409,
        )
    if str(payload.get("operation") or "").strip().upper() != "CLEAN":
        raise RemoteCleaningError("REMOTE_CLEANING_OPERATION_INVALID", "task is not a CLEAN material batch", 422)
    options = clean_options(payload.get("options") or {})
    selection_path = artifacts.artifact_path(str(task.task_id), SELECTION_REF)
    if not selection_path.is_file():
        raise RemoteCleaningError("REMOTE_CLEANING_SELECTION_UNAVAILABLE", "frozen cleaning selection is missing", 409)

    lock = FileLock(str(selection_path) + ".lock", timeout=60)
    try:
        lock.acquire()
    except Timeout as error:
        raise RemoteCleaningError("REMOTE_CLEANING_COMMIT_BUSY", "cleaning result commit is busy", 409) from error
    materials = MaterialRepository(Path(project_path))
    try:
        manifest = BatchSelection(selection_path)
        try:
            if not manifest.frozen():
                raise RemoteCleaningError("REMOTE_CLEANING_SELECTION_UNAVAILABLE", "cleaning selection is not frozen", 409)
            total = int(manifest.database.execute("SELECT COUNT(*) FROM selection").fetchone()[0])
            if total > MAX_REMOTE_CLEAN_ITEMS:
                raise RemoteCleaningError("REMOTE_CLEANING_SELECTION_TOO_LARGE", "cleaning selection exceeds 250000 items", 413)
            index = DurableHashIndex(manifest.database, lambda: None)
            with path.open("r", encoding="utf-8", newline="") as stream:
                header = _read_json_line(stream, label="cleaning review header")
                if (
                    int(header.get("schema_version") or 0) != 1
                    or str(header.get("task_id") or "") != str(task.task_id)
                    or str(header.get("project_id") or "") != str(task.project_id)
                    or int(header.get("execution_generation") or 0) != int(execution_generation)
                    or str(header.get("operation") or "") != "CLEAN"
                    or int(header.get("total") or -1) != total
                ):
                    raise RemoteCleaningError("REMOTE_CLEANING_REVIEW_IDENTITY_MISMATCH", "cleaning review identity does not match durable task truth", 409)

                selected_ids = [
                    str(row[0])
                    for row in manifest.database.execute("SELECT image_id FROM selection ORDER BY image_id")
                ]
                with manifest.transaction():
                    manifest.database.execute("DELETE FROM clean_results")
                    manifest.database.execute("DELETE FROM clean_hashes")
                    manifest.database.execute("DELETE FROM clean_bands")
                    manifest.database.execute("UPDATE meta SET value='0' WHERE key='clean_flagged'")
                    manifest.database.execute("UPDATE selection SET state='pending', error=NULL")

                    for start in range(0, total, 500):
                        batch_ids = selected_ids[start:start + 500]
                        material_rows = materials.get_many(batch_ids)
                        by_id = {str(row["id"]): row for row in material_rows}
                        if set(by_id) != set(batch_ids):
                            raise RemoteCleaningError("REMOTE_CLEANING_SELECTION_CHANGED", "selected material no longer exists", 409)
                        for image_id in batch_ids:
                            item = _read_json_line(stream, label=f"cleaning result {image_id}")
                            if str(item.get("image_id") or "") != image_id:
                                raise RemoteCleaningError("REMOTE_CLEANING_REVIEW_ORDER_INVALID", "cleaning review is not the exact frozen selection order", 409)
                            material = by_id[image_id]
                            source_sha = str(material.get("content_sha256") or "").strip().lower()
                            try:
                                source_size = int(material.get("size_bytes") or 0)
                            except (TypeError, ValueError):
                                source_size = 0
                            if (
                                len(source_sha) != 64
                                or str(item.get("source_sha256") or "").strip().lower() != source_sha
                                or int(item.get("source_size_bytes") or 0) != source_size
                            ):
                                raise RemoteCleaningError("REMOTE_CLEANING_SOURCE_CHANGED", f"material {image_id} changed after selection freeze", 409)

                            status = str(item.get("status") or "").strip().lower()
                            inspected_at = utc_now()
                            near_indexed = False
                            if status == "analyzed":
                                metrics = _metrics(item.get("metrics"), source_sha)
                                issues, near_indexed = metric_issues(metrics, options, image_id, index)
                                result = {
                                    "image_id": image_id,
                                    "filename": material.get("filename"),
                                    "status": "succeeded",
                                    "metrics": metrics,
                                    "issues": issues,
                                    "suggest_delete": bool(issues),
                                    "inspected_at": inspected_at,
                                }
                                index.remember(image_id, metrics, near_indexed)
                                state, error_text = "succeeded", None
                            elif status == "corrupt" and options["corrupt_check"]:
                                detail = str(item.get("error") or "image decode failed")[:1000]
                                issues = [{"code": "corrupt", "name": "图片损坏", "detail": detail}]
                                result = {
                                    "image_id": image_id,
                                    "filename": material.get("filename"),
                                    "status": "succeeded",
                                    "metrics": {},
                                    "issues": issues,
                                    "suggest_delete": True,
                                    "inspected_at": inspected_at,
                                }
                                state, error_text = "succeeded", None
                            elif status in {"failed", "corrupt"}:
                                error_text = str(item.get("error") or "remote cleaning analysis failed")[:1000]
                                result = {
                                    "image_id": image_id,
                                    "filename": material.get("filename"),
                                    "status": "failed",
                                    "error": error_text,
                                    "metrics": {},
                                    "issues": [],
                                    "suggest_delete": False,
                                    "inspected_at": inspected_at,
                                }
                                state = "failed"
                            else:
                                raise RemoteCleaningError("REMOTE_CLEANING_REVIEW_INVALID", f"material {image_id} has invalid analysis status", 422)

                            flagged = int(bool(result["issues"]))
                            manifest.database.execute(
                                "INSERT INTO clean_results(image_id,result_json,flagged) VALUES (?,?,?)",
                                (image_id, json.dumps(result, ensure_ascii=False), flagged),
                            )
                            manifest.database.execute(
                                "UPDATE selection SET state=?,error=?,attempts=attempts+1 WHERE image_id=?",
                                (state, error_text, image_id),
                            )

                    trailing = stream.read(1)
                    if trailing:
                        raise RemoteCleaningError("REMOTE_CLEANING_REVIEW_EXTRA_ITEMS", "cleaning review contains items outside the frozen selection", 409)

                audit_summary = audit_cleaning_annotations(
                    project_path,
                    manifest.database,
                    materials,
                    enabled=bool(options.get("annotation_audit", True)),
                )
                summary = manifest.summary()
                summary["annotation_audit"] = audit_summary
        finally:
            manifest.close()

    finally:
        lock.release()

    # BatchSelection does not implement context-manager methods; project material
    # projection is intentionally performed after the atomic task-result commit.
    manifest = BatchSelection(selection_path)
    try:
        cursor = ""
        while True:
            rows = manifest.database.execute(
                "SELECT image_id,result_json,state FROM clean_results JOIN selection USING(image_id) "
                "WHERE image_id>? ORDER BY image_id LIMIT 500",
                (cursor,),
            ).fetchall()
            if not rows:
                break
            patches = {}
            for row in rows:
                result = json.loads(row["result_json"])
                patches[str(row["image_id"])] = {
                    "clean_status": "failed" if str(row["state"]) == "failed"
                    else ("needs_review" if result.get("issues") else "passed"),
                    "clean_result_task_id": str(task.task_id),
                    "clean_checked_at": str(result.get("inspected_at") or utc_now()),
                    "clean_issues": list(result.get("issues") or []),
                }
            materials.patch(patches)
            cursor = str(rows[-1]["image_id"])
    finally:
        manifest.close()

    return {
        **summary,
        "clean_results_ref": SELECTION_REF,
        "review_required": bool(
            summary.get("flagged")
            or (summary.get("annotation_audit") or {}).get("review_images")
        ),
        "scan_only": True,
        "remote_cleaning_verified": True,
        "execution_generation": int(execution_generation),
    }


__all__ = [
    "MAX_REMOTE_CLEAN_ITEMS",
    "MAX_REMOTE_CLEAN_LINE_BYTES",
    "MAX_REMOTE_CLEAN_RESULT_BYTES",
    "RemoteCleaningError",
    "commit_remote_cleaning_review",
]
