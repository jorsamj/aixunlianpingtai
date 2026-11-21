"""2D-2D2B1: isolated root CPU ONNX runtime execution evidence.

This verifies a pinned *existing ONNX* CPU inference, NOT PT->ONNX conversion.
It is not imported by Agent/production Runner/SupervisorService. Root-side
staging and the OS backend must be independently trusted by their caller.
No central grant, task finish, StopReceipt, GPU or recovery permission results.
"""
from __future__ import annotations

from dataclasses import dataclass
import hmac
from pathlib import Path
import re
from typing import Mapping

from .os_supervisor_authorization import GrantRejected
from .os_supervisor_conversion_adapter import FrozenOnnxInput, VerifiedOnnxBytes
from .os_supervisor_cpu_systemd import FixedCpuSystemd
from .os_supervisor_onnx_cpu_systemd_pilot import StagedOnnxCpuPilot
from .os_supervisor_onnx_cpu_ort_systemd_pilot import parse_ort_result_log

_HANDLE = re.compile(r"[0-9a-f]{32}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CURSOR = re.compile(r"s=[A-Za-z0-9=;:._+-]{1,510}\Z")
_MAX_PAGES = 8
_MAX_PAGE_BYTES = 8192


def _hold(code: str) -> None:
    raise GrantRejected(code + "_HOLD")


@dataclass(frozen=True, slots=True)
class IsolatedCpuOnnxEvidence:
    """Diagnostic-only: no central owner assertion or release capability."""

    task_id: str
    task_attempt: int
    source_sha256: str
    unit_name: str
    invocation_id: str
    original_main_pid: int
    input_sha256: str
    output_sha256: str
    model_cpu_provider: str = "CPUExecutionProvider"
    model_was_converted: bool = False
    central_lease_verified: bool = False
    business_result_verified: bool = False
    trusted_stop_receipt_available: bool = False
    automatic_reassignment_allowed: bool = False
    result_publish_allowed: bool = False
    production_launch_allowed: bool = False


def verify_isolated_onnx_cpu_evidence(
        *, frozen: FrozenOnnxInput, verified: VerifiedOnnxBytes,
        staged: StagedOnnxCpuPilot, first: Mapping[str, object],
        backend: FixedCpuSystemd,
        expected_input_sha256: str,
        expected_output_sha256: str) -> IsolatedCpuOnnxEvidence:
    """Join original, trusted root OS snapshot, actual journal and exit.

    The independent expected output hash is a **CI test oracle** for a fixed
    Identity ONNX fixture; never accept it as an Agent-uploaded permission.
    The first OS snapshot is supplied by the trusted root pilot after launch;
    it is NOT accepted as self-authenticating Agent JSON in production.
    """
    if (type(frozen) is not FrozenOnnxInput
            or type(verified) is not VerifiedOnnxBytes
            or type(staged) is not StagedOnnxCpuPilot
            or not isinstance(backend, FixedCpuSystemd)
            or not isinstance(first, Mapping)):
        _hold("CPU_EVIDENCE_TYPE_UNTRUSTED")
    if (type(frozen.task_attempt) is not int or frozen.task_attempt <= 0
            or frozen.profile != "onnx-cpu-readonly-v1"
            or not isinstance(frozen.source_sha256, str)
            or not _SHA256.fullmatch(frozen.source_sha256)
            or type(frozen.source_size_bytes) is not int
            or not 0 < frozen.source_size_bytes <= 64 * 1024 * 1024
            or not isinstance(verified.source_sha256, str)
            or not hmac.compare_digest(
                frozen.source_sha256, verified.source_sha256)
            or type(verified.size_bytes) is not int
            or verified.size_bytes != frozen.source_size_bytes
            or staged.sha256 != frozen.source_sha256
            or staged.size_bytes != frozen.source_size_bytes
            or staged.production_launch_allowed is not False
            or staged.trusted_stop_receipt_available is not False):
        _hold("CPU_EVIDENCE_FROZEN_INPUT_MISMATCH")
    h = staged.handle
    if (not isinstance(h, str) or not _HANDLE.fullmatch(h)
            or staged.root != Path("/run") / ("changlian-os-onnx-pilot-" + h)):
        _hold("CPU_EVIDENCE_STAGED_SCOPE_INVALID")
    unit = "changlian-os-" + h + ".service"
    invocation = first.get("invocation_id")
    pid = first.get("main_pid")
    if (not isinstance(invocation, str)
            or not _HANDLE.fullmatch(invocation)
            or first.get("unit_name") != unit
            or first.get("control_group") != "/system.slice/" + unit
            or type(pid) is not int or pid <= 1
            or first.get("exec_main_pid") != str(pid)
            or first.get("active_state") != "active"
            or first.get("sub_state") != "running"
            or first.get("trusted_stop_receipt_available") is not False
            or first.get("central_recovery_allowed") is not False
            or first.get("production_launch_allowed") is not False):
        _hold("CPU_EVIDENCE_ORIGINAL_OS_IDENTITY_INVALID")

    for digest in (expected_input_sha256, expected_output_sha256):
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            _hold("CPU_EVIDENCE_TEST_ORACLE_INVALID")

    # Recheck ORIGINAL InvocationID, MainPID and cgroup via the trusted OS
    # backend; no status string supplied by the Agent can establish exit.
    terminal = backend.verified_natural_exit(
        unit, invocation,
        original_control_group="/system.slice/" + unit,
        original_main_pid=pid,
    )
    if (not isinstance(terminal, Mapping)
            or terminal.get("invocation_id") != invocation
            or terminal.get("main_pid") != pid
            or type(terminal.get("exit_code")) is not int
            or terminal["exit_code"] != 0
            or terminal.get("unit_result") != "success"
            or terminal.get("cgroup_exit_type_verified") is not True
            or terminal.get("trusted_stop_receipt_available") is not False):
        _hold("CPU_EVIDENCE_TERMINAL_UNVERIFIED")

    # Journalctl backend already cross-checks every entry against unit and
    # _SYSTEMD_INVOCATION_ID. The cursor must strictly progress per page.
    pages: list[bytes] = []
    previous_cursor: str | None = None
    ended = False
    for _ in range(_MAX_PAGES):
        page = backend.read_log_page(unit, invocation, cursor=previous_cursor)
        if (not isinstance(page, Mapping)
                or page.get("offset_contract_available") is not True
                or page.get("trusted_stop_receipt_available") is not False
                or type(page.get("data")) is not bytes
                or len(page["data"]) > _MAX_PAGE_BYTES):
            _hold("CPU_EVIDENCE_LOG_PAGE_UNVERIFIED")
        data = page["data"]
        cursor = page.get("cursor")
        if not data:
            ended = True
            break
        if (not isinstance(cursor, str) or not _CURSOR.fullmatch(cursor)
                or cursor == previous_cursor):
            _hold("CPU_EVIDENCE_LOG_CURSOR_UNVERIFIED")
        pages.append(data)
        previous_cursor = cursor
    if not ended:
        _hold("CPU_EVIDENCE_LOG_INCOMPLETE")

    record = parse_ort_result_log(b"".join(pages), frozen.source_sha256)
    if (record["input_shape"] != [1, 3, 32, 32]
            or record["output_shape"] != [1, 3, 32, 32]
            or not hmac.compare_digest(
                record["input_sha256"], expected_input_sha256)
            or not hmac.compare_digest(
                record["output_sha256"], expected_output_sha256)):
        _hold("CPU_EVIDENCE_INFERENCE_ORACLE_MISMATCH")
    return IsolatedCpuOnnxEvidence(
        task_id=frozen.task_id, task_attempt=frozen.task_attempt,
        source_sha256=frozen.source_sha256, unit_name=unit,
        invocation_id=invocation, original_main_pid=pid,
        input_sha256=record["input_sha256"],
        output_sha256=record["output_sha256"],
    )
