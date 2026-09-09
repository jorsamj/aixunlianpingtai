from __future__ import annotations

import base64
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Iterable, Mapping, Sequence, TypeVar

from .material_selection import MaterialFilters
from .material_store import MaterialSnapshot


_Result = TypeVar("_Result")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS materials (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL DEFAULT '',
    storage_source_id TEXT NOT NULL DEFAULT 'default_local',
    storage_type TEXT NOT NULL DEFAULT 'local',
    object_key TEXT NOT NULL,
    content_sha256 TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    etag TEXT NOT NULL DEFAULT '',
    processing_status TEXT NOT NULL DEFAULT 'pending_decision',
    box_count INTEGER NOT NULL DEFAULT 0,
    annotated INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_materials_source ON materials(storage_source_id, created_at, id);
CREATE INDEX IF NOT EXISTS ix_materials_reference ON materials(storage_source_id, object_key);
CREATE INDEX IF NOT EXISTS ix_materials_status ON materials(processing_status, created_at, id);
CREATE INDEX IF NOT EXISTS ix_materials_filename ON materials(filename COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS ix_materials_created ON materials(created_at, id);
CREATE INDEX IF NOT EXISTS ix_materials_content_sha256 ON materials(content_sha256) WHERE content_sha256 <> '';
CREATE INDEX IF NOT EXISTS ix_materials_content_sha256_normalized ON materials(lower(trim(content_sha256))) WHERE content_sha256 <> '';
CREATE TABLE IF NOT EXISTS material_labels (
    material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    label_code TEXT NOT NULL,
    PRIMARY KEY(material_id, label_code)
);
CREATE INDEX IF NOT EXISTS ix_material_labels_code ON material_labels(label_code, material_id);
CREATE TABLE IF NOT EXISTS material_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO material_meta(key, value) VALUES ('revision', '0');
CREATE TABLE IF NOT EXISTS material_migrations (
    source TEXT PRIMARY KEY,
    signature TEXT NOT NULL,
    imported_count INTEGER NOT NULL,
    imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS material_storage_audit (
    task_id TEXT NOT NULL, image_id TEXT NOT NULL, action TEXT NOT NULL,
    old_sha256 TEXT NOT NULL, new_sha256 TEXT NOT NULL, recorded_at TEXT NOT NULL,
    PRIMARY KEY(task_id,image_id)
);
"""


@dataclass(frozen=True)
class MaterialPage:
    items: list[dict[str, Any]]
    next_cursor: str | None
    total: int


@dataclass(frozen=True)
class MaterialIdPage:
    items: list[str]
    next_cursor: str | None
    total: int

    def __iter__(self):
        return iter(self.items)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _basename(value: object) -> str:
    raw = str(value or "")
    if not raw or "\x00" in raw:
        return ""
    if "\\" in raw:
        return PureWindowsPath(raw).name
    return Path(raw).name


def _portable_stored_name(image_id: str, object_key: object, filename: object = "") -> str:
    """Return a collision-safe local working name for externally indexed material.

    Historical external rows may have stored_name="" because no copy lives in project/uploads.
    Legacy dataset/export code still expects a basename, so expose a deterministic image-id name
    without changing the physical storage reference.
    """
    suffix = Path(str(object_key or filename or "")).suffix.lower()
    if not suffix or len(suffix) > 12 or not suffix.startswith(".") or not suffix[1:].isalnum():
        suffix = ".bin"
    return f"{image_id}{suffix}"


def normalize_material(value: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(value)
    image_id = str(row.get("id") or "").strip()
    if not image_id:
        raise ValueError("素材 id 不能为空")
    source_id = str(row.get("storage_source_id") or "default_local").strip()
    storage_type = str(row.get("storage_type") or ("local" if source_id == "default_local" else "remote")).strip().lower()
    stored_name = _basename(row.get("stored_name"))
    if not stored_name and source_id == "default_local":
        stored_name = _basename(row.get("filename"))
    object_key = str(row.get("object_key") or "").replace("\\", "/").lstrip("/")
    if not object_key and stored_name:
        object_key = f"uploads/{stored_name}"
    if not object_key:
        raise ValueError(f"素材 {image_id} 缺少 object_key")
    if ".." in Path(object_key).parts or PureWindowsPath(object_key).drive:
        raise ValueError(f"素材 {image_id} 的 object_key 非法")
    if not stored_name:
        if source_id == "default_local":
            stored_name = Path(object_key).name
        else:
            stored_name = _portable_stored_name(image_id, object_key, row.get("filename"))
    labels = sorted({str(label).strip() for label in row.get("labels") or [] if str(label).strip()})
    row.update({
        "id": image_id,
        "filename": str(row.get("filename") or stored_name or image_id),
        "stored_name": stored_name,
        "storage_source_id": source_id,
        "storage_type": storage_type,
        "object_key": object_key,
        "content_sha256": str(row.get("content_sha256") or "").strip().lower(),
        "size_bytes": max(0, int(row.get("size_bytes") or 0)),
        "etag": str(row.get("etag") or ""),
        "processing_status": str(row.get("processing_status") or "pending_decision"),
        "box_count": max(0, int(row.get("box_count") or 0)),
        "annotated": bool(row.get("annotated") or int(row.get("box_count") or 0) > 0),
        "labels": labels,
        "created_at": str(row.get("created_at") or _now()),
        "updated_at": str(row.get("updated_at") or ""),
    })
    return row


def _encode_cursor(created_at: str, image_id: str) -> str:
    raw = json.dumps([created_at, image_id], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded = str(cursor) + "=" * (-len(str(cursor)) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError
        return str(value[0]), str(value[1])
    except Exception as error:
        raise ValueError("invalid material cursor") from error


class MaterialRepository:
    def __init__(self, project_path: str | Path) -> None:
        self.project_path = Path(project_path)
        self.project_path.mkdir(parents=True, exist_ok=True)
        self.path = self.project_path / "materials.sqlite3"
        with self._connect() as database:
            database.executescript(_SCHEMA)
        self._migrate_legacy_json()

    def _connect(self) -> sqlite3.Connection:
        database = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("PRAGMA foreign_keys=ON")
        database.execute("PRAGMA busy_timeout=30000")
        return database

    def journal_mode(self) -> str:
        with self._connect() as database:
            return str(database.execute("PRAGMA journal_mode").fetchone()[0]).lower()

    def current_revision(self) -> int:
        with self._connect() as database:
            return self._revision(database)

    @staticmethod
    def _row_payload(row: sqlite3.Row) -> dict[str, Any]:
        value = json.loads(row["payload_json"])
        if not isinstance(value, dict):
            raise ValueError("material payload is invalid")
        payload = dict(value)
        if not _basename(payload.get("stored_name")):
            image_id = str(payload.get("id") or "").strip()
            source_id = str(payload.get("storage_source_id") or "default_local").strip()
            object_key = str(payload.get("object_key") or "").replace("\\", "/").lstrip("/")
            if image_id and source_id != "default_local" and object_key:
                payload["stored_name"] = _portable_stored_name(
                    image_id, object_key, payload.get("filename")
                )
            elif object_key:
                payload["stored_name"] = _basename(object_key)
        return payload

    @staticmethod
    def _revision(database: sqlite3.Connection) -> int:
        return int(database.execute("SELECT value FROM material_meta WHERE key = 'revision'").fetchone()[0])

    @staticmethod
    def _bump_revision(database: sqlite3.Connection) -> None:
        database.execute("UPDATE material_meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'revision'")

    @staticmethod
    def _write_row(database: sqlite3.Connection, value: Mapping[str, Any]) -> dict[str, Any]:
        row = normalize_material(value)
        database.execute(
            """
            INSERT INTO materials
            (id, filename, storage_source_id, storage_type, object_key, content_sha256,
             size_bytes, etag, processing_status, box_count, annotated, created_at,
             updated_at, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              filename=excluded.filename, storage_source_id=excluded.storage_source_id,
              storage_type=excluded.storage_type, object_key=excluded.object_key,
              content_sha256=excluded.content_sha256, size_bytes=excluded.size_bytes,
              etag=excluded.etag, processing_status=excluded.processing_status,
              box_count=excluded.box_count, annotated=excluded.annotated,
              created_at=excluded.created_at, updated_at=excluded.updated_at,
              payload_json=excluded.payload_json
            """,
            (
                row["id"], row["filename"], row["storage_source_id"], row["storage_type"],
                row["object_key"], row["content_sha256"], row["size_bytes"], row["etag"],
                row["processing_status"], row["box_count"], int(row["annotated"]),
                row["created_at"], row["updated_at"],
                json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )
        database.execute("DELETE FROM material_labels WHERE material_id = ?", (row["id"],))
        database.executemany(
            "INSERT INTO material_labels(material_id, label_code) VALUES (?, ?)",
            ((row["id"], label) for label in row["labels"]),
        )
        return row

    def _migrate_legacy_json(self) -> None:
        legacy = self.project_path / "images.json"
        if not legacy.is_file():
            return
        stat = legacy.stat()
        signature = f"{stat.st_size}:{stat.st_mtime_ns}"
        with self._connect() as database:
            migrated = database.execute(
                "SELECT 1 FROM material_migrations WHERE source = 'images.json'"
            ).fetchone()
            existing = int(database.execute("SELECT COUNT(*) FROM materials").fetchone()[0])
        if migrated or existing:
            return
        value = json.loads(legacy.read_text(encoding="utf-8"))
        rows = value.get("items", []) if isinstance(value, dict) else value
        if not isinstance(rows, list):
            raise ValueError("images.json 必须是数组")
        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            try:
                for source in rows:
                    self._write_row(database, source)
                if rows:
                    self._bump_revision(database)
                database.execute(
                    "INSERT INTO material_migrations(source, signature, imported_count, imported_at) VALUES (?, ?, ?, ?)",
                    ("images.json", signature, len(rows), _now()),
                )
                database.execute("COMMIT")
            except Exception:
                database.execute("ROLLBACK")
                raise

    def read(self) -> MaterialSnapshot:
        with self._connect() as database:
            revision = self._revision(database)
            rows = database.execute("SELECT payload_json FROM materials ORDER BY created_at, id").fetchall()
        return MaterialSnapshot(revision=revision, rows=[self._row_payload(row) for row in rows])

    def get(self, image_id: str) -> dict[str, Any] | None:
        with self._connect() as database:
            row = database.execute("SELECT payload_json FROM materials WHERE id = ?", (str(image_id),)).fetchone()
        return self._row_payload(row) if row else None

    def get_many(self, image_ids: Iterable[str]) -> list[dict[str, Any]]:
        ids = list(dict.fromkeys(str(value) for value in image_ids if str(value)))
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as database:
            rows = database.execute(
                f"SELECT id, payload_json FROM materials WHERE id IN ({placeholders})", ids
            ).fetchall()
        by_id = {str(row["id"]): self._row_payload(row) for row in rows}
        return [by_id[image_id] for image_id in ids if image_id in by_id]

    def find_existing_content_hashes(self, hashes: Iterable[str]) -> set[str]:
        """Return normalized content SHA256 values already indexed by the repository."""
        existing: set[str] = set()
        pending: set[str] = set()

        def fetch_pending(database: sqlite3.Connection) -> None:
            if not pending:
                return
            batch = tuple(pending)
            database.executemany(
                "INSERT OR IGNORE INTO material_content_hash_lookup(content_sha256) VALUES (?)",
                ((content_hash,) for content_hash in batch),
            )
            placeholders = ",".join("?" for _ in batch)
            unchecked = tuple(
                str(row["content_sha256"])
                for row in database.execute(
                    "SELECT content_sha256 FROM material_content_hash_lookup "
                    f"WHERE processed = 0 AND content_sha256 IN ({placeholders})",
                    batch,
                ).fetchall()
            )
            if not unchecked:
                pending.clear()
                return
            lookup_placeholders = ",".join("?" for _ in unchecked)
            rows = database.execute(
                "SELECT DISTINCT content_sha256 FROM materials "
                f"WHERE content_sha256 <> '' AND content_sha256 IN ({lookup_placeholders})",
                unchecked,
            ).fetchall()
            exact_matches = {str(row["content_sha256"]).strip().lower() for row in rows}
            existing.update(exact_matches)
            unmatched = tuple(content_hash for content_hash in unchecked if content_hash not in exact_matches)
            if unmatched:
                normalized_placeholders = ",".join("?" for _ in unmatched)
                normalized_rows = database.execute(
                    "SELECT DISTINCT lower(trim(content_sha256)) AS content_sha256 FROM materials "
                    "WHERE content_sha256 <> '' "
                    f"AND lower(trim(content_sha256)) IN ({normalized_placeholders})",
                    unmatched,
                ).fetchall()
                existing.update(str(row["content_sha256"]).strip().lower() for row in normalized_rows)
            database.execute(
                "UPDATE material_content_hash_lookup SET processed = 1 "
                f"WHERE content_sha256 IN ({lookup_placeholders})",
                unchecked,
            )
            pending.clear()

        with closing(self._connect()) as database:
            database.execute("PRAGMA temp_store=FILE")
            database.execute(
                "CREATE TEMP TABLE material_content_hash_lookup ("
                "content_sha256 TEXT PRIMARY KEY, processed INTEGER NOT NULL DEFAULT 0"
                ") WITHOUT ROWID"
            )
            for value in hashes:
                content_hash = str(value or "").strip().lower()
                if not content_hash or content_hash in existing:
                    continue
                pending.add(content_hash)
                if len(pending) == 500:
                    fetch_pending(database)
            fetch_pending(database)
        return existing

    def find_existing_storage_references(
        self, references: Iterable[tuple[object, object]],
    ) -> set[tuple[str, str]]:
        """Return exact source/object-key pairs already present, in bounded batches."""
        existing: set[tuple[str, str]] = set()
        pending: set[tuple[str, str]] = set()

        with closing(self._connect()) as database:
            database.execute("PRAGMA temp_store=FILE")
            database.execute(
                "CREATE TEMP TABLE requested_material_references ("
                "storage_source_id TEXT NOT NULL, object_key TEXT NOT NULL, "
                "PRIMARY KEY(storage_source_id, object_key)) WITHOUT ROWID"
            )

            def fetch_pending() -> None:
                if not pending:
                    return
                database.executemany(
                    "INSERT OR IGNORE INTO requested_material_references VALUES (?, ?)",
                    pending,
                )
                existing.update(
                    (str(row[0]), str(row[1]))
                    for row in database.execute(
                        "SELECT DISTINCT m.storage_source_id, m.object_key "
                        "FROM materials m JOIN requested_material_references r "
                        "ON r.storage_source_id=m.storage_source_id AND r.object_key=m.object_key"
                    )
                )
                database.execute("DELETE FROM requested_material_references")
                pending.clear()

            for source_id, object_key in references:
                reference = (str(source_id or "").strip(), str(object_key or ""))
                if not reference[0] or not reference[1] or reference in existing:
                    continue
                pending.add(reference)
                if len(pending) == 500:
                    fetch_pending()
            fetch_pending()
        return existing

    @staticmethod
    def _filters(
        filters: MaterialFilters | Mapping[str, Any] | None = None, **legacy_filters: Any,
    ) -> tuple[list[str], list[Any]]:
        """Build the sole authoritative SQL predicate for material selections."""
        if filters is not None and legacy_filters:
            raise ValueError("pass either filters or keyword filters, not both")
        selected = MaterialFilters.from_mapping(filters if filters is not None else legacy_filters)
        clauses: list[str] = []
        params: list[Any] = []
        if selected.query:
            clauses.append("m.filename LIKE ? COLLATE NOCASE")
            params.append(f"%{selected.query}%")
        if selected.storage_source_ids:
            clauses.append("m.storage_source_id IN (" + ",".join("?" for _ in selected.storage_source_ids) + ")")
            params.extend(selected.storage_source_ids)
        if selected.processing_status:
            normalized_status = selected.processing_status
            if normalized_status == "unprocessed":
                clauses.append("m.processing_status IN ('unprocessed','pending_decision','cleaning')")
            else:
                clauses.append("m.processing_status = ?")
                params.append(normalized_status)
        if selected.split:
            clauses.append("COALESCE(json_extract(m.payload_json, '$.split'), 'unassigned') = ?")
            params.append(selected.split)
        if selected.annotated is not None:
            clauses.append("m.annotated = ?")
            params.append(int(selected.annotated))
        if selected.annotation_state:
            clauses.append(
                "COALESCE(json_extract(m.payload_json, '$.annotation_state'), "
                "json_extract(m.payload_json, '$.annotation_status'), "
                "CASE WHEN m.annotated <> 0 THEN 'annotated' ELSE 'unannotated' END) = ?"
            )
            params.append(selected.annotation_state)
        if selected.labels:
            clauses.append(
                "EXISTS (SELECT 1 FROM material_labels ml WHERE ml.material_id = m.id AND ml.label_code IN ("
                + ",".join("?" for _ in selected.labels) + "))"
            )
            params.extend(selected.labels)
        return clauses, params

    def count(self, **filters: Any) -> int:
        return self.count_filtered(filters)

    def summary(self) -> dict[str, int]:
        """Read indexed counters without hydrating material payloads or files."""
        with self._connect() as database:
            row = database.execute("""SELECT COUNT(*) AS total,
                COALESCE(SUM(annotated), 0) AS annotated,
                COALESCE(SUM(box_count), 0) AS boxes
                FROM materials""").fetchone()
            return {**{key: int(row[key]) for key in row.keys()},
                    "revision": self._revision(database)}

    def count_filtered(self, filters: MaterialFilters | Mapping[str, Any] | None = None) -> int:
        clauses, params = self._filters(filters)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as database:
            return int(database.execute("SELECT COUNT(*) FROM materials m" + where, params).fetchone()[0])

    def list_page(
        self, *, cursor: str | None = None, limit: int = 100, query: str = "",
        storage_source_ids: Sequence[str] | None = None, processing_status: str | None = None,
        labels: Sequence[str] | None = None, annotated: bool | None = None,
        split: str | None = None, annotation_state: str | None = None,
    ) -> MaterialPage:
        bounded = max(1, min(1000, int(limit)))
        filter_values = MaterialFilters(
            query=query, storage_source_ids=tuple(storage_source_ids or ()),
            processing_status=processing_status, split=split, labels=tuple(labels or ()),
            annotated=annotated, annotation_state=annotation_state,
        )
        clauses, params = self._filters(filter_values)
        if cursor:
            created_at, image_id = _decode_cursor(cursor)
            clauses.append("(m.created_at > ? OR (m.created_at = ? AND m.id > ?))")
            params.extend((created_at, created_at, image_id))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as database:
            rows = database.execute(
                "SELECT m.id, m.created_at, m.payload_json FROM materials m" + where + " ORDER BY m.created_at, m.id LIMIT ?",
                [*params, bounded + 1],
            ).fetchall()
        visible = rows[:bounded]
        next_cursor = None
        if len(rows) > bounded and visible:
            next_cursor = _encode_cursor(str(visible[-1]["created_at"]), str(visible[-1]["id"]))
        return MaterialPage(
            items=[self._row_payload(row) for row in visible], next_cursor=next_cursor,
            total=self.count_filtered(filter_values),
        )

    def iter_filtered_ids(
        self, filters: MaterialFilters | Mapping[str, Any] | None = None,
        cursor: str | None = None, limit: int = 500, *, include_total: bool = True,
    ) -> MaterialIdPage:
        selected = MaterialFilters.from_mapping(filters)
        bounded = max(1, min(500, int(limit)))
        clauses, params = self._filters(selected)
        if cursor:
            created_at, image_id = _decode_cursor(cursor)
            clauses.append("(m.created_at > ? OR (m.created_at = ? AND m.id > ?))")
            params.extend((created_at, created_at, image_id))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as database:
            rows = database.execute(
                "SELECT m.id, m.created_at FROM materials m" + where
                + " ORDER BY m.created_at, m.id LIMIT ?",
                [*params, bounded + 1],
            ).fetchall()
        visible = rows[:bounded]
        next_cursor = None
        if len(rows) > bounded and visible:
            next_cursor = _encode_cursor(str(visible[-1]["created_at"]), str(visible[-1]["id"]))
        return MaterialIdPage(
            items=[str(row["id"]) for row in visible], next_cursor=next_cursor,
            total=self.count_filtered(selected) if include_total else -1,
        )

    def list_ids(self, **kwargs: Any) -> MaterialIdPage:
        page = self.list_page(**kwargs)
        return MaterialIdPage([str(row["id"]) for row in page.items], page.next_cursor, page.total)

    def upsert(self, record: Mapping[str, Any]) -> dict[str, Any]:
        image_id = str(record.get("id") or "")
        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            try:
                existing = database.execute("SELECT payload_json FROM materials WHERE id = ?", (image_id,)).fetchone()
                merged = self._row_payload(existing) if existing else {}
                merged.update(dict(record))
                persisted = self._write_row(database, merged)
                self._bump_revision(database)
                database.execute("COMMIT")
            except Exception:
                database.execute("ROLLBACK")
                raise
        return persisted

    def upsert_many(self, records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        incoming = [dict(record) for record in records]
        if not incoming:
            return []
        persisted = []
        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            try:
                for record in incoming:
                    image_id = str(record.get("id") or "")
                    existing = database.execute("SELECT payload_json FROM materials WHERE id = ?", (image_id,)).fetchone()
                    merged = self._row_payload(existing) if existing else {}
                    merged.update(record)
                    persisted.append(self._write_row(database, merged))
                self._bump_revision(database)
                database.execute("COMMIT")
            except Exception:
                database.execute("ROLLBACK")
                raise
        return persisted

    def patch(self, patches: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
        changed = []
        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            try:
                for image_id, patch in patches.items():
                    existing = database.execute("SELECT payload_json FROM materials WHERE id = ?", (str(image_id),)).fetchone()
                    if not existing:
                        continue
                    merged = self._row_payload(existing)
                    merged.update(dict(patch))
                    changed.append(self._write_row(database, merged))
                if changed:
                    self._bump_revision(database)
                database.execute("COMMIT")
            except Exception:
                database.execute("ROLLBACK")
                raise
        return changed

    def remove(self, image_ids: Iterable[str]) -> list[dict[str, Any]]:
        ids = list(dict.fromkeys(str(value) for value in image_ids if str(value)))
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            try:
                rows = database.execute(f"SELECT id, payload_json FROM materials WHERE id IN ({placeholders})", ids).fetchall()
                by_id = {str(row["id"]): self._row_payload(row) for row in rows}
                database.execute(f"DELETE FROM materials WHERE id IN ({placeholders})", ids)
                if rows:
                    self._bump_revision(database)
                database.execute("COMMIT")
            except Exception:
                database.execute("ROLLBACK")
                raise
        return [by_id[image_id] for image_id in ids if image_id in by_id]

    def reference_count(self, storage_source_id: str) -> int:
        with self._connect() as database:
            return int(database.execute("SELECT COUNT(*) FROM materials WHERE storage_source_id = ?", (str(storage_source_id),)).fetchone()[0])

    def snapshot_storage_references(self, manifest_path, source_id):
        """Copy only index metadata to the task DB in a consistent SQLite snapshot."""
        with closing(self._connect()) as db:
            db.execute('ATTACH DATABASE ? AS rescan', (str(manifest_path),))
            db.execute('BEGIN IMMEDIATE')
            try:
                db.execute('DELETE FROM rescan.rescan_baseline')
                db.execute('INSERT INTO rescan.rescan_baseline SELECT id,object_key,payload_json '
                           'FROM materials WHERE storage_source_id=?', (source_id,))
                db.execute("INSERT OR REPLACE INTO rescan.rescan_meta VALUES('baseline_complete','true')")
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def reconcile_storage_batch(self, task_id, source_id, changes):
        """Preserve annotation payload and atomically audit idempotent metadata patches."""
        changes = list(changes)
        if len(changes) > 500:
            raise ValueError('reconciliation batch is limited to 500 objects')
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                db.execute('CREATE TEMP TABLE changes(object_key TEXT PRIMARY KEY,payload TEXT)')
                db.executemany('INSERT INTO changes VALUES(?,?)',
                               ((r['object_key'], json.dumps(r)) for r in changes))
                cursor = db.execute('SELECT m.id,m.payload_json,c.payload FROM materials m '
                    'JOIN changes c USING(object_key) LEFT JOIN material_storage_audit a '
                    'ON a.task_id=? AND a.image_id=m.id WHERE m.storage_source_id=? AND a.image_id IS NULL',
                    (task_id, source_id))
                count = 0
                while rows := cursor.fetchmany(500):
                    updates, audits = [], []
                    for row in rows:
                        current, change = json.loads(row[1]), json.loads(row[2])
                        old_hash = str(current.get('content_sha256') or '')
                        if old_hash != str(change.get('old_sha256') or ''):
                            raise ValueError('material changed since rescan; create a new rescan')
                        action = change['category']
                        if action == 'MISSING':
                            current.update(source_available=False, source_status='MISSING')
                        else:
                            for field in ('content_sha256', 'size_bytes', 'etag', 'width', 'height'):
                                current[field] = change[field]
                            current.update(source_available=True, source_status='AVAILABLE')
                            if action == 'CHANGED':
                                current.update(needs_review=True, annotation_needs_review=True,
                                    annotation_review_reason='SOURCE_CONTENT_CHANGED',
                                    content_cache_generation=change['content_sha256'])
                        now = _now()
                        current.update(storage_rescan_task_id=task_id, updated_at=now)
                        updates.append((current.get('content_sha256', ''), current.get('size_bytes', 0),
                                        current.get('etag', ''), now, json.dumps(current), row[0]))
                        audits.append((task_id, row[0], action, old_hash,
                                       current.get('content_sha256', ''), now))
                    db.executemany('UPDATE materials SET content_sha256=?,size_bytes=?,etag=?,updated_at=?,payload_json=? WHERE id=?', updates)
                    db.executemany('INSERT INTO material_storage_audit VALUES(?,?,?,?,?,?)', audits)
                    count += len(updates)
                if count:
                    self._bump_revision(db)
                db.commit()
                return count
            except BaseException:
                db.rollback()
                raise

    def get_by_storage_references(self, references) -> dict[tuple[str, str], dict]:
        references = list(references)
        if len(references) > 500:
            raise ValueError("storage reference lookup is limited to 500")
        with closing(self._connect()) as db:
            db.execute("CREATE TEMP TABLE requested_refs(source TEXT, key TEXT, PRIMARY KEY(source,key))")
            db.executemany("INSERT OR IGNORE INTO requested_refs VALUES (?,?)", references)
            rows = db.execute("SELECT m.payload_json FROM materials m JOIN requested_refs r "
                              "ON m.storage_source_id=r.source AND m.object_key=r.key ORDER BY m.created_at, m.id")
            result = {}
            for row in rows:
                value = self._row_payload(row)
                result.setdefault((value['storage_source_id'], value['object_key']), value)
            return result

    def find_by_storage_reference(self, storage_source_id: str, object_key: str) -> dict[str, Any] | None:
        with self._connect() as database:
            row = database.execute(
                "SELECT payload_json FROM materials WHERE storage_source_id = ? AND object_key = ? LIMIT 1",
                (str(storage_source_id), str(object_key)),
            ).fetchone()
        return self._row_payload(row) if row else None

    def mutate(self, fn: Callable[[list[dict[str, Any]]], _Result]) -> _Result:
        """Compatibility transaction for legacy callers without full-table rewrite.

        Legacy callbacks still receive all rows, so they remain unsuitable for million-row hot
        paths. This compatibility layer now diffs the callback result and persists only rows that
        actually changed, were added, or were removed.
        """
        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            try:
                stored = database.execute(
                    "SELECT id, payload_json FROM materials ORDER BY created_at, id"
                ).fetchall()
                before_payload = {str(row["id"]): str(row["payload_json"]) for row in stored}
                rows = [self._row_payload(row) for row in stored]
                result = fn(rows)

                after: dict[str, dict[str, Any]] = {}
                after_payload: dict[str, str] = {}
                for value in rows:
                    normalized = normalize_material(value)
                    image_id = normalized["id"]
                    if image_id in after:
                        raise ValueError(f"素材 id 重复：{image_id}")
                    after[image_id] = normalized
                    after_payload[image_id] = json.dumps(
                        normalized,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )

                deleted_ids = [image_id for image_id in before_payload if image_id not in after]
                changed_ids = [
                    image_id
                    for image_id, payload in after_payload.items()
                    if before_payload.get(image_id) != payload
                ]

                if deleted_ids:
                    placeholders = ",".join("?" for _ in deleted_ids)
                    database.execute(
                        f"DELETE FROM materials WHERE id IN ({placeholders})",
                        deleted_ids,
                    )
                for image_id in changed_ids:
                    self._write_row(database, after[image_id])
                if deleted_ids or changed_ids:
                    self._bump_revision(database)
                database.execute("COMMIT")
            except Exception:
                database.execute("ROLLBACK")
                raise
        return result
