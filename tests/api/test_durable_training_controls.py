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
        cancelling = repository.get(task_id)
        assert cancelling is not None
        assert cancelling.status is TaskStatus.CANCEL_REQUESTED
        assert cancelling.stage == "cancelling"

        # A late/stale resume request must never revive a task once cancellation
        # has become durable truth. The API guard covers ordinary requests while
        # the repository set_stage guard closes the stop/resume race window.
        resume_after_stop = client.post(f"/api/v48/projects/{project_id}/jobs/{task_id}/resume")
        assert resume_after_stop.status_code == 400, resume_after_stop.text
        still_cancelling = repository.get(task_id)
        assert still_cancelling is not None
        assert still_cancelling.status is TaskStatus.CANCEL_REQUESTED
        assert still_cancelling.stage == "cancelling"

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



def test_direct_delete_cancels_durable_training_before_hiding_job(client, seeded_project):
    import app as app_module

    project_id, _ = seeded_project
    task_id = f"delete-{uuid.uuid4().hex[:8]}"
    artifacts = app_module.shared_task_artifacts()
    repository = app_module.shared_task_repository()
    artifacts.atomic_write_json(task_id, "payload.json", {"framework": "ultralytics"})
    repository.create(
        TaskRecord.new(
            task_id,
            project_id,
            TaskKind.TRAINING,
            "payload.json",
            f"training:delete:{task_id}",
            required_capabilities=("training.ultralytics",),
        )
    )
    lease = repository.claim_next(
        "delete-control-test", {TaskKind.TRAINING}, {"training.ultralytics"}, lease_seconds=60
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
        deleted = client.delete(f"/api/v12/projects/{project_id}/jobs/{task_id}")
        assert deleted.status_code == 200, deleted.text
        durable = repository.get(task_id)
        assert durable is not None
        assert durable.status is TaskStatus.CANCEL_REQUESTED
        assert durable.stage == "cancelling"
        assert not job_dir.exists()

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

def test_legacy_remote_training_stop_fails_closed_when_remote_rejects(client, seeded_project, monkeypatch):
    import app as app_module

    project_id, _ = seeded_project
    job_id = f"legacy-remote-stop-{uuid.uuid4().hex[:8]}"
    job_dir = app_module.project_dir(project_id) / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    job_file = job_dir / "job.json"
    job_file.write_text(
        json.dumps({
            "id": job_id,
            "status": "running",
            "target": "remote",
            "remote": {
                "base_url": "http://remote-agent.invalid:9000",
                "job_id": "remote-job-1",
                "api_key": "test-key",
            },
        }),
        encoding="utf-8",
    )

    class FailedResponse:
        ok = False
        status_code = 409
        text = "remote process still running"

    calls = []
    monkeypatch.setattr(
        app_module.requests,
        "post",
        lambda url, **kwargs: calls.append((url, kwargs)) or FailedResponse(),
    )

    stopped = client.post(f"/api/v48/projects/{project_id}/jobs/{job_id}/stop")
    assert stopped.status_code == 502, stopped.text
    assert "本地状态保持不变" in stopped.text
    persisted = json.loads(job_file.read_text(encoding="utf-8"))
    assert persisted["status"] == "running"
    assert len(calls) == 1
    assert calls[0][0].endswith("/api/remote/jobs/remote-job-1/stop")


def test_legacy_remote_training_stop_commits_local_state_only_after_remote_ack(client, seeded_project, monkeypatch):
    import app as app_module

    project_id, _ = seeded_project
    job_id = f"legacy-remote-stop-ok-{uuid.uuid4().hex[:8]}"
    job_dir = app_module.project_dir(project_id) / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    job_file = job_dir / "job.json"
    job_file.write_text(
        json.dumps({
            "id": job_id,
            "status": "running",
            "target": "remote",
            "remote": {
                "base_url": "http://remote-agent.invalid:9000",
                "job_id": "remote-job-2",
                "api_key": "test-key",
            },
        }),
        encoding="utf-8",
    )

    class OkResponse:
        ok = True
        status_code = 200
        text = ""

    monkeypatch.setattr(app_module.requests, "post", lambda *args, **kwargs: OkResponse())

    stopped = client.post(f"/api/v48/projects/{project_id}/jobs/{job_id}/stop")
    assert stopped.status_code == 200, stopped.text
    persisted = json.loads(job_file.read_text(encoding="utf-8"))
    assert persisted["status"] == "stopped"
    assert persisted["message"] == "用户手动停止"

