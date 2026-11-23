"""Node-level recovery coordination for Node Agent execution slots.

This module deliberately uses the existing workdir process identities and
ProcessController.  It does not create a second task-state database.
"""
from __future__ import annotations

import os
import threading
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

    def __init__(self, workdirs: "AgentExecutionWorkdir", controller: "ProcessController") -> None:
        self.workdirs = workdirs
        self.controller = controller
        self._lock = threading.RLock()
        self._owners: set[tuple[str, int]] = set()
        self._prepared = False
        self._error = ""

    def register_owner(self, task_id: str, generation: int) -> None:
        with self._lock:
            self._owners.add((str(task_id), int(generation)))

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
                    self._error = (
                        "remote launch outcome is unverified; exact process identity "
                        f"was not persisted for {unverified[0].get('kind')} task "
                        f"{unverified[0].get('task_id')}"
                    )
                    return self._error
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
                )
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
                try:
                    self.workdirs.clear_process_identity_record(key[0], key[1])
                except (OSError, ValueError) as error:
                    self._error = (
                        "unowned process identity cleanup could not be persisted: "
                        f"{type(error).__name__}: {error}"
                    )
                    return self._error
            self._error = ""
            return ""
