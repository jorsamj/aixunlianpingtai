"""Transactional, immutable owner change log for U3-P3 incremental sync.

The log is written by the business owner in the same SQLite transaction as the
business change.  It is deliberately small and append-only:

* three independent logical streams (``materials``, ``annotations`` and
  ``negative_pool``) each own a monotonic ``sequence`` in their own database;
* every event stores the full projection snapshot that the owner just
  committed, plus a digest computed at write time;
* the event row can never be updated or deleted by normal SQL.

This module contains no consumer and no background worker.  It is the P3-B1
owner-side contract; PostgreSQL consumption lives in
``platform_core/u3_incremental_sync.py``.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

MATERIAL_STREAM = "materials"
ANNOTATION_STREAM = "annotations"
NEGATIVE_POOL_STREAM = "negative_pool"
STREAMS = (MATERIAL_STREAM, ANNOTATION_STREAM, NEGATIVE_POOL_STREAM)
EVENT_SCHEMA_VERSION = 2

#: Real SQLite primary-key columns of every historical evidence table. The
#: order must match ``PRAGMA table_info`` (the P0 exporter uses that order), so
#: the incremental evidence row identity is byte-for-byte the same hash.
EVIDENCE_KEY_COLUMNS: dict[str, tuple[str, ...]] = {
    "material_migrations": ("source",),
    "material_storage_audit": ("task_id", "image_id"),
    "material_retirements": ("task_id", "image_id"),
    "material_cleanup_deferred": ("cleanup_id",),
    "material_assignment_receipts": ("task_id", "image_id"),
    "negative_pool_operations": ("operation_id",),
    "annotation_delete_backup": ("token", "image_id"),
    "annotation_candidate_commits": ("task_id", "image_id"),
    "annotation_negative_reviews": (
        "image_id", "source_version", "actor_id",
        "reviewed_scope_json", "source_content_sha256",
    ),
    "task_negative_confirmations": ("receipt_id",),
}


def evidence_row_key(table: str, row: Mapping[str, Any]) -> str:
    """P0-compatible evidence identity: SHA256 of the real primary-key values."""
    columns = EVIDENCE_KEY_COLUMNS[str(table)]
    values = [row.get(name) for name in columns]
    body = json.dumps(
        values, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS owner_change_meta (
        stream TEXT PRIMARY KEY,
        last_sequence INTEGER NOT NULL CHECK(last_sequence >= 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS owner_change_log (
        stream TEXT NOT NULL,
        sequence INTEGER NOT NULL CHECK(sequence > 0),
        event_kind TEXT NOT NULL CHECK(event_kind IN ('upsert', 'delete')),
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        payload_json TEXT NOT NULL,
        payload_digest TEXT NOT NULL,
        event_digest TEXT,
        created_at TEXT NOT NULL,
        PRIMARY KEY(stream, sequence)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_owner_change_entity
        ON owner_change_log(stream, entity_type, entity_id, sequence)
    """,
    """
    CREATE TRIGGER IF NOT EXISTS owner_change_log_no_update
    BEFORE UPDATE ON owner_change_log BEGIN
        SELECT RAISE(ABORT, 'owner_change_log is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS owner_change_log_no_delete
    BEFORE DELETE ON owner_change_log BEGIN
        SELECT RAISE(ABORT, 'owner_change_log is append-only');
    END
    """,
)

_PROJECT_ID_CACHE: dict[str, str] = {}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def payload_digest(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def event_envelope_digest(event: Mapping[str, Any]) -> str:
    """Digest over the full immutable event envelope and its payload."""
    return payload_digest({
        "stream": str(event["stream"]),
        "sequence": int(event["sequence"]),
        "event_kind": str(event["event_kind"]),
        "entity_type": str(event["entity_type"]),
        "entity_id": str(event["entity_id"]),
        "project_id": str(event["project_id"]),
        "schema_version": int(event["schema_version"]),
        "payload": event["payload"],
    })


def project_id_for_database(database: sqlite3.Connection) -> str:
    """Derive the owner project id from the database file location."""
    row = database.execute(
        "SELECT file FROM pragma_database_list WHERE name='main'"
    ).fetchone()
    path = str(row[0] or "") if row is not None else ""
    if not path:
        raise RuntimeError("owner database has no main file")
    resolved = str(Path(path).resolve())
    cached = _PROJECT_ID_CACHE.get(resolved)
    if cached is not None:
        return cached
    project_id = Path(resolved).parent.name
    _PROJECT_ID_CACHE[resolved] = project_id
    return project_id


def ensure_change_log(
    database: sqlite3.Connection,
    streams: Sequence[str],
    project_id: str,
) -> None:
    """Create the append-only log additively; safe on an existing database."""
    for statement in _DDL:
        database.execute(statement)
    columns = {
        str(row[1])
        for row in database.execute("PRAGMA table_info(owner_change_log)")
    }
    if "event_digest" not in columns:
        # v1 log rows have no envelope digest; they remain readable and are
        # verified with the historical payload-only digest contract.
        database.execute("ALTER TABLE owner_change_log ADD COLUMN event_digest TEXT")
    for stream in streams:
        database.execute(
            "INSERT OR IGNORE INTO owner_change_meta(stream, last_sequence) "
            "VALUES (?, 0)",
            (str(stream),),
        )


def _allocate(
    database: sqlite3.Connection, stream: str, count: int
) -> int:
    row = database.execute(
        "SELECT last_sequence FROM owner_change_meta WHERE stream=?", (stream,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"owner change stream is not initialized: {stream}")
    first = int(row[0]) + 1
    database.execute(
        "UPDATE owner_change_meta SET last_sequence=? WHERE stream=?",
        (first + count - 1, stream),
    )
    return first


def append_events(
    database: sqlite3.Connection,
    stream: str,
    events: Iterable[Mapping[str, Any]],
    *,
    project_id: str | None = None,
    schema_version: int = EVENT_SCHEMA_VERSION,
) -> int:
    """Append events in the caller's current transaction.

    ``events`` items must contain ``event_kind``, ``entity_type``,
    ``entity_id`` and ``payload``.  The sequence is allocated once for the
    batch and every payload digest is computed before any row is inserted.
    The caller owns BEGIN/COMMIT/ROLLBACK; an exception therefore rolls the
    business rows, the sequences and the log rows back together.
    """
    prepared = list(events)
    if not prepared:
        return 0
    project = str(project_id or project_id_for_database(database))
    first = _allocate(database, stream, len(prepared))
    rows = []
    for index, event in enumerate(prepared):
        kind = str(event.get("event_kind") or "upsert")
        if kind not in {"upsert", "delete"}:
            raise ValueError(f"unsupported owner change event kind: {kind}")
        entity_type = str(event.get("entity_type") or "").strip()
        entity_id = str(event.get("entity_id") or "").strip()
        if not entity_type or not entity_id:
            raise ValueError("owner change event requires an entity identity")
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("owner change event payload must be an object")
        sequence = first + index
        payload_json = canonical_json(dict(payload))
        envelope = {
            "stream": stream,
            "sequence": sequence,
            "event_kind": kind,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "project_id": project,
            "schema_version": int(schema_version),
            "payload": dict(payload),
        }
        rows.append((
            stream, sequence, kind, entity_type, entity_id, project,
            int(schema_version), payload_json,
            hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
            payload_digest(envelope),
        ))
    database.executemany(
        "INSERT INTO owner_change_log("
        "stream, sequence, event_kind, entity_type, entity_id, project_id, "
        "schema_version, payload_json, payload_digest, event_digest, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        rows,
    )
    return len(rows)


def append_event(
    database: sqlite3.Connection,
    stream: str,
    event_kind: str,
    entity_type: str,
    entity_id: str,
    payload: Mapping[str, Any],
    *,
    project_id: str | None = None,
) -> int:
    return append_events(
        database,
        stream,
        [{
            "event_kind": event_kind,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "payload": payload,
        }],
        project_id=project_id,
    )


def change_log_ready(database: sqlite3.Connection) -> bool:
    """True when the log table and the v2 envelope digest column exist."""
    try:
        if database.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='owner_change_log'"
        ).fetchone() is None:
            return False
        return any(
            str(row[1]) == "event_digest"
            for row in database.execute("PRAGMA table_info(owner_change_log)")
        )
    except sqlite3.Error:
        return False


def high_water_marks(database: sqlite3.Connection) -> dict[str, int]:
    """Strict high-water read: a SQL failure must not look like an empty log."""
    rows = database.execute(
        "SELECT stream, last_sequence FROM owner_change_meta ORDER BY stream"
    ).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def read_events(
    database: sqlite3.Connection,
    stream: str,
    after_sequence: int,
    limit: int,
    *,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """Read one bounded page in strict sequence order."""
    if int(limit) < 1 or int(limit) > 1000:
        raise ValueError("owner change page size must be between 1 and 1000")
    rows = database.execute(
        "SELECT stream, sequence, event_kind, entity_type, entity_id, "
        "project_id, schema_version, payload_json, payload_digest, event_digest, "
        "created_at FROM owner_change_log WHERE stream=? AND sequence>? "
        "ORDER BY sequence LIMIT ?",
        (str(stream), int(after_sequence), int(limit)),
    ).fetchall()
    result = []
    for row in rows:
        event = {
            "stream": str(row[0]),
            "sequence": int(row[1]),
            "event_kind": str(row[2]),
            "entity_type": str(row[3]),
            "entity_id": str(row[4]),
            "project_id": str(row[5]),
            "schema_version": int(row[6]),
            "payload": json.loads(row[7]),
            "payload_json": str(row[7]),
            "payload_digest": str(row[8]),
            "event_digest": str(row[9]) if row[9] else None,
            "created_at": str(row[10]),
        }
        if project_id is not None and event["project_id"] != str(project_id):
            raise ValueError("owner change event belongs to another project")
        if payload_digest(event["payload"]) != event["payload_digest"]:
            raise ValueError("owner change event payload digest does not match")
        if event["schema_version"] >= 2:
            if not event["event_digest"]:
                raise ValueError("v2 owner change event has no envelope digest")
            if event_envelope_digest(event) != event["event_digest"]:
                raise ValueError("owner change event envelope digest does not match")
        elif event["event_digest"] is not None:
            raise ValueError("v1 owner change event unexpectedly carries an envelope digest")
        result.append(event)
    return result


def _material_labels(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    counts = row.get("label_counts") if isinstance(row.get("label_counts"), Mapping) else {}
    return [
        {"label_code": str(label), "box_count": max(0, int(counts.get(label) or 0))}
        for label in row.get("labels") or []
    ]


def _material_scopes(row: Mapping[str, Any]) -> list[str]:
    return sorted({
        str(label).strip()
        for label in row.get("annotation_scope") or []
        if str(label).strip()
    })


def material_projection(
    row: Mapping[str, Any], *,
    labels: Sequence[Mapping[str, Any]] | None = None,
    annotation_scope: Sequence[str] | None = None,
) -> dict[str, Any]:
    """The exact material projection committed by the owner write."""
    normalized = dict(row)
    return {
        "id": str(normalized["id"]),
        "filename": str(normalized.get("filename") or ""),
        "storage_source_id": str(normalized.get("storage_source_id") or "default_local"),
        "storage_type": str(normalized.get("storage_type") or "local"),
        "object_key": str(normalized.get("object_key") or ""),
        "content_sha256": str(normalized.get("content_sha256") or ""),
        "size_bytes": int(normalized.get("size_bytes") or 0),
        "etag": str(normalized.get("etag") or ""),
        "processing_status": str(normalized.get("processing_status") or "pending_decision"),
        "box_count": int(normalized.get("box_count") or 0),
        "annotated": bool(normalized.get("annotated")),
        "created_at": str(normalized.get("created_at") or ""),
        "updated_at": str(normalized.get("updated_at") or ""),
        "payload": normalized,
        "labels": list(labels) if labels is not None else _material_labels(normalized),
        "annotation_scope": (
            list(annotation_scope) if annotation_scope is not None
            else _material_scopes(normalized)
        ),
    }


def append_material_event(
    database: sqlite3.Connection,
    row: Mapping[str, Any],
    *,
    event_kind: str = "upsert",
    reason: str = "",
    project_id: str | None = None,
) -> None:
    payload = material_projection(row)
    if reason:
        payload["reason"] = str(reason)
    append_event(
        database,
        MATERIAL_STREAM,
        event_kind,
        "material",
        str(row["id"]),
        payload,
        project_id=project_id,
    )


def append_material_events(
    database: sqlite3.Connection,
    rows: Iterable[Mapping[str, Any]],
    *,
    project_id: str | None = None,
) -> int:
    prepared = [
        {
            "event_kind": "upsert",
            "entity_type": "material",
            "entity_id": str(row["id"]),
            "payload": material_projection(row),
        }
        for row in rows
    ]
    return append_events(
        database, MATERIAL_STREAM, prepared, project_id=project_id
    )


def append_material_delete(
    database: sqlite3.Connection,
    image_id: str,
    last_payload: Mapping[str, Any] | None,
    *,
    reason: str = "deleted",
    project_id: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "id": str(image_id),
        "deleted": True,
        "reason": str(reason),
        "last_payload": dict(last_payload) if last_payload is not None else None,
    }
    append_event(
        database,
        MATERIAL_STREAM,
        "delete",
        "material",
        str(image_id),
        payload,
        project_id=project_id,
    )


def append_material_deletes(
    database: sqlite3.Connection,
    rows: Iterable[Mapping[str, Any]],
    *,
    reason: str = "deleted",
    project_id: str | None = None,
) -> int:
    prepared = [
        {
            "event_kind": "delete",
            "entity_type": "material",
            "entity_id": str(row["id"]),
            "payload": {
                "id": str(row["id"]),
                "deleted": True,
                "reason": str(reason),
                "last_payload": dict(row),
            },
        }
        for row in rows
    ]
    return append_events(
        database, MATERIAL_STREAM, prepared, project_id=project_id
    )


def append_annotation_events(
    database: sqlite3.Connection,
    image_ids: Iterable[str],
    *,
    project_id: str | None = None,
) -> int:
    ids = list(dict.fromkeys(str(value) for value in image_ids if str(value)))
    if not ids:
        return 0
    events = []
    for offset in range(0, len(ids), 500):
        chunk = ids[offset:offset + 500]
        placeholders = ",".join("?" for _ in chunk)
        rows = database.execute(
            f"SELECT * FROM annotations WHERE image_id IN ({placeholders})",
            chunk,
        ).fetchall()
        references: dict[str, list[dict[str, Any]]] = {}
        for ref in database.execute(
            "SELECT image_id, label_code, box_count, scope_ref, annotation_state, "
            "source_kind FROM annotation_label_references "
            f"WHERE image_id IN ({placeholders}) "
            "ORDER BY image_id, label_code",
            chunk,
        ):
            references.setdefault(str(ref[0]), []).append({
                "label_code": str(ref[1]),
                "box_count": int(ref[2]),
                "scope_ref": int(ref[3]),
                "annotation_state": str(ref[4]),
                "source_kind": str(ref[5]),
            })
        for row in rows:
            image_id = str(row["image_id"])
            events.append({
                "event_kind": "upsert",
                "entity_type": "annotation",
                "entity_id": image_id,
                "payload": {
                    "image_id": image_id,
                    "annotation_state": str(row["annotation_state"]),
                    "version": int(row["version"]),
                    "content_digest": str(row["content_digest"]),
                    "boxes": json.loads(row["boxes_json"] or "[]"),
                    "scope": json.loads(row["scope_json"] or "[]"),
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["updated_at"]),
                    "label_references": references.get(image_id, []),
                },
            })
    return append_events(
        database, ANNOTATION_STREAM, events, project_id=project_id
    )


def append_annotation_delete(
    database: sqlite3.Connection,
    image_id: str,
    *,
    last_version: int = 0,
    last_content_digest: str = "",
    reason: str = "deleted",
    project_id: str | None = None,
) -> None:
    append_event(
        database,
        ANNOTATION_STREAM,
        "delete",
        "annotation",
        str(image_id),
        {
            "image_id": str(image_id),
            "deleted": True,
            "reason": str(reason),
            "last_version": int(last_version),
            "last_content_digest": str(last_content_digest),
        },
        project_id=project_id,
    )


def append_annotation_deletes(
    database: sqlite3.Connection,
    rows: Iterable[sqlite3.Row],
    *,
    reason: str = "deleted",
    project_id: str | None = None,
) -> int:
    prepared = [
        {
            "event_kind": "delete",
            "entity_type": "annotation",
            "entity_id": str(row["image_id"]),
            "payload": {
                "image_id": str(row["image_id"]),
                "deleted": True,
                "reason": str(reason),
                "last_version": int(row["version"]),
                "last_content_digest": str(row["content_digest"]),
            },
        }
        for row in rows
    ]
    return append_events(
        database, ANNOTATION_STREAM, prepared, project_id=project_id
    )


def append_confirmation_event(
    database: sqlite3.Connection,
    receipt_id: str,
    context_key: str,
    evidence: Mapping[str, Any],
    *,
    project_id: str | None = None,
) -> None:
    append_event(
        database,
        ANNOTATION_STREAM,
        "upsert",
        "task_negative_confirmation",
        str(receipt_id),
        {
            "receipt_id": str(receipt_id),
            "context_key": str(context_key),
            "image_id": str(evidence.get("image_id") or ""),
            "evidence": dict(evidence),
        },
        project_id=project_id,
    )


def append_evidence_event(
    database: sqlite3.Connection,
    store: str,
    table: str,
    row: Mapping[str, Any],
    *,
    event_kind: str = "upsert",
    project_id: str | None = None,
) -> None:
    key = evidence_row_key(table, row)
    schema_version = int(database.execute("PRAGMA user_version").fetchone()[0])
    append_event(
        database,
        MATERIAL_STREAM if store == "materials" else ANNOTATION_STREAM,
        event_kind,
        f"evidence:{table}",
        key,
        {"store": str(store), "table": str(table), "row_key": key,
         "schema_version": schema_version, "row": dict(row)},
        project_id=project_id,
    )


def append_evidence_events(
    database: sqlite3.Connection,
    store: str,
    entries: Iterable[tuple[str, Mapping[str, Any]]],
    *,
    event_kind: str = "upsert",
    project_id: str | None = None,
) -> int:
    prepared = []
    schema_version = int(database.execute("PRAGMA user_version").fetchone()[0])
    for table, row in entries:
        key = evidence_row_key(table, row)
        prepared.append({
            "event_kind": event_kind,
            "entity_type": f"evidence:{table}",
            "entity_id": key,
            "payload": {
                "store": str(store),
                "table": str(table),
                "row_key": key,
                "schema_version": schema_version,
                "row": dict(row),
            },
        })
    return append_events(
        database,
        MATERIAL_STREAM if store == "materials" else ANNOTATION_STREAM,
        prepared,
        project_id=project_id,
    )


def negative_pool_member_payload(
    database: sqlite3.Connection, material_id: str
) -> dict[str, Any]:
    member = database.execute(
        "SELECT joined_at FROM negative_pool_members WHERE material_id=?",
        (str(material_id),),
    ).fetchone()
    links = [
        {"category_id": str(row[0])}
        for row in database.execute(
            "SELECT category_id FROM negative_pool_links "
            "WHERE material_id=? ORDER BY category_id",
            (str(material_id),),
        )
    ]
    algorithms = [
        {"algorithm_id": str(row[0]), "joined_at": str(row[1])}
        for row in database.execute(
            "SELECT algorithm_id, joined_at FROM negative_pool_algorithm_members "
            "WHERE material_id=? ORDER BY algorithm_id",
            (str(material_id),),
        )
    ]
    return {
        "material_id": str(material_id),
        "member": None if member is None else {"joined_at": str(member[0])},
        "links": links,
        "algorithms": algorithms,
    }


def append_negative_pool_member(
    database: sqlite3.Connection,
    material_id: str,
    *,
    project_id: str | None = None,
) -> None:
    payload = negative_pool_member_payload(database, material_id)
    append_event(
        database,
        NEGATIVE_POOL_STREAM,
        "upsert" if payload["member"] is not None else "delete",
        "negative_pool_member",
        str(material_id),
        payload,
        project_id=project_id,
    )


def append_negative_pool_category(
    database: sqlite3.Connection,
    category_id: str,
    *,
    last_row: Mapping[str, Any] | None = None,
    project_id: str | None = None,
) -> None:
    row = database.execute(
        "SELECT id, name, enabled FROM negative_pool_categories WHERE id=?",
        (str(category_id),),
    ).fetchone()
    if row is None:
        payload = {
            "id": str(category_id),
            "deleted": True,
            "last_row": dict(last_row) if last_row is not None else None,
        }
        append_event(
            database, NEGATIVE_POOL_STREAM, "delete",
            "negative_pool_category", str(category_id), payload,
            project_id=project_id,
        )
        return
    append_event(
        database,
        NEGATIVE_POOL_STREAM,
        "upsert",
        "negative_pool_category",
        str(category_id),
        {"id": str(row[0]), "name": str(row[1]), "enabled": bool(row[2])},
        project_id=project_id,
    )
