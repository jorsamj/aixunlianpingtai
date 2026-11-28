"""Read-only U3 PostgreSQL deployment preflight and SQLite rollback readiness.

This module never creates schemas, never writes business data and never switches
the production Picker.  Missing evidence is reported as blocked, not as empty.
"""
from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .u3_shadow import SCHEMA_NAME, SCHEMA_VERSION


def _pg_state(dsn: str) -> dict[str, Any]:
    if not str(dsn or "").strip():
        return {"status": "UNAVAILABLE", "reason": "DSN_MISSING"}
    try:
        import psycopg
    except ImportError:
        return {"status": "UNAVAILABLE", "reason": "DRIVER_MISSING"}
    try:
        with psycopg.connect(dsn, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT to_regclass(%s)", (f"{SCHEMA_NAME}.schema_migration",)
                )
                present = cursor.fetchone()[0] is not None
                if not present:
                    return {"status": "SCHEMA_MISSING", "schema_version": None}
                cursor.execute(
                    f"SELECT max(version) FROM {SCHEMA_NAME}.schema_migration"
                )
                version = int(cursor.fetchone()[0] or 0)
                cursor.execute(
                    "SELECT to_regclass(%s),to_regclass(%s),to_regclass(%s)",
                    (
                        f"{SCHEMA_NAME}.u3_projection_cursor",
                        f"{SCHEMA_NAME}.picker_snapshot_state",
                        f"{SCHEMA_NAME}.u3_projection_baseline",
                    ),
                )
                tables = cursor.fetchone()
                return {
                    "status": "AVAILABLE",
                    "schema_version": version,
                    "supports_u3": version >= SCHEMA_VERSION,
                    "projection_tables": all(table is not None for table in tables),
                }
    except Exception as error:  # noqa: BLE001 - deployment preflight boundary
        return {"status": "UNAVAILABLE", "reason": str(error)[:300]}


def _sqlite_owner_state(project: Path) -> dict[str, Any]:
    materials = project / "materials.sqlite3"
    annotations = project / "annotations.sqlite3"
    if not materials.is_file() or not annotations.is_file():
        return {"status": "INCOMPLETE", "reason": "SQLITE_OWNER_MISSING"}
    try:
        with closing(sqlite3.connect(materials, timeout=5)) as database:
            material_schema = int(database.execute("PRAGMA user_version").fetchone()[0])
            log_table = database.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='owner_change_meta'"
            ).fetchone()
            hwm = {
                str(row[0]): int(row[1])
                for row in database.execute(
                    "SELECT stream,last_sequence FROM owner_change_meta"
                )
            } if log_table else {}
        with closing(sqlite3.connect(annotations, timeout=5)) as database:
            annotation_schema = int(
                database.execute("PRAGMA user_version").fetchone()[0]
            )
        return {
            "status": "AVAILABLE",
            "materials_schema": material_schema,
            "annotations_schema": annotation_schema,
            "change_log": bool(log_table),
            "high_water_marks": hwm,
        }
    except sqlite3.Error as error:
        return {"status": "INCOMPLETE", "reason": str(error)[:300]}


def preflight(data_dir: str | Path, dsn: str) -> dict[str, Any]:
    """Read-only prerequisite assessment; never initializes or writes."""
    root = Path(data_dir)
    projects_root = root / "projects"
    projects = sorted(
        path for path in projects_root.iterdir()
        if path.is_dir() and (path / "materials.sqlite3").is_file()
    ) if projects_root.is_dir() else []
    pg = _pg_state(dsn)
    owners = {
        project.name: _sqlite_owner_state(project) for project in projects
    }
    blockers: list[str] = []
    if pg.get("status") != "AVAILABLE":
        blockers.append(f"PG_{pg.get('status')}")
    elif not pg.get("supports_u3"):
        blockers.append("PG_SCHEMA_VERSION_TOO_OLD")
    elif not pg.get("projection_tables"):
        blockers.append("PG_U3_TABLES_MISSING")
    if not projects:
        blockers.append("NO_PROJECTS")
    for name, state in owners.items():
        if state.get("status") != "AVAILABLE":
            blockers.append(f"OWNER_UNREADABLE:{name}")
    try:
        disk = shutil.disk_usage(root if root.exists() else root.parent)
        disk_state = {
            "total": disk.total, "used": disk.used, "free": disk.free,
        }
    except OSError:
        disk_state = {"status": "UNAVAILABLE"}
        blockers.append("DISK_UNAVAILABLE")
    return {
        "status": "READY" if not blockers else "BLOCKED",
        "blockers": blockers,
        "data_dir": str(root),
        "projects": owners,
        "postgres": pg,
        "disk": disk_state,
        "sync_default_enabled": False,
        "read_switch_enabled": False,
        "writes_performed": False,
    }


def rollback_readiness(data_dir: str | Path, dsn: str) -> dict[str, Any]:
    """Confirm the SQLite owner remains usable while PG stays a projection."""
    state = preflight(data_dir, dsn)
    owners_ok = bool(state["projects"]) and all(
        row.get("status") == "AVAILABLE" for row in state["projects"].values()
    )
    return {
        "sqlite_owner_available": owners_ok,
        "postgres_projection_status": state["postgres"].get("status"),
        "stop_sync_required": True,
        "keep_pg_projection": True,
        "keep_owner_data": True,
        "read_switch_enabled": False,
        "ready": owners_ok and state["postgres"].get("status") == "AVAILABLE",
        "blockers": [] if owners_ok else ["SQLITE_OWNER_UNAVAILABLE"],
    }
