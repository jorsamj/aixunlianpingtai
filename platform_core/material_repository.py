from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Iterable, Mapping, Sequence, TypeVar

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
CREATE INDEX IF NOT EXISTS ix_materials_status ON materials(processing_status, created_at, id);
CREATE INDEX IF NOT EXISTS ix_materials_filename ON materials(filename COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS ix_materials_created ON materials(created_at, id);
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _basename(value: object) -> str:
    raw = str(value or "")
    if not raw or "\x00" in raw:
        return ""
    if "\\" in raw:
        return PureWindowsPath(raw).name
    return Path(raw).name


def normalize_material(value: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(value)
    image_id = str(row.get("id") or "").strip()
    if not image_id:
        raise ValueError("素材 id 不能为空")
    source_id = str(row.get("storage_source_id") or "default_local").strip()
    storage_type = str(row.get("storage_type") or ("local" if source_id == "default_local" else "remote")).strip().lower()
    stored_name = _basename(row.get("stored_name"))
    object_key = str(row.get("object_key") or "").replace("\\", "/").lstrip("/")
    if not object_key and stored_name:
        object_key = f"uploads/{stored_name}"
    if not object_key:
        raise ValueError(f"素材 {image_id} 缺少 object_key")
    if ".." in Path(object_key).parts or PureWindowsPath(object_key).drive:
        raise ValueError(f"素材 {image_id} 的 object_key 非法")
    if not stored_name and storage_type == "local":
        stored_name = Path(object_key).name
    labels = sorted({str(label).strip() for label in row.get("labels") or [] if str(label).strip()})
    row.update({
        "id": image_id,
        "filename": str(row.get("filename") or stored_name or image_id),
        "stored_name": stored_name,
        "storage_source_id": source_id,
        "storage_type": storage_type,
        "object_key": object_key,
        "content_sha256": str(row.get("content_sha256") or "").lower(),
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

    @staticmethod
    def _row_payload(row: sqlite3.Row) -> dict[str, Any]:
        value = json.loads(row["payload_json"])
        if not isinstance(value, dict):
            raise ValueError("material payload is invalid")
        return dict(value)

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

    @staticmethod
    def _filters(
        *, query: str = "", storage_source_ids: Sequence[str] | None = None,
        processing_status: str | None = None, labels: Sequence[str] | None = None,
        annotated: bool | None = None,
    ) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if str(query).strip():
            clauses.append("m.filename LIKE ? COLLATE NOCASE")
            params.append(f"%{str(query).strip()}%")
        sources = list(dict.fromkeys(str(value) for value in storage_source_ids or [] if str(value)))
        if sources:
            clauses.append("m.storage_source_id IN (" + ",".join("?" for _ in sources) + ")")
            params.extend(sources)
        if processing_status:
            clauses.append("m.processing_status = ?")
            params.append(str(processing_status))
        if annotated is not None:
            clauses.append("m.annotated = ?")
            params.append(int(bool(annotated)))
        selected_labels = list(dict.fromkeys(str(value) for value in labels or [] if str(value)))
        if selected_labels:
            clauses.append(
                "EXISTS (SELECT 1 FROM material_labels ml WHERE ml.material_id = m.id AND ml.label_code IN ("
                + ",".join("?" for _ in selected_labels) + "))"
            )
            params.extend(selected_labels)
        return clauses, params

    def count(self, **filters: Any) -> int:
        clauses, params = self._filters(**filters)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as database:
            return int(database.execute("SELECT COUNT(*) FROM materials m" + where, params).fetchone()[0])

    def list_page(
        self, *, cursor: str | None = None, limit: int = 100, query: str = "",
        storage_source_ids: Sequence[str] | None = None, processing_status: str | None = None,
        labels: Sequence[str] | None = None, annotated: bool | None = None,
    ) -> MaterialPage:
        bounded = max(1, min(1000, int(limit)))
        filter_values = dict(query=query, storage_source_ids=storage_source_ids, processing_status=processing_status, labels=labels, annotated=annotated)
        clauses, params = self._filters(**filter_values)
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
            total=self.count(**filter_values),
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

    def mutate(self, fn: Callable[[list[dict[str, Any]]], _Result]) -> _Result:
        """Compatibility transaction for legacy callers; new code must use set-based APIs."""
        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            try:
                rows = [self._row_payload(row) for row in database.execute("SELECT payload_json FROM materials ORDER BY created_at, id").fetchall()]
                result = fn(rows)
                database.execute("DELETE FROM materials")
                for row in rows:
                    self._write_row(database, row)
                self._bump_revision(database)
                database.execute("COMMIT")
            except Exception:
                database.execute("ROLLBACK")
                raise
        return result
