import uuid

import app as platform_app
from platform_core.task_runtime import TaskKind, TaskRecord


def test_unified_task_api_exposes_paused_as_effective_status(client, seeded_project):
    project_id, _image = seeded_project
    task_id = f"paused-{uuid.uuid4().hex[:10]}"
    repository = platform_app.shared_task_repository()
    repository.create(
        TaskRecord.new(
            task_id,
            project_id,
            TaskKind.TRAINING,
            "request.json",
            f"training:pause:{task_id}",
            priority=1,
            required_capabilities=("cuda",),
        )
    )
    lease = repository.claim_next("worker-pause-truth", [TaskKind.TRAINING], {"cuda"})
    assert lease is not None and lease.task.task_id == task_id
    repository.heartbeat(task_id, lease.lease_token, progress=47, stage="training", current_item="epoch 5/10")
    repository.set_stage(task_id, "paused")

    response = client.get(f"/api/v62/projects/{project_id}/tasks/{task_id}")
    response.raise_for_status()
    body = response.json()

    assert body["status"] == "PAUSED"
    assert body["persisted_status"] == "RUNNING"
    assert body["phase"] == "paused"
    assert body["progress_percent"] == 47
    assert body["current_item"] == "epoch 5/10"
    assert body["worker_id"] == "worker-pause-truth"
    assert body["lease_expires_at"]
