import multiprocessing as mp
import os
import sqlite3
from pathlib import Path

import pytest

import platform_core.resource_discovery.cache as cache_module
import platform_core.resource_discovery.tasks as tasks_module
from platform_core.resource_discovery.cache import DiscoveryCache
from platform_core.resource_discovery.tasks import _ModelManifest


class TrackingConnection:
    def __init__(self, connection, counters, statements):
        object.__setattr__(self, "_connection", connection)
        object.__setattr__(self, "_counters", counters)
        object.__setattr__(self, "_statements", statements)
        object.__setattr__(self, "_closed", False)

    @property
    def row_factory(self):
        return self._connection.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._connection.row_factory = value

    @property
    def in_transaction(self):
        return self._connection.in_transaction

    def __enter__(self):
        self._connection.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._connection.__exit__(exc_type, exc, tb)

    def execute(self, sql, *args, **kwargs):
        self._statements.append(str(sql).strip())
        return self._connection.execute(sql, *args, **kwargs)

    def executemany(self, sql, *args, **kwargs):
        self._statements.append(str(sql).strip())
        return self._connection.executemany(sql, *args, **kwargs)

    def executescript(self, sql, *args, **kwargs):
        self._counters["scripts"] += 1
        self._statements.append("<executescript>")
        return self._connection.executescript(sql, *args, **kwargs)

    def commit(self):
        return self._connection.commit()

    def rollback(self):
        return self._connection.rollback()

    def close(self):
        if not self._closed:
            object.__setattr__(self, "_closed", True)
            self._counters["closed"] += 1
        return self._connection.close()

    def __getattr__(self, name):
        return getattr(self._connection, name)


def _tracking_connect(real_connect, counters, statements):
    def connect(*args, **kwargs):
        counters["opened"] += 1
        return TrackingConnection(real_connect(*args, **kwargs), counters, statements)

    return connect


def _concurrent_cache_worker(path, start, queue):
    try:
        if not start.wait(15):
            raise RuntimeError("start gate timeout")
        cache = DiscoveryCache(path)
        generation = cache.next_generation("environment")
        queue.put(("ok", generation, cache.journal_mode()))
    except BaseException as error:
        queue.put(("error", type(error).__name__, str(error)))


def _count_sqlite_fds(path):
    proc_fd = Path("/proc/self/fd")
    if not proc_fd.is_dir():
        return None
    wanted = str(Path(path).resolve())
    prefixes = {wanted, wanted + "-wal", wanted + "-shm"}
    count = 0
    for fd in proc_fd.iterdir():
        try:
            target = os.readlink(fd).removesuffix(" (deleted)")
        except OSError:
            continue
        if target in prefixes:
            count += 1
    return count


def test_reopening_cache_does_not_reassert_wal_or_schema(tmp_path, monkeypatch):
    path = tmp_path / "resource-discovery.sqlite3"
    first = DiscoveryCache(path)
    assert first.journal_mode() == "wal"

    real_connect = sqlite3.connect
    counters = {"opened": 0, "closed": 0, "scripts": 0}
    statements = []
    monkeypatch.setattr(
        cache_module.sqlite3,
        "connect",
        _tracking_connect(real_connect, counters, statements),
    )

    reopened = DiscoveryCache(path)
    assert reopened.journal_mode() == "wal"
    assert counters["scripts"] == 0, "schema bootstrap must not rerun on every cache object"
    assert not any(
        statement.replace(" ", "").lower().startswith("pragmajournal_mode=wal")
        for statement in statements
    ), "WAL transition belongs only to single-owner schema initialization"
    assert counters["closed"] == counters["opened"]


def test_model_manifest_explicitly_closes_every_sqlite_connection(tmp_path, monkeypatch):
    real_connect = sqlite3.connect
    counters = {"opened": 0, "closed": 0, "scripts": 0}
    statements = []
    monkeypatch.setattr(
        tasks_module.sqlite3,
        "connect",
        _tracking_connect(real_connect, counters, statements),
    )

    manifest = _ModelManifest(tmp_path / "models.sqlite3")
    manifest.reset()
    for index in range(300):
        manifest.add({"path": str(tmp_path / f"model-{index}.onnx"), "name": f"model-{index}.onnx"})
    manifest.flush()
    assert manifest.count() == 300
    assert len(list(manifest.rows())) == 300
    assert counters["opened"] > 0
    assert counters["closed"] == counters["opened"]


def test_concurrent_cache_initialization_and_generation_allocation_is_lock_safe(tmp_path):
    path = str(tmp_path / "resource-discovery.sqlite3")
    ctx = mp.get_context("spawn")
    start = ctx.Event()
    queue = ctx.Queue()
    processes = [ctx.Process(target=_concurrent_cache_worker, args=(path, start, queue)) for _ in range(8)]
    for process in processes:
        process.start()
    start.set()

    results = [queue.get(timeout=40) for _ in processes]
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    errors = [row for row in results if row[0] != "ok"]
    assert errors == []
    generations = sorted(row[1] for row in results)
    assert generations == list(range(1, len(processes) + 1))
    assert {row[2] for row in results} == {"wal"}


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="Linux /proc FD accounting required")
def test_discovery_cache_sqlite_fd_count_does_not_grow(tmp_path):
    path = tmp_path / "resource-discovery.sqlite3"
    cache = DiscoveryCache(path)
    baseline = _count_sqlite_fds(path)
    assert baseline == 0

    for _ in range(100):
        reopened = DiscoveryCache(path)
        reopened.list_environments()
        reopened.model_count()
        reopened.metadata()

    assert _count_sqlite_fds(path) == baseline
