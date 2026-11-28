"""Formal POSIX E2E: real ``node_agent.py`` OS process SIGKILL recovery.

The chain under test is the production one:

    real node_agent.py OS process
      -> claim TRAINING from the central HTTP server
      -> launch a real child Worker process
      -> persist the original ProcessIdentity + dual-slot intent
      -> SIGKILL the Agent process (worker survives)
      -> a new real Agent process starts on the same state directory
      -> it reads the local evidence, reconciles with central HTTP
      -> stops the original Worker, records the Stop Proof, releases the Hold
      -> clears the local identity/slot intent
      -> admits the next task

Only the training worker script is the established test double.  The central
service, HTTP transport, Agent entrypoint, recovery coordinator, process
control and identity persistence are production code.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import signal
import sys
from pathlib import Path

import pytest


def _load_support():
    """Load the sibling harness by path (tests are not a Python package)."""
    name = "real_agent_crash_recovery_e2e_support"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    path = Path(__file__).with_name("_real_agent_crash_recovery_support.py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


support = _load_support()

ORIGINAL_TASK = "sigkill-original-task"
NEXT_TASK = "sigkill-next-task"
TERMINAL = {"FAILED", "CANCELLED", "SUCCEEDED", "PARTIAL_SUCCESS",
            "BLOCKED_BY_ENVIRONMENT", "BLOCKED_BY_HARDWARE"}


def _identity_sha256(identity: dict) -> str:
    return hashlib.sha256(support.canonical_json({
        "pid": int(identity["pid"]),
        "create_time": float(identity["create_time"]),
        "command_hash": str(identity["command_hash"]),
    }).encode("utf-8")).hexdigest()


@pytest.mark.skipif(os.name != "posix", reason="POSIX SIGKILL OS process recovery proof")
def test_real_agent_sigkill_full_os_process_recovery(tmp_path):
    support.unit_fixtures()
    state_dir = tmp_path / "agent-state"
    data_dir = tmp_path / "agent-data"
    staged = support.write_staged_runtime(tmp_path / "runtime", sleep_seconds=900.0)
    stack = support.start_central(tmp_path)
    storage = support.BundleStorage()
    agents: list[dict] = []
    original_identity = None
    next_identity = None
    context: dict = {"state_dir": state_dir, "repository": stack["repository"]}
    try:
        support.create_training_task(
            stack, tmp_path, storage, task_id=ORIGINAL_TASK, gpu_uuid=support.GPU_A,
        )
        support.assign_next(stack)
        first = support.launch_agent(
            staged, stack, state_dir=state_dir, data_dir=data_dir,
            log_path=tmp_path / "agent-first.log",
        )
        agents.append(first)
        context["agent"] = first
        original_identity = support.wait_worker_started(
            stack, staged, state_dir, context, task_id=ORIGINAL_TASK,
        )
        assert support.process_alive(original_identity)
        original_status = support.central_status(stack, ORIGINAL_TASK)
        original_hold = support.hold_row(stack["repository"], ORIGINAL_TASK)
        original_assignment_generation = int(original_hold["assignment_generation"])
        original_execution_attempt = int(original_hold["execution_attempt"])
        original_gpu_uuid = str(original_hold["gpu_uuid"])
        assert original_status["status"] == "RUNNING"
        assert original_status["hold_state"] == "HELD"
        # A live HELD execution has no stop proof yet: SQL NULL must stay JSON null.
        assert original_status["proof_type"] is None
        assert original_status["proof_sha256"] is None
        assert original_status["process_identity_sha256"] == _identity_sha256(original_identity)
        assert original_gpu_uuid == support.GPU_A
        assert original_execution_attempt == 1

        # --- SIGKILL only the Agent process, never the Worker -----------------
        first["process"].send_signal(signal.SIGKILL)
        assert first["process"].wait(timeout=20) == -signal.SIGKILL
        assert support.process_alive(original_identity), (
            "Agent SIGKILL must not stop the independently launched Worker"
        )
        after_kill = support.central_status(stack, ORIGINAL_TASK)
        assert after_kill["status"] == "RUNNING"
        assert after_kill["hold_state"] == "HELD"
        assert support.task_row(stack["repository"], ORIGINAL_TASK)["process_pid"] == original_identity["pid"]

        # The next task is assigned while the original execution still owns its
        # HELD resource, exercising capacity release + admission after recovery.
        support.heartbeat_with_gpus(stack)
        support.create_training_task(
            stack, tmp_path, storage, task_id=NEXT_TASK, gpu_uuid=support.GPU_B,
        )
        support.assign_next(stack)

        # --- new real Agent process on the same state dir --------------------
        second = support.launch_agent(
            staged, stack, state_dir=state_dir, data_dir=data_dir,
            log_path=tmp_path / "agent-second.log",
        )
        agents.append(second)
        context["agent"] = second

        # 1) The original Worker is stopped by the recovery coordinator.
        assert support.wait_process_gone(original_identity, timeout=60), (
            "restarted Agent did not stop the original Worker with the recovered identity"
        )
        # 2) Central reconciliation: FAILED + RELEASED + PROCESS_STOP_VERIFIED.
        def recovered_status():
            status = support.central_status(stack, ORIGINAL_TASK)
            if (
                status["status"] == "FAILED"
                and status["hold_state"] == "RELEASED"
                and status["proof_type"] == "PROCESS_STOP_VERIFIED"
                and status["proof_sha256"]
            ):
                return status
            return None

        settled = support.wait_for(
            recovered_status, timeout=90,
            message="central did not record the recovered stop proof",
            context=context,
        )
        task = support.task_row(stack["repository"], ORIGINAL_TASK)
        hold = support.hold_row(stack["repository"], ORIGINAL_TASK)
        assert task["status"] == "FAILED"
        assert task["process_pid"] == original_identity["pid"], (
            "the original registered process identity must remain the audit anchor"
        )
        assert hold["state"] == "RELEASED"
        assert hold["proof_type"] == "PROCESS_STOP_VERIFIED"
        assert int(hold["assignment_generation"]) == original_assignment_generation
        assert int(hold["execution_attempt"]) == original_execution_attempt
        assert str(hold["gpu_uuid"]) == original_gpu_uuid
        assert settled["hold_execution_attempt"] == original_execution_attempt
        assert settled["hold_assignment_generation"] == original_assignment_generation
        assert settled["hold_gpu_uuid"] == original_gpu_uuid
        expected_digest = support.expected_stop_proof_digest(
            node_id=support.NODE_ID,
            task_id=ORIGINAL_TASK,
            assignment_generation=original_assignment_generation,
            execution_generation=original_execution_attempt,
            gpu_uuid=original_gpu_uuid,
            identity=original_identity,
        )
        assert hold["proof_sha256"] == expected_digest, (
            "central stop proof must be recomputable from the original local ProcessIdentity"
        )
        assert settled["proof_sha256"] == expected_digest

        # 3) Local identity / slot intent for the recovered execution is cleared.
        support.wait_for(
            lambda: support.local_identity(state_dir, ORIGINAL_TASK, 1) is None,
            timeout=30,
            message="recovered local ProcessIdentity was not cleared",
            context=context,
        )
        recovered_records = [
            record for record in support.intent_records(state_dir)
            if record.get("task_id") == ORIGINAL_TASK
        ]
        assert recovered_records == [], (
            f"recovered dual-slot intent was not cleared: {recovered_records}"
        )

        # 4) The original task is never scheduled again.
        support.assert_no_duplicate_execution(stack["repository"], ORIGINAL_TASK)

        # 5) The restarted Agent republishes its capability set.
        def capabilities_restored():
            node = support.node_public(stack)
            reported = set(node["reported_capabilities"])
            if {"training", "execution-slots:2"} <= reported:
                return node
            return None

        support.wait_for(
            capabilities_restored, timeout=90,
            message="restarted Agent did not republish its execution capabilities",
            context=context,
        )

        # 6) New task admission: the next assignment reaches RUNNING on a new PID.
        def next_running():
            status = support.central_status(stack, NEXT_TASK)
            if status["status"] in TERMINAL:
                raise AssertionError(f"next task failed instead of running: {status}")
            return status if status["status"] == "RUNNING" else None

        next_status = support.wait_for(
            next_running, timeout=120,
            message="restarted Agent did not admit the next TRAINING task",
            context=context,
        )
        next_identity = support.wait_for(
            lambda: support.local_identity(state_dir, NEXT_TASK, 1),
            timeout=60,
            message="next task worker identity was not persisted",
            context=context,
        )
        assert int(next_identity["pid"]) != int(original_identity["pid"])
        assert support.process_alive(next_identity)
        assert next_status["hold_state"] == "HELD"
        assert next_status["hold_gpu_uuid"] == support.GPU_B
        assert support.local_identity(state_dir, ORIGINAL_TASK, 1) is None, (
            "the recovered original identity must not be reused by the next task"
        )
        next_records = [
            record for record in support.intent_records(state_dir)
            if record.get("task_id") == NEXT_TASK
        ]
        assert next_records, "next task dual-slot intent was not persisted"
        original_after = support.central_status(stack, ORIGINAL_TASK)
        assert original_after["status"] == "FAILED"
        assert original_after["hold_state"] == "RELEASED"
    finally:
        for agent in agents:
            support.stop_agent(agent)
        for identity in (original_identity, next_identity):
            support.kill_process_identity(identity)
        try:
            for record in support.local_workdirs(state_dir).list_process_identities():
                support.kill_process_identity(record)
        except Exception:
            pass
        storage.stop()
        support.stop_central(stack)


def test_real_agent_restart_is_fail_closed_without_stop_proof(tmp_path):
    """Cross-platform restart contract (passes on Windows and POSIX hosts)."""
    support.run_restart_fail_closed_scenario(tmp_path)
