"""2D-2D2A isolated central-lease / OS observer bridge, NOT an executor.

The original central task attempt and existing ExecutionLeaseMonitor remain
the only ownership/renewal authority. This bridge makes no systemd start/stop,
upload, finalization or central reassignment requests. It deliberately has no
production Agent/Runner imports and may only observe a fixed-CPU pilot.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from typing import Any, Mapping

from .node_agent_executor_runtime import (
    ExecutionLeaseMonitor, NodeExecutorClient, RemoteExecutionLease,
)
from .os_supervisor_conversion_adapter import (
    ConversionOsObservation, FrozenOnnxInput, SupervisedConversionHandle,
)
from .os_supervisor_protocol import SupervisorProtocolError


def _hold(code: str) -> None:
    raise SupervisorProtocolError(code + "_HOLD")


@dataclass(frozen=True, slots=True)
class LeaseBoundOsSnapshot:
    """Diagnostic observation: OS exit 0 is NOT a business success receipt."""

    task_id: str
    task_attempt: int
    os_state: str
    os_exit_code: int | None
    central_lease_verified_now: bool = True
    trusted_stop_receipt_available: bool = False
    central_recovery_allowed: bool = False
    result_publish_allowed: bool = False
    production_launch_allowed: bool = False


class SupervisedConversionLeaseGuard:
    """One-shot synchronous heartbeat before EACH OS inspect or log page.

    Reuses ExecutionLeaseMonitor.beat(), rather than starting a second thread,
    scheduler, local authority or central task. Any ambiguity permanently
    latches HOLD for this guard instance, with no fallback / retry action.
    """

    def __init__(self, *, lease: RemoteExecutionLease,
                 observer: SupervisedConversionHandle,
                 monitor: ExecutionLeaseMonitor):
        if (not isinstance(lease, RemoteExecutionLease)
                or not isinstance(observer, SupervisedConversionHandle)
                or not isinstance(monitor, ExecutionLeaseMonitor)
                or monitor.lease is not lease
                or not isinstance(monitor.client, NodeExecutorClient)
                or monitor.on_fenced is not None
                or monitor._thread is not None):
            _hold("CONVERSION_BRIDGE_ORIGINAL_OWNER_INVALID")
        frozen = FrozenOnnxInput.from_lease(lease)
        saved = observer.frozen_input
        if (not isinstance(saved, FrozenOnnxInput)
                or saved != frozen
                or monitor.client.node_id != frozen.node_id
                or not isinstance(lease.lease_token, str)
                or not hmac.compare_digest(
                    frozen.lease_sha256,
                    hashlib.sha256(lease.lease_token.encode("utf-8")).hexdigest())
                or observer.os_handle.execution_generation != frozen.task_attempt):
            _hold("CONVERSION_BRIDGE_LEASE_OS_IDENTITY_MISMATCH")
        self.lease = lease
        self.observer = observer
        self.monitor = monitor
        self._blocked = False

    @property
    def permanently_held(self) -> bool:
        return self._blocked

    def _verified_heartbeat(self) -> None:
        if self._blocked:
            _hold("CONVERSION_BRIDGE_ALREADY_FENCED")
        try:
            self.monitor.assert_active()
            body = self.monitor.beat()
            self.monitor.assert_active()
            if not isinstance(body, Mapping):
                _hold("CONVERSION_BRIDGE_CENTRAL_RESPONSE_INVALID")
            # Never treat a missing cancellation flag as "not cancelled".
            if body.get("cancel_requested") is not False:
                _hold("CONVERSION_BRIDGE_CANCEL_OR_UNVERIFIED")
            task = body.get("task")
            if (not isinstance(task, Mapping)
                    or task.get("status") != "RUNNING"):
                _hold("CONVERSION_BRIDGE_CENTRAL_TASK_NOT_RUNNING")
            # The existing endpoint may only include task.status. Validate
            # identity fields whenever included; the authenticated heartbeat
            # request itself carries the original task+attempt+lease.
            for key, value in (("task_id", self.lease.task_id),
                               ("worker_id", self.lease.worker_id)):
                if key in task and task[key] != value:
                    _hold("CONVERSION_BRIDGE_CENTRAL_IDENTITY_MISMATCH")
            for key, value in (("attempt", self.lease.generation),
                               ("generation", self.lease.generation)):
                if key in task and (type(task[key]) is not int
                                    or task[key] != value):
                    _hold("CONVERSION_BRIDGE_CENTRAL_GENERATION_MISMATCH")
            if "execution_generation" in body and (
                    type(body["execution_generation"]) is not int
                    or body["execution_generation"] != self.lease.generation):
                _hold("CONVERSION_BRIDGE_EXECUTION_GENERATION_MISMATCH")
        except Exception as exc:
            self._blocked = True
            if isinstance(exc, SupervisorProtocolError):
                raise
            raise SupervisorProtocolError(
                "CONVERSION_BRIDGE_LEASE_UNVERIFIED_HOLD") from exc

    def observe_once(self) -> LeaseBoundOsSnapshot:
        self._verified_heartbeat()
        try:
            evidence = self.observer.observe()
            if (not isinstance(evidence, ConversionOsObservation)
                    or evidence.os_state not in ("RUNNING_OR_STARTING", "EXITED")
                    or evidence.business_result_verified is not False
                    or evidence.result_publish_allowed is not False
                    or evidence.trusted_stop_receipt_available is not False
                    or evidence.production_launch_allowed is not False):
                _hold("CONVERSION_BRIDGE_OS_EVIDENCE_UNVERIFIED")
            if evidence.os_state == "RUNNING_OR_STARTING":
                if evidence.os_exit_code is not None:
                    _hold("CONVERSION_BRIDGE_RUNNING_EXIT_MISMATCH")
            elif (type(evidence.os_exit_code) is not int
                  or evidence.os_exit_code < -255
                  or evidence.os_exit_code > 255):
                _hold("CONVERSION_BRIDGE_TERMINAL_EXIT_MISMATCH")
            return LeaseBoundOsSnapshot(
                task_id=self.lease.task_id,
                task_attempt=self.lease.generation,
                os_state=evidence.os_state,
                os_exit_code=evidence.os_exit_code,
            )
        except Exception as exc:
            self._blocked = True
            if isinstance(exc, SupervisorProtocolError):
                raise
            raise SupervisorProtocolError(
                "CONVERSION_BRIDGE_OS_UNAVAILABLE_HOLD") from exc

    def read_log_page(self, cursor: str | None = None) -> dict[str, Any]:
        """Current central lease is mandatory even for existing OS log pages."""
        self._verified_heartbeat()
        try:
            page = self.observer.read_log_page(cursor)
            if (not isinstance(page, dict)
                    or type(page.get("data")) is not bytes
                    or not isinstance(page.get("cursor"), (str, type(None)))
                    or len(page["data"]) > 8192):
                _hold("CONVERSION_BRIDGE_LOG_EVIDENCE_UNVERIFIED")
            return page
        except Exception as exc:
            self._blocked = True
            if isinstance(exc, SupervisorProtocolError):
                raise
            raise SupervisorProtocolError(
                "CONVERSION_BRIDGE_LOG_UNAVAILABLE_HOLD") from exc

    def request_stop(self) -> None:
        _hold("CONVERSION_BRIDGE_TRUSTED_STOP_NOT_IMPLEMENTED")

    def publish_result(self) -> None:
        _hold("CONVERSION_BRIDGE_RESULT_TRANSACTION_NOT_IMPLEMENTED")
