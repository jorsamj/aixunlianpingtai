"""Durable central task-to-node assignment truth.

This is deliberately an assignment layer, not a second task state machine. Tasks
remain owned by TaskRepository; an active node assignment fences legacy Workers
from self-claiming that task until the assignment is explicitly released. The
future HTTP Agent executor can claim these assignments without requiring remote
SQLite/NFS access.
"""
from __future__ import annotations

import json
import secrets
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .service_nodes import HEARTBEAT_TTL_SECONDS
from .task_runtime import TaskKind, TaskStatus
from .task_runtime.fenced_repository import FencedTaskRepository
from .task_runtime.repository import _from_row
from .task_runtime.models import utc_now


ASSIGNMENT_STATES = ("ASSIGNED", "CLAIMED", "RELEASED")
ACTIVE_ASSIGNMENT_STATES = ("ASSIGNED", "CLAIMED")
DEFAULT_ASSIGNMENT_LEASE_SECONDS = 30

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


def _public_assignment(row) -> dict[str, Any]:
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
    if task.kind is TaskKind.MATERIAL_IMPORT:
        return "material-import"
    if task.kind is TaskKind.CLEANING:
        return "cleaning"
    if task.kind is TaskKind.AI_ANNOTATION:
        return "annotation"
    if task.kind is TaskKind.VIDEO_FRAMES:
        return "video"
    if task.kind is TaskKind.TRAINING:
        return "training"
    if task.kind is TaskKind.MODEL_CONVERSION:
        return "conversion"
    if task.kind is TaskKind.DEPLOYMENT_TEST:
        return "deployment-test"
    if task.kind is TaskKind.MATERIAL_BATCH:
        payload = artifacts.read_json(task.task_id, task.payload_ref, default={})
        operation = str(payload.get("operation") or "").strip().upper() if isinstance(payload, Mapping) else ""
        if operation == "CLEAN":
            return "cleaning"
        if operation == "AI_ANNOTATE":
            return "annotation"
        return "material-import"
    # RESOURCE_DISCOVERY remains control-plane/local runtime work for now.
    return None


def _online_node_rows(database, capability: str, *, now: datetime, ttl_seconds: int):
    rows = database.execute(
        "SELECT * FROM service_nodes WHERE enabled=1 AND last_heartbeat_at IS NOT NULL"
    ).fetchall()
    eligible = []
    for row in rows:
        heartbeat = _utc(row["last_heartbeat_at"])
        if heartbeat is None or (now - heartbeat).total_seconds() > ttl_seconds:
            continue
        allowed = set(_loads(row["allowed_capabilities"], []))
        reported = set(_loads(row["reported_capabilities"], []))
        if capability not in allowed or capability not in reported:
            continue
        eligible.append(row)
    return eligible


def _node_resource_score(row, capability: str, active_assignments: int) -> tuple[float, str]:
    resources = _loads(row["resource_json"], {})
    memory = resources.get("memory") if isinstance(resources, Mapping) else {}
    disk = resources.get("disk") if isinstance(resources, Mapping) else {}
    cpu = resources.get("cpu") if isinstance(resources, Mapping) else {}
    gpu = resources.get("gpu") if isinstance(resources, Mapping) else {}
    available_memory = float((memory or {}).get("available_bytes") or 0)
    free_disk = float((disk or {}).get("free_bytes") or 0)
    logical_cores = float((cpu or {}).get("logical_cores") or 0)
    gpus = (gpu or {}).get("gpus") if isinstance(gpu, Mapping) else []
    gpus = gpus if isinstance(gpus, list) else []
    gpu_free = max((float(item.get("memory_free_bytes") or 0) for item in gpus if isinstance(item, Mapping)), default=0.0)
    # Prefer fewer active assignments first. Within the same load, training
    # favors free VRAM; CPU/material workloads favor RAM/cores/disk.
    load_penalty = float(active_assignments) * 1e18
    if capability == "training":
        score = gpu_free * 1000.0 + available_memory * 10.0 + logical_cores * 1e9 - load_penalty
    else:
        score = available_memory * 10.0 + free_disk + logical_cores * 1e9 - load_penalty
    return score, str(row["node_id"])


def _selected_gpu(row) -> dict[str, Any] | None:
    resources = _loads(row["resource_json"], {})
    gpu = resources.get("gpu") if isinstance(resources, Mapping) else {}
    items = (gpu or {}).get("gpus") if isinstance(gpu, Mapping) else []
    items = [item for item in items or [] if isinstance(item, Mapping)]
    if not items:
        return None
    best = max(items, key=lambda item: float(item.get("memory_free_bytes") or 0))
    return {
        "id": str(best.get("id") or f"cuda:{best.get('index', 0)}"),
        "index": int(best.get("index") or 0),
        "uuid": best.get("uuid"),
        "name": best.get("name"),
        "memory_free_bytes": int(best.get("memory_free_bytes") or 0),
        "memory_total_bytes": int(best.get("memory_total_bytes") or 0),
    }


class CentralTaskAllocator:
    def __init__(self, repository, artifacts, *, heartbeat_ttl_seconds: int = HEARTBEAT_TTL_SECONDS):
        self.repository = repository
        self.artifacts = artifacts
        self.heartbeat_ttl_seconds = max(10, int(heartbeat_ttl_seconds))
        with closing(self.repository._connect()) as database:
            ensure_task_node_assignment_schema(database)

    def list(self, *, active_only: bool = False, node_id: str | None = None) -> list[dict[str, Any]]:
        clauses = []
        values: list[object] = []
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
        return [_public_assignment(row) for row in rows]

    def get_active(self, task_id: str) -> dict[str, Any] | None:
        with closing(self.repository._connect()) as database:
            row = database.execute(
                """
                SELECT * FROM task_node_assignments
                 WHERE task_id=? AND state IN ('ASSIGNED','CLAIMED')
                 ORDER BY generation DESC LIMIT 1
                """,
                (str(task_id),),
            ).fetchone()
        return _public_assignment(row) if row is not None else None

    def assign_next(self) -> dict[str, Any] | None:
        current = datetime.now(timezone.utc)
        now = current.isoformat()
        with closing(self.repository._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            ensure_task_node_assignment_schema(database)
            tasks = database.execute(
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
            chosen_task = None
            chosen_node = None
            chosen_capability = None
            for task_row in tasks:
                task = _from_row(task_row)
                capability = task_node_capability(task, self.artifacts)
                if capability is None:
                    continue
                node_rows = _online_node_rows(
                    database,
                    capability,
                    now=current,
                    ttl_seconds=self.heartbeat_ttl_seconds,
                )
                if not node_rows:
                    continue
                scored = []
                for node_row in node_rows:
                    active = int(database.execute(
                        "SELECT COUNT(*) FROM task_node_assignments WHERE node_id=? AND state IN ('ASSIGNED','CLAIMED')",
                        (str(node_row["node_id"]),),
                    ).fetchone()[0])
                    score, node_key = _node_resource_score(node_row, capability, active)
                    scored.append((score, node_key, node_row))
                scored.sort(key=lambda item: (-item[0], item[1]))
                chosen_task, chosen_capability, chosen_node = task, capability, scored[0][2]
                break
            if chosen_task is None or chosen_node is None or chosen_capability is None:
                database.commit()
                return None
            generation = int(database.execute(
                "SELECT COALESCE(MAX(generation),0)+1 FROM task_node_assignments WHERE task_id=?",
                (chosen_task.task_id,),
            ).fetchone()[0])
            gpu = _selected_gpu(chosen_node) if chosen_capability == "training" else None
            config = {
                "protocol": "agent-http-v1",
                "node_id": str(chosen_node["node_id"]),
                "capability": chosen_capability,
                "selected_device": gpu["id"] if gpu else "cpu",
                "selected_gpu": gpu,
                "node_build_id": str(chosen_node["build_id"] or ""),
                "node_runtime": _loads(chosen_node["runtime_json"], {}),
                "assigned_at": now,
            }
            database.execute(
                """
                INSERT INTO task_node_assignments
                    (task_id,generation,node_id,capability,state,assigned_at,updated_at,resolved_execution_config)
                VALUES (?,?,?,?, 'ASSIGNED',?,?,?)
                """,
                (
                    chosen_task.task_id,
                    generation,
                    str(chosen_node["node_id"]),
                    chosen_capability,
                    now,
                    now,
                    _dumps(config),
                ),
            )
            row = database.execute(
                "SELECT * FROM task_node_assignments WHERE task_id=? AND generation=?",
                (chosen_task.task_id, generation),
            ).fetchone()
            database.commit()
        return _public_assignment(row)

    def release(self, task_id: str, reason: str = "operator_release") -> dict[str, Any]:
        now = utc_now()
        with closing(self.repository._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                """
                SELECT * FROM task_node_assignments
                 WHERE task_id=? AND state IN ('ASSIGNED','CLAIMED')
                 ORDER BY generation DESC LIMIT 1
                """,
                (str(task_id),),
            ).fetchone()
            if row is None:
                database.rollback()
                raise NodeAssignmentError("NODE_ASSIGNMENT_NOT_FOUND", "task has no active node assignment", 404)
            database.execute(
                """
                UPDATE task_node_assignments
                   SET state='RELEASED',updated_at=?,released_at=?,release_reason=?,
                       lease_token=NULL,lease_expires_at=NULL
                 WHERE task_id=? AND generation=? AND state IN ('ASSIGNED','CLAIMED')
                """,
                (now, now, str(reason or "operator_release")[:1000], str(task_id), int(row["generation"])),
            )
            released = database.execute(
                "SELECT * FROM task_node_assignments WHERE task_id=? AND generation=?",
                (str(task_id), int(row["generation"])),
            ).fetchone()
            database.commit()
        return _public_assignment(released)

    def claim_for_node(self, node_id: str, *, lease_seconds: int = DEFAULT_ASSIGNMENT_LEASE_SECONDS) -> dict[str, Any] | None:
        """Reserve one assigned task for a future HTTP Agent executor.

        This does not transition TaskRepository to RUNNING yet. That transition
        belongs to the executor protocol so task fencing remains single-owner.
        """
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        expires = (now_dt + timedelta(seconds=max(5, int(lease_seconds)))).isoformat()
        token = secrets.token_urlsafe(24)
        with closing(self.repository._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            ensure_task_node_assignment_schema(database)
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
        public = _public_assignment(claimed)
        public["assignment_lease_token"] = token
        return public


class AssignmentAwareFencedTaskRepository(FencedTaskRepository):
    """Legacy Worker repository that refuses centrally assigned tasks."""

    def claim_next(self, worker_id, kinds, capabilities, lease_seconds: int = 30, admission=None):
        caller = admission

        def assignment_guard(database, candidate, owner, token, expires_at, now):
            table = database.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_node_assignments'"
            ).fetchone()
            if table is not None:
                row = database.execute(
                    """
                    SELECT node_id,state FROM task_node_assignments
                     WHERE task_id=? AND state IN ('ASSIGNED','CLAIMED')
                     ORDER BY generation DESC LIMIT 1
                    """,
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
        assigned = allocator().assign_next()
        return {"assigned": assigned is not None, "assignment": assigned}

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
    "central_scheduler_router",
    "ensure_task_node_assignment_schema",
    "task_node_capability",
]
