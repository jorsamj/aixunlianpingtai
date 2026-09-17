"""Local GPU admission; all reservation decisions run in the task claim transaction.

Memory figures are bytes. Missing telemetry is unknown, never zero/free. No MIG
admission is supported. Resource samples and reservations live in tasks.sqlite3.
"""
from __future__ import annotations

from contextlib import closing

import csv
import io
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .node_identity import resolve_node_identity
from .training_devices import normalize_training_device, probe_training_devices


_GPU_INVENTORY_CREATE = """
CREATE TABLE IF NOT EXISTS gpu_inventory (
    node_id TEXT NOT NULL,
    gpu_uuid TEXT NOT NULL,
    physical_index INTEGER,
    model TEXT NOT NULL,
    total_bytes INTEGER,
    free_bytes INTEGER,
    utilization REAL,
    sampled_at TEXT NOT NULL,
    telemetry_source TEXT NOT NULL,
    telemetry_available INTEGER NOT NULL DEFAULT 0,
    mig_mode TEXT NOT NULL DEFAULT 'unknown',
    PRIMARY KEY(node_id, gpu_uuid)
)
"""

_GPU_SAMPLES_CREATE = """
CREATE TABLE IF NOT EXISTS gpu_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    gpu_uuid TEXT NOT NULL,
    free_bytes INTEGER,
    utilization REAL,
    sampled_at TEXT NOT NULL
)
"""

_GPU_AUX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_gpu_inventory_node ON gpu_inventory(node_id, physical_index);
CREATE INDEX IF NOT EXISTS idx_gpu_inventory_sampled ON gpu_inventory(sampled_at);
CREATE INDEX IF NOT EXISTS idx_gpu_samples ON gpu_samples(node_id, gpu_uuid, id DESC);
CREATE TABLE IF NOT EXISTS worker_gpu_visibility (
    worker_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    gpu_uuid TEXT NOT NULL,
    logical_cuda_index INTEGER NOT NULL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY(worker_id, node_id, gpu_uuid),
    UNIQUE(worker_id, logical_cuda_index)
);
CREATE INDEX IF NOT EXISTS idx_worker_gpu_visibility_node
    ON worker_gpu_visibility(node_id, gpu_uuid, observed_at);
CREATE TABLE IF NOT EXISTS gpu_reservations (
    task_id TEXT PRIMARY KEY, gpu_uuid TEXT NOT NULL, gpu_index INTEGER NOT NULL,
    reserved_bytes INTEGER NOT NULL, estimated_bytes INTEGER,
    worker_id TEXT NOT NULL, worker_slot TEXT NOT NULL UNIQUE,
    lease_token TEXT NOT NULL, policy TEXT NOT NULL CHECK(policy IN ('auto','exclusive','shared')),
    share_eligible INTEGER NOT NULL DEFAULT 0, sharing_evidence_at TEXT, created_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gpu_reservations ON gpu_reservations(gpu_uuid, expires_at);
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

GPU_SCHEMA = _GPU_INVENTORY_CREATE + ";" + _GPU_SAMPLES_CREATE + ";" + _GPU_AUX_SCHEMA


def ensure_gpu_runtime_schema(database, *, legacy_node_id: str | None = None) -> None:
    """Create or migrate the GPU runtime tables without touching reservations."""

    fallback_node_id = str(legacy_node_id or "").strip() or "legacy-unscoped"
    database.execute("BEGIN IMMEDIATE")
    try:
        inventory_columns = {
            str(row[1]) for row in database.execute("PRAGMA table_info(gpu_inventory)").fetchall()
        }
        sample_columns = {
            str(row[1]) for row in database.execute("PRAGMA table_info(gpu_samples)").fetchall()
        }
        if inventory_columns and "node_id" not in inventory_columns:
            database.execute("ALTER TABLE gpu_inventory RENAME TO gpu_inventory_v1")
        database.execute(_GPU_INVENTORY_CREATE)
        if inventory_columns and "node_id" not in inventory_columns:
            database.execute(
                """
                INSERT INTO gpu_inventory(
                    node_id,gpu_uuid,physical_index,model,total_bytes,free_bytes,
                    utilization,sampled_at,telemetry_source,telemetry_available,mig_mode
                )
                SELECT ?,uuid,gpu_index,model,total_bytes,free_bytes,utilization,
                       sampled_at,source,
                       CASE WHEN total_bytes IS NOT NULL AND free_bytes IS NOT NULL
                                  AND utilization IS NOT NULL THEN 1 ELSE 0 END,
                       'unknown'
                  FROM gpu_inventory_v1
                """,
                (fallback_node_id,),
            )
            database.execute("DROP TABLE gpu_inventory_v1")

        if sample_columns and "node_id" not in sample_columns:
            database.execute("ALTER TABLE gpu_samples RENAME TO gpu_samples_v1")
        database.execute(_GPU_SAMPLES_CREATE)
        if sample_columns and "node_id" not in sample_columns:
            database.execute(
                """
                INSERT INTO gpu_samples(id,node_id,gpu_uuid,free_bytes,utilization,sampled_at)
                SELECT id,?,uuid,free_bytes,utilization,sampled_at FROM gpu_samples_v1
                """,
                (fallback_node_id,),
            )
            database.execute("DROP TABLE gpu_samples_v1")
        database.commit()
    except Exception:
        database.rollback()
        raise
    database.executescript(_GPU_AUX_SCHEMA)


@dataclass(frozen=True)
class GPUConfig:
    max_concurrent: int = 2
    safety_bytes: int = 1024 ** 3
    max_reserved_ratio: float = 0.9
    sample_max_age_seconds: int = 15
    shared_utilization_limit: float = 35.0
    small_job_ratio: float = 0.25

    @classmethod
    def from_env(cls):
        return cls(
            max_concurrent=max(1, int(os.environ.get("TRAINING_GPU_MAX_CONCURRENT", "2"))),
            safety_bytes=max(0, int(os.environ.get("TRAINING_GPU_SAFETY_BYTES", str(1024 ** 3)))),
            max_reserved_ratio=max(0.01, min(1.0, float(os.environ.get("TRAINING_GPU_MAX_RESERVED_RATIO", "0.9")))),
        )


def _number(value, scale=1):
    try:
        return max(0, int(float(value) * scale))
    except (TypeError, ValueError, OverflowError):
        return None


def _text(value):
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def _metrics_are_fresh(sampled_at, now, max_age_seconds):
    try:
        sampled = datetime.fromisoformat(str(sampled_at).replace("Z", "+00:00"))
        if sampled.tzinfo is None:
            sampled = sampled.replace(tzinfo=timezone.utc)
        age = (now - sampled.astimezone(timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        return False
    return 0 <= age <= max(0, int(max_age_seconds))


def _cuda_index(gpu):
    explicit = gpu.get("logical_cuda_index")
    if explicit is not None:
        return int(explicit)
    physical_index = gpu.get("physical_index", gpu.get("gpu_index"))
    gpu_uuid = str(gpu.get("gpu_uuid") or gpu.get("uuid") or "")
    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if visible is None:
        return None if physical_index is None else int(physical_index)
    for ordinal, token in enumerate(visible.split(",")):
        token = token.strip()
        if token == str(physical_index) or (token.startswith("GPU-") and gpu_uuid.startswith(token)):
            return ordinal
    return None


def _normalized_gpu_row(row):
    gpu_uuid = str(row.get("gpu_uuid") or row.get("uuid") or "").strip()
    if not gpu_uuid:
        raise ValueError("GPU sample is missing gpu_uuid")
    source = str(row.get("telemetry_source") or row.get("source") or "unknown")
    total_bytes = _number(row.get("total_bytes"))
    free_bytes = _number(row.get("free_bytes"))
    utilization = row.get("utilization")
    try:
        utilization = None if utilization is None else max(0.0, float(utilization))
    except (TypeError, ValueError, OverflowError):
        utilization = None
    physical_index = row.get("physical_index", row.get("gpu_index"))
    try:
        physical_index = None if physical_index is None else int(physical_index)
    except (TypeError, ValueError, OverflowError):
        physical_index = None
    telemetry_available = bool(
        row.get("telemetry_available")
        if "telemetry_available" in row
        else source in {"nvml", "nvidia-smi"}
    )
    telemetry_available = bool(
        telemetry_available
        and total_bytes is not None
        and total_bytes > 0
        and free_bytes is not None
        and free_bytes <= total_bytes
        and utilization is not None
        and utilization <= 100.0
    )
    mig_mode = str(row.get("mig_mode") or "unknown").lower()
    if mig_mode not in {"enabled", "disabled", "unknown"}:
        mig_mode = "unknown"
    return {
        "gpu_uuid": gpu_uuid,
        "physical_index": physical_index,
        "logical_cuda_index": _cuda_index(row),
        "model": str(row.get("model") or "unknown"),
        "total_bytes": total_bytes if telemetry_available else None,
        "free_bytes": free_bytes if telemetry_available else None,
        "utilization": utilization if telemetry_available else None,
        "sampled_at": str(row.get("sampled_at") or datetime.now(timezone.utc).isoformat()),
        "telemetry_source": source,
        "telemetry_available": telemetry_available,
        "mig_mode": mig_mode,
    }


def sample_gpus(python_executable=None):
    """Prefer NVML, then nvidia-smi CSV; Torch supplies identity only."""
    sampled_at = datetime.now(timezone.utc).isoformat()
    rows = []
    try:
        import pynvml
        pynvml.nvmlInit()
        try:
            for index in range(pynvml.nvmlDeviceGetCount()):
                handle = pynvml.nvmlDeviceGetHandleByIndex(index)
                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                utilization = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
                try:
                    mig = pynvml.nvmlDeviceGetMigMode(handle)[0] != 0
                except pynvml.NVMLError_NotSupported:
                    mig = False
                gpu_uuid = _text(pynvml.nvmlDeviceGetUUID(handle))
                rows.append(dict(gpu_uuid=gpu_uuid, uuid=gpu_uuid, physical_index=index, gpu_index=index,
                                 model=_text(pynvml.nvmlDeviceGetName(handle)), total_bytes=int(memory.total),
                                 free_bytes=int(memory.free), utilization=float(utilization),
                                 sampled_at=sampled_at, telemetry_source="nvml", source="nvml",
                                 telemetry_available=True, mig_mode="enabled" if mig else "disabled"))
        finally:
            pynvml.nvmlShutdown()
        return rows
    except Exception:
        rows = []
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,uuid,name,memory.total,memory.free,utilization.gpu,mig.mode.current",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise RuntimeError("nvidia-smi failed")
        for values in csv.reader(io.StringIO(result.stdout), skipinitialspace=True):
            if len(values) != 7:
                continue
            index, uuid, model, total, free, utilization, mig = (value.strip() for value in values)
            rows.append(dict(gpu_uuid=uuid, uuid=uuid, physical_index=int(index), gpu_index=int(index), model=model,
                             total_bytes=_number(total, 1024 ** 2), free_bytes=_number(free, 1024 ** 2),
                             utilization=_number(utilization), sampled_at=sampled_at,
                             telemetry_source="nvidia-smi", source="nvidia-smi", telemetry_available=True,
                             mig_mode=("enabled" if mig.lower() == "enabled" else
                                       "disabled" if mig.lower() in {"disabled", "[n/a]", "n/a", "[not supported]"}
                                       else "unknown")))
        if rows:
            return rows
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError):
        pass
    if python_executable:
        report = probe_training_devices(python_executable, timeout=10)
        for gpu in report.get("gpus") or []:
            logical_index = int(gpu["index"])
            visible_tokens = [token.strip() for token in os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",")]
            physical_index = logical_index if "CUDA_VISIBLE_DEVICES" not in os.environ else None
            if logical_index < len(visible_tokens) and visible_tokens[logical_index].isdigit():
                physical_index = int(visible_tokens[logical_index])
            gpu_uuid = gpu.get("uuid") or f"torch-logical:{logical_index}"
            rows.append(dict(gpu_uuid=gpu_uuid, uuid=gpu_uuid, physical_index=physical_index,
                             gpu_index=physical_index, logical_cuda_index=logical_index,
                             model=gpu.get("name") or "unknown", total_bytes=None, free_bytes=None,
                             utilization=None, sampled_at=sampled_at, telemetry_source="torch-identity",
                             source="torch-identity", telemetry_available=False, mig_mode="unknown"))
    return rows


def update_reservation_evidence(repository, lease, metrics):
    """Worker telemetry may shrink its own budget only with a fresh full window.

    Never trust client sharing flags to replace measured CPU/IO evidence here.
    Board-wide used memory is a conservative upper bound on this process usage.
    """
    diagnostic = metrics.get("diagnostic") or {}
    stamp = metrics.get("sampled_at")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(str(stamp))).total_seconds()
    except (TypeError, ValueError):
        return
    if not 0 <= age <= 15:
        return
    estimated = _number(metrics.get("estimated_gpu_memory_bytes"))
    latest = metrics.get("latest") or {}
    observed = _number(latest.get("gpu_used_bytes"))
    total = _number(latest.get("gpu_total_bytes"))
    known = (diagnostic.get("window_samples", 0) >= 6 and estimated and observed and total)
    eligible = bool(known and diagnostic.get("cpu_bottleneck") is False and
                    diagnostic.get("io_bottleneck") is False and
                    diagnostic.get("code") not in {"memory_pressure", "memory_pressure_oom"})
    with closing(repository._connect()) as database:
        database.execute("BEGIN IMMEDIATE")
        row = database.execute("SELECT * FROM gpu_reservations WHERE task_id=? AND lease_token=? AND worker_id=?",
                               (lease.task.task_id, lease.lease_token, lease.worker_id)).fetchone()
        if row is not None:
            budget = max(estimated or 0, int((observed or 0) * 1.2))
            eligible = bool(eligible and budget <= total * 0.25)
            # Do not shrink a reservation based on idle/startup samples.
            resolved_budget = min(row["reserved_bytes"], budget) if known and metrics.get("epoch_duration_seconds") else row["reserved_bytes"]
            database.execute("UPDATE gpu_reservations SET estimated_bytes=?,reserved_bytes=?,share_eligible=?,sharing_evidence_at=? "
                             "WHERE task_id=? AND lease_token=? AND worker_id=?",
                             (budget or None, resolved_budget, int(eligible), stamp if eligible else None,
                              lease.task.task_id, lease.lease_token, lease.worker_id))
        database.commit()


class GPUResourceManager:
    def __init__(self, repository, artifacts, *, worker_slot="default", python_executable=None,
                 config=None, sampler=None, node_id=None, worker_id=None):
        self.repository = repository
        self.artifacts = artifacts
        self.worker_slot = str(worker_slot)
        self.python_executable = python_executable
        self.config = config or GPUConfig.from_env()
        self.sampler = sampler or sample_gpus
        self.node_id = str(node_id or "").strip() or resolve_node_identity().node_id
        self.worker_id = str(worker_id or "").strip() or None
        self._last_refresh = 0.0
        self._lock = threading.Lock()

    def refresh(self):
        # Probe outside BEGIN IMMEDIATE: driver/subprocess latency must not hold SQLite's writer lock.
        with self._lock:
            if time.monotonic() - self._last_refresh < 2:
                return
            rows = [_normalized_gpu_row(row) for row in self.sampler(self.python_executable)]
            with closing(self.repository._connect()) as database:
                database.execute("BEGIN IMMEDIATE")
                for row in rows:
                    database.execute(
                        "DELETE FROM gpu_inventory WHERE node_id='legacy-unscoped' AND gpu_uuid=?",
                        (row["gpu_uuid"],),
                    )
                    database.execute(
                        "DELETE FROM gpu_samples WHERE node_id='legacy-unscoped' AND gpu_uuid=?",
                        (row["gpu_uuid"],),
                    )
                    database.execute(
                        """
                        INSERT INTO gpu_inventory(
                            node_id,gpu_uuid,physical_index,model,total_bytes,free_bytes,
                            utilization,sampled_at,telemetry_source,telemetry_available,mig_mode
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(node_id,gpu_uuid) DO UPDATE SET
                            physical_index=excluded.physical_index, model=excluded.model,
                            total_bytes=excluded.total_bytes, free_bytes=excluded.free_bytes,
                            utilization=excluded.utilization, sampled_at=excluded.sampled_at,
                            telemetry_source=excluded.telemetry_source,
                            telemetry_available=excluded.telemetry_available,
                            mig_mode=excluded.mig_mode
                        """,
                        (
                            self.node_id,
                            row["gpu_uuid"],
                            row["physical_index"],
                            row["model"],
                            row["total_bytes"],
                            row["free_bytes"],
                            row["utilization"],
                            row["sampled_at"],
                            row["telemetry_source"],
                            int(row["telemetry_available"]),
                            row["mig_mode"],
                        ),
                    )
                    database.execute(
                        """
                        INSERT INTO gpu_samples(node_id,gpu_uuid,free_bytes,utilization,sampled_at)
                        VALUES (?,?,?,?,?)
                        """,
                        (
                            self.node_id,
                            row["gpu_uuid"],
                            row["free_bytes"],
                            row["utilization"],
                            row["sampled_at"],
                        ),
                    )
                    database.execute(
                        """
                        DELETE FROM gpu_samples
                         WHERE node_id=? AND gpu_uuid=? AND id NOT IN (
                            SELECT id FROM gpu_samples
                             WHERE node_id=? AND gpu_uuid=? ORDER BY id DESC LIMIT 60
                         )
                        """,
                        (self.node_id, row["gpu_uuid"], self.node_id, row["gpu_uuid"]),
                    )
                if self.worker_id:
                    database.execute("DELETE FROM worker_gpu_visibility WHERE worker_id=?", (self.worker_id,))
                    for row in rows:
                        if row["logical_cuda_index"] is None:
                            continue
                        database.execute(
                            """
                            INSERT INTO worker_gpu_visibility(
                                worker_id,node_id,gpu_uuid,logical_cuda_index,observed_at
                            ) VALUES (?,?,?,?,?)
                            """,
                            (
                                self.worker_id,
                                self.node_id,
                                row["gpu_uuid"],
                                row["logical_cuda_index"],
                                row["sampled_at"],
                            ),
                        )
                database.commit()
            self._last_refresh = time.monotonic()

    def _sharing_evidence(self, payload, now):
        evidence = payload.get("gpu_sharing_evidence")
        if not isinstance(evidence, dict):
            return False
        try:
            stamp = datetime.fromisoformat(str(evidence.get("sampled_at")))
            age = (datetime.fromisoformat(now) - stamp).total_seconds()
        except (TypeError, ValueError):
            return False
        return (0 <= age <= self.config.sample_max_age_seconds and
                evidence.get("cpu_bottleneck") is False and evidence.get("io_bottleneck") is False)

    def admit(self, database, task, worker_id, token, expires_at, now):
        """Return (allowed, wait_reason), inserting reservation inside caller's transaction."""
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
        slot = database.execute("SELECT task_id FROM gpu_reservations WHERE worker_slot=?", (self.worker_slot,)).fetchone()
        if slot:
            return False, "GPU_WORKER_SLOT_BUSY: training slot already owns a task"
        estimated = _number(payload.get("estimated_gpu_memory_bytes")) or None
        cutoff = (datetime.fromisoformat(now) - timedelta(seconds=self.config.sample_max_age_seconds)).isoformat()
        candidates = []
        reasons = []
        for gpu_row in database.execute(
            "SELECT * FROM gpu_inventory WHERE node_id=? ORDER BY physical_index",
            (self.node_id,),
        ).fetchall():
            gpu = dict(gpu_row)
            cuda_index = _cuda_index(gpu)
            if cuda_index is None or (device != "auto" and device != f"cuda:{cuda_index}"):
                continue
            total, free = gpu["total_bytes"], gpu["free_bytes"]
            if (not gpu["telemetry_available"] or gpu["mig_mode"] == "enabled" or
                    gpu["sampled_at"] < cutoff or total is None or free is None or
                    gpu["utilization"] is None):
                reasons.append("GPU_TELEMETRY_UNAVAILABLE: fresh memory/utilization and non-MIG device required")
                continue
            active = database.execute(
                "SELECT * FROM gpu_reservations WHERE gpu_uuid=?", (gpu["gpu_uuid"],)
            ).fetchall()
            count = len(active)
            if count >= self.config.max_concurrent or (count and (policy == "exclusive" or any(r["policy"] == "exclusive" for r in active))):
                reasons.append("GPU_CONCURRENCY_LIMIT: GPU is reserved")
                continue
            capacity = min(int(total * self.config.max_reserved_ratio), total - self.config.safety_bytes)
            # Unknown job size takes the entire allowed budget, preventing implicit sharing.
            requested = estimated or capacity
            reserved = sum(row["reserved_bytes"] for row in active)
            if requested <= 0 or reserved + requested > capacity or requested > free - reserved - self.config.safety_bytes:
                reasons.append("GPU_MEMORY_INSUFFICIENT: free memory after reservations and safety reserve is insufficient")
                continue
            eligible = bool(estimated and estimated <= total * self.config.small_job_ratio and self._sharing_evidence(payload, now))
            if count and (policy == "auto" or any(row["policy"] == "auto" for row in active)):
                samples = database.execute(
                    """
                    SELECT utilization FROM gpu_samples
                     WHERE node_id=? AND gpu_uuid=? AND sampled_at>=?
                     ORDER BY id DESC LIMIT 5
                    """,
                    (self.node_id, gpu["gpu_uuid"], cutoff),
                ).fetchall()
                low_utilization = (len(samples) >= 2 and all(sample["utilization"] is not None and
                                   sample["utilization"] <= self.config.shared_utilization_limit for sample in samples))
                if not eligible or not low_utilization or not all(row["share_eligible"] and (row["sharing_evidence_at"] or "") >= cutoff for row in active):
                    reasons.append("GPU_SHARING_EVIDENCE_REQUIRED: small memory estimate and recent low GPU/CPU/IO pressure required")
                    continue
            # Lexicographic score always spreads to idle GPUs before considering sharing.
            score = (count == 0, -count, (free - reserved - self.config.safety_bytes) / total,
                     -gpu["utilization"], -int(gpu["physical_index"] or 0))
            candidates.append((score, gpu, requested, eligible))
        if not candidates:
            return False, reasons[0] if reasons else f"GPU_NOT_AVAILABLE: waiting for {device}"
        _, gpu, requested, eligible = max(candidates, key=lambda item: item[0])
        database.execute("INSERT INTO gpu_reservations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (task["task_id"], gpu["gpu_uuid"], _cuda_index(gpu), requested, estimated, worker_id,
                          self.worker_slot, token, policy, int(eligible),
                          (payload.get("gpu_sharing_evidence") or {}).get("sampled_at") if eligible else None,
                          now, now, expires_at))
        return True, None

    def assignment(self, lease):
        payload = self.artifacts.read_json(lease.task.task_id, lease.task.payload_ref, default={})
        requested = normalize_training_device(payload.get("requested_device", payload.get("device")))
        if requested == "cpu":
            return {"requested_device": "cpu", "assigned_device": "cpu", "lease_token": lease.lease_token,
                    "worker_id": lease.worker_id}
        with closing(self.repository._connect()) as database:
            row = database.execute("SELECT * FROM gpu_reservations WHERE task_id=? AND lease_token=?",
                                   (lease.task.task_id, lease.lease_token)).fetchone()
        if row is None:
            raise EnvironmentError("GPU_RESERVATION_REQUIRED: assignment has no owned reservation")
        return {**dict(row), "requested_device": requested, "assigned_device": f"cuda:{row['gpu_index']}"}

    def summary(self):
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        with closing(self.repository._connect()) as database:
            rows = database.execute("SELECT g.*, COUNT(r.task_id) AS active_tasks, "
                                    "COALESCE(SUM(r.reserved_bytes),0) AS reserved_bytes FROM gpu_inventory g "
                                    "LEFT JOIN gpu_reservations r ON r.gpu_uuid=g.gpu_uuid AND r.expires_at>? "
                                    "WHERE g.node_id=? GROUP BY g.node_id,g.gpu_uuid "
                                    "ORDER BY g.physical_index", (now_text, self.node_id)).fetchall()
        return {"node_id": self.node_id,
                "gpus": [self._public_gpu(dict(row), now, self.config.sample_max_age_seconds) for row in rows],
                "policy_default": "auto", "max_concurrent_per_gpu": self.config.max_concurrent,
                "memory_safety_bytes": self.config.safety_bytes, "max_reserved_ratio": self.config.max_reserved_ratio}

    @staticmethod
    def _public_gpu(row, now, max_age_seconds):
        total = row.get("total_bytes")
        free = row.get("free_bytes")
        telemetry_available = bool(row.get("telemetry_available"))
        return {
            **row,
            "telemetry_available": telemetry_available,
            "metrics_fresh": bool(
                telemetry_available
                and _metrics_are_fresh(row.get("sampled_at"), now, max_age_seconds)
            ),
            "used_bytes": max(0, int(total) - int(free)) if total is not None and free is not None else None,
            "health_status": "unknown",
        }

    def runtime_truth(self, *, now=None):
        return read_gpu_runtime_truth(self.repository, config=self.config, now=now)


def read_gpu_runtime_truth(repository, *, config=None, now=None):
    """Return the durable GPU runtime projection without sampling or scheduling."""

    runtime_config = config or GPUConfig.from_env()
    generated_at = now or datetime.now(timezone.utc)
    if isinstance(generated_at, str):
        generated_at = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    generated_at = generated_at.astimezone(timezone.utc)
    with closing(repository._connect()) as database:
        gpu_rows = database.execute(
            "SELECT * FROM gpu_inventory ORDER BY node_id,physical_index,gpu_uuid"
        ).fetchall()
        visibility_rows = database.execute(
            """
            SELECT worker_id,node_id,gpu_uuid,logical_cuda_index,observed_at
              FROM worker_gpu_visibility
             ORDER BY node_id,worker_id,logical_cuda_index
            """
        ).fetchall()
    from .task_runtime.worker_instances import WorkerInstanceService

    workers = WorkerInstanceService(repository).list_runtime(now=generated_at)
    gpus = [
        GPUResourceManager._public_gpu(
            dict(row), generated_at, runtime_config.sample_max_age_seconds
        )
        for row in gpu_rows
    ]
    node_map = {}
    for worker in workers:
        node = node_map.setdefault(
            worker["node_id"],
            {"node_id": worker["node_id"], "hostnames": set(), "online_worker_count": 0, "gpu_count": 0},
        )
        if worker["hostname"]:
            node["hostnames"].add(worker["hostname"])
        if worker["online"]:
            node["online_worker_count"] += 1
    for gpu in gpus:
        node = node_map.setdefault(
            gpu["node_id"],
            {"node_id": gpu["node_id"], "hostnames": set(), "online_worker_count": 0, "gpu_count": 0},
        )
        node["gpu_count"] += 1
    nodes = [
        {**value, "hostnames": sorted(value["hostnames"])}
        for _, value in sorted(node_map.items())
    ]
    return {
        "generated_at": generated_at.isoformat(),
        "metrics_max_age_seconds": runtime_config.sample_max_age_seconds,
        "nodes": nodes,
        "workers": workers,
        "gpus": gpus,
        "worker_gpu_visibility": [dict(row) for row in visibility_rows],
        "telemetry": {
            "available_gpu_count": sum(1 for gpu in gpus if gpu["telemetry_available"]),
            "fresh_gpu_count": sum(1 for gpu in gpus if gpu["metrics_fresh"]),
        },
    }
