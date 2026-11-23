from __future__ import annotations

import sys
import time
from types import SimpleNamespace

import pytest

from platform_core.node_agent_execution_slots import BoundedExecutionSlots, SlotCapacityError
from platform_core.task_runtime.process_control import ProcessController, launch_process


def lease(task_id, generation=1):
    return SimpleNamespace(task_id=task_id, generation=generation)


def test_two_real_cpu_processes_overlap_and_third_is_rejected():
    slots = BoundedExecutionSlots(2)
    controller = ProcessController()
    started = {}
    closed = {}
    handles = {}

    def run(slot, lease_value):
        handle = launch_process([sys.executable, "-c", "import time; time.sleep(30)"])
        handles[lease_value.task_id] = handle
        started[lease_value.task_id] = time.monotonic()
        try:
            while not slot.stop_event.wait(0.02):
                pass
        finally:
            controller.terminate_tree(handle.identity, timeout=3.0)
            closed[lease_value.task_id] = time.monotonic()
        return "CANCELLED"

    try:
        slots.submit(lease("a"), run)
        slots.submit(lease("b"), run)
        deadline = time.monotonic() + 10
        while not {"a", "b"}.issubset(started) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert {"a", "b"} <= set(started)
        assert abs(started["a"] - started["b"]) < 5
        with pytest.raises(SlotCapacityError):
            slots.submit(lease("c"), run)
        assert "c" not in handles
        assert slots.cancel("a", 1) is True
        deadline = time.monotonic() + 10
        while "a" not in closed and time.monotonic() < deadline:
            time.sleep(0.02)
        assert "a" in closed
        assert handles["b"].process.poll() is None
        slots.cancel("b", 1)
        slots.wait(10)
        assert {"a", "b"} <= set(closed)
        assert handles["a"].process.poll() is not None
        assert handles["b"].process.poll() is not None
    finally:
        for handle in handles.values():
            if handle.process.poll() is None:
                controller.terminate_tree(handle.identity, timeout=3.0)
        slots.shutdown()
