"""Durable central task-to-node assignment truth.

Assignments are control-plane truth, not a second task state machine. An active
assignment fences legacy Workers from self-claiming that queued task. The HTTP
Agent executor will later turn a claimed assignment into the one real task
execution lease without requiring remote SQLite/NFS access.
"""
from __future__ import annotations

import json
import secrets
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .service_nodes import HEARTBEAT_TTL_SECONDS, ServiceNodeRepository
from .task_runtime import TaskKind
from .task_runtime.fenced_repository import FencedTaskRepository
from .task_runtime.models import utc_now
from .task_runtime.repository import _from_row


ASSIGNMENT_STATES = ("ASSIGNED", "CLAIMED", "RELEASED")
ACTIVE_ASSIGNMENT_STATES = ("ASSIGNED", "CLAIMED")
DEFAULT_ASSIGNMENT_LEASE_SECONDS = 30
REMOTE_EXECUTION_CONTRACT_VERSION = 1
SUPPORTED_REMOTE_EXECUTION_TRANSPORTS = (
    "object-storage-v1",
    "agent-artifact-v1",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_node_assignments (
    task_id TEXT NOT NULL,
    generation INTEGER NOT NULL,
    node_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('ASSIGNED','CLAIMED','RELEASED')),
    assigned_at TEXT NOT NULL,
    claimed_at TEXT,
    updated_at TEXT NOT NULL,
    lease_token TEXT,
    lease_expires_at TEXT,
    released_at TEXT,
    release_reason TEXT NOT NULL DEFAULT '',
    resolved_execution_config TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY(task_id,generation)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_task_node_assignment_active
    ON task_node_assignments(task_id)
    WHERE state IN ('ASSIGNED','CLAIMED');
CREATE INDEX IF NOT EXISTS idx_task_node_assignment_node
    ON task_node_assignments(node_id,state,assigned_at,task_id);
"""


class NodeAssignmentError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409):
        self.code = str(code)
        self.status_code = int(status_code)
        super().__init__(str(message))


def ensure_task_node_assignment_schema(database) -> None:
    database.executescript(_SCHEMA)


def _loads(value: object, fallback):
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError):
        return fallback


def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _utc(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _public(row) -> dict[str, Any]:
    return {
        "task_id": str(row["task_id"]),
        "generation": int(row["generation"]),
        "node_id": str(row["node_id"]),
        "capability": str(row["capability"]),
        "state": str(row["state"]),
        "assigned_at": str(row["assigned_at"]),
        "claimed_at": row["claimed_at"],
        "updated_at": str(row["updated_at"]),
        "lease_expires_at": row["lease_expires_at"],
        "released_at": row["released_at"],
        "release_reason": str(row["release_reason"] or ""),
        "resolved_execution_config": _loads(row["resolved_execution_config"], {}),
    }


def task_node_capability(task, artifacts) -> str | None:
    if task.kind is TaskKind.MATERIAL_IMPORT and task.accepted is True:
        # Confirmation hands formal repository projection back to the existing
        # local Storage Worker; never send accepted material tasks to an Agent.
        return None
    fixed = {
        TaskKind.MATERIAL_IMPORT: "material-import",
        TaskKind.CLEANING: "cleaning",
        TaskKind.AI_ANNOTATION: "annotation",
        TaskKind.VIDEO_FRAMES: "video",
        TaskKind.TRAINING: "training",
    }
    if task.kind in fixed:
        return fixed[task.kind]
    if task.kind is TaskKind.DEPLOYMENT_TEST:
        try:
            payload = artifacts.read_json(task.task_id, task.payload_ref, default={})
        except (OSError, TypeError, ValueError):
            payload = {}
        if isinstance(payload, Mapping):
            mode = str(payload.get("execution_mode") or "").strip().lower()
            runtime_format = str(payload.get("runtime_format") or "").strip().lower()
            if mode == "agent" and runtime_format == "rknn":
                return "deployment-test.rknn"
        return "deployment-test"
    if task.kind is TaskKind.MODEL_CONVERSION:
        try:
            payload = artifacts.read_json(task.task_id, task.payload_ref, default={})
        except (OSError, TypeError, ValueError):
            payload = {}
        if isinstance(payload, Mapping):
            mode = str(payload.get("execution_mode") or "local").strip().lower()
            target = str(payload.get("target") or "").strip().lower()
            if not target:
                remote = payload.get("remote_execution")
                conversion = remote.get("conversion") if isinstance(remote, Mapping) else None
                if isinstance(conversion, Mapping):
                    target = str(conversion.get("target") or "").strip().lower()
            if mode == "agent" and target in {"rockchip", "rknn"}:
                return "conversion.rknn"
        return "conversion"
    if task.kind is TaskKind.MATERIAL_BATCH:
        payload = artifacts.read_json(task.task_id, task.payload_ref, default={})
        operation = str(payload.get("operation") or "").strip().upper() if isinstance(payload, Mapping) else ""
        if operation == "CLEAN":
            return "cleaning"
        if operation == "AI_ANNOTATE":
            return "annotation"
        return "material-import"
    # Resource discovery remains local control-plane work for now.
    return None


def task_remote_execution_contract(task, artifacts) -> dict[str, Any] | None:
    """Return sanitized metadata only for an explicitly portable task contract.

    Legacy task payloads contain control-plane absolute paths and must never be
    inferred as remote-safe. A remote Agent becomes eligible only after the task
    producer publishes this versioned contract deliberately.
    """
    try:
        payload = artifacts.read_json(task.task_id, task.payload_ref, default={})
    except (OSError, TypeError, ValueError):
        return None
    if not isinstance(payload, Mapping):
        return None
    raw = payload.get("remote_execution")
    if not isinstance(raw, Mapping):
        return None
    try:
        version = int(raw.get("version") or 0)
    except (TypeError, ValueError):
        return None
    task_kind = str(raw.get("task_kind") or "").strip()
    transport = str(raw.get("transport") or "").strip().lower()
    if (
        version != REMOTE_EXECUTION_CONTRACT_VERSION
        or task_kind != task.kind.value
        or transport not in SUPPORTED_REMOTE_EXECUTION_TRANSPORTS
    ):
        return None
    # Never copy task-provided credentials, URLs, paths or arbitrary nested
    # data into scheduler truth. Transport-specific manifests are validated by
    # the task-kind runner later; scheduling needs only this allow-list metadata.
    return {
        "version": version,
        "task_kind": task_kind,
        "transport": transport,
    }


def task_node_connection_mode(task, artifacts) -> str | None:
    """Return an explicit node connection-mode requirement when product intent demands it."""
    if task.kind not in {
        TaskKind.TRAINING,
        TaskKind.MODEL_CONVERSION,
        TaskKind.MATERIAL_IMPORT,
        TaskKind.MATERIAL_BATCH,
        TaskKind.DEPLOYMENT_TEST,
    }:
        return None
    try:
        payload = artifacts.read_json(task.task_id, task.payload_ref, default={})
    except (OSError, TypeError, ValueError):
        return None
    if not isinstance(payload, Mapping):
        return None
    if task.kind is TaskKind.TRAINING:
        if str(payload.get("target") or "local").strip().lower() == "remote":
            return "agent"
        return None
    if task.kind is TaskKind.MATERIAL_BATCH:
        if str(payload.get("operation") or "").strip().upper() != "CLEAN":
            return None
        mode = str(payload.get("execution_mode") or "local").strip().lower()
        return "agent" if mode == "agent" else "local"
    if task.kind is TaskKind.DEPLOYMENT_TEST:
        mode = str(payload.get("execution_mode") or "").strip().lower()
        return "agent" if mode == "agent" else None
    # Conversion/material import remain local unless the producer explicitly
    # publishes an Agent execution mode. A portable contract alone never changes
    # product intent or silently migrates a local task to a remote node.
    mode = str(payload.get("execution_mode") or "local").strip().lower()
    return "agent" if mode == "agent" else "local"


def _online_nodes(
    database,
    capability: str,
    *,
    now: datetime,
    ttl_seconds: int,
    remote_contract: Mapping[str, Any] | None,
    required_connection_mode: str | None = None,
):
    rows = database.execute(
        "SELECT * FROM service_nodes WHERE enabled=1 AND last_heartbeat_at IS NOT NULL"
    ).fetchall()
    result = []
    for row in rows:
        heartbeat = _utc(row["last_heartbeat_at"])
        if heartbeat is None or (now - heartbeat).total_seconds() > ttl_seconds:
            continue
        allowed = set(_loads(row["allowed_capabilities"], []))
        reported = set(_loads(row["reported_capabilities"], []))
        if capability not in allowed or capability not in reported:
            continue
        connection_mode = str(row["connection_mode"] or "").strip().lower()
        if required_connection_mode and connection_mode != required_connection_mode:
            continue
        if connection_mode == "agent" and remote_contract is None:
            # Fail closed: existing task payloads commonly contain absolute
            # control-plane paths. Never turn those into a fake remote job.
            continue
        result.append(row)
    return result


def _gpu_rank_value(item: Mapping[str, Any]) -> float:
    free = float(item.get("memory_free_bytes") or 0)
    total = float(item.get("memory_total_bytes") or 0)
    utilization = max(0.0, min(100.0, float(item.get("utilization_percent") or 0)))
    # Treat utilization as real contention, not just display telemetry. A GPU
    # with slightly less free VRAM but very low utilization should beat a busy
    # card when both have enough memory.
    utilization_penalty = total * (utilization / 100.0) * 0.35
    return free - utilization_penalty


def _score_node(row, capability: str, active: int) -> tuple[float, str]:
    resources = _loads(row["resource_json"], {})
    memory = resources.get("memory", {}) if isinstance(resources, Mapping) else {}
    disk = resources.get("disk", {}) if isinstance(resources, Mapping) else {}
    cpu = resources.get("cpu", {}) if isinstance(resources, Mapping) else {}
    gpu = resources.get("gpu", {}) if isinstance(resources, Mapping) else {}
    memory_free = float((memory or {}).get("available_bytes") or 0)
    disk_free = float((disk or {}).get("free_bytes") or 0)
    cores = float((cpu or {}).get("logical_cores") or 0)
    gpus = (gpu or {}).get("gpus") if isinstance(gpu, Mapping) else []
    gpus = [item for item in (gpus if isinstance(gpus, list) else []) if isinstance(item, Mapping)]
    best_gpu_score = max((_gpu_rank_value(item) for item in gpus), default=0.0)
    # One active assignment is treated roughly like 10 GiB of GPU headroom.
    # This strongly favors idle nodes, but real free VRAM/utilization can still
    # win when an "idle" node is nearly full or otherwise unsuitable.
    penalty = float(active) * 10.0 * 1024**3 * 1000.0
    score = (
        best_gpu_score * 1000.0 + memory_free * 10.0 + cores * 1e9 - penalty
        if capability == "training"
        else memory_free * 10.0 + disk_free + cores * 1e9 - penalty
    )
    return score, str(row["node_id"])


def _selected_gpu(row) -> dict[str, Any] | None:
    resources = _loads(row["resource_json"], {})
    gpu = resources.get("gpu", {}) if isinstance(resources, Mapping) else {}
    items = (gpu or {}).get("gpus") if isinstance(gpu, Mapping) else []
    items = [item for item in items or [] if isinstance(item, Mapping)]
    if not items:
        return None
    best = max(items, key=_gpu_rank_value)
    return {
        "id": str(best.get("id") or f"cuda:{best.get('index', 0)}"),
        "index": int(best.get("index") or 0),
        "uuid": best.get("uuid"),
        "name": best.get("name"),
        "memory_free_bytes": int(best.get("memory_free_bytes") or 0),
        "memory_total_bytes": int(best.get("memory_total_bytes") or 0),
        "utilization_percent": (
            int(best.get("utilization_percent"))
            if best.get("utilization_percent") is not None
            else None
        ),
    }


class CentralTaskAllocator:
    def __init__(self, repository, artifacts, *, heartbeat_ttl_seconds: int = HEARTBEAT_TTL_SECONDS):
        self.repository = repository
        self.artifacts = artifacts
        self.heartbeat_ttl_seconds = max(10, int(heartbeat_ttl_seconds))
        # Ensure both authoritative tables before any scheduling transaction.
        # Never run executescript() after BEGIN IMMEDIATE: sqlite3 may issue an
        # implicit COMMIT around scripts and would break allocator atomicity.
        ServiceNodeRepository(repository)
        with closing(self.repository._connect()) as database:
            ensure_task_node_assignment_schema(database)

    def list(self, *, active_only: bool = False, node_id: str | None = None) -> list[dict[str, Any]]:
        clauses, values = [], []
        if active_only:
            clauses.append("state IN ('ASSIGNED','CLAIMED')")
        if node_id is not None:
            clauses.append("node_id=?")
            values.append(str(node_id))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with closing(self.repository._connect()) as database:
            rows = database.execute(
                f"SELECT * FROM task_node_assignments{where} ORDER BY assigned_at DESC,task_id DESC,generation DESC",
                values,
            ).fetchall()
        return [_public(row) for row in rows]

    def get_active(self, task_id: str) -> dict[str, Any] | None:
        with closing(self.repository._connect()) as database:
            row = database.execute(
                "SELECT * FROM task_node_assignments WHERE task_id=? AND state IN ('ASSIGNED','CLAIMED') ORDER BY generation DESC LIMIT 1",
                (str(task_id),),
            ).fetchone()
        return _public(row) if row is not None else None

    def assign_next(self) -> dict[str, Any] | None:
        current = datetime.now(timezone.utc)
        now = current.isoformat()
        with closing(self.repository._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            task_rows = database.execute(
                """
                SELECT task.* FROM tasks task
                 WHERE task.status='QUEUED'
                   AND NOT EXISTS (
                       SELECT 1 FROM task_node_assignments assignment
                        WHERE assignment.task_id=task.task_id
                          AND assignment.state IN ('ASSIGNED','CLAIMED')
                   )
                 ORDER BY task.priority ASC,task.queue_rank DESC,task.created_at ASC,task.task_id ASC
                """
            ).fetchall()
            selected = None
            for task_row in task_rows:
                task = _from_row(task_row)
                capability = task_node_capability(task, self.artifacts)
                if capability is None:
                    continue
                remote_contract = task_remote_execution_contract(task, self.artifacts)
                required_connection_mode = task_node_connection_mode(task, self.artifacts)
                nodes = _online_nodes(
                    database,
                    capability,
                    now=current,
                    ttl_seconds=self.heartbeat_ttl_seconds,
                    remote_contract=remote_contract,
                    required_connection_mode=required_connection_mode,
                )
                if not nodes:
                    continue
                if capability == "training":
                    gpu_nodes = []
                    for candidate in nodes:
                        resources = _loads(candidate["resource_json"], {})
                        gpu = resources.get("gpu", {}) if isinstance(resources, Mapping) else {}
                        items = (gpu or {}).get("gpus") if isinstance(gpu, Mapping) else []
                        if any(
                            isinstance(item, Mapping)
                            and int(item.get("memory_total_bytes") or 0) > 0
                            for item in (items if isinstance(items, list) else [])
                        ):
                            gpu_nodes.append(candidate)
                    if gpu_nodes:
                        nodes = gpu_nodes
                ranked = []
                for node in nodes:
                    active = int(database.execute(
                        "SELECT COUNT(*) FROM task_node_assignments WHERE node_id=? AND state IN ('ASSIGNED','CLAIMED')",
                        (str(node["node_id"]),),
                    ).fetchone()[0])
                    score, node_id = _score_node(node, capability, active)
                    ranked.append((score, node_id, node))
                ranked.sort(key=lambda item: (-item[0], item[1]))
                selected = (task, capability, ranked[0][2], remote_contract)
                break
            if selected is None:
                database.commit()
                return None
            task, capability, node, remote_contract = selected
            generation = int(database.execute(
                "SELECT COALESCE(MAX(generation),0)+1 FROM task_node_assignments WHERE task_id=?",
                (task.task_id,),
            ).fetchone()[0])
            gpu = _selected_gpu(node) if capability == "training" else None
            resolved = {
                "protocol": "agent-http-v1",
                "node_id": str(node["node_id"]),
                "capability": capability,
                "selected_device": gpu["id"] if gpu else "cpu",
                "selected_gpu": gpu,
                "node_build_id": str(node["build_id"] or ""),
                "node_runtime": _loads(node["runtime_json"], {}),
                "connection_mode": str(node["connection_mode"] or ""),
                "remote_execution": dict(remote_contract) if remote_contract is not None else None,
                "assigned_at": now,
            }
            database.execute(
                """
                INSERT INTO task_node_assignments
                    (task_id,generation,node_id,capability,state,assigned_at,updated_at,resolved_execution_config)
                VALUES (?,?,?,?, 'ASSIGNED',?,?,?)
                """,
                (task.task_id, generation, str(node["node_id"]), capability, now, now, _dumps(resolved)),
            )
            row = database.execute(
                "SELECT * FROM task_node_assignments WHERE task_id=? AND generation=?",
                (task.task_id, generation),
            ).fetchone()
            database.commit()
        return _public(row)

    def release(self, task_id: str, reason: str = "operator_release") -> dict[str, Any]:
        now = utc_now()
        with closing(self.repository._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT * FROM task_node_assignments WHERE task_id=? AND state IN ('ASSIGNED','CLAIMED') ORDER BY generation DESC LIMIT 1",
                (str(task_id),),
            ).fetchone()
            if row is None:
                database.rollback()
                raise NodeAssignmentError("NODE_ASSIGNMENT_NOT_FOUND", "task has no active node assignment", 404)
            database.execute(
                """
                UPDATE task_node_assignments
                   SET state='RELEASED',updated_at=?,released_at=?,release_reason=?,lease_token=NULL,lease_expires_at=NULL
                 WHERE task_id=? AND generation=? AND state IN ('ASSIGNED','CLAIMED')
                """,
                (now, now, str(reason or "operator_release")[:1000], str(task_id), int(row["generation"])),
            )
            released = database.execute(
                "SELECT * FROM task_node_assignments WHERE task_id=? AND generation=?",
                (str(task_id), int(row["generation"])),
            ).fetchone()
            database.commit()
        return _public(released)

    def claim_for_node(self, node_id: str, *, lease_seconds: int = DEFAULT_ASSIGNMENT_LEASE_SECONDS) -> dict[str, Any] | None:
        """Reserve one assignment for the future HTTP Agent executor.

        TaskRepository is intentionally still QUEUED here. The executor protocol
        will own the one atomic QUEUED->RUNNING transition and task execution
        lease, preserving the existing fencing model.
        """
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        expires = (now_dt + timedelta(seconds=max(5, int(lease_seconds)))).isoformat()
        token = secrets.token_urlsafe(24)
        with closing(self.repository._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            database.execute(
                """
                UPDATE task_node_assignments
                   SET state='ASSIGNED',lease_token=NULL,lease_expires_at=NULL,updated_at=?
                 WHERE node_id=? AND state='CLAIMED' AND lease_expires_at IS NOT NULL AND lease_expires_at<=?
                """,
                (now, str(node_id), now),
            )
            row = database.execute(
                """
                SELECT assignment.* FROM task_node_assignments assignment
                JOIN tasks task ON task.task_id=assignment.task_id
                 WHERE assignment.node_id=? AND assignment.state='ASSIGNED' AND task.status='QUEUED'
                 ORDER BY task.priority ASC,task.queue_rank DESC,task.created_at ASC,task.task_id ASC
                 LIMIT 1
                """,
                (str(node_id),),
            ).fetchone()
            if row is None:
                database.commit()
                return None
            changed = database.execute(
                """
                UPDATE task_node_assignments
                   SET state='CLAIMED',claimed_at=COALESCE(claimed_at,?),updated_at=?,lease_token=?,lease_expires_at=?
                 WHERE task_id=? AND generation=? AND state='ASSIGNED'
                """,
                (now, now, token, expires, str(row["task_id"]), int(row["generation"])),
            ).rowcount
            if changed != 1:
                database.rollback()
                return None
            claimed = database.execute(
                "SELECT * FROM task_node_assignments WHERE task_id=? AND generation=?",
                (str(row["task_id"]), int(row["generation"])),
            ).fetchone()
            database.commit()
        result = _public(claimed)
        result["assignment_lease_token"] = token
        return result


class AssignmentAwareFencedTaskRepository(FencedTaskRepository):
    """Production Worker repository that refuses centrally assigned tasks."""

    def claim_next(self, worker_id, kinds, capabilities, lease_seconds: int = 30, admission=None):
        caller = admission

        def assignment_guard(database, candidate, owner, token, expires_at, now):
            table = database.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_node_assignments'"
            ).fetchone()
            if table is not None:
                row = database.execute(
                    "SELECT node_id FROM task_node_assignments WHERE task_id=? AND state IN ('ASSIGNED','CLAIMED') ORDER BY generation DESC LIMIT 1",
                    (str(candidate["task_id"]),),
                ).fetchone()
                if row is not None:
                    return False, f"CENTRAL_NODE_ASSIGNED: waiting for Agent execution on node {row['node_id']}"
            if caller is None:
                return True, None
            return caller(database, candidate, owner, token, expires_at, now)

        return super().claim_next(
            worker_id,
            kinds,
            capabilities,
            lease_seconds,
            admission=assignment_guard,
        )


def central_scheduler_router(task_repository, task_artifacts):
    from fastapi import APIRouter, Body, HTTPException, Query

    router = APIRouter(prefix="/api/v63/scheduler")

    def allocator() -> CentralTaskAllocator:
        return CentralTaskAllocator(task_repository(), task_artifacts())

    @router.get("/assignments")
    def assignments(active_only: bool = Query(default=True), node_id: str | None = Query(default=None)):
        return {"items": allocator().list(active_only=active_only, node_id=node_id)}

    @router.post("/allocate-next")
    def allocate_next():
        assignment = allocator().assign_next()
        return {"assigned": assignment is not None, "assignment": assignment}

    @router.post("/assignments/{task_id}/release")
    def release_assignment(task_id: str, payload: dict = Body(default={})):
        try:
            assignment = allocator().release(task_id, str(payload.get("reason") or "operator_release"))
        except NodeAssignmentError as error:
            raise HTTPException(status_code=error.status_code, detail={"code": error.code, "message": str(error)}) from error
        return {"ok": True, "assignment": assignment}

    return router


__all__ = [
    "ACTIVE_ASSIGNMENT_STATES",
    "ASSIGNMENT_STATES",
    "AssignmentAwareFencedTaskRepository",
    "CentralTaskAllocator",
    "NodeAssignmentError",
    "REMOTE_EXECUTION_CONTRACT_VERSION",
    "SUPPORTED_REMOTE_EXECUTION_TRANSPORTS",
    "central_scheduler_router",
    "ensure_task_node_assignment_schema",
    "task_node_capability",
    "task_node_connection_mode",
    "task_remote_execution_contract",
]
