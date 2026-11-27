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

#: A future trusted stop proof must carry, at minimum: the nodes covered, the
#: worker services/units that were stopped, the observed process identities, the
#: observation time, an expiry, the evidence source and a verifier signature.
#: Nothing in this repository can verify that today, so a caller-supplied mapping
#: is never accepted as proof.
STOP_PROOF_CONTRACT = (
    "nodes",
    "worker_services",
    "process_identities",
    "observed_at",
    "expires_at",
    "source",
    "verifier_signature",
)
STOP_PROOF_MISSING = "MISSING"
STOP_PROOF_UNVERIFIED = "UNVERIFIED"


def stop_proof_status(proof: dict[str, Any] | None) -> str:
    """Classify a stop proof. This build has no trusted verifier.

    The repository only has per-task remote-agent stop evidence
    (``node_agent_settlement.stop_proof_digests`` / ``STOP_VERIFIED`` in
    ``agent_execution``), which proves one task's process stopped - not that every
    Worker service on every node was drained. A mapping supplied by the caller
    (including ``workers_stopped=True``) is therefore unverified, never accepted.
    """
    if not proof:
        return STOP_PROOF_MISSING
    return STOP_PROOF_UNVERIFIED


class TaskStoreReadinessError(RuntimeError):
    """The readiness diagnostic could not read the store (fail closed)."""

    def __init__(self, code: str, message: str, *, detail: str = ""):
        super().__init__(message)
        self.code = str(code)
        self.detail = str(detail or "")


#: Tables the current task schema (user_version 8) always has and whose absence
#: (or structural damage) makes the diagnostic meaningless. ``worker_instances``
#: comes from the base task schema, ``gpu_reservations`` from
#: ``ensure_gpu_runtime_schema`` called by every TaskRepository initialization.
REQUIRED_TABLES = {
    "tasks": ("task_id", "status", "stage", "lease_expires_at", "attempt"),
    "worker_instances": ("instance_key", "owner_token", "worker_id", "heartbeat_at", "expires_at"),
    "gpu_reservations": ("task_id", "gpu_uuid", "worker_id", "lease_token", "expires_at"),
}


def _columns(database, table: str) -> set[str]:
    """Read table columns; any SQLite error propagates (never "no columns")."""
    return {str(row[1]) for row in database.execute(f"PRAGMA table_info({table})")}


def _scalar(database, statement: str, parameters: tuple[Any, ...] = ()) -> int:
    """Run one count; any SQLite error propagates (never a silent 0)."""
    row = database.execute(statement, parameters).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def readiness(
    data_dir: str | Path,
    *,
    now: str | None = None,
    stop_proof: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    proof = dict(stop_proof or {}) if isinstance(stop_proof, dict) else {}
    proof_status = stop_proof_status(proof or None)
    report: dict[str, Any] = {
        "provider": "sqlite",
        "worker_registration": "optional",
        "stop_proof_status": proof_status,
        "stop_proof_contract": list(STOP_PROOF_CONTRACT),
        "external_stop_proof": proof if proof else None,
        "external_stop_proof_valid": False,
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
            structural: list[str] = []
            tables_present: dict[str, bool] = {}
            for table, required_columns in REQUIRED_TABLES.items():
                present = _columns(database, table)
                tables_present[table] = bool(present)
                if not present:
                    structural.append(f"{table}_table_missing")
                    continue
                missing = [name for name in required_columns if name not in present]
                if missing:
                    structural.append(f"{table}_incomplete:{','.join(missing)}")
            report["tables"] = tables_present
            if structural:
                report["blockers"] = structural
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
            report["gpu_reservations"] = _scalar(
                database, "SELECT COUNT(*) FROM gpu_reservations"
            )
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
    # ``claim_next`` only needs a worker_id string: a running worker does not have
    # to be registered, so an empty worker_instances table cannot prove that every
    # worker stopped. A cutover therefore needs an external stop proof (services
    # stopped/drained) in addition to the database evidence.
    # No trusted verifier exists in this build: a cutover is never admissible from
    # a caller-supplied mapping, and a missing proof is blocked separately.
    if proof_status == STOP_PROOF_MISSING:
        blockers.append("external_worker_stop_proof_required")
    else:
        blockers.append("external_worker_stop_proof_unverified")
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
