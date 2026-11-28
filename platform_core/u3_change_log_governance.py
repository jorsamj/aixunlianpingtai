"""Read-only U3 Owner Change Log capacity diagnostics and dry-run.

No deletion, truncation, compaction or trigger changes live here.  A dry-run only
reports a conservative candidate range and every reason that prevents cleanup.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .u3_incremental_sync import STREAMS, _baseline, _cursor
from .u3_shadow import SCHEMA_NAME
from .u3_owner_change_log import high_water_marks

_STREAM_FILES = {
    "materials": "materials.sqlite3",
    "negative_pool": "materials.sqlite3",
    "annotations": "annotations.sqlite3",
}


def _owner_inventory(project_dir: Path, stream: str) -> dict[str, Any]:
    path = project_dir / _STREAM_FILES[stream]
    if not path.is_file():
        return {"available": False, "reason": "OWNER_MISSING"}
    try:
        with closing(sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10
        )) as database:
            database.row_factory = sqlite3.Row
            hwm = high_water_marks(database)
            row = database.execute(
                "SELECT MIN(sequence),MAX(sequence),COUNT(*) FROM owner_change_log "
                "WHERE stream=?", (stream,)
            ).fetchone()
            kinds = {
                str(kind): int(count)
                for kind, count in database.execute(
                    "SELECT event_kind,COUNT(*) FROM owner_change_log "
                    "WHERE stream=? GROUP BY event_kind", (stream,)
                )
            }
        return {
            "available": True,
            "path": str(path),
            "file_bytes": path.stat().st_size,
            "wal_bytes": (path.with_name(path.name + "-wal")).stat().st_size
            if path.with_name(path.name + "-wal").is_file() else 0,
            "high_water_sequence": int(hwm.get(stream, 0)),
            "min_sequence": int(row[0]) if row and row[0] is not None else None,
            "max_sequence": int(row[1]) if row and row[1] is not None else None,
            "row_count": int(row[2]) if row else 0,
            "event_kinds": kinds,
        }
    except sqlite3.Error as error:
        return {"available": False, "reason": str(error), "path": str(path)}


def owner_change_log_inventory(project_dir: str | Path) -> dict[str, Any]:
    """Explicit diagnostic: per-stream counts/ranges/sizes, never a hot-path COUNT."""
    project = Path(project_dir)
    streams = {
        stream: _owner_inventory(project, stream) for stream in STREAMS
    }
    return {
        "project_dir": str(project),
        "streams": streams,
        "available": all(row.get("available") for row in streams.values()),
    }


def change_log_dry_run(
    connection, *, project_dir: str | Path, project_id: str,
) -> dict[str, Any]:
    """Read-only retention dry-run.  It never proposes deletion as safe by default."""
    project = Path(project_dir)
    inventory = owner_change_log_inventory(project)
    reasons: list[str] = []
    candidates: dict[str, dict[str, Any]] = {}
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT status FROM {SCHEMA_NAME}.picker_snapshot_state "
            "WHERE project_id=%s", (project_id,)
        )
        state = cursor.fetchone()
    status = str(state[0]) if state is not None else "MISSING"
    if status != "READY":
        reasons.append(f"PROJECT_NOT_READY:{status}")
    for stream in STREAMS:
        row = inventory["streams"].get(stream) or {}
        if not row.get("available"):
            reasons.append(f"OWNER_UNAVAILABLE:{stream}")
            continue
        baseline = _baseline(connection, project_id, stream)
        cursor_value, _ = _cursor(connection, project_id, stream)
        if baseline is None:
            reasons.append(f"BASELINE_MISSING:{stream}")
            continue
        if cursor_value < int(row.get("high_water_sequence") or 0):
            reasons.append(f"BACKLOG_PENDING:{stream}")
        upper = min(
            int(baseline["high_water_sequence"]),
            int(cursor_value),
            int(row.get("high_water_sequence") or 0),
        )
        candidates[stream] = {
            "from_sequence": 1,
            "to_sequence": max(0, upper),
            "rows": max(0, upper),
            "requires_new_baseline": True,
        }
    return {
        "project_id": project_id,
        "inventory": inventory,
        "status": status,
        "candidates": candidates,
        "blocked_reasons": reasons,
        "safe_to_delete": False,
        "note": "只读 dry-run；历史 READY 身份引用未建模，禁止据此实际清理",
    }
