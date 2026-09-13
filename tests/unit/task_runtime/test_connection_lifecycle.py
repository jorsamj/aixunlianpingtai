from __future__ import annotations

import gc
import sqlite3
from pathlib import Path

import pytest

import platform_core.task_runtime.fenced_repository as fenced_repository_module
import platform_core.task_runtime.repository as repository_module
from platform_core.task_runtime import FencedTaskRepository, TaskKind, TaskRecord, TaskRepository, TaskStatus


class _TrackedConnection(sqlite3.Connection):
    closed_explicitly = False

    def close(self):
        self.closed_explicitly = True
        return super().close()


def _plain_contexts() -> dict[str, int]:
    owners = {
        "repository.py": Path(repository_module.__file__),
        "fenced_repository.py": Path(fenced_repository_module.__file__),
    }
    return {
        name: path.read_text(encoding="utf-8").count("with self._connect() as database:")
        for name, path in owners.items()
    }


def test_task_repositories_require_explicit_sqlite_connection_owners():
    plain = _plain_contexts()
    assert plain == {"repository.py": 0, "fenced_repository.py": 0}, (
        f"plain_connection_contexts={plain}"
    )


def test_task_repositories_explicitly_close_connections_without_gc(tmp_path, monkeypatch):
    real_connect = repository_module.sqlite3.connect
    opened: list[_TrackedConnection] = []

    def tracked_connect(*args, **kwargs):
        kwargs["factory"] = _TrackedConnection
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(repository_module.sqlite3, "connect", tracked_connect)

    base = TaskRepository(tmp_path / "base-tasks.sqlite3")
    base.create(
        TaskRecord.new(
            task_id="base-task",
            project_id="project-1",
            kind=TaskKind.TRAINING,
            payload_ref="payload.json",
            resource_key="gpu:base:0",
            priority=20,
            required_capabilities=("cuda",),
        )
    )
    assert base.journal_mode() == "wal"
    assert base.get("base-task") is not None
    assert base.list(project_id="project-1").items
    assert base.resource_queue_position("base-task") == 1
    base_lease = base.claim_next("base-worker", [TaskKind.TRAINING], {"cuda"})
    assert base_lease is not None
    base.heartbeat("base-task", base_lease.lease_token, progress=21, stage="training")
    base.finish("base-task", base_lease.lease_token, TaskStatus.SUCCEEDED)

    fenced = FencedTaskRepository(tmp_path / "fenced-tasks.sqlite3")
    fenced.create(
        TaskRecord.new(
            task_id="fenced-task",
            project_id="project-2",
            kind=TaskKind.TRAINING,
            payload_ref="payload.json",
            resource_key="gpu:fenced:0",
            priority=10,
            required_capabilities=("cuda",),
        )
    )
    fenced_lease = fenced.claim_next("fenced-worker", [TaskKind.TRAINING], {"cuda"})
    assert fenced_lease is not None
    generation = fenced_lease.task.attempt
    fenced.assert_execution("fenced-task", fenced_lease.lease_token, generation)
    fenced.heartbeat(
        "fenced-task",
        fenced_lease.lease_token,
        progress=33,
        execution_generation=generation,
    )
    fenced.finish(
        "fenced-task",
        fenced_lease.lease_token,
        TaskStatus.SUCCEEDED,
        execution_generation=generation,
    )

    assert opened, "test must observe real task-runtime SQLite connections"
    leaked = [connection for connection in opened if not connection.closed_explicitly]
    assert leaked == [], f"{len(leaked)} task-runtime SQLite connections were left open"


def test_task_repository_repeated_reads_do_not_depend_on_gc_for_fd_recovery(tmp_path):
    psutil = pytest.importorskip("psutil")
    process = psutil.Process()
    counter = getattr(process, "num_fds", None) or getattr(process, "num_handles", None)
    if counter is None:
        pytest.skip("platform does not expose a process FD/handle counter")

    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(
        TaskRecord.new(
            task_id="fd-task",
            project_id="project-fd",
            kind=TaskKind.TRAINING,
            payload_ref="payload.json",
            resource_key="cpu:fd",
            priority=50,
        )
    )
    gc.collect()
    baseline = int(counter())
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(128):
            assert repository.get("fd-task") is not None
        after = int(counter())
    finally:
        if was_enabled:
            gc.enable()
        gc.collect()

    assert after - baseline <= 4, f"FD/handle growth requires GC recovery: {baseline} -> {after}"
