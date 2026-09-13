import sys
import time

import psutil

import app as platform_app
from platform_core.task_runtime import ProcessController, TaskKind, TaskRecord, TaskStatus
from platform_core.task_runtime.process_control import launch_process


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_unified_cancel_terminates_exact_bound_process_even_when_paused(client, seeded_project, tmp_path):
    project_id, _image = seeded_project
    repository = platform_app.shared_task_repository()
    task_id = "cancel-paused-process"
    repository.create(
        TaskRecord.new(
            task_id=task_id,
            project_id=project_id,
            kind=TaskKind.TRAINING,
            payload_ref="request.json",
            resource_key="training:local:test",
            priority=10,
        )
    )
    lease = repository.claim_next("cancel-test-worker", [TaskKind.TRAINING], set())
    assert lease is not None and lease.task.task_id == task_id

    handle = launch_process(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=tmp_path,
    )
    controller = ProcessController()
    try:
        repository.bind_process(task_id, lease.lease_token, handle.identity)
        controller.suspend_tree(handle.identity)
        assert psutil.Process(handle.identity.pid).status() == psutil.STATUS_STOPPED
        repository.set_stage(task_id, "paused")

        response = client.post(f"/api/v62/projects/{project_id}/tasks/{task_id}/cancel")
        response.raise_for_status()
        body = response.json()
        assert body["status"] == TaskStatus.CANCEL_REQUESTED.value
        assert body["phase"] == "cancelling"

        assert _wait_until(lambda: not psutil.pid_exists(handle.identity.pid)), (
            "unified cancel recorded durable intent but left the exact bound process alive"
        )
        durable = repository.get(task_id)
        assert durable is not None
        assert durable.status is TaskStatus.CANCEL_REQUESTED
    finally:
        try:
            controller.terminate_tree(handle.identity, timeout=1.0)
        except (ProcessLookupError, PermissionError):
            pass
