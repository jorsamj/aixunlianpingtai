import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

import platform_core.training_metrics as training_metrics


def test_detail_metrics_history_is_bounded_chronological_and_summary_default_stays_small(tmp_path):
    import json
    database = tmp_path / "metrics.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE summary(id INTEGER PRIMARY KEY,value TEXT)")
        db.execute("INSERT INTO summary VALUES(1,?)", (json.dumps({"images_per_second":12}),))
        for table in ("epochs", "samples"):
            db.execute(f"CREATE TABLE {table}(id INTEGER PRIMARY KEY,value TEXT)")
            db.executemany(f"INSERT INTO {table} VALUES(?,?)",
                           [(i, json.dumps({"epoch":i})) for i in range(1,1101)])
    assert training_metrics.read_metrics(database) == {"images_per_second":12}
    result = training_metrics.read_metrics(database, include_history=True)
    assert len(result["epochs"]) == 1000
    assert result["epochs"][0]["epoch"] == 101
    assert result["epochs"][-1]["epoch"] == 1100
    assert len(result["samples"]) == 720
    assert result["samples"][0]["epoch"] == 381


class TrackingConnection:
    def __init__(self, connection, counters):
        self._connection = connection
        self._counters = counters
        self._closed = False

    def __enter__(self):
        self._connection.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._connection.__exit__(exc_type, exc, tb)

    def close(self):
        if not self._closed:
            self._closed = True
            self._counters["closed"] += 1
        return self._connection.close()

    def __getattr__(self, name):
        return getattr(self._connection, name)


def resolved_resources(**overrides):
    value = {
        "resolved_batch": 4,
        "resolved_workers": 0,
        "resolved_cache": False,
    }
    value.update(overrides)
    return value


def test_training_metrics_closes_every_sqlite_connection(tmp_path, monkeypatch):
    db_path = tmp_path / "training-metrics.sqlite3"
    real_connect = sqlite3.connect
    counters = {"opened": 0, "closed": 0}

    def tracked_connect(*args, **kwargs):
        counters["opened"] += 1
        return TrackingConnection(real_connect(*args, **kwargs), counters)

    monkeypatch.setattr(training_metrics.sqlite3, "connect", tracked_connect)

    metrics = training_metrics.TrainingMetrics(
        db_path,
        resolved_resources(),
        gpu_uuid=None,
        interval=999,
    )
    metrics.psutil = None

    for _ in range(25):
        metrics.sample()

    trainer = SimpleNamespace(
        epoch=0,
        train_loader=SimpleNamespace(dataset=[1, 2, 3, 4]),
    )
    metrics.on_epoch_end(trainer)

    for _ in range(25):
        summary = training_metrics.read_metrics(db_path)
        assert summary["resolved_batch"] == 4

    assert counters["opened"] == 52
    assert counters["closed"] == counters["opened"]


def _count_open_fds_for(path):
    proc_fd = Path("/proc/self/fd")
    if not proc_fd.is_dir():
        return None
    wanted = str(Path(path).resolve())
    count = 0
    for fd in proc_fd.iterdir():
        try:
            target = os.readlink(fd)
        except OSError:
            continue
        if target.removesuffix(" (deleted)") == wanted:
            count += 1
    return count


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="Linux /proc FD accounting required")
def test_training_metrics_sqlite_fd_count_does_not_grow(tmp_path):
    db_path = tmp_path / "training-metrics.sqlite3"
    metrics = training_metrics.TrainingMetrics(
        db_path,
        resolved_resources(),
        gpu_uuid=None,
        interval=999,
    )
    metrics.psutil = None

    baseline = _count_open_fds_for(db_path)
    assert baseline == 0

    for _ in range(100):
        metrics.sample()
        assert training_metrics.read_metrics(db_path)["resolved_batch"] == 4

    assert _count_open_fds_for(db_path) == baseline


def test_runtime_truth_reads_effective_train_loader_not_trainer_batch_size(tmp_path):
    metrics = training_metrics.TrainingMetrics(
        tmp_path / "runtime-truth.sqlite3",
        resolved_resources(resolved_batch=11, resolved_workers=0),
        gpu_uuid=None,
        interval=999,
    )
    metrics.psutil = None
    trainer = SimpleNamespace(
        batch_size=100,
        args=SimpleNamespace(cache=False),
        train_loader=SimpleNamespace(
            batch_size=11,
            num_workers=0,
            dataset=[object()] * 11,
        ),
    )

    runtime = metrics.on_train_start(trainer)

    assert runtime == {
        "runtime_batch": 11,
        "runtime_workers": 0,
        "runtime_cache": False,
    }
    assert metrics.resolved["runtime_batch"] == 11
    assert metrics.resolved["runtime_workers"] == 0


def test_resource_runtime_mismatch_guard_still_fails_closed(tmp_path):
    metrics = training_metrics.TrainingMetrics(
        tmp_path / "runtime-mismatch.sqlite3",
        resolved_resources(resolved_batch=11, resolved_workers=0),
        gpu_uuid=None,
        interval=999,
    )
    metrics.psutil = None
    trainer = SimpleNamespace(
        batch_size=100,
        args=SimpleNamespace(cache=False),
        train_loader=SimpleNamespace(
            batch_size=10,
            num_workers=0,
            dataset=[object()] * 11,
        ),
    )

    with pytest.raises(RuntimeError, match="RESOURCE_RUNTIME_MISMATCH"):
        metrics.on_train_start(trainer)


def test_runtime_worker_truth_comes_from_train_loader(tmp_path):
    metrics = training_metrics.TrainingMetrics(
        tmp_path / "runtime-workers.sqlite3",
        resolved_resources(resolved_batch=50, resolved_workers=2),
        gpu_uuid=None,
        interval=999,
    )
    metrics.psutil = None
    trainer = SimpleNamespace(
        batch_size=100,
        args=SimpleNamespace(cache=False),
        train_loader=SimpleNamespace(
            batch_size=50,
            num_workers=2,
            dataset=[object()] * 100,
        ),
    )

    runtime = metrics.on_train_start(trainer)

    assert runtime["runtime_batch"] == 50
    assert runtime["runtime_workers"] == 2


def test_resource_sample_records_system_memory_without_guessing(tmp_path):
    metrics = training_metrics.TrainingMetrics(
        tmp_path / "system-memory.sqlite3",
        resolved_resources(),
        gpu_uuid=None,
        interval=999,
    )
    metrics.psutil = SimpleNamespace(
        cpu_percent=lambda: 42.0,
        cpu_times_percent=lambda: SimpleNamespace(iowait=3.0),
        virtual_memory=lambda: SimpleNamespace(percent=61.5),
    )
    metrics.sample()
    result = training_metrics.read_metrics(metrics.path, include_history=True)
    assert result["latest"]["memory_percent"] == 61.5
    assert result["samples"][-1]["memory_percent"] == 61.5
