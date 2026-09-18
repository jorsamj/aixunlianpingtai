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
import re
import secrets
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any

from .service_nodes import (
    HEARTBEAT_TTL_SECONDS,
    ServiceNodeError,
    ServiceNodeRepository,
    verify_service_node_token,
)
from .task_node_assignments import CentralTaskAllocator
from .task_runtime import TaskKind, TaskStatus
from .task_runtime.fenced_repository import FencedTaskRepository
from .task_runtime.repository import TERMINAL_STATUSES, _from_row


DEFAULT_EXECUTION_LEASE_SECONDS = 30
MAX_REMOTE_LOG_BYTES = 64 * 1024
MAX_REMOTE_RESULT_METADATA_BYTES = 64 * 1024


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


def _remote_result_state_ref(execution_generation: int) -> str:
    return f"remote-results/{int(execution_generation)}/upload.json"


def _remote_result_ref(execution_generation: int) -> str:
    return f"remote-results/{int(execution_generation)}/result.json"


def _remote_training_models_state_ref(execution_generation: int) -> str:
    return f"remote-results/{int(execution_generation)}/training-models.json"


def _json(value: object, fallback):
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError):
        return fallback


def _sanitize_runtime_result_metadata(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AgentExecutionError(
            "REMOTE_RESULT_METADATA_INVALID",
            "runtime_result must be an object",
            422,
        )

    result: dict[str, Any] = {}
    if "ok" in value:
        result["ok"] = bool(value.get("ok"))

    for key in (
        "preprocess_ms",
        "inference_ms",
        "postprocess_ms",
        "elapsed_ms",
        "total_elapsed_ms",
    ):
        raw = value.get(key)
        if raw is None:
            continue
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise AgentExecutionError(
                "REMOTE_RESULT_METADATA_INVALID",
                f"{key} must be numeric",
                422,
            )
        result[key] = float(raw)

    for key, maximum in (
        ("engine", 120),
        ("model", 240),
        ("note", 2000),
    ):
        raw = value.get(key)
        if raw is None:
            continue
        text = str(raw)
        if len(text) > maximum:
            raise AgentExecutionError(
                "REMOTE_RESULT_METADATA_INVALID",
                f"{key} exceeds maximum length",
                422,
            )
        if key == "model" and ("/" in text or "\\" in text):
            raise AgentExecutionError(
                "REMOTE_RESULT_METADATA_INVALID",
                "model must not disclose a local path",
                422,
            )
        result[key] = text

    labels = value.get("labels")
    if labels is not None:
        if not isinstance(labels, list) or len(labels) > 1000:
            raise AgentExecutionError(
                "REMOTE_RESULT_METADATA_INVALID",
                "labels must be a list with at most 1000 entries",
                422,
            )
        clean_labels = []
        for item in labels:
            text = str(item)
            if len(text) > 256:
                raise AgentExecutionError(
                    "REMOTE_RESULT_METADATA_INVALID",
                    "label exceeds maximum length",
                    422,
                )
            clean_labels.append(text)
        result["labels"] = clean_labels

    detections = value.get("detections")
    if detections is not None:
        if not isinstance(detections, list) or len(detections) > 1000:
            raise AgentExecutionError(
                "REMOTE_RESULT_METADATA_INVALID",
                "detections must be a list with at most 1000 entries",
                422,
            )
        clean_detections = []
        allowed_numeric = ("class_id", "confidence", "x1", "y1", "x2", "y2")
        for item in detections:
            if not isinstance(item, dict):
                raise AgentExecutionError(
                    "REMOTE_RESULT_METADATA_INVALID",
                    "each detection must be an object",
                    422,
                )
            clean: dict[str, Any] = {}
            if "label" in item:
                label = str(item.get("label") or "")
                if len(label) > 256:
                    raise AgentExecutionError(
                        "REMOTE_RESULT_METADATA_INVALID",
                        "detection label exceeds maximum length",
                        422,
                    )
                clean["label"] = label
            for key in allowed_numeric:
                raw = item.get(key)
                if raw is None:
                    continue
                if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                    raise AgentExecutionError(
                        "REMOTE_RESULT_METADATA_INVALID",
                        f"detection {key} must be numeric",
                        422,
                    )
                clean[key] = int(raw) if key == "class_id" else float(raw)
            clean_detections.append(clean)
        result["detections"] = clean_detections

    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_REMOTE_RESULT_METADATA_BYTES:
        raise AgentExecutionError(
            "REMOTE_RESULT_METADATA_TOO_LARGE",
            "runtime_result exceeds 64 KiB",
            413,
        )
    return result


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
        execution_payload_resolver=None,
        result_upload_preparer=None,
        result_upload_confirmer=None,
        result_commit_handler=None,
        training_model_upload_preparer=None,
        training_model_upload_confirmer=None,
    ):
        self.repository = repository
        self.artifacts = artifacts
        self.heartbeat_ttl_seconds = max(10, int(heartbeat_ttl_seconds))
        self.execution_lease_seconds = max(5, int(execution_lease_seconds))
        self.execution_payload_resolver = execution_payload_resolver
        self.result_upload_preparer = result_upload_preparer
        self.result_upload_confirmer = result_upload_confirmer
        self.result_commit_handler = result_commit_handler
        self.training_model_upload_preparer = training_model_upload_preparer
        self.training_model_upload_confirmer = training_model_upload_confirmer
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
        require_enabled: bool = True,
        required_capability: str | None = None,
    ) -> dict[str, Any]:
        self.nodes.authenticate(node_id, node_token)
        node = self.nodes.get_public(node_id)
        if require_enabled and not node["enabled"]:
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
        node_public = self.nodes.get_public(node_id)
        preflight_task = self.repository.get(task_id)
        if preflight_task is None:
            raise AgentExecutionError("TASK_NOT_FOUND", "assigned task no longer exists", 404)
        missing_payload = object()
        try:
            payload = self.artifacts.read_json(
                preflight_task.task_id,
                preflight_task.payload_ref,
                default=missing_payload,
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise AgentExecutionError(
                "TASK_PAYLOAD_UNAVAILABLE",
                "assigned task payload cannot be read",
                409,
            ) from error
        if payload is missing_payload:
            raise AgentExecutionError(
                "TASK_PAYLOAD_UNAVAILABLE",
                "assigned task payload does not exist",
                409,
            )

        current, now = _iso_now()
        # Check assignment ownership before minting any short-lived transport
        # credentials. The authoritative transaction below repeats these checks.
        with closing(self.repository._connect()) as database:
            preflight_assignment = database.execute(
                """
                SELECT * FROM task_node_assignments
                 WHERE task_id=? AND node_id=? AND state='CLAIMED'
                 ORDER BY generation DESC LIMIT 1
                """,
                (str(task_id), str(node_id)),
            ).fetchone()
        if preflight_assignment is None:
            raise AgentExecutionError(
                "ASSIGNMENT_NOT_CLAIMED",
                "task has no claimed assignment for this node",
                409,
            )
        preflight_assignment_token = str(preflight_assignment["lease_token"] or "")
        supplied_assignment_token = str(assignment_lease_token or "")
        if (
            not preflight_assignment_token
            or not supplied_assignment_token
            or not hmac.compare_digest(preflight_assignment_token, supplied_assignment_token)
        ):
            raise AgentExecutionError(
                "INVALID_ASSIGNMENT_LEASE",
                "assignment lease token is invalid",
                401,
            )
        if (
            not preflight_assignment["lease_expires_at"]
            or str(preflight_assignment["lease_expires_at"]) <= now
        ):
            raise AgentExecutionError(
                "ASSIGNMENT_LEASE_EXPIRED",
                "assignment lease expired before execution start",
                409,
            )
        assignment_snapshot = {
            "generation": int(preflight_assignment["generation"]),
            "node_id": str(preflight_assignment["node_id"]),
            "capability": str(preflight_assignment["capability"]),
            "resolved_execution_config": _json(
                preflight_assignment["resolved_execution_config"], {}
            ),
        }

        execution_payload = payload
        if str(node_public.get("connection_mode") or "") == "agent":
            if not isinstance(payload, dict):
                raise AgentExecutionError(
                    "REMOTE_EXECUTION_PAYLOAD_INVALID",
                    "remote task payload must be an object",
                    422,
                )
            if not callable(self.execution_payload_resolver):
                raise AgentExecutionError(
                    "REMOTE_EXECUTION_PAYLOAD_UNAVAILABLE",
                    "remote Agent execution payload resolver is not configured",
                    409,
                )
            try:
                execution_payload = self.execution_payload_resolver(
                    preflight_task,
                    payload,
                    assignment_snapshot,
                )
            except AgentExecutionError:
                raise
            except Exception as error:
                code = str(getattr(error, "code", "") or "REMOTE_EXECUTION_PAYLOAD_FAILED")
                status_code = int(getattr(error, "status_code", 409) or 409)
                raise AgentExecutionError(code, str(error), status_code) from error
            if not isinstance(execution_payload, dict):
                raise AgentExecutionError(
                    "REMOTE_EXECUTION_PAYLOAD_INVALID",
                    "remote execution payload resolver returned a non-object",
                    500,
                )

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
                "SELECT enabled,last_heartbeat_at,allowed_capabilities,reported_capabilities,token_hash FROM service_nodes WHERE node_id=?",
                (str(node_id),),
            ).fetchone()
            if node is None or not bool(node["enabled"]):
                database.rollback()
                raise AgentExecutionError("NODE_DISABLED", "service node is disabled", 409)
            if not verify_service_node_token(
                node_id,
                node_token,
                str(node["token_hash"] or ""),
            ):
                database.rollback()
                raise AgentExecutionError(
                    "INVALID_NODE_TOKEN",
                    "service node token changed before execution start",
                    401,
                )
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
            "payload": execution_payload,
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
        self._authenticate_node(
            node_id,
            node_token,
            require_online=False,
            require_enabled=False,
        )
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
        # Re-check immediately before publishing the append. Logs are append-only,
        # but a stale generation must still be fenced from writing after takeover.
        task = self._owned_execution(
            node_id,
            node_token,
            task_id,
            execution_lease_token,
            execution_generation,
        )
        self.artifacts.append_log(task.task_id, task.log_ref, value)
        return {"ok": True, "bytes": len(value.encode("utf-8"))}

    def _read_task_payload(self, task) -> dict[str, Any]:
        missing = object()
        try:
            payload = self.artifacts.read_json(
                task.task_id,
                task.payload_ref,
                default=missing,
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise AgentExecutionError(
                "TASK_PAYLOAD_UNAVAILABLE",
                "task payload cannot be read",
                409,
            ) from error
        if payload is missing or not isinstance(payload, dict):
            raise AgentExecutionError(
                "TASK_PAYLOAD_UNAVAILABLE",
                "task payload is unavailable or invalid",
                409,
            )
        return payload

    @staticmethod
    def _requires_remote_result_confirmation(task, payload: dict[str, Any]) -> bool:
        remote = payload.get("remote_execution")
        return (
            task.kind in {
                TaskKind.DEPLOYMENT_TEST,
                TaskKind.TRAINING,
                TaskKind.MODEL_CONVERSION,
                TaskKind.MATERIAL_IMPORT,
            }
            and isinstance(remote, dict)
            and int(remote.get("version") or 0) == 1
            and str(remote.get("task_kind") or "") == task.kind.value
            and str(remote.get("transport") or "") == "object-storage-v1"
        )

    @staticmethod
    def _normalized_result_evidence(sha256: object, size_bytes: object, generation: int) -> dict[str, Any]:
        digest = str(sha256 or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise AgentExecutionError(
                "REMOTE_RESULT_EVIDENCE_INVALID",
                "result sha256 must be a 64-character hexadecimal SHA256",
                422,
            )
        try:
            size = int(size_bytes)
        except (TypeError, ValueError) as error:
            raise AgentExecutionError(
                "REMOTE_RESULT_EVIDENCE_INVALID",
                "result size_bytes must be a positive integer",
                422,
            ) from error
        if size <= 0:
            raise AgentExecutionError(
                "REMOTE_RESULT_EVIDENCE_INVALID",
                "result size_bytes must be a positive integer",
                422,
            )
        return {
            "sha256": digest,
            "size_bytes": size,
            "execution_generation": int(generation),
        }

    def _confirmed_remote_result(self, task, execution_generation: int) -> dict[str, Any] | None:
        payload = self._read_task_payload(task)
        if not self._requires_remote_result_confirmation(task, payload):
            return None
        state = self.artifacts.read_json(
            task.task_id,
            _remote_result_state_ref(execution_generation),
            default={},
        )
        if (
            not isinstance(state, dict)
            or state.get("confirmed") is not True
            or int(state.get("execution_generation") or 0) != int(execution_generation)
            or str(state.get("result_ref") or "") != _remote_result_ref(execution_generation)
        ):
            raise AgentExecutionError(
                "REMOTE_RESULT_NOT_CONFIRMED",
                "remote execution result must be uploaded and verified before finalization",
                409,
            )
        return state

    @staticmethod
    def _model_evidence_projection(items: object) -> list[dict[str, Any]]:
        if not isinstance(items, list) or not items or len(items) > 4:
            raise AgentExecutionError(
                "REMOTE_TRAINING_MODELS_INVALID",
                "training model upload response must contain 1-4 entries",
                500,
            )
        projected = []
        for item in items:
            if not isinstance(item, dict):
                raise AgentExecutionError(
                    "REMOTE_TRAINING_MODELS_INVALID",
                    "training model upload entry must be an object",
                    500,
                )
            role = str(item.get("role") or "").strip().lower()
            digest = str(item.get("sha256") or "").strip().lower()
            try:
                size = int(item.get("size_bytes") or 0)
            except (TypeError, ValueError) as error:
                raise AgentExecutionError(
                    "REMOTE_TRAINING_MODELS_INVALID",
                    "training model size evidence is invalid",
                    500,
                ) from error
            file_name = str(item.get("file_name") or "").strip()
            artifact_id = str(item.get("artifact_id") or "").strip()
            storage_ref = item.get("storage_ref")
            if (
                role not in {"best", "last"}
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or size <= 0
                or not file_name
                or "/" in file_name
                or "\\" in file_name
                or not artifact_id
                or not isinstance(storage_ref, dict)
                or not str(storage_ref.get("storage_source_id") or "").strip()
                or not str(storage_ref.get("object_key") or "").strip()
            ):
                raise AgentExecutionError(
                    "REMOTE_TRAINING_MODELS_INVALID",
                    "training model upload response contains invalid evidence",
                    500,
                )
            projected.append({
                "role": role,
                "file_name": file_name,
                "sha256": digest,
                "size_bytes": size,
                "artifact_id": artifact_id,
                "storage_ref": {
                    "storage_source_id": str(storage_ref.get("storage_source_id") or ""),
                    "object_key": str(storage_ref.get("object_key") or ""),
                    "file_name": str(storage_ref.get("file_name") or file_name),
                    "content_type": str(storage_ref.get("content_type") or "application/octet-stream"),
                },
            })
        roles = [item["role"] for item in projected]
        if len(set(roles)) != len(roles):
            raise AgentExecutionError(
                "REMOTE_TRAINING_MODELS_INVALID",
                "training model roles must be unique",
                500,
            )
        return sorted(projected, key=lambda item: item["role"])

    def prepare_training_model_uploads(
        self,
        node_id: str,
        node_token: str,
        task_id: str,
        execution_lease_token: str,
        execution_generation: int,
        *,
        models: object,
    ) -> dict[str, Any]:
        current = self._owned_execution(
            node_id,
            node_token,
            task_id,
            execution_lease_token,
            execution_generation,
        )
        if current.status is TaskStatus.CANCEL_REQUESTED:
            raise AgentExecutionError(
                "CANCELLATION_WON",
                "cancel-requested execution cannot prepare training model uploads",
                409,
            )
        payload = self._read_task_payload(current)
        if current.kind is not TaskKind.TRAINING or not self._requires_remote_result_confirmation(current, payload):
            raise AgentExecutionError(
                "REMOTE_TRAINING_MODEL_PROTOCOL_UNAVAILABLE",
                "this execution does not use the portable training model protocol",
                409,
            )
        if not callable(self.training_model_upload_preparer):
            raise AgentExecutionError(
                "REMOTE_TRAINING_MODEL_UPLOAD_UNAVAILABLE",
                "training model upload preparer is not configured",
                409,
            )
        try:
            prepared = self.training_model_upload_preparer(
                current,
                payload,
                execution_generation=int(execution_generation),
                models=models,
            )
        except AgentExecutionError:
            raise
        except Exception as error:
            raise AgentExecutionError(
                str(getattr(error, "code", "") or "REMOTE_TRAINING_MODEL_PREPARE_FAILED"),
                str(error),
                int(getattr(error, "status_code", 409) or 409),
            ) from error
        if not isinstance(prepared, dict):
            raise AgentExecutionError(
                "REMOTE_TRAINING_MODEL_PREPARE_INVALID",
                "training model upload preparer returned a non-object",
                500,
            )
        projected = self._model_evidence_projection(prepared.get("items"))
        version_id = str(prepared.get("version_id") or "").strip()
        if not version_id:
            raise AgentExecutionError(
                "REMOTE_TRAINING_MODEL_PREPARE_INVALID",
                "training model upload preparer returned no version id",
                500,
            )

        # Re-prove execution ownership after signing ephemeral PUT URLs.
        owned_after_signing = self._owned_execution(
            node_id,
            node_token,
            task_id,
            execution_lease_token,
            execution_generation,
        )
        if owned_after_signing.status is TaskStatus.CANCEL_REQUESTED:
            raise AgentExecutionError(
                "CANCELLATION_WON",
                "task cancellation won while preparing training model uploads",
                409,
            )
        state_ref = _remote_training_models_state_ref(execution_generation)
        existing = self.artifacts.read_json(current.task_id, state_ref, default={})
        if isinstance(existing, dict) and existing:
            existing_models = existing.get("models")
            if (
                int(existing.get("execution_generation") or 0) != int(execution_generation)
                or str(existing.get("node_id") or "") != str(node_id)
                or str(existing.get("version_id") or "") != version_id
                or existing_models != projected
            ):
                raise AgentExecutionError(
                    "REMOTE_TRAINING_MODEL_EVIDENCE_CONFLICT",
                    "prepared training model evidence conflicts with this execution generation",
                    409,
                )
        _, prepared_at = _iso_now()
        state = {
            "task_id": current.task_id,
            "project_id": current.project_id,
            "node_id": str(node_id),
            "execution_generation": int(execution_generation),
            "version_id": version_id,
            "models": projected,
            "prepared_at": str(existing.get("prepared_at") or prepared_at) if isinstance(existing, dict) else prepared_at,
            "confirmed": bool(existing.get("confirmed")) if isinstance(existing, dict) else False,
            "confirmed_at": existing.get("confirmed_at") if isinstance(existing, dict) else None,
        }
        self.artifacts.atomic_write_json(current.task_id, state_ref, state)
        return prepared

    def confirm_training_model_uploads(
        self,
        node_id: str,
        node_token: str,
        task_id: str,
        execution_lease_token: str,
        execution_generation: int,
    ) -> dict[str, Any]:
        current = self._owned_execution(
            node_id,
            node_token,
            task_id,
            execution_lease_token,
            execution_generation,
        )
        if current.status is TaskStatus.CANCEL_REQUESTED:
            raise AgentExecutionError(
                "CANCELLATION_WON",
                "cancel-requested execution cannot confirm training model uploads",
                409,
            )
        payload = self._read_task_payload(current)
        if current.kind is not TaskKind.TRAINING or not self._requires_remote_result_confirmation(current, payload):
            raise AgentExecutionError(
                "REMOTE_TRAINING_MODEL_PROTOCOL_UNAVAILABLE",
                "this execution does not use the portable training model protocol",
                409,
            )
        if not callable(self.training_model_upload_confirmer):
            raise AgentExecutionError(
                "REMOTE_TRAINING_MODEL_CONFIRM_UNAVAILABLE",
                "training model upload confirmer is not configured",
                409,
            )
        state_ref = _remote_training_models_state_ref(execution_generation)
        state = self.artifacts.read_json(current.task_id, state_ref, default={})
        if (
            not isinstance(state, dict)
            or int(state.get("execution_generation") or 0) != int(execution_generation)
            or str(state.get("node_id") or "") != str(node_id)
            or not str(state.get("version_id") or "")
            or not isinstance(state.get("models"), list)
        ):
            raise AgentExecutionError(
                "REMOTE_TRAINING_MODELS_NOT_PREPARED",
                "training model uploads must be prepared by this execution generation first",
                409,
            )
        if state.get("confirmed") is True:
            return {
                "confirmed": True,
                "version_id": str(state["version_id"]),
                "items": list(state["models"]),
            }
        try:
            confirmed = self.training_model_upload_confirmer(
                current,
                payload,
                execution_generation=int(execution_generation),
                models=state["models"],
            )
        except AgentExecutionError:
            raise
        except Exception as error:
            raise AgentExecutionError(
                str(getattr(error, "code", "") or "REMOTE_TRAINING_MODEL_CONFIRM_FAILED"),
                str(error),
                int(getattr(error, "status_code", 409) or 409),
            ) from error
        if not isinstance(confirmed, dict):
            raise AgentExecutionError(
                "REMOTE_TRAINING_MODEL_CONFIRM_INVALID",
                "training model upload confirmer returned a non-object",
                500,
            )
        projected = self._model_evidence_projection(confirmed.get("items"))
        if (
            str(confirmed.get("version_id") or "") != str(state["version_id"])
            or projected != state["models"]
            or confirmed.get("confirmed") is not True
        ):
            raise AgentExecutionError(
                "REMOTE_TRAINING_MODEL_CONFIRM_INVALID",
                "confirmed training model evidence changed after upload",
                500,
            )
        self._owned_execution(
            node_id,
            node_token,
            task_id,
            execution_lease_token,
            execution_generation,
        )
        _, confirmed_at = _iso_now()
        state.update({
            "confirmed": True,
            "confirmed_at": confirmed_at,
        })
        self.artifacts.atomic_write_json(current.task_id, state_ref, state)
        return {
            "confirmed": True,
            "version_id": str(state["version_id"]),
            "items": list(state["models"]),
        }

    def _confirmed_training_models(
        self,
        task,
        execution_generation: int,
    ) -> dict[str, Any] | None:
        if task.kind is not TaskKind.TRAINING:
            return None
        state = self.artifacts.read_json(
            task.task_id,
            _remote_training_models_state_ref(execution_generation),
            default={},
        )
        if (
            not isinstance(state, dict)
            or state.get("confirmed") is not True
            or int(state.get("execution_generation") or 0) != int(execution_generation)
            or not str(state.get("version_id") or "")
            or not isinstance(state.get("models"), list)
        ):
            raise AgentExecutionError(
                "REMOTE_TRAINING_MODELS_NOT_CONFIRMED",
                "remote training models must be uploaded and verified before result finalization",
                409,
            )
        return state

    def prepare_result_upload(
        self,
        node_id: str,
        node_token: str,
        task_id: str,
        execution_lease_token: str,
        execution_generation: int,
        *,
        sha256: object,
        size_bytes: object,
    ) -> dict[str, Any]:
        current = self._owned_execution(
            node_id,
            node_token,
            task_id,
            execution_lease_token,
            execution_generation,
        )
        if current.status is TaskStatus.CANCEL_REQUESTED:
            raise AgentExecutionError(
                "CANCELLATION_WON",
                "cancel-requested execution cannot prepare a result upload",
                409,
            )
        payload = self._read_task_payload(current)
        if not self._requires_remote_result_confirmation(current, payload):
            raise AgentExecutionError(
                "REMOTE_RESULT_PROTOCOL_UNAVAILABLE",
                "this execution does not use the portable result publication protocol",
                409,
            )
        if not callable(self.result_upload_preparer):
            raise AgentExecutionError(
                "REMOTE_RESULT_UPLOAD_UNAVAILABLE",
                "remote result upload preparer is not configured",
                409,
            )
        evidence = self._normalized_result_evidence(
            sha256,
            size_bytes,
            execution_generation,
        )
        state_ref = _remote_result_state_ref(execution_generation)
        existing = self.artifacts.read_json(current.task_id, state_ref, default={})
        if isinstance(existing, dict) and existing:
            if (
                int(existing.get("execution_generation") or 0) != int(execution_generation)
                or str(existing.get("node_id") or "") != str(node_id)
                or str(existing.get("sha256") or "") != evidence["sha256"]
                or int(existing.get("size_bytes") or 0) != evidence["size_bytes"]
            ):
                raise AgentExecutionError(
                    "REMOTE_RESULT_EVIDENCE_CONFLICT",
                    "prepared result evidence conflicts with this execution generation",
                    409,
                )
            if existing.get("confirmed") is True:
                return {
                    "already_uploaded": True,
                    "confirmed": True,
                    "storage_ref": dict(existing.get("storage_ref") or {}),
                    "sha256": evidence["sha256"],
                    "size_bytes": evidence["size_bytes"],
                    "upload": None,
                }
        try:
            prepared = self.result_upload_preparer(current, payload, evidence)
        except AgentExecutionError:
            raise
        except Exception as error:
            raise AgentExecutionError(
                str(getattr(error, "code", "") or "REMOTE_RESULT_UPLOAD_PREPARE_FAILED"),
                str(error),
                int(getattr(error, "status_code", 409) or 409),
            ) from error
        if not isinstance(prepared, dict) or not isinstance(prepared.get("storage_ref"), dict):
            raise AgentExecutionError(
                "REMOTE_RESULT_UPLOAD_INVALID",
                "result upload preparer returned an invalid response",
                500,
            )
        if str(prepared.get("sha256") or "") != evidence["sha256"] or int(
            prepared.get("size_bytes") or 0
        ) != evidence["size_bytes"]:
            raise AgentExecutionError(
                "REMOTE_RESULT_UPLOAD_INVALID",
                "result upload preparer changed execution content evidence",
                500,
            )

        # Re-check ownership after external storage signing. A stale generation
        # may receive a short-lived URL, but generation-scoped object keys keep
        # it isolated and stale evidence is never published as current truth.
        owned_after_signing = self._owned_execution(
            node_id,
            node_token,
            task_id,
            execution_lease_token,
            execution_generation,
        )
        if owned_after_signing.status is TaskStatus.CANCEL_REQUESTED:
            raise AgentExecutionError(
                "CANCELLATION_WON",
                "task cancellation won while preparing result upload",
                409,
            )
        _, prepared_at = _iso_now()
        state = {
            "task_id": current.task_id,
            "project_id": current.project_id,
            "node_id": str(node_id),
            "execution_generation": int(execution_generation),
            "sha256": evidence["sha256"],
            "size_bytes": evidence["size_bytes"],
            "storage_ref": dict(prepared["storage_ref"]),
            "prepared_at": prepared_at,
            "confirmed": False,
        }
        self.artifacts.atomic_write_json(current.task_id, state_ref, state)
        return {
            "already_uploaded": bool(prepared.get("already_uploaded")),
            "confirmed": False,
            "storage_ref": dict(prepared["storage_ref"]),
            "sha256": evidence["sha256"],
            "size_bytes": evidence["size_bytes"],
            "upload": prepared.get("upload"),
        }

    def confirm_result_upload(
        self,
        node_id: str,
        node_token: str,
        task_id: str,
        execution_lease_token: str,
        execution_generation: int,
        *,
        runtime_result: object = None,
    ) -> dict[str, Any]:
        current = self._owned_execution(
            node_id,
            node_token,
            task_id,
            execution_lease_token,
            execution_generation,
        )
        if current.status is TaskStatus.CANCEL_REQUESTED:
            raise AgentExecutionError(
                "CANCELLATION_WON",
                "cancel-requested execution cannot confirm a result upload",
                409,
            )
        payload = self._read_task_payload(current)
        runtime_metadata = _sanitize_runtime_result_metadata(runtime_result)
        if not self._requires_remote_result_confirmation(current, payload):
            raise AgentExecutionError(
                "REMOTE_RESULT_PROTOCOL_UNAVAILABLE",
                "this execution does not use the portable result publication protocol",
                409,
            )
        if not callable(self.result_upload_confirmer):
            raise AgentExecutionError(
                "REMOTE_RESULT_CONFIRM_UNAVAILABLE",
                "remote result upload confirmer is not configured",
                409,
            )
        state_ref = _remote_result_state_ref(execution_generation)
        state = self.artifacts.read_json(current.task_id, state_ref, default={})
        if (
            not isinstance(state, dict)
            or int(state.get("execution_generation") or 0) != int(execution_generation)
            or str(state.get("node_id") or "") != str(node_id)
            or not str(state.get("sha256") or "")
            or int(state.get("size_bytes") or 0) <= 0
        ):
            raise AgentExecutionError(
                "REMOTE_RESULT_NOT_PREPARED",
                "remote result upload must be prepared by this execution generation first",
                409,
            )
        if state.get("confirmed") is True:
            result = self.artifacts.read_json(
                current.task_id,
                str(state.get("result_ref") or ""),
                default={},
            )
            return {
                "confirmed": True,
                "result_ref": str(state.get("result_ref") or ""),
                "result": result if isinstance(result, dict) else {},
            }
        evidence = {
            "sha256": str(state["sha256"]),
            "size_bytes": int(state["size_bytes"]),
            "execution_generation": int(execution_generation),
        }
        try:
            confirmed = self.result_upload_confirmer(current, payload, evidence)
        except AgentExecutionError:
            raise
        except Exception as error:
            raise AgentExecutionError(
                str(getattr(error, "code", "") or "REMOTE_RESULT_CONFIRM_FAILED"),
                str(error),
                int(getattr(error, "status_code", 409) or 409),
            ) from error
        if not isinstance(confirmed, dict) or not isinstance(confirmed.get("result"), dict):
            raise AgentExecutionError(
                "REMOTE_RESULT_CONFIRM_INVALID",
                "result upload confirmer returned an invalid response",
                500,
            )
        training_models = self._confirmed_training_models(
            current,
            int(execution_generation),
        )
        if training_models is not None:
            manifest_models = confirmed["result"].get("verified_models")
            if not isinstance(manifest_models, list):
                raise AgentExecutionError(
                    "REMOTE_TRAINING_RESULT_MODELS_INVALID",
                    "training result manifest contains no model evidence",
                    409,
                )
            manifest_projection = sorted(
                [
                    {
                        "role": str(item.get("role") or "").strip().lower(),
                        "file_name": str(item.get("file_name") or "").strip(),
                        "sha256": str(item.get("sha256") or "").strip().lower(),
                        "size_bytes": int(item.get("size_bytes") or 0),
                    }
                    for item in manifest_models
                    if isinstance(item, dict)
                ],
                key=lambda item: item["role"],
            )
            state_projection = [
                {
                    "role": str(item["role"]),
                    "file_name": str(item["file_name"]),
                    "sha256": str(item["sha256"]),
                    "size_bytes": int(item["size_bytes"]),
                }
                for item in training_models["models"]
            ]
            if manifest_projection != state_projection:
                raise AgentExecutionError(
                    "REMOTE_TRAINING_RESULT_MODELS_MISMATCH",
                    "training result manifest does not match confirmed model artifact uploads",
                    409,
                )
            confirmed = {
                **confirmed,
                "training_models": {
                    "version_id": str(training_models["version_id"]),
                    "models": list(training_models["models"]),
                },
            }

        # Object verification happens before the commit gate. Then reuse the
        # durable finalization transaction so cancellation and result publication
        # cannot both win after verification.
        self._owned_execution(
            node_id,
            node_token,
            task_id,
            execution_lease_token,
            execution_generation,
        )
        try:
            self.fenced.begin_finalization(
                task_id,
                execution_lease_token,
                execution_generation=int(execution_generation),
            )
        except InterruptedError as error:
            raise AgentExecutionError(
                "CANCELLATION_WON",
                "task cancellation won while verifying result upload",
                409,
            ) from error
        except PermissionError as error:
            raise AgentExecutionError(
                "EXECUTION_FENCED",
                "remote execution lost ownership before result publication",
                409,
            ) from error
        commit_result: dict[str, Any] = {}
        if callable(self.result_commit_handler):
            try:
                committed = self.result_commit_handler(
                    current,
                    payload,
                    evidence,
                    confirmed,
                )
            except AgentExecutionError:
                raise
            except Exception as error:
                raise AgentExecutionError(
                    str(getattr(error, "code", "") or "REMOTE_RESULT_COMMIT_FAILED"),
                    str(error),
                    int(getattr(error, "status_code", 409) or 409),
                ) from error
            if committed is not None:
                if not isinstance(committed, dict):
                    raise AgentExecutionError(
                        "REMOTE_RESULT_COMMIT_INVALID",
                        "result commit handler returned a non-object",
                        500,
                    )
                commit_result = dict(committed)

        result_ref = _remote_result_ref(execution_generation)
        result = {
            **runtime_metadata,
            **dict(confirmed["result"]),
            **commit_result,
        }
        result["execution_generation"] = int(execution_generation)
        result["output_sha256"] = evidence["sha256"]
        result["output_size_bytes"] = evidence["size_bytes"]
        self.artifacts.atomic_write_json(current.task_id, result_ref, result)
        _, confirmed_at = _iso_now()
        state.update({
            "confirmed": True,
            "confirmed_at": confirmed_at,
            "result_ref": result_ref,
        })
        self.artifacts.atomic_write_json(current.task_id, state_ref, state)
        return {
            "confirmed": True,
            "result_ref": result_ref,
            "result": result,
        }

    def begin_finalization(
        self,
        node_id: str,
        node_token: str,
        task_id: str,
        execution_lease_token: str,
        execution_generation: int,
    ) -> dict[str, Any]:
        current = self._owned_execution(
            node_id,
            node_token,
            task_id,
            execution_lease_token,
            execution_generation,
        )
        if current.status is TaskStatus.CANCEL_REQUESTED:
            raise AgentExecutionError(
                "CANCELLATION_WON",
                "task cancellation won before finalization",
                409,
            )
        self._confirmed_remote_result(current, execution_generation)
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
        if target in {
            TaskStatus.SUCCEEDED,
            TaskStatus.PARTIAL_SUCCESS,
            TaskStatus.AWAITING_CONFIRMATION,
        }:
            confirmed = self._confirmed_remote_result(current, execution_generation)
            if confirmed is not None:
                result_ref = str(confirmed["result_ref"])
        if (
            target is TaskStatus.AWAITING_CONFIRMATION
            and current.kind is not TaskKind.MATERIAL_IMPORT
        ):
            raise AgentExecutionError(
                "INVALID_FINISH_STATUS",
                "only material import may finish as awaiting confirmation",
                422,
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


def _execution_generation(value: object) -> int:
    try:
        generation = int(value)
    except (TypeError, ValueError) as error:
        raise AgentExecutionError(
            "INVALID_EXECUTION_GENERATION",
            "execution_generation must be a positive integer",
            422,
        ) from error
    if generation <= 0:
        raise AgentExecutionError(
            "INVALID_EXECUTION_GENERATION",
            "execution_generation must be a positive integer",
            422,
        )
    return generation


def _bearer_token(value: object) -> str:
    raw = str(value or "").strip()
    if not raw.lower().startswith("bearer ") or not raw[7:].strip():
        raise ServiceNodeError(
            "NODE_TOKEN_REQUIRED",
            "Bearer service node token is required",
            401,
        )
    return raw[7:].strip()


def agent_executor_router(
    task_repository,
    task_artifacts,
    execution_payload_resolver=None,
    result_upload_preparer=None,
    result_upload_confirmer=None,
    result_commit_handler=None,
    training_model_upload_preparer=None,
    training_model_upload_confirmer=None,
):
    from fastapi import APIRouter, Body, Header, HTTPException

    router = APIRouter(prefix="/api/v63/node-executor/{node_id}")

    def service() -> AgentExecutionService:
        return AgentExecutionService(
            task_repository(),
            task_artifacts(),
            execution_payload_resolver=execution_payload_resolver,
            result_upload_preparer=result_upload_preparer,
            result_upload_confirmer=result_upload_confirmer,
            result_commit_handler=result_commit_handler,
            training_model_upload_preparer=training_model_upload_preparer,
            training_model_upload_confirmer=training_model_upload_confirmer,
        )

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
            invoke(_execution_generation, payload.get("execution_generation")),
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
            invoke(_execution_generation, payload.get("execution_generation")),
            str(payload.get("text") or ""),
        )

    @router.post("/executions/{task_id}/training-models/prepare")
    def prepare_training_models(
        node_id: str,
        task_id: str,
        payload: dict = Body(...),
        authorization: str | None = Header(default=None),
    ):
        return invoke(
            service().prepare_training_model_uploads,
            node_id,
            token(authorization),
            task_id,
            str(payload.get("execution_lease_token") or ""),
            invoke(_execution_generation, payload.get("execution_generation")),
            models=payload.get("models"),
        )

    @router.post("/executions/{task_id}/training-models/confirm")
    def confirm_training_models(
        node_id: str,
        task_id: str,
        payload: dict = Body(...),
        authorization: str | None = Header(default=None),
    ):
        return invoke(
            service().confirm_training_model_uploads,
            node_id,
            token(authorization),
            task_id,
            str(payload.get("execution_lease_token") or ""),
            invoke(_execution_generation, payload.get("execution_generation")),
        )

    @router.post("/executions/{task_id}/result-upload/prepare")
    def prepare_result_upload(
        node_id: str,
        task_id: str,
        payload: dict = Body(...),
        authorization: str | None = Header(default=None),
    ):
        return invoke(
            service().prepare_result_upload,
            node_id,
            token(authorization),
            task_id,
            str(payload.get("execution_lease_token") or ""),
            invoke(_execution_generation, payload.get("execution_generation")),
            sha256=payload.get("sha256"),
            size_bytes=payload.get("size_bytes"),
        )

    @router.post("/executions/{task_id}/result-upload/confirm")
    def confirm_result_upload(
        node_id: str,
        task_id: str,
        payload: dict = Body(...),
        authorization: str | None = Header(default=None),
    ):
        return invoke(
            service().confirm_result_upload,
            node_id,
            token(authorization),
            task_id,
            str(payload.get("execution_lease_token") or ""),
            invoke(_execution_generation, payload.get("execution_generation")),
            runtime_result=payload.get("runtime_result"),
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
            invoke(_execution_generation, payload.get("execution_generation")),
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
            invoke(_execution_generation, payload.get("execution_generation")),
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
    "MAX_REMOTE_RESULT_METADATA_BYTES",
    "agent_executor_router",
]
