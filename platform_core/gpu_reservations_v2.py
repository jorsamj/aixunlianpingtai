"""Node-scoped GPU reservation truth for Task Runtime Phase 1B.

Phase 1A already made inventory/telemetry and Worker GPU visibility node-aware.
This module upgrades only the reservation/assignment side while preserving the
existing GPUResourceManager sampling and policy behavior.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone

from .gpu_resources import GPUResourceManager, _number
from .training_devices import normalize_training_device


LEGACY_UNSCOPED_NODE = "legacy-unscoped"

_GPU_RESERVATIONS_V2_CREATE = """
CREATE TABLE IF NOT EXISTS gpu_reservations (
    task_id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL,
    gpu_uuid TEXT NOT NULL,
    physical_index INTEGER,
    logical_cuda_index INTEGER NOT NULL,
    gpu_index INTEGER NOT NULL,
    reserved_bytes INTEGER NOT NULL,
    estimated_bytes INTEGER,
    worker_id TEXT NOT NULL,
    worker_slot TEXT NOT NULL,
    lease_token TEXT NOT NULL,
    policy TEXT NOT NULL CHECK(policy IN ('auto','exclusive','shared')),
    share_eligible INTEGER NOT NULL DEFAULT 0,
    sharing_evidence_at TEXT,
    created_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    UNIQUE(node_id, worker_slot)
)
"""

_GPU_RESERVATIONS_V2_AUX = """
CREATE INDEX IF NOT EXISTS idx_gpu_reservations_node_gpu
    ON gpu_reservations(node_id, gpu_uuid, expires_at);
CREATE INDEX IF NOT EXISTS idx_gpu_reservations_worker
    ON gpu_reservations(node_id, worker_id, expires_at);
CREATE TRIGGER IF NOT EXISTS gpu_task_heartbeat AFTER UPDATE OF lease_expires_at ON tasks
WHEN NEW.status IN ('RUNNING','CANCEL_REQUESTED') AND NEW.lease_token IS NOT NULL
BEGIN
    UPDATE gpu_reservations SET expires_at=NEW.lease_expires_at, heartbeat_at=NEW.updated_at
    WHERE task_id=NEW.task_id AND lease_token=NEW.lease_token AND worker_id=NEW.worker_id;
END;
CREATE TRIGGER IF NOT EXISTS gpu_task_release AFTER UPDATE OF status,lease_token ON tasks
BEGIN
    DELETE FROM gpu_reservations WHERE task_id=NEW.task_id AND
        (NEW.status NOT IN ('RUNNING','CANCEL_REQUESTED') OR
         NEW.lease_token IS NULL OR lease_token<>NEW.lease_token);
END;
"""

_REQUIRED_RESERVATION_COLUMNS = {
    "task_id",
    "node_id",
    "gpu_uuid",
    "physical_index",
    "logical_cuda_index",
    "gpu_index",
    "reserved_bytes",
    "estimated_bytes",
    "worker_id",
    "worker_slot",
    "lease_token",
    "policy",
    "share_eligible",
    "sharing_evidence_at",
    "created_at",
    "heartbeat_at",
    "expires_at",
}


def _resolved_legacy_node(database, worker_id: str) -> str:
    rows = database.execute(
        """
        SELECT DISTINCT node_id
          FROM worker_instances
         WHERE worker_id=? AND node_id IS NOT NULL AND TRIM(node_id)<>''
        """,
        (worker_id,),
    ).fetchall()
    node_ids = {
        str(row[0]).strip()
        for row in rows
        if str(row[0] or "").strip() not in {"", LEGACY_UNSCOPED_NODE}
    }
    return next(iter(node_ids)) if len(node_ids) == 1 else LEGACY_UNSCOPED_NODE


def _physical_index_for(database, node_id: str, gpu_uuid: str):
    if node_id == LEGACY_UNSCOPED_NODE:
        return None
    row = database.execute(
        "SELECT physical_index FROM gpu_inventory WHERE node_id=? AND gpu_uuid=?",
        (node_id, gpu_uuid),
    ).fetchone()
    return None if row is None or row[0] is None else int(row[0])


def ensure_node_scoped_gpu_reservations(database) -> None:
    """Migrate the legacy global reservation table without guessing node ownership.

    A legacy row is mapped to a node only when worker_instances proves exactly one
    non-legacy node for its worker_id. Ambiguous rows remain `legacy-unscoped` and
    admission blocks conservatively until those leases expire or are released.
    """

    columns = {
        str(row[1]) for row in database.execute("PRAGMA table_info(gpu_reservations)").fetchall()
    }
    if not columns:
        database.execute("BEGIN IMMEDIATE")
        try:
            database.execute(_GPU_RESERVATIONS_V2_CREATE)
            database.executescript(_GPU_RESERVATIONS_V2_AUX)
            database.commit()
        except Exception:
            database.rollback()
            raise
        return

    table_sql_row = database.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='gpu_reservations'"
    ).fetchone()
    table_sql = "" if table_sql_row is None else str(table_sql_row[0] or "")
    normalized_sql = "".join(table_sql.lower().split())
    node_slot_unique = "unique(node_id,worker_slot)" in normalized_sql
    if _REQUIRED_RESERVATION_COLUMNS <= columns and node_slot_unique:
        database.executescript(_GPU_RESERVATIONS_V2_AUX)
        return

    database.execute("BEGIN IMMEDIATE")
    try:
        legacy_rows = [dict(row) for row in database.execute("SELECT * FROM gpu_reservations").fetchall()]
        database.execute("DROP TRIGGER IF EXISTS gpu_task_heartbeat")
        database.execute("DROP TRIGGER IF EXISTS gpu_task_release")
        database.execute("DROP INDEX IF EXISTS idx_gpu_reservations")
        database.execute("DROP INDEX IF EXISTS idx_gpu_reservations_node_gpu")
        database.execute("DROP INDEX IF EXISTS idx_gpu_reservations_worker")
        database.execute("ALTER TABLE gpu_reservations RENAME TO gpu_reservations_v1")
        database.execute(_GPU_RESERVATIONS_V2_CREATE)

        for row in legacy_rows:
            worker_id = str(row.get("worker_id") or "")
            node_id = str(row.get("node_id") or "").strip()
            if not node_id:
                node_id = _resolved_legacy_node(database, worker_id)
            gpu_uuid = str(row.get("gpu_uuid") or "")
            logical_index = row.get("logical_cuda_index")
            if logical_index is None:
                logical_index = row.get("gpu_index")
            if logical_index is None:
                # A legacy reservation without an execution index cannot be
                # made truthful. Keep the system fail-closed by not inventing one.
                continue
            physical_index = row.get("physical_index")
            if physical_index is None:
                physical_index = _physical_index_for(database, node_id, gpu_uuid)
            database.execute(
                """
                INSERT INTO gpu_reservations(
                    task_id,node_id,gpu_uuid,physical_index,logical_cuda_index,gpu_index,
                    reserved_bytes,estimated_bytes,worker_id,worker_slot,lease_token,policy,
                    share_eligible,sharing_evidence_at,created_at,heartbeat_at,expires_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row["task_id"], node_id, gpu_uuid, physical_index,
                    int(logical_index), int(logical_index), row["reserved_bytes"],
                    row.get("estimated_bytes"), worker_id, row["worker_slot"],
                    row["lease_token"], row["policy"], int(row.get("share_eligible") or 0),
                    row.get("sharing_evidence_at"), row["created_at"],
                    row["heartbeat_at"], row["expires_at"],
                ),
            )
        database.execute("DROP TABLE gpu_reservations_v1")
        database.executescript(_GPU_RESERVATIONS_V2_AUX)
        database.commit()
    except Exception:
        database.rollback()
        raise


class NodeScopedGPUResourceManager(GPUResourceManager):
    """GPUResourceManager with node-scoped reservation and assignment identity."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        with closing(self.repository._connect()) as database:
            ensure_node_scoped_gpu_reservations(database)

    @staticmethod
    def _visibility_row(database, *, worker_id: str, node_id: str, gpu_uuid: str):
        return database.execute(
            """
            SELECT logical_cuda_index,observed_at
              FROM worker_gpu_visibility
             WHERE worker_id=? AND node_id=? AND gpu_uuid=?
            """,
            (worker_id, node_id, gpu_uuid),
        ).fetchone()

    def admit(self, database, task, worker_id, token, expires_at, now):
        """Admit using node-scoped slot/GPU reservations and durable visibility truth."""
        if task["kind"] != "TRAINING" or str(task["resource_key"]).startswith("training:remote:"):
            return True, None
        try:
            payload = self.artifacts.read_json(task["task_id"], task["payload_ref"], default={})
            device = normalize_training_device(payload.get("requested_device", payload.get("device")))
        except (OSError, TypeError, ValueError, AttributeError):
            return False, "GPU_REQUEST_INVALID: training payload or device is invalid"
        if device == "cpu":
            return True, None
        policy = str(payload.get("gpu_policy") or "auto").lower()
        if policy not in {"auto", "exclusive", "shared"}:
            return False, "GPU_POLICY_INVALID: expected auto, exclusive, or shared"

        unresolved = database.execute(
            "SELECT task_id FROM gpu_reservations WHERE node_id=? AND expires_at>? LIMIT 1",
            (LEGACY_UNSCOPED_NODE, now),
        ).fetchone()
        if unresolved is not None:
            return False, "GPU_LEGACY_RESERVATION_UNSCOPED: waiting for pre-upgrade GPU lease to expire"

        slot = database.execute(
            "SELECT task_id FROM gpu_reservations WHERE node_id=? AND worker_slot=? AND expires_at>?",
            (self.node_id, self.worker_slot, now),
        ).fetchone()
        if slot:
            return False, "GPU_WORKER_SLOT_BUSY: training slot already owns a task on this node"

        estimated = _number(payload.get("estimated_gpu_memory_bytes")) or None
        cutoff = (datetime.fromisoformat(now) - timedelta(seconds=self.config.sample_max_age_seconds)).isoformat()
        candidates = []
        reasons = []
        for gpu_row in database.execute(
            "SELECT * FROM gpu_inventory WHERE node_id=? ORDER BY physical_index",
            (self.node_id,),
        ).fetchall():
            gpu = dict(gpu_row)
            visibility = self._visibility_row(
                database,
                worker_id=str(worker_id),
                node_id=self.node_id,
                gpu_uuid=str(gpu["gpu_uuid"]),
            )
            if visibility is None:
                reasons.append("GPU_VISIBILITY_UNAVAILABLE: Worker GPU logical index is not proven")
                continue
            logical_index = int(visibility["logical_cuda_index"])
            if device != "auto" and device != f"cuda:{logical_index}":
                continue
            physical_index = gpu.get("physical_index")
            if physical_index is None:
                reasons.append("GPU_IDENTITY_INCOMPLETE: physical GPU index is unknown")
                continue
            total, free = gpu["total_bytes"], gpu["free_bytes"]
            if (not gpu["telemetry_available"] or gpu["mig_mode"] == "enabled" or
                    gpu["sampled_at"] < cutoff or total is None or free is None or
                    gpu["utilization"] is None):
                reasons.append("GPU_TELEMETRY_UNAVAILABLE: fresh memory/utilization and non-MIG device required")
                continue
            active = database.execute(
                "SELECT * FROM gpu_reservations WHERE node_id=? AND gpu_uuid=? AND expires_at>?",
                (self.node_id, gpu["gpu_uuid"], now),
            ).fetchall()
            count = len(active)
            if count >= self.config.max_concurrent or (
                count and (policy == "exclusive" or any(r["policy"] == "exclusive" for r in active))
            ):
                reasons.append("GPU_CONCURRENCY_LIMIT: GPU is reserved on this node")
                continue
            capacity = min(int(total * self.config.max_reserved_ratio), total - self.config.safety_bytes)
            requested = estimated or capacity
            reserved = sum(row["reserved_bytes"] for row in active)
            if requested <= 0 or reserved + requested > capacity or requested > free - reserved - self.config.safety_bytes:
                reasons.append("GPU_MEMORY_INSUFFICIENT: free memory after reservations and safety reserve is insufficient")
                continue
            eligible = bool(
                estimated
                and estimated <= total * self.config.small_job_ratio
                and self._sharing_evidence(payload, now)
            )
            if count and (policy == "auto" or any(row["policy"] == "auto" for row in active)):
                samples = database.execute(
                    """
                    SELECT utilization FROM gpu_samples
                     WHERE node_id=? AND gpu_uuid=? AND sampled_at>=?
                     ORDER BY id DESC LIMIT 5
                    """,
                    (self.node_id, gpu["gpu_uuid"], cutoff),
                ).fetchall()
                low_utilization = (
                    len(samples) >= 2
                    and all(
                        sample["utilization"] is not None
                        and sample["utilization"] <= self.config.shared_utilization_limit
                        for sample in samples
                    )
                )
                if (
                    not eligible
                    or not low_utilization
                    or not all(
                        row["share_eligible"] and (row["sharing_evidence_at"] or "") >= cutoff
                        for row in active
                    )
                ):
                    reasons.append(
                        "GPU_SHARING_EVIDENCE_REQUIRED: small memory estimate and recent low GPU/CPU/IO pressure required"
                    )
                    continue
            score = (
                count == 0,
                -count,
                (free - reserved - self.config.safety_bytes) / total,
                -gpu["utilization"],
                -int(physical_index),
            )
            candidates.append((score, gpu, physical_index, logical_index, requested, eligible))

        if not candidates:
            return False, reasons[0] if reasons else f"GPU_NOT_AVAILABLE: waiting for {device} on node {self.node_id}"

        _, gpu, physical_index, logical_index, requested, eligible = max(candidates, key=lambda item: item[0])
        database.execute(
            """
            INSERT INTO gpu_reservations(
                task_id,node_id,gpu_uuid,physical_index,logical_cuda_index,gpu_index,
                reserved_bytes,estimated_bytes,worker_id,worker_slot,lease_token,policy,
                share_eligible,sharing_evidence_at,created_at,heartbeat_at,expires_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                task["task_id"], self.node_id, gpu["gpu_uuid"], int(physical_index),
                int(logical_index), int(logical_index), requested, estimated, worker_id,
                self.worker_slot, token, policy, int(eligible),
                (payload.get("gpu_sharing_evidence") or {}).get("sampled_at") if eligible else None,
                now, now, expires_at,
            ),
        )
        return True, None

    def assignment(self, lease):
        payload = self.artifacts.read_json(lease.task.task_id, lease.task.payload_ref, default={})
        requested = normalize_training_device(payload.get("requested_device", payload.get("device")))
        if requested == "cpu":
            return {
                "requested_device": "cpu",
                "assigned_device": "cpu",
                "lease_token": lease.lease_token,
                "worker_id": lease.worker_id,
                "node_id": self.node_id,
            }
        with closing(self.repository._connect()) as database:
            row = database.execute(
                """
                SELECT * FROM gpu_reservations
                 WHERE task_id=? AND lease_token=? AND worker_id=? AND node_id=?
                """,
                (lease.task.task_id, lease.lease_token, lease.worker_id, self.node_id),
            ).fetchone()
            if row is None:
                raise EnvironmentError("GPU_RESERVATION_REQUIRED: assignment has no owned node-scoped reservation")
            visibility = self._visibility_row(
                database,
                worker_id=lease.worker_id,
                node_id=self.node_id,
                gpu_uuid=row["gpu_uuid"],
            )
            if visibility is None or int(visibility["logical_cuda_index"]) != int(row["logical_cuda_index"]):
                raise EnvironmentError("GPU_ASSIGNMENT_FENCED: Worker GPU visibility no longer matches reservation")
            result = dict(row)
        return {
            **result,
            "requested_device": requested,
            "assigned_device": f"cuda:{int(result['logical_cuda_index'])}",
            "physical_index": None if result["physical_index"] is None else int(result["physical_index"]),
            "logical_index": int(result["logical_cuda_index"]),
        }

    def summary(self):
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        with closing(self.repository._connect()) as database:
            rows = database.execute(
                """
                SELECT g.*, COUNT(r.task_id) AS active_tasks,
                       COALESCE(SUM(r.reserved_bytes),0) AS reserved_bytes
                  FROM gpu_inventory g
                  LEFT JOIN gpu_reservations r
                    ON r.node_id=g.node_id AND r.gpu_uuid=g.gpu_uuid AND r.expires_at>?
                 WHERE g.node_id=?
                 GROUP BY g.node_id,g.gpu_uuid
                 ORDER BY g.physical_index
                """,
                (now_text, self.node_id),
            ).fetchall()
        return {
            "node_id": self.node_id,
            "gpus": [self._public_gpu(dict(row), now, self.config.sample_max_age_seconds) for row in rows],
            "policy_default": "auto",
            "max_concurrent_per_gpu": self.config.max_concurrent,
            "memory_safety_bytes": self.config.safety_bytes,
            "max_reserved_ratio": self.config.max_reserved_ratio,
        }
