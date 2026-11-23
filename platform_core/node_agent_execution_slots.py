"""Bounded, opt-in Node Agent execution slots (CPU protocol foundation).

Capacity is never released merely because a Python worker thread exited. A
slot stays occupied until an explicit stop proof (existing ProcessController +
ProcessIdentity) succeeds; otherwise it is quarantined.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable


class SlotCapacityError(RuntimeError):
    pass


class SlotNotReleased(RuntimeError):
    pass


@dataclass
class ExecutionSlot:
    task_id: str
    generation: int
    lease: Any = None
    gpu_uuid: str = ""
    slot_id: str = ""
    state: str = "LOCAL_RESERVED"
    execution_attempt: int = 0
    stop_event: threading.Event = field(default_factory=threading.Event)
    identity: Any = None
    outcome: Any = None
    error: BaseException | None = None
    worker_exited: bool = False
    released: bool = False
    quarantined: bool = False
    started_at: float = 0.0
    exited_at: float = 0.0


class BoundedExecutionSlots:
    def __init__(self, max_slots: int = 1) -> None:
        if max_slots not in (1, 2):
            raise ValueError("max_slots must be 1 or 2")
        self.max_slots = int(max_slots)
        self._lock = threading.RLock()
        self._slots: dict[tuple[str, int], tuple[ExecutionSlot, threading.Thread | None]] = {}

    def active(self) -> tuple[ExecutionSlot, ...]:
        """All occupied slots, including exited/quarantined-but-unreleased."""
        with self._lock:
            return tuple(
                slot for slot, _thread in self._slots.values() if not slot.released
            )

    def reserve(
        self, lease: Any, *, gpu_uuid: str = "", slot_id: str = ""
    ) -> ExecutionSlot:
        key = (str(lease.task_id), int(lease.generation))
        with self._lock:
            if key in self._slots:
                raise SlotCapacityError("execution slot is already owned")
            if len(self._slots) >= self.max_slots:
                raise SlotCapacityError("execution slot capacity is full")
            if gpu_uuid and any(
                slot.gpu_uuid == str(gpu_uuid) for slot, _thread in self._slots.values()
            ):
                raise SlotCapacityError("GPU UUID is already reserved by another slot")
            slot = ExecutionSlot(
                key[0], key[1], lease=lease, gpu_uuid=str(gpu_uuid or ""),
                slot_id=str(slot_id or ""), started_at=time.monotonic(),
            )
            self._slots[key] = (slot, None)
            return slot

    def mark_started(self, slot: ExecutionSlot, lease: Any) -> None:
        with self._lock:
            current = self._slots.get((slot.task_id, slot.generation))
            if current is None or current[0] is not slot:
                raise SlotNotReleased("local reservation is no longer current")
            if slot.state != "LOCAL_RESERVED":
                raise SlotNotReleased("local reservation is not in reserved state")
            slot.lease = lease
            slot.execution_attempt = int(getattr(lease, "generation", 0) or 0)
            slot.state = "CENTRAL_STARTED"

    def abort_reserved(self, slot: ExecutionSlot, error: BaseException | None = None) -> None:
        """Abort only a never-started local reservation; central-started is never freed here."""
        with self._lock:
            current = self._slots.get((slot.task_id, slot.generation))
            if current is None or current[0] is not slot:
                return
            if slot.state != "LOCAL_RESERVED":
                slot.quarantined = True
                return
            if error is not None:
                slot.error = error
            slot.released = True
            self._slots.pop((slot.task_id, slot.generation), None)

    def mark_central_unknown(self, slot: ExecutionSlot, error: BaseException | None = None) -> None:
        with self._lock:
            current = self._slots.get((slot.task_id, slot.generation))
            if current is not None and current[0] is slot:
                slot.state = "CENTRAL_UNKNOWN"
                slot.quarantined = True
                if error is not None:
                    slot.error = error

    def start_worker(
        self, slot: ExecutionSlot, run: Callable[[ExecutionSlot, Any], Any]
    ) -> ExecutionSlot:
        with self._lock:
            current = self._slots.get((slot.task_id, slot.generation))
            if current is None or current[0] is not slot:
                raise SlotNotReleased("local reservation is no longer current")
            if slot.state != "CENTRAL_STARTED":
                raise SlotNotReleased("central start is not confirmed")
            if current[1] is not None:
                raise SlotNotReleased("slot worker already started")
            lease = slot.lease

            def execute() -> None:
                slot.state = "RUNNING"
                try:
                    slot.outcome = run(slot, lease)
                except BaseException as error:  # noqa: BLE001 - retained for recovery
                    slot.error = error
                    slot.state = "WORKER_FAILED"
                finally:
                    slot.worker_exited = True
                    slot.exited_at = time.monotonic()
                    if slot.state == "RUNNING":
                        slot.state = "STOP_PENDING"

            thread = threading.Thread(target=execute, name=f"agent-slot-{slot.task_id}", daemon=True)
            self._slots[(slot.task_id, slot.generation)] = (slot, thread)
            thread.start()
            return slot

    def submit(
        self,
        lease: Any,
        run: Callable[[ExecutionSlot, Any], Any],
        *,
        gpu_uuid: str = "",
        slot_id: str = "",
    ) -> ExecutionSlot:
        slot = self.reserve(lease, gpu_uuid=gpu_uuid, slot_id=slot_id)
        try:
            self.mark_started(slot, lease)
            return self.start_worker(slot, run)
        except Exception:
            self.abort_reserved(slot)
            raise

    def request_cancel(self, task_id: str, generation: int) -> bool:
        with self._lock:
            item = self._slots.get((str(task_id), int(generation)))
        if item is None or item[0].released:
            return False
        item[0].stop_event.set()
        return True

    def confirm_stopped(self, slot: ExecutionSlot, controller: Any, *, timeout: float = 8.0) -> bool:
        """Release capacity only after worker exit AND ProcessController proof."""
        key = (slot.task_id, slot.generation)
        with self._lock:
            current = self._slots.get(key)
            if current is None or current[0] is not slot:
                # A newer slot with the same task/generation must not be
                # released by a stale confirmation.
                raise SlotNotReleased("slot is not the current registered execution")
            if not slot.worker_exited:
                raise SlotNotReleased("execution worker has not exited")
            if slot.identity is None:
                slot.quarantined = True
                return False
        try:
            controller.terminate_tree(slot.identity, timeout=timeout)
        except Exception:
            slot.quarantined = True
            return False
        with self._lock:
            current = self._slots.get(key)
            if current is None or current[0] is not slot:
                return False
            slot.released = True
            self._slots.pop(key, None)
        return True

    def wait(self, timeout: float | None = None) -> None:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                threads = [thread for _slot, thread in self._slots.values()
                           if thread is not None and thread.is_alive()]
            if not threads:
                return
            for thread in threads:
                remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                thread.join(remaining)
            if deadline is not None and time.monotonic() >= deadline:
                return

    def shutdown(self, timeout: float = 10.0) -> tuple[ExecutionSlot, ...]:
        """Request stop and return slots still not proven released."""
        with self._lock:
            slots = [slot for slot, _thread in self._slots.values() if not slot.released]
        for slot in slots:
            slot.stop_event.set()
        self.wait(timeout)
        with self._lock:
            return tuple(slot for slot, _thread in self._slots.values() if not slot.released)
