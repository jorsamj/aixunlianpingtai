"""Node-level recovery coordination for Node Agent execution slots.

This module deliberately uses the existing workdir process identities and
ProcessController.  It does not create a second task-state database.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .node_agent_training_runtime import AgentExecutionWorkdir
    from .task_runtime.process_control import ProcessController


class NodeRecoveryCoordinator:
    """One node-wide decision point for persisted process ownership.

    A runner must not scan and terminate every persisted process independently.
    The coordinator scans once, skips records owned by a registered active slot,
    and only cleans an unowned record when process death/cleanup is verifiable.
    """

    def __init__(
        self,
        workdirs: "AgentExecutionWorkdir",
        controller: "ProcessController",
        *,
        client=None,
        intent_path: str | Path | None = None,
    ) -> None:
        self.workdirs = workdirs
        self.controller = controller
        self.client = client
        self.intent_path = Path(intent_path) if intent_path else None
        self._lock = threading.RLock()
        self._owners: set[tuple[str, int]] = set()
        self._prepared = False
        self._error = ""

    @staticmethod
    def _identity_sha256(record: dict[str, Any]) -> str:
        value = {
            "pid": int(record["pid"]),
            "create_time": float(record["create_time"]),
            "command_hash": str(record["command_hash"]),
        }
        return hashlib.sha256(json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()

    def _status_matches_identity(self, status: dict[str, Any], record: dict[str, Any]) -> str:
        if str(status.get("task_id")) != str(record["task_id"]):
            return "central task identity mismatch"
        node_id = str(getattr(self.client, "node_id", "") or "")
        if node_id and str(status.get("node_id")) != node_id:
            return "central node identity mismatch"
        if int(status.get("execution_attempt") or 0) != int(record["generation"]):
            return "central execution attempt mismatch"
        if int(status.get("hold_execution_attempt") or 0) != int(record["generation"]):
            return "central Hold execution attempt mismatch"
        local_assignment = int(record.get("assignment_generation") or 0)
        if local_assignment > 0 and int(
            status.get("hold_assignment_generation") or 0
        ) != local_assignment:
            return "central Hold assignment generation mismatch"
        local_gpu = str(record.get("gpu_uuid") or "")
        if local_gpu and str(status.get("hold_gpu_uuid") or "") != local_gpu:
            return "central Hold GPU UUID mismatch"
        if int(status.get("hold_assignment_generation") or 0) <= 0:
            return "central Hold assignment generation missing"
        if not str(status.get("hold_gpu_uuid") or "").strip():
            return "central Hold GPU UUID missing"
        if str(status.get("process_identity_sha256") or "") != self._identity_sha256(record):
            return "central ProcessIdentity digest mismatch"
        return ""

    def _clear_intent(
        self, task_id: str, generation: int, *,
        execution_attempt: int | None = None,
        gpu_uuid: str | None = None,
        assignment_generation: int | None = None,
    ) -> None:
        if self.intent_path is None or not self.intent_path.is_file():
            return
        try:
            records = json.loads(self.intent_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ValueError("persisted dual-slot intent is unreadable")
        if not isinstance(records, list):
            raise ValueError("persisted dual-slot intent is invalid")
        def matches(item: object) -> bool:
            if not isinstance(item, dict):
                return False
            if (str(item.get("task_id")) != str(task_id)
                    or int(item.get("generation") or 0) != int(generation)):
                return False
            if execution_attempt is not None and item.get("execution_attempt") is not None:
                if int(item.get("execution_attempt")) != int(execution_attempt):
                    return False
            if gpu_uuid is not None and str(item.get("gpu_uuid") or ""):
                if str(item.get("gpu_uuid")) != str(gpu_uuid):
                    return False
            if (assignment_generation is not None
                    and item.get("assignment_generation") is not None):
                if int(item.get("assignment_generation")) != int(assignment_generation):
                    return False
            return True
        remaining = [item for item in records if not matches(item)]
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.intent_path.name}.", dir=str(self.intent_path.parent),
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(remaining, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.intent_path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def register_owner(self, task_id: str, generation: int) -> bool:
        with self._lock:
            key = (str(task_id), int(generation))
            if key in self._owners:
                return False
            self._owners.add(key)
            return True

    def unregister_owner(self, task_id: str, generation: int) -> None:
        with self._lock:
            self._owners.discard((str(task_id), int(generation)))

    def owner_slots(self) -> tuple[tuple[str, int], ...]:
        with self._lock:
            return tuple(sorted(self._owners))

    def prepare(self) -> str:
        """Scan once; return empty string on success, otherwise a fail-closed reason."""
        with self._lock:
            if self._prepared:
                return self._error
            self._prepared = True
            try:
                unverified = self.workdirs.list_unverified_process_launch_intents()
                if unverified:
                    if self.client is None:
                        item = unverified[0]
                        self._error = (
                            "remote launch outcome is unverified; exact process identity "
                            f"was not persisted for {item.get('kind')} task "
                            f"{item.get('task_id')}"
                        )
                        return self._error
                    for item in unverified:
                        try:
                            status = self.client.execution_status(str(item["task_id"]))
                        except Exception as error:
                            self._error = (
                                "central recovery status is unavailable: "
                                f"{type(error).__name__}: {error}"
                            )
                            return self._error
                        if (int(status.get("execution_attempt") or 0) != int(item["generation"])
                                or str(status.get("status")) not in {
                                    "SUCCEEDED", "PARTIAL_SUCCESS", "CANCELLED", "FAILED",
                                    "BLOCKED_BY_ENVIRONMENT", "BLOCKED_BY_HARDWARE"}
                                or str(status.get("hold_state")) != "RELEASED"
                                or str(status.get("proof_type") or "") != "NO_PROCESS_LAUNCHED"
                                or status.get("process_identity_sha256") is not None):
                            self._error = (
                                "remote launch outcome is unverified and not proven no-launch "
                                f"for task {item.get('task_id')}"
                            )
                            return self._error
                    for item in unverified:
                        self.workdirs.clear_process_launch_intent(
                            str(item["task_id"]), int(item["generation"]),
                        )
                records = self.workdirs.list_process_identities()
            except (OSError, ValueError) as error:
                self._error = f"persisted process identity is unsafe or unreadable: {error}"
                return self._error
            if os.name == "nt" and records:
                self._error = (
                    "Windows training recovery lacks Job Object descendant stop proof; "
                    "persisted process identity retained"
                )
                return self._error

            from .task_runtime.process_control import ProcessIdentity
            for record in records:
                key = (str(record["task_id"]), int(record["generation"]))
                if key in self._owners:
                    continue
                identity = ProcessIdentity(
                    pid=int(record["pid"]),
                    create_time=float(record["create_time"]),
                    command_hash=str(record["command_hash"]),
                    group_token=str(record.get("group_token") or ""),
                )
                status = None
                if self.client is not None:
                    try:
                        status = self.client.execution_status(str(record["task_id"]))
                    except Exception as error:
                        self._error = (
                            "central recovery status is unavailable: "
                            f"{type(error).__name__}: {error}"
                        )
                        return self._error
                    error = self._status_matches_identity(status, record)
                    if error:
                        self._error = error
                        return self._error
                try:
                    self.controller.terminate_tree(identity, timeout=8.0)
                except ProcessLookupError:
                    pass
                except (PermissionError, OSError) as error:
                    self._error = (
                        "unowned training process cleanup could not be verified: "
                        f"{type(error).__name__}: {error}"
                    )
                    return self._error
                if self.client is not None:
                    if (str(status.get("status")) not in {
                            "SUCCEEDED", "PARTIAL_SUCCESS", "CANCELLED", "FAILED",
                            "BLOCKED_BY_ENVIRONMENT", "BLOCKED_BY_HARDWARE"}
                            or str(status.get("hold_state")) != "RELEASED"):
                        try:
                            self.client.recover_execution(
                                str(record["task_id"]),
                                assignment_generation=int(status.get("hold_assignment_generation") or 0),
                                execution_generation=int(record["generation"]),
                                gpu_uuid=str(status.get("hold_gpu_uuid") or ""),
                                process_identity={
                                    "pid": int(record["pid"]),
                                    "create_time": float(record["create_time"]),
                                    "command_hash": str(record["command_hash"]),
                                },
                            )
                            refreshed = self.client.execution_status(str(record["task_id"]))
                        except Exception as error:
                            self._error = (
                                "central recovery could not release original execution: "
                                f"{type(error).__name__}: {error}"
                            )
                            return self._error
                        if str(refreshed.get("hold_state")) != "RELEASED":
                            self._error = "central recovery did not release the original Hold"
                            return self._error
                        refreshed_error = self._status_matches_identity(refreshed, record)
                        if refreshed_error:
                            self._error = refreshed_error
                            return self._error
                        status = refreshed
                try:
                    self.workdirs.clear_process_identity_record(key[0], key[1])
                    self._clear_intent(
                        key[0], key[1],
                        execution_attempt=int(record["generation"]),
                        gpu_uuid=str(status.get("hold_gpu_uuid") or "") if status else None,
                        assignment_generation=int(record.get("assignment_generation") or 0) or None,
                    )
                except (OSError, ValueError) as error:
                    self._error = (
                        "unowned process identity cleanup could not be persisted: "
                        f"{type(error).__name__}: {error}"
                    )
                    return self._error
            self._error = ""
            return ""
