from __future__ import annotations

import json
import sys
import time
from types import SimpleNamespace

import pytest

from platform_core.node_agent_execution_slots import (
    BoundedExecutionSlots,
    SlotCapacityError,
    SlotNotReleased,
)
from platform_core.task_runtime.process_control import ProcessController, launch_process


def lease(task_id, generation=1, *, gpu_uuid=""):
    config = {"selected_gpu": {"uuid": gpu_uuid}} if gpu_uuid else {}
    return SimpleNamespace(
        task_id=task_id,
        generation=generation,
        assignment={
            "generation": int(generation),
            "resolved_execution_config": config,
        },
    )


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


def test_slot_intent_persists_assignment_and_execution_generations_separately(tmp_path):
    import json
    slots = BoundedExecutionSlots(1, persist_path=tmp_path / "intents.json")
    local_reservation = SimpleNamespace(task_id="task-1", generation=5)
    execution_lease = SimpleNamespace(
        task_id="task-1", generation=2,
        assignment={"generation": 5, "resolved_execution_config": {
            "selected_gpu": {"uuid": "GPU-A"}}},
    )
    slot = slots.reserve(local_reservation, gpu_uuid="GPU-A")
    slots.mark_started(slot, execution_lease)
    records = json.loads((tmp_path / "intents.json").read_text(encoding="utf-8"))
    assert records[0]["execution_attempt"] == 2
    assert records[0]["assignment_generation"] == 5
    assert records[0]["generation"] == 5
    slots.abort_reserved(slot)


def test_mark_started_rejects_central_assignment_identity_mismatch(tmp_path):
    slots = BoundedExecutionSlots(1, persist_path=tmp_path / "intents.json")
    local_reservation = SimpleNamespace(task_id="task-1", generation=5)
    slot = slots.reserve(local_reservation, gpu_uuid="GPU-A")
    wrong = SimpleNamespace(
        task_id="task-1", generation=2,
        assignment={"generation": 9, "resolved_execution_config": {
            "selected_gpu": {"uuid": "GPU-A"}}},
    )
    with pytest.raises(SlotNotReleased, match="assignment generation"):
        slots.mark_started(slot, wrong)
    # A rejected central identity must not pollute the local reservation: the
    # slot still owns its original lease and has never bound an attempt.
    assert slot.state == "LOCAL_RESERVED"
    assert slot.generation == 5
    assert slot.assignment_generation == 5
    assert slot.lease is local_reservation
    assert slot.execution_attempt == 0
    records = json.loads((tmp_path / "intents.json").read_text(encoding="utf-8"))
    assert records == [{
        "task_id": "task-1", "generation": 5, "gpu_uuid": "GPU-A",
        "state": "LOCAL_RESERVED", "execution_attempt": 0,
        "assignment_generation": 5,
    }]


def test_mark_started_rejects_wrong_gpu_or_missing_assignment_without_pollution(tmp_path):
    slots = BoundedExecutionSlots(1, persist_path=tmp_path / "intents.json")
    local_reservation = SimpleNamespace(task_id="task-1", generation=5)
    slot = slots.reserve(local_reservation, gpu_uuid="GPU-A")
    wrong_gpu = SimpleNamespace(
        task_id="task-1", generation=2,
        assignment={"generation": 5, "resolved_execution_config": {
            "selected_gpu": {"uuid": "GPU-B"}}},
    )
    with pytest.raises(SlotNotReleased, match="GPU"):
        slots.mark_started(slot, wrong_gpu)
    missing_evidence = SimpleNamespace(task_id="task-1", generation=2)
    with pytest.raises(SlotNotReleased, match="assignment evidence"):
        slots.mark_started(slot, missing_evidence)
    wrong_task = SimpleNamespace(task_id="task-2", generation=2, assignment={
        "generation": 5,
        "resolved_execution_config": {"selected_gpu": {"uuid": "GPU-A"}},
    })
    with pytest.raises(SlotNotReleased, match="task mismatch"):
        slots.mark_started(slot, wrong_task)

    assert slot.state == "LOCAL_RESERVED"
    assert slot.lease is local_reservation
    assert slot.execution_attempt == 0
    records = json.loads((tmp_path / "intents.json").read_text(encoding="utf-8"))
    assert records[0]["execution_attempt"] == 0
    assert records[0]["state"] == "LOCAL_RESERVED"


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
        a = slots.submit(lease("a", gpu_uuid="GPU-UUID-A"), run, gpu_uuid="GPU-UUID-A", slot_id="slot-a")
        with pytest.raises(SlotCapacityError, match="GPU UUID"):
            slots.submit(lease("dup", gpu_uuid="GPU-UUID-A"), run, gpu_uuid="GPU-UUID-A", slot_id="slot-dup")
        b = slots.submit(lease("b", gpu_uuid="GPU-UUID-B"), run, gpu_uuid="GPU-UUID-B", slot_id="slot-b")
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


def test_confirm_requires_worker_exit_and_rejects_stale_slot():
    controller = ProcessController()
    slots = BoundedExecutionSlots(1)

    def run(slot, lease_value):
        handle = launch_process([sys.executable, "-c", "import time; time.sleep(30)"])
        slot.identity = handle.identity
        while not slot.stop_event.wait(0.02):
            pass

    slot = slots.submit(lease("a"), run)
    try:
        deadline = time.monotonic() + 10
        while slot.identity is None and time.monotonic() < deadline:
            time.sleep(0.02)
        with pytest.raises(SlotNotReleased, match="worker has not exited"):
            slots.confirm_stopped(slot, controller)
        slots.request_cancel("a", 1)
        slots.wait(10)
        assert slots.confirm_stopped(slot, controller, timeout=5.0) is True
        with pytest.raises(SlotNotReleased, match="not the current"):
            slots.confirm_stopped(slot, controller, timeout=5.0)
        replacement = slots.submit(lease("a"), run)
        with pytest.raises(SlotNotReleased, match="not the current"):
            slots.confirm_stopped(slot, controller, timeout=5.0)
        slots.request_cancel("a", 1)
        slots.wait(10)
        assert slots.confirm_stopped(replacement, controller, timeout=5.0) is True
    finally:
        slots.shutdown()


def test_no_launch_slot_can_release_only_with_explicit_central_allowance():
    from types import SimpleNamespace
    slots = BoundedExecutionSlots(1)
    reservation = SimpleNamespace(task_id="no-launch", generation=1)
    execution_lease = SimpleNamespace(
        task_id="no-launch", generation=2,
        assignment={"generation": 1, "resolved_execution_config": {
            "selected_gpu": {"uuid": "GPU-A"}}},
    )
    slot = slots.reserve(reservation, gpu_uuid="GPU-A")
    slots.mark_started(slot, execution_lease)
    slots.start_worker(slot, lambda _slot, _lease: (_ for _ in ()).throw(RuntimeError("preflight")))
    slots.wait(5)
    controller = type("Controller", (), {"terminate_tree": lambda *args, **kwargs: None})()
    assert slots.confirm_stopped(slot, controller) is False
    assert slots.active() == (slot,)
    assert slots.confirm_stopped(slot, controller, allow_no_process=True) is True
    assert slots.active() == ()


def test_persisted_unknown_intent_blocks_restart(tmp_path):
    from types import SimpleNamespace
    path = tmp_path / "dual-intents.json"
    first = BoundedExecutionSlots(2, persist_path=path)
    slot = first.reserve(SimpleNamespace(task_id="a", generation=2),
                         gpu_uuid="GPU-A", slot_id="slot-a")
    first.mark_central_unknown(slot, RuntimeError("lost response"))
    restarted = BoundedExecutionSlots(2, persist_path=path)
    assert restarted.blocked_reason == "PERSISTED_DUAL_SLOT_INTENT_REQUIRES_RECONCILIATION"
    with pytest.raises(SlotCapacityError):
        restarted.reserve(SimpleNamespace(task_id="b", generation=1), gpu_uuid="GPU-B")


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
