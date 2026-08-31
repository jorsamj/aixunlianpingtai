import json
import subprocess
import sys
import time
import uuid

import psutil

from platform_core.task_runtime import ProcessController, TaskKind, TaskRecord, TaskStatus, launch_process


def test_durable_training_pause_resume_and_stop_use_verified_process_identity(client, seeded_project):
    import app as app_module

    project_id, _ = seeded_project
    task_id = f"control-{uuid.uuid4().hex[:8]}"
    artifacts = app_module.shared_task_artifacts()
    repository = app_module.shared_task_repository()
    artifacts.atomic_write_json(task_id, "payload.json", {"framework": "ultralytics"})
    repository.create(
        TaskRecord.new(
            task_id,
            project_id,
            TaskKind.TRAINING,
            "payload.json",
            f"training:control:{task_id}",
            required_capabilities=("training.ultralytics",),
        )
    )
    lease = repository.claim_next(
        "control-test", {TaskKind.TRAINING}, {"training.ultralytics"}, lease_seconds=60
    )
    assert lease is not None
    launched = launch_process(
        [sys.executable, "-c", "import time\nwhile True: time.sleep(0.1)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    repository.bind_process(task_id, lease.lease_token, launched.identity)
    job_dir = app_module.project_dir(project_id) / "jobs" / task_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "job.json").write_text(
        json.dumps({"id": task_id, "task_id": task_id, "status": "running", "target": "local"}),
        encoding="utf-8",
    )
    controller = ProcessController()
    try:
        paused = client.post(f"/api/v48/projects/{project_id}/jobs/{task_id}/pause")
        assert paused.status_code == 200, paused.text
        assert repository.get(task_id).stage == "paused"
        assert controller.inspect(launched.identity).status() == psutil.STATUS_STOPPED

        resumed = client.post(f"/api/v48/projects/{project_id}/jobs/{task_id}/resume")
        assert resumed.status_code == 200, resumed.text
        assert repository.get(task_id).stage == "training"
        assert controller.inspect(launched.identity).status() != psutil.STATUS_STOPPED

        stopped = client.post(f"/api/v48/projects/{project_id}/jobs/{task_id}/stop")
        assert stopped.status_code == 200, stopped.text
        assert repository.get(task_id).status is TaskStatus.CANCEL_REQUESTED
        for _ in range(30):
            if not psutil.pid_exists(launched.identity.pid):
                break
            time.sleep(0.05)
        assert not psutil.pid_exists(launched.identity.pid)
    finally:
        try:
            controller.terminate_tree(launched.identity)
        except Exception:
            pass
