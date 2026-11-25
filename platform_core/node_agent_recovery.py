"""Node-level recovery coordination for Node Agent execution slots.

This module deliberately uses the existing workdir process identities and
ProcessController.  It does not create a second task-state database.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .node_agent_training_runtime import AgentExecutionWorkdir
    from .task_runtime.process_control import ProcessController


TERMINAL_TASK_STATUSES = frozenset({
    "SUCCEEDED",
    "PARTIAL_SUCCESS",
    "CANCELLED",
    "FAILED",
    "BLOCKED_BY_ENVIRONMENT",
    "BLOCKED_BY_HARDWARE",
})
PROCESS_STOP_VERIFIED = "PROCESS_STOP_VERIFIED"


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
    def _digest(value: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()

    @classmethod
    def _identity_sha256(cls, record: dict[str, Any]) -> str:
        return cls._digest({
            "pid": int(record["pid"]),
            "create_time": float(record["create_time"]),
            "command_hash": str(record["command_hash"]),
        })

    @classmethod
    def _stop_proof_digests(
        cls, status: dict[str, Any], record: dict[str, Any],
    ) -> tuple[str, str]:
        """Recompute the acceptable stop-proof digests from local evidence.

        The first digest is the current proof schema, the second the frozen
        schema-6/7 legacy digest that predates proof_type/no-launch fields.
        """
        base = {
            "node_id": str(status.get("node_id") or ""),
            "task_id": str(record["task_id"]),
            "assignment_generation": int(record.get("assignment_generation") or 0),
            "execution_attempt": int(record["generation"]),
            "gpu_uuid": str(record.get("gpu_uuid") or ""),
            "process_identity": {
                "pid": int(record["pid"]),
                "create_time": float(record["create_time"]),
                "command_hash": str(record["command_hash"]),
            },
            "stop_verified": True,
        }
        current = dict(base)
        current["proof_type"] = PROCESS_STOP_VERIFIED
        current["no_process_launched"] = False
        current["no_launch_evidence"] = {}
        return cls._digest(current), cls._digest(base)

    def _hold_identity_error(
        self,
        status: dict[str, Any],
        record: dict[str, Any],
        local_assignment: int,
        local_gpu: str,
    ) -> str:
        if int(status.get("hold_execution_attempt") or 0) != int(record["generation"]):
            return "central Hold execution attempt mismatch"
        if int(status.get("hold_assignment_generation") or 0) != int(local_assignment):
            return "central Hold assignment generation mismatch"
        if str(status.get("hold_gpu_uuid") or "") != local_gpu:
            return "central Hold GPU UUID mismatch"
        return ""

    def _proof_error(self, status: dict[str, Any], record: dict[str, Any]) -> str:
        """Post-verify the recorded stop proof against the original identity."""
        hold_state = str(status.get("hold_state") or "")
        proof_type = str(status.get("proof_type") or "")
        proof_sha256 = str(status.get("proof_sha256") or "")
        if hold_state in {"STOP_VERIFIED", "RELEASED"}:
            if proof_type != PROCESS_STOP_VERIFIED:
                return "central stop proof type mismatch"
            if not proof_sha256:
                return "central stop proof digest is missing"
            current, legacy = self._stop_proof_digests(status, record)
            if not (hmac.compare_digest(proof_sha256, current)
                    or hmac.compare_digest(proof_sha256, legacy)):
                return "central stop proof digest mismatch"
            return ""
        if hold_state == "HELD":
            if proof_sha256 or proof_type:
                return "central stop proof recorded for a held execution"
            return ""
        return "central Hold state is invalid"

    def _single_slot_contract_error(
        self,
        status: dict[str, Any],
        record: dict[str, Any],
        local_assignment: int,
    ) -> str:
        """Validate the original single-slot recovery contract.

        A single-slot execution never created a resource Hold, so its durable
        evidence is the execution attempt, the released Assignment that started
        it, and the registered ProcessIdentity. It must not be blocked merely
        because no Hold exists, and it must not borrow the dual-slot proof.
        """
        if status.get("hold_state") is not None or status.get("hold_execution_attempt") is not None:
            return "central Hold present for single-slot execution"
        if status.get("proof_type") or status.get("proof_sha256"):
            return "central stop proof present without a Hold"
        central_assignment = status.get("assignment_generation")
        if local_assignment > 0 and central_assignment is not None:
            if int(central_assignment) != int(local_assignment):
                return "central assignment generation mismatch"
        return ""

    def _status_matches_identity(self, status: dict[str, Any], record: dict[str, Any]) -> str:
        if str(status.get("task_id")) != str(record["task_id"]):
            return "central task identity mismatch"
        node_id = str(getattr(self.client, "node_id", "") or "")
        if node_id and str(status.get("node_id")) != node_id:
            return "central node identity mismatch"
        if int(status.get("execution_attempt") or 0) != int(record["generation"]):
            return "central execution attempt mismatch"
        if str(status.get("process_identity_sha256") or "") != self._identity_sha256(record):
            return "central ProcessIdentity digest mismatch"

        local_assignment = int(record.get("assignment_generation") or 0)
        local_gpu = str(record.get("gpu_uuid") or "")
        local_slots = int(record.get("execution_slots") or 0)
        has_hold = (
            status.get("hold_state") is not None
            or status.get("hold_execution_attempt") is not None
        )
        if local_slots == 2 or (local_slots == 0 and has_hold):
            # The original contract is a dual slot: either recorded explicitly
            # by the control plane at start, or a pre-marker record that owns a
            # central Hold. A dual-slot execution must carry complete original
            # Assignment/GPU evidence; missing local fields are corruption, not
            # legacy, and a missing central Hold is never bypassed.
            if not has_hold:
                return "central Hold missing for dual-slot execution"
            if local_assignment <= 0:
                return "local Assignment generation missing for dual-slot recovery"
            if not local_gpu:
                return "local GPU UUID missing for dual-slot recovery"
            error = self._hold_identity_error(status, record, local_assignment, local_gpu)
            if error:
                return error
            return self._proof_error(status, record)
        if local_slots == 1 and has_hold:
            return "central Hold present for single-slot execution"
        return self._single_slot_contract_error(status, record, local_assignment)

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
        if str(value.get("proof_type") or "") != PROCESS_STOP_VERIFIED:
            return None, "persisted stop evidence has an unknown proof type"
        if value.get("stop_verified") is not True:
            return None, "persisted stop evidence does not verify a stop"
        if value.get("no_process_launched") is not False:
            return None, "persisted stop evidence contradicts the recorded identity"
        if str(value.get("task_id") or "") != str(record["task_id"]):
            return None, "persisted stop evidence names another task"
        if int(value.get("execution_attempt") or 0) != int(record["generation"]):
            return None, "persisted stop evidence names another execution attempt"
        identity = value.get("process_identity")
        if not isinstance(identity, dict):
            return None, "persisted stop evidence has no process identity"
        create_time = float(identity.get("create_time") or 0.0)
        if not math.isfinite(create_time) or create_time <= 0.0:
            return None, "persisted stop evidence has an invalid create time"
        if (
            int(identity.get("pid") or 0) != int(record["pid"])
            or create_time != float(record["create_time"])
            or str(identity.get("command_hash") or "") != str(record["command_hash"])
        ):
            return None, "persisted stop evidence names another process identity"
        local_assignment = int(record.get("assignment_generation") or 0)
        if local_assignment > 0 and int(value.get("assignment_generation") or 0) != local_assignment:
            return None, "persisted stop evidence names another assignment generation"
        local_gpu = str(record.get("gpu_uuid") or "")
        if local_gpu and str(value.get("gpu_uuid") or "") != local_gpu:
            return None, "persisted stop evidence names another GPU"
        return value, ""

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
                                or str(status.get("status")) not in TERMINAL_TASK_STATUSES
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
                evidence, evidence_error = self._stop_evidence_error(record)
                if evidence_error:
                    self._error = evidence_error
                    return self._error
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
                    hold_state = status.get("hold_state")
                    if (str(status.get("status")) not in TERMINAL_TASK_STATUSES
                            or str(hold_state or "") != "RELEASED"):
                        if hold_state is None:
                            # A single-slot execution has no Hold, but that is not a
                            # central settlement. Until the control plane reports a
                            # terminal task for this exact attempt, the original
                            # identity is the only evidence and must survive; the
                            # existing central lease expiry is the legal path to
                            # that terminal state.
                            if str(status.get("status")) not in TERMINAL_TASK_STATUSES:
                                self._error = (
                                    "single-slot execution is not centrally settled; "
                                    "original process identity retained"
                                )
                                return self._error
                        else:
                            try:
                                recovered = self.client.recover_execution(
                                    str(record["task_id"]),
                                    assignment_generation=int(
                                        record.get("assignment_generation") or 0),
                                    execution_generation=int(record["generation"]),
                                    gpu_uuid=str(record.get("gpu_uuid") or ""),
                                    process_identity={
                                        "pid": int(record["pid"]),
                                        "create_time": float(record["create_time"]),
                                        "command_hash": str(record["command_hash"]),
                                    },
                                )
                                refreshed = self.client.execution_status(
                                    str(record["task_id"]))
                            except Exception as error:
                                self._error = (
                                    "central recovery could not release original execution: "
                                    f"{type(error).__name__}: {error}"
                                )
                                return self._error
                            recovered_digest = str(
                                (recovered or {}).get("proof_sha256") or "")
                            if str(refreshed.get("hold_state")) != "RELEASED":
                                self._error = "central recovery did not release the original Hold"
                                return self._error
                            if (not recovered_digest
                                    or not hmac.compare_digest(
                                        str(refreshed.get("proof_sha256") or ""),
                                        recovered_digest)):
                                self._error = (
                                    "central recovery stop proof does not match the "
                                    "original execution identity"
                                )
                                return self._error
                            refreshed_error = self._status_matches_identity(
                                refreshed, record)
                            if refreshed_error:
                                self._error = refreshed_error
                                return self._error
                            status = refreshed
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
                    self.workdirs.clear_process_identity_record(key[0], key[1])
                except (OSError, ValueError) as error:
                    self._error = (
                        "unowned process identity cleanup could not be persisted: "
                        f"{type(error).__name__}: {error}"
                    )
                    return self._error
            self._error = ""
            return ""
