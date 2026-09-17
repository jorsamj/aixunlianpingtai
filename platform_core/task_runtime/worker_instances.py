from __future__ import annotations

from contextlib import closing

import hashlib
import json
import os
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

import psutil

from ..node_identity import resolve_node_identity


class DuplicateWorkerInstance(RuntimeError):
    def __init__(self, worker_id: str, pid: int):
        self.worker_id = str(worker_id)
        self.pid = int(pid)
        super().__init__(f"worker instance is already active: worker_id={self.worker_id}, pid={self.pid}")


def worker_instance_key(
    data_dir: str | Path,
    roles: Iterable[str],
    slot: str = "default",
    hostname: str | None = None,
    node_id: str | None = None,
) -> str:
    payload = {
        "data_dir": os.path.normcase(str(Path(data_dir).resolve())),
        "node_id": str(node_id or hostname or socket.gethostname()).strip().casefold(),
        "roles": sorted({str(role).strip().casefold() for role in roles if str(role).strip()}),
        "slot": str(slot).strip().casefold() or "default",
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _legacy_worker_instance_key(
    data_dir: str | Path,
    roles: Iterable[str],
    slot: str,
    hostname: str,
) -> str:
    payload = {
        "data_dir": os.path.normcase(str(Path(data_dir).resolve())),
        "hostname": str(hostname).strip().casefold(),
        "roles": sorted({str(role).strip().casefold() for role in roles if str(role).strip()}),
        "slot": str(slot).strip().casefold() or "default",
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pid_is_definitely_dead(pid: int) -> bool:
    try:
        if not psutil.pid_exists(int(pid)):
            return True
        return psutil.Process(int(pid)).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True
    except (psutil.AccessDenied, OSError, ValueError):
        # Failure to inspect must never authorize takeover of a possibly-live process.
        return False


def _normalized_values(values: Iterable[object]) -> list[str]:
    normalized = {
        str(getattr(value, "value", value)).strip()
        for value in values
        if str(getattr(value, "value", value)).strip()
    }
    return sorted(normalized)


def _json_values(value: object) -> list[str]:
    try:
        decoded = json.loads(str(value or "[]"))
    except (TypeError, ValueError):
        return []
    if not isinstance(decoded, list):
        return []
    return _normalized_values(decoded)


def _utc_datetime(value: datetime | str) -> datetime | None:
    try:
        parsed = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass
class WorkerInstanceLease:
    service: "WorkerInstanceService"
    instance_key: str
    owner_token: str
    worker_id: str
    pid: int
    lease_seconds: int
    expires_at: str
    renew_hooks: list[Callable[[], None]] = field(default_factory=list, repr=False)

    def add_renew_hook(self, hook: Callable[[], None]) -> None:
        if not callable(hook):
            raise TypeError("worker renew hook must be callable")
        self.renew_hooks.append(hook)

    def renew(self) -> None:
        self.expires_at = self.service.renew(self.instance_key, self.owner_token, self.lease_seconds)
        # Observability hooks piggyback the one existing Worker heartbeat. They
        # are best-effort and may never turn a healthy Worker lease into a task
        # outage merely because cache-status reporting failed.
        for hook in tuple(self.renew_hooks):
            try:
                hook()
            except Exception:
                continue

    def release(self) -> bool:
        return self.service.release(self.instance_key, self.owner_token)


class WorkerInstanceService:
    def __init__(self, repository):
        self.repository = repository

    def acquire(
        self,
        data_dir: str | Path,
        roles: Iterable[str],
        slot: str,
        worker_id: str,
        *,
        pid: int | None = None,
        lease_seconds: int = 30,
        hostname: str | None = None,
        node_id: str | None = None,
        build_id: str = "",
        task_kinds: Iterable[object] = (),
        capabilities: Iterable[object] = (),
    ) -> WorkerInstanceLease:
        normalized_roles = _normalized_values(roles)
        normalized_task_kinds = _normalized_values(task_kinds)
        normalized_capabilities = _normalized_values(capabilities)
        runtime_hostname = str(hostname or "").strip() or socket.gethostname()
        runtime_node_id = str(node_id or "").strip() or resolve_node_identity().node_id
        instance_key = worker_instance_key(
            data_dir,
            normalized_roles,
            slot,
            hostname=runtime_hostname,
            node_id=runtime_node_id,
        )
        legacy_instance_key = _legacy_worker_instance_key(
            data_dir,
            normalized_roles,
            slot,
            runtime_hostname,
        )
        owner_token = uuid.uuid4().hex
        process_id = int(pid if pid is not None else os.getpid())
        seconds = max(3, int(lease_seconds))
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        expires_at = (now + timedelta(seconds=seconds)).isoformat()
        with closing(self.repository._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                """
                SELECT instance_key,worker_id,pid,expires_at FROM worker_instances
                 WHERE instance_key IN (?, ?)
                 ORDER BY expires_at DESC LIMIT 1
                """,
                (instance_key, legacy_instance_key),
            ).fetchone()
            if row is not None and str(row["expires_at"]) > now_text and not _pid_is_definitely_dead(int(row["pid"])):
                database.rollback()
                raise DuplicateWorkerInstance(str(row["worker_id"]), int(row["pid"]))
            database.execute(
                "DELETE FROM worker_instances WHERE instance_key IN (?, ?)",
                (instance_key, legacy_instance_key),
            )
            database.execute(
                """
                INSERT INTO worker_instances
                    (instance_key, owner_token, worker_id, node_id, pid, hostname, build_id,
                     roles, task_kinds, capabilities, started_at, heartbeat_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instance_key) DO UPDATE SET
                    owner_token=excluded.owner_token, worker_id=excluded.worker_id,
                    node_id=excluded.node_id, pid=excluded.pid, hostname=excluded.hostname,
                    build_id=excluded.build_id,
                    roles=excluded.roles, task_kinds=excluded.task_kinds,
                    capabilities=excluded.capabilities, started_at=excluded.started_at,
                    heartbeat_at=excluded.heartbeat_at, expires_at=excluded.expires_at
                """,
                (
                    instance_key,
                    owner_token,
                    str(worker_id),
                    runtime_node_id,
                    process_id,
                    runtime_hostname,
                    str(build_id).strip(),
                    json.dumps(normalized_roles, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(normalized_task_kinds, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(normalized_capabilities, ensure_ascii=False, separators=(",", ":")),
                    now_text,
                    now_text,
                    expires_at,
                ),
            )
            database.commit()
        return WorkerInstanceLease(self, instance_key, owner_token, str(worker_id), process_id, seconds, expires_at)

    def list_runtime(self, now: datetime | str | None = None) -> list[dict[str, object]]:
        current = _utc_datetime(now or datetime.now(timezone.utc))
        if current is None:
            raise ValueError("invalid runtime query timestamp")
        with closing(self.repository._connect()) as database:
            rows = database.execute(
                """
                SELECT worker_id, node_id, hostname, pid, build_id, roles, task_kinds, capabilities,
                       started_at, heartbeat_at, expires_at
                  FROM worker_instances
                 ORDER BY worker_id ASC, instance_key ASC
                """
            ).fetchall()
        try:
            from ..storage.material_cache_runtime import load_node_cache_reports

            cache_reports = load_node_cache_reports(self.repository)
        except Exception:
            # Worker runtime remains available even if optional cache
            # observability storage is absent or temporarily unreadable.
            cache_reports = {}
        result: list[dict[str, object]] = []
        for row in rows:
            heartbeat = _utc_datetime(str(row["heartbeat_at"]))
            expiry = _utc_datetime(str(row["expires_at"]))
            item: dict[str, object] = {
                "worker_id": str(row["worker_id"]),
                "node_id": str(row["node_id"]),
                "hostname": str(row["hostname"]),
                "pid": int(row["pid"]),
                "build_id": str(row["build_id"]),
                "roles": _json_values(row["roles"]),
                "task_kinds": _json_values(row["task_kinds"]),
                "capabilities": _json_values(row["capabilities"]),
                "started_at": str(row["started_at"]),
                "heartbeat_at": str(row["heartbeat_at"]),
                "expires_at": str(row["expires_at"]),
                "online": heartbeat is not None and expiry is not None and expiry > current,
            }
            cache_report = cache_reports.get(str(row["node_id"]))
            if cache_report is not None:
                item["material_cache"] = cache_report
            result.append(item)
        return result

    def renew(self, instance_key: str, owner_token: str, lease_seconds: int = 30) -> str:
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        expires_at = (now + timedelta(seconds=max(3, int(lease_seconds)))).isoformat()
        with closing(self.repository._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            changed = database.execute(
                "UPDATE worker_instances SET heartbeat_at=?, expires_at=? WHERE instance_key=? AND owner_token=?",
                (now_text, expires_at, str(instance_key), str(owner_token)),
            ).rowcount
            if changed != 1:
                database.rollback()
                raise PermissionError("worker instance lease is no longer owned")
            database.commit()
        return expires_at

    def release(self, instance_key: str, owner_token: str) -> bool:
        with closing(self.repository._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            changed = database.execute(
                "DELETE FROM worker_instances WHERE instance_key=? AND owner_token=?",
                (str(instance_key), str(owner_token)),
            ).rowcount
            database.commit()
        return changed == 1