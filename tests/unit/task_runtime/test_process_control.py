import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from platform_core.task_runtime import TaskKind, TaskRecord, TaskRepository
from platform_core.task_runtime.process_control import (
    ProcessController,
    ProcessIdentity,
    ProcessIdentityMismatchError,
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


def process_execution_alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
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


@pytest.mark.skipif(os.name != "nt", reason="Windows Popen process handle lifetime")
def test_launch_binds_original_windows_process_after_exit(monkeypatch):
    from platform_core.task_runtime import process_control

    popen = subprocess.Popen

    def exit_before_identity(*args, **kwargs):
        child = popen(*args, **kwargs)
        assert child.wait(timeout=10) == 0
        return child

    monkeypatch.setattr(process_control.subprocess, "Popen", exit_before_identity)
    command = [sys.executable, "-c", "pass"]
    started = time.time()
    launched = launch_process(command)
    assert launched.process.returncode == 0
    assert launched.identity.pid == launched.process.pid
    assert started - 1 <= launched.identity.create_time <= time.time() + 1
    assert launched.identity.command_hash == hash_command(command)
    with pytest.raises(ProcessLookupError):
        ProcessController().inspect(launched.identity)


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
    # Signal delivery is asynchronous; observe the same exact state using the
    # existing deadline also used by resume and termination below.
    assert wait_until(lambda: psutil.Process(handle.identity.pid).status() == psutil.STATUS_STOPPED)
    controller.resume_tree(handle.identity)
    assert wait_until(lambda: psutil.Process(handle.identity.pid).status() != psutil.STATUS_STOPPED)

    controller.terminate_tree(handle.identity)
    assert wait_until(lambda: not process_execution_alive(handle.identity.pid))
    assert wait_until(lambda: not process_execution_alive(child_pid))


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group orphan recovery")
def test_terminate_tree_reaps_group_after_leader_was_killed(tmp_path):
    child_pid_file = tmp_path / "orphan-child.pid"
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
    assert process_execution_alive(child_pid)
    assert os.getpgid(child_pid) == handle.identity.pid

    # Reproduce the production failure mode: Linux OOM-kills only the training
    # leader, while DataLoader-like descendants remain alive and become orphans.
    os.kill(handle.identity.pid, signal.SIGKILL)
    handle.process.wait(timeout=5)
    assert not process_execution_alive(handle.identity.pid)
    assert process_execution_alive(child_pid)

    controller.terminate_tree(handle.identity, timeout=3.0)

    assert wait_until(lambda: not process_execution_alive(child_pid), timeout=5.0)


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group token proof")
def test_leaderless_group_without_token_fails_closed(tmp_path):
    child_pid_file = tmp_path / "token-child.pid"
    script = (
        "import pathlib,subprocess,sys,time;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        f"pathlib.Path({str(child_pid_file)!r}).write_text(str(p.pid));"
        "time.sleep(60)"
    )
    handle = launch_process([sys.executable, "-c", script], cwd=tmp_path)
    assert wait_until(child_pid_file.exists)
    child_pid = int(child_pid_file.read_text())
    os.kill(handle.identity.pid, signal.SIGKILL)
    handle.process.wait(timeout=5)
    untrusted = ProcessIdentity(
        pid=handle.identity.pid,
        create_time=handle.identity.create_time,
        command_hash=handle.identity.command_hash,
        group_token="",
    )
    try:
        with pytest.raises(PermissionError):
            ProcessController().terminate_tree(untrusted, timeout=1.0)
        assert process_execution_alive(child_pid)
    finally:
        ProcessController().terminate_tree(handle.identity, timeout=3.0)
    assert wait_until(lambda: not process_execution_alive(child_pid), timeout=5.0)


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

@pytest.mark.parametrize("bad_created", [float("nan"), float("inf"), float("-inf"), "nan", "Infinity"])
def test_process_controller_denies_nonfinite_creation_time_even_when_pid_and_command_match(
    bad_created,
):
    # A matching command hash is not enough: NaN otherwise bypasses
    # abs(observed_time - claimed_time) > tolerance comparisons.
    current = psutil.Process(os.getpid())
    record = ProcessIdentity(
        pid=current.pid,
        create_time=bad_created,
        command_hash=hash_command(current.cmdline()),
    )
    with pytest.raises(ProcessIdentityMismatchError, match="invalid pid/create_time"):
        ProcessController().inspect(record)
