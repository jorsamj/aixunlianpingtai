from __future__ import annotations

import hashlib
import json
import os
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import psutil


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
) -> str:
    payload = {
        "data_dir": os.path.normcase(str(Path(data_dir).resolve())),
        "hostname": (hostname or socket.gethostname()).strip().casefold(),
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


@dataclass
class WorkerInstanceLease:
    service: "WorkerInstanceService"
    instance_key: str
    owner_token: str
    worker_id: str
    pid: int
    lease_seconds: int
    expires_at: str

    def renew(self) -> None:
        self.expires_at = self.service.renew(self.instance_key, self.owner_token, self.lease_seconds)

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
    ) -> WorkerInstanceLease:
        instance_key = worker_instance_key(data_dir, roles, slot)
        owner_token = uuid.uuid4().hex
        process_id = int(pid if pid is not None else os.getpid())
        seconds = max(3, int(lease_seconds))
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        expires_at = (now + timedelta(seconds=seconds)).isoformat()
        with self.repository._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT worker_id, pid, expires_at FROM worker_instances WHERE instance_key=?",
                (instance_key,),
            ).fetchone()
            if row is not None and str(row["expires_at"]) > now_text and not _pid_is_definitely_dead(int(row["pid"])):
                database.rollback()
                raise DuplicateWorkerInstance(str(row["worker_id"]), int(row["pid"]))
            database.execute(
                """
                INSERT INTO worker_instances
                    (instance_key, owner_token, worker_id, pid, started_at, heartbeat_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instance_key) DO UPDATE SET
                    owner_token=excluded.owner_token, worker_id=excluded.worker_id,
                    pid=excluded.pid, started_at=excluded.started_at,
                    heartbeat_at=excluded.heartbeat_at, expires_at=excluded.expires_at
                """,
                (instance_key, owner_token, str(worker_id), process_id, now_text, now_text, expires_at),
            )
            database.commit()
        return WorkerInstanceLease(self, instance_key, owner_token, str(worker_id), process_id, seconds, expires_at)

    def renew(self, instance_key: str, owner_token: str, lease_seconds: int = 30) -> str:
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        expires_at = (now + timedelta(seconds=max(3, int(lease_seconds)))).isoformat()
        with self.repository._connect() as database:
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
        with self.repository._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            changed = database.execute(
                "DELETE FROM worker_instances WHERE instance_key=? AND owner_token=?",
                (str(instance_key), str(owner_token)),
            ).rowcount
            database.commit()
        return changed == 1
