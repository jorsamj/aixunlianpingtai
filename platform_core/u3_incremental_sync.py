"""U3-P3-B2 PostgreSQL incremental consumer core.

Explicit, bounded, per-stream consumption of the owner change log created by
``platform_core/u3_owner_change_log.py``.  There is no worker, queue or timer:
a caller invokes :func:`apply_incremental_batch` for one project/stream and the
function applies at most ``limit`` events in one PostgreSQL transaction.

Contracts:

* events are consumed in strict ``sequence`` order per stream;
* the durable event digest is verified before application;
* re-consuming the same sequence is idempotent, a different digest at the same
  sequence is refused;
* a sequence gap stops the batch without advancing the cursor;
* business projection changes, association changes, evidence changes and the
  cursor advance commit (or roll back) together;
* a project with an existing READY snapshot is marked STALE in the same
  transaction before its projection is modified.  Publishing a new READY
  identity is deliberately left to P3-B3.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping

from .u3_owner_change_log import (
    ANNOTATION_STREAM,
    EVENT_SCHEMA_VERSION,
    MATERIAL_STREAM,
    NEGATIVE_POOL_STREAM,
    STREAMS,
    EVIDENCE_KEY_COLUMNS,
    evidence_row_key,
    high_water_marks,
    payload_digest,
    read_events,
)
from .u3_shadow import (
    REVISION_STORES,
    SCHEMA_NAME,
    _declared_snapshot_id,
    _revision_vector,
    _store_digest,
    export_project_snapshot,
    import_project_snapshot,
    read_target_snapshot,
    reconcile,
    snapshot_evidence_streams,
    snapshot_integrity_error,
    _insert_import_ledger,
)

_STREAM_DATABASE = {
    MATERIAL_STREAM: "materials.sqlite3",
    NEGATIVE_POOL_STREAM: "materials.sqlite3",
    ANNOTATION_STREAM: "annotations.sqlite3",
}

_SCHEMA_DDL = (
    f"""
    CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.u3_applied_owner_event (
        project_id TEXT NOT NULL,
        store TEXT NOT NULL,
        sequence BIGINT NOT NULL,
        event_kind TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        payload_digest CHAR(64) NOT NULL,
        event_digest CHAR(64),
        applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (project_id, store, sequence)
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.u3_projection_baseline (
        project_id TEXT NOT NULL,
        store TEXT NOT NULL,
        baseline_id TEXT NOT NULL,
        snapshot_id TEXT NOT NULL,
        high_water_sequence BIGINT NOT NULL,
        established_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (project_id, store)
    )
    """,
)


class U3IncrementalSyncError(RuntimeError):
    def __init__(self, code: str, message: str, *, detail: str = ""):
        self.code = str(code)
        self.detail = str(detail or "")
        super().__init__(f"{self.code}: {message}")


def ensure_incremental_schema(connection) -> None:
    """Create the B2/B3-only consumption evidence tables (additive, idempotent)."""
    for statement in _SCHEMA_DDL:
        connection.execute(statement)
    columns = {
        str(row[0])
        for row in connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=%s AND table_name='u3_applied_owner_event'",
            (SCHEMA_NAME,),
        ).fetchall()
    }
    if "event_digest" not in columns:
        connection.execute(
            f"ALTER TABLE {SCHEMA_NAME}.u3_applied_owner_event "
            "ADD COLUMN event_digest CHAR(64)"
        )


def _open_owner_database(project_dir: str | Path, stream: str) -> sqlite3.Connection:
    database = Path(project_dir) / _STREAM_DATABASE[stream]
    if not database.is_file():
        raise U3IncrementalSyncError(
            "U3_INCREMENTAL_OWNER_MISSING",
            "the owner database does not exist",
            detail=str(database),
        )
    connection = sqlite3.connect(
        database.resolve().as_uri() + "?mode=ro", uri=True, timeout=30
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def _project_transaction_lock(connection, project_id: str) -> None:
    """The same project-level advisory lock used by full snapshot import."""
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))",
        (f"u3_import:{project_id}",),
    )


def _baseline(connection, project_id: str, stream: str) -> dict[str, Any] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT baseline_id, snapshot_id, high_water_sequence "
            f"FROM {SCHEMA_NAME}.u3_projection_baseline "
            "WHERE project_id=%s AND store=%s",
            (project_id, stream),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return {
        "baseline_id": str(row[0]),
        "snapshot_id": str(row[1]),
        "high_water_sequence": int(row[2]),
    }


def _cursor(connection, project_id: str, stream: str) -> tuple[int, dict[str, Any] | None]:
    baseline = _baseline(connection, project_id, stream)
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT last_applied_seq FROM {SCHEMA_NAME}.u3_projection_cursor "
            "WHERE project_id=%s AND store=%s",
            (project_id, stream),
        )
        row = cursor.fetchone()
    if row is not None and row[0] is not None:
        return int(row[0]), baseline
    if baseline is not None:
        return int(baseline["high_water_sequence"]), baseline
    return 0, None


def establish_baseline_from_snapshot(
    connection, project_id: str, snapshot: Mapping[str, Any],
    revisions: Mapping[str, Any],
) -> bool:
    """Bind a full import to the snapshot's per-stream high-water marks.

    Called inside the full-import transaction, so data, READY state, initial
    cursors and baseline evidence either all commit or all roll back. A legacy
    snapshot without B3 high-water marks returns ``False`` and does not create a
    baseline; incremental consumption then fails closed until a B3 export is
    imported.
    """
    marks = snapshot.get("change_high_water_marks")
    present = snapshot.get("change_log_present")
    if not isinstance(marks, Mapping) or not isinstance(present, Mapping):
        return False
    ensure_incremental_schema(connection)
    from .u3_shadow import _baseline_identity
    snapshot_id = _declared_snapshot_id(snapshot)
    baseline_id = _baseline_identity(snapshot_id, marks, present)
    for stream in STREAMS:
        sequence = marks.get(stream)
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise U3IncrementalSyncError(
                "U3_BASELINE_HIGH_WATER_INVALID",
                "the snapshot high-water mark is invalid",
                detail=f"stream={stream} value={sequence!r}",
            )
        connection.execute(
            f"SELECT high_water_sequence FROM {SCHEMA_NAME}.u3_projection_baseline "
            "WHERE project_id=%s AND store=%s",
            (project_id, stream),
        )
        prior = connection.fetchone()
        if prior is not None and int(prior[0]) > int(sequence):
            raise U3IncrementalSyncError(
                "U3_BASELINE_CURSOR_REGRESSION",
                "the snapshot baseline is behind the established baseline",
                detail=f"stream={stream} existing={prior[0]} incoming={sequence}",
            )
        connection.execute(
            f"INSERT INTO {SCHEMA_NAME}.u3_projection_baseline"
            "(project_id,store,baseline_id,snapshot_id,high_water_sequence,established_at) "
            "VALUES (%s,%s,%s,%s,%s,now()) "
            "ON CONFLICT (project_id,store) DO UPDATE SET "
            "baseline_id=EXCLUDED.baseline_id, snapshot_id=EXCLUDED.snapshot_id, "
            "high_water_sequence=EXCLUDED.high_water_sequence, established_at=now()",
            (project_id, stream, baseline_id, snapshot_id, int(sequence)),
        )
        connection.execute(
            f"INSERT INTO {SCHEMA_NAME}.u3_projection_cursor"
            "(project_id,store,last_applied_seq,source_revision,updated_at) "
            "VALUES (%s,%s,%s,%s,now()) "
            "ON CONFLICT (project_id,store) DO UPDATE SET "
            "last_applied_seq=GREATEST("
            f"{SCHEMA_NAME}.u3_projection_cursor.last_applied_seq, EXCLUDED.last_applied_seq"
            "), source_revision=EXCLUDED.source_revision, updated_at=now()",
            (project_id, stream, int(sequence), revisions.get(stream)),
        )
    return True


def read_owner_change_marks(project_dir: str | Path) -> dict[str, Any]:
    """Strict, read-only Owner high-water marks for B3 diagnostics.

    A missing/unreadable owner is reported as unavailable, never as zero.
    """
    result: dict[str, Any] = {}
    for stream, filename in (
        (MATERIAL_STREAM, "materials.sqlite3"),
        (NEGATIVE_POOL_STREAM, "materials.sqlite3"),
        (ANNOTATION_STREAM, "annotations.sqlite3"),
    ):
        path = Path(project_dir) / filename
        if not path.is_file():
            result[stream] = {"available": False, "reason": "OWNER_MISSING"}
            continue
        try:
            with closing(_open_owner_database(project_dir, stream)) as owner:
                marks = high_water_marks(owner)
        except (sqlite3.Error, U3IncrementalSyncError) as error:
            result[stream] = {"available": False, "reason": str(error)}
            continue
        if stream not in marks:
            result[stream] = {"available": False, "reason": "STREAM_MISSING"}
            continue
        result[stream] = {
            "available": True,
            "high_water_sequence": int(marks[stream]),
        }
    return result


def _applied_digest(connection, project_id: str, stream: str, sequence: int) -> tuple[str | None, str | None]:
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT payload_digest, event_digest "
            f"FROM {SCHEMA_NAME}.u3_applied_owner_event "
            "WHERE project_id=%s AND store=%s AND sequence=%s",
            (project_id, stream, sequence),
        )
        row = cursor.fetchone()
    if row is None:
        return None, None
    return str(row[0]), (str(row[1]) if row[1] else None)
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT payload_digest, event_digest "
            f"FROM {SCHEMA_NAME}.u3_applied_owner_event "
            "WHERE project_id=%s AND store=%s AND sequence=%s",
            (project_id, stream, sequence),
        )
        row = cursor.fetchone()
    if row is None:
        return None, None
    return str(row[0]), (str(row[1]) if row[1] else None)


def _mark_projection_stale(connection, project_id: str) -> None:
    connection.execute(
        f"UPDATE {SCHEMA_NAME}.picker_snapshot_state "
        "SET status='STALE', published_at=now() "
        "WHERE project_id=%s AND status='READY'",
        (project_id,),
    )


def _advance_cursor(connection, project_id: str, stream: str, last_sequence: int) -> None:
    connection.execute(
        f"INSERT INTO {SCHEMA_NAME}.u3_projection_cursor"
        "(project_id, store, last_applied_seq, source_revision, updated_at) "
        "VALUES (%s, %s, %s, NULL, now()) "
        "ON CONFLICT (project_id, store) DO UPDATE SET "
        "last_applied_seq=GREATEST("
        f"{SCHEMA_NAME}.u3_projection_cursor.last_applied_seq, EXCLUDED.last_applied_seq"
        "), updated_at=now()",
        (project_id, stream, int(last_sequence)),
    )


def _record_applied(connection, project_id: str, stream: str, event: Mapping[str, Any]) -> None:
    event_digest = event.get("event_digest") or event["payload_digest"]
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {SCHEMA_NAME}.u3_applied_owner_event"
            "(project_id, store, sequence, event_kind, entity_type, entity_id, "
            "payload_digest, event_digest) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (project_id, store, sequence) DO NOTHING",
            (
                project_id, stream, int(event["sequence"]), str(event["event_kind"]),
                str(event["entity_type"]), str(event["entity_id"]),
                str(event["payload_digest"]), str(event_digest),
            ),
        )
        if int(cursor.rowcount) != 1:
            cursor.execute(
                f"SELECT payload_digest, event_digest "
                f"FROM {SCHEMA_NAME}.u3_applied_owner_event "
                "WHERE project_id=%s AND store=%s AND sequence=%s",
                (project_id, stream, int(event["sequence"])),
            )
            existing = cursor.fetchone()
            if existing is None or str(existing[0]) != str(event["payload_digest"]):
                raise U3IncrementalSyncError(
                    "U3_INCREMENTAL_EVENT_DIGEST_CONFLICT",
                    "the applied-event evidence already has a different digest",
                    detail=f"stream={stream} sequence={event['sequence']}",
                )


def _upsert_evidence_row(
    connection, project_id: str, store: str, table: str, row_key: str,
    row: Mapping[str, Any], *, schema_version: int | None = None,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {SCHEMA_NAME}.evidence_row"
            "(project_id, store, table_name, row_key, payload) "
            "VALUES (%s, %s, %s, %s, %s::jsonb) "
            "ON CONFLICT (project_id, store, table_name, row_key) DO NOTHING",
            (
                project_id, store, table, row_key,
                json.dumps(dict(row), ensure_ascii=False, sort_keys=True),
            ),
        )
        inserted = int(cursor.rowcount) == 1
        if not inserted:
            cursor.execute(
                f"UPDATE {SCHEMA_NAME}.evidence_row SET payload=%s::jsonb "
                "WHERE project_id=%s AND store=%s AND table_name=%s AND row_key=%s",
                (
                    json.dumps(dict(row), ensure_ascii=False, sort_keys=True),
                    project_id, store, table, row_key,
                ),
            )
        else:
            cursor.execute(
                f"UPDATE {SCHEMA_NAME}.table_state SET present=true, "
                "row_count=row_count+1 "
                "WHERE project_id=%s AND store=%s AND table_name=%s",
                (project_id, store, table),
            )
            if int(cursor.rowcount) == 0:
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.table_state"
                    "(project_id,store,table_name,present,schema_version,row_count) "
                    "VALUES (%s,%s,%s,true,%s,1)",
                    (project_id, store, table, schema_version),
                )
            elif schema_version is not None:
                cursor.execute(
                    f"UPDATE {SCHEMA_NAME}.table_state SET schema_version=%s "
                    "WHERE project_id=%s AND store=%s AND table_name=%s",
                    (schema_version, project_id, store, table),
                )


def _delete_evidence_row(
    connection, project_id: str, store: str, table: str, row_key: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"DELETE FROM {SCHEMA_NAME}.evidence_row "
            "WHERE project_id=%s AND store=%s AND table_name=%s AND row_key=%s",
            (project_id, store, table, row_key),
        )
        if int(cursor.rowcount) == 1:
            cursor.execute(
                f"UPDATE {SCHEMA_NAME}.table_state SET row_count=GREATEST(0,row_count-1) "
                "WHERE project_id=%s AND store=%s AND table_name=%s",
                (project_id, store, table),
            )


def _apply_material_upsert(connection, project_id: str, payload: Mapping[str, Any]) -> None:
    material_id = str(payload["id"])
    connection.execute(
        f"INSERT INTO {SCHEMA_NAME}.material"
        "(project_id,id,filename,storage_source_id,storage_type,object_key,"
        "content_sha256,size_bytes,etag,processing_status,box_count,annotated,"
        "created_at,updated_at,payload) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) "
        "ON CONFLICT (project_id,id) DO UPDATE SET "
        "filename=EXCLUDED.filename, storage_source_id=EXCLUDED.storage_source_id, "
        "storage_type=EXCLUDED.storage_type, object_key=EXCLUDED.object_key, "
        "content_sha256=EXCLUDED.content_sha256, size_bytes=EXCLUDED.size_bytes, "
        "etag=EXCLUDED.etag, processing_status=EXCLUDED.processing_status, "
        "box_count=EXCLUDED.box_count, annotated=EXCLUDED.annotated, "
        "created_at=EXCLUDED.created_at, updated_at=EXCLUDED.updated_at, "
        "payload=EXCLUDED.payload",
        (
            project_id, material_id, str(payload.get("filename") or ""),
            str(payload.get("storage_source_id") or "default_local"),
            str(payload.get("storage_type") or "local"),
            str(payload.get("object_key") or ""),
            str(payload.get("content_sha256") or ""),
            int(payload.get("size_bytes") or 0), str(payload.get("etag") or ""),
            str(payload.get("processing_status") or "pending_decision"),
            int(payload.get("box_count") or 0), int(bool(payload.get("annotated"))),
            str(payload.get("created_at") or ""), str(payload.get("updated_at") or ""),
            json.dumps(dict(payload.get("payload") or {}), ensure_ascii=False, sort_keys=True),
        ),
    )
    connection.execute(
        f"DELETE FROM {SCHEMA_NAME}.material_label "
        "WHERE project_id=%s AND material_id=%s",
        (project_id, material_id),
    )
    labels = payload.get("labels") or []
    if labels:
        with connection.cursor() as cursor:
            cursor.executemany(
                f"INSERT INTO {SCHEMA_NAME}.material_label"
                "(project_id, material_id, label_code, box_count) "
                "VALUES (%s, %s, %s, %s)",
                (
                    (project_id, material_id, str(label["label_code"]),
                     int(label.get("box_count") or 0))
                    for label in labels
                ),
            )
    connection.execute(
        f"DELETE FROM {SCHEMA_NAME}.material_annotation_scope "
        "WHERE project_id=%s AND material_id=%s",
        (project_id, material_id),
    )
    scopes = payload.get("annotation_scope") or []
    if scopes:
        with connection.cursor() as cursor:
            cursor.executemany(
                f"INSERT INTO {SCHEMA_NAME}.material_annotation_scope"
                "(project_id, material_id, label_code) VALUES (%s, %s, %s)",
                ((project_id, material_id, str(scope)) for scope in scopes),
            )


def _apply_annotation_upsert(connection, project_id: str, payload: Mapping[str, Any]) -> None:
    image_id = str(payload["image_id"])
    version = int(payload.get("version") or 0)
    digest = str(payload.get("content_digest") or "")
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {SCHEMA_NAME}.annotation"
            "(project_id,image_id,annotation_state,version,content_digest,boxes,scope,"
            "created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s) "
            "ON CONFLICT (project_id,image_id) DO UPDATE SET "
            "annotation_state=EXCLUDED.annotation_state, version=EXCLUDED.version, "
            "content_digest=EXCLUDED.content_digest, boxes=EXCLUDED.boxes, "
            "scope=EXCLUDED.scope, created_at=EXCLUDED.created_at, "
            "updated_at=EXCLUDED.updated_at "
            "WHERE annotation.version <= EXCLUDED.version "
            "AND (annotation.version < EXCLUDED.version "
            "OR annotation.content_digest = EXCLUDED.content_digest) "
            "RETURNING version",
            (
                project_id, image_id, str(payload.get("annotation_state") or ""),
                version, digest,
                json.dumps(payload.get("boxes") or [], ensure_ascii=False, sort_keys=True),
                json.dumps(payload.get("scope") or [], ensure_ascii=False, sort_keys=True),
                str(payload.get("created_at") or ""), str(payload.get("updated_at") or ""),
            ),
        )
        applied = cursor.fetchone() is not None
        if not applied:
            cursor.execute(
                f"SELECT version, content_digest FROM {SCHEMA_NAME}.annotation "
                "WHERE project_id=%s AND image_id=%s",
                (project_id, image_id),
            )
            existing = cursor.fetchone()
            if existing is not None and int(existing[0]) == version and str(existing[1]) != digest:
                raise U3IncrementalSyncError(
                    "U3_INCREMENTAL_ANNOTATION_CONFLICT",
                    "the same annotation version has a different content digest",
                    detail=f"image_id={image_id} version={version}",
                )
            return
        cursor.execute(
            f"DELETE FROM {SCHEMA_NAME}.annotation_label_reference "
            "WHERE project_id=%s AND image_id=%s",
            (project_id, image_id),
        )
        references = payload.get("label_references") or []
        if references:
            cursor.executemany(
                f"INSERT INTO {SCHEMA_NAME}.annotation_label_reference"
                "(project_id,image_id,label_code,box_count,scope_ref,"
                "annotation_state,source_kind) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    (
                        project_id, image_id, str(ref["label_code"]),
                        int(ref.get("box_count") or 0), int(ref.get("scope_ref") or 0),
                        str(ref.get("annotation_state") or ""),
                        str(ref.get("source_kind") or "sqlite"),
                    )
                    for ref in references
                ),
            )


def _apply_confirmation(connection, project_id: str, payload: Mapping[str, Any]) -> None:
    receipt_id = str(payload["receipt_id"])
    evidence = payload.get("evidence") or {}
    context_key = str(payload.get("context_key") or "")
    connection.execute(
        f"INSERT INTO {SCHEMA_NAME}.task_negative_confirmation"
        "(project_id,receipt_id,context_key,image_id,evidence) "
        "VALUES (%s,%s,%s,%s,%s::jsonb) "
        "ON CONFLICT (project_id,receipt_id) DO UPDATE SET "
        "context_key=EXCLUDED.context_key, image_id=EXCLUDED.image_id, "
        "evidence=EXCLUDED.evidence",
        (
            project_id, receipt_id, context_key,
            str(payload.get("image_id") or ""),
            json.dumps(dict(evidence), ensure_ascii=False, sort_keys=True),
        ),
    )


def _apply_negative_pool_member(
    connection, project_id: str, payload: Mapping[str, Any], *, deleted: bool,
) -> None:
    material_id = str(payload["material_id"])
    if deleted or payload.get("member") is None:
        connection.execute(
            f"DELETE FROM {SCHEMA_NAME}.negative_pool_member "
            "WHERE project_id=%s AND material_id=%s",
            (project_id, material_id),
        )
        return
    connection.execute(
        f"INSERT INTO {SCHEMA_NAME}.negative_pool_member"
        "(project_id, material_id, joined_at) VALUES (%s,%s,%s) "
        "ON CONFLICT (project_id, material_id) DO UPDATE SET joined_at=EXCLUDED.joined_at",
        (project_id, material_id, str((payload.get("member") or {}).get("joined_at") or "")),
    )
    connection.execute(
        f"DELETE FROM {SCHEMA_NAME}.negative_pool_link "
        "WHERE project_id=%s AND material_id=%s",
        (project_id, material_id),
    )
    links = payload.get("links") or []
    if links:
        with connection.cursor() as cursor:
            cursor.executemany(
                f"INSERT INTO {SCHEMA_NAME}.negative_pool_link"
                "(project_id, material_id, category_id) VALUES (%s,%s,%s)",
                ((project_id, material_id, str(link["category_id"])) for link in links),
            )
    connection.execute(
        f"DELETE FROM {SCHEMA_NAME}.negative_pool_algorithm_member "
        "WHERE project_id=%s AND material_id=%s",
        (project_id, material_id),
    )
    algorithms = payload.get("algorithms") or []
    if algorithms:
        with connection.cursor() as cursor:
            cursor.executemany(
                f"INSERT INTO {SCHEMA_NAME}.negative_pool_algorithm_member"
                "(project_id, algorithm_id, material_id, joined_at) "
                "VALUES (%s,%s,%s,%s)",
                (
                    (project_id, str(item["algorithm_id"]), material_id,
                     str(item.get("joined_at") or ""))
                    for item in algorithms
                ),
            )


def _apply_negative_pool_category(
    connection, project_id: str, payload: Mapping[str, Any], *, deleted: bool,
) -> None:
    category_id = str(payload["id"])
    if deleted:
        connection.execute(
            f"DELETE FROM {SCHEMA_NAME}.negative_pool_category "
            "WHERE project_id=%s AND id=%s",
            (project_id, category_id),
        )
        return
    connection.execute(
        f"INSERT INTO {SCHEMA_NAME}.negative_pool_category"
        "(project_id,id,name,enabled) VALUES (%s,%s,%s,%s) "
        "ON CONFLICT (project_id,id) DO UPDATE SET "
        "name=EXCLUDED.name, enabled=EXCLUDED.enabled",
        (
            project_id, category_id, str(payload.get("name") or ""),
            int(bool(payload.get("enabled"))),
        ),
    )


def _apply_event(connection, project_id: str, event: Mapping[str, Any]) -> None:
    entity_type = str(event["entity_type"])
    payload = event["payload"]
    deleted = str(event["event_kind"]) == "delete"
    if entity_type == "material":
        if deleted:
            connection.execute(
                f"DELETE FROM {SCHEMA_NAME}.material "
                "WHERE project_id=%s AND id=%s",
                (project_id, str(payload["id"])),
            )
        else:
            _apply_material_upsert(connection, project_id, payload)
    elif entity_type == "annotation":
        if deleted:
            image_id = str(payload["image_id"])
            connection.execute(
                f"DELETE FROM {SCHEMA_NAME}.annotation "
                "WHERE project_id=%s AND image_id=%s",
                (project_id, image_id),
            )
            connection.execute(
                f"DELETE FROM {SCHEMA_NAME}.annotation_label_reference "
                "WHERE project_id=%s AND image_id=%s",
                (project_id, image_id),
            )
        else:
            _apply_annotation_upsert(connection, project_id, payload)
    elif entity_type == "task_negative_confirmation":
        _apply_confirmation(connection, project_id, payload)
    elif entity_type == "negative_pool_member":
        _apply_negative_pool_member(connection, project_id, payload, deleted=deleted)
    elif entity_type == "negative_pool_category":
        _apply_negative_pool_category(connection, project_id, payload, deleted=deleted)
    elif entity_type.startswith("evidence:"):
        if deleted:
            _delete_evidence_row(
                connection, project_id, str(payload["store"]),
                str(payload["table"]), str(payload["row_key"]),
            )
        else:
            _upsert_evidence_row(
                connection, project_id, str(payload["store"]),
                str(payload["table"]), str(payload["row_key"]),
                payload.get("row") or {},
                schema_version=payload.get("schema_version"),
            )
    else:
        raise U3IncrementalSyncError(
            "U3_INCREMENTAL_EVENT_UNSUPPORTED",
            "the change event entity type is not supported",
            detail=entity_type,
        )


def _validate_batch(
    events: list[dict[str, Any]], cursors: Mapping[str, int], project_id: str, stream: str,
) -> None:
    expected = int(cursors[stream]) + 1
    for event in events:
        if int(event["sequence"]) != expected:
            raise U3IncrementalSyncError(
                "U3_INCREMENTAL_SEQUENCE_GAP",
                "the change log is not contiguous after the applied cursor",
                detail=(
                    f"stream={stream} expected={expected} "
                    f"actual={event['sequence']}"
                ),
            )
        if int(event["schema_version"]) not in {1, EVENT_SCHEMA_VERSION}:
            raise U3IncrementalSyncError(
                "U3_INCREMENTAL_SCHEMA_UNSUPPORTED",
                "the change event schema version is not supported",
                detail=f"sequence={event['sequence']} "
                       f"schema_version={event['schema_version']}",
            )
        if str(event["project_id"]) != str(project_id):
            raise U3IncrementalSyncError(
                "U3_INCREMENTAL_PROJECT_MISMATCH",
                "the change event belongs to another project",
                detail=f"sequence={event['sequence']}",
            )
        if payload_digest(event["payload"]) != str(event["payload_digest"]):
            raise U3IncrementalSyncError(
                "U3_INCREMENTAL_EVENT_DIGEST_CONFLICT",
                "the persisted change event digest does not match its payload",
                detail=f"stream={stream} sequence={event['sequence']}",
            )
        if str(event["event_kind"]) not in {"upsert", "delete"}:
            raise U3IncrementalSyncError(
                "U3_INCREMENTAL_EVENT_UNSUPPORTED",
                "the change event kind is not supported",
                detail=f"sequence={event['sequence']} kind={event['event_kind']}",
            )
        entity_type = str(event["entity_type"])
        entity_id = str(event["entity_id"])
        payload = event["payload"]
        if entity_type == "material":
            if str(payload.get("id") or "") != entity_id:
                raise U3IncrementalSyncError(
                    "U3_INCREMENTAL_ENTITY_MISMATCH",
                    "material event entity and payload identity differ",
                    detail=f"sequence={event['sequence']}",
                )
        elif entity_type == "annotation":
            if str(payload.get("image_id") or "") != entity_id:
                raise U3IncrementalSyncError(
                    "U3_INCREMENTAL_ENTITY_MISMATCH",
                    "annotation event entity and payload identity differ",
                    detail=f"sequence={event['sequence']}",
                )
        elif entity_type == "task_negative_confirmation":
            if str(payload.get("receipt_id") or "") != entity_id:
                raise U3IncrementalSyncError(
                    "U3_INCREMENTAL_ENTITY_MISMATCH",
                    "confirmation event entity and payload identity differ",
                    detail=f"sequence={event['sequence']}",
                )
        elif entity_type == "negative_pool_member":
            if str(payload.get("material_id") or "") != entity_id:
                raise U3IncrementalSyncError(
                    "U3_INCREMENTAL_ENTITY_MISMATCH",
                    "pool member event entity and payload identity differ",
                    detail=f"sequence={event['sequence']}",
                )
        elif entity_type == "negative_pool_category":
            if str(payload.get("id") or "") != entity_id:
                raise U3IncrementalSyncError(
                    "U3_INCREMENTAL_ENTITY_MISMATCH",
                    "pool category event entity and payload identity differ",
                    detail=f"sequence={event['sequence']}",
                )
        elif entity_type.startswith("evidence:"):
            table = entity_type.partition(":")[2]
            if str(payload.get("table") or "") != table:
                raise U3IncrementalSyncError(
                    "U3_INCREMENTAL_ENTITY_MISMATCH",
                    "evidence event table and entity type differ",
                    detail=f"sequence={event['sequence']}",
                )
            row_key = str(payload.get("row_key") or "")
            row = payload.get("row")
            if not isinstance(row, Mapping) or not row_key:
                raise U3IncrementalSyncError(
                    "U3_INCREMENTAL_ENTITY_MISMATCH",
                    "evidence event has no full row identity",
                    detail=f"sequence={event['sequence']} table={table}",
                )
            if row_key != entity_id:
                raise U3IncrementalSyncError(
                    "U3_INCREMENTAL_ENTITY_MISMATCH",
                    "evidence event row key and entity id differ",
                    detail=f"sequence={event['sequence']} table={table}",
                )
            if table not in EVIDENCE_KEY_COLUMNS:
                raise U3IncrementalSyncError(
                    "U3_INCREMENTAL_EVENT_UNSUPPORTED",
                    "the evidence table is not a known owner evidence table",
                    detail=f"sequence={event['sequence']} table={table}",
                )
            if evidence_row_key(table, row) != row_key:
                raise U3IncrementalSyncError(
                    "U3_INCREMENTAL_ENTITY_MISMATCH",
                    "evidence row identity does not match its real primary key",
                    detail=f"sequence={event['sequence']} table={table}",
                )
        else:
            raise U3IncrementalSyncError(
                "U3_INCREMENTAL_EVENT_UNSUPPORTED",
                "the change event entity type is not supported",
                detail=f"sequence={event['sequence']} entity_type={entity_type}",
            )
        expected += 1


def apply_incremental_batch(
    connection,
    *,
    project_dir: str | Path,
    project_id: str,
    stream: str,
    limit: int = 200,
) -> dict[str, Any]:
    """Apply one bounded batch of events for one stream.

    ``connection`` must be a writable psycopg connection.  The caller owns the
    connection lifecycle; this function owns one transaction and never touches
    the SQLite owner.
    """
    if stream not in STREAMS:
        raise U3IncrementalSyncError(
            "U3_INCREMENTAL_STREAM_INVALID",
            "unknown owner change stream",
            detail=str(stream),
        )
    if int(limit) < 1 or int(limit) > 1000:
        raise U3IncrementalSyncError(
            "U3_INCREMENTAL_LIMIT_INVALID",
            "the batch limit must be between 1 and 1000",
            detail=str(limit),
        )
    project = str(project_id or "").strip()
    if not project:
        raise U3IncrementalSyncError(
            "U3_INCREMENTAL_PROJECT_MISSING", "project_id is required"
        )
    with closing(_open_owner_database(project_dir, stream)) as owner:
        with connection.transaction():
            _project_transaction_lock(connection, project)
            ensure_incremental_schema(connection)
            cursor, baseline = _cursor(connection, project, stream)
            if baseline is None:
                raise U3IncrementalSyncError(
                    "U3_INCREMENTAL_BASELINE_MISSING",
                    "the stream has no trusted baseline; import a full snapshot first",
                    detail=f"stream={stream}",
                )
            try:
                marks = high_water_marks(owner)
            except sqlite3.Error as error:
                raise U3IncrementalSyncError(
                    "U3_INCREMENTAL_OWNER_UNAVAILABLE",
                    "the owner high-water mark cannot be read",
                    detail=str(error),
                ) from error
            owner_hwm = marks.get(stream)
            if owner_hwm is None:
                raise U3IncrementalSyncError(
                    "U3_INCREMENTAL_LOG_MISSING",
                    "the owner change stream is missing",
                    detail=f"stream={stream} marks={sorted(marks)}",
                )
            if cursor > int(owner_hwm):
                raise U3IncrementalSyncError(
                    "U3_INCREMENTAL_CURSOR_AHEAD",
                    "the projection cursor is ahead of the owner log",
                    detail=f"stream={stream} cursor={cursor} owner={owner_hwm}",
                )
            try:
                events = read_events(owner, stream, cursor, int(limit))
            except ValueError as error:
                raise U3IncrementalSyncError(
                    "U3_INCREMENTAL_EVENT_INVALID",
                    "the owner change log cannot be verified",
                    detail=str(error),
                ) from error
            if not events:
                if cursor != int(owner_hwm):
                    raise U3IncrementalSyncError(
                        "U3_INCREMENTAL_LOG_TAIL_MISSING",
                        "the owner high-water mark is ahead but no events are readable",
                        detail=(
                            f"stream={stream} cursor={cursor} owner={owner_hwm}"
                        ),
                    )
                return {
                    "stream": stream, "applied": 0, "skipped": 0,
                    "last_sequence": cursor, "has_more": False,
                    "caught_up": True,
                }
            _validate_batch(events, {stream: cursor}, project, stream)
            applied = 0
            skipped = 0
            previous = cursor
            stale_marked = False
            for event in events:
                sequence = int(event["sequence"])
                prior_payload, prior_event = _applied_digest(
                    connection, project, stream, sequence
                )
                if prior_payload is not None:
                    expected_digest = str(
                        event.get("event_digest") or event["payload_digest"]
                    )
                    if prior_payload != str(event["payload_digest"]) or (
                        prior_event is not None and prior_event != expected_digest
                    ):
                        raise U3IncrementalSyncError(
                            "U3_INCREMENTAL_EVENT_DIGEST_CONFLICT",
                            "the same event identity has a different digest",
                            detail=(
                                f"stream={stream} sequence={sequence} "
                                f"prior={prior_payload}/{prior_event} "
                                f"current={event['payload_digest']}/{expected_digest}"
                            ),
                        )
                    skipped += 1
                    previous = sequence
                    continue
                if sequence <= cursor:
                    raise U3IncrementalSyncError(
                        "U3_INCREMENTAL_CURSOR_EVIDENCE_MISSING",
                        "the cursor is ahead of the applied event evidence",
                        detail=f"stream={stream} sequence={sequence} cursor={cursor}",
                    )
                if int(sequence) > int(owner_hwm):
                    raise U3IncrementalSyncError(
                        "U3_INCREMENTAL_EVENT_BEYOND_HIGH_WATER",
                        "an event is beyond the verified owner high-water mark",
                        detail=f"stream={stream} sequence={sequence} owner={owner_hwm}",
                    )
                if not stale_marked:
                    _mark_projection_stale(connection, project)
                    stale_marked = True
                _apply_event(connection, project, event)
                _record_applied(connection, project, stream, event)
                applied += 1
                previous = sequence
            _advance_cursor(connection, project, stream, previous)
            return {
                "stream": stream,
                "applied": applied,
                "skipped": skipped,
                "last_sequence": previous,
                "has_more": previous < int(owner_hwm),
                "caught_up": previous >= int(owner_hwm),
            }


def _publish_ready_state(connection, project_id: str, snapshot: Mapping[str, Any]) -> None:
    from .u3_shadow import _revision_vector, _store_digest, snapshot_evidence_streams

    revisions = snapshot.get("revisions") or {}
    digests = snapshot.get("digests") or {}
    streams = snapshot_evidence_streams(snapshot)
    store_digests = {
        store: _store_digest(digests, store) for store in REVISION_STORES
    }
    revision_vector = _revision_vector(revisions, store_digests, streams)
    confirmation = streams["negative_confirmation"]
    connection.execute(
        f"INSERT INTO {SCHEMA_NAME}.picker_snapshot_state(project_id,snapshot_id,"
        "content_digest,material_revision,annotation_revision,negative_pool_revision,"
        "materials_digest,annotations_digest,negative_pool_digest,"
        "negative_confirmation_revision,negative_confirmation_generation,"
        "negative_confirmation_digest,revision_vector,status,captured_at,published_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,'READY',NULL,now()) "
        "ON CONFLICT (project_id) DO UPDATE SET snapshot_id=EXCLUDED.snapshot_id,"
        "content_digest=EXCLUDED.content_digest,"
        "material_revision=EXCLUDED.material_revision,"
        "annotation_revision=EXCLUDED.annotation_revision,"
        "negative_pool_revision=EXCLUDED.negative_pool_revision,"
        "materials_digest=EXCLUDED.materials_digest,"
        "annotations_digest=EXCLUDED.annotations_digest,"
        "negative_pool_digest=EXCLUDED.negative_pool_digest,"
        "negative_confirmation_revision=EXCLUDED.negative_confirmation_revision,"
        "negative_confirmation_generation=EXCLUDED.negative_confirmation_generation,"
        "negative_confirmation_digest=EXCLUDED.negative_confirmation_digest,"
        "revision_vector=EXCLUDED.revision_vector,status='READY',published_at=now()",
        (
            project_id, str(snapshot["snapshot_id"]),
            str(snapshot.get("content_digest") or ""),
            revisions.get("materials"), revisions.get("annotations"),
            revisions.get("negative_pool"),
            store_digests["materials"], store_digests["annotations"],
            store_digests["negative_pool"],
            int(confirmation["revision"]), int(confirmation["generation"]),
            str(confirmation["digest"]),
            json.dumps(revision_vector, ensure_ascii=False, sort_keys=True),
        ),
    )
    for store, revision in revisions.items():
        connection.execute(
            f"INSERT INTO {SCHEMA_NAME}.store_revision(project_id,store,revision) "
            "VALUES(%s,%s,%s) ON CONFLICT (project_id,store) DO UPDATE SET "
            "revision=EXCLUDED.revision, recorded_at=now()",
            (project_id, store, revision),
        )
        connection.execute(
            f"UPDATE {SCHEMA_NAME}.u3_projection_cursor SET source_revision=%s, "
            "updated_at=now() WHERE project_id=%s AND store=%s",
            (revision, project_id, store),
        )
    with connection.cursor() as cursor:
        _insert_import_ledger(
            cursor,
            project_id=project_id,
            snapshot_id=str(snapshot["snapshot_id"]),
            snapshot_digest=str(snapshot.get("content_digest") or ""),
            revision_vector=revision_vector,
            mode="incremental-publish",
            outcome="APPLIED",
        )


def publish_ready(
    connection, *, project_dir: str | Path, project_id: str,
) -> dict[str, Any]:
    """Publish a new READY identity after all streams are caught up.

    The lifecycle fence keeps Owner writes out while the final Owner snapshot and
    target projection are compared. The publication transaction re-checks the
    persisted cursors and baseline before writing state, revisions and identity.
    """
    from .material_repository import material_annotation_lifecycle_fence

    project = str(project_id or "").strip()
    if not project:
        raise U3IncrementalSyncError(
            "U3_INCREMENTAL_PROJECT_MISSING", "project_id is required"
        )
    with material_annotation_lifecycle_fence(project_dir, timeout=60):
        snapshot = export_project_snapshot(project_dir, project)
        integrity = snapshot_integrity_error(snapshot)
        if integrity:
            raise U3IncrementalSyncError(
                "U3_READY_SNAPSHOT_INTEGRITY",
                "the owner snapshot does not match its own identity",
                detail=str(integrity),
            )
        marks = snapshot.get("change_high_water_marks") or {}
        target = read_target_snapshot(connection, project)
        compare_target = dict(target)
        compare_target["revisions"] = dict(snapshot.get("revisions") or {})
        report = reconcile(snapshot, compare_target)
        if not report["same"]:
            return {
                "published": False,
                "code": "U3_READY_PROJECTION_MISMATCH",
                "blocking_findings": report["blocking_findings"],
            }
        with connection.transaction():
            _project_transaction_lock(connection, project)
            ensure_incremental_schema(connection)
            for stream in STREAMS:
                cursor_value, baseline = _cursor(connection, project, stream)
                if baseline is None:
                    return {
                        "published": False,
                        "code": "U3_READY_BASELINE_MISSING",
                        "stream": stream,
                    }
                if int(marks.get(stream, -1)) != cursor_value:
                    return {
                        "published": False,
                        "code": "U3_READY_STREAM_NOT_ALIGNED",
                        "stream": stream,
                        "cursor": cursor_value,
                        "owner": marks.get(stream),
                    }
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(*) FROM {SCHEMA_NAME}.task_negative_confirmation c "
                    f"LEFT JOIN {SCHEMA_NAME}.annotation a "
                    "ON a.project_id=c.project_id AND a.image_id=c.image_id "
                    "WHERE c.project_id=%s AND a.image_id IS NULL",
                    (project,),
                )
                if int(cursor.fetchone()[0]):
                    return {
                        "published": False,
                        "code": "U3_READY_CONFIRMATION_WITHOUT_ANNOTATION",
                    }
            _publish_ready_state(connection, project, snapshot)
        return {
            "published": True,
            "snapshot_id": str(snapshot["snapshot_id"]),
            "baseline_id": str(snapshot.get("baseline_id") or ""),
            "change_high_water_marks": dict(marks),
            "revisions": dict(snapshot.get("revisions") or {}),
        }


def synchronize_project(
    connection, *, project_dir: str | Path, project_id: str,
    limit: int = 200, max_batches: int = 100,
) -> dict[str, Any]:
    """Drain all streams in bounded batches, then publish READY if aligned."""
    if int(max_batches) < 1:
        raise U3IncrementalSyncError(
            "U3_INCREMENTAL_LIMIT_INVALID", "max_batches must be positive"
        )
    applied = 0
    batches = 0
    while batches < int(max_batches):
        progressed = False
        for stream in STREAMS:
            result = apply_incremental_batch(
                connection, project_dir=project_dir,
                project_id=project_id, stream=stream, limit=limit,
            )
            applied += int(result["applied"])
            batches += 1
            if result.get("has_more"):
                progressed = True
        if not progressed:
            published = publish_ready(
                connection, project_dir=project_dir, project_id=project_id
            )
            return {
                "status": "READY" if published.get("published") else "NOT_READY",
                "applied": applied,
                "batches": batches,
                "publication": published,
            }
    return {
        "status": "INCOMPLETE",
        "applied": applied,
        "batches": batches,
        "publication": {
            "published": False, "code": "U3_INCREMENTAL_BATCH_LIMIT"
        },
    }


def rebuild_project(
    connection, *, project_dir: str | Path, project_id: str,
    limit: int = 200, max_batches: int = 100,
) -> dict[str, Any]:
    """Controlled full rebuild: export, atomic full import as STALE, then catch up.

    A failed import rolls back to the previous projection. New Owner events that
    land after the export are consumed by the following synchronize step; the
    imported state is never advertised as READY in between.
    """
    project = str(project_id or "").strip()
    if not project:
        raise U3IncrementalSyncError(
            "U3_INCREMENTAL_PROJECT_MISSING", "project_id is required"
        )
    snapshot = export_project_snapshot(project_dir, project)
    imported = import_project_snapshot(
        connection, snapshot, mode="full", status_override="STALE"
    )
    synchronized = synchronize_project(
        connection, project_dir=project_dir, project_id=project,
        limit=limit, max_batches=max_batches,
    )
    return {
        "rebuilt": True,
        "snapshot_id": str(snapshot.get("snapshot_id") or ""),
        "import": imported,
        "synchronize": synchronized,
    }


def diagnose_project(
    connection, *, project_dir: str | Path, project_id: str,
) -> dict[str, Any]:
    """Read-only backlog/diagnostic view over existing state and evidence."""
    project = str(project_id or "").strip()
    owner = read_owner_change_marks(project_dir)
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT snapshot_id,status,published_at FROM {SCHEMA_NAME}.picker_snapshot_state "
                "WHERE project_id=%s",
                (project,),
            )
            state = cursor.fetchone()
            cursor.execute(
                f"SELECT store,last_applied_seq FROM {SCHEMA_NAME}.u3_projection_cursor "
                "WHERE project_id=%s ORDER BY store",
                (project,),
            )
            cursors = {str(row[0]): (int(row[1]) if row[1] is not None else None)
                       for row in cursor.fetchall()}
    streams: dict[str, Any] = {}
    needs_rebuild = False
    for stream in STREAMS:
        current = cursors.get(stream)
        marks = owner.get(stream) or {}
        if not marks.get("available"):
            streams[stream] = {
                "owner": "UNAVAILABLE", "cursor": current, "pending": None,
                "reason": marks.get("reason"),
            }
            continue
        hwm = int(marks["high_water_sequence"])
        pending = max(0, hwm - current) if current is not None else None
        next_sequence = None
        gap = False
        if current is not None and hwm > current:
            try:
                with closing(_open_owner_database(project_dir, stream)) as database:
                    events = read_events(database, stream, current, 1)
                next_sequence = int(events[0]["sequence"]) if events else None
                gap = next_sequence is None or next_sequence != current + 1
            except (sqlite3.Error, ValueError, U3IncrementalSyncError):
                gap = True
        needs_rebuild = needs_rebuild or gap
        streams[stream] = {
            "owner": "AVAILABLE",
            "high_water_sequence": hwm,
            "cursor": current,
            "pending": pending,
            "next_sequence": next_sequence,
            "gap": gap,
        }
    return {
        "project_id": project,
        "status": None if state is None else str(state[1]),
        "snapshot_id": None if state is None else str(state[0]),
        "published_at": None if state is None else state[2],
        "streams": streams,
        "needs_rebuild": bool(needs_rebuild),
    }
