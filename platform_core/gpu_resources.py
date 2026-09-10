"""Local GPU admission; all reservation decisions run in the task claim transaction.

Memory figures are bytes. Missing telemetry is unknown, never zero/free. No MIG
admission is supported. Resource samples and reservations live in tasks.sqlite3.
"""
from __future__ import annotations

import csv
import io
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .training_devices import normalize_training_device, probe_training_devices


GPU_SCHEMA = """
CREATE TABLE IF NOT EXISTS gpu_inventory (
    uuid TEXT PRIMARY KEY, gpu_index INTEGER NOT NULL, model TEXT NOT NULL,
    total_bytes INTEGER, free_bytes INTEGER, utilization REAL,
    sampled_at TEXT NOT NULL, source TEXT NOT NULL, healthy INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS gpu_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT, uuid TEXT NOT NULL,
    free_bytes INTEGER, utilization REAL, sampled_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gpu_samples ON gpu_samples(uuid, id DESC);
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


def _cuda_index(gpu):
    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if visible is None:
        return gpu["gpu_index"]
    for ordinal, token in enumerate(visible.split(",")):
        token = token.strip()
        if token == str(gpu["gpu_index"]) or (token.startswith("GPU-") and gpu["uuid"].startswith(token)):
            return ordinal
    return None


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
                rows.append(dict(uuid=_text(pynvml.nvmlDeviceGetUUID(handle)), gpu_index=index,
                                 model=_text(pynvml.nvmlDeviceGetName(handle)), total_bytes=int(memory.total),
                                 free_bytes=int(memory.free), utilization=float(utilization),
                                 sampled_at=sampled_at, source="nvml", healthy=not mig))
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
            rows.append(dict(uuid=uuid, gpu_index=int(index), model=model,
                             total_bytes=_number(total, 1024 ** 2), free_bytes=_number(free, 1024 ** 2),
                             utilization=_number(utilization), sampled_at=sampled_at, source="nvidia-smi",
                             healthy=mig.lower() in {"disabled", "[n/a]", "n/a", "[not supported]"}))
        if rows:
            return rows
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError):
        pass
    if python_executable:
        report = probe_training_devices(python_executable, timeout=10)
        for gpu in report.get("gpus") or []:
            rows.append(dict(uuid=gpu.get("uuid") or f"torch-index:{gpu['index']}", gpu_index=gpu["index"],
                             model=gpu.get("name") or "unknown", total_bytes=None, free_bytes=None,
                             utilization=None, sampled_at=sampled_at, source="torch-identity", healthy=False))
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
                    diagnostic.get("code") not in {"memory_pressure", "memory_pressure_oom", "host_memory_pressure"})
    with repository._connect() as database:
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
                 config=None, sampler=None):
        self.repository = repository
        self.artifacts = artifacts
        self.worker_slot = str(worker_slot)
        self.python_executable = python_executable
        self.config = config or GPUConfig.from_env()
        self.sampler = sampler or sample_gpus
        self._last_refresh = 0.0
        self._lock = threading.Lock()

    def refresh(self):
        # Probe outside BEGIN IMMEDIATE: driver/subprocess latency must not hold SQLite's writer lock.
        with self._lock:
            if time.monotonic() - self._last_refresh < 2:
                return
            rows = self.sampler(self.python_executable)
            with self.repository._connect() as database:
                database.execute("BEGIN IMMEDIATE")
                database.execute("UPDATE gpu_inventory SET healthy=0")
                for row in rows:
                    values = (row["uuid"], row["gpu_index"], row["model"], row["total_bytes"],
                              row["free_bytes"], row["utilization"], row["sampled_at"], row["source"], int(row["healthy"]))
                    database.execute("INSERT OR REPLACE INTO gpu_inventory VALUES (?,?,?,?,?,?,?,?,?)", values)
                    database.execute("INSERT INTO gpu_samples(uuid,free_bytes,utilization,sampled_at) VALUES (?,?,?,?)",
                                     (row["uuid"], row["free_bytes"], row["utilization"], row["sampled_at"]))
                    database.execute("DELETE FROM gpu_samples WHERE uuid=? AND id NOT IN "
                                     "(SELECT id FROM gpu_samples WHERE uuid=? ORDER BY id DESC LIMIT 60)",
                                     (row["uuid"], row["uuid"]))
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
        for gpu in database.execute("SELECT * FROM gpu_inventory ORDER BY gpu_index").fetchall():
            cuda_index = _cuda_index(gpu)
            if cuda_index is None or (device != "auto" and device != f"cuda:{cuda_index}"):
                continue
            total, free = gpu["total_bytes"], gpu["free_bytes"]
            if not gpu["healthy"] or gpu["sampled_at"] < cutoff or total is None or free is None or gpu["utilization"] is None:
                reasons.append("GPU_TELEMETRY_UNAVAILABLE: fresh memory/utilization and non-MIG device required")
                continue
            active = database.execute("SELECT * FROM gpu_reservations WHERE gpu_uuid=?", (gpu["uuid"],)).fetchall()
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
            if count:
                samples = database.execute("SELECT utilization FROM gpu_samples WHERE uuid=? AND sampled_at>=? "
                                           "ORDER BY id DESC LIMIT 5", (gpu["uuid"], cutoff)).fetchall()
                low_utilization = (len(samples) >= 2 and all(sample["utilization"] is not None and
                                   sample["utilization"] <= self.config.shared_utilization_limit for sample in samples))
                if not eligible or not low_utilization or not all(row["share_eligible"] and (row["sharing_evidence_at"] or "") >= cutoff for row in active):
                    reasons.append("GPU_SHARING_EVIDENCE_REQUIRED: small memory estimate and recent low GPU/CPU/IO pressure required")
                    continue
            # Lexicographic score always spreads to idle GPUs before considering sharing.
            score = (count == 0, -count, (free - reserved - self.config.safety_bytes) / total,
                     -gpu["utilization"], -gpu["gpu_index"])
            candidates.append((score, gpu, requested, eligible))
        if not candidates:
            return False, reasons[0] if reasons else f"GPU_NOT_AVAILABLE: waiting for {device}"
        _, gpu, requested, eligible = max(candidates, key=lambda item: item[0])
        database.execute("INSERT INTO gpu_reservations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (task["task_id"], gpu["uuid"], _cuda_index(gpu), requested, estimated, worker_id,
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
        with self.repository._connect() as database:
            row = database.execute("SELECT * FROM gpu_reservations WHERE task_id=? AND lease_token=?",
                                   (lease.task.task_id, lease.lease_token)).fetchone()
        if row is None:
            raise EnvironmentError("GPU_RESERVATION_REQUIRED: assignment has no owned reservation")
        return {**dict(row), "requested_device": requested, "assigned_device": f"cuda:{row['gpu_index']}"}

    def summary(self):
        now = datetime.now(timezone.utc).isoformat()
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=self.config.sample_max_age_seconds)).isoformat()
        with self.repository._connect() as database:
            rows = database.execute("SELECT g.*, COUNT(r.task_id) AS active_tasks, "
                                    "COALESCE(SUM(r.reserved_bytes),0) AS reserved_bytes FROM gpu_inventory g "
                                    "LEFT JOIN gpu_reservations r ON r.gpu_uuid=g.uuid AND r.expires_at>? "
                                    "GROUP BY g.uuid ORDER BY g.gpu_index", (now,)).fetchall()
        return {"gpus": [{**dict(row), "metrics_fresh": row["sampled_at"] >= cutoff} for row in rows],
                "policy_default": "auto", "max_concurrent_per_gpu": self.config.max_concurrent,
                "memory_safety_bytes": self.config.safety_bytes, "max_reserved_ratio": self.config.max_reserved_ratio}
