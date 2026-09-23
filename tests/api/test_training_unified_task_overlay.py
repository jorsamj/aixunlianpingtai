import os
import uuid

from platform_core.task_runtime import (
    ArtifactStore,
    TaskKind,
    TaskRecord,
    TaskRepository,
    WorkerInstanceService,
)


def test_training_batch_delete_purges_terminal_truth_and_skips_active(client, seeded_project):
    import app as app_module

    project_id, _image = seeded_project
    repository = app_module.shared_task_repository()
    artifacts = app_module.shared_task_artifacts()
    terminal_id = f"train-delete-terminal-{uuid.uuid4().hex[:10]}"
    active_id = f"train-delete-active-{uuid.uuid4().hex[:10]}"

    for task_id in (terminal_id, active_id):
        repository.create(TaskRecord.new(
            task_id,
            project_id,
            TaskKind.TRAINING,
            "payload.json",
            "training:cpu",
            priority=50,
            required_capabilities=("training.ultralytics",),
        ))
        artifacts.atomic_write_json(task_id, "payload.json", {"task_id": task_id})
        job_dir = app_module.project_dir(project_id) / "jobs" / task_id
        job_dir.mkdir(parents=True, exist_ok=True)
        app_module.write_json(job_dir / "job.json", {
            "id": task_id,
            "task_id": task_id,
            "status": "queued",
            "asset_algorithm_name": "批量删除验收",
        })

    repository.request_cancel(terminal_id)
    terminal_job = app_module.project_dir(project_id) / "jobs" / terminal_id / "job.json"
    app_module.write_json(terminal_job, {
        "id": terminal_id,
        "task_id": terminal_id,
        "status": "stopped",
        "asset_algorithm_name": "批量删除验收",
    })
    app_module.sync_jobs_index(project_id)

    response = client.post(
        f"/api/v48/projects/{project_id}/jobs/batch-delete",
        json={"job_ids": [terminal_id, active_id]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["deleted"] == 1
    assert body["deleted_ids"] == [terminal_id]
    assert body["skipped_active"] == 1
    assert body["skipped_active_ids"] == [active_id]
    assert repository.get(terminal_id) is None
    assert repository.get(active_id) is not None
    assert not (app_module.project_dir(project_id) / "jobs" / terminal_id).exists()
    assert (app_module.project_dir(project_id) / "jobs" / active_id).exists()
    assert not (artifacts.root / terminal_id).exists()
    assert (artifacts.root / active_id).exists()


def test_training_job_overlay_uses_unified_resource_waiting_truth(tmp_path, monkeypatch):
    import app as app_module

    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(TaskRecord.new(
        "train-wait", "project-1", TaskKind.TRAINING, "payload.json", "training:gpu:0",
        priority=7, required_capabilities=("training.ultralytics",),
    ))
    WorkerInstanceService(repository).acquire(
        tmp_path,
        {"training"},
        "default",
        "a800-worker",
        pid=os.getpid(),
        hostname="a800-worker.example",
        build_id="build-current",
        task_kinds={TaskKind.TRAINING.value},
        capabilities={"training.ultralytics"},
    )

    def deny(database, candidate, worker_id, token, expires_at, now):
        return False, "GPU_MEMORY_BUSY"

    assert repository.claim_next(
        "a800-worker", [TaskKind.TRAINING], {"training.ultralytics"}, admission=deny,
    ) is None
    monkeypatch.setattr(app_module, "shared_task_repository", lambda: repository)

    job = app_module.enrich_job_runtime("project-1", {
        "id": "train-wait", "status": "queued", "queue_priority": 50,
        "framework": "ultralytics",
    })

    assert job["status"] == "waiting"
    assert job["task_status"] == "WAITING_RESOURCE"
    assert job["queue_priority"] == 7
    assert job["queue_rank"] == 0
    assert job["priority_scheme"] == "lower_number_first"
    assert job["resource_queue_position"] == 1
    assert job["resource_wait_reason"] == "GPU_MEMORY_BUSY"
    assert job["task_worker_id"] is None


def test_training_job_overlay_derives_worker_waiting_and_pool_metadata(tmp_path, monkeypatch):
    import app as app_module

    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    task = repository.create(TaskRecord.new(
        "train-worker-wait", "project-1", TaskKind.TRAINING, "payload.json", "training:auto",
        priority=7, required_capabilities=("training.ultralytics",),
    ))
    monkeypatch.setattr(app_module, "shared_task_repository", lambda: repository)

    waiting = app_module.enrich_job_runtime("project-1", {"id": task.task_id, "status": "queued"})

    assert waiting["status"] == "waiting"
    assert waiting["task_status"] == "WAITING_RESOURCE"
    assert waiting["resource_wait_reason"] == "当前没有在线 Worker"
    assert waiting["resource_pool_key"] == "training:auto"
    assert waiting["resource_pool_label"] == "GPU 自动"
    assert waiting["resource_queue_position_exact"] is False

    WorkerInstanceService(repository).acquire(
        tmp_path,
        {"training"},
        "default",
        "training-worker",
        pid=os.getpid(),
        hostname="training-worker.example",
        build_id="build-current",
        task_kinds={TaskKind.TRAINING.value},
        capabilities={"training.ultralytics"},
    )
    queued = app_module.enrich_job_runtime("project-1", waiting)

    assert queued["status"] == "queued"
    assert queued["task_status"] == "QUEUED"
    assert queued["resource_wait_reason"] is None


def test_training_job_overlay_exposes_worker_and_lease_for_running_task(tmp_path, monkeypatch):
    import app as app_module

    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(TaskRecord.new(
        "train-run", "project-1", TaskKind.TRAINING, "payload.json", "training:gpu:0",
        priority=1, required_capabilities=("training.ultralytics",),
    ))
    lease = repository.claim_next("a800-worker-01", [TaskKind.TRAINING], {"training.ultralytics"})
    assert lease is not None
    repository.heartbeat("train-run", lease.lease_token, progress=18, stage="training", current_item="epoch 2/10")
    monkeypatch.setattr(app_module, "shared_task_repository", lambda: repository)

    job = app_module.enrich_job_runtime("project-1", {"id": "train-run", "status": "queued"})
    assert job["status"] == "running"
    assert job["progress_percent"] == 18
    assert job["current_item"] == "epoch 2/10"
    assert job["task_worker_id"] == "a800-worker-01"
    assert job["task_lease_expires_at"]


def test_training_job_overlay_exposes_durable_dataset_revision_and_snapshot(tmp_path, monkeypatch):
    import app as app_module

    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    task = repository.create(TaskRecord.new(
        "train-revision", "project-1", TaskKind.TRAINING, "payload.json",
        "training:cpu", priority=5, required_capabilities=("training.ultralytics",),
    ))
    artifacts.atomic_write_json(task.task_id, "snapshot.json", {
        "schema_version": 3,
        "snapshot_id": "a" * 64,
        "dataset_revision_id": "b" * 64,
    })
    monkeypatch.setattr(app_module, "shared_task_repository", lambda: repository)
    monkeypatch.setattr(app_module, "shared_task_artifacts", lambda: artifacts)

    job = app_module.enrich_job_runtime("project-1", {
        "id": task.task_id,
        "status": "queued",
        "framework": "ultralytics",
    })

    assert job["snapshot_id"] == "a" * 64
    assert job["dataset_revision_id"] == "b" * 64


def test_training_job_overlay_exposes_durable_dataset_manifest_reference(tmp_path, monkeypatch):
    import app as app_module

    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    task = repository.create(TaskRecord.new(
        "train-manifest", "project-1", TaskKind.TRAINING, "payload.json",
        "training:cpu", priority=5, required_capabilities=("training.ultralytics",),
    ))
    lease = repository.claim_next(
        "training-worker",
        [TaskKind.TRAINING],
        {"training.ultralytics"},
    )
    assert lease is not None
    artifacts.atomic_write_json(task.task_id, "result.json", {
        "dataset_manifest_ref": "work/bundle/manifest.json",
        "internal_secret": "must-not-project",
    })
    repository.finish(
        task.task_id,
        lease.lease_token,
        app_module.TaskStatus.SUCCEEDED,
        "result.json",
    )
    monkeypatch.setattr(app_module, "shared_task_repository", lambda: repository)
    monkeypatch.setattr(app_module, "shared_task_artifacts", lambda: artifacts)

    job = app_module.enrich_job_runtime("project-1", {
        "id": task.task_id,
        "status": "running",
        "framework": "ultralytics",
    })

    assert job["dataset_manifest_ref"] == "work/bundle/manifest.json"
    assert "internal_secret" not in job
