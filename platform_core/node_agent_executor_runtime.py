"""Agent-side client/runtime primitives for remote task execution.

This module is intentionally database-free.  A service-node Agent talks only to
control-plane HTTP APIs and a task-local work directory.  It must never import
or open the control-plane TaskRepository/SQLite database and must never assume a
shared NFS path.

Task-kind-specific portable runners are layered on top of these primitives.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote, urlparse

import requests


_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
DEFAULT_EXECUTOR_TIMEOUT_SECONDS = 15.0
DEFAULT_RESULT_CONFIRM_TIMEOUT_SECONDS = 300.0
DEFAULT_EXECUTION_HEARTBEAT_SECONDS = 5.0


class NodeExecutorHTTPError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 0,
        retryable: bool = False,
    ) -> None:
        self.code = str(code or "NODE_EXECUTOR_REQUEST_FAILED")
        self.status_code = int(status_code or 0)
        self.retryable = bool(retryable)
        super().__init__(str(message or self.code))


class RemoteExecutionFenced(RuntimeError):
    """The Agent can no longer prove ownership of the current execution."""


def _safe_component(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_COMPONENT.fullmatch(text) or text in {".", ".."}:
        raise ValueError(f"{field} must be one safe path component")
    return text


def _control_plane_base(value: object) -> str:
    base = str(value or "").strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("control plane URL must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("control plane URL must not contain userinfo")
    return base


def _json_error(body: object, fallback: str) -> tuple[str, str]:
    detail = body.get("detail") if isinstance(body, Mapping) else None
    if isinstance(detail, Mapping):
        return (
            str(detail.get("code") or "NODE_EXECUTOR_REQUEST_FAILED"),
            str(detail.get("message") or fallback),
        )
    if detail:
        return "NODE_EXECUTOR_REQUEST_FAILED", str(detail)
    return "NODE_EXECUTOR_REQUEST_FAILED", fallback


@dataclass(frozen=True)
class RemoteExecutionLease:
    task_id: str
    kind: str
    project_id: str
    generation: int
    lease_token: str
    lease_expires_at: str
    worker_id: str
    payload: dict[str, Any]
    assignment: dict[str, Any]
    transport: dict[str, Any]

    @classmethod
    def from_start_response(cls, body: Mapping[str, Any]) -> "RemoteExecutionLease":
        task = body.get("task")
        execution = body.get("execution")
        if not isinstance(task, Mapping) or not isinstance(execution, Mapping):
            raise ValueError("executor start response is missing task/execution")
        task_id = _safe_component(task.get("task_id"), "task_id")
        kind = str(task.get("kind") or "").strip()
        project_id = str(task.get("project_id") or "").strip()
        token = str(execution.get("lease_token") or "").strip()
        worker_id = str(execution.get("worker_id") or "").strip()
        expiry = str(execution.get("lease_expires_at") or "").strip()
        try:
            generation = int(execution.get("generation"))
        except (TypeError, ValueError) as error:
            raise ValueError("executor start response has invalid generation") from error
        if not kind or not token or generation <= 0 or not worker_id or not expiry:
            raise ValueError("executor start response is incomplete")
        payload = body.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("executor start response payload must be an object")
        assignment = body.get("assignment")
        transport = body.get("transport")
        return cls(
            task_id=task_id,
            kind=kind,
            project_id=project_id,
            generation=generation,
            lease_token=token,
            lease_expires_at=expiry,
            worker_id=worker_id,
            payload=dict(payload),
            assignment=dict(assignment) if isinstance(assignment, Mapping) else {},
            transport=dict(transport) if isinstance(transport, Mapping) else {},
        )


class NodeExecutorClient:
    def __init__(
        self,
        control_plane_url: str,
        node_id: str,
        token: str,
        *,
        session: requests.Session | None = None,
        timeout: float = DEFAULT_EXECUTOR_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = _control_plane_base(control_plane_url)
        self.node_id = _safe_component(node_id, "node_id")
        self.token = str(token or "").strip()
        if not self.token:
            raise ValueError("node token is required")
        self.session = session or requests.Session()
        self.timeout = max(1.0, float(timeout))

    @property
    def _prefix(self) -> str:
        return (
            f"{self.base_url}/api/v63/node-executor/"
            f"{quote(self.node_id, safe='')}"
        )

    def _post(
        self,
        suffix: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        request_timeout = self.timeout if timeout is None else max(1.0, float(timeout))
        try:
            response = self.session.post(
                self._prefix + suffix,
                headers={"Authorization": f"Bearer {self.token}"},
                json=dict(payload or {}),
                timeout=request_timeout,
            )
        except requests.RequestException as error:
            raise NodeExecutorHTTPError(
                "NODE_EXECUTOR_TRANSPORT_FAILED",
                f"{type(error).__name__}: {error}",
                retryable=True,
            ) from error
        try:
            body = response.json()
        except ValueError as error:
            if response.ok:
                raise NodeExecutorHTTPError(
                    "NODE_EXECUTOR_INVALID_RESPONSE",
                    "control plane returned non-JSON executor response",
                    status_code=int(response.status_code),
                ) from error
            body = {}
        if not response.ok:
            code, message = _json_error(
                body,
                f"control plane returned HTTP {response.status_code}",
            )
            raise NodeExecutorHTTPError(
                code,
                message,
                status_code=int(response.status_code),
                retryable=int(response.status_code) in {408, 425, 429} or int(response.status_code) >= 500,
            )
        if not isinstance(body, dict):
            raise NodeExecutorHTTPError(
                "NODE_EXECUTOR_INVALID_RESPONSE",
                "control plane returned a non-object executor response",
            )
        return body

    def claim_assignment(self) -> dict[str, Any] | None:
        body = self._post("/assignments/claim")
        if not bool(body.get("claimed")):
            return None
        item = body.get("item")
        if not isinstance(item, Mapping):
            raise NodeExecutorHTTPError(
                "NODE_EXECUTOR_INVALID_RESPONSE",
                "claimed assignment response is missing item",
            )
        return dict(item)

    def start_execution(
        self,
        task_id: str,
        assignment_lease_token: str,
    ) -> RemoteExecutionLease:
        key = _safe_component(task_id, "task_id")
        token = str(assignment_lease_token or "").strip()
        if not token:
            raise ValueError("assignment lease token is required")
        body = self._post(
            f"/assignments/{quote(key, safe='')}/start",
            {"assignment_lease_token": token},
        )
        return RemoteExecutionLease.from_start_response(body)

    def heartbeat(
        self,
        lease: RemoteExecutionLease,
        *,
        progress: float | None = None,
        stage: str | None = None,
        current_item: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "execution_lease_token": lease.lease_token,
            "execution_generation": lease.generation,
        }
        if progress is not None:
            payload["progress"] = float(progress)
        if stage is not None:
            payload["stage"] = str(stage)
        if current_item is not None:
            payload["current_item"] = str(current_item)
        return self._post(
            f"/executions/{quote(lease.task_id, safe='')}/heartbeat",
            payload,
        )

    def append_log(self, lease: RemoteExecutionLease, text: str) -> dict[str, Any]:
        return self._post(
            f"/executions/{quote(lease.task_id, safe='')}/logs",
            {
                "execution_lease_token": lease.lease_token,
                "execution_generation": lease.generation,
                "text": str(text or ""),
            },
        )

    def material_scan_page(
        self,
        lease: RemoteExecutionLease,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "execution_lease_token": lease.lease_token,
            "execution_generation": lease.generation,
            "limit": max(1, min(100, int(limit))),
        }
        if cursor:
            payload["cursor"] = str(cursor)
        return self._post(
            f"/executions/{quote(lease.task_id, safe='')}/material-scan/page",
            payload,
        )

    def material_scan_read(
        self,
        lease: RemoteExecutionLease,
        object_key: str,
    ) -> dict[str, Any]:
        key = str(object_key or "").strip()
        if not key:
            raise ValueError("material scan object_key is required")
        return self._post(
            f"/executions/{quote(lease.task_id, safe='')}/material-scan/read",
            {
                "execution_lease_token": lease.lease_token,
                "execution_generation": lease.generation,
                "object_key": key,
            },
        )

    def prepare_training_model_uploads(
        self,
        lease: RemoteExecutionLease,
        models: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        return self._post(
            f"/executions/{quote(lease.task_id, safe='')}/training-models/prepare",
            {
                "execution_lease_token": lease.lease_token,
                "execution_generation": lease.generation,
                "models": [dict(item) for item in models],
            },
        )

    def confirm_training_model_uploads(
        self,
        lease: RemoteExecutionLease,
    ) -> dict[str, Any]:
        return self._post(
            f"/executions/{quote(lease.task_id, safe='')}/training-models/confirm",
            {
                "execution_lease_token": lease.lease_token,
                "execution_generation": lease.generation,
            },
        )

    def prepare_result_upload(
        self,
        lease: RemoteExecutionLease,
        *,
        sha256: str,
        size_bytes: int,
    ) -> dict[str, Any]:
        return self._post(
            f"/executions/{quote(lease.task_id, safe='')}/result-upload/prepare",
            {
                "execution_lease_token": lease.lease_token,
                "execution_generation": lease.generation,
                "sha256": str(sha256 or ""),
                "size_bytes": int(size_bytes),
            },
        )

    def confirm_result_upload(
        self,
        lease: RemoteExecutionLease,
        *,
        runtime_result: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "execution_lease_token": lease.lease_token,
            "execution_generation": lease.generation,
        }
        if runtime_result is not None:
            payload["runtime_result"] = dict(runtime_result)
        return self._post(
            f"/executions/{quote(lease.task_id, safe='')}/result-upload/confirm",
            payload,
            timeout=max(self.timeout, DEFAULT_RESULT_CONFIRM_TIMEOUT_SECONDS),
        )

    def begin_finalization(self, lease: RemoteExecutionLease) -> dict[str, Any]:
        return self._post(
            f"/executions/{quote(lease.task_id, safe='')}/begin-finalization",
            {
                "execution_lease_token": lease.lease_token,
                "execution_generation": lease.generation,
            },
        )

    def finish(
        self,
        lease: RemoteExecutionLease,
        status: str,
        *,
        result_ref: str | None = None,
        error: str | None = None,
        accepted: bool | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "execution_lease_token": lease.lease_token,
            "execution_generation": lease.generation,
            "status": str(status or ""),
        }
        if result_ref is not None:
            payload["result_ref"] = str(result_ref)
        if error is not None:
            payload["error"] = str(error)
        if accepted is not None:
            payload["accepted"] = bool(accepted)
        return self._post(
            f"/executions/{quote(lease.task_id, safe='')}/finish",
            payload,
        )


def _persistable_payload(value: object) -> object:
    """Remove ephemeral transport credentials before writing debug metadata."""
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            lowered = key.lower()
            if lowered in {
                "url",
                "authorization",
                "token",
                "lease_token",
                "assignment_lease_token",
                "execution_lease_token",
            }:
                continue
            if lowered == "headers":
                # Signed headers can contain temporary authorization or
                # provider-specific credential material. Keep only their names.
                if isinstance(raw_value, Mapping):
                    sanitized["header_names"] = sorted(str(name) for name in raw_value)
                continue
            sanitized[key] = _persistable_payload(raw_value)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [_persistable_payload(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class AgentExecutionWorkdir:
    """Task-local Agent work directory with no interpretation of central paths."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _contained_directory(self, path: Path, *, create: bool) -> Path | None:
        root = self.root.resolve()
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_dir():
                raise ValueError("execution workdir contains an unsafe path component")
        elif create:
            path.mkdir()
        else:
            return None
        resolved = path.resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError("execution workdir escaped Agent state root")
        return resolved

    def path_for(self, lease: RemoteExecutionLease) -> Path:
        task_id = _safe_component(lease.task_id, "task_id")
        generation = str(int(lease.generation))
        executions = self.root / "executions"
        self._contained_directory(executions, create=True)
        task_dir = executions / task_id
        self._contained_directory(task_dir, create=True)
        target = task_dir / generation
        resolved = self._contained_directory(target, create=True)
        if resolved is None:
            raise RuntimeError("failed to create execution workdir")
        return resolved

    @staticmethod
    def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temp_path = Path(temporary)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                json.dump(dict(value), stream, ensure_ascii=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)

    def prepare(self, lease: RemoteExecutionLease) -> Path:
        target = self.path_for(lease)
        self._atomic_write_json(
            target / "request.json",
            _persistable_payload(lease.payload),
        )
        # Do not persist Node/Assignment/Execution secrets. If the Agent process
        # dies, the central lease expires and a newer generation takes over.
        self._atomic_write_json(target / "execution.json", {
            "task_id": lease.task_id,
            "kind": lease.kind,
            "project_id": lease.project_id,
            "generation": lease.generation,
            "worker_id": lease.worker_id,
            "lease_expires_at": lease.lease_expires_at,
            "assignment": lease.assignment,
            "transport": lease.transport,
        })
        return target

    @staticmethod
    def _validated_process_identity(value: object) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ValueError("persisted process identity must be an object")
        try:
            pid = int(value.get("pid"))
            create_time = float(value.get("create_time"))
        except (TypeError, ValueError) as error:
            raise ValueError("persisted process identity has invalid pid/create_time") from error
        command_hash = str(value.get("command_hash") or "").strip().lower()
        if (
            pid <= 0
            or create_time <= 0
            or not re.fullmatch(r"[0-9a-f]{64}", command_hash)
        ):
            raise ValueError("persisted process identity is incomplete")
        return {
            "pid": pid,
            "create_time": create_time,
            "command_hash": command_hash,
        }

    def persist_process_identity(
        self,
        lease: RemoteExecutionLease,
        identity,
    ) -> Path:
        target = self.path_for(lease)
        value = self._validated_process_identity({
            "pid": getattr(identity, "pid", None),
            "create_time": getattr(identity, "create_time", None),
            "command_hash": getattr(identity, "command_hash", None),
        })
        value.update({
            "task_id": str(lease.task_id),
            "generation": int(lease.generation),
        })
        path = target / "process-identity.json"
        self._atomic_write_json(path, value)
        return path

    def read_process_identity(
        self,
        lease: RemoteExecutionLease,
    ) -> dict[str, Any] | None:
        task_id = _safe_component(lease.task_id, "task_id")
        generation = str(int(lease.generation))
        executions = self._contained_directory(
            self.root / "executions",
            create=False,
        )
        if executions is None:
            return None
        task_dir = self._contained_directory(
            Path(executions) / task_id,
            create=False,
        )
        if task_dir is None:
            return None
        target = self._contained_directory(
            Path(task_dir) / generation,
            create=False,
        )
        if target is None:
            return None
        path = Path(target) / "process-identity.json"
        if not path.exists() and not path.is_symlink():
            return None
        if path.is_symlink() or not path.is_file():
            raise ValueError("persisted process identity path is unsafe")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("persisted process identity is unreadable") from error
        identity = self._validated_process_identity(raw)
        if (
            str(raw.get("task_id") or "") != task_id
            or int(raw.get("generation") or 0) != int(lease.generation)
        ):
            raise ValueError("persisted process identity lineage mismatch")
        return identity

    def clear_process_identity(self, lease: RemoteExecutionLease) -> None:
        self.clear_process_identity_record(lease.task_id, lease.generation)

    def clear_process_identity_record(
        self,
        task_id: str,
        generation: int,
    ) -> None:
        task_id = _safe_component(task_id, "task_id")
        generation = str(int(generation))
        executions = self._contained_directory(
            self.root / "executions",
            create=False,
        )
        if executions is None:
            return
        task_dir = self._contained_directory(
            Path(executions) / task_id,
            create=False,
        )
        if task_dir is None:
            return
        target = self._contained_directory(
            Path(task_dir) / generation,
            create=False,
        )
        if target is None:
            return
        path = Path(target) / "process-identity.json"
        if path.is_symlink():
            raise ValueError("persisted process identity path is unsafe")
        path.unlink(missing_ok=True)

    def list_process_identities(self) -> list[dict[str, Any]]:
        executions = self._contained_directory(
            self.root / "executions",
            create=False,
        )
        if executions is None:
            return []
        result: list[dict[str, Any]] = []
        for raw_task_dir in sorted(Path(executions).iterdir(), key=lambda item: item.name):
            if raw_task_dir.is_symlink() or not raw_task_dir.is_dir():
                raise ValueError("execution workdir contains an unsafe task directory")
            task_id = _safe_component(raw_task_dir.name, "task_id")
            task_dir = self._contained_directory(raw_task_dir, create=False)
            if task_dir is None:
                continue
            for raw_generation_dir in sorted(
                Path(task_dir).iterdir(),
                key=lambda item: item.name,
            ):
                if raw_generation_dir.is_symlink() or not raw_generation_dir.is_dir():
                    raise ValueError("execution workdir contains an unsafe generation directory")
                try:
                    generation = int(raw_generation_dir.name)
                except ValueError as error:
                    raise ValueError("execution workdir generation is invalid") from error
                if generation <= 0:
                    raise ValueError("execution workdir generation is invalid")
                generation_dir = self._contained_directory(
                    raw_generation_dir,
                    create=False,
                )
                if generation_dir is None:
                    continue
                path = Path(generation_dir) / "process-identity.json"
                if not path.exists() and not path.is_symlink():
                    continue
                if path.is_symlink() or not path.is_file():
                    raise ValueError("persisted process identity path is unsafe")
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as error:
                    raise ValueError("persisted process identity is unreadable") from error
                identity = self._validated_process_identity(raw)
                if (
                    str(raw.get("task_id") or "") != task_id
                    or int(raw.get("generation") or 0) != generation
                ):
                    raise ValueError("persisted process identity lineage mismatch")
                result.append({
                    "task_id": task_id,
                    "generation": generation,
                    **identity,
                })
        return result

    def cleanup(self, lease: RemoteExecutionLease) -> None:
        task_id = _safe_component(lease.task_id, "task_id")
        generation = str(int(lease.generation))
        executions = self._contained_directory(self.root / "executions", create=False)
        if executions is None:
            return
        task_dir = self._contained_directory(Path(executions) / task_id, create=False)
        if task_dir is None:
            return
        target = self._contained_directory(Path(task_dir) / generation, create=False)
        if target is not None:
            shutil.rmtree(target)


class ExecutionLeaseMonitor:
    """Fail-closed background lease renewal and cancellation observation."""

    def __init__(
        self,
        client: NodeExecutorClient,
        lease: RemoteExecutionLease,
        *,
        interval: float = DEFAULT_EXECUTION_HEARTBEAT_SECONDS,
        on_fenced: Callable[[], None] | None = None,
    ) -> None:
        self.client = client
        self.lease = lease
        self.interval = max(1.0, float(interval))
        self.on_fenced = on_fenced
        self.cancel_requested = threading.Event()
        self.fenced = threading.Event()
        self.stop_event = threading.Event()
        self.last_error = ""
        self._thread: threading.Thread | None = None

    def _mark_fenced(self, error: BaseException) -> None:
        self.last_error = f"{type(error).__name__}: {error}"
        self.fenced.set()
        if self.on_fenced is not None:
            try:
                self.on_fenced()
            except Exception:
                pass

    def beat(self, *, progress=None, stage=None, current_item=None) -> dict[str, Any]:
        if self.fenced.is_set():
            raise RemoteExecutionFenced(self.last_error or "remote execution is fenced")
        try:
            body = self.client.heartbeat(
                self.lease,
                progress=progress,
                stage=stage,
                current_item=current_item,
            )
        except (NodeExecutorHTTPError, requests.RequestException, OSError) as error:
            self._mark_fenced(error)
            raise RemoteExecutionFenced(self.last_error) from error
        if bool(body.get("cancel_requested")):
            self.cancel_requested.set()
        return body

    def _serve(self) -> None:
        while not self.stop_event.wait(self.interval):
            try:
                self.beat()
            except RemoteExecutionFenced:
                return

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self.stop_event.clear()
        self._thread = threading.Thread(
            target=self._serve,
            name=f"agent-execution-lease-{self.lease.task_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + 1.0)

    def assert_active(self) -> None:
        if self.fenced.is_set():
            raise RemoteExecutionFenced(self.last_error or "remote execution is fenced")
        if self.cancel_requested.is_set():
            raise InterruptedError("remote task cancellation requested")


__all__ = [
    "AgentExecutionWorkdir",
    "DEFAULT_EXECUTION_HEARTBEAT_SECONDS",
    "DEFAULT_EXECUTOR_TIMEOUT_SECONDS",
    "DEFAULT_RESULT_CONFIRM_TIMEOUT_SECONDS",
    "ExecutionLeaseMonitor",
    "NodeExecutorClient",
    "NodeExecutorHTTPError",
    "RemoteExecutionFenced",
    "RemoteExecutionLease",
]
