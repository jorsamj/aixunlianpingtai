from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import platform_core.task_runtime.worker_instances as worker_instances_module
from platform_core.task_runtime import TaskRepository, WorkerInstanceService


class _TrackedConnection(sqlite3.Connection):
    closed_explicitly = False

    def close(self):
        self.closed_explicitly = True
        return super().close()


def test_worker_instance_service_has_no_plain_repository_connection_contexts():
    source = Path(worker_instances_module.__file__).read_text(encoding="utf-8")
    count = source.count("with self.repository._connect() as database:")
    assert count == 0, f"worker instance service still has {count} plain repository connection contexts"


def test_worker_instance_service_closes_connections_without_gc(tmp_path, monkeypatch):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    real_connect = sqlite3.connect
    opened: list[_TrackedConnection] = []

    def tracked_connect():
        database = real_connect(
            repository.path,
            timeout=5,
            isolation_level=None,
            factory=_TrackedConnection,
        )
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("PRAGMA synchronous=FULL")
        database.execute("PRAGMA busy_timeout=5000")
        opened.append(database)
        return database

    monkeypatch.setattr(repository, "_connect", tracked_connect)
    service = WorkerInstanceService(repository)
    lease = service.acquire(
        tmp_path / "data",
        {"training"},
        "default",
        "worker-a",
        pid=os.getpid(),
        lease_seconds=30,
    )
    lease.renew()
    assert lease.release() is True

    assert len(opened) == 3, f"expected acquire/renew/release to open 3 connections, got {len(opened)}"
    leaked = [database for database in opened if not database.closed_explicitly]
    assert leaked == [], f"{len(leaked)} worker-instance SQLite connections were left open"
