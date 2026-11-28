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
    payload_digest,
    read_events,
)
from .u3_shadow import SCHEMA_NAME

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
        applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (project_id, store, sequence)
    )
    """,
)


class U3IncrementalSyncError(RuntimeError):
    def __init__(self, code: str, message: str, *, detail: str = ""):
        self.code = str(code)
        self.detail = str(detail or "")
        super().__init__(f"{self.code}: {message}")


def ensure_incremental_schema(connection) -> None:
    """Create the B2-only consumption evidence table (additive, idempotent)."""
    for statement in _SCHEMA_DDL:
        connection.execute(statement)


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


def _cursor(connection, project_id: str, stream: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT last_applied_seq FROM {SCHEMA_NAME}.u3_projection_cursor "
            "WHERE project_id=%s AND store=%s",
            (project_id, stream),
        )
        row = cursor.fetchone()
    return int(row[0]) if row is not None and row[0] is not None else 0


def _applied_digest(connection, project_id: str, stream: str, sequence: int) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT payload_digest FROM {SCHEMA_NAME}.u3_applied_owner_event "
            "WHERE project_id=%s AND store=%s AND sequence=%s",
            (project_id, stream, sequence),
        )
        row = cursor.fetchone()
    return str(row[0]) if row is not None else None


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
        "last_applied_seq=EXCLUDED.last_applied_seq, updated_at=now()",
        (project_id, stream, int(last_sequence)),
    )


def _record_applied(connection, project_id: str, stream: str, event: Mapping[str, Any]) -> None:
    connection.execute(
        f"INSERT INTO {SCHEMA_NAME}.u3_applied_owner_event"
        "(project_id, store, sequence, event_kind, entity_type, entity_id, payload_digest) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (project_id, store, sequence) DO UPDATE SET "
        "event_kind=EXCLUDED.event_kind, entity_type=EXCLUDED.entity_type, "
        "entity_id=EXCLUDED.entity_id, payload_digest=EXCLUDED.payload_digest",
        (
            project_id, stream, int(event["sequence"]), str(event["event_kind"]),
            str(event["entity_type"]), str(event["entity_id"]),
            str(event["payload_digest"]),
        ),
    )


def _upsert_evidence_row(
    connection, project_id: str, store: str, table: str, row_key: str,
    row: Mapping[str, Any],
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
                f"UPDATE {SCHEMA_NAME}.table_state SET row_count=row_count+1 "
                "WHERE project_id=%s AND store=%s AND table_name=%s",
                (project_id, store, table),
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
    _upsert_evidence_row(
        connection, project_id, "annotations", "task_negative_confirmations",
        receipt_id,
        {
            "receipt_id": receipt_id, "context_key": context_key,
            "evidence_json": json.dumps(dict(evidence), ensure_ascii=False, sort_keys=True),
        },
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
        if int(event["schema_version"]) != EVENT_SCHEMA_VERSION:
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
            ensure_incremental_schema(connection)
            cursor = _cursor(connection, project, stream)
            try:
                events = read_events(owner, stream, cursor, int(limit))
            except ValueError as error:
                raise U3IncrementalSyncError(
                    "U3_INCREMENTAL_EVENT_INVALID",
                    "the owner change log cannot be verified",
                    detail=str(error),
                ) from error
            if not events:
                return {
                    "stream": stream, "applied": 0, "skipped": 0,
                    "last_sequence": cursor, "has_more": False,
                }
            _validate_batch(events, {stream: cursor}, project, stream)
            applied = 0
            skipped = 0
            previous = cursor
            stale_marked = False
            for event in events:
                sequence = int(event["sequence"])
                prior = _applied_digest(connection, project, stream, sequence)
                if prior is not None:
                    if prior != str(event["payload_digest"]):
                        raise U3IncrementalSyncError(
                            "U3_INCREMENTAL_EVENT_DIGEST_CONFLICT",
                            "the same event identity has a different digest",
                            detail=(
                                f"stream={stream} sequence={sequence} "
                                f"prior={prior} current={event['payload_digest']}"
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
                "has_more": bool(events) and len(events) == int(limit),
            }
