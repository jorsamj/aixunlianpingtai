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


def test_training_job_status_keeps_history_opt_in():
    import inspect
    import app
    signature = inspect.signature(app.job_status)
    assert signature.parameters['include_history'].default is False
    source = inspect.getsource(app.job_status)
    assert 'include_history=include_history' in source


def test_remote_training_preparation_installs_app_import_dependencies():
    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github"
        / "workflows"
        / "remote-training-runtime.yml"
    ).read_text(encoding="utf-8")
    install_step = workflow.split(
        "- name: Install focused training preparation dependencies", 1
    )[1].split("- name: Compile remote training preparation chain", 1)[0]
    assert "python-multipart" in install_step


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


def test_resource_sample_sums_unique_process_memory_not_shared_rss(tmp_path, monkeypatch):
    class Process:
        def __init__(self, uss, children=()):
            self.uss = uss
            self._children = list(children)

        def children(self, recursive=False):
            return list(self._children)

        def memory_full_info(self):
            return SimpleNamespace(uss=self.uss, pss=self.uss + 10)

        def memory_info(self):
            return SimpleNamespace(rss=2 * 1024 ** 3)

    child = Process(200 * 1024 ** 2)
    root = Process(500 * 1024 ** 2, [child])
    metrics = training_metrics.TrainingMetrics(
        tmp_path / "process-tree.sqlite3",
        resolved_resources(node_id="node-a"),
        interval=999,
        task_id="train-a",
    )
    metrics.psutil = SimpleNamespace(
        Process=lambda _pid: root,
        cpu_percent=lambda: 42.0,
        cpu_times_percent=lambda: SimpleNamespace(iowait=3.0),
        virtual_memory=lambda: SimpleNamespace(percent=61.5),
    )
    monkeypatch.setattr(training_metrics, "host_resource_snapshot", lambda: {
        "effective_available_bytes": 10 * 1024 ** 3,
        "host_total_bytes": 31 * 1024 ** 3,
        "cgroup_limit_bytes": 20 * 1024 ** 3,
        "cgroup_current_bytes": 10 * 1024 ** 3,
        "memory_source": "cgroup_v2",
    })

    metrics.sample()
    latest = training_metrics.read_metrics(metrics.path)["latest"]
    assert latest["process_tree_memory_bytes"] == 700 * 1024 ** 2
    assert latest["process_tree_peak_memory_bytes"] == 700 * 1024 ** 2
    assert latest["process_tree_memory_measure"] == "uss"
    assert latest["process_tree_count"] == 2
    assert latest["task_id"] == "train-a"
    assert latest["node_id"] == "node-a"
    assert latest["cgroup_memory_limit_bytes"] == 20 * 1024 ** 3


def test_actual_optimizer_and_initial_lr_are_captured_from_trainer_not_request(tmp_path):
    metrics=training_metrics.TrainingMetrics(tmp_path/'optimizer.sqlite3',resolved_resources(resolved_batch=4,resolved_workers=0),gpu_uuid=None,interval=999)
    metrics.psutil=None
    optimizer=type('AdamW',(),{})();optimizer.param_groups=[{'lr':.0003,'initial_lr':.002}]
    trainer=SimpleNamespace(args=SimpleNamespace(cache=False,optimizer='auto',lr0=.01),optimizer=optimizer,amp=False,
        train_loader=SimpleNamespace(batch_size=4,num_workers=0,dataset=[1,2,3,4]))
    try:
        metrics.on_train_start(trainer)
        recorded=training_metrics.read_metrics(tmp_path/'optimizer.sqlite3')
        assert recorded['runtime_optimizer']=='AdamW'
        assert recorded['runtime_initial_learning_rates']=={'lr/pg0':.002}
        assert recorded['amp_runtime_enabled'] is False
    finally:metrics.stop_event.set()
