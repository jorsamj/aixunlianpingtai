from __future__ import annotations

import threading
import time

from platform_core.node_agent_deployment_runtime import AgentDeploymentOutcome
from platform_core.node_agent_executor_loop import (
    NodeAgentExecutorLoop,
    executable_agent_capabilities,
)
from platform_core.node_agent_executor_runtime import RemoteExecutionFenced, RemoteExecutionLease


def lease(task_id="task-1", kind="DEPLOYMENT_TEST"):
    return RemoteExecutionLease(
        task_id=task_id,
        kind=kind,
        project_id="project-1",
        generation=1,
        lease_token="execution-secret",
        lease_expires_at="2026-09-18T10:00:00+00:00",
        worker_id="agent:node-1",
        payload={},
        assignment={},
        transport={},
    )


class FakeClient:
    def __init__(self, claims=None):
        self.claims = list(claims or [])
        self.claim_calls = 0
        self.start_calls = []
        self.finish_calls = []
        self.last_claimed_kind = "DEPLOYMENT_TEST"

    def claim_assignment(self):
        self.claim_calls += 1
        item = self.claims.pop(0) if self.claims else None
        if item is not None:
            self.last_claimed_kind = str((item.get("task") or {}).get("kind") or "DEPLOYMENT_TEST")
        return item

    def start_execution(self, task_id, assignment_token):
        self.start_calls.append((task_id, assignment_token))
        return lease(task_id, self.last_claimed_kind)

    def finish(self, current, status, *, result_ref=None, error=None, accepted=None):
        self.finish_calls.append({
            "task_id": current.task_id,
            "status": status,
            "result_ref": result_ref,
            "error": error,
        })
        return {"task": {"status": status}}


class FakeRunner:
    def __init__(
        self,
        *,
        block=False,
        fenced=False,
        ready=True,
        recovery_error="",
    ):
        self.block = block
        self.fenced = fenced
        self.ready = bool(ready)
        self.recovery_error = str(recovery_error)
        self.started = threading.Event()
        self.release = threading.Event()
        self.shutdown_requested = False
        self.calls = []

    def run(self, current):
        self.calls.append(current.task_id)
        self.started.set()
        if self.block:
            self.release.wait(timeout=5.0)
        if self.fenced or self.shutdown_requested:
            raise RemoteExecutionFenced("ownership moved")
        return AgentDeploymentOutcome(
            current.task_id,
            current.generation,
            "SUCCEEDED",
            result_ref=f"remote-results/{current.generation}/result.json",
        )

    def request_shutdown(self):
        self.shutdown_requested = True
        self.release.set()


def claimed(task_id="task-1", kind="DEPLOYMENT_TEST"):
    return {
        "assignment": {
            "task_id": task_id,
            "assignment_lease_token": "assignment-secret",
        },
        "task": {
            "task_id": task_id,
            "kind": kind,
        },
    }


def test_executor_reports_only_capabilities_this_agent_build_can_run():
    assert executable_agent_capabilities(
        ["training", "deployment-test", "conversion", "conversion.rknn", "material-import", "cleaning", "deployment-test"]
    ) == ["cleaning", "conversion", "conversion.rknn", "deployment-test", "material-import", "training"]
    assert executable_agent_capabilities(["training", "conversion", "conversion.rknn"]) == ["conversion", "conversion.rknn", "training"]


def test_executor_withdraws_training_capability_when_runner_recovery_is_unsafe():
    client = FakeClient([])
    deployment_runner = FakeRunner()
    training_runner = FakeRunner(
        ready=False,
        recovery_error="stale training process cleanup could not be verified",
    )
    loop = NodeAgentExecutorLoop(
        client,
        deployment_runner,
        capabilities=["deployment-test", "training"],
        runners={"TRAINING": training_runner},
    )

    assert loop.capabilities == ("deployment-test", "training")
    assert loop.effective_capabilities() == ("deployment-test",)
    assert "cleanup could not be verified" in loop.status().last_error


def test_run_once_claims_starts_and_dispatches_one_deployment_task():
    client = FakeClient([claimed()])
    runner = FakeRunner()
    loop = NodeAgentExecutorLoop(
        client,
        runner,
        capabilities=["deployment-test"],
        poll_interval=0.5,
    )

    assert loop.run_once() is True

    assert client.start_calls == [("task-1", "assignment-secret")]
    assert runner.calls == ["task-1"]
    status = loop.status()
    assert status.active_tasks == ()
    assert status.completed_tasks == 1
    assert status.last_outcome == "SUCCEEDED"
    assert status.last_error == ""


def test_conversion_capability_dispatches_to_registered_conversion_runner():
    client = FakeClient([claimed(kind="MODEL_CONVERSION")])
    deployment_runner = FakeRunner()
    conversion_runner = FakeRunner()
    loop = NodeAgentExecutorLoop(
        client,
        deployment_runner,
        capabilities=["conversion"],
        runners={"MODEL_CONVERSION": conversion_runner},
    )

    assert loop.enabled is True
    assert loop.effective_capabilities() == ("conversion",)
    assert loop.run_once() is True
    assert client.start_calls == [("task-1", "assignment-secret")]
    assert deployment_runner.calls == []
    assert conversion_runner.calls == ["task-1"]
    assert loop.status().completed_tasks == 1


def test_executor_withdraws_conversion_capability_when_cleanup_is_unsafe():
    client = FakeClient([])
    deployment_runner = FakeRunner()
    conversion_runner = FakeRunner(
        ready=False,
        recovery_error="stale conversion process cleanup could not be verified",
    )
    loop = NodeAgentExecutorLoop(
        client,
        deployment_runner,
        capabilities=["conversion", "deployment-test"],
        runners={"MODEL_CONVERSION": conversion_runner},
    )

    assert loop.capabilities == ("conversion", "deployment-test")
    assert loop.effective_capabilities() == ("deployment-test",)
    assert "conversion process cleanup" in loop.status().last_error


def test_training_capability_dispatches_to_registered_training_runner():
    client = FakeClient([claimed(kind="TRAINING")])
    deployment_runner = FakeRunner()
    training_runner = FakeRunner()
    loop = NodeAgentExecutorLoop(
        client,
        deployment_runner,
        capabilities=["training"],
        runners={"TRAINING": training_runner},
    )

    assert loop.enabled is True
    assert loop.run_once() is True
    assert client.start_calls == [("task-1", "assignment-secret")]
    assert deployment_runner.calls == []
    assert training_runner.calls == ["task-1"]
    assert loop.status().completed_tasks == 1


def test_material_import_capability_dispatches_to_registered_material_runner():
    client = FakeClient([claimed(kind="MATERIAL_IMPORT")])
    deployment_runner = FakeRunner()
    material_runner = FakeRunner()
    loop = NodeAgentExecutorLoop(
        client,
        deployment_runner,
        capabilities=["material-import"],
        runners={"MATERIAL_IMPORT": material_runner},
    )

    assert loop.enabled is True
    assert loop.effective_capabilities() == ("material-import",)
    assert loop.run_once() is True
    assert client.start_calls == [("task-1", "assignment-secret")]
    assert deployment_runner.calls == []
    assert material_runner.calls == ["task-1"]
    assert loop.status().completed_tasks == 1


def test_cleaning_capability_dispatches_material_batch_to_registered_cleaning_runner():
    client = FakeClient([claimed(kind="MATERIAL_BATCH")])
    deployment_runner = FakeRunner()
    cleaning_runner = FakeRunner()
    loop = NodeAgentExecutorLoop(
        client,
        deployment_runner,
        capabilities=["cleaning"],
        runners={"MATERIAL_BATCH": cleaning_runner},
    )

    assert loop.enabled is True
    assert loop.effective_capabilities() == ("cleaning",)
    assert loop.run_once() is True
    assert client.start_calls == [("task-1", "assignment-secret")]
    assert deployment_runner.calls == []
    assert cleaning_runner.calls == ["task-1"]
    assert loop.status().completed_tasks == 1


def test_cleaning_capability_is_withdrawn_when_runtime_dependencies_are_unavailable():
    client = FakeClient([])
    deployment_runner = FakeRunner()
    cleaning_runner = FakeRunner(
        ready=False,
        recovery_error="CLEANING_RUNTIME_UNAVAILABLE: cv2 missing",
    )
    loop = NodeAgentExecutorLoop(
        client,
        deployment_runner,
        capabilities=["cleaning", "deployment-test"],
        runners={"MATERIAL_BATCH": cleaning_runner},
    )

    assert loop.capabilities == ("cleaning", "deployment-test")
    assert loop.effective_capabilities() == ("deployment-test",)
    assert "CLEANING_RUNTIME_UNAVAILABLE" in loop.status().last_error


def test_inconsistent_unsupported_claim_is_not_started_and_waits_for_claim_lease_expiry():
    client = FakeClient([claimed(kind="MODEL_CONVERSION")])
    runner = FakeRunner()
    loop = NodeAgentExecutorLoop(
        client,
        runner,
        capabilities=["deployment-test"],
    )

    assert loop.run_once() is True
    assert client.start_calls == []
    assert runner.calls == []
    assert "UNSUPPORTED_AGENT_TASK_KIND" in loop.last_error()


def test_background_loop_keeps_one_active_task_and_shutdown_fences_runner():
    client = FakeClient([claimed("task-blocking")])
    runner = FakeRunner(block=True)
    loop = NodeAgentExecutorLoop(
        client,
        runner,
        capabilities=["deployment-test"],
        poll_interval=0.5,
    )

    loop.start()
    assert runner.started.wait(timeout=2.0)
    assert loop.active_tasks() == ("task-blocking",)
    # The executor cannot claim another task while the single runner call blocks.
    assert client.claim_calls == 1

    loop.stop(timeout=3.0)

    assert runner.shutdown_requested is True
    assert loop.active_tasks() == ()
    assert "EXECUTION_FENCED" in loop.last_error()


def test_fenced_execution_never_publishes_terminal_status():
    client = FakeClient([claimed("task-fenced")])
    runner = FakeRunner(fenced=True)
    loop = NodeAgentExecutorLoop(
        client,
        runner,
        capabilities=["deployment-test"],
    )

    assert loop.run_once() is True

    assert client.finish_calls == []
    assert "EXECUTION_FENCED" in loop.last_error()


def test_executor_loop_source_has_no_control_plane_database_dependency():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2]
        / "platform_core"
        / "node_agent_executor_loop.py"
    ).read_text(encoding="utf-8")
    assert "sqlite3" not in source
    assert "TaskRepository" not in source
    assert "tasks.sqlite3" not in source
