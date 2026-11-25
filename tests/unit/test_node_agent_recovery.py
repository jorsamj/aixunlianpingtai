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
    def __init__(self, records=None, unverified=None, evidence=None):
        self.records = list(records or [])
        self.unverified = list(unverified or [])
        self.evidence = dict(evidence or {})
        self.cleared = []

    def stop_evidence_path(self, task_id, generation):
        path = self.evidence.get((str(task_id), int(generation)))
        if path is None:
            raise ValueError("execution workdir is missing")
        return path

    def read_stop_evidence(self, task_id, generation):
        path = self.evidence.get((str(task_id), int(generation)))
        if path is None:
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError("persisted stop evidence is unreadable") from error
        if not isinstance(value, dict):
            raise ValueError("persisted stop evidence is invalid")
        if (str(value.get("task_id") or "") != str(task_id)
                or int(value.get("execution_attempt") or 0) != int(generation)):
            raise ValueError("persisted stop evidence lineage mismatch")
        return value

    def list_process_identities(self):
        return list(self.records)

    def list_unverified_process_launch_intents(self):
        return list(self.unverified)

    def clear_process_identity_record(self, task_id, generation):
        self.cleared.append((task_id, generation))

    def clear_stop_evidence(self, task_id, generation):
        self.evidence.pop((str(task_id), int(generation)), None)


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
        # Model the real /recover response: the central side records a
        # PROCESS_STOP_VERIFIED proof digest derived from the original identity,
        # returns it, and exposes it again through the refreshed status.
        self.recovered.append((task_id, kwargs))
        digest = hashlib.sha256(json.dumps({
            "proof_type": "PROCESS_STOP_VERIFIED",
            "node_id": self.node_id,
            "task_id": str(task_id),
            "assignment_generation": int(kwargs["assignment_generation"]),
            "execution_attempt": int(kwargs["execution_generation"]),
            "gpu_uuid": str(kwargs["gpu_uuid"]),
            "process_identity": dict(kwargs["process_identity"]),
            "stop_verified": True,
            "no_process_launched": False,
            "no_launch_evidence": {},
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        self.status = {
            **self.status,
            "status": "FAILED",
            "hold_state": "RELEASED",
            "proof_type": "PROCESS_STOP_VERIFIED",
            "proof_sha256": digest,
        }
        return {"task_id": task_id, "state": "RELEASED", "proof_sha256": digest}


@pytest.mark.parametrize("field,value", [
    ("node_id", "node-b"),
    ("execution_attempt", 3),
    ("hold_execution_attempt", 3),
    ("hold_assignment_generation", 9),
    ("hold_gpu_uuid", "GPU-B"),
    ("process_identity_sha256", "0" * 64),
])
def test_coordinator_fails_closed_on_central_identity_mismatch(tmp_path, monkeypatch, field, value):
    _use_posix_recovery(monkeypatch)
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


def test_coordinator_uses_central_recovery_and_clears_intent(tmp_path, monkeypatch):
    _use_posix_recovery(monkeypatch)
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
    client = SingleSlotRecoveryClient(status)
    coordinator = NodeRecoveryCoordinator(workdirs, controller, client=client)
    assert coordinator.prepare() == ""
    assert controller.terminated == [(11, 1.0, "h")]
    # A single-slot execution has no Hold, so the control plane must settle the
    # exact original attempt through the shared fenced recovery contract.
    assert client.recovered == [("a", {
        "assignment_generation": 5,
        "execution_generation": 2,
        "gpu_uuid": "",
        "process_identity": {"pid": 11, "create_time": 1.0, "command_hash": "h"},
    })]
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

def _stop_evidence(tmp_path, name, record_value, **overrides):
    value = {
        "task_id": record_value["task_id"],
        "execution_attempt": record_value["generation"],
        "assignment_generation": record_value["assignment_generation"],
        "gpu_uuid": record_value["gpu_uuid"],
        "proof_type": "PROCESS_STOP_VERIFIED",
        "stop_verified": True,
        "no_process_launched": False,
        "reason": "terminate_active",
        "verified_at": "2026-11-25T08:00:00Z",
        "process_identity": {
            "pid": record_value["pid"],
            "create_time": record_value["create_time"],
            "command_hash": record_value["command_hash"],
        },
    }
    value.update(overrides)
    path = tmp_path / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_valid_stop_evidence_is_consumed_before_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    record_value = record("a", 1, 11)
    evidence = _stop_evidence(tmp_path, "a-1.json", record_value)
    workdirs = FakeWorkdirs([record_value], evidence={("a", 1): evidence})
    controller = FakeController()
    coordinator = NodeRecoveryCoordinator(workdirs, controller)
    assert coordinator.prepare() == ""
    # The trusted stop is still re-verified against the real OS boundary.
    assert controller.terminated == [(11, 1.0, "h")]
    assert workdirs.cleared == [("a", 1)]


def test_stop_evidence_for_another_identity_blocks_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    record_value = record("a", 1, 11)
    evidence = _stop_evidence(tmp_path, "a-1.json", record_value, task_id="b")
    workdirs = FakeWorkdirs([record_value], evidence={("a", 1): evidence})
    controller = FakeController()
    coordinator = NodeRecoveryCoordinator(workdirs, controller)
    error = coordinator.prepare()
    assert "persisted stop evidence" in error
    assert controller.terminated == []
    assert workdirs.cleared == []


def test_corrupt_stop_evidence_blocks_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    record_value = record("a", 1, 11)
    path = tmp_path / "a-1.json"
    path.write_text("{not json", encoding="utf-8")
    workdirs = FakeWorkdirs([record_value], evidence={("a", 1): path})
    coordinator = NodeRecoveryCoordinator(workdirs, FakeController())
    assert "persisted stop evidence is unsafe" in coordinator.prepare()
    assert workdirs.cleared == []

class _SingleSlotClient:
    """Real single-slot status projection: no Hold, no stop proof.

    ``node_id`` is part of the central contract and must be present in the
    status body; identity is only bound when the control plane registered it.
    """

    def __init__(self, status):
        self.status = status
        self.node_id = "node-a"

    def execution_status(self, task_id):
        return dict(self.status, task_id=task_id)


class SingleSlotRecoveryClient(_SingleSlotClient):
    """Models the extended single-slot recovery response of the real API."""

    def __init__(self, status, *, recovered_status="FAILED", fail_first=False):
        super().__init__(status)
        self.recovered_status = recovered_status
        self.fail_first = bool(fail_first)
        self.recovered = []
        self.calls = 0

    def recover_execution(self, task_id, **kwargs):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise OSError("central recovery response was lost")
        self.recovered.append((task_id, kwargs))
        identity = dict(kwargs["process_identity"])
        digest = NodeRecoveryCoordinator._identity_sha256({
            "pid": identity["pid"],
            "create_time": identity["create_time"],
            "command_hash": identity["command_hash"],
        })
        self.status = {
            **self.status,
            "status": self.recovered_status,
            "process_identity_sha256": digest,
        }
        return {
            "task_id": task_id,
            "state": "SETTLED",
            "terminal_status": self.recovered_status,
            "execution_attempt": int(kwargs["execution_generation"]),
            "proof_sha256": "",
        }


def test_single_slot_unsettled_execution_retains_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    record_value = record("a", 1, 11, assignment_generation=0, gpu_uuid="")
    workdirs = FakeWorkdirs([record_value])
    client = _SingleSlotClient({
        "status": "RUNNING", "execution_attempt": 1, "hold_state": None,
        "node_id": "node-a",
        "process_identity_sha256": None,
    })
    coordinator = NodeRecoveryCoordinator(workdirs, FakeController(), client=client)
    error = coordinator.prepare()
    assert "not centrally settled" in error
    assert coordinator.retryable is True
    assert workdirs.cleared == []


def test_single_slot_settled_execution_is_cleaned(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    record_value = record("a", 1, 11, assignment_generation=0, gpu_uuid="")
    workdirs = FakeWorkdirs([record_value])
    client = _SingleSlotClient({
        "status": "CANCELLED", "execution_attempt": 1, "hold_state": None,
        "node_id": "node-a",
        "process_identity_sha256": None,
    })
    coordinator = NodeRecoveryCoordinator(workdirs, FakeController(), client=client)
    assert coordinator.prepare() == ""
    assert workdirs.cleared == [("a", 1)]


def test_single_slot_transient_block_is_reverified_and_converges(monkeypatch):
    """Same coordinator instance: unsettled -> evidence kept -> later settled."""
    _use_posix_recovery(monkeypatch)
    record_value = {"task_id": "a", "generation": 2, "pid": 11, "create_time": 1.0,
                    "command_hash": "h", "assignment_generation": 5,
                    "gpu_uuid": "", "execution_slots": 1}
    status = {
        "status": "RUNNING", "execution_attempt": 2, "node_id": "node-a",
        "assignment_generation": 5, "assignment_state": "RELEASED",
        "hold_state": None, "hold_execution_attempt": None,
        "hold_assignment_generation": None, "hold_gpu_uuid": None,
        "proof_type": None, "proof_sha256": None,
        "process_identity_sha256": None,
    }
    workdirs = FakeWorkdirs([record_value])
    client = SingleSlotRecoveryClient(status, fail_first=True)
    coordinator = NodeRecoveryCoordinator(workdirs, FakeController(), client=client)

    first = coordinator.prepare()
    assert "not centrally settled" in first
    assert coordinator.retryable is True
    assert workdirs.cleared == []
    assert len(workdirs.records) == 1

    # The control plane is reachable again: the same instance re-verifies the
    # exact original execution and only then releases the evidence.
    assert coordinator.prepare() == ""
    assert coordinator.retryable is False
    assert client.calls == 2
    assert workdirs.cleared == [("a", 2)]
    # A settled scan stays cached; no duplicate recovery owner is created.
    assert coordinator.prepare() == ""
    assert client.calls == 2


def test_permanent_recovery_block_is_cached_not_retried(monkeypatch):
    _use_posix_recovery(monkeypatch)
    record_value = record("a", 1, 11, assignment_generation=0, gpu_uuid="")
    workdirs = FakeWorkdirs([record_value])
    client = _SingleSlotClient({
        "status": "RUNNING", "execution_attempt": 1, "hold_state": None,
        "node_id": "node-b",
        "process_identity_sha256": None,
    })
    coordinator = NodeRecoveryCoordinator(workdirs, FakeController(), client=client)
    first = coordinator.prepare()
    assert "central node identity mismatch" in first
    assert coordinator.retryable is False
    # Even if the control plane would now agree, a permanent identity mismatch
    # is not silently re-adjudicated by a retry.
    client.status["node_id"] = "node-a"
    assert coordinator.prepare() == first
    assert workdirs.cleared == []


def test_dual_slot_accepted_stop_proof_without_release_retains_evidence(monkeypatch):
    """proof accepted is not a settlement: the Hold must actually be RELEASED."""
    _use_posix_recovery(monkeypatch)
    digest = stop_proof_digest()
    status = dual_status(
        status="RUNNING", hold_state="STOP_VERIFIED",
        proof_type="PROCESS_STOP_VERIFIED", proof_sha256=digest,
    )
    workdirs = FakeWorkdirs([dual_record()])
    controller = FakeController()
    client = RecoveringClient(
        status, digest=digest, refreshed={"hold_state": "STOP_VERIFIED"},
    )
    coordinator = NodeRecoveryCoordinator(workdirs, controller, client=client)
    error = coordinator.prepare()
    assert "did not release the original Hold" in error
    assert coordinator.retryable is True
    assert workdirs.cleared == []


def _lost_response_client(status, digest):
    class LostResponseClient(RecoveringClient):
        def recover_execution(self, task_id, **kwargs):
            RecoveringClient.recover_execution(self, task_id, **kwargs)
            raise OSError("central recovery response was lost")

    return LostResponseClient(status, digest=digest)


def test_lost_recovery_response_converges_on_the_next_verification(monkeypatch):
    _use_posix_recovery(monkeypatch)
    digest = stop_proof_digest()
    status = dual_status()
    workdirs = FakeWorkdirs([dual_record()])
    client = _lost_response_client(status, digest)
    coordinator = NodeRecoveryCoordinator(workdirs, FakeController(), client=client)

    first = coordinator.prepare()
    assert "central recovery could not release original execution" in first
    assert workdirs.cleared == []
    assert len(client.recovered) == 1

    # The control plane did commit the recovery before the response was lost:
    # the refreshed status alone now proves the settlement, idempotently.
    assert coordinator.prepare() == ""
    assert len(client.recovered) == 1
    assert workdirs.cleared == [("a", 2)]


@pytest.mark.parametrize("field,value", [
    ("execution_attempt", True),
    ("execution_attempt", "2"),
    ("execution_attempt", 2.0),
    ("assignment_generation", "5"),
    ("assignment_generation", True),
    ("gpu_uuid", 5),
])
def test_stop_evidence_rejects_coerced_top_level_fields(tmp_path, monkeypatch, field, value):
    monkeypatch.setattr(os, "name", "posix")
    record_value = record("a", 1, 11)
    evidence = _stop_evidence(tmp_path, "a-1.json", record_value, **{field: value})
    workdirs = FakeWorkdirs([record_value], evidence={("a", 1): evidence})
    controller = FakeController()
    coordinator = NodeRecoveryCoordinator(workdirs, controller)
    error = coordinator.prepare()
    assert "persisted stop evidence" in error
    assert coordinator.retryable is False
    assert controller.terminated == []
    assert workdirs.cleared == []


@pytest.mark.parametrize("field,value", [
    ("pid", "11"),
    ("pid", True),
    ("pid", 0),
    ("create_time", "1.0"),
    ("create_time", True),
    ("create_time", float("nan")),
    ("create_time", float("inf")),
    ("create_time", 0.0),
    ("create_time", -1.0),
    ("command_hash", None),
    ("command_hash", 11),
])
def test_stop_evidence_rejects_invalid_process_identity_fields(
    tmp_path, monkeypatch, field, value,
):
    monkeypatch.setattr(os, "name", "posix")
    record_value = record("a", 1, 11)
    evidence = _stop_evidence(tmp_path, "a-1.json", record_value)
    raw = json.loads(evidence.read_text(encoding="utf-8"))
    raw["process_identity"][field] = value
    evidence.write_text(json.dumps(raw), encoding="utf-8")
    workdirs = FakeWorkdirs([record_value], evidence={("a", 1): evidence})
    controller = FakeController()
    coordinator = NodeRecoveryCoordinator(workdirs, controller)
    error = coordinator.prepare()
    assert "persisted stop evidence" in error
    assert coordinator.retryable is False
    assert controller.terminated == []
    assert workdirs.cleared == []


def test_real_workdir_stop_evidence_blocks_cleanup_and_is_cleared_idempotently(tmp_path):
    """The real persisted witness, not a fake: unsafe evidence fails closed."""
    from platform_core.node_agent_executor_runtime import AgentExecutionWorkdir
    from types import SimpleNamespace

    workdirs = AgentExecutionWorkdir(tmp_path / "state")
    lease = SimpleNamespace(task_id="task-a", generation=2, kind="TRAINING")
    target = workdirs.path_for(lease)
    identity = {"pid": 11, "create_time": 1.0, "command_hash": "a" * 64}
    witness = {
        "task_id": "task-a", "execution_attempt": 2, "assignment_generation": 0,
        "gpu_uuid": "", "proof_type": "PROCESS_STOP_VERIFIED",
        "stop_verified": True, "no_process_launched": False,
        "process_identity": identity,
    }
    workdirs._atomic_write_json(target / "process-stop-verified.json", witness)
    assert workdirs.read_stop_evidence("task-a", 2) == witness
    assert workdirs.read_stop_evidence_present("task-a", 2) is True
    with pytest.raises(ValueError, match="unsettled stop evidence"):
        workdirs.cleanup(lease)

    workdirs.clear_stop_evidence("task-a", 2)
    workdirs.clear_stop_evidence("task-a", 2)
    assert workdirs.read_stop_evidence_present("task-a", 2) is False
    assert workdirs.read_stop_evidence("task-a", 2) is None

    # Coerced lineage fields are not accepted as this execution attempt.
    workdirs._atomic_write_json(
        target / "process-stop-verified.json", dict(witness, execution_attempt="2"),
    )
    with pytest.raises(ValueError, match="lineage mismatch"):
        workdirs.read_stop_evidence("task-a", 2)

    # A directory/symlink-looking witness is unsafe, never "no evidence".
    (target / "process-stop-verified.json").unlink()
    (target / "process-stop-verified.json").mkdir()
    with pytest.raises(ValueError, match="path is unsafe"):
        workdirs.read_stop_evidence("task-a", 2)
    with pytest.raises(ValueError, match="path is unsafe"):
        workdirs.clear_stop_evidence("task-a", 2)

    (target / "process-stop-verified.json").rmdir()
    workdirs.cleanup(lease)
    assert not target.exists()

    # A path-escaping identity is refused before touching the filesystem.
    with pytest.raises(ValueError):
        workdirs.read_stop_evidence("../escape", 1)
    with pytest.raises(ValueError):
        workdirs.clear_stop_evidence("../escape", 1)


@pytest.mark.parametrize("fault", ["missing-state", "slot-mismatch", "missing-hold"])
def test_shared_settlement_rejects_incomplete_slot_contract(fault):
    from platform_core.node_agent_settlement import settlement_error

    local = {**record(), "execution_slots": 1}
    status = {"task_id": "a", "node_id": "node-a", "status": "FAILED",
              "execution_attempt": 1, "execution_slots": 1,
              "assignment_generation": 5, "assignment_state": "RELEASED"}
    if fault == "missing-state":
        status.pop("assignment_state")
    elif fault == "slot-mismatch":
        status["execution_slots"] = 2
    else:
        local["execution_slots"] = status["execution_slots"] = 2
    assert settlement_error(status, local, node_id="node-a")


@pytest.mark.parametrize("fault", [None, "missing-proof", "wrong-proof", "central-process"])
def test_shared_no_launch_settlement_requires_real_dual_proof(fault):
    from platform_core.node_agent_settlement import (
        no_launch_evidence, settlement_error, stop_proof_digests,
    )

    local = {"task_id": "a", "generation": 1, "assignment_generation": 5,
             "gpu_uuid": "GPU-A", "execution_slots": 2, "no_process_launched": True}
    local["no_launch_evidence"] = no_launch_evidence(local)
    status = {"task_id": "a", "node_id": "node-a", "status": "FAILED",
              "execution_attempt": 1, "execution_slots": 2,
              "hold_state": "RELEASED", "hold_execution_attempt": 1,
              "hold_assignment_generation": 5, "hold_gpu_uuid": "GPU-A",
              "proof_type": "NO_PROCESS_LAUNCHED", "process_identity_sha256": None}
    status["proof_sha256"] = stop_proof_digests(status, local)[0]
    if fault == "missing-proof":
        status.pop("proof_sha256")
    elif fault == "wrong-proof":
        status["proof_sha256"] = "0" * 64
    elif fault == "central-process":
        status["process_identity_sha256"] = "a" * 64
    error = settlement_error(status, local, node_id="node-a", expected_status="FAILED")
    assert bool(error) == (fault is not None)


def _pending_resource_wait(tmp_path, slots):
    from platform_core.node_agent_executor_runtime import AgentExecutionWorkdir, RemoteExecutionLease
    from platform_core.node_agent_settlement import canonical_digest, no_launch_evidence, stop_proof_digests

    workdirs = AgentExecutionWorkdir(tmp_path / "state")
    lease = RemoteExecutionLease(task_id="pending", kind="TRAINING", project_id="p", generation=3,
        worker_id="agent:node-a", lease_token="credential-not-for-logs", lease_expires_at="2099-01-01T00:00:00+00:00",
        payload={}, transport={}, execution_slots=slots, assignment={"generation": 5, "node_id": "node-a",
        "resolved_execution_config": {"selected_gpu": {"uuid": "GPU-A"}, "selected_device": "cuda:0"}})
    workdir = workdirs.prepare(lease)
    record = {"task_id": "pending", "generation": 3, "assignment_generation": 5, "gpu_uuid": "GPU-A", "no_process_launched": True}
    request = {"execution_lease_token": lease.lease_token, "execution_generation": 3, "assignment_generation": 5,
        "gpu_uuid": "GPU-A", "no_launch_evidence": no_launch_evidence(record),
        "admission": {"classification": "TEMPORARILY_UNAVAILABLE", "code": "RESOURCE_HOST_MEMORY_INSUFFICIENT",
                      "reason": "RAM busy", "required_bytes": 8, "total_bytes": 32, "available_bytes": 2}}
    workdirs._atomic_write_json(workdir / "resource-wait-request.json", request)
    receipt = {"state": "REQUEUED", "task_id": "pending", "node_id": "node-a", "execution_attempt": 3,
        "assignment_generation": 5, "gpu_uuid": "GPU-A", "request_sha256": canonical_digest(request),
        "proof_type": "NO_PROCESS_LAUNCHED", "proof_sha256": stop_proof_digests({"node_id": "node-a"}, record)[0],
        "execution_slots": slots, "hold_state": "RELEASED" if slots == 2 else None}
    return workdirs, lease, workdir / "resource-wait-request.json", request, receipt


@pytest.mark.parametrize("slots", [1, 2])
@pytest.mark.parametrize("mode", ["receipt", "replay-lost-response", "unavailable", "cancel"])
def test_restart_recovers_original_resource_wait_receipt_without_touching_new_attempt(tmp_path, slots, mode):
    from platform_core.node_agent_executor_runtime import NodeExecutorHTTPError

    workdirs, lease, marker, request, receipt = _pending_resource_wait(tmp_path, slots)
    intent = tmp_path / "slots.json"
    old = {"task_id": "pending", "generation": 5, "assignment_generation": 5, "execution_attempt": 3, "gpu_uuid": "GPU-A"}
    newer = {**old, "generation": 6, "assignment_generation": 6, "execution_attempt": 4}
    original_intents = ([old, newer] if mode == "receipt" else [old]) if slots == 2 else []
    remaining_intents = [newer] if slots == 2 and mode == "receipt" else []
    intent.write_text(json.dumps(original_intents), encoding="utf-8")
    from platform_core.node_agent_execution_slots import BoundedExecutionSlots
    capacity = BoundedExecutionSlots(slots, persist_path=intent)

    class Client:
        node_id = "node-a"
        committed = mode == "receipt"
        offline = mode == "unavailable"
        replays = []
        def resource_wait_receipt(self, task_id, **kwargs):
            assert task_id == "pending" and kwargs == {"assignment_generation": 5, "execution_generation": 3}
            if self.offline:
                raise OSError("credential-not-for-logs")
            if not self.committed:
                raise NodeExecutorHTTPError("RESOURCE_WAIT_RECEIPT_NOT_FOUND", "absent", status_code=404)
            return dict(receipt)
        def execution_status(self, *_args):
            raise AssertionError("must not inspect the task's newer attempt")
        def requeue_resource_wait(self, original, body):
            assert original.task_id == "pending" and body == request
            self.replays.append(body)
            if mode == "cancel":
                raise NodeExecutorHTTPError("CANCELLATION_WON", "cancelled", status_code=409)
            self.committed = True
            raise OSError("lost replay response")

    client = Client()
    coordinator = NodeRecoveryCoordinator(workdirs, FakeController(), client=client, intent_path=intent)
    error = coordinator.prepare()
    assert lease.lease_token not in error
    if mode == "cancel":
        assert error and marker.exists() and not coordinator.retryable
        assert json.loads(intent.read_text()) == original_intents
        return
    if mode == "unavailable":
        assert error and marker.exists() and coordinator.retryable and client.replays == []
        client.offline = False
        client.committed = True
        assert coordinator.prepare() == ""
    else:
        assert error == ""
    assert not marker.exists()
    assert json.loads(intent.read_text()) == remaining_intents
    assert capacity.reconcile_persisted_intent() is (not remaining_intents)
    workdirs.cleanup(lease)
    assert not marker.parent.exists()
    assert len(client.replays) == (1 if mode == "replay-lost-response" else 0)


@pytest.mark.parametrize("fault", ["corrupt", "node", "gpu", "launch", "receipt"])
def test_restart_resource_wait_fails_closed_and_retains_credentials(tmp_path, fault):
    workdirs, lease, marker, request, receipt = _pending_resource_wait(tmp_path, 2)
    if fault == "corrupt":
        marker.write_text('{"credential-not-for-logs":', encoding="utf-8")
    elif fault == "gpu":
        request["gpu_uuid"] = "GPU-wrong"
        workdirs._atomic_write_json(marker, request)
    elif fault == "launch":
        workdirs.begin_process_launch(lease)
    elif fault == "receipt":
        receipt["proof_sha256"] = "0" * 64
    class Client:
        node_id = "other-node" if fault == "node" else "node-a"
        def resource_wait_receipt(self, *_args, **_kwargs):
            return receipt
        def requeue_resource_wait(self, *_args, **_kwargs):
            raise AssertionError("invalid request must not replay")
    error = NodeRecoveryCoordinator(workdirs, FakeController(), client=Client()).prepare()
    assert error and lease.lease_token not in error and marker.exists()
    with pytest.raises(ValueError):
        workdirs.cleanup(lease)
    assert marker.exists()
