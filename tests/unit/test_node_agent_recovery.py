from __future__ import annotations

import os

import pytest

from platform_core.node_agent_recovery import NodeRecoveryCoordinator


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


def test_unverified_launch_intent_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    workdirs = FakeWorkdirs(unverified=[{"kind": "TRAINING", "task_id": "a"}])
    coordinator = NodeRecoveryCoordinator(workdirs, FakeController())
    assert "launch outcome is unverified" in coordinator.prepare()
