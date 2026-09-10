from argparse import Namespace
from pathlib import Path

import task_worker


def args(training_slot=None):
    return Namespace(training_slot=training_slot)


def test_all_role_supervisor_child_command_is_role_isolated():
    command = task_worker._role_worker_command(args(), Path("runtime-data"), "storage", "host-storage")
    assert command[0] == task_worker.sys.executable
    assert command[-2:] == ["--roles", "storage"]
    assert "all" not in command
    assert "--allow-parallel" not in command


def test_training_slot_is_only_forwarded_to_training_child():
    training = task_worker._role_worker_command(args("gpu-a"), Path("runtime-data"), "training", "host-training")
    storage = task_worker._role_worker_command(args("gpu-a"), Path("runtime-data"), "storage", "host-storage")
    assert training[-2:] == ["--training-slot", "gpu-a"]
    assert "--training-slot" not in storage
