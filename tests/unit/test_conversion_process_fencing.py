from __future__ import annotations

import sys
import time
from pathlib import Path

import psutil
import pytest

from platform_core.deployment.conversion_tasks import run_conversion
from platform_core.task_runtime import (
    ArtifactStore,
    ExecutionFencedError,
    FencedTaskRepository,
    TaskKind,
    TaskRecord,
    WorkerContext,
)


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_conversion_lease_loss_terminates_entire_process_tree(tmp_path: Path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    task_id = "convert-1"
    job_dir = tmp_path / "conversion-job"
    job_dir.mkdir()
    child_pid_file = job_dir / "child.pid"
    worker = job_dir / "conversion_worker.py"
    worker.write_text(
        "import pathlib,subprocess,sys,time\n"
        "job_dir=pathlib.Path(sys.argv[sys.argv.index('--job-dir')+1])\n"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
        "(job_dir/'child.pid').write_text(str(child.pid))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    (job_dir / "job.json").write_text(
        '{"id":"job-1","status":"running","progress":10,"stage":"CONVERTING"}',
        encoding="utf-8",
    )
    artifacts.atomic_write_json(
        task_id,
        "request.json",
        {
            "job_dir": str(job_dir),
            "worker_path": str(worker),
            "python_path": sys.executable,
        },
    )
    repository.create(
        TaskRecord.new(
            task_id,
            "project-1",
            TaskKind.MODEL_CONVERSION,
            "request.json",
            "cpu:conversion",
        )
    )
    lease = repository.claim_next("worker-a", [TaskKind.MODEL_CONVERSION], set())
    assert lease is not None
    context = WorkerContext(lease.task, lease, repository, artifacts)

    real_heartbeat = context.heartbeat

    def lose_lease(*args, **kwargs):
        assert _wait_until(child_pid_file.exists)
        context.mark_lease_lost()
        raise ExecutionFencedError("simulated lease loss")

    context.heartbeat = lose_lease  # type: ignore[method-assign]
    with pytest.raises(ExecutionFencedError, match="simulated"):
        run_conversion(context)

    record = repository.get(task_id)
    assert record is not None
    assert record.process_pid is not None
    child_pid = int(child_pid_file.read_text())
    assert _wait_until(lambda: not psutil.pid_exists(record.process_pid))
    assert _wait_until(lambda: not psutil.pid_exists(child_pid))
    assert not artifacts.artifact_path(task_id, "conversion/result.json").exists()

    # Keep a reference so static analyzers do not treat the original method as
    # intentionally unused; it also documents that only this test replaced it.
    assert callable(real_heartbeat)
