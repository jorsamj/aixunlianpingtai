"""Bounded, opt-in Node Agent execution slots (CPU protocol foundation).

Production default is one slot. Two slots are only admitted when the caller
explicitly supplies max_slots=2 after central authorization and local safety
checks. This module does not replace TaskRepository, leases, or GPU admission.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Any


class SlotCapacityError(RuntimeError):
    pass


@dataclass
class ExecutionSlot:
    task_id: str
    generation: int
    lease: Any
    stop_event: threading.Event = field(default_factory=threading.Event)
    outcome: Any = None
    error: BaseException | None = None


class BoundedExecutionSlots:
    def __init__(self, max_slots: int = 1) -> None:
        if max_slots not in (1, 2):
            raise ValueError("max_slots must be 1 or 2")
        self.max_slots = int(max_slots)
        self._lock = threading.RLock()
        self._slots: dict[tuple[str, int], tuple[ExecutionSlot, threading.Thread]] = {}

    def active(self) -> tuple[ExecutionSlot, ...]:
        with self._lock:
            return tuple(slot for slot, _thread in self._slots.values() if _thread.is_alive())

    def submit(self, lease: Any, run: Callable[[ExecutionSlot, Any], Any]) -> ExecutionSlot:
        key = (str(lease.task_id), int(lease.generation))
        with self._lock:
            if key in self._slots:
                raise SlotCapacityError("execution slot is already owned")
            live = [item for item in self._slots.values() if item[1].is_alive()]
            if len(live) >= self.max_slots:
                raise SlotCapacityError("execution slot capacity is full")
            slot = ExecutionSlot(key[0], key[1], lease)

            def execute() -> None:
                try:
                    slot.outcome = run(slot, lease)
                except BaseException as error:  # noqa: BLE001 - retained for owner
                    slot.error = error
                finally:
                    with self._lock:
                        self._slots.pop(key, None)

            thread = threading.Thread(target=execute, name=f"agent-slot-{key[0]}", daemon=True)
            self._slots[key] = (slot, thread)
            thread.start()
            return slot

    def cancel(self, task_id: str, generation: int) -> bool:
        with self._lock:
            item = self._slots.get((str(task_id), int(generation)))
        if item is None:
            return False
        item[0].stop_event.set()
        return True

    def wait(self, timeout: float | None = None) -> None:
        deadline = None if timeout is None else __import__("time").monotonic() + timeout
        while True:
            with self._lock:
                threads = [thread for _slot, thread in self._slots.values() if thread.is_alive()]
            if not threads:
                return
            for thread in threads:
                remaining = None if deadline is None else max(0.0, deadline - __import__("time").monotonic())
                thread.join(remaining)
            if deadline is not None and __import__("time").monotonic() >= deadline:
                return

    def shutdown(self, timeout: float = 10.0) -> None:
        with self._lock:
            slots = [slot for slot, _thread in self._slots.values()]
        for slot in slots:
            slot.stop_event.set()
        self.wait(timeout)
