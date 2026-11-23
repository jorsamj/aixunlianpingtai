from __future__ import annotations

import os
import sys
import time

import pytest

from platform_core.node_agent_recovery import NodeRecoveryCoordinator
from platform_core.task_runtime.process_control import launch_process


class FakeWorkdirs:
    def __init__(self, records=None, unverified=None):
        self.records = list(records or [])
        self.unverified = list(unverified or [])
        self.cleared = []

    def list_process_identities(self):
        return list(self.records)

    def list_unverified_process_launch_intents(self):
        return list(self.unverified)

    def clear_process_identity_record(self, task_id, generation):
        self.cleared.append((task_id, generation))


class FakeController:
    def __init__(self):
        self.terminated = []
        self.fail = False

    def terminate_tree(self, identity, timeout=8.0):
        if self.fail:
            raise PermissionError("cannot verify")
        self.terminated.append((identity.pid, identity.create_time, identity.command_hash))


def record(task_id="a", generation=1, pid=11, create_time=1.0, command_hash="h"):
    return {"task_id": task_id, "generation": generation, "pid": pid,
            "create_time": create_time, "command_hash": command_hash}


def test_coordinator_skips_owned_slot_and_cleans_unowned(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    workdirs = FakeWorkdirs([record("a", 1, 11), record("b", 1, 22)])
    controller = FakeController()
    coordinator = NodeRecoveryCoordinator(workdirs, controller)
    coordinator.register_owner("a", 1)
    assert coordinator.prepare() == ""
    assert controller.terminated == [(22, 1.0, "h")]
    assert workdirs.cleared == [("b", 1)]
    assert coordinator.prepare() == ""  # prepared once; no second scan
    assert controller.terminated == [(22, 1.0, "h")]


def test_unowned_cleanup_failure_retains_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    workdirs = FakeWorkdirs([record("a", 1, 11)])
    controller = FakeController()
    controller.fail = True
    coordinator = NodeRecoveryCoordinator(workdirs, controller)
    error = coordinator.prepare()
    assert "cannot verify" in error
    assert workdirs.cleared == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group cleanup proof is required")
def test_real_subprocess_owner_is_not_killed_and_unowned_is_cleaned(tmp_path):
    launched = launch_process([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        record_a = {"task_id": "a", "generation": 1, "pid": launched.identity.pid,
                    "create_time": launched.identity.create_time,
                    "command_hash": launched.identity.command_hash}
        coordinator = NodeRecoveryCoordinator(FakeWorkdirs([record_a]), __import__(
            "platform_core.task_runtime.process_control", fromlist=["ProcessController"]
        ).ProcessController())
        coordinator.register_owner("a", 1)
        assert coordinator.prepare() == ""
        assert launched.process.poll() is None

        coordinator_clean = NodeRecoveryCoordinator(FakeWorkdirs([record_a]), __import__(
            "platform_core.task_runtime.process_control", fromlist=["ProcessController"]
        ).ProcessController())
        assert coordinator_clean.prepare() == ""
        launched.process.wait(timeout=10)
        assert launched.process.poll() is not None
    finally:
        if launched.process.poll() is None:
            launched.process.kill()
            launched.process.wait(timeout=10)


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group cleanup proof is required")
def test_identity_mismatch_never_kills_real_process(tmp_path):
    launched = launch_process([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        bad = {"task_id": "a", "generation": 1, "pid": launched.identity.pid,
               "create_time": launched.identity.create_time, "command_hash": "wrong"}
        controller = __import__("platform_core.task_runtime.process_control",
                                fromlist=["ProcessController"]).ProcessController()
        coordinator = NodeRecoveryCoordinator(FakeWorkdirs([bad]), controller)
        assert "cleanup could not be verified" in coordinator.prepare()
        assert launched.process.poll() is None
    finally:
        if launched.process.poll() is None:
            launched.process.kill()
            launched.process.wait(timeout=10)


def test_duplicate_owner_claim_is_rejected():
    coordinator = NodeRecoveryCoordinator(FakeWorkdirs(), FakeController())
    assert coordinator.register_owner("task", 1) is True
    assert coordinator.register_owner("task", 1) is False
    assert coordinator.register_owner("task", 2) is True
    coordinator.unregister_owner("task", 1)
    assert coordinator.register_owner("task", 1) is True


@pytest.mark.skipif(os.name == "nt", reason="Windows recovery is deliberately fail-closed")
def test_training_and_conversion_share_recovery_owner_across_managers():
    from pathlib import Path
    from platform_core.node_agent_conversion_runtime import AgentConversionRunner
    from platform_core.node_agent_training_runtime import AgentTrainingRunner
    from platform_core.task_runtime.process_control import ProcessController

    launched = launch_process([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        record_a = {"task_id": "a", "generation": 1, "pid": launched.identity.pid,
                    "create_time": launched.identity.create_time,
                    "command_hash": launched.identity.command_hash}
        workdirs = FakeWorkdirs([record_a])
        coordinator = NodeRecoveryCoordinator(workdirs, ProcessController())
        coordinator.register_owner("a", 1)
        assert coordinator.prepare() == ""
        conversion = AgentConversionRunner(
            object(), workdirs, runtime_root=Path(__file__).resolve().parents[2],
            recovery_coordinator=coordinator,
        )
        training = AgentTrainingRunner(
            object(), workdirs, runtime_root=Path(__file__).resolve().parents[2],
            recovery_coordinator=coordinator,
        )
        assert conversion.ready and training.ready
        assert launched.process.poll() is None
    finally:
        if launched.process.poll() is None:
            launched.process.kill()
            launched.process.wait(timeout=10)


def test_unverified_launch_intent_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    workdirs = FakeWorkdirs(unverified=[{"kind": "TRAINING", "task_id": "a"}])
    coordinator = NodeRecoveryCoordinator(workdirs, FakeController())
    assert "launch outcome is unverified" in coordinator.prepare()
