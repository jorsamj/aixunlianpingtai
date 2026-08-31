import sys
import time
from pathlib import Path

import psutil
import pytest

from platform_core.task_runtime import TaskKind, TaskRecord, TaskRepository
from platform_core.task_runtime.process_control import (
    ProcessController,
    ProcessIdentity,
    hash_command,
    launch_process,
)


def wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_launch_requires_argv_and_identity_rejects_reused_pid(tmp_path):
    with pytest.raises(TypeError, match="argv"):
        launch_process(f'{sys.executable} -c "print(1)"', cwd=tmp_path)

    handle = launch_process(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
    )
    controller = ProcessController()
    try:
        assert controller.inspect(handle.identity).pid == handle.identity.pid
        wrong = ProcessIdentity(
            handle.identity.pid,
            handle.identity.create_time - 10,
            handle.identity.command_hash,
        )
        with pytest.raises(PermissionError, match="identity"):
            controller.inspect(wrong)
    finally:
        controller.terminate_tree(handle.identity)


def test_suspend_resume_and_terminate_real_process_tree(tmp_path):
    child_pid_file = tmp_path / "child.pid"
    script = (
        "import pathlib,subprocess,sys,time;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        f"pathlib.Path({str(child_pid_file)!r}).write_text(str(p.pid));"
        "time.sleep(60)"
    )
    handle = launch_process([sys.executable, "-c", script], cwd=tmp_path)
    controller = ProcessController()
    assert wait_until(child_pid_file.exists)
    child_pid = int(child_pid_file.read_text())
    assert psutil.pid_exists(child_pid)

    controller.suspend_tree(handle.identity)
    assert psutil.Process(handle.identity.pid).status() == psutil.STATUS_STOPPED
    controller.resume_tree(handle.identity)
    assert wait_until(lambda: psutil.Process(handle.identity.pid).status() != psutil.STATUS_STOPPED)

    controller.terminate_tree(handle.identity)
    assert wait_until(lambda: not psutil.pid_exists(handle.identity.pid))
    assert wait_until(lambda: not psutil.pid_exists(child_pid))


def test_repository_binds_process_only_for_owned_lease(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(
        TaskRecord.new(
            "train-1",
            "project-1",
            TaskKind.TRAINING,
            "payload.json",
            "gpu:local:0",
            required_capabilities=("cuda",),
        )
    )
    lease = repository.claim_next("worker", [TaskKind.TRAINING], {"cuda"})
    assert lease is not None
    identity = ProcessIdentity(123, 456.5, hash_command(["python", "train_worker.py"]))

    with pytest.raises(PermissionError, match="lease"):
        repository.bind_process("train-1", "wrong", identity)

    bound = repository.bind_process("train-1", lease.lease_token, identity)
    assert (bound.process_pid, bound.process_create_time, bound.process_command_hash) == (
        123,
        456.5,
        identity.command_hash,
    )
