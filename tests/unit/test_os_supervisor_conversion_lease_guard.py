"""2D-2D2A central lease vs OS status fail-closed bridge contracts."""
from __future__ import annotations

import base64
from dataclasses import replace
import hashlib

import pytest

from platform_core.node_agent_executor_runtime import (
    ExecutionLeaseMonitor, NodeExecutorClient, NodeExecutorHTTPError,
    RemoteExecutionLease,
)
from platform_core.os_supervisor_conversion_adapter import (
    FrozenOnnxInput, SupervisedConversionHandle,
)
from platform_core.os_supervisor_conversion_lease_guard import (
    SupervisedConversionLeaseGuard, LeaseBoundOsSnapshot,
)
from platform_core.os_supervisor_protocol import (
    SupervisedProcessHandle, SupervisorProtocolError,
)


SOURCE = b"bounded frozen onnx dummy bytes; no model executes in these unit tests"
SHA = hashlib.sha256(SOURCE).hexdigest()


def lease(**changes):
    payload = {
        "schema_version": 1,
        "task_kind": "MODEL_CONVERSION",
        "transport": "object-storage-v1",
        "target": "onnx",
        "params": {"opset": 12},
        "source": {"type": "object", "download": {
            "method": "GET", "file_name": "safe.onnx",
            "size_bytes": len(SOURCE), "sha256": SHA}},
        "source_trace": {"sha256": SHA},
        "output": {"type": "object", "storage_ref": {"object_key": "test"},
                   "upload_protocol": "prepare-after-local-hash-v1"},
    }
    return RemoteExecutionLease(
        task_id="conversion_test987", kind="MODEL_CONVERSION",
        project_id="isolated", generation=4,
        lease_token=changes.get("lease_token", "central-fixed-execution-token"),
        lease_expires_at="2026-11-18T12:00:00+00:00",
        worker_id=changes.get("worker_id", "agent:pilot-node"),
        payload=payload, assignment={}, transport={},
    )


class FakeCentral(NodeExecutorClient):
    def __init__(self):
        self.node_id = "pilot-node"
        self.receipts = []
        self.calls = 0
        self.failure = None

    def heartbeat(self, remote_lease, **_kwargs):
        self.calls += 1
        if self.failure:
            raise self.failure
        if self.receipts:
            item = self.receipts.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return {"cancel_requested": False, "task": {"status": "RUNNING"}}


class FakeSupervisor:
    def __init__(self):
        self.calls = []
        self.state = "RUNNING"
        self.code = 0
        self.fail = False

    def call(self, action, payload):
        self.calls.append((action, payload))
        if self.fail:
            raise SupervisorProtocolError("TEST_UNIX_DISCONNECTED_HOLD")
        if action == "inspect":
            return {"ok": True, "result": {
                "state": self.state, "exit_code": self.code,
            }}
        if action == "read_log":
            return {"ok": True, "result": {
                "encoding": "base64", "offset_contract_available": True,
                "data_base64": base64.b64encode(b"pilot-log\n").decode("ascii"),
                "cursor": "s=pilotlog;i=1",
            }}
        raise AssertionError("Unexpected stop/launch/upload operation: " + action)


def guard_factory():
    current = lease()
    central = FakeCentral()
    supervisor = FakeSupervisor()
    frozen = FrozenOnnxInput.from_lease(current)
    observer = SupervisedConversionHandle(
        frozen_input=frozen,
        os_handle=SupervisedProcessHandle(
            client=supervisor, handle_id="a" * 32,
            execution_generation=current.generation),
    )
    monitor = ExecutionLeaseMonitor(central, current, interval=60)
    guard = SupervisedConversionLeaseGuard(
        lease=current, observer=observer, monitor=monitor)
    return current, central, supervisor, monitor, guard, observer


def test_running_and_exit_zero_stay_diagnostic_with_original_attempt():
    current, central, os_rpc, monitor, guard, observer = guard_factory()
    running = guard.observe_once()
    assert running == LeaseBoundOsSnapshot(
        task_id=current.task_id, task_attempt=current.generation,
        os_state="RUNNING_OR_STARTING", os_exit_code=None)
    assert running.central_lease_verified_now
    assert not running.trusted_stop_receipt_available
    assert not running.central_recovery_allowed
    assert not running.result_publish_allowed
    assert not running.production_launch_allowed
    os_rpc.state = "EXITED"
    terminal = guard.observe_once()
    assert terminal.os_state == "EXITED"
    assert terminal.os_exit_code == 0
    assert not terminal.result_publish_allowed
    assert not hasattr(guard, "start")
    assert not hasattr(guard, "finish")
    assert not hasattr(guard, "kill")
    assert [name for name, _ in os_rpc.calls] == ["inspect", "inspect"]
    assert central.calls == 2
    assert not guard.permanently_held


def test_log_page_revalidates_central_lease_and_never_stops():
    _lease, central, os_rpc, monitor, guard, observer = guard_factory()
    assert guard.read_log_page()["data"] == b"pilot-log\n"
    assert guard.read_log_page("s=pilotlog;i=1")["cursor"] == "s=pilotlog;i=1"
    assert central.calls == 2
    assert [name for name, _ in os_rpc.calls] == ["read_log", "read_log"]
    with pytest.raises(SupervisorProtocolError, match="TRUSTED_STOP_NOT_IMPLEMENTED"):
        guard.request_stop()
    with pytest.raises(SupervisorProtocolError, match="RESULT_TRANSACTION_NOT_IMPLEMENTED"):
        guard.publish_result()
    assert len(os_rpc.calls) == 2


@pytest.mark.parametrize("response", [
    {},
    {"task": {"status": "RUNNING"}},
    {"cancel_requested": "false", "task": {"status": "RUNNING"}},
    {"cancel_requested": None, "task": {"status": "RUNNING"}},
    {"cancel_requested": True, "task": {"status": "CANCEL_REQUESTED"}},
    {"cancel_requested": False, "task": {}},
    {"cancel_requested": False, "task": {"status": "SUCCEEDED"}},
    {"cancel_requested": False, "task": {"status": "QUEUED"}},
    {"cancel_requested": False, "task": {"status": "RUNNING", "task_id": "other"}},
    {"cancel_requested": False, "task": {"status": "RUNNING", "worker_id": "agent:other"}},
    {"cancel_requested": False, "task": {"status": "RUNNING", "attempt": 5}},
    {"cancel_requested": False, "task": {"status": "RUNNING", "generation": True}},
    {"cancel_requested": False, "task": {"status": "RUNNING"}, "execution_generation": 3},
    [],
    "not an object",
])
def test_invalid_central_receipt_latches_hold_before_any_os_rpc(response):
    _lease, central, os_rpc, monitor, guard, observer = guard_factory()
    central.receipts = [response]
    with pytest.raises(SupervisorProtocolError, match="HOLD"):
        guard.observe_once()
    assert guard.permanently_held
    assert not os_rpc.calls
    assert central.calls == 1
    with pytest.raises(SupervisorProtocolError, match="ALREADY_FENCED_HOLD"):
        guard.observe_once()
    with pytest.raises(SupervisorProtocolError, match="ALREADY_FENCED_HOLD"):
        guard.read_log_page()
    assert central.calls == 1


def test_central_cancel_event_is_not_a_stop_receipt():
    current, central, os_rpc, monitor, guard, observer = guard_factory()
    central.receipts = [{"cancel_requested": True, "task": {"status": "CANCEL_REQUESTED"}}]
    with pytest.raises(SupervisorProtocolError, match="HOLD"):
        guard.observe_once()
    assert guard.permanently_held
    assert monitor.cancel_requested.is_set()
    assert not os_rpc.calls


def test_transport_outage_and_failed_lease_renewal_no_retry():
    _lease, central, os_rpc, monitor, guard, observer = guard_factory()
    central.failure = NodeExecutorHTTPError(
        "TEST_LEASE_EXPIRED", "isolated lease revoked", status_code=409)
    with pytest.raises(SupervisorProtocolError, match="LEASE_UNVERIFIED_HOLD"):
        guard.observe_once()
    assert monitor.fenced.is_set()
    assert guard.permanently_held
    central.failure = None
    with pytest.raises(SupervisorProtocolError, match="ALREADY_FENCED_HOLD"):
        guard.observe_once()
    assert central.calls == 1 and os_rpc.calls == []


def test_unknown_or_disconnected_os_after_valid_heartbeat_latches_hold():
    _lease, central, os_rpc, monitor, guard, observer = guard_factory()
    os_rpc.state = "UNKNOWN"
    with pytest.raises(SupervisorProtocolError, match="HOLD"):
        guard.observe_once()
    assert central.calls == 1
    assert guard.permanently_held
    os_rpc.state = "RUNNING"
    with pytest.raises(SupervisorProtocolError, match="ALREADY_FENCED_HOLD"):
        guard.observe_once()
    assert central.calls == 1
    _lease, central, os_rpc, monitor, guard, observer = guard_factory()
    os_rpc.fail = True
    with pytest.raises(SupervisorProtocolError, match="HOLD"):
        guard.read_log_page()
    assert central.calls == 1 and guard.permanently_held


@pytest.mark.parametrize("case", [
    "different_lease_object", "different_attempt", "different_node",
    "wrong_frozen_identity", "wrong_os_generation",
])
def test_binding_cannot_mix_original_lease_and_remote_os_handle(case):
    current, central, os_rpc, monitor, guard, observer = guard_factory()
    candidate = current
    if case == "different_lease_object":
        candidate = replace(current)
    elif case == "different_attempt":
        candidate = replace(current, generation=5)
    elif case == "different_node":
        central.node_id = "elsewhere"
    elif case == "wrong_frozen_identity":
        observer = replace(observer, frozen_input=replace(
            observer.frozen_input, source_sha256="0" * 64))
    elif case == "wrong_os_generation":
        observer = replace(observer, os_handle=SupervisedProcessHandle(
            os_rpc, "a" * 32, current.generation + 1))
    with pytest.raises(SupervisorProtocolError, match="HOLD"):
        SupervisedConversionLeaseGuard(
            lease=candidate, observer=observer, monitor=monitor)


def test_heartbeat_identity_fields_are_checked_when_server_supplies_them():
    current, central, os_rpc, monitor, guard, observer = guard_factory()
    central.receipts = [{
        "cancel_requested": False,
        "task": {"status": "RUNNING",
                 "task_id": current.task_id, "worker_id": current.worker_id,
                 "attempt": current.generation, "generation": current.generation},
        "execution_generation": current.generation,
    }]
    assert guard.observe_once().os_state == "RUNNING_OR_STARTING"
    assert not guard.permanently_held


def test_guard_refuses_legacy_direct_process_stop_callback():
    current, central, os_rpc, monitor, guard, observer = guard_factory()
    monitor.on_fenced = lambda: (_ for _ in ()).throw(
        AssertionError("must never invoke legacy direct process kill"))
    with pytest.raises(SupervisorProtocolError, match="ORIGINAL_OWNER_INVALID_HOLD"):
        SupervisedConversionLeaseGuard(
            lease=current, observer=observer, monitor=monitor)
    monitor.on_fenced = None
    monitor._thread = object()  # any previously scheduled renewal is rejected
    with pytest.raises(SupervisorProtocolError, match="ORIGINAL_OWNER_INVALID_HOLD"):
        SupervisedConversionLeaseGuard(
            lease=current, observer=observer, monitor=monitor)
    assert central.calls == 0 and os_rpc.calls == []


def test_preexisting_cancel_flag_blocks_even_without_http_request():
    current, central, os_rpc, monitor, guard, observer = guard_factory()
    monitor.cancel_requested.set()
    with pytest.raises(SupervisorProtocolError, match="LEASE_UNVERIFIED_HOLD"):
        guard.observe_once()
    assert central.calls == 0
    assert os_rpc.calls == []
    assert guard.permanently_held


def test_midflight_cancellation_prevents_further_os_log_observation():
    current, central, os_rpc, monitor, guard, observer = guard_factory()
    assert guard.read_log_page()["data"] == b"pilot-log\n"
    central.receipts = [{
        "cancel_requested": True, "task": {"status": "CANCEL_REQUESTED"}}]
    with pytest.raises(SupervisorProtocolError, match="HOLD"):
        guard.read_log_page()
    assert central.calls == 2
    assert [action for action, _ in os_rpc.calls] == ["read_log"]
    assert guard.permanently_held
