"""Node-level recovery coordination for Node Agent execution slots.

This module deliberately uses the existing workdir process identities and
ProcessController.  It does not create a second task-state database.
"""
from __future__ import annotations

import hmac
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from .node_agent_settlement import (
    HOLD_RELEASED,
    PROCESS_STOP_VERIFIED,
    TERMINAL_TASK_STATUSES,
    canonical_digest,
    fetch_status,
    hold_identity_error,
    is_dual_slot,
    process_identity_sha256,
    proof_error,
    settlement_error,
    single_slot_contract_error,
    status_identity_error,
    stop_proof_digests,
    strict_int,
    strict_positive_number,
)

if TYPE_CHECKING:
    from .node_agent_training_runtime import AgentExecutionWorkdir
    from .task_runtime.process_control import ProcessController


# A scan result is either final (the node must stay blocked until an operator
# resolves the durable evidence) or retryable (the control plane was simply not
# at a terminal state yet, or was unreachable).  Only a retryable verdict may be
# re-evaluated by a later ``prepare()`` call; a permanent one is cached.
DISPOSITION_OK = "OK"
DISPOSITION_PERMANENT = "PERMANENT"
DISPOSITION_RETRYABLE = "RETRYABLE"

_UNCONFIRMED_SINGLE_SLOT = (
    "single-slot execution is not centrally settled; original process identity retained"
)


class NodeRecoveryCoordinator:
    """One node-wide decision point for persisted process ownership.

    A runner must not scan and terminate every persisted process independently.
    The coordinator scans once, skips records owned by a registered active slot,
    and only cleans an unowned record when process death/cleanup is verifiable
    *and* the control plane has settled that exact execution.
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
        self._disposition = ""
        self._error = ""

    # -- shared settlement contract -------------------------------------------

    @staticmethod
    def _digest(value: dict[str, Any]) -> str:
        return canonical_digest(value)

    @classmethod
    def _identity_sha256(cls, record: dict[str, Any]) -> str:
        return process_identity_sha256(
            record["pid"], record["create_time"], record["command_hash"],
        )

    @classmethod
    def _stop_proof_digests(
        cls, status: dict[str, Any], record: dict[str, Any],
    ) -> tuple[str, str]:
        return stop_proof_digests(status, record)

    def _hold_identity_error(
        self,
        status: dict[str, Any],
        record: dict[str, Any],
        local_assignment: int,
        local_gpu: str,
    ) -> str:
        return hold_identity_error(status, record, local_assignment, local_gpu)

    def _proof_error(self, status: dict[str, Any], record: dict[str, Any]) -> str:
        return proof_error(status, record)

    def _single_slot_contract_error(
        self,
        status: dict[str, Any],
        record: dict[str, Any],
        local_assignment: int,
    ) -> str:
        return single_slot_contract_error(status, record, local_assignment)

    def _node_id(self) -> str:
        return str(getattr(self.client, "node_id", "") or "")

    def _status_matches_identity(self, status: dict[str, Any], record: dict[str, Any]) -> str:
        return status_identity_error(status, record, node_id=self._node_id())

    # -- persisted trusted-stop witness ---------------------------------------

    def _stop_evidence_error(self, record: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """Strictly read and bind the persisted trusted-stop witness.

        Returns ``(evidence, "")`` only for a proof that names exactly this
        execution and process identity. A missing file is legacy (``(None, "")``);
        an unreadable, corrupt or mismatching file is fail-closed.
        """
        reader = getattr(self.workdirs, "read_stop_evidence", None)
        if reader is None:
            return None, ""
        try:
            value = reader(str(record["task_id"]), int(record["generation"]))
        except ValueError as error:
            # Path escape, symlink, unsafe file type, unreadable or corrupt JSON
            # and lineage mismatch are all fail-closed, never "no evidence".
            return None, f"persisted stop evidence is unsafe: {error}"
        except OSError as error:
            return None, f"persisted stop evidence is unreadable: {error}"
        if value is None:
            return None, ""
        try:
            return self._validated_stop_evidence(record, value)
        except (TypeError, ValueError, OverflowError) as error:
            return None, f"persisted stop evidence has invalid fields: {error}"

    def _validated_stop_evidence(
        self, record: dict[str, Any], value: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        """Validate every persisted field without any implicit coercion.

        ``int("11")``, ``int(True)`` or ``float("NaN")`` must never be accepted
        as a match for the real process identity: a corrupted witness is a
        fail-closed recovery block, not legacy evidence.
        """
        if not isinstance(value, Mapping):
            return None, "persisted stop evidence is invalid"
        if str(value.get("proof_type") or "") != PROCESS_STOP_VERIFIED:
            return None, "persisted stop evidence has an unknown proof type"
        if value.get("stop_verified") is not True:
            return None, "persisted stop evidence does not verify a stop"
        if value.get("no_process_launched") is not False:
            return None, "persisted stop evidence contradicts the recorded identity"
        task_id = value.get("task_id")
        if not isinstance(task_id, str) or task_id != str(record["task_id"]):
            return None, "persisted stop evidence names another task"
        attempt = strict_int(value.get("execution_attempt"))
        if attempt is None or attempt <= 0:
            return None, "persisted stop evidence has an invalid execution attempt"
        if attempt != int(record["generation"]):
            return None, "persisted stop evidence names another execution attempt"
        identity = value.get("process_identity")
        if not isinstance(identity, Mapping):
            return None, "persisted stop evidence has no process identity"
        pid = strict_int(identity.get("pid"))
        if pid is None or pid <= 0:
            return None, "persisted stop evidence has an invalid pid"
        create_time = strict_positive_number(identity.get("create_time"))
        if create_time is None:
            return None, "persisted stop evidence has an invalid create time"
        command_hash = identity.get("command_hash")
        if not isinstance(command_hash, str) or not command_hash:
            return None, "persisted stop evidence has an invalid command hash"
        if (
            pid != int(record["pid"])
            or create_time != float(record["create_time"])
            or command_hash != str(record["command_hash"])
        ):
            return None, "persisted stop evidence names another process identity"
        assignment = value.get("assignment_generation")
        assignment = 0 if assignment is None else strict_int(assignment)
        if assignment is None or assignment < 0:
            return None, "persisted stop evidence has an invalid assignment generation"
        local_assignment = int(record.get("assignment_generation") or 0)
        if local_assignment > 0 and assignment != local_assignment:
            return None, "persisted stop evidence names another assignment generation"
        gpu_uuid = value.get("gpu_uuid")
        if gpu_uuid is not None and not isinstance(gpu_uuid, str):
            return None, "persisted stop evidence has an invalid GPU UUID"
        local_gpu = str(record.get("gpu_uuid") or "")
        if local_gpu and str(gpu_uuid or "") != local_gpu:
            return None, "persisted stop evidence names another GPU"
        return value, ""

    def _clear_stop_evidence(self, task_id: str, generation: int) -> None:
        """Remove the settled attempt's trusted-stop witness (idempotent)."""
        clearer = getattr(self.workdirs, "clear_stop_evidence", None)
        if callable(clearer):
            clearer(str(task_id), int(generation))

    # -- persisted slot intent ------------------------------------------------

    def _clear_intent(
        self, task_id: str, generation: int, *,
        execution_attempt: int | None = None,
        gpu_uuid: str | None = None,
        assignment_generation: int | None = None,
    ) -> int:
        """Remove the exact recovered slot intent; never a different attempt.

        Returns the number of removed records. A record for the same task that
        does not match the recovered identity is corruption (or a newer attempt)
        and is never silently ignored: it raises so recovery stays fail-closed.
        """
        if self.intent_path is None or not self.intent_path.is_file():
            return 0
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

        same_task = [
            item for item in records
            if isinstance(item, dict) and str(item.get("task_id")) == str(task_id)
        ]
        matched = [item for item in same_task if matches(item)]
        if same_task and not matched:
            raise ValueError(
                "persisted dual-slot intent does not match the recovered execution"
            )
        if not matched:
            return 0
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
        return len(matched)

    # -- ownership ------------------------------------------------------------

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

    @property
    def retryable(self) -> bool:
        """True when the last verdict may be re-evaluated by a later prepare()."""
        with self._lock:
            return self._disposition == DISPOSITION_RETRYABLE

    def prepare(self) -> str:
        """Scan and reconcile; empty string means every record is settled.

        A settled scan is cached.  A permanent block is cached.  A transient
        block (control plane unreachable or not terminal yet) is re-evaluated on
        the next call, under the same lock, so exactly one owner can converge.
        """
        with self._lock:
            if self._prepared and self._disposition != DISPOSITION_RETRYABLE:
                return self._error
            self._prepared = True
            self._error = ""
            self._disposition = DISPOSITION_OK
            try:
                return self._prepare_locked()
            except (OSError, ValueError) as error:
                return self._block(
                    f"persisted process identity is unsafe or unreadable: {error}",
                )

    def _block(self, message: str, *, retryable: bool = False) -> str:
        self._error = message
        self._disposition = (
            DISPOSITION_RETRYABLE if retryable else DISPOSITION_PERMANENT
        )
        return message

    def _prepare_locked(self) -> str:
        try:
            unverified = self.workdirs.list_unverified_process_launch_intents()
            if unverified:
                if self.client is None:
                    item = unverified[0]
                    return self._block(
                        "remote launch outcome is unverified; exact process identity "
                        f"was not persisted for {item.get('kind')} task "
                        f"{item.get('task_id')}"
                    )
                for item in unverified:
                    status, error = fetch_status(self.client, str(item["task_id"]))
                    if error:
                        return self._block(error, retryable=True)
                    if (strict_int(status.get("execution_attempt")) != int(item["generation"])
                            or str(status.get("status")) not in TERMINAL_TASK_STATUSES
                            or str(status.get("hold_state")) != HOLD_RELEASED
                            or str(status.get("proof_type") or "") != "NO_PROCESS_LAUNCHED"
                            or status.get("process_identity_sha256") is not None):
                        return self._block(
                            "remote launch outcome is unverified and not proven no-launch "
                            f"for task {item.get('task_id')}"
                        )
                for item in unverified:
                    self.workdirs.clear_process_launch_intent(
                        str(item["task_id"]), int(item["generation"]),
                    )
            records = self.workdirs.list_process_identities()
        except (OSError, ValueError) as error:
            return self._block(
                f"persisted process identity is unsafe or unreadable: {error}",
            )
        if os.name == "nt" and records:
            return self._block(
                "Windows training recovery lacks Job Object descendant stop proof; "
                "persisted process identity retained"
            )

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
            evidence, evidence_error = self._stop_evidence_error(record)
            if evidence_error:
                return self._block(evidence_error)
            status: dict[str, Any] | None = None
            if self.client is not None:
                status, status_error = fetch_status(self.client, key[0])
                if status_error:
                    return self._block(status_error, retryable=True)
                error = self._status_matches_identity(status, record)
                if error:
                    return self._block(error)
            try:
                self.controller.terminate_tree(identity, timeout=8.0)
            except ProcessLookupError:
                pass
            except (PermissionError, OSError) as error:
                return self._block(
                    "unowned training process cleanup could not be verified: "
                    f"{type(error).__name__}: {error}"
                )
            if self.client is not None:
                if status is None:
                    return self._block(
                        "central recovery status is unavailable", retryable=True,
                    )
                error = settlement_error(
                    status, record,
                    node_id=self._node_id(),
                    require_process_identity=is_dual_slot(record, status),
                )
                if error:
                    recovered = self._recover_original_execution(record, status)
                    if isinstance(recovered, str):
                        return recovered
                    status = recovered
            try:
                assignment_generation = int(record.get("assignment_generation") or 0)
                # Clear the intent first: the persisted ProcessIdentity is the
                # unique original execution evidence and must survive any
                # interruption before the second step. Both steps are
                # idempotent, so a retried preparation converges.
                self._clear_intent(
                    key[0],
                    assignment_generation or key[1],
                    execution_attempt=int(record["generation"]),
                    gpu_uuid=str(record.get("gpu_uuid") or ""),
                    assignment_generation=assignment_generation,
                )
                # Order matters: the intent is already gone, the witness goes
                # next and the ProcessIdentity (the unique recovery evidence)
                # is released last. Every step is idempotent, so an interrupted
                # cleanup simply converges on the next verification.
                self._clear_stop_evidence(key[0], key[1])
                self.workdirs.clear_process_identity_record(key[0], key[1])
            except (OSError, ValueError) as error:
                return self._block(
                    "unowned process identity cleanup could not be persisted: "
                    f"{type(error).__name__}: {error}"
                )
        self._error = ""
        self._disposition = DISPOSITION_OK
        return ""

    def _recover_original_execution(
        self,
        record: dict[str, Any],
        status: dict[str, Any],
    ):
        """Ask the control plane to settle this exact original execution.

        Returns the refreshed, verified status, or a blocking error string.
        Dual-slot executions are released through the existing Hold/stop-proof
        contract.  A single-slot execution has no Hold, so its legal settlement
        is the same fenced recovery: the control plane CASes the terminal status
        and durably registers the exact ProcessIdentity, which the refreshed
        status must then prove.
        """
        client = self.client
        dual = is_dual_slot(record, status)
        try:
            recovered = client.recover_execution(
                str(record["task_id"]),
                assignment_generation=int(record.get("assignment_generation") or 0),
                execution_generation=int(record["generation"]),
                gpu_uuid=str(record.get("gpu_uuid") or ""),
                process_identity={
                    "pid": int(record["pid"]),
                    "create_time": float(record["create_time"]),
                    "command_hash": str(record["command_hash"]),
                },
            )
            refreshed, refresh_error = fetch_status(client, str(record["task_id"]))
        except Exception as error:  # noqa: BLE001 - fail closed, retryable
            if dual:
                return self._block(
                    "central recovery could not release original execution: "
                    f"{type(error).__name__}: {error}",
                    retryable=True,
                )
            return self._block(
                f"{_UNCONFIRMED_SINGLE_SLOT}; central recovery could not be "
                f"confirmed: {type(error).__name__}: {error}",
                retryable=True,
            )
        if refresh_error:
            return self._block(refresh_error, retryable=True)
        if not isinstance(recovered, Mapping):
            return self._block(
                "central recovery returned no settlement evidence",
                retryable=not dual,
            )
        if dual:
            recovered_digest = str(recovered.get("proof_sha256") or "")
            if str(refreshed.get("hold_state")) != HOLD_RELEASED:
                return self._block(
                    "central recovery did not release the original Hold",
                    retryable=True,
                )
            if (not recovered_digest
                    or not hmac.compare_digest(
                        str(refreshed.get("proof_sha256") or ""),
                        recovered_digest)):
                return self._block(
                    "central recovery stop proof does not match the "
                    "original execution identity"
                )
        else:
            if str(recovered.get("state") or "") not in {"SETTLED", HOLD_RELEASED}:
                return self._block(
                    "central recovery did not settle the single-slot execution",
                    retryable=True,
                )
            if str(refreshed.get("status") or "") not in TERMINAL_TASK_STATUSES:
                return self._block(_UNCONFIRMED_SINGLE_SLOT, retryable=True)
        error = settlement_error(
            refreshed, record,
            node_id=self._node_id(),
            require_process_identity=True,
        )
        if error:
            return self._block(error)
        return refreshed


__all__ = ["NodeRecoveryCoordinator"]
