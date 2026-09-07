from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .errors import redact_storage_error
from .models import StorageType


_SCHEMA = """
CREATE TABLE IF NOT EXISTS storage_sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    secret_ref TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    health_status TEXT NOT NULL DEFAULT 'UNKNOWN',
    health_message TEXT NOT NULL DEFAULT '',
    last_checked_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_storage_sources_default
ON storage_sources(is_default) WHERE is_default = 1;
CREATE INDEX IF NOT EXISTS ix_storage_sources_type_enabled
ON storage_sources(type, enabled);
"""

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_SENSITIVE = re.compile(r"(?i)(secret|password|token|api[_-]?key|access[_-]?key)")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    value = dict(config or {})
    pending: list[tuple[str, Any]] = list(value.items())
    while pending:
        key, item = pending.pop()
        if _SENSITIVE.search(str(key)):
            raise ValueError(f"sensitive storage config key is not allowed: {key}")
        if isinstance(item, Mapping):
            pending.extend((str(child_key), child) for child_key, child in item.items())
    json.dumps(value, ensure_ascii=False)
    return value


@dataclass(frozen=True)
class StorageSource:
    id: str
    name: str
    type: str
    config: dict[str, Any]
    secret_ref: str = ""
    enabled: bool = True
    is_default: bool = False
    health_status: str = "UNKNOWN"
    health_message: str = ""
    last_checked_at: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_public_dict(
        self, *, secret_configured: bool = False, secret_masked: str = ""
    ) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "config": dict(self.config),
            "secret_ref": self.secret_ref,
            "secret_configured": bool(secret_configured),
            "secret_masked": str(secret_masked),
            "enabled": self.enabled,
            "is_default": self.is_default,
            "health_status": self.health_status,
            "health_message": self.health_message,
            "last_checked_at": self.last_checked_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _from_row(row: sqlite3.Row) -> StorageSource:
    return StorageSource(
        id=str(row["id"]),
        name=str(row["name"]),
        type=str(row["type"]),
        config=dict(json.loads(row["config_json"] or "{}")),
        secret_ref=str(row["secret_ref"] or ""),
        enabled=bool(row["enabled"]),
        is_default=bool(row["is_default"]),
        health_status=str(row["health_status"] or "UNKNOWN"),
        health_message=str(row["health_message"] or ""),
        last_checked_at=row["last_checked_at"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


class StorageSourceRepository:
    def __init__(
        self,
        path: str | Path,
        *,
        reference_counter: Callable[[str], int] | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.reference_counter = reference_counter or (lambda _source_id: 0)
        with self._connect() as database:
            database.executescript(_SCHEMA)
            stamp = _now()
            database.execute(
                """
                INSERT OR IGNORE INTO storage_sources
                (id, name, type, config_json, enabled, is_default, created_at, updated_at)
                VALUES ('default_local', '平台本地存储', 'local', '{}', 1, 1, ?, ?)
                """,
                (stamp, stamp),
            )

    def _connect(self) -> sqlite3.Connection:
        database = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("PRAGMA foreign_keys=ON")
        database.execute("PRAGMA busy_timeout=5000")
        return database

    def journal_mode(self) -> str:
        with self._connect() as database:
            return str(database.execute("PRAGMA journal_mode").fetchone()[0]).lower()

    def list(self) -> list[StorageSource]:
        with self._connect() as database:
            rows = database.execute(
                "SELECT * FROM storage_sources ORDER BY is_default DESC, created_at, id"
            ).fetchall()
        return [_from_row(row) for row in rows]

    def get(self, source_id: str) -> StorageSource | None:
        with self._connect() as database:
            row = database.execute(
                "SELECT * FROM storage_sources WHERE id = ?", (str(source_id),)
            ).fetchone()
        return _from_row(row) if row else None

    def default(self) -> StorageSource:
        with self._connect() as database:
            row = database.execute(
                "SELECT * FROM storage_sources WHERE is_default = 1"
            ).fetchone()
        if not row:
            raise RuntimeError("storage source repository has no default source")
        return _from_row(row)

    def create(self, value: Mapping[str, Any]) -> StorageSource:
        source_id = str(value.get("id") or "").strip()
        name = str(value.get("name") or "").strip()
        if not _IDENTIFIER.fullmatch(source_id):
            raise ValueError("storage source id is invalid")
        if not name:
            raise ValueError("storage source name is required")
        source_type = StorageType.parse(value.get("type")).value
        config = _safe_config(value.get("config") if isinstance(value.get("config"), Mapping) else {})
        stamp = _now()
        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            try:
                database.execute(
                    """
                    INSERT INTO storage_sources
                    (id, name, type, config_json, secret_ref, enabled, is_default, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        source_id,
                        name,
                        source_type,
                        json.dumps(config, ensure_ascii=False, sort_keys=True),
                        str(value.get("secret_ref") or ""),
                        int(bool(value.get("enabled", True))),
                        stamp,
                        stamp,
                    ),
                )
                database.execute("COMMIT")
            except Exception:
                database.execute("ROLLBACK")
                raise
        return self.get(source_id)  # type: ignore[return-value]

    def update(self, source_id: str, changes: Mapping[str, Any]) -> StorageSource:
        current = self.get(source_id)
        if current is None:
            raise KeyError(f"storage source does not exist: {source_id}")
        if current.id == "default_local" and changes.get("enabled") is False:
            raise ValueError("default local storage cannot be disabled")
        allowed = {"name", "config", "secret_ref", "enabled"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError("unsupported storage source fields: " + ", ".join(sorted(unknown)))
        updated = replace(
            current,
            name=str(changes.get("name", current.name)).strip(),
            config=_safe_config(changes.get("config", current.config)),
            secret_ref=str(changes.get("secret_ref", current.secret_ref) or ""),
            enabled=bool(changes.get("enabled", current.enabled)),
            updated_at=_now(),
        )
        with self._connect() as database:
            database.execute(
                """
                UPDATE storage_sources
                SET name = ?, config_json = ?, secret_ref = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    updated.name,
                    json.dumps(updated.config, ensure_ascii=False, sort_keys=True),
                    updated.secret_ref,
                    int(updated.enabled),
                    updated.updated_at,
                    updated.id,
                ),
            )
        return self.get(source_id)  # type: ignore[return-value]

    def set_default(self, source_id: str) -> StorageSource:
        source = self.get(source_id)
        if source is None:
            raise KeyError(f"storage source does not exist: {source_id}")
        if not source.enabled:
            raise ValueError("disabled storage source cannot be the default")
        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            try:
                database.execute("UPDATE storage_sources SET is_default = 0 WHERE is_default = 1")
                database.execute(
                    "UPDATE storage_sources SET is_default = 1, updated_at = ? WHERE id = ?",
                    (_now(), source_id),
                )
                database.execute("COMMIT")
            except Exception:
                database.execute("ROLLBACK")
                raise
        return self.get(source_id)  # type: ignore[return-value]

    def record_health(self, source_id: str, *, ok: bool, message: str) -> StorageSource:
        checked = _now()
        safe_message = redact_storage_error(message)
        with self._connect() as database:
            cursor = database.execute(
                """
                UPDATE storage_sources
                SET health_status = ?, health_message = ?, last_checked_at = ?, updated_at = ?
                WHERE id = ?
                """,
                ("AVAILABLE" if ok else "UNAVAILABLE", safe_message, checked, checked, source_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"storage source does not exist: {source_id}")
        return self.get(source_id)  # type: ignore[return-value]

    def delete(self, source_id: str) -> bool:
        if str(source_id) == "default_local":
            raise ValueError("default local storage cannot be deleted")
        source = self.get(source_id)
        if source is None:
            return False
        references = int(self.reference_counter(str(source_id)))
        if references:
            raise ValueError(f"storage source is referenced by {references} materials")
        if source.is_default:
            raise ValueError("default storage source cannot be deleted")
        with self._connect() as database:
            cursor = database.execute(
                "DELETE FROM storage_sources WHERE id = ?", (str(source_id),)
            )
        return cursor.rowcount == 1

