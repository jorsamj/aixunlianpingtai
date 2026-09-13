from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

import psutil
import pytest

from platform_core.deployment.inference_tasks import run_deployment_test
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


def _kill_if_alive(pid: int) -> None:
    try:
        process = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return
    try:
        descendants = process.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        descendants = []
    for child in descendants:
        try:
            child.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    try:
        process.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    try:
        process.wait(timeout=2)
    except (psutil.NoSuchProcess, psutil.TimeoutExpired):
        pass


def test_deployment_test_lease_loss_binds_and_terminates_runner(tmp_path: Path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    task_id = "deployment-test-lease-loss"

    model = tmp_path / "model.onnx"
    model.write_bytes(b"fake-model")
    image = tmp_path / "input.jpg"
    image.write_bytes(b"fake-image")
    output = tmp_path / "output.jpg"
    runner_pid_file = tmp_path / "runner.pid"
    runner = tmp_path / "predict_ultralytics_runner.py"
    runner.write_text(
        "import os,pathlib,sys,time\n"
        "args=sys.argv\n"
        "output=pathlib.Path(args[args.index('--output')+1])\n"
        "(output.parent/'runner.pid').write_text(str(os.getpid()), encoding='utf-8')\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )

    artifacts.atomic_write_json(
        task_id,
        "request.json",
        {
            "model_path": str(model),
            "model_reference": "",
            "model_reference_type": "",
            "input_path": str(image),
            "output_path": str(output),
            "runner_path": str(runner),
            "python_path": sys.executable,
            "framework": "ultralytics",
            "conf": 0.25,
        },
    )
    repository.create(
        TaskRecord.new(
            task_id,
            "project-1",
            TaskKind.DEPLOYMENT_TEST,
            "request.json",
            "cpu:deployment-test",
        )
    )
    lease = repository.claim_next("worker-a", [TaskKind.DEPLOYMENT_TEST], set())
    assert lease is not None
    context = WorkerContext(lease.task, lease, repository, artifacts)

    def lose_lease():
        assert _wait_until(runner_pid_file.exists)
        context.mark_lease_lost()
        raise ExecutionFencedError("simulated deployment-test lease loss")

    context.cancel_requested = lose_lease  # type: ignore[method-assign]
    runner_pid = None
    try:
        with pytest.raises(ExecutionFencedError, match="simulated deployment-test lease loss"):
            run_deployment_test(context)

        assert runner_pid_file.exists()
        runner_pid = int(runner_pid_file.read_text(encoding="utf-8"))
        record = repository.get(task_id)
        assert record is not None
        assert record.process_pid == runner_pid
        assert record.process_create_time is not None
        assert record.process_command_hash
        assert _wait_until(lambda: not psutil.pid_exists(runner_pid))
        assert not output.exists()
    finally:
        if runner_pid is None and runner_pid_file.exists():
            runner_pid = int(runner_pid_file.read_text(encoding="utf-8"))
        if runner_pid is not None:
            _kill_if_alive(runner_pid)
