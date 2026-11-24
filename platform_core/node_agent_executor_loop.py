"""Single-concurrency remote executor loop for the service-node Agent.

The loop is intentionally database-free. It claims assignments from the control
plane, starts the execution lease, and dispatches only task kinds implemented by
this Agent build.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from .node_agent_execution_slots import BoundedExecutionSlots, SlotNotReleased
from .node_agent_deployment_runtime import (
    AgentDeploymentOutcome,
    AgentDeploymentRunner,
)
from .node_agent_executor_runtime import (
    NodeExecutorClient,
    NodeExecutorHTTPError,
    RemoteExecutionFenced,
)


SUPPORTED_AGENT_EXECUTOR_CAPABILITIES = frozenset({
    "cleaning",
    "conversion",
    "conversion.rknn",
    "deployment-test",
    "deployment-test.rknn",
    "material-import",
    "model-upload",
    "training",
})
SUPPORTED_AGENT_TASK_KINDS = frozenset({
    "DEPLOYMENT_TEST",
    "MATERIAL_BATCH",
    "MATERIAL_IMPORT",
    "MODEL_CONVERSION",
    "MODEL_INSTALL",
    "TRAINING",
})
_CAPABILITY_BY_TASK_KIND = {
    "DEPLOYMENT_TEST": "deployment-test",
    "MATERIAL_BATCH": "cleaning",
    "MATERIAL_IMPORT": "material-import",
    "MODEL_CONVERSION": "conversion",
    "MODEL_INSTALL": "model-upload",
    "TRAINING": "training",
}


def executable_agent_capabilities(values: Iterable[str]) -> list[str]:
    """Return only capabilities this concrete Agent build can really execute."""
    requested = {
        str(value or "").strip().lower()
        for value in values
        if str(value or "").strip()
    }
    return sorted(requested & set(SUPPORTED_AGENT_EXECUTOR_CAPABILITIES))


@dataclass(frozen=True)
class AgentExecutorStatus:
    enabled: bool
    running: bool
    active_tasks: tuple[str, ...]
    last_error: str
    completed_tasks: int
    last_outcome: str


class NodeAgentExecutorLoop:
    """Run at most one remote execution while the main Agent keeps heartbeating."""

    def __init__(
        self,
        client: NodeExecutorClient,
        deployment_runner: AgentDeploymentRunner,
        *,
        capabilities: Iterable[str],
        runners: Mapping[str, object] | None = None,
        poll_interval: float = 2.0,
        on_status_change: Callable[[AgentExecutorStatus], None] | None = None,
        max_slots: int = 1,
        slot_runner_factory: Callable[[str, Callable[[Any], None]], object] | None = None,
        slot_controller: object | None = None,
        slot_intent_path: object | None = None,
        recovery_error: str = "",
    ) -> None:
        self.client = client
        self.deployment_runner = deployment_runner
        self.runners: dict[str, object] = {"DEPLOYMENT_TEST": deployment_runner}
        for raw_kind, runner in dict(runners or {}).items():
            kind = str(raw_kind or "").strip().upper()
            if kind:
                self.runners[kind] = runner
        self.capabilities = tuple(executable_agent_capabilities(capabilities))
        self.poll_interval = max(0.5, float(poll_interval))
        self.on_status_change = on_status_change
        self.stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._active_tasks: set[str] = set()
        self._last_error = ""
        self._last_outcome = ""
        self._completed_tasks = 0
        # A node-level recovery verdict that blocks this Agent from safely
        # owning any new remote execution. It is not cleared by later runner
        # status: the durable recovery evidence is still unresolved.
        self._recovery_error = str(recovery_error or "").strip()
        self.max_slots = 2 if max_slots == 2 and slot_runner_factory and slot_controller else 1
        self._slot_factory = slot_runner_factory
        self._slot_controller = slot_controller
        self._slots = BoundedExecutionSlots(2, persist_path=slot_intent_path) if self.max_slots == 2 else None
        self._slot_runners: dict[tuple[str, int], object] = {}
        self._reap_lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.capabilities) and not self._recovery_error

    def effective_capabilities(self) -> tuple[str, ...]:
        """Capabilities safe to advertise in the current local runtime state."""
        if self._recovery_error:
            # Fail closed: unsafe persisted recovery evidence means this Agent
            # must not accept any new remote work, even for unrelated kinds.
            return ()
        kind_by_capability = {
            capability: kind
            for kind, capability in _CAPABILITY_BY_TASK_KIND.items()
        }
        kind_by_capability["conversion.rknn"] = "MODEL_CONVERSION"
        kind_by_capability["deployment-test.rknn"] = "DEPLOYMENT_TEST"
        effective = []
        for capability in self.capabilities:
            kind = kind_by_capability.get(str(capability))
            runner = self.runners.get(kind) if kind else None
            # A capability is executable only if this Agent instance actually
            # registered a ready runner; an allow-listed name alone is not proof.
            if runner is None or not callable(getattr(runner, "run", None)):
                continue
            if getattr(runner, "ready", True) is False:
                continue
            effective.append(str(capability))
        if self.max_slots == 2 and self._slots is not None:
            if self._slots.blocked_reason:
                return ()
            training = self.runners.get("TRAINING")
            if (not training or "training" not in self.capabilities
                    or not callable(getattr(training, "run", None))
                    or getattr(training, "ready", True) is False):
                return ()
            return ("training", "execution-slots:2")
        return tuple(effective)

    def _runner_recovery_error(self) -> str:
        for runner in self.runners.values():
            if getattr(runner, "ready", True) is False:
                value = str(getattr(runner, "recovery_error", "") or "").strip()
                if value:
                    return value
        return ""

    def _snapshot_locked(self) -> AgentExecutorStatus:
        active = set(self._active_tasks)
        if self._slots is not None:
            active.update(slot.task_id for slot in self._slots.active())
        return AgentExecutorStatus(
            enabled=self.enabled,
            running=bool(self._thread and self._thread.is_alive()),
            active_tasks=tuple(sorted(active)),
            last_error=(
                self._recovery_error
                or self._last_error
                or self._runner_recovery_error()
            ),
            completed_tasks=self._completed_tasks,
            last_outcome=self._last_outcome,
        )

    def status(self) -> AgentExecutorStatus:
        with self._lock:
            return self._snapshot_locked()

    def active_tasks(self) -> tuple[str, ...]:
        return self.status().active_tasks

    def last_error(self) -> str:
        return self.status().last_error

    def _publish_status(self) -> None:
        callback = self.on_status_change
        if callback is None:
            return
        try:
            callback(self.status())
        except Exception:
            pass

    def _set_active(self, task_id: str, active: bool) -> None:
        with self._lock:
            if active:
                self._active_tasks.add(str(task_id))
            else:
                self._active_tasks.discard(str(task_id))
        self._publish_status()

    def _set_error(self, value: object) -> None:
        with self._lock:
            self._last_error = str(value or "")
        self._publish_status()

    def _record_outcome(self, outcome) -> None:
        with self._lock:
            self._completed_tasks += 1
            self._last_outcome = str(outcome.status or "")
            self._last_error = str(outcome.error or "") if outcome.status == "FAILED" else ""
        self._publish_status()

    @staticmethod
    def _claimed_task(claimed: Mapping[str, Any]) -> tuple[str, str, str, str]:
        assignment = claimed.get("assignment")
        task = claimed.get("task")
        if not isinstance(assignment, Mapping) or not isinstance(task, Mapping):
            raise ValueError("claimed executor item is missing assignment/task")
        task_id = str(task.get("task_id") or assignment.get("task_id") or "").strip()
        kind = str(task.get("kind") or "").strip().upper()
        assignment_token = str(
            assignment.get("assignment_lease_token") or ""
        ).strip()
        capability = str(
            assignment.get("capability")
            or _CAPABILITY_BY_TASK_KIND.get(kind)
            or ""
        ).strip().lower()
        if not task_id or not kind or not assignment_token or not capability:
            raise ValueError("claimed executor item is incomplete")
        return task_id, kind, assignment_token, capability

    def run_once(self) -> bool:
        """Claim and execute at most one task. Return True when a task was claimed."""
        if not self.enabled or self.stop_event.is_set():
            return False
        try:
            claimed = self.client.claim_assignment()
        except NodeExecutorHTTPError as error:
            self._set_error(f"{error.code}: {error}")
            return False
        except (OSError, ValueError) as error:
            self._set_error(f"{type(error).__name__}: {error}")
            return False
        if claimed is None:
            return False

        try:
            task_id, kind, assignment_token, required_capability = self._claimed_task(claimed)
        except ValueError as error:
            self._set_error(f"NODE_EXECUTOR_INVALID_RESPONSE: {error}")
            return True

        if kind not in SUPPORTED_AGENT_TASK_KINDS:
            # This should be impossible when reported capabilities are truthful.
            # Do not start an execution we cannot own safely; the assignment
            # claim lease will expire and return to ASSIGNED for an operator or
            # a future compatible Agent build.
            self._set_error(
                f"UNSUPPORTED_AGENT_TASK_KIND: claimed {kind} for {task_id}"
            )
            return True

        default_capability = _CAPABILITY_BY_TASK_KIND.get(kind)
        allowed_capabilities = (
            {"conversion", "conversion.rknn"}
            if kind == "MODEL_CONVERSION"
            else (
                {"deployment-test", "deployment-test.rknn"}
                if kind == "DEPLOYMENT_TEST"
                else ({default_capability} if default_capability else set())
            )
        )
        runner = self.runners.get(kind)
        effective = set(self.effective_capabilities())
        if (
            required_capability not in allowed_capabilities
            or required_capability not in effective
            or runner is None
            or not callable(getattr(runner, "run", None))
            or getattr(runner, "ready", True) is False
        ):
            # A stale central assignment can race with a local runtime becoming
            # unavailable. Never convert that stale assignment into a RUNNING
            # execution lease. The assignment claim lease can expire/reassign
            # after the next heartbeat withdraws this capability.
            reason = str(getattr(runner, "recovery_error", "") or "").strip()
            detail = (
                f": {reason}"
                if reason
                else ""
            )
            self._set_error(
                f"UNSUPPORTED_AGENT_TASK_KIND: {kind} is not executable "
                f"by this Agent runtime{detail}"
            )
            return True

        try:
            lease = self.client.start_execution(task_id, assignment_token)
        except NodeExecutorHTTPError as error:
            self._set_error(f"{error.code}: {error}")
            return True
        except (OSError, ValueError) as error:
            self._set_error(f"{type(error).__name__}: {error}")
            return True

        self._set_active(lease.task_id, True)
        try:
            # Runner readiness was fenced before start_execution. Re-check the
            # returned kind only for protocol corruption; do not dispatch a
            # different runner than the one that was admitted above.
            if str(lease.kind or "").strip().upper() != kind:
                try:
                    self.client.finish(
                        lease,
                        "FAILED",
                        error=(
                            "control plane returned a different task kind "
                            f"after start: expected {kind}, got {lease.kind}"
                        ),
                    )
                except Exception:
                    pass
                self._set_error(
                    f"NODE_EXECUTOR_INVALID_RESPONSE: started {lease.kind} for "
                    f"{lease.task_id}, expected {kind}"
                )
                return True
            outcome = runner.run(lease)
            self._record_outcome(outcome)
            return True
        except RemoteExecutionFenced as error:
            # Ownership moved elsewhere. Never publish a terminal mutation from
            # the stale generation.
            self._set_error(f"EXECUTION_FENCED: {error}")
            return True
        except Exception as error:
            # The task-specific runner normally publishes FAILED itself. This
            # catch protects the executor thread from dying on a programming or
            # transport error while preserving one-task-at-a-time operation.
            self._set_error(f"{type(error).__name__}: {error}")
            try:
                self.client.finish(
                    lease,
                    "FAILED",
                    error=f"{type(error).__name__}: {error}",
                )
            except Exception:
                pass
            return True
        finally:
            self._set_active(lease.task_id, False)

    def _dual_gpu_uuid(self, lease) -> str:
        assignment = getattr(lease, "assignment", None)
        config = assignment.get("resolved_execution_config") if isinstance(assignment, Mapping) else None
        selected = config.get("selected_gpu") if isinstance(config, Mapping) else None
        return str(selected.get("uuid") or "") if isinstance(selected, Mapping) else ""

    def _reap_dual_slots(self) -> None:
        if self._slots is None:
            return
        if not self._reap_lock.acquire(blocking=False):
            # Another thread is already reconciling the slots. Concurrent
            # reaping could release the same slot twice and turn a legitimate
            # release into a spurious SlotNotReleased failure.
            return
        try:
            self._reap_dual_slots_locked()
        finally:
            self._reap_lock.release()

    def _reap_dual_slots_locked(self) -> None:
        for slot in self._slots.active():
            if not slot.worker_exited:
                continue
            try:
                status = self.client.execution_status(slot.task_id)
            except Exception as error:
                self._set_error(f"SLOT_STATUS_UNKNOWN: {type(error).__name__}: {error}")
                continue
            expected_identity_sha = None
            if slot.identity is not None:
                expected_identity_sha = hashlib.sha256(json.dumps({
                    "pid": int(slot.identity.pid),
                    "create_time": float(slot.identity.create_time),
                    "command_hash": str(slot.identity.command_hash),
                }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            if (str(status.get("task_id")) != str(slot.task_id)
                    or str(status.get("node_id")) != str(self.client.node_id)
                    or int(status.get("execution_attempt") or -1) != int(slot.execution_attempt)
                    or int(status.get("hold_assignment_generation") or -1) != int(slot.generation)
                    or str(status.get("hold_gpu_uuid") or "") != str(slot.gpu_uuid)
                    or (status.get("process_identity_sha256") or None) != expected_identity_sha):
                self._set_error(
                    f"SLOT_IDENTITY_MISMATCH: {slot.task_id} generation {slot.generation}"
                )
                continue
            expected_proof_type = (
                "NO_PROCESS_LAUNCHED" if slot.identity is None else "PROCESS_STOP_VERIFIED"
            )
            if str(status.get("proof_type") or "") != expected_proof_type:
                self._set_error(
                    f"SLOT_PROOF_TYPE_MISMATCH: {slot.task_id} generation {slot.generation}"
                )
                continue
            if (str(status.get("status")) not in {
                    "SUCCEEDED", "PARTIAL_SUCCESS", "CANCELLED", "FAILED",
                    "BLOCKED_BY_ENVIRONMENT", "BLOCKED_BY_HARDWARE"}
                    or str(status.get("hold_state")) != "RELEASED"
                    or int(status.get("hold_execution_attempt") or -1) != int(slot.execution_attempt)):
                continue
            try:
                released = self._slots.confirm_stopped(
                    slot, self._slot_controller,
                    allow_no_process=slot.identity is None,
                )
            except SlotNotReleased:
                # The slot was released by another reconciler between the scan
                # and this confirmation; that is an idempotent success, not an
                # error, and capacity is already accounted for.
                self._slot_runners.pop((slot.task_id, slot.generation), None)
                self._set_active(slot.task_id, False)
                continue
            if released:
                self._slot_runners.pop((slot.task_id, slot.generation), None)
                self._set_active(slot.task_id, False)
                self._completed_tasks += 1
            else:
                self._set_error(
                    f"SLOT_STOP_UNVERIFIED: {slot.task_id} generation {slot.generation}"
                )

    def _run_dual_once(self) -> bool:
        if self._slots is None or len(self._slots.active()) >= self.max_slots:
            return False
        if self._slots.blocked_reason:
            self._set_error(self._slots.blocked_reason)
            return False
        try:
            claimed = self.client.claim_assignment()
        except NodeExecutorHTTPError as error:
            self._set_error(f"{error.code}: {error}")
            return False
        except (OSError, ValueError) as error:
            self._set_error(f"{type(error).__name__}: {error}")
            return False
        if claimed is None:
            return False
        try:
            task_id, kind, assignment_token, required_capability = self._claimed_task(claimed)
        except ValueError as error:
            self._set_error(f"NODE_EXECUTOR_INVALID_RESPONSE: {error}")
            return True
        factory = self._slot_factory
        if factory is None or kind != "TRAINING":
            self._set_error(f"UNSUPPORTED_DUAL_SLOT_KIND: {kind}")
            return True
        assignment = claimed.get("assignment") or {}
        config = assignment.get("resolved_execution_config") or {}
        selected = config.get("selected_gpu") if isinstance(config, Mapping) else None
        gpu_uuid = str(selected.get("uuid") or "") if isinstance(selected, Mapping) else ""
        if not gpu_uuid:
            self._set_error("DUAL_SLOT_GPU_UUID_MISSING")
            return True
        try:
            local_lease = type("LocalReservation", (), {
                "task_id": task_id, "generation": int(assignment.get("generation") or 1)
            })()
            slot = self._slots.reserve(
                local_lease, gpu_uuid=gpu_uuid, slot_id=f"slot-{task_id}",
            )
        except Exception as error:
            self._set_error(f"SLOT_RESERVE_FAILED: {type(error).__name__}: {error}")
            return True
        bound = {"slot": slot}

        def on_process_started(identity) -> None:
            target = bound.get("slot")
            if target is None:
                raise RuntimeError("slot identity callback fired outside reservation")
            target.identity = identity

        try:
            try:
                runner = factory(kind, on_process_started, task_id)
            except TypeError:
                runner = factory(kind, on_process_started)
        except Exception as error:
            self._slots.abort_reserved(slot, error)
            self._set_error(f"SLOT_RUNNER_FACTORY_FAILED: {type(error).__name__}: {error}")
            return True
        if getattr(runner, "ready", True) is False:
            self._slots.abort_reserved(slot)
            self._set_error(
                "SLOT_RUNNER_NOT_READY: "
                + str(getattr(runner, "recovery_error", "") or "")
            )
            return True
        try:
            lease = self.client.start_execution(task_id, assignment_token)
        except NodeExecutorHTTPError as error:
            if error.outcome_unknown:
                self._slots.mark_central_unknown(slot, error)
                self._set_error(
                    f"CENTRAL_START_UNKNOWN: {error.code}: {error}"
                )
            else:
                self._slots.abort_reserved(slot, error)
                self._set_error(f"{error.code}: {error}")
            return True
        except (OSError, ValueError) as error:
            # Outcome unknown: central may already be RUNNING. Never reuse the
            # local slot or blindly retry the start.
            self._slots.mark_central_unknown(slot, error)
            self._set_error(f"CENTRAL_START_UNKNOWN: {type(error).__name__}: {error}")
            return True
        if str(lease.task_id) != task_id:
            self._slots.mark_central_unknown(slot, RuntimeError("start lease task mismatch"))
            self._set_error("SLOT_START_IDENTITY_MISMATCH")
            return True
        # The dual-slot manager may only bind a lease that provably belongs to
        # the reservation it made: same Assignment generation, same GPU UUID,
        # and (when the control plane reports it) the two-slot contract. An
        # explicit single-slot contract under a dual-slot reservation means the
        # central Hold/stop-proof chain does not exist for this execution.
        assignment_evidence = lease.assignment if isinstance(lease.assignment, dict) else {}
        evidence_config = assignment_evidence.get("resolved_execution_config")
        evidence_selected = (
            evidence_config.get("selected_gpu") if isinstance(evidence_config, dict) else None
        )
        evidence_gpu = (
            str(evidence_selected.get("uuid") or "")
            if isinstance(evidence_selected, dict) else ""
        )
        central_slots = int(getattr(lease, "execution_slots", 0) or 0)
        if (central_slots not in (0, 2)
                or int(assignment_evidence.get("generation") or 0)
                != int(slot.assignment_generation)
                or not evidence_gpu
                or evidence_gpu != gpu_uuid):
            self._slots.mark_central_unknown(
                slot, RuntimeError("start lease assignment identity mismatch"),
            )
            self._set_error("SLOT_START_IDENTITY_MISMATCH")
            return True
        try:
            self._slots.mark_started(slot, lease)
        except Exception as error:
            self._slots.mark_central_unknown(slot, error)
            self._set_error(f"SLOT_MARK_STARTED_FAILED: {error}")
            return True
        self._set_active(lease.task_id, True)

        def run_slot(slot_value, lease_value):
            try:
                return runner.run(lease_value)
            except RemoteExecutionFenced as error:
                self._set_error(f"EXECUTION_FENCED: {error}")
                raise
            except Exception as error:
                self._set_error(f"{type(error).__name__}: {error}")
                raise

        try:
            self._slots.start_worker(slot, run_slot)
            self._slot_runners[(slot.task_id, slot.generation)] = runner
        except Exception as error:
            self._slots.mark_central_unknown(slot, error)
            self._set_error(f"SLOT_WORKER_START_FAILED: {type(error).__name__}: {error}")
            return True
        return True

    def cancel_task(self, task_id: str, generation: int | None = None) -> bool:
        """Cancel only the matching slot; never request shutdown for siblings."""
        if self._slots is None:
            return False
        for slot in self._slots.active():
            if slot.task_id != str(task_id):
                continue
            if generation is not None and slot.generation != int(generation):
                continue
            self._slots.request_cancel(slot.task_id, slot.generation)
            runner = self._slot_runners.get((slot.task_id, slot.generation))
            request_shutdown = getattr(runner, "request_shutdown", None)
            if callable(request_shutdown):
                request_shutdown()
            return True
        return False

    def _serve(self) -> None:
        while not self.stop_event.is_set():
            if self._slots is not None:
                self._reap_dual_slots()
                claimed = self._run_dual_once()
                if claimed:
                    continue
            else:
                claimed = self.run_once()
                if claimed:
                    continue
            self.stop_event.wait(self.poll_interval)

    def start(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self.stop_event.clear()
            self._thread = threading.Thread(
                target=self._serve,
                name="node-agent-executor",
                daemon=True,
            )
            self._thread.start()
        self._publish_status()

    def stop(self, *, timeout: float = 10.0) -> None:
        self.stop_event.set()
        # Local shutdown must never leave a child inference process behind. The
        # runner treats this as execution fencing so central lease expiry/retry
        # remains authoritative rather than publishing a false terminal status.
        for runner in list(self._slot_runners.values()):
            request_shutdown = getattr(runner, "request_shutdown", None)
            if callable(request_shutdown):
                request_shutdown()
        if self._slots is not None:
            for slot in self._slots.active():
                self._slots.request_cancel(slot.task_id, slot.generation)
        seen_runners: set[int] = set()
        for runner in self.runners.values():
            identity = id(runner)
            if identity in seen_runners:
                continue
            seen_runners.add(identity)
            request_shutdown = getattr(runner, "request_shutdown", None)
            if callable(request_shutdown):
                request_shutdown()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.1, float(timeout)))
        self._publish_status()


__all__ = [
    "AgentExecutorStatus",
    "NodeAgentExecutorLoop",
    "SUPPORTED_AGENT_EXECUTOR_CAPABILITIES",
    "SUPPORTED_AGENT_TASK_KINDS",
    "executable_agent_capabilities",
]
