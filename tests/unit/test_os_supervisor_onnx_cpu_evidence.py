"""2D-2D2B1 CPU-only root evidence join negative/security contracts.

This unit suite has no external model downloads, process spawning or GPU.
"""
from __future__ import annotations

from dataclasses import replace
import json

import pytest

from platform_core.os_supervisor_authorization import GrantRejected
from platform_core.os_supervisor_conversion_adapter import (
    FrozenOnnxInput, VerifiedOnnxBytes,
)
from platform_core.os_supervisor_cpu_systemd import FixedCpuSystemd
from platform_core.os_supervisor_onnx_cpu_systemd_pilot import StagedOnnxCpuPilot
from platform_core.os_supervisor_onnx_cpu_evidence import (
    IsolatedCpuOnnxEvidence, verify_isolated_onnx_cpu_evidence,
)

HANDLE = "a" * 32
INVOCATION = "b" * 32
SOURCE = "c" * 64
INPUT = "d" * 64
OUTPUT = "e" * 64
UNIT = "changlian-os-" + HANDLE + ".service"


def fixture():
    frozen = FrozenOnnxInput(
        task_id="conversion_test001", task_attempt=4,
        worker_id="agent:ci-node", node_id="ci-node",
        lease_sha256="f" * 64, source_sha256=SOURCE,
        source_size_bytes=123, source_name="model.onnx",
    )
    verified = VerifiedOnnxBytes(SOURCE, 123)
    staged = StagedOnnxCpuPilot(
        HANDLE, __import__("pathlib").Path("/run/changlian-os-onnx-pilot-" + HANDLE),
        SOURCE, 123,
    )
    first = {
        "unit_name": UNIT, "invocation_id": INVOCATION,
        "control_group": "/system.slice/" + UNIT,
        "main_pid": 1234, "exec_main_pid": "1234",
        "active_state": "active", "sub_state": "running",
        "trusted_stop_receipt_available": False,
        "production_launch_allowed": False,
        "central_recovery_allowed": False,
    }
    record = {
        "model_sha256": SOURCE, "input_sha256": INPUT,
        "output_sha256": OUTPUT,
        "input_shape": [1, 3, 32, 32],
        "output_shape": [1, 3, 32, 32],
        "provider": "CPUExecutionProvider", "onnxruntime_version": "1.22.1",
    }
    log = ("starting\nchanglian-onnx-ort-result:" +
           json.dumps(record, separators=(",", ":")) + "\n").encode()
    return frozen, verified, staged, first, log


class FakeRootOS(FixedCpuSystemd):
    def __init__(self, pages):
        # No parent init. OS interactions are simulated only in unit tests.
        self.pages = list(pages)
        self.calls = []
        self.final = {}

    def verified_natural_exit(
            self, unit, invocation, *,
            original_control_group, original_main_pid):
        self.calls.append(("terminal", unit, invocation, original_main_pid))
        assert unit == UNIT and invocation == INVOCATION
        assert original_control_group == "/system.slice/" + UNIT
        assert original_main_pid == 1234
        return {
            "invocation_id": INVOCATION, "main_pid": 1234,
            "exit_code": 0, "unit_result": "success",
            "cgroup_exit_type_verified": True,
            "trusted_stop_receipt_available": False,
            **self.final,
        }

    def read_log_page(self, unit, invocation, *, cursor=None):
        self.calls.append(("log", unit, invocation, cursor))
        assert unit == UNIT and invocation == INVOCATION
        if not self.pages:
            return {"data": b"", "cursor": cursor,
                    "offset_contract_available": True,
                    "trusted_stop_receipt_available": False}
        page = self.pages.pop(0)
        return {
            "offset_contract_available": True,
            "trusted_stop_receipt_available": False,
            **page,
        }


def approved_args():
    frozen, verified, staged, first, log = fixture()
    backend = FakeRootOS([{"data": log, "cursor": "s=ci-onnx;i=1"}])
    return dict(
        frozen=frozen, verified=verified, staged=staged,
        first=first, backend=backend,
        expected_input_sha256=INPUT,
        expected_output_sha256=OUTPUT,
    )


def test_root_os_identity_and_actual_ort_log_join_is_diagnostic_only():
    kw = approved_args()
    receipt = verify_isolated_onnx_cpu_evidence(**kw)
    assert isinstance(receipt, IsolatedCpuOnnxEvidence)
    assert receipt.task_id == "conversion_test001"
    assert receipt.task_attempt == 4
    assert receipt.unit_name == UNIT
    assert receipt.invocation_id == INVOCATION
    assert receipt.original_main_pid == 1234
    assert receipt.model_cpu_provider == "CPUExecutionProvider"
    assert not receipt.model_was_converted
    assert not receipt.central_lease_verified
    assert not receipt.business_result_verified
    assert not receipt.trusted_stop_receipt_available
    assert not receipt.automatic_reassignment_allowed
    assert not receipt.result_publish_allowed
    assert not receipt.production_launch_allowed
    assert kw["backend"].calls == [
        ("terminal", UNIT, INVOCATION, 1234),
        ("log", UNIT, INVOCATION, None),
        ("log", UNIT, INVOCATION, "s=ci-onnx;i=1"),
    ]


@pytest.mark.parametrize("field,value", [
    ("source_sha256", "0" * 64), ("source_size_bytes", 124),
    ("task_attempt", 0), ("profile", "shell-v1"),
])
def test_invalid_frozen_identity_blocks_before_any_os_call(field, value):
    kw = approved_args()
    kw["frozen"] = replace(kw["frozen"], **{field: value})
    with pytest.raises(GrantRejected, match="HOLD"):
        verify_isolated_onnx_cpu_evidence(**kw)
    assert kw["backend"].calls == []


@pytest.mark.parametrize("field,value", [
    ("source_sha256", "0" * 64), ("size_bytes", True),
])
def test_invalid_verified_bytes_blocks_before_any_os_call(field, value):
    kw = approved_args()
    kw["verified"] = replace(kw["verified"], **{field: value})
    with pytest.raises(GrantRejected, match="HOLD"):
        verify_isolated_onnx_cpu_evidence(**kw)
    assert kw["backend"].calls == []


@pytest.mark.parametrize("field,value", [
    ("sha256", "0" * 64), ("size_bytes", 124),
    ("production_launch_allowed", True),
    ("trusted_stop_receipt_available", True),
    ("handle", "invalid"),
])
def test_staged_scope_mismatch_blocks_before_any_os_call(field, value):
    kw = approved_args()
    kw["staged"] = replace(kw["staged"], **{field: value})
    with pytest.raises(GrantRejected, match="HOLD"):
        verify_isolated_onnx_cpu_evidence(**kw)
    assert kw["backend"].calls == []


@pytest.mark.parametrize("field,value", [
    ("unit_name", "changlian-os-" + "d" * 32 + ".service"),
    ("invocation_id", "d" * 32),
    ("control_group", "/wrong/cgroup"),
    ("main_pid", 0),
    ("main_pid", True),
    ("exec_main_pid", "999"),
    ("active_state", "failed"),
    ("sub_state", "exited"),
    ("trusted_stop_receipt_available", True),
    ("production_launch_allowed", True),
    ("central_recovery_allowed", True),
])
def test_original_os_identity_tamper_blocks_without_query(field, value):
    kw = approved_args()
    kw["first"][field] = value
    with pytest.raises(GrantRejected, match="HOLD"):
        verify_isolated_onnx_cpu_evidence(**kw)
    assert kw["backend"].calls == []


@pytest.mark.parametrize("field,value", [
    ("exit_code", 1), ("exit_code", True),
    ("unit_result", "exit-code"),
    ("invocation_id", "d" * 32), ("main_pid", 999),
    ("cgroup_exit_type_verified", False),
    ("trusted_stop_receipt_available", True),
])
def test_terminal_cannot_be_replaced_by_exit_code_or_stop_ack(field, value):
    kw = approved_args()
    kw["backend"].final[field] = value
    with pytest.raises(GrantRejected, match="HOLD"):
        verify_isolated_onnx_cpu_evidence(**kw)
    assert kw["backend"].calls[0][0] == "terminal"
    assert all(x[0] != "log" for x in kw["backend"].calls)


def test_original_journal_cursor_paginates_with_bounded_logs():
    kw = approved_args()
    original = kw["backend"].pages[0]["data"]
    marker = b"changlian-onnx-ort-result:"
    a = original.split(marker)[0]
    b = marker + original.split(marker)[1]
    kw["backend"].pages = [
        {"data": a, "cursor": "s=ci-onnx;i=1"},
        {"data": b, "cursor": "s=ci-onnx;i=2"},
    ]
    assert verify_isolated_onnx_cpu_evidence(**kw).source_sha256 == SOURCE
    assert [x[3] for x in kw["backend"].calls if x[0] == "log"] == [
        None, "s=ci-onnx;i=1", "s=ci-onnx;i=2",
    ]


def test_journal_reused_cursor_is_a_hard_fail_not_infinite_loop():
    kw = approved_args()
    kw["backend"].pages = [
        {"data": b"first\n", "cursor": "s=ci-onnx;i=1"},
        {"data": kw["backend"].pages[0]["data"],
         "cursor": "s=ci-onnx;i=1"},
    ]
    with pytest.raises(GrantRejected, match="CURSOR_UNVERIFIED_HOLD"):
        verify_isolated_onnx_cpu_evidence(**kw)


@pytest.mark.parametrize("override", [
    {"data": b"x" * 8193},
    {"data": "not-bytes"},
    {"data": b"not-empty", "cursor": None},
    {"data": b"any", "cursor": "invalid"},
    {"offset_contract_available": False},
    {"trusted_stop_receipt_available": True},
])
def test_invalid_log_page_is_rejected(override):
    kw = approved_args()
    page = kw["backend"].pages[0]
    page.update(override)
    with pytest.raises(GrantRejected, match="HOLD"):
        verify_isolated_onnx_cpu_evidence(**kw)


def test_log_without_unique_result_or_more_than_eight_pages_is_hold():
    kw = approved_args()
    kw["backend"].pages = [{"data": b"no result\n", "cursor": "s=ci-onnx;i=1"}]
    with pytest.raises(GrantRejected, match="RESULT_MISSING_HOLD"):
        verify_isolated_onnx_cpu_evidence(**kw)
    kw = approved_args()
    kw["backend"].pages = [
        {"data": b"noise\n", "cursor": f"s=ci-onnx;i={i}"}
        for i in range(1, 9)
    ]
    with pytest.raises(GrantRejected, match="LOG_INCOMPLETE_HOLD"):
        verify_isolated_onnx_cpu_evidence(**kw)


@pytest.mark.parametrize("field,value", [
    ("model_sha256", "0" * 64),
    ("output_sha256", "0" * 64),
    ("provider", "CUDAExecutionProvider"),
    ("onnxruntime_version", "0.0.0"),
    ("input_shape", [1, 3, 64, 64]),
])
def test_parsed_ort_diagnostic_cannot_claim_altered_result(field, value):
    kw = approved_args()
    _, _, _, _, original = fixture()
    line = next(x for x in original.decode().splitlines()
                if x.startswith("changlian-onnx-ort-result:"))
    record = json.loads(line.split(":", 1)[1])
    record[field] = value
    kw["backend"].pages = [{
        "data": ("changlian-onnx-ort-result:" + json.dumps(record) + "\n").encode(),
        "cursor": "s=ci-onnx;i=1",
    }]
    with pytest.raises(GrantRejected, match="HOLD"):
        verify_isolated_onnx_cpu_evidence(**kw)


def test_independent_oracle_digest_mismatch_denies_success():
    kw = approved_args()
    kw["expected_output_sha256"] = "0" * 64
    with pytest.raises(GrantRejected, match="INFERENCE_ORACLE_MISMATCH_HOLD"):
        verify_isolated_onnx_cpu_evidence(**kw)
