"""Project-level label integrity audit snapshots.

AnnotationRepository is the sole Ground Truth owner. Audit SQLite artifacts are
immutable diagnostic snapshots and must never be treated as repair truth.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

from .annotation_repository import AnnotationRepository, _normalize_scope
from .material_repository import MaterialRepository
from .task_runtime import TaskKind, TaskRecord
from .task_runtime.models import utc_now


AUDIT_OPERATION = "AUDIT_LABEL_INTEGRITY"
AUDIT_REF = "label-integrity.sqlite3"

_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_metadata (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_summary (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS annotation_references (
    image_id TEXT NOT NULL,
    label_code TEXT NOT NULL,
    annotation_state TEXT NOT NULL,
    box_count INTEGER NOT NULL,
    scope_ref INTEGER NOT NULL,
    class_ids_json TEXT NOT NULL,
    annotation_digest TEXT NOT NULL,
    PRIMARY KEY(image_id, label_code)
);
CREATE INDEX IF NOT EXISTS ix_audit_references_label
    ON annotation_references(label_code, image_id);
CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    label_code TEXT NOT NULL DEFAULT '',
    annotation_state TEXT NOT NULL,
    box_count INTEGER NOT NULL DEFAULT 0,
    scope_ref INTEGER NOT NULL DEFAULT 0,
    class_ids_json TEXT NOT NULL DEFAULT '[]',
    details_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(image_id, issue_type, label_code)
);
CREATE INDEX IF NOT EXISTS ix_audit_issues_page ON issues(id);
CREATE INDEX IF NOT EXISTS ix_audit_issues_group
    ON issues(issue_type, label_code, image_id);
CREATE TABLE IF NOT EXISTS issue_groups (
    issue_type TEXT NOT NULL,
    label_code TEXT NOT NULL,
    image_count INTEGER NOT NULL,
    box_count INTEGER NOT NULL,
    PRIMARY KEY(issue_type, label_code)
);
"""


def _catalog(project_path: Path) -> tuple[dict[str, dict], str]:
    meta_path = project_path / "meta.json"
    value = json.loads(meta_path.read_text(encoding="utf-8"))
    labels = list(value.get("labels") or [])
    metadata = list(value.get("label_meta") or [])
    rows: dict[str, dict] = {}
    for class_id, raw in enumerate(labels):
        code = str(raw or "").strip()
        if not code:
            continue
        info = metadata[class_id] if class_id < len(metadata) and isinstance(metadata[class_id], dict) else {}
        rows[code] = {
            "code": code,
            "class_id": class_id,
            "status": str(info.get("status") or "active").strip().lower(),
            "merged_into": str(info.get("merged_into") or "").strip(),
        }
    fingerprint = hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return rows, fingerprint


def _reference_map(record: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for box in record.get("boxes") or []:
        code = str(box.get("label") or box.get("code") or "").strip()
        if not code:
            continue
        row = result.setdefault(code, {"box_count": 0, "scope_ref": 0, "class_ids": set(), "boxes": []})
        row["box_count"] += 1
        if box.get("class_id") is not None:
            try:
                row["class_ids"].add(int(box.get("class_id")))
            except (TypeError, ValueError):
                pass
        row["boxes"].append(box)
    for code in _normalize_scope(record.get("annotation_scope")):
        result.setdefault(code, {"box_count": 0, "scope_ref": 0, "class_ids": set(), "boxes": []})["scope_ref"] = 1
    return result


def _insert_issue(database, record, issue_type, code, reference, details=None):
    database.execute(
        "INSERT OR IGNORE INTO issues "
        "(image_id,issue_type,label_code,annotation_state,box_count,scope_ref,class_ids_json,details_json) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            str(record.get("image_id") or ""),
            issue_type,
            code,
            str(record.get("annotation_state") or "unannotated"),
            int(reference.get("box_count") or 0),
            int(bool(reference.get("scope_ref"))),
            json.dumps(sorted(reference.get("class_ids") or [])),
            json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
        ),
    )


def run_label_integrity_audit(project_path: str | Path, artifact_path: str | Path, progress=None) -> dict:
    project_path = Path(project_path)
    artifact_path = Path(artifact_path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    annotations = AnnotationRepository(project_path)
    materials = MaterialRepository(project_path)
    annotations.rebuild_reference_index()
    governance, governance_fingerprint = _catalog(project_path)
    annotation_revision = annotations.current_revision()
    annotation_fingerprint = annotations.repository_fingerprint()
    material_revision = materials.current_revision()
    records = annotations.iter_records()
    scanned = 0
    affected: set[str] = set()

    with closing(sqlite3.connect(artifact_path)) as database:
        database.executescript(_AUDIT_SCHEMA)
        database.execute("BEGIN IMMEDIATE")
        database.execute("DELETE FROM audit_metadata")
        database.execute("DELETE FROM audit_summary")
        database.execute("DELETE FROM annotation_references")
        database.execute("DELETE FROM issues")
        database.execute("DELETE FROM issue_groups")

        batch: list[dict] = []

        def audit_batch(rows: list[dict]) -> None:
            nonlocal scanned
            if not rows:
                return
            projected = {
                str(row.get("id")): row
                for row in materials.get_many(str(record.get("image_id")) for record in rows)
            }
            for record in rows:
                image_id = str(record.get("image_id") or "")
                references = _reference_map(record)
                digest = annotations.record_digest(record)
                for code, reference in references.items():
                    class_ids = sorted(reference["class_ids"])
                    database.execute(
                        "INSERT INTO annotation_references "
                        "(image_id,label_code,annotation_state,box_count,scope_ref,class_ids_json,annotation_digest) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (
                            image_id,
                            code,
                            str(record.get("annotation_state") or "unannotated"),
                            int(reference["box_count"]),
                            int(reference["scope_ref"]),
                            json.dumps(class_ids),
                            digest,
                        ),
                    )
                    label = governance.get(code)
                    if label is None:
                        _insert_issue(database, record, "ORPHAN_LABEL", code, reference)
                    elif label["status"] == "merged":
                        _insert_issue(
                            database, record, "INCOMPLETE_MERGE", code, reference,
                            {"merged_into": label["merged_into"]},
                        )
                    elif label["status"] != "active":
                        _insert_issue(database, record, "INACTIVE_REFERENCE", code, reference)
                    if label is not None:
                        expected_class_id = int(label["class_id"])
                        if any(value != expected_class_id for value in class_ids):
                            _insert_issue(
                                database, record, "CLASS_ID_IDENTITY_CONFLICT", code, reference,
                                {"expected_class_id": expected_class_id},
                            )
                        boxes = reference.get("boxes") or []
                        missing_identity = any(
                            box.get("canonical_label_id") is None
                            or box.get("canonical_project_class_id") is None
                            for box in boxes
                        )
                        conflicting_identity = any(
                            (
                                box.get("canonical_label_id") is not None
                                and str(box.get("canonical_label_id")) != code
                            )
                            or (
                                box.get("canonical_project_class_id") is not None
                                and int(box.get("canonical_project_class_id")) != expected_class_id
                            )
                            for box in boxes
                        )
                        if missing_identity:
                            _insert_issue(database, record, "CANONICAL_IDENTITY_MISSING", code, reference)
                        if conflicting_identity:
                            _insert_issue(database, record, "CANONICAL_IDENTITY_CONFLICT", code, reference)

                material = projected.get(image_id)
                truth_labels = {
                    code: int(reference["box_count"])
                    for code, reference in references.items()
                    if int(reference["box_count"]) > 0
                }
                truth_scopes = set(_normalize_scope(record.get("annotation_scope")))
                projected_labels = set(material.get("labels") or []) if material else set()
                projected_counts = material.get("label_counts") if material and isinstance(material.get("label_counts"), dict) else {}
                projected_scopes = set(_normalize_scope(material.get("annotation_scope"))) if material else set()
                drift_codes = set(truth_labels) | projected_labels | truth_scopes | projected_scopes
                for code in sorted(drift_codes):
                    if (
                        int(truth_labels.get(code, 0)) != int(projected_counts.get(code, 0) or 0)
                        or (code in truth_scopes) != (code in projected_scopes)
                    ):
                        reference = references.get(code) or {
                            "box_count": 0, "scope_ref": int(code in truth_scopes),
                            "class_ids": set(), "boxes": [],
                        }
                        _insert_issue(
                            database, record, "PROJECTION_DRIFT", code, reference,
                            {
                                "truth_box_count": int(truth_labels.get(code, 0)),
                                "projected_box_count": int(projected_counts.get(code, 0) or 0),
                                "truth_scope_ref": code in truth_scopes,
                                "projected_scope_ref": code in projected_scopes,
                            },
                        )
                scanned += 1
                if database.execute(
                    "SELECT 1 FROM issues WHERE image_id=? LIMIT 1", (image_id,)
                ).fetchone():
                    affected.add(image_id)

        for record in records:
            batch.append(record)
            if len(batch) >= 500:
                audit_batch(batch)
                batch = []
                if progress:
                    progress(scanned)
        audit_batch(batch)

        database.execute(
            "INSERT INTO issue_groups(issue_type,label_code,image_count,box_count) "
            "SELECT issue_type,label_code,COUNT(DISTINCT image_id),SUM(box_count) "
            "FROM issues GROUP BY issue_type,label_code"
        )
        issue_count = int(database.execute("SELECT COUNT(*) FROM issues").fetchone()[0])
        _current_governance, current_governance_fingerprint = _catalog(project_path)
        if (
            annotations.current_revision() != annotation_revision
            or annotations.repository_fingerprint() != annotation_fingerprint
            or materials.current_revision() != material_revision
            or current_governance_fingerprint != governance_fingerprint
        ):
            raise RuntimeError(
                "LABEL_INTEGRITY_TRUTH_CHANGED_DURING_AUDIT: "
                "annotation, material projection, or governance changed; retry the audit"
            )
        metadata = {
            "schema_version": 1,
            "created_at": utc_now(),
            "truth_owner": "AnnotationRepository",
            "annotation_revision": annotation_revision,
            "annotation_fingerprint": annotation_fingerprint,
            "material_revision": material_revision,
            "governance_fingerprint": governance_fingerprint,
            "snapshot_only": True,
        }
        database.executemany(
            "INSERT INTO audit_metadata(key,value_json) VALUES (?,?)",
            ((key, json.dumps(value, ensure_ascii=False, sort_keys=True)) for key, value in metadata.items()),
        )
        summary = {
            "scanned_images": scanned,
            "affected_images": len(affected),
            "issue_count": issue_count,
        }
        database.executemany(
            "INSERT INTO audit_summary(key,value) VALUES (?,?)", summary.items()
        )
        database.execute("COMMIT")
    return {**summary, "audit_ref": AUDIT_REF, "metadata": metadata}


def create_label_integrity_audit(project_id, repository, artifacts):
    task_id = uuid.uuid4().hex
    request = {"operation": AUDIT_OPERATION, "audit_scope": "PROJECT"}
    checkpoint = {
        "total": None,
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "selection_frozen": False,
        "audit_ref": AUDIT_REF,
    }
    artifacts.atomic_write_json(task_id, "request.json", request)
    artifacts.atomic_write_json(task_id, "checkpoints/worker.json", checkpoint)
    task = TaskRecord.new(
        task_id,
        str(project_id),
        TaskKind.MATERIAL_BATCH,
        "request.json",
        f"materials:{project_id}",
        required_capabilities=("materials.batch",),
    )
    return repository.create(task, artifacts=artifacts)


def create_orphan_repair(
    project_id,
    project_path,
    repository,
    artifacts,
    audit_task_id,
    source_label,
    target_label,
):
    """Re-read current GT and freeze only audit candidates still needing repair."""
    from .material_batches import BatchRequestError, BatchSelection, RESULT_REF, SELECTION_REF

    source = str(source_label or "").strip()
    target = str(target_label or "").strip()
    if not source or not target or source == target:
        raise BatchRequestError(
            "LABEL_INTEGRITY_MAPPING_INVALID",
            "来源标签和目标标签必须明确且不同",
            422,
        )
    project_path = Path(project_path)
    governance, _fingerprint = _catalog(project_path)
    target_info = governance.get(target)
    if target_info is None or target_info["status"] != "active":
        raise BatchRequestError(
            "LABEL_INTEGRITY_TARGET_UNAVAILABLE",
            "目标标签已不存在或不是 active，请刷新后重新映射",
            409,
        )
    audit_path = artifacts.artifact_path(audit_task_id, AUDIT_REF)
    if not audit_path.is_file():
        raise BatchRequestError(
            "LABEL_INTEGRITY_AUDIT_INCOMPLETE",
            "完整性审计尚未完成",
            409,
        )
    uri = audit_path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as database:
        candidates = [
            str(row[0])
            for row in database.execute(
                "SELECT DISTINCT r.image_id FROM annotation_references r "
                "WHERE r.label_code=? AND EXISTS ("
                "SELECT 1 FROM issues i WHERE i.image_id=r.image_id AND i.label_code=r.label_code"
                ") ORDER BY r.image_id",
                (source,),
            ).fetchall()
        ]

    annotations = AnnotationRepository(project_path)
    frozen: list[tuple[str, str]] = []
    already_resolved = 0
    for offset in range(0, len(candidates), 500):
        chunk = candidates[offset:offset + 500]
        current = annotations.get_many(chunk)
        for image_id in chunk:
            record = current[image_id]
            references = _reference_map(record)
            if source not in references:
                already_resolved += 1
                continue
            source_digest = annotations.record_digest(record)
            preview = annotations.plan_label_remap(
                record,
                source_label=source,
                target_label=target,
                target_class_id=int(target_info["class_id"]),
            )
            plan = {
                "operation": "REMAP_ANNOTATION_LABELS",
                "repair_mode": True,
                "audit_task_id": str(audit_task_id),
                "source_labels": [source],
                "source_label": source,
                "target_label": target,
                "source_digest": source_digest,
                "expected_digest": source_digest,
                "result_digest": preview["content_digest"],
                "changed_boxes": int(preview["changed_boxes"]),
                "changed_scope": int(preview.get("changed_scope") or 0),
                "target_class_id": int(target_info["class_id"]),
                "planned_at": utc_now(),
            }
            frozen.append((image_id, json.dumps(plan, ensure_ascii=False, sort_keys=True)))

    task_id = uuid.uuid4().hex
    selection_path = artifacts.artifact_path(task_id, SELECTION_REF)
    with closing(BatchSelection(selection_path)) as manifest:
        with manifest.transaction():
            manifest.database.executemany(
                "INSERT INTO selection(image_id,tombstone_json) VALUES (?,?)",
                frozen,
            )
            manifest.database.executemany(
                "INSERT INTO meta(key,value) VALUES (?,?)",
                (
                    ("frozen", utc_now()),
                    ("selection_kind", "label_integrity_repair"),
                    ("audit_task_id", str(audit_task_id)),
                    ("annotation_revision", str(annotations.current_revision())),
                    ("source_label", source),
                    ("target_label", target),
                ),
            )
        checkpoint = manifest.summary()
    stats = {
        "candidate": len(candidates),
        "still_requires_repair": len(frozen),
        "already_resolved": already_resolved,
    }
    request = {
        "operation": "REMAP_ANNOTATION_LABELS",
        "options": {
            "source_labels": [source],
            "source_label": source,
            "target_label": target,
            "repair_mode": True,
            "audit_task_id": str(audit_task_id),
            "retire_sources_on_success": False,
            **stats,
        },
        "selection_spec": {
            "scope": "LABEL_INTEGRITY_REPAIR",
            "audit_task_id": str(audit_task_id),
        },
    }
    artifacts.atomic_write_json(task_id, "request.json", request)
    artifacts.atomic_write_json(task_id, "checkpoints/worker.json", checkpoint)
    task = TaskRecord.new(
        task_id,
        str(project_id),
        TaskKind.MATERIAL_BATCH,
        "request.json",
        f"materials:{project_id}",
        required_capabilities=("materials.batch",),
    )
    return repository.create(task, artifacts=artifacts), stats


def read_audit_issues(path: str | Path, *, cursor: int = 0, limit: int = 100) -> dict:
    if not 1 <= int(limit) <= 500:
        raise ValueError("limit must be between 1 and 500")
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as database:
        database.row_factory = sqlite3.Row
        metadata = {
            str(row["key"]): json.loads(row["value_json"])
            for row in database.execute("SELECT key,value_json FROM audit_metadata")
        }
        summary = {
            str(row["key"]): int(row["value"])
            for row in database.execute("SELECT key,value FROM audit_summary")
        }
        groups = [
            dict(row)
            for row in database.execute(
                "SELECT issue_type,label_code,image_count,box_count "
                "FROM issue_groups ORDER BY image_count DESC,issue_type,label_code"
            ).fetchall()
        ]
        rows = database.execute(
            "SELECT * FROM issues WHERE id>? ORDER BY id LIMIT ?",
            (max(0, int(cursor)), int(limit)),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["class_ids"] = json.loads(item.pop("class_ids_json"))
            item["details"] = json.loads(item.pop("details_json"))
            items.append(item)
        next_cursor = int(rows[-1]["id"]) if rows and database.execute(
            "SELECT 1 FROM issues WHERE id>? LIMIT 1", (int(rows[-1]["id"]),)
        ).fetchone() else None
    return {
        "metadata": metadata,
        "summary": summary,
        "groups": groups,
        "items": items,
        "next_cursor": next_cursor,
    }


def label_integrity_router(get_project, material_store, task_repository, task_artifacts):
    from fastapi import APIRouter, Body, HTTPException
    from .material_batches import BatchRequestError

    router = APIRouter(prefix="/api/v54/projects/{project_id}/labels/integrity")

    def require_audit(project_id: str, task_id: str):
        get_project(project_id)
        task = task_repository().get(task_id)
        if task is None or task.project_id != project_id or task.kind is not TaskKind.MATERIAL_BATCH:
            raise HTTPException(404, detail="label integrity audit not found")
        request = task_artifacts().read_json(task_id, task.payload_ref, default={})
        if request.get("operation") != AUDIT_OPERATION:
            raise HTTPException(404, detail="label integrity audit not found")
        return task

    @router.post("/audits", status_code=202)
    def create_audit(project_id: str):
        get_project(project_id)
        task = create_label_integrity_audit(project_id, task_repository(), task_artifacts())
        from .material_batches import public_batch
        return public_batch(task, task_artifacts(), task_repository())

    @router.get("/audits/{task_id}/issues")
    def issues(project_id: str, task_id: str, cursor: int = 0, limit: int = 100):
        task = require_audit(project_id, task_id)
        if task.status.value != "SUCCEEDED":
            raise HTTPException(409, detail="label integrity audit is not complete")
        path = task_artifacts().artifact_path(task_id, AUDIT_REF)
        if not path.is_file():
            raise HTTPException(409, detail="label integrity audit is not complete")
        try:
            return read_audit_issues(path, cursor=cursor, limit=limit)
        except ValueError as error:
            raise HTTPException(422, detail=str(error)) from error

    @router.post("/audits/{task_id}/repairs", status_code=202)
    def create_repair(project_id: str, task_id: str, payload: dict = Body(...)):
        audit = require_audit(project_id, task_id)
        if audit.status.value != "SUCCEEDED":
            raise HTTPException(409, detail="label integrity audit is not complete")
        try:
            get_project(project_id)
            task, stats = create_orphan_repair(
                project_id,
                material_store(project_id).project_path,
                task_repository(),
                task_artifacts(),
                task_id,
                payload.get("source_label"),
                payload.get("target_label"),
            )
        except BatchRequestError as error:
            raise HTTPException(
                error.status_code,
                detail={"code": error.code, "message": str(error)},
            ) from error
        from .material_batches import public_batch
        return {**public_batch(task, task_artifacts(), task_repository()), **stats}

    return router
