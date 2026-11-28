import sqlite3
import threading
import time

import pytest

from platform_core.task_runtime import ArtifactStore, Scheduler, TaskKind, TaskRecord, TaskStatus
from platform_core.task_runtime.fenced_repository import FencedTaskRepository
from platform_core.task_runtime.worker import WorkerContext, ExecutionFencedError
from platform_core.task_runtime.worker_instances import WorkerInstanceService


def fixture(tmp_path, monkeypatch, lease_seconds=3):
    repo = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    repo.create(TaskRecord.new("busy-task", "project", TaskKind.VIDEO_FRAMES, "payload.json", "cpu:1"))
    lease = repo.claim_next("worker", [TaskKind.VIDEO_FRAMES], set(), lease_seconds)
    connect = repo._connect
    def short_connect():
        db = connect()
        db.execute("PRAGMA busy_timeout=30")
        return db
    monkeypatch.setattr(repo, "_connect", short_connect)
    context = WorkerContext(lease.task, lease, repo, ArtifactStore(tmp_path / "artifacts"), lease_seconds=lease_seconds)
    return repo, context


def test_nested_ownership_read_busy_is_retried_not_fenced(tmp_path, monkeypatch):
    repo, context = fixture(tmp_path, monkeypatch)
    get = repo.assert_execution
    calls = []
    def transient_get(task_id, *args):
        calls.append(task_id)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        return get(task_id, *args)
    monkeypatch.setattr(repo, "assert_execution", transient_get)
    context.heartbeat()
    assert len(calls) >= 2
    assert not context.lease_lost


@pytest.mark.parametrize("bind", [True, False])
def test_real_training_child_cannot_execute_until_durable_binding(tmp_path, monkeypatch, bind):
    import os
    import subprocess
    import sys
    from platform_core.task_runtime.process_start_gate import execution_environment
    from platform_core.task_runtime.process_control import launch_process
    repo, context = fixture(tmp_path, monkeypatch, lease_seconds=2)
    marker = tmp_path / "training-started"
    argv = [sys.executable, "-c", "from platform_core.task_runtime.process_start_gate import wait_for_execution_binding; "
            "wait_for_execution_binding(); from pathlib import Path; Path(__import__('sys').argv[1]).write_text('started')", str(marker)]
    launched = launch_process(argv, env={**os.environ, **execution_environment(context)},
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(.2)
        assert not marker.exists()
        if bind:
            context.bind_process(launched.identity)
        launched.process.wait(timeout=4)
        assert marker.exists() is bind
        assert (launched.process.returncode == 0) is bind
    finally:
        if launched.process.poll() is None:
            launched.process.kill()
        launched.process.wait(timeout=3)


def test_short_real_writer_lock_does_not_lose_execution(tmp_path, monkeypatch):
    repo, context = fixture(tmp_path, monkeypatch)
    errors, results = [], []
    db = sqlite3.connect(repo.path, isolation_level=None)
    db.execute("BEGIN IMMEDIATE")
    def renew():
        try:
            results.append(context.heartbeat())
        except Exception as error:
            errors.append(error)
    thread = threading.Thread(target=renew)
    thread.start()
    time.sleep(.22)
    db.rollback(); db.close()
    thread.join(3)
    assert not thread.is_alive()
    assert errors == []
    assert results[0].worker_id == "worker"
    assert not context.lease_lost


def test_instance_renew_recovers_short_real_lock(tmp_path, monkeypatch):
    repo, _ = fixture(tmp_path, monkeypatch)
    lease = WorkerInstanceService(repo).acquire(tmp_path, ["video"], "slot", "worker", lease_seconds=3)
    db = sqlite3.connect(repo.path, isolation_level=None); db.execute("BEGIN IMMEDIATE")
    errors = []
    def renew():
        try: lease.renew()
        except Exception as error: errors.append(error)
    thread = threading.Thread(target=renew); thread.start()
    time.sleep(.22); db.rollback(); db.close(); thread.join(3)
    assert errors == []
    assert lease.expires_at


def test_expired_instance_cannot_renew_itself(tmp_path, monkeypatch):
    repo, _ = fixture(tmp_path, monkeypatch)
    lease = WorkerInstanceService(repo).acquire(tmp_path, ["video"], "slot", "worker", lease_seconds=3)
    db = repo._connect()
    db.execute("UPDATE worker_instances SET expires_at='2000-01-01T00:00:00+00:00'")
    db.close()
    with pytest.raises(PermissionError): lease.renew()


def test_release_expired_does_not_inspect_process_while_holding_writer(tmp_path, monkeypatch):
    repo, context = fixture(tmp_path, monkeypatch)
    db = repo._connect()
    db.execute("UPDATE tasks SET process_pid=123,process_create_time=1,process_command_hash='identity',lease_expires_at='2000-01-01T00:00:00+00:00'")
    db.close()
    inspected = []
    def inspect(_identity):
        other = sqlite3.connect(repo.path, timeout=.03, isolation_level=None)
        try:
            other.execute("BEGIN IMMEDIATE")
            inspected.append(True)
            other.rollback()
        except sqlite3.OperationalError:
            inspected.append(False)
        finally: other.close()
        raise ProcessLookupError("isolated expired process is gone")
    monkeypatch.setattr("platform_core.task_runtime.fenced_repository.ProcessController.inspect", lambda self, identity: inspect(identity))
    repo.release_expired()
    assert inspected == [True]
    assert repo.get(context.task.task_id).status is TaskStatus.QUEUED


def test_worker_loop_survives_busy_but_not_programming_errors(tmp_path, monkeypatch):
    repo, _ = fixture(tmp_path, monkeypatch)
    stop = threading.Event()
    calls = []
    scheduler = Scheduler(repo, ArtifactStore(tmp_path / "artifacts"), "worker", {}, set())
    def run():
        calls.append(1)
        if len(calls) == 1: raise sqlite3.OperationalError("database is locked")
        stop.set()
        return False
    monkeypatch.setattr(scheduler, "run_once", run)
    scheduler.serve_forever(stop)
    assert len(calls) == 2
    monkeypatch.setattr(scheduler, "run_once", lambda: (_ for _ in ()).throw(sqlite3.OperationalError("no such table: deliberate_error")))
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        scheduler.serve_forever(threading.Event())


def test_long_lock_fences_before_confirmed_lease_expires(tmp_path, monkeypatch):
    repo, context = fixture(tmp_path, monkeypatch)
    original_deadline = context._confirmed_deadline
    db = sqlite3.connect(repo.path, isolation_level=None); db.execute("BEGIN IMMEDIATE")
    started = time.monotonic()
    try:
        with pytest.raises(ExecutionFencedError): context.heartbeat()
    finally:
        db.rollback(); db.close()
    assert context.lease_lost
    assert context._confirmed_deadline == original_deadline
    assert time.monotonic() <= original_deadline + .05
    assert .5 < time.monotonic() - started < 3


def test_generation_change_during_busy_retry_is_fenced(tmp_path, monkeypatch):
    repo, context = fixture(tmp_path, monkeypatch)
    db = sqlite3.connect(repo.path, isolation_level=None); db.execute("BEGIN IMMEDIATE")
    errors = []
    def heartbeat():
        try: context.heartbeat()
        except Exception as error: errors.append(error)
    thread = threading.Thread(target=heartbeat); thread.start(); time.sleep(.12)
    db.execute("UPDATE tasks SET attempt=attempt+1,worker_id='other',lease_token='other-token'")
    db.commit(); db.close(); thread.join(3)
    assert len(errors) == 1 and isinstance(errors[0], ExecutionFencedError)
    assert context.lease_lost
    assert repo.get(context.task.task_id).worker_id == "other"


def test_concurrent_context_heartbeats_are_serialized(tmp_path, monkeypatch):
    repo, context = fixture(tmp_path, monkeypatch)
    active = [0, 0]
    lock = threading.Lock()
    def once(*args):
        with lock:
            active[0] += 1; active[1] = max(active[0], active[1])
        time.sleep(.05)
        with lock: active[0] -= 1
        return repo.get(context.task.task_id)
    monkeypatch.setattr(context, "_heartbeat_once", once)
    threads = [threading.Thread(target=context.heartbeat) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(2)
    assert active[1] == 1


def test_process_binding_retries_within_confirmed_lease(tmp_path, monkeypatch):
    from platform_core.task_runtime.process_control import ProcessIdentity
    repo, context = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(context, "terminate_bound_process", lambda *args, **kwargs: True)
    db = sqlite3.connect(repo.path, isolation_level=None); db.execute("BEGIN IMMEDIATE")
    errors = []
    def bind():
        try: context.bind_process(ProcessIdentity(12345, 1, "isolated-identity"))
        except Exception as error: errors.append(error)
    thread = threading.Thread(target=bind); thread.start(); time.sleep(.22)
    db.rollback(); db.close(); thread.join(3)
    assert errors == []
    assert repo.get(context.task.task_id).process_pid == 12345


def test_instance_stop_during_claim_cannot_start_handler(tmp_path, monkeypatch):
    repo, context = fixture(tmp_path, monkeypatch)
    calls = []
    class Handler:
        def run(self, context): calls.append(1); return TaskStatus.SUCCEEDED, None
    scheduler = Scheduler(repo, ArtifactStore(tmp_path / "artifacts"), "worker", {TaskKind.VIDEO_FRAMES: Handler()}, set())
    scheduler._service_stop = threading.Event()
    def claim(*args, **kwargs):
        scheduler._service_stop.set()
        return context.lease
    monkeypatch.setattr(repo, "claim_next", claim)
    scheduler.run_once()
    assert calls == []


def test_retry_attempt_cap_cannot_expire_before_its_confirmed_budget(monkeypatch):
    from platform_core.task_runtime import sqlite_busy
    clock = [0.0]
    monkeypatch.setattr(sqlite_busy.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(sqlite_busy.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(sqlite_busy.random, "uniform", lambda left, right: left)
    def busy(): raise sqlite3.OperationalError("database is locked")
    with pytest.raises(sqlite3.OperationalError): sqlite_busy.run_with_busy_retry(busy, deadline=120)
    assert 119.99 <= clock[0] <= 120


def test_gpu_payload_is_read_without_holding_task_writer(tmp_path, monkeypatch):
    from platform_core.gpu_resources import GPUResourceManager
    from platform_core.task_node_assignments import AssignmentAwareFencedTaskRepository
    repo = AssignmentAwareFencedTaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    repo.create(TaskRecord.new("gpu-payload", "project", TaskKind.TRAINING, "payload.json", "training:auto"))
    artifacts.atomic_write_json("gpu-payload", "payload.json", {"device": "cpu"})
    original = artifacts.read_json
    writes_available = []
    def read(*args, **kwargs):
        db = sqlite3.connect(repo.path, timeout=.03, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE"); writes_available.append(True); db.rollback()
        except sqlite3.OperationalError: writes_available.append(False)
        finally: db.close()
        return original(*args, **kwargs)
    monkeypatch.setattr(artifacts, "read_json", read)
    manager = GPUResourceManager(repo, artifacts)
    lease = repo.claim_next("worker", [TaskKind.TRAINING], set(), admission=manager.admit)
    assert lease is not None
    assert writes_available and all(writes_available)
