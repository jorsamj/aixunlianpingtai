"""Node-scoped MaterialCache reporting through the existing Worker heartbeat.

This module never starts a timer, registry, or scheduler. A running Worker reads
one compact cache ``status.json`` and publishes that snapshot while it still
owns its existing ``worker_instances`` lease. Reports are stored per ``node_id``
so multiple Worker processes on one machine do not appear as multiple caches.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .cache import MaterialCacheLocation, resolve_material_cache_location


CACHE_KIND = "remote_material_content"
_RUNTIME_SCHEMA = """
CREATE TABLE IF NOT EXISTS node_cache_runtime (
    node_id TEXT NOT NULL,
    cache_kind TEXT NOT NULL,
    reporter_worker_id TEXT NOT NULL,
    hostname TEXT NOT NULL DEFAULT '',
    cache_scope TEXT NOT NULL,
    cache_root_source TEXT NOT NULL,
    snapshot_generated_at TEXT,
    snapshot_json TEXT,
    reported_at TEXT NOT NULL,
    PRIMARY KEY(node_id, cache_kind)
);
CREATE INDEX IF NOT EXISTS idx_node_cache_runtime_reported
    ON node_cache_runtime(reported_at);
"""
_PUBLIC_SNAPSHOT_KEYS = (
    "schema_version",
    "cache_kind",
    "cache_scope",
    "cache_root_source",
    "generated_at",
    "max_bytes",
    "ttl_seconds",
    "maintenance_interval_seconds",
    "recent_access_grace_seconds",
    "scanned_files",
    "before_bytes",
    "after_bytes",
    "evicted_files",
    "evicted_bytes",
    "ttl_evictions",
    "quota_evictions",
    "skipped_recent",
    "skipped_locked",
    "skipped_protected",
    "eviction_failures",
    "over_budget_bytes",
)


def _iso(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _safe_snapshot(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    if str(value.get("cache_kind") or "") != CACHE_KIND:
        return None
    generated_at = str(value.get("generated_at") or "").strip()
    if not generated_at:
        return None
    return {key: value.get(key) for key in _PUBLIC_SNAPSHOT_KEYS if key in value}


def read_material_cache_snapshot(location: MaterialCacheLocation) -> dict[str, Any] | None:
    """Read the compact maintenance snapshot without scanning cached objects."""
    path = Path(location.root) / "status.json"
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    snapshot = _safe_snapshot(decoded)
    if snapshot is None:
        return None
    # Current runtime configuration wins over a stale status file created before
    # the cache root was moved or reconfigured.
    snapshot["cache_scope"] = location.cache_scope
    snapshot["cache_root_source"] = location.cache_root_source
    return snapshot


def load_node_cache_reports(repository) -> dict[str, dict[str, Any]]:
    """Return existing node reports without mutating a read-only API path."""
    try:
        with closing(repository._connect()) as database:
            rows = database.execute(
                """
                SELECT node_id,reporter_worker_id,hostname,cache_scope,
                       cache_root_source,snapshot_generated_at,snapshot_json,reported_at
                  FROM node_cache_runtime
                 WHERE cache_kind=?
                """,
                (CACHE_KIND,),
            ).fetchall()
    except sqlite3.OperationalError as error:
        if "no such table" in str(error).lower():
            return {}
        raise

    reports: dict[str, dict[str, Any]] = {}
    for row in rows:
        snapshot = None
        if row["snapshot_json"]:
            try:
                snapshot = _safe_snapshot(json.loads(str(row["snapshot_json"])))
            except (TypeError, ValueError):
                snapshot = None
        reports[str(row["node_id"])] = {
            "cache_kind": CACHE_KIND,
            "reporter_worker_id": str(row["reporter_worker_id"] or ""),
            "hostname": str(row["hostname"] or ""),
            "cache_scope": str(row["cache_scope"] or ""),
            "cache_root_source": str(row["cache_root_source"] or ""),
            "snapshot_generated_at": str(row["snapshot_generated_at"] or ""),
            "reported_at": str(row["reported_at"] or ""),
            "snapshot": snapshot,
        }
    return reports


class MaterialCacheRuntimeReporter:
    """Heartbeat observer fenced by the existing Worker instance lease."""

    def __init__(self, repository, worker_instance, data_dir: str | Path) -> None:
        self.repository = repository
        self.worker_instance = worker_instance
        self.location = resolve_material_cache_location(data_dir)

    def report(self, *, now: datetime | None = None) -> None:
        snapshot = read_material_cache_snapshot(self.location)
        safe_snapshot = _safe_snapshot(snapshot)
        reported_at = _iso(now)
        snapshot_generated_at = (
            str(safe_snapshot.get("generated_at") or "").strip()
            if safe_snapshot is not None
            else None
        )
        payload = (
            json.dumps(safe_snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if safe_snapshot is not None
            else None
        )
        with closing(self.repository._connect()) as database:
            database.executescript(_RUNTIME_SCHEMA)
            database.execute("BEGIN IMMEDIATE")
            worker = database.execute(
                """
                SELECT worker_id,node_id,hostname FROM worker_instances
                 WHERE instance_key=? AND owner_token=?
                """,
                (
                    str(self.worker_instance.instance_key),
                    str(self.worker_instance.owner_token),
                ),
            ).fetchone()
            if worker is None:
                database.rollback()
                raise PermissionError("worker instance lease is no longer owned")
            database.execute(
                """
                INSERT INTO node_cache_runtime
                    (node_id,cache_kind,reporter_worker_id,hostname,cache_scope,
                     cache_root_source,snapshot_generated_at,snapshot_json,reported_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(node_id,cache_kind) DO UPDATE SET
                    reporter_worker_id=excluded.reporter_worker_id,
                    hostname=excluded.hostname,
                    cache_scope=excluded.cache_scope,
                    cache_root_source=excluded.cache_root_source,
                    snapshot_generated_at=excluded.snapshot_generated_at,
                    snapshot_json=excluded.snapshot_json,
                    reported_at=excluded.reported_at
                """,
                (
                    str(worker["node_id"]),
                    CACHE_KIND,
                    str(worker["worker_id"]),
                    str(worker["hostname"]),
                    str(self.location.cache_scope),
                    str(self.location.cache_root_source),
                    snapshot_generated_at,
                    payload,
                    reported_at,
                ),
            )
            database.commit()


__all__ = [
    "CACHE_KIND",
    "MaterialCacheRuntimeReporter",
    "load_node_cache_reports",
    "read_material_cache_snapshot",
]
