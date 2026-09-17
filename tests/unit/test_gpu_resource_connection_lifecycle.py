from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import platform_core.gpu_resources as gpu_module
from platform_core.gpu_resources import GPUResourceManager, update_reservation_evidence
from platform_core.task_runtime import TaskRepository


class _TrackedConnection(sqlite3.Connection):
    closed_explicitly = False

    def close(self):
        self.closed_explicitly = True
        return super().close()


class _Artifacts:
    def read_json(self, task_id, relative_path, default=None):
        return {"device": "cuda:0"}


def test_gpu_resource_manager_has_no_plain_repository_connection_contexts():
    source = Path(gpu_module.__file__).read_text(encoding="utf-8")
    direct = source.count("with repository._connect() as database:")
    owned = source.count("with self.repository._connect() as database:")
    assert direct == 0 and owned == 0, (
        f"GPU resource owner still has {direct + owned} plain repository connection contexts "
        f"(direct={direct}, owned={owned})"
    )


def test_gpu_resource_paths_close_connections_without_gc(tmp_path, monkeypatch):
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
    manager = GPUResourceManager(repository, _Artifacts(), sampler=lambda _python: [])

    manager.refresh()
    manager.summary()

    lease = SimpleNamespace(
        task=SimpleNamespace(task_id="gpu-lifecycle", payload_ref="payload.json"),
        lease_token="lease-token",
        worker_id="worker-a",
    )
    update_reservation_evidence(
        repository,
        lease,
        {
            "sampled_at": datetime.now(timezone.utc).isoformat(),
            "diagnostic": {},
        },
    )
    with pytest.raises(EnvironmentError, match="reservation"):
        manager.assignment(lease)

    assert len(opened) == 4, f"expected four GPU resource DB paths, got {len(opened)}"
    leaked = [database for database in opened if not database.closed_explicitly]
    assert leaked == [], f"{len(leaked)} GPU resource SQLite connections were left open"
