"""2D-2D1 isolated read-only conversion/OS admission; no business Runner."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import base64
import hashlib

import pytest

from platform_core.node_agent_executor_runtime import RemoteExecutionLease
from platform_core.os_supervisor_cpu_network_pilot import IsolatedCpuNetworkPilot
from platform_core.os_supervisor_conversion_adapter import (
    FrozenOnnxInput, SupervisedConversionHandle, VerifiedOnnxBytes,
)
from platform_core.os_supervisor_protocol import (
    SupervisedProcessHandle, SupervisorProtocolError,
)


SOURCE = b"test-only frozen source bytes (not a valid ONNX model)"
DIGEST = hashlib.sha256(SOURCE).hexdigest()


def make_lease(**changes):
    payload = {
        "schema_version": 1, "task_kind": "MODEL_CONVERSION",
        "transport": "object-storage-v1", "target": "onnx",
        "params": {"opset": 12},
        "source": {"type": "object", "download": {
            "method": "GET", "file_name": "model.onnx",
            "size_bytes": len(SOURCE), "sha256": DIGEST,
        }},
        "source_trace": {"sha256": DIGEST},
        "output": {"type": "object", "storage_ref": {"object_key": "ci/test"},
                   "upload_protocol": "prepare-after-local-hash-v1"},
    }
    return RemoteExecutionLease(
        task_id=changes.get("task_id", "conv_cpu_test123"),
        kind=changes.get("kind", "MODEL_CONVERSION"),
        project_id="test", generation=changes.get("generation", 3),
        lease_token=changes.get("lease_token", "fixed-central-lease"),
        lease_expires_at="2026-11-16T00:00:00+00:00",
        worker_id=changes.get("worker_id", "agent:linux2"),
        payload=changes.get("payload", payload),
        assignment={}, transport={},
    )


def test_freezes_original_task_attempt_and_validates_exact_bytes():
    lease = make_lease()
    frozen = FrozenOnnxInput.from_lease(lease)
    assert frozen.task_attempt == lease.generation
    assert frozen.node_id == "linux2"
    assert frozen.lease_sha256 == hashlib.sha256(
        lease.lease_token.encode()).hexdigest()
    assert lease.lease_token not in repr(frozen)
    assert frozen.profile == "onnx-cpu-readonly-v1"
    proof = frozen.verify_source_stream([SOURCE[:4], SOURCE[4:]])
    assert proof == VerifiedOnnxBytes(DIGEST, len(SOURCE))
    assert not hasattr(frozen, "source_url")
    with pytest.raises(FrozenInstanceError):
        frozen.task_attempt = 123


@pytest.mark.parametrize("chunks", [
    [b"corrupt"], [SOURCE[:-1]], [SOURCE + b"extra"],
    [SOURCE, b"extra"],
])
def test_rejects_truncated_changed_or_oversized_source(chunks):
    frozen = FrozenOnnxInput.from_lease(make_lease())
    with pytest.raises(SupervisorProtocolError, match="HOLD"):
        frozen.verify_source_stream(chunks)


def test_rejects_nonbyte_stream_or_wrong_chunk_type():
    frozen = FrozenOnnxInput.from_lease(make_lease())
    with pytest.raises(SupervisorProtocolError, match="HOLD"):
        frozen.verify_source_stream(SOURCE)
    with pytest.raises(SupervisorProtocolError, match="HOLD"):
        frozen.verify_source_stream([memoryview(SOURCE)])


@pytest.mark.parametrize("overrides", [
    {"target": "rockchip"},
    {"calibration": {"items": []}},
    {"source": {"type": "object", "download": {
        "method": "GET", "file_name": "../evil.onnx",
        "size_bytes": len(SOURCE), "sha256": DIGEST}}},
    {"source": {"type": "object", "download": {
        "method": "GET", "file_name": "evil.pt",
        "size_bytes": len(SOURCE), "sha256": DIGEST}}},
    {"source": {"type": "object", "download": {
        "method": "GET", "file_name": "model.onnx",
        "size_bytes": True, "sha256": DIGEST}}},
    {"source_trace": {"sha256": "0"*64}},
    {"command": ["python", "-c", "danger"]},
    {"params": {"shell": True}},
    {"output": {"type": "object", "storage_ref": {},
                "upload_protocol": "raw-upload"}},
])
def test_rejects_unsupported_or_injected_conversion_scope(overrides):
    p = dict(make_lease().payload)
    p.update(overrides)
    with pytest.raises(SupervisorProtocolError, match="HOLD"):
        FrozenOnnxInput.from_lease(make_lease(payload=p))


@pytest.mark.parametrize("kwargs", [
    {"kind": "TRAINING"}, {"generation": 0}, {"generation": True},
    {"worker_id": "worker:local"}, {"worker_id": "agent:evil/foo"},
    {"task_id": "../unsafe-task"}, {"lease_token": ""},
])
def test_rejects_wrong_central_lease_identity(kwargs):
    with pytest.raises(SupervisorProtocolError, match="HOLD"):
        FrozenOnnxInput.from_lease(make_lease(**kwargs))


class FakeRpc:
    def __init__(self):
        self.state = "RUNNING"
        self.exit_code = 0
        self.calls = []

    def call(self, action, payload):
        self.calls.append((action, payload))
        if action == "inspect":
            return {"ok": True, "result": {
                "state": self.state, "exit_code": self.exit_code}}
        if action == "read_log":
            return {"ok": True, "result": {
                "encoding": "base64", "offset_contract_available": True,
                "data_base64": base64.b64encode(b"cpu log\n").decode(),
                "cursor": "s=cpu2d1;i=1"}}
        raise AssertionError("unexpected OS operation: " + action)


def make_pilot(lease=None):
    lease = lease or make_lease()
    rpc = FakeRpc()
    # Test-only stand-in for a pilot already launched by the prior 2D-2C3 E2E.
    pilot = IsolatedCpuNetworkPilot.__new__(IsolatedCpuNetworkPilot)
    pilot.task_id = lease.task_id
    pilot.node_id = lease.worker_id.removeprefix("agent:")
    pilot.generation = lease.generation
    pilot.execution_lease_token = lease.lease_token
    pilot.supervisor = rpc
    pilot.handle = SupervisedProcessHandle(rpc, "a" * 32, lease.generation)
    pilot._launch_attempted = True
    frozen = FrozenOnnxInput.from_lease(lease)
    proof = frozen.verify_source_stream([SOURCE])
    return lease, pilot, proof, rpc


def test_os_observation_never_promotes_exit_to_conversion_success():
    lease, pilot, proof, rpc = make_pilot()
    adapter = SupervisedConversionHandle.bind_isolated_cpu_pilot(
        lease, pilot, proof)
    running = adapter.observe()
    assert running.os_state == "RUNNING_OR_STARTING"
    assert running.os_exit_code is None
    rpc.state = "EXITED"
    done = adapter.observe()
    assert done.os_state == "EXITED" and done.os_exit_code == 0
    assert not done.business_result_verified
    assert not done.production_launch_allowed
    assert not done.result_publish_allowed
    assert not done.trusted_stop_receipt_available
    assert adapter.read_log_page()["data"] == b"cpu log\n"
    with pytest.raises(SupervisorProtocolError, match="STOP_RECEIPT_UNAVAILABLE_HOLD"):
        adapter.request_stop()
    with pytest.raises(SupervisorProtocolError, match="RESULT_NOT_VERIFIED_HOLD"):
        adapter.publish_result()
    assert not any(action in ("stop", "start", "start_rechecked")
                   for action, _ in rpc.calls)
    assert not hasattr(adapter, "pid")
    assert not hasattr(adapter, "kill")


@pytest.mark.parametrize("change", [
    "task_id", "generation", "worker_id", "lease_token", "handle",
    "not_launched", "wrong_client", "wrong_proof", "bad_handle_id",
])
def test_rejects_cross_task_or_ambiguous_os_handle(change):
    lease, pilot, proof, rpc = make_pilot()
    if change == "task_id":
        pilot.task_id = "another_task123"
    elif change == "generation":
        pilot.generation += 1
    elif change == "worker_id":
        pilot.node_id = "other"
    elif change == "lease_token":
        pilot.execution_lease_token = "different-lease"
    elif change == "handle":
        pilot.handle = SupervisedProcessHandle(rpc, "a" * 32, lease.generation + 1)
    elif change == "not_launched":
        pilot._launch_attempted = False
    elif change == "wrong_client":
        pilot.handle = SupervisedProcessHandle(FakeRpc(), "a" * 32,
                                               lease.generation)
    elif change == "wrong_proof":
        proof = replace(proof, source_sha256="0" * 64)
    elif change == "bad_handle_id":
        pilot.handle = SupervisedProcessHandle(rpc, "unsafe", lease.generation)
    with pytest.raises(SupervisorProtocolError, match="HOLD"):
        SupervisedConversionHandle.bind_isolated_cpu_pilot(
            lease, pilot, proof)


def test_unknown_or_invalid_os_exit_fails_closed():
    lease, pilot, proof, rpc = make_pilot()
    adapter = SupervisedConversionHandle.bind_isolated_cpu_pilot(
        lease, pilot, proof)
    rpc.state = "UNKNOWN"
    with pytest.raises(SupervisorProtocolError, match="HOLD"):
        adapter.observe()
    rpc.state = "EXITED"
    rpc.exit_code = None
    with pytest.raises(SupervisorProtocolError, match="HOLD"):
        adapter.observe()
