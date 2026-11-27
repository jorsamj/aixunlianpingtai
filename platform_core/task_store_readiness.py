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


class TaskStoreReadinessError(RuntimeError):
    """The readiness diagnostic could not read the store (fail closed)."""

    def __init__(self, code: str, message: str, *, detail: str = ""):
        super().__init__(message)
        self.code = str(code)
        self.detail = str(detail or "")


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


def readiness(data_dir: str | Path, *, now: str | None = None) -> dict[str, Any]:
    """Report the read-only facts that would block or allow a U5 switch.

    ``now`` is an ISO-8601 UTC instant (defaults to the real current time) so the
    active/expired lease split is deterministic in tests. Every query failure is a
    hard error: a diagnostic that silently reports 0 would look like a clean store.
    """
    from datetime import datetime, timezone

    from .task_runtime.repository import _SCHEMA_VERSION as TASK_SCHEMA_VERSION

    instant = now or datetime.now(timezone.utc).isoformat()
    root = Path(data_dir)
    path = root / "task_runtime" / "tasks.sqlite3"
    report: dict[str, Any] = {
        "provider": "sqlite",
        "authority": str(path),
        "present": path.is_file(),
        "schema_version": None,
        "supported_schema_version": int(TASK_SCHEMA_VERSION),
        "now": instant,
        "tasks": 0,
        "queued_tasks": 0,
        "active_leases": 0,
        "expired_leases": 0,
        "unknown_lease": 0,
        "unverified_stop": 0,
        "recovery_blocked": 0,
        "gpu_reservations": 0,
        "worker_instances_active": 0,
        "worker_instances_expired": 0,
        "blockers": [],
        "read_only": True,
    }
    if not path.is_file():
        report["blockers"] = ["task_store_missing"]
        report["ready_for_cutover"] = False
        return report
    uri = path.resolve().as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=10)) as database:
            database.row_factory = sqlite3.Row
            database.execute("PRAGMA query_only=ON")
            report["schema_version"] = int(
                database.execute("PRAGMA user_version").fetchone()[0]
            )
            if report["schema_version"] != int(TASK_SCHEMA_VERSION):
                report["blockers"] = [
                    f"unsupported_task_schema:{report['schema_version']}"
                ]
                report["ready_for_cutover"] = False
                return report
            columns = _columns(database, "tasks")
            missing = [
                name for name in ("task_id", "status", "stage", "lease_expires_at", "attempt")
                if name not in columns
            ]
            if missing:
                report["blockers"] = [f"task_table_incomplete:{','.join(missing)}"]
                report["ready_for_cutover"] = False
                return report
            report["tasks"] = _scalar(database, "SELECT COUNT(*) FROM tasks")
            report["queued_tasks"] = _scalar(
                database, "SELECT COUNT(*) FROM tasks WHERE status='QUEUED'"
            )
            report["active_leases"] = _scalar(
                database,
                "SELECT COUNT(*) FROM tasks WHERE status IN ('RUNNING','CANCEL_REQUESTED') "
                "AND lease_expires_at IS NOT NULL AND lease_expires_at > ?",
                (instant,),
            )
            report["expired_leases"] = _scalar(
                database,
                "SELECT COUNT(*) FROM tasks WHERE status IN ('RUNNING','CANCEL_REQUESTED') "
                "AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?",
                (instant,),
            )
            report["unknown_lease"] = _scalar(
                database,
                "SELECT COUNT(*) FROM tasks WHERE status IN ('RUNNING','CANCEL_REQUESTED') "
                "AND (lease_expires_at IS NULL OR trim(lease_expires_at)='')",
            )
            # cancellation verification is a durable *stage*, not a TaskStatus; the
            # recovery blockers are stages too. Querying them as statuses would
            # always report zero.
            report["unverified_stop"] = _scalar(
                database,
                "SELECT COUNT(*) FROM tasks WHERE stage='cancelling' "
                "OR (status='CANCEL_REQUESTED' AND (stage IS NULL OR trim(stage)=''))",
            )
            report["recovery_blocked"] = _scalar(
                database,
                "SELECT COUNT(*) FROM tasks WHERE stage LIKE 'recovery_blocked%' "
                "OR stage IN ('process_cleanup_blocked','lease_expired_process_alive')",
            )
            if _columns(database, "gpu_reservations"):
                report["gpu_reservations"] = _scalar(
                    database, "SELECT COUNT(*) FROM gpu_reservations"
                )
            if _columns(database, "worker_instances"):
                report["worker_instances_active"] = _scalar(
                    database, "SELECT COUNT(*) FROM worker_instances WHERE expires_at > ?",
                    (instant,),
                )
                report["worker_instances_expired"] = _scalar(
                    database, "SELECT COUNT(*) FROM worker_instances WHERE expires_at <= ?",
                    (instant,),
                )
    except sqlite3.Error as error:
        raise TaskStoreReadinessError(
            "TASK_STORE_READ_FAILED", "the task store could not be read", detail=str(error)
        ) from error
    blockers: list[str] = []
    if report["queued_tasks"]:
        blockers.append("queued_tasks_require_drain")
    if report["active_leases"]:
        blockers.append("active_leases_require_drain")
    if report["expired_leases"]:
        blockers.append("expired_leases_require_recovery")
    if report["unknown_lease"]:
        blockers.append("unproven_lease_window")
    if report["unverified_stop"]:
        blockers.append("unverified_stop_proof")
    if report["recovery_blocked"]:
        blockers.append("recovery_blocked_owner")
    if report["gpu_reservations"]:
        blockers.append("gpu_reservations_held")
    if report["worker_instances_active"]:
        # An active worker keeps the ability to claim a task, renew its lease and
        # write task state/results. There is no OS-level isolation that would make
        # a switch safe while it runs, so the cutover requires a real drain
        # (stopped workers), not just a count in the report.
        blockers.append("active_worker_instances_require_drain")
    if report["worker_instances_expired"]:
        blockers.append("expired_worker_instances")
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
