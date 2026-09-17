"""HTTP Agent execution control-plane protocol.

Remote Agents never open the control-plane SQLite database.  The control plane
owns assignment, the one QUEUED->RUNNING transition, execution generation, lease
fencing, progress/log persistence, cancellation truth, and terminal completion.

This module intentionally transports only control metadata + JSON task request
payloads. Large training/material/model bytes require the later object-storage
transport layer; do not replace that layer with SQLite/NFS access from Agents.
"""
from __future__ import annotations

import hmac
import json
import secrets
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any

from .service_nodes import HEARTBEAT_TTL_SECONDS, ServiceNodeError, ServiceNodeRepository
from .task_node_assignments import CentralTaskAllocator
from .task_runtime import TaskLease, TaskStatus
from .task_runtime.fenced_repository import FencedTaskRepository
from .task_runtime.repository import TERMINAL_STATUSES, _from_row


DEFAULT_EXECUTION_LEASE_SECONDS = 30
MAX_REMOTE_LOG_BYTES = 64 * 1024


class AgentExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409):
        self.code = str(code)
        self.status_code = int(status_code)
        super().__init__(str(message))


def _iso_now() -> tuple[datetime, str]:
    current = datetime.now(timezone.utc)
    return current, current.isoformat()


def _agent_worker_id(node_id: str) -> str:
    return f"agent:{node_id}"


def _json(value: object, fallback):
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError):
        return fallback


def _task_public(task) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "project_id": task.project_id,
        "kind": task.kind.value,
        "status": task.status.value,
        "priority": task.priority,
        "resource_key": task.resource_key,
        "required_capabilities": list(task.required_capabilities),
        "payload_ref": task.payload_ref,
        "log_ref": task.log_ref,
        "progress": task.progress,
        "stage": task.stage,
        "current_item": task.current_item,
        "attempt": task.attempt,
        "worker_id": task.worker_id,
        "lease_expires_at": task.lease_expires_at,
    }


class AgentExecutionService:
    def __init__(
        self,
        repository,
        artifacts,
        *,
        heartbeat_ttl_seconds: int = HEARTBEAT_TTL_SECONDS,
        execution_lease_seconds: int = DEFAULT_EXECUTION_LEASE_SECONDS,
    ):
        self.repository = repository
        self.artifacts = artifacts
        self.heartbeat_ttl_seconds = max(10, int(heartbeat_ttl_seconds))
        self.execution_lease_seconds = max(5, int(execution_lease_seconds))
        self.nodes = ServiceNodeRepository(
            repository,
            heartbeat_ttl_seconds=self.heartbeat_ttl_seconds,
        )
        self.allocator = CentralTaskAllocator(
            repository,
            artifacts,
            heartbeat_ttl_seconds=self.heartbeat_ttl_seconds,
        )
        self.fenced = FencedTaskRepository(repository.path)

    def _authenticate_node(
        self,
        node_id: str,
        node_token: str,
        *,
        require_online: bool,
        required_capability: str | None = None,
    ) -> dict[str, Any]:
        self.nodes.authenticate(node_id, node_token)
        node = self.nodes.get_public(node_id)
        if not node["enabled"]:
            raise AgentExecutionError("NODE_DISABLED", "service node is disabled", 409)
        if require_online and not node["reachable"]:
            raise AgentExecutionError("NODE_OFFLINE", "service node heartbeat is stale", 409)
        if required_capability and required_capability not in set(node["effective_capabilities"]):
            raise AgentExecutionError(
                "NODE_CAPABILITY_UNAVAILABLE",
                f"service node cannot execute capability {required_capability}",
                409,
            )
        return node

    def claim_assignment(self, node_id: str, node_token: str) -> dict[str, Any] | None:
        node = self._authenticate_node(node_id, node_token, require_online=True)
        claimed = self.allocator.claim_for_node(node_id)
        if claimed is None:
            return None
        capability = str(claimed["capability"])
        if capability not in set(node["effective_capabilities"]):
            # Desired/reported capability changed between assignment and claim.
            self.allocator.release(claimed["task_id"], "node_capability_changed_before_claim")
            raise AgentExecutionError(
                "NODE_CAPABILITY_UNAVAILABLE",
                f"service node cannot execute capability {capability}",
                409,
            )
        task = self.repository.get(claimed["task_id"])
        if task is None:
            self.allocator.release(claimed["task_id"], "task_missing_before_execution")
            raise AgentExecutionError("TASK_NOT_FOUND", "assigned task no longer exists", 404)
        return {
            "assignment": claimed,
            "task": _task_public(task),
        }

    def start_execution(
        self,
        node_id: str,
        node_token: str,
        task_id: str,
        assignment_lease_token: str,
    ) -> dict[str, Any]:
        self.nodes.authenticate(node_id, node_token)
        current, now = _iso_now()
        execution_expires = (
            current + timedelta(seconds=self.execution_lease_seconds)
        ).isoformat()
        execution_token = secrets.token_urlsafe(32)
        worker_id = _agent_worker_id(node_id)

        with closing(self.repository._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            assignment = database.execute(
                """
                SELECT * FROM task_node_assignments
                 WHERE task_id=? AND node_id=? AND state='CLAIMED'
                 ORDER BY generation DESC LIMIT 1
                """,
                (str(task_id), str(node_id)),
            ).fetchone()
            if assignment is None:
                database.rollback()
                raise AgentExecutionError(
                    "ASSIGNMENT_NOT_CLAIMED",
                    "task has no claimed assignment for this node",
                    409,
                )
            stored_assignment_token = str(assignment["lease_token"] or "")
            supplied_assignment_token = str(assignment_lease_token or "")
            if (
                not stored_assignment_token
                or not supplied_assignment_token
                or not hmac.compare_digest(stored_assignment_token, supplied_assignment_token)
            ):
                database.rollback()
                raise AgentExecutionError(
                    "INVALID_ASSIGNMENT_LEASE",
                    "assignment lease token is invalid",
                    401,
                )
            if (
                not assignment["lease_expires_at"]
                or str(assignment["lease_expires_at"]) <= now
            ):
                database.rollback()
                raise AgentExecutionError(
                    "ASSIGNMENT_LEASE_EXPIRED",
                    "assignment lease expired before execution start",
                    409,
                )

            node = database.execute(
                "SELECT enabled,last_heartbeat_at,allowed_capabilities,reported_capabilities FROM service_nodes WHERE node_id=?",
                (str(node_id),),
            ).fetchone()
            if node is None or not bool(node["enabled"]):
                database.rollback()
                raise AgentExecutionError("NODE_DISABLED", "service node is disabled", 409)
            try:
                heartbeat = datetime.fromisoformat(
                    str(node["last_heartbeat_at"] or "").replace("Z", "+00:00")
                )
                if heartbeat.tzinfo is None:
                    heartbeat = heartbeat.replace(tzinfo=timezone.utc)
                heartbeat = heartbeat.astimezone(timezone.utc)
            except ValueError:
                heartbeat = None
            if heartbeat is None or (current - heartbeat).total_seconds() > self.heartbeat_ttl_seconds:
                database.rollback()
                raise AgentExecutionError("NODE_OFFLINE", "service node heartbeat is stale", 409)
            allowed = set(_json(node["allowed_capabilities"], []))
            reported = set(_json(node["reported_capabilities"], []))
            capability = str(assignment["capability"])
            if capability not in allowed or capability not in reported:
                database.rollback()
                raise AgentExecutionError(
                    "NODE_CAPABILITY_UNAVAILABLE",
                    f"service node cannot execute capability {capability}",
                    409,
                )

            task_row = database.execute(
                "SELECT * FROM tasks WHERE task_id=?",
                (str(task_id),),
            ).fetchone()
            if task_row is None:
                database.rollback()
                raise AgentExecutionError("TASK_NOT_FOUND", "assigned task no longer exists", 404)
            if str(task_row["status"]) != TaskStatus.QUEUED.value:
                database.rollback()
                raise AgentExecutionError(
                    "TASK_NOT_QUEUED",
                    "assigned task is no longer queued",
                    409,
                )

            changed = database.execute(
                """
                UPDATE tasks
                   SET status='RUNNING',
                       stage=CASE
                           WHEN kind='MATERIAL_IMPORT' AND accepted=1 AND stage='indexing_queued'
                               THEN 'indexing'
                           ELSE 'running'
                       END,
                       worker_id=?,lease_token=?,lease_expires_at=?,
                       attempt=attempt+1,updated_at=?,finished_at=NULL,
                       resource_wait_reason=NULL,
                       process_pid=NULL,process_create_time=NULL,process_command_hash=NULL
                 WHERE task_id=? AND status='QUEUED'
                """,
                (worker_id, execution_token, execution_expires, now, str(task_id)),
            ).rowcount
            if changed != 1:
                database.rollback()
                raise AgentExecutionError(
                    "EXECUTION_START_RACE",
                    "task execution ownership changed before start",
                    409,
                )

            released = database.execute(
                """
                UPDATE task_node_assignments
                   SET state='RELEASED',updated_at=?,released_at=?,
                       release_reason='execution_started',
                       lease_token=NULL,lease_expires_at=NULL
                 WHERE task_id=? AND generation=? AND node_id=? AND state='CLAIMED'
                       AND lease_token=?
                """,
                (
                    now,
                    now,
                    str(task_id),
                    int(assignment["generation"]),
                    str(node_id),
                    stored_assignment_token,
                ),
            ).rowcount
            if released != 1:
                database.rollback()
                raise AgentExecutionError(
                    "ASSIGNMENT_RELEASE_RACE",
                    "assignment ownership changed before execution start",
                    409,
                )

            started_row = database.execute(
                "SELECT * FROM tasks WHERE task_id=?",
                (str(task_id),),
            ).fetchone()
            database.commit()

        task = _from_row(started_row)
        payload = self.artifacts.read_json(task.task_id, task.payload_ref, default={})
        return {
            "task": _task_public(task),
            "execution": {
                "lease_token": execution_token,
                "generation": int(task.attempt),
                "lease_expires_at": execution_expires,
                "worker_id": worker_id,
            },
            "assignment": {
                "generation": int(assignment["generation"]),
                "capability": str(assignment["capability"]),
                "resolved_execution_config": _json(
                    assignment["resolved_execution_config"], {}
                ),
            },
            "payload": payload,
            "transport": {
                "protocol": "agent-http-control-v1",
                "large_artifacts": "object-storage-required",
                "shared_sqlite_required": False,
                "shared_nfs_required": False,
            },
        }

    def _owned_execution(
        self,
        node_id: str,
        node_token: str,
        task_id: str,
        execution_lease_token: str,
        execution_generation: int,
    ):
        self._authenticate_node(node_id, node_token, require_online=False)
        try:
            task = self.fenced.assert_execution(
                task_id,
                execution_lease_token,
                int(execution_generation),
            )
        except (KeyError, PermissionError) as error:
            raise AgentExecutionError(
                "EXECUTION_FENCED",
                "remote execution lease is no longer current",
                409,
            ) from error
        if str(task.worker_id or "") != _agent_worker_id(node_id):
            raise AgentExecutionError(
                "EXECUTION_NODE_MISMATCH",
                "execution belongs to a different service node",
                403,
            )
        return task

    def heartbeat_execution(
        self,
        node_id: str,
        node_token: str,
        task_id: str,
        execution_lease_token: str,
        execution_generation: int,
        *,
        progress=None,
        stage=None,
        current_item=None,
    ) -> dict[str, Any]:
        self._owned_execution(
            node_id,
            node_token,
            task_id,
            execution_lease_token,
            execution_generation,
        )
        try:
            task = self.fenced.heartbeat(
                task_id,
                execution_lease_token,
                progress=progress,
                stage=stage,
                current_item=current_item,
                execution_generation=int(execution_generation),
                lease_seconds=self.execution_lease_seconds,
            )
        except PermissionError as error:
            raise AgentExecutionError(
                "EXECUTION_FENCED",
                "remote execution heartbeat lost ownership",
                409,
            ) from error
        return {
            "task": _task_public(task),
            "cancel_requested": task.status is TaskStatus.CANCEL_REQUESTED,
        }

    def append_log(
        self,
        node_id: str,
        node_token: str,
        task_id: str,
        execution_lease_token: str,
        execution_generation: int,
        text: str,
    ) -> dict[str, Any]:
        task = self._owned_execution(
            node_id,
            node_token,
            task_id,
            execution_lease_token,
            execution_generation,
        )
        value = str(text or "")
        if len(value.encode("utf-8")) > MAX_REMOTE_LOG_BYTES:
            raise AgentExecutionError(
                "REMOTE_LOG_TOO_LARGE",
                f"one remote log append exceeds {MAX_REMOTE_LOG_BYTES} bytes",
                413,
            )
        self.artifacts.append_log(task.task_id, task.log_ref, value)
        return {"ok": True, "bytes": len(value.encode("utf-8"))}

    def begin_finalization(
        self,
        node_id: str,
        node_token: str,
        task_id: str,
        execution_lease_token: str,
        execution_generation: int,
    ) -> dict[str, Any]:
        self._owned_execution(
            node_id,
            node_token,
            task_id,
            execution_lease_token,
            execution_generation,
        )
        try:
            task = self.fenced.begin_finalization(
                task_id,
                execution_lease_token,
                execution_generation=int(execution_generation),
            )
        except InterruptedError as error:
            raise AgentExecutionError(
                "CANCELLATION_WON",
                "task cancellation won before finalization",
                409,
            ) from error
        except PermissionError as error:
            raise AgentExecutionError(
                "EXECUTION_FENCED",
                "remote execution lost ownership before finalization",
                409,
            ) from error
        return {"task": _task_public(task)}

    def finish_execution(
        self,
        node_id: str,
        node_token: str,
        task_id: str,
        execution_lease_token: str,
        execution_generation: int,
        *,
        status: str,
        result_ref: str | None = None,
        error: str | None = None,
        accepted: bool | None = None,
    ) -> dict[str, Any]:
        current = self._owned_execution(
            node_id,
            node_token,
            task_id,
            execution_lease_token,
            execution_generation,
        )
        try:
            target = TaskStatus(str(status))
        except ValueError as exc:
            raise AgentExecutionError("INVALID_FINISH_STATUS", "invalid task finish status", 422) from exc
        if target not in TERMINAL_STATUSES | {TaskStatus.AWAITING_CONFIRMATION}:
            raise AgentExecutionError("INVALID_FINISH_STATUS", "invalid task finish status", 422)
        if current.status is TaskStatus.CANCEL_REQUESTED and target is not TaskStatus.CANCELLED:
            raise AgentExecutionError(
                "CANCELLATION_WON",
                "cancel-requested execution may only finish as CANCELLED",
                409,
            )
        try:
            task = self.fenced.finish(
                task_id,
                execution_lease_token,
                target,
                result_ref=result_ref,
                error=error,
                accepted=accepted,
                execution_generation=int(execution_generation),
            )
        except PermissionError as exc:
            raise AgentExecutionError(
                "EXECUTION_FENCED",
                "remote execution finish lost ownership",
                409,
            ) from exc
        return {"task": _task_public(task)}


def _bearer_token(value: object) -> str:
    raw = str(value or "").strip()
    if not raw.lower().startswith("bearer ") or not raw[7:].strip():
        raise ServiceNodeError(
            "NODE_TOKEN_REQUIRED",
            "Bearer service node token is required",
            401,
        )
    return raw[7:].strip()


def agent_executor_router(task_repository, task_artifacts):
    from fastapi import APIRouter, Body, Header, HTTPException

    router = APIRouter(prefix="/api/v63/node-executor/{node_id}")

    def service() -> AgentExecutionService:
        return AgentExecutionService(task_repository(), task_artifacts())

    def token(authorization: str | None) -> str:
        try:
            return _bearer_token(authorization)
        except ServiceNodeError as error:
            raise HTTPException(
                status_code=error.status_code,
                detail={"code": error.code, "message": str(error)},
            ) from error

    def invoke(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (ServiceNodeError, AgentExecutionError) as error:
            raise HTTPException(
                status_code=error.status_code,
                detail={"code": error.code, "message": str(error)},
            ) from error

    @router.post("/assignments/claim")
    def claim_assignment(
        node_id: str,
        authorization: str | None = Header(default=None),
    ):
        claimed = invoke(service().claim_assignment, node_id, token(authorization))
        return {"claimed": claimed is not None, "item": claimed}

    @router.post("/assignments/{task_id}/start")
    def start_execution(
        node_id: str,
        task_id: str,
        payload: dict = Body(...),
        authorization: str | None = Header(default=None),
    ):
        return invoke(
            service().start_execution,
            node_id,
            token(authorization),
            task_id,
            str(payload.get("assignment_lease_token") or ""),
        )

    @router.post("/executions/{task_id}/heartbeat")
    def heartbeat_execution(
        node_id: str,
        task_id: str,
        payload: dict = Body(...),
        authorization: str | None = Header(default=None),
    ):
        return invoke(
            service().heartbeat_execution,
            node_id,
            token(authorization),
            task_id,
            str(payload.get("execution_lease_token") or ""),
            int(payload.get("execution_generation") or 0),
            progress=payload.get("progress"),
            stage=payload.get("stage"),
            current_item=payload.get("current_item"),
        )

    @router.post("/executions/{task_id}/logs")
    def append_log(
        node_id: str,
        task_id: str,
        payload: dict = Body(...),
        authorization: str | None = Header(default=None),
    ):
        return invoke(
            service().append_log,
            node_id,
            token(authorization),
            task_id,
            str(payload.get("execution_lease_token") or ""),
            int(payload.get("execution_generation") or 0),
            str(payload.get("text") or ""),
        )

    @router.post("/executions/{task_id}/begin-finalization")
    def begin_finalization(
        node_id: str,
        task_id: str,
        payload: dict = Body(...),
        authorization: str | None = Header(default=None),
    ):
        return invoke(
            service().begin_finalization,
            node_id,
            token(authorization),
            task_id,
            str(payload.get("execution_lease_token") or ""),
            int(payload.get("execution_generation") or 0),
        )

    @router.post("/executions/{task_id}/finish")
    def finish_execution(
        node_id: str,
        task_id: str,
        payload: dict = Body(...),
        authorization: str | None = Header(default=None),
    ):
        return invoke(
            service().finish_execution,
            node_id,
            token(authorization),
            task_id,
            str(payload.get("execution_lease_token") or ""),
            int(payload.get("execution_generation") or 0),
            status=str(payload.get("status") or ""),
            result_ref=payload.get("result_ref"),
            error=payload.get("error"),
            accepted=payload.get("accepted"),
        )

    return router


__all__ = [
    "AgentExecutionError",
    "AgentExecutionService",
    "DEFAULT_EXECUTION_LEASE_SECONDS",
    "MAX_REMOTE_LOG_BYTES",
    "agent_executor_router",
]
