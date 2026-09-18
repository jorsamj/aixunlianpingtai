"""Single-concurrency remote executor loop for the service-node Agent.

The loop is intentionally database-free. It claims assignments from the control
plane, starts the execution lease, and dispatches only task kinds implemented by
this Agent build.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from .node_agent_deployment_runtime import (
    AgentDeploymentOutcome,
    AgentDeploymentRunner,
)
from .node_agent_executor_runtime import (
    NodeExecutorClient,
    NodeExecutorHTTPError,
    RemoteExecutionFenced,
)


SUPPORTED_AGENT_EXECUTOR_CAPABILITIES = frozenset({"conversion", "deployment-test", "training"})
SUPPORTED_AGENT_TASK_KINDS = frozenset({"DEPLOYMENT_TEST", "MODEL_CONVERSION", "TRAINING"})


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

    @property
    def enabled(self) -> bool:
        return bool(self.capabilities)

    def effective_capabilities(self) -> tuple[str, ...]:
        """Capabilities safe to advertise in the current local runtime state."""
        kind_by_capability = {
            "conversion": "MODEL_CONVERSION",
            "deployment-test": "DEPLOYMENT_TEST",
            "training": "TRAINING",
        }
        effective = []
        for capability in self.capabilities:
            kind = kind_by_capability.get(str(capability))
            runner = self.runners.get(kind) if kind else None
            if runner is not None and getattr(runner, "ready", True) is False:
                continue
            effective.append(str(capability))
        return tuple(effective)

    def _runner_recovery_error(self) -> str:
        for runner in self.runners.values():
            if getattr(runner, "ready", True) is False:
                value = str(getattr(runner, "recovery_error", "") or "").strip()
                if value:
                    return value
        return ""

    def _snapshot_locked(self) -> AgentExecutorStatus:
        return AgentExecutorStatus(
            enabled=self.enabled,
            running=bool(self._thread and self._thread.is_alive()),
            active_tasks=tuple(sorted(self._active_tasks)),
            last_error=self._last_error or self._runner_recovery_error(),
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
    def _claimed_task(claimed: Mapping[str, Any]) -> tuple[str, str, str]:
        assignment = claimed.get("assignment")
        task = claimed.get("task")
        if not isinstance(assignment, Mapping) or not isinstance(task, Mapping):
            raise ValueError("claimed executor item is missing assignment/task")
        task_id = str(task.get("task_id") or assignment.get("task_id") or "").strip()
        kind = str(task.get("kind") or "").strip().upper()
        assignment_token = str(
            assignment.get("assignment_lease_token") or ""
        ).strip()
        if not task_id or not kind or not assignment_token:
            raise ValueError("claimed executor item is incomplete")
        return task_id, kind, assignment_token

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
            task_id, kind, assignment_token = self._claimed_task(claimed)
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
            runner = self.runners.get(str(lease.kind or "").strip().upper())
            if runner is None or not callable(getattr(runner, "run", None)):
                try:
                    self.client.finish(
                        lease,
                        "FAILED",
                        error=f"Agent build does not implement task kind {lease.kind}",
                    )
                except Exception:
                    pass
                self._set_error(
                    f"UNSUPPORTED_AGENT_TASK_KIND: started {lease.kind} for {lease.task_id}"
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

    def _serve(self) -> None:
        while not self.stop_event.is_set():
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
