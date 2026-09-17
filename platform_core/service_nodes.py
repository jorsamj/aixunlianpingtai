"""Authoritative service-node registry and authenticated Agent heartbeat contract.

The central control plane owns desired node state.  Agents only report observed
runtime/resource truth; they never make scheduling decisions from this module.
The registry deliberately shares the durable TaskRepository database so future
central task assignment can be transactional with queue state without creating a
second scheduler or a SQLite-over-NFS side database.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Mapping

from .task_runtime import WorkerInstanceService
from .task_runtime.models import utc_now


SUPPORTED_NODE_CAPABILITIES = (
    "training",
    "material-import",
    "cleaning",
    "annotation",
    "video",
    "conversion",
    "deployment-test",
    "model-upload",
)
HEARTBEAT_TTL_SECONDS = 45
_NODE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CAPABILITY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS service_nodes (
    node_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    connection_mode TEXT NOT NULL CHECK(connection_mode IN ('local','agent')),
    agent_url TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    allowed_capabilities TEXT NOT NULL DEFAULT '[]',
    token_hash TEXT NOT NULL,
    token_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_heartbeat_at TEXT,
    hostname TEXT NOT NULL DEFAULT '',
    os_name TEXT NOT NULL DEFAULT '',
    os_version TEXT NOT NULL DEFAULT '',
    architecture TEXT NOT NULL DEFAULT '',
    agent_version TEXT NOT NULL DEFAULT '',
    build_id TEXT NOT NULL DEFAULT '',
    reported_capabilities TEXT NOT NULL DEFAULT '[]',
    resource_json TEXT NOT NULL DEFAULT '{}',
    runtime_json TEXT NOT NULL DEFAULT '{}',
    process_json TEXT NOT NULL DEFAULT '{}',
    active_tasks_json TEXT NOT NULL DEFAULT '[]',
    last_error TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_service_nodes_enabled_heartbeat
    ON service_nodes(enabled,last_heartbeat_at);
"""


class ServiceNodeError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = str(code)
        self.status_code = int(status_code)
        super().__init__(str(message))


def _text(value: object, *, field: str, limit: int, required: bool = False) -> str:
    normalized = str(value or "").strip()
    if required and not normalized:
        raise ServiceNodeError("NODE_FIELD_REQUIRED", f"{field} is required", 422)
    if len(normalized) > limit:
        raise ServiceNodeError("NODE_FIELD_TOO_LONG", f"{field} exceeds {limit} characters", 422)
    return normalized


def _node_id(value: object) -> str:
    normalized = _text(value, field="node_id", limit=128, required=True)
    if not _NODE_ID_PATTERN.fullmatch(normalized):
        raise ServiceNodeError(
            "INVALID_NODE_ID",
            "node_id must use letters, digits, '.', '_', ':', or '-'",
            422,
        )
    return normalized


def _capabilities(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise ServiceNodeError("INVALID_NODE_CAPABILITIES", "capabilities must be an array", 422)
    normalized = tuple(sorted({str(item or "").strip().lower() for item in value if str(item or "").strip()}))
    unknown = [item for item in normalized if item not in SUPPORTED_NODE_CAPABILITIES]
    if unknown:
        raise ServiceNodeError(
            "UNSUPPORTED_NODE_CAPABILITY",
            "unsupported node capabilities: " + ", ".join(unknown),
            422,
        )
    if any(not _CAPABILITY_PATTERN.fullmatch(item) for item in normalized):
        raise ServiceNodeError("INVALID_NODE_CAPABILITIES", "invalid capability name", 422)
    return normalized


def _json_array(value: object, *, field: str, limit: int = 256) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ServiceNodeError("INVALID_NODE_HEARTBEAT", f"{field} must be an array", 422)
    if len(value) > limit:
        raise ServiceNodeError("INVALID_NODE_HEARTBEAT", f"{field} exceeds {limit} items", 422)
    return [
        _text(item, field=field, limit=160, required=True)
        for item in value
    ]


def _json_mapping(value: object, *, field: str, max_bytes: int = 131072) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ServiceNodeError("INVALID_NODE_HEARTBEAT", f"{field} must be an object", 422)
    result = dict(value)
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > max_bytes:
        raise ServiceNodeError("INVALID_NODE_HEARTBEAT", f"{field} exceeds {max_bytes} bytes", 422)
    return result


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(value: object, fallback):
    try:
        decoded = json.loads(str(value or ""))
    except (TypeError, ValueError):
        return fallback
    return decoded


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _token_hash(node_id: str, token: str) -> str:
    return hashlib.sha256(f"service-node:v1:{node_id}:{token}".encode("utf-8")).hexdigest()


def _new_token(node_id: str) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, _token_hash(node_id, token)


class ServiceNodeRepository:
    def __init__(self, task_repository, *, heartbeat_ttl_seconds: int = HEARTBEAT_TTL_SECONDS):
        self.task_repository = task_repository
        self.heartbeat_ttl_seconds = max(10, int(heartbeat_ttl_seconds))
        with closing(self.task_repository._connect()) as database:
            database.executescript(_SCHEMA)

    def _row(self, node_id: str):
        with closing(self.task_repository._connect()) as database:
            return database.execute(
                "SELECT * FROM service_nodes WHERE node_id=?",
                (_node_id(node_id),),
            ).fetchone()

    def _require_row(self, node_id: str):
        row = self._row(node_id)
        if row is None:
            raise ServiceNodeError("SERVICE_NODE_NOT_FOUND", "service node not found", 404)
        return row

    def _runtime_projection(self, now: datetime | None = None) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]]:
        workers = WorkerInstanceService(self.task_repository).list_runtime(now=now or datetime.now(timezone.utc))
        workers_by_node: dict[str, list[dict[str, Any]]] = {}
        worker_to_node: dict[str, str] = {}
        for worker in workers:
            node = str(worker.get("node_id") or "")
            if not node:
                continue
            workers_by_node.setdefault(node, []).append(worker)
            worker_to_node[str(worker.get("worker_id") or "")] = node
        tasks_by_node: dict[str, list[dict[str, Any]]] = {}
        if worker_to_node:
            with closing(self.task_repository._connect()) as database:
                rows = database.execute(
                    """
                    SELECT task_id,kind,status,stage,progress,worker_id,lease_expires_at
                      FROM tasks
                     WHERE status IN ('RUNNING','CANCEL_REQUESTED') AND worker_id IS NOT NULL
                     ORDER BY updated_at ASC, task_id ASC
                    """
                ).fetchall()
            for row in rows:
                node = worker_to_node.get(str(row["worker_id"] or ""))
                if node is None:
                    continue
                tasks_by_node.setdefault(node, []).append({
                    "task_id": str(row["task_id"]),
                    "kind": str(row["kind"]),
                    "status": str(row["status"]),
                    "stage": str(row["stage"]),
                    "progress": float(row["progress"] or 0.0),
                    "worker_id": str(row["worker_id"]),
                    "lease_expires_at": row["lease_expires_at"],
                })
        return workers_by_node, tasks_by_node

    def _public_row(
        self,
        row,
        *,
        now: datetime,
        workers: list[dict[str, Any]] | None = None,
        durable_tasks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        heartbeat = _parse_time(row["last_heartbeat_at"])
        age = None if heartbeat is None else max(0.0, (now - heartbeat).total_seconds())
        reachable = age is not None and age <= self.heartbeat_ttl_seconds
        enabled = bool(row["enabled"])
        if not enabled:
            status = "DISABLED"
        elif heartbeat is None:
            status = "NEVER_CONNECTED"
        elif reachable:
            status = "ONLINE"
        else:
            status = "OFFLINE"
        allowed = tuple(_json_loads(row["allowed_capabilities"], []))
        reported = tuple(_json_loads(row["reported_capabilities"], []))
        effective = sorted(set(allowed) & set(reported)) if enabled and reachable else []
        return {
            "node_id": str(row["node_id"]),
            "display_name": str(row["display_name"]),
            "connection_mode": str(row["connection_mode"]),
            "agent_url": str(row["agent_url"]),
            "enabled": enabled,
            "status": status,
            "online": bool(enabled and reachable),
            "reachable": bool(reachable),
            "heartbeat_age_seconds": age,
            "heartbeat_ttl_seconds": self.heartbeat_ttl_seconds,
            "allowed_capabilities": list(allowed),
            "reported_capabilities": list(reported),
            "effective_capabilities": effective,
            "token_version": int(row["token_version"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "last_heartbeat_at": row["last_heartbeat_at"],
            "hostname": str(row["hostname"]),
            "os_name": str(row["os_name"]),
            "os_version": str(row["os_version"]),
            "architecture": str(row["architecture"]),
            "agent_version": str(row["agent_version"]),
            "build_id": str(row["build_id"]),
            "resources": _json_loads(row["resource_json"], {}),
            "runtime": _json_loads(row["runtime_json"], {}),
            "process": _json_loads(row["process_json"], {}),
            "reported_active_tasks": _json_loads(row["active_tasks_json"], []),
            "last_error": str(row["last_error"] or ""),
            "workers": list(workers or []),
            "durable_tasks": list(durable_tasks or []),
        }

    def list_public(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        current = now or datetime.now(timezone.utc)
        with closing(self.task_repository._connect()) as database:
            rows = database.execute(
                "SELECT * FROM service_nodes ORDER BY display_name COLLATE NOCASE ASC, node_id ASC"
            ).fetchall()
        workers_by_node, tasks_by_node = self._runtime_projection(current)
        return [
            self._public_row(
                row,
                now=current,
                workers=workers_by_node.get(str(row["node_id"]), []),
                durable_tasks=tasks_by_node.get(str(row["node_id"]), []),
            )
            for row in rows
        ]

    def get_public(self, node_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        row = self._require_row(node_id)
        workers_by_node, tasks_by_node = self._runtime_projection(current)
        key = str(row["node_id"])
        return self._public_row(
            row,
            now=current,
            workers=workers_by_node.get(key, []),
            durable_tasks=tasks_by_node.get(key, []),
        )

    def create(self, payload: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
        body = dict(payload or {})
        node_id = _node_id(body.get("node_id"))
        display_name = _text(body.get("display_name") or node_id, field="display_name", limit=120, required=True)
        mode = _text(body.get("connection_mode") or "agent", field="connection_mode", limit=16, required=True).lower()
        if mode not in {"local", "agent"}:
            raise ServiceNodeError("INVALID_CONNECTION_MODE", "connection_mode must be local or agent", 422)
        agent_url = _text(body.get("agent_url"), field="agent_url", limit=1000)
        capabilities = _capabilities(body.get("allowed_capabilities"))
        token, token_hash = _new_token(node_id)
        now = utc_now()
        try:
            with closing(self.task_repository._connect()) as database:
                database.execute("BEGIN IMMEDIATE")
                database.execute(
                    """
                    INSERT INTO service_nodes
                        (node_id,display_name,connection_mode,agent_url,enabled,allowed_capabilities,
                         token_hash,token_version,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        node_id,
                        display_name,
                        mode,
                        agent_url,
                        int(bool(body.get("enabled", True))),
                        _json_dumps(capabilities),
                        token_hash,
                        1,
                        now,
                        now,
                    ),
                )
                database.commit()
        except sqlite3.IntegrityError as error:
            raise ServiceNodeError("SERVICE_NODE_EXISTS", "service node already exists", 409) from error
        return self.get_public(node_id), token

    def update(self, node_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = dict(payload or {})
        self._require_row(node_id)
        updates: list[str] = []
        values: list[object] = []
        if "display_name" in body:
            updates.append("display_name=?")
            values.append(_text(body.get("display_name"), field="display_name", limit=120, required=True))
        if "connection_mode" in body:
            mode = _text(body.get("connection_mode"), field="connection_mode", limit=16, required=True).lower()
            if mode not in {"local", "agent"}:
                raise ServiceNodeError("INVALID_CONNECTION_MODE", "connection_mode must be local or agent", 422)
            updates.append("connection_mode=?")
            values.append(mode)
        if "agent_url" in body:
            updates.append("agent_url=?")
            values.append(_text(body.get("agent_url"), field="agent_url", limit=1000))
        if "enabled" in body:
            updates.append("enabled=?")
            values.append(int(bool(body.get("enabled"))))
        if "allowed_capabilities" in body:
            updates.append("allowed_capabilities=?")
            values.append(_json_dumps(_capabilities(body.get("allowed_capabilities"))))
        if not updates:
            return self.get_public(node_id)
        updates.append("updated_at=?")
        values.append(utc_now())
        values.append(_node_id(node_id))
        with closing(self.task_repository._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            database.execute(
                f"UPDATE service_nodes SET {','.join(updates)} WHERE node_id=?",
                values,
            )
            database.commit()
        return self.get_public(node_id)

    def rotate_token(self, node_id: str) -> tuple[dict[str, Any], str]:
        key = _node_id(node_id)
        row = self._require_row(key)
        token, token_hash = _new_token(key)
        version = int(row["token_version"]) + 1
        now = utc_now()
        with closing(self.task_repository._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            database.execute(
                "UPDATE service_nodes SET token_hash=?,token_version=?,updated_at=? WHERE node_id=?",
                (token_hash, version, now, key),
            )
            database.commit()
        return self.get_public(key), token

    def heartbeat(self, node_id: str, token: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        key = _node_id(node_id)
        row = self._require_row(key)
        supplied = _text(token, field="agent_token", limit=512, required=True)
        if not hmac.compare_digest(str(row["token_hash"]), _token_hash(key, supplied)):
            raise ServiceNodeError("INVALID_NODE_TOKEN", "invalid service node token", 401)
        body = dict(payload or {})
        capabilities = _capabilities(body.get("reported_capabilities"))
        resources = _json_mapping(body.get("resources"), field="resources")
        runtime = _json_mapping(body.get("runtime"), field="runtime")
        process = _json_mapping(body.get("process"), field="process")
        active_tasks = _json_array(body.get("active_tasks"), field="active_tasks")
        now = utc_now()
        with closing(self.task_repository._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            database.execute(
                """
                UPDATE service_nodes
                   SET last_heartbeat_at=?,updated_at=?,hostname=?,os_name=?,os_version=?,architecture=?,
                       agent_version=?,build_id=?,reported_capabilities=?,resource_json=?,runtime_json=?,
                       process_json=?,active_tasks_json=?,last_error=?
                 WHERE node_id=?
                """,
                (
                    now,
                    now,
                    _text(body.get("hostname"), field="hostname", limit=255),
                    _text(body.get("os_name"), field="os_name", limit=120),
                    _text(body.get("os_version"), field="os_version", limit=255),
                    _text(body.get("architecture"), field="architecture", limit=120),
                    _text(body.get("agent_version"), field="agent_version", limit=120),
                    _text(body.get("build_id"), field="build_id", limit=255),
                    _json_dumps(capabilities),
                    _json_dumps(resources),
                    _json_dumps(runtime),
                    _json_dumps(process),
                    _json_dumps(active_tasks),
                    _text(body.get("last_error"), field="last_error", limit=4000),
                    key,
                ),
            )
            database.commit()
        return self.get_public(key)

    def delete(self, node_id: str) -> None:
        key = _node_id(node_id)
        self._require_row(key)
        now = utc_now()
        with closing(self.task_repository._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            live_workers = int(database.execute(
                "SELECT COUNT(*) FROM worker_instances WHERE node_id=? AND expires_at>?",
                (key, now),
            ).fetchone()[0])
            active_tasks = int(database.execute(
                """
                SELECT COUNT(*) FROM tasks
                 WHERE status IN ('RUNNING','CANCEL_REQUESTED')
                   AND worker_id IN (SELECT worker_id FROM worker_instances WHERE node_id=?)
                """,
                (key,),
            ).fetchone()[0])
            if live_workers or active_tasks:
                database.rollback()
                raise ServiceNodeError(
                    "SERVICE_NODE_BUSY",
                    "disable the node and wait for active workers/tasks to stop before deleting it",
                    409,
                )
            database.execute("DELETE FROM service_nodes WHERE node_id=?", (key,))
            database.commit()


def _bearer_token(value: object) -> str:
    text = str(value or "").strip()
    if not text.lower().startswith("bearer "):
        raise ServiceNodeError("NODE_TOKEN_REQUIRED", "Bearer service node token is required", 401)
    token = text[7:].strip()
    if not token:
        raise ServiceNodeError("NODE_TOKEN_REQUIRED", "Bearer service node token is required", 401)
    return token


def service_node_router(task_repository):
    from fastapi import APIRouter, Body, Header, HTTPException

    router = APIRouter(prefix="/api/v63/service-nodes")

    def registry() -> ServiceNodeRepository:
        return ServiceNodeRepository(task_repository())

    def invoke(function, *args):
        try:
            return function(*args)
        except ServiceNodeError as error:
            raise HTTPException(
                status_code=error.status_code,
                detail={"code": error.code, "message": str(error)},
            ) from error

    @router.get("/capabilities")
    def capabilities():
        return {"items": list(SUPPORTED_NODE_CAPABILITIES)}

    @router.get("")
    def list_nodes():
        return {"items": registry().list_public(), "supported_capabilities": list(SUPPORTED_NODE_CAPABILITIES)}

    @router.post("", status_code=201)
    def create_node(payload: dict = Body(...)):
        node, token = invoke(registry().create, payload)
        return {"node": node, "agent_token": token, "token_version": node["token_version"]}

    @router.get("/{node_id}")
    def get_node(node_id: str):
        return invoke(registry().get_public, node_id)

    @router.patch("/{node_id}")
    def update_node(node_id: str, payload: dict = Body(...)):
        return invoke(registry().update, node_id, payload)

    @router.delete("/{node_id}")
    def delete_node(node_id: str):
        invoke(registry().delete, node_id)
        return {"ok": True, "node_id": node_id}

    @router.post("/{node_id}/rotate-token")
    def rotate_node_token(node_id: str):
        node, token = invoke(registry().rotate_token, node_id)
        return {"node": node, "agent_token": token, "token_version": node["token_version"]}

    @router.post("/{node_id}/heartbeat")
    def node_heartbeat(
        node_id: str,
        payload: dict = Body(...),
        authorization: str | None = Header(default=None),
    ):
        try:
            token = _bearer_token(authorization)
        except ServiceNodeError as error:
            raise HTTPException(
                status_code=error.status_code,
                detail={"code": error.code, "message": str(error)},
            ) from error
        node = invoke(registry().heartbeat, node_id, token, payload)
        return {
            "ok": True,
            "node": node,
            "desired": {
                "enabled": node["enabled"],
                "allowed_capabilities": node["allowed_capabilities"],
            },
        }

    return router


__all__ = [
    "HEARTBEAT_TTL_SECONDS",
    "SUPPORTED_NODE_CAPABILITIES",
    "ServiceNodeError",
    "ServiceNodeRepository",
    "service_node_router",
]
