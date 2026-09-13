from __future__ import annotations

import gc
import sqlite3
from pathlib import Path

import pytest

from platform_core.storage import source_repository as source_repository_module
from platform_core.storage.source_repository import StorageSourceRepository


class _TrackedConnection(sqlite3.Connection):
    pass


def _connection_is_closed(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute("SELECT 1")
    except sqlite3.ProgrammingError as error:
        return "closed" in str(error).lower()
    return False


def test_storage_source_repository_source_requires_explicit_connection_owners():
    source = Path(source_repository_module.__file__).read_text(encoding="utf-8")
    assert "with self._connect() as database:" not in source


def test_storage_source_repository_explicitly_closes_connections_without_gc(tmp_path, monkeypatch):
    real_connect = source_repository_module.sqlite3.connect
    opened = []

    def tracked_connect(*args, **kwargs):
        kwargs["factory"] = _TrackedConnection
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(source_repository_module.sqlite3, "connect", tracked_connect)
    repository = StorageSourceRepository(tmp_path / "storage-sources.sqlite3")

    assert repository.journal_mode() == "wal"
    assert repository.default().id == "default_local"
    assert repository.list()

    source = repository.create({
        "id": "scratch_local",
        "name": "Scratch local",
        "type": "local",
        "config": {"root": str(tmp_path / "scratch")},
        "enabled": True,
    })
    assert repository.get(source.id) is not None
    repository.update(source.id, {"name": "Scratch local updated"})
    repository.set_default(source.id)
    repository.record_health(source.id, ok=True, message="available")
    repository.set_default("default_local")
    assert repository.delete(source.id) is True

    assert opened, "test must observe real StorageSourceRepository SQLite connections"
    leaked = [connection for connection in opened if not _connection_is_closed(connection)]
    assert leaked == [], f"{len(leaked)} StorageSourceRepository SQLite connections were left open"


def test_storage_source_repository_repeated_reads_do_not_depend_on_gc_for_fd_recovery(tmp_path):
    psutil = pytest.importorskip("psutil")
    process = psutil.Process()
    counter = getattr(process, "num_fds", None) or getattr(process, "num_handles", None)
    if counter is None:
        pytest.skip("platform does not expose a process FD/handle counter")

    repository = StorageSourceRepository(tmp_path / "storage-sources.sqlite3")
    gc.collect()
    baseline = int(counter())
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(128):
            assert repository.default().id == "default_local"
        after = int(counter())
    finally:
        if was_enabled:
            gc.enable()
        gc.collect()

    assert after - baseline <= 4, f"FD/handle growth requires GC recovery: {baseline} -> {after}"
