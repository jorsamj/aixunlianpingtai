from __future__ import annotations

import hashlib
import json
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


def record(task_id="a", generation=1, pid=11, create_time=1.0, command_hash="h",
           assignment_generation=5, gpu_uuid="GPU-A"):
    return {"task_id": task_id, "generation": generation, "pid": pid,
            "create_time": create_time, "command_hash": command_hash,
            "assignment_generation": assignment_generation, "gpu_uuid": gpu_uuid}


def test_clear_intent_matches_assignment_and_execution_generations(tmp_path):
    intent = tmp_path / "dual-slot-intents.json"
    intent.write_text(json.dumps([
        {"task_id": "a", "generation": 5, "execution_attempt": 2,
         "assignment_generation": 5, "gpu_uuid": "GPU-A"},
        {"task_id": "a", "generation": 6, "execution_attempt": 3,
         "assignment_generation": 6, "gpu_uuid": "GPU-A"},
        {"task_id": "b", "generation": 5, "execution_attempt": 2,
         "assignment_generation": 5, "gpu_uuid": "GPU-B"},
    ]), encoding="utf-8")
    coordinator = NodeRecoveryCoordinator(
        FakeWorkdirs(), FakeController(), intent_path=intent,
    )
    coordinator._clear_intent(
        "a", 5, execution_attempt=2, gpu_uuid="GPU-A", assignment_generation=5,
    )
    remaining = json.loads(intent.read_text(encoding="utf-8"))
    assert [(item["task_id"], item["generation"]) for item in remaining] == [
        ("a", 6), ("b", 5),
    ]


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


class FakeRecoveryClient:
    node_id = "node-a"

    def __init__(self, status):
        self.status = status
        self.recovered = []

    def execution_status(self, task_id):
        return dict(self.status, task_id=task_id)

    def recover_execution(self, task_id, **kwargs):
        self.recovered.append((task_id, kwargs))
        self.status = {
            **self.status,
            "status": "FAILED",
            "hold_state": "RELEASED",
        }
        return {"task_id": task_id, "state": "RELEASED"}


@pytest.mark.skipif(os.name != "posix", reason="POSIX recovery proof")
@pytest.mark.parametrize("field,value", [
    ("node_id", "node-b"),
    ("execution_attempt", 3),
    ("hold_execution_attempt", 3),
    ("hold_assignment_generation", 9),
    ("hold_gpu_uuid", "GPU-B"),
    ("process_identity_sha256", "0" * 64),
])
def test_coordinator_fails_closed_on_central_identity_mismatch(tmp_path, field, value):
    workdirs = FakeWorkdirs([record("a", 2, 11)])
    controller = FakeController()
    status = {
        "status": "RUNNING", "execution_attempt": 2, "hold_state": "HELD",
        "hold_execution_attempt": 2, "hold_assignment_generation": 5,
        "hold_gpu_uuid": "GPU-A", "node_id": "node-a",
        "process_identity_sha256": hashlib.sha256(json.dumps(
            {"pid": 11, "create_time": 1.0, "command_hash": "h"},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest(),
    }
    status[field] = value
    client = FakeRecoveryClient(status)
    coordinator = NodeRecoveryCoordinator(workdirs, controller, client=client)
    assert coordinator.prepare() != ""
    assert client.recovered == []
    assert workdirs.cleared == []
    assert controller.terminated == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX recovery proof")
def test_coordinator_uses_central_recovery_and_clears_intent(tmp_path):
    workdirs = FakeWorkdirs([record("a", 2, 11)])
    controller = FakeController()
    intent = tmp_path / "dual-slot-intents.json"
    intent.write_text(json.dumps([
        {"task_id": "a", "generation": 5, "gpu_uuid": "GPU-A", "state": "CENTRAL_STARTED",
         "execution_attempt": 2, "assignment_generation": 5},
        {"task_id": "b", "generation": 1, "gpu_uuid": "GPU-B", "state": "CENTRAL_STARTED",
         "execution_attempt": 1, "assignment_generation": 1},
    ]), encoding="utf-8")
    client = FakeRecoveryClient({
        "status": "RUNNING", "execution_attempt": 2, "hold_state": "HELD",
        "hold_execution_attempt": 2, "hold_assignment_generation": 5,
        "hold_gpu_uuid": "GPU-A", "node_id": "node-a",
        "process_identity_sha256": hashlib.sha256(json.dumps(
            {"pid": 11, "create_time": 1.0, "command_hash": "h"},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest(),
    })
    coordinator = NodeRecoveryCoordinator(
        workdirs, controller, client=client, intent_path=intent,
    )
    assert coordinator.prepare() == ""
    assert client.recovered[0][0] == "a"
    assert client.recovered[0][1]["execution_generation"] == 2
    assert client.recovered[0][1]["assignment_generation"] == 5
    assert workdirs.cleared == [("a", 2)]
    remaining = json.loads(intent.read_text(encoding="utf-8"))
    assert [item["task_id"] for item in remaining] == ["b"]


def test_unverified_launch_intent_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    workdirs = FakeWorkdirs(unverified=[{"kind": "TRAINING", "task_id": "a"}])
    coordinator = NodeRecoveryCoordinator(workdirs, FakeController())
    assert "launch outcome is unverified" in coordinator.prepare()




def _use_posix_recovery(monkeypatch):
    """Exercise the POSIX recovery branch without changing global os.name.

    Patching os.name would make pathlib build PosixPath on Windows; only the
    coordinator module's view of the OS needs to be POSIX for these logic tests.
    """
    import platform_core.node_agent_recovery as recovery_module

    class _PosixView:
        name = "posix"

        def __getattr__(self, item):
            return getattr(os, item)

    monkeypatch.setattr(recovery_module, "os", _PosixView())

class RecoveringClient:
    node_id = "node-a"

    def __init__(self, status, *, digest=None, refreshed=None):
        self.status = dict(status)
        self.digest = digest
        self.refreshed = dict(refreshed) if refreshed is not None else None
        self.recovered = []

    def execution_status(self, task_id):
        return dict(self.status, task_id=task_id)

    def recover_execution(self, task_id, **kwargs):
        self.recovered.append((task_id, kwargs))
        body = {
            "status": "FAILED",
            "hold_state": "RELEASED",
            "proof_type": "PROCESS_STOP_VERIFIED",
            "proof_sha256": self.digest,
        }
        if self.refreshed is not None:
            body.update(self.refreshed)
        self.status = {**self.status, **body}
        return {"task_id": task_id, "state": "RELEASED",
                "proof_sha256": self.digest}


def _local_digest(pid=11, create_time=1.0, command_hash="h"):
    return hashlib.sha256(json.dumps(
        {"pid": pid, "create_time": create_time, "command_hash": command_hash},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def stop_proof_digest(*, legacy=False, **overrides):
    body = {
        "node_id": "node-a", "task_id": "a", "assignment_generation": 5,
        "execution_attempt": 2, "gpu_uuid": "GPU-A",
        "process_identity": {"pid": 11, "create_time": 1.0, "command_hash": "h"},
        "stop_verified": True,
    }
    if not legacy:
        body["proof_type"] = "PROCESS_STOP_VERIFIED"
        body["no_process_launched"] = False
        body["no_launch_evidence"] = {}
    body.update(overrides)
    return hashlib.sha256(json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def dual_record(**overrides):
    value = {"task_id": "a", "generation": 2, "pid": 11, "create_time": 1.0,
             "command_hash": "h", "assignment_generation": 5,
             "gpu_uuid": "GPU-A", "execution_slots": 2}
    value.update(overrides)
    return value


def dual_status(*, hold_state="HELD", proof_type=None, proof_sha256=None, **overrides):
    value = {
        "status": "RUNNING", "execution_attempt": 2, "hold_state": hold_state,
        "hold_execution_attempt": 2, "hold_assignment_generation": 5,
        "hold_gpu_uuid": "GPU-A", "node_id": "node-a",
        "process_identity_sha256": _local_digest(),
        "proof_type": proof_type, "proof_sha256": proof_sha256,
    }
    value.update(overrides)
    return value


def test_legacy_single_slot_recovery_without_hold_is_not_blocked(monkeypatch):
    _use_posix_recovery(monkeypatch)
    record = {"task_id": "a", "generation": 2, "pid": 11, "create_time": 1.0,
              "command_hash": "h", "assignment_generation": 5,
              "gpu_uuid": "", "execution_slots": 1}
    status = {
        "status": "RUNNING", "execution_attempt": 2, "node_id": "node-a",
        "assignment_generation": 5, "assignment_state": "RELEASED",
        "hold_state": None, "hold_execution_attempt": None,
        "hold_assignment_generation": None, "hold_gpu_uuid": None,
        "proof_type": None, "proof_sha256": None,
        "process_identity_sha256": _local_digest(),
    }
    workdirs = FakeWorkdirs([record])
    controller = FakeController()
    client = RecoveringClient(status)
    coordinator = NodeRecoveryCoordinator(workdirs, controller, client=client)
    assert coordinator.prepare() == ""
    assert controller.terminated == [(11, 1.0, "h")]
    assert client.recovered == []
    assert workdirs.cleared == [("a", 2)]


def test_dual_slot_missing_hold_blocks_recovery(monkeypatch):
    _use_posix_recovery(monkeypatch)
    workdirs = FakeWorkdirs([dual_record()])
    controller = FakeController()
    status = dual_status(hold_state=None, hold_execution_attempt=None,
                         hold_assignment_generation=None, hold_gpu_uuid=None)
    coordinator = NodeRecoveryCoordinator(
        workdirs, controller, client=RecoveringClient(status))
    assert coordinator.prepare() == "central Hold missing for dual-slot execution"
    assert controller.terminated == []
    assert workdirs.cleared == []


@pytest.mark.skipif(os.name == "nt", reason="Windows recovery is deliberately fail-closed")
@pytest.mark.parametrize("legacy_digest", [False, True])
def test_released_stop_proof_is_verified_and_idempotently_cleaned(legacy_digest, monkeypatch):
    digest = stop_proof_digest(legacy=legacy_digest)
    workdirs = FakeWorkdirs([dual_record()])
    controller = FakeController()
    client = RecoveringClient(dual_status(
        status="FAILED", hold_state="RELEASED",
        proof_type="PROCESS_STOP_VERIFIED", proof_sha256=digest,
    ))
    coordinator = NodeRecoveryCoordinator(workdirs, controller, client=client)
    assert coordinator.prepare() == ""
    assert client.recovered == []
    assert controller.terminated == [(11, 1.0, "h")]
    assert workdirs.cleared == [("a", 2)]


def test_released_stop_proof_mismatch_keeps_evidence(monkeypatch):
    _use_posix_recovery(monkeypatch)
    workdirs = FakeWorkdirs([dual_record()])
    controller = FakeController()
    client = RecoveringClient(dual_status(
        status="FAILED", hold_state="RELEASED",
        proof_type="PROCESS_STOP_VERIFIED", proof_sha256="0" * 64,
    ))
    coordinator = NodeRecoveryCoordinator(workdirs, controller, client=client)
    assert coordinator.prepare() == "central stop proof digest mismatch"
    assert controller.terminated == []
    assert workdirs.cleared == []


def test_no_launch_proof_cannot_cover_a_persisted_process_identity(monkeypatch):
    _use_posix_recovery(monkeypatch)
    workdirs = FakeWorkdirs([dual_record()])
    controller = FakeController()
    client = RecoveringClient(dual_status(
        status="FAILED", hold_state="RELEASED",
        proof_type="NO_PROCESS_LAUNCHED", proof_sha256=stop_proof_digest(),
    ))
    coordinator = NodeRecoveryCoordinator(workdirs, controller, client=client)
    assert coordinator.prepare() == "central stop proof type mismatch"
    assert controller.terminated == []
    assert workdirs.cleared == []


def test_legacy_single_slot_must_not_carry_a_stop_proof(monkeypatch):
    _use_posix_recovery(monkeypatch)
    record = {"task_id": "a", "generation": 2, "pid": 11, "create_time": 1.0,
              "command_hash": "h", "assignment_generation": 0,
              "gpu_uuid": "", "execution_slots": 0}
    status = {
        "status": "RUNNING", "execution_attempt": 2, "node_id": "node-a",
        "assignment_generation": None, "hold_state": None,
        "proof_type": "NO_PROCESS_LAUNCHED", "proof_sha256": "a" * 64,
        "process_identity_sha256": _local_digest(),
    }
    workdirs = FakeWorkdirs([record])
    controller = FakeController()
    coordinator = NodeRecoveryCoordinator(
        workdirs, controller, client=RecoveringClient(status))
    assert coordinator.prepare() == "central stop proof present without a Hold"
    assert controller.terminated == []


def test_recovery_digest_must_match_refreshed_status(monkeypatch):
    _use_posix_recovery(monkeypatch)
    digest = stop_proof_digest()
    workdirs = FakeWorkdirs([dual_record()])
    controller = FakeController()
    client = RecoveringClient(
        dual_status(),
        digest=digest,
        refreshed={"proof_type": "PROCESS_STOP_VERIFIED", "proof_sha256": "b" * 64},
    )
    coordinator = NodeRecoveryCoordinator(workdirs, controller, client=client)
    assert "stop proof does not match" in coordinator.prepare()
    assert len(client.recovered) == 1
    assert workdirs.cleared == []


def test_central_recovery_releases_hold_with_exact_identity(monkeypatch):
    _use_posix_recovery(monkeypatch)
    digest = stop_proof_digest()
    workdirs = FakeWorkdirs([dual_record()])
    controller = FakeController()
    client = RecoveringClient(dual_status(), digest=digest)
    coordinator = NodeRecoveryCoordinator(workdirs, controller, client=client)
    assert coordinator.prepare() == ""
    assert client.recovered == [("a", {
        "assignment_generation": 5,
        "execution_generation": 2,
        "gpu_uuid": "GPU-A",
        "process_identity": {"pid": 11, "create_time": 1.0, "command_hash": "h"},
    })]
    assert workdirs.cleared == [("a", 2)]


class FlakyWorkdirs(FakeWorkdirs):
    def __init__(self, records=None, unverified=None, failures=1):
        super().__init__(records, unverified)
        self.failures = int(failures)

    def clear_process_identity_record(self, task_id, generation):
        if self.failures > 0:
            self.failures -= 1
            raise OSError("injected identity cleanup failure")
        super().clear_process_identity_record(task_id, generation)


def test_intent_is_cleared_first_and_a_failed_identity_cleanup_converges(tmp_path, monkeypatch):
    _use_posix_recovery(monkeypatch)
    intent = tmp_path / "dual-slot-intents.json"
    intent.write_text(json.dumps([
        {"task_id": "a", "generation": 5, "execution_attempt": 2,
         "assignment_generation": 5, "gpu_uuid": "GPU-A", "state": "CENTRAL_STARTED"},
        {"task_id": "b", "generation": 1, "execution_attempt": 1,
         "assignment_generation": 1, "gpu_uuid": "GPU-B", "state": "CENTRAL_STARTED"},
    ]), encoding="utf-8")
    digest = stop_proof_digest()
    status = dual_status(status="FAILED", hold_state="RELEASED",
                         proof_type="PROCESS_STOP_VERIFIED", proof_sha256=digest)
    workdirs = FlakyWorkdirs([dual_record()], failures=1)
    controller = FakeController()
    first = NodeRecoveryCoordinator(
        workdirs, controller, client=RecoveringClient(status), intent_path=intent,
    )
    assert "could not be persisted" in first.prepare()
    # The unique original execution evidence was retained because the second
    # step failed; the intent (not the evidence) was already cleared.
    assert workdirs.cleared == []
    remaining = json.loads(intent.read_text(encoding="utf-8"))
    assert [item["task_id"] for item in remaining] == ["b"]

    # A restarted coordinator converges: no matching intent record is fine, the
    # identity is cleared, and the other task's intent is untouched.
    second = NodeRecoveryCoordinator(
        workdirs, controller, client=RecoveringClient(status), intent_path=intent,
    )
    assert second.prepare() == ""
    assert workdirs.cleared == [("a", 2)]
    remaining = json.loads(intent.read_text(encoding="utf-8"))
    assert [item["task_id"] for item in remaining] == ["b"]


def test_unmatched_same_task_intent_blocks_instead_of_silently_ignoring(tmp_path, monkeypatch):
    _use_posix_recovery(monkeypatch)
    intent = tmp_path / "dual-slot-intents.json"
    intent.write_text(json.dumps([
        {"task_id": "a", "generation": 5, "execution_attempt": 3,
         "assignment_generation": 5, "gpu_uuid": "GPU-A", "state": "CENTRAL_STARTED"},
    ]), encoding="utf-8")
    digest = stop_proof_digest()
    status = dual_status(status="FAILED", hold_state="RELEASED",
                         proof_type="PROCESS_STOP_VERIFIED", proof_sha256=digest)
    workdirs = FakeWorkdirs([dual_record()])
    controller = FakeController()
    coordinator = NodeRecoveryCoordinator(
        workdirs, controller, client=RecoveringClient(status), intent_path=intent,
    )
    assert "does not match" in coordinator.prepare()
    assert workdirs.cleared == []
    remaining = json.loads(intent.read_text(encoding="utf-8"))
    assert remaining[0]["execution_attempt"] == 3
