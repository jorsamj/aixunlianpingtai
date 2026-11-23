from __future__ import annotations

import sys
import time
from types import SimpleNamespace

import pytest

from platform_core.node_agent_execution_slots import BoundedExecutionSlots, SlotCapacityError
from platform_core.task_runtime.process_control import ProcessController, launch_process


def lease(task_id, generation=1):
    return SimpleNamespace(task_id=task_id, generation=generation)


def child_slot_runner(controller, *, clean_on_stop=True):
    def run(slot, lease_value):
        handle = launch_process([sys.executable, "-c", "import time; time.sleep(30)"])
        slot.identity = handle.identity
        try:
            while not slot.stop_event.wait(0.02):
                pass
            return "CANCELLED"
        finally:
            if clean_on_stop:
                controller.terminate_tree(handle.identity, timeout=3.0)
    return run


def test_stop_proof_required_before_capacity_can_be_reused():
    controller = ProcessController()
    slots = BoundedExecutionSlots(2)
    running = {}
    started = {}

    def run(slot, lease_value):
        handle = launch_process([sys.executable, "-c", "import time; time.sleep(30)"])
        slot.identity = handle.identity
        running[lease_value.task_id] = handle
        started[lease_value.task_id] = time.monotonic()
        while not slot.stop_event.wait(0.02):
            pass
        return "CANCELLED"

    try:
        a = slots.submit(lease("a"), run)
        b = slots.submit(lease("b"), run)
        deadline = time.monotonic() + 10
        while not {"a", "b"}.issubset(started) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert abs(started["a"] - started["b"]) < 5
        with pytest.raises(SlotCapacityError):
            slots.submit(lease("c"), run)

        assert slots.request_cancel("a", 1) is True
        deadline = time.monotonic() + 10
        while not a.worker_exited and time.monotonic() < deadline:
            time.sleep(0.02)
        assert a.worker_exited
        assert running["a"].process.poll() is None  # worker exit is not stop proof
        assert running["b"].process.poll() is None
        assert len(slots.active()) == 2

        assert slots.confirm_stopped(a, controller, timeout=5.0) is True
        assert running["a"].process.poll() is not None
        c = slots.submit(lease("c"), run)
        assert running["b"].process.poll() is None
        assert slots.request_cancel("b", 1) is True
        assert slots.request_cancel("c", 1) is True
        slots.wait(10)
        assert slots.confirm_stopped(b, controller, timeout=5.0) is True
        assert slots.confirm_stopped(c, controller, timeout=5.0) is True
        assert slots.active() == ()
    finally:
        for handle in running.values():
            if handle.process.poll() is None:
                controller.terminate_tree(handle.identity, timeout=3.0)
        slots.shutdown()


def test_worker_exception_keeps_slot_quarantined_until_proof():
    controller = ProcessController()
    slots = BoundedExecutionSlots(2)
    handles = {}

    def crash(slot, lease_value):
        handle = launch_process([sys.executable, "-c", "import time; time.sleep(30)"])
        slot.identity = handle.identity
        handles[lease_value.task_id] = handle
        raise RuntimeError("worker crashed while child remains")

    try:
        a = slots.submit(lease("a"), crash)
        deadline = time.monotonic() + 10
        while not a.worker_exited and time.monotonic() < deadline:
            time.sleep(0.02)
        assert a.error is not None
        assert handles["a"].process.poll() is None
        c = slots.submit(lease("c"), child_slot_runner(controller))
        with pytest.raises(SlotCapacityError):
            slots.submit(lease("c2"), child_slot_runner(controller))
        assert slots.confirm_stopped(a, controller, timeout=5.0) is True
        assert handles["a"].process.poll() is not None
        slots.request_cancel("c", 1)
        slots.wait(10)
        assert slots.confirm_stopped(c, controller, timeout=5.0) is True
        assert slots.active() == ()
    finally:
        for handle in handles.values():
            if handle.process.poll() is None:
                controller.terminate_tree(handle.identity, timeout=3.0)
        slots.shutdown()


def test_shutdown_timeout_never_reports_released():
    controller = ProcessController()
    slots = BoundedExecutionSlots(1)
    handles = {}

    def stuck(slot, lease_value):
        handle = launch_process([sys.executable, "-c", "import time; time.sleep(30)"])
        slot.identity = handle.identity
        handles[lease_value.task_id] = handle
        while not slot.stop_event.wait(0.02):
            pass
        time.sleep(2.0)  # ignores prompt exit; child remains alive

    slot = slots.submit(lease("a"), stuck)
    try:
        deadline = time.monotonic() + 10
        while slot.identity is None and time.monotonic() < deadline:
            time.sleep(0.02)
        remaining = slots.shutdown(timeout=0.2)
        assert slot in remaining
        assert slots.active() == (slot,)
        assert handles["a"].process.poll() is None
    finally:
        slot.stop_event.set()
        if handles.get("a") is not None:
            controller.terminate_tree(handles["a"].identity, timeout=3.0)
