"""Read-only U5 migration readiness diagnostics for the task store.

This never writes, never claims a lease, never touches a reservation and never
switches a provider: it only reads the existing SQLite task store and reports the
facts a U5 cutover would need. The five questions it answers are the ones the U5
ADR calls blocking evidence: which authority is in place, what schema it is, what
is currently leased/reserved, which stops are unproven and therefore what blocks a
safe switch.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

#: Statuses whose terminal transition requires a trusted stop proof.
UNVERIFIED_STOP_STATUSES = ("CANCEL_REQUESTED", "cancelling_unverified")
#: Statuses that indicate recovery could not prove the old owner is gone.
RECOVERY_BLOCKED_PREFIX = "recovery_blocked"


def _columns(database, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in database.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _scalar(database, statement: str, parameters: tuple[Any, ...] = ()) -> int:
    try:
        row = database.execute(statement, parameters).fetchone()
    except sqlite3.Error:
        return 0
    return int(row[0]) if row and row[0] is not None else 0


def readiness(data_dir: str | Path) -> dict[str, Any]:
    """Report the read-only facts that would block or allow a U5 switch."""
    root = Path(data_dir)
    path = root / "task_runtime" / "tasks.sqlite3"
    report: dict[str, Any] = {
        "provider": "sqlite",
        "authority": str(path),
        "present": path.is_file(),
        "schema_version": None,
        "tasks": 0,
        "active_leases": 0,
        "expired_leases": 0,
        "unverified_stop": 0,
        "recovery_blocked": 0,
        "gpu_reservations": 0,
        "worker_instances": 0,
        "blockers": [],
        "read_only": True,
    }
    if not path.is_file():
        report["blockers"] = ["task_store_missing"]
        report["ready_for_cutover"] = False
        return report
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=10)) as database:
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA query_only=ON")
        report["schema_version"] = int(
            database.execute("PRAGMA user_version").fetchone()[0]
        )
        columns = _columns(database, "tasks")
        if not columns:
            report["blockers"] = ["task_table_missing"]
            report["ready_for_cutover"] = False
            return report
        report["tasks"] = _scalar(database, "SELECT COUNT(*) FROM tasks")
        report["queued_tasks"] = _scalar(
            database, "SELECT COUNT(*) FROM tasks WHERE status='QUEUED'"
        )
        if "lease_expires_at" in columns:
            report["active_leases"] = _scalar(
                database,
                "SELECT COUNT(*) FROM tasks WHERE status IN ('RUNNING','CANCEL_REQUESTED') "
                "AND lease_expires_at IS NOT NULL AND lease_expires_at > ?",
                (os.environ.get("U5_READINESS_NOW", "1970-01-01T00:00:00+00:00"),),
            )
            report["expired_leases"] = _scalar(
                database,
                "SELECT COUNT(*) FROM tasks WHERE status IN ('RUNNING','CANCEL_REQUESTED') "
                "AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?",
                (os.environ.get("U5_READINESS_NOW", "1970-01-01T00:00:00+00:00"),),
            )
        report["unverified_stop"] = _scalar(
            database,
            "SELECT COUNT(*) FROM tasks WHERE status IN (?,?)",
            UNVERIFIED_STOP_STATUSES,
        )
        report["recovery_blocked"] = _scalar(
            database, "SELECT COUNT(*) FROM tasks WHERE status LIKE ?",
            (RECOVERY_BLOCKED_PREFIX + "%",),
        )
        report["gpu_reservations"] = (
            _scalar(database, "SELECT COUNT(*) FROM gpu_reservations")
            if _columns(database, "gpu_reservations") else 0
        )
        report["worker_instances"] = (
            _scalar(database, "SELECT COUNT(*) FROM worker_instances")
            if _columns(database, "worker_instances") else 0
        )
    blockers: list[str] = []
    if report["queued_tasks"]:
        blockers.append("queued_tasks_require_drain")
    if report["active_leases"]:
        blockers.append("active_leases_require_drain")
    if report["expired_leases"]:
        blockers.append("expired_leases_require_recovery")
    if report["unverified_stop"]:
        blockers.append("unverified_stop_proof")
    if report["recovery_blocked"]:
        blockers.append("recovery_blocked_owner")
    if report["gpu_reservations"]:
        blockers.append("gpu_reservations_held")
    report["blockers"] = blockers
    report["ready_for_cutover"] = not blockers
    return report


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - operator entry
    import argparse

    parser = argparse.ArgumentParser(prog="task_store_readiness")
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(readiness(args.data_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
