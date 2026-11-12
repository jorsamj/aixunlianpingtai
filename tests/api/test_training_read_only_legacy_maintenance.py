"""Old training queues must not depend on an operator opening a GET page."""
import json

import app as api
from filelock import FileLock
from platform_core.task_runtime import TaskKind, TaskRecord, TaskRepository
from platform_core.training_history_projection import TrainingHistoryProjection


def _legacy_fixture(tmp_path, monkeypatch):
    project = tmp_path / "projects" / "legacy"
    job_file = project / "jobs" / "old-queued" / "job.json"
    job_file.parent.mkdir(parents=True)
    job = {
        "id": "old-queued", "status": "queued", "queue_priority": 100,
        "asset_algorithm_name": "历史算法", "resource_key": "local:default",
        "created_at": "2026-10-01T00:00:00+00:00",
    }
    job_file.write_text(json.dumps(job), encoding="utf-8")
    repository = TaskRepository(tmp_path / "runtime" / "tasks.sqlite3")
    monkeypatch.setattr(api, "get_project", lambda _project_id: {"id": "legacy"})
    monkeypatch.setattr(api, "project_dir", lambda _project_id: project)
    monkeypatch.setattr(api, "list_projects", lambda: [{"id": "legacy"}])
    monkeypatch.setattr(api, "shared_task_repository", lambda: repository)
    monkeypatch.setattr(api, "_TRAINING_HISTORY_PROJECTION", TrainingHistoryProjection())
    monkeypatch.setattr(api, "_TRAINING_JOB_PROJECTIONS", {})
    return job_file


def test_training_get_and_bootstrap_projection_do_not_start_or_rewrite_legacy_jobs(tmp_path, monkeypatch):
    job_file = _legacy_fixture(tmp_path, monkeypatch)
    initial = job_file.read_bytes()
    launches = []
    monkeypatch.setattr(api, "_v48_launch_saved_job", lambda *_args: launches.append(True))
    assert api.list_jobs("legacy")[0]["status"] == "queued"
    assert api._v53_live_jobs("legacy")[0]["status"] == "queued"
    assert job_file.read_bytes() == initial
    assert not (job_file.parent.parent / "index.json").exists()
    assert launches == []


def test_legacy_maintenance_dispatches_once_without_get_and_retains_failure_evidence(tmp_path, monkeypatch):
    job_file = _legacy_fixture(tmp_path, monkeypatch)
    attempted = []

    def fail_launch(_project_id, job):
        attempted.append(job["id"])
        raise RuntimeError("历史模型文件不可用")

    monkeypatch.setattr(api, "_v48_launch_saved_job", fail_launch)
    assert api._v48_legacy_maintenance_tick() is True
    assert attempted == ["old-queued"]
    persisted = json.loads(job_file.read_text(encoding="utf-8"))
    assert persisted["never_started"] is True
    assert persisted["status"] == "failed"
    assert "历史模型文件不可用" in persisted["message"]
    assert api.list_jobs("legacy")[0]["status"] == "failed"
    assert attempted == ["old-queued"]
    assert api._v48_legacy_maintenance_tick() is False


def test_legacy_read_only_projection_never_archives_a_completed_job(tmp_path, monkeypatch):
    job_file = _legacy_fixture(tmp_path, monkeypatch)
    job = json.loads(job_file.read_text(encoding="utf-8"))
    job.update(status="done", artifact_verified=True, asset_algorithm_id="old-algorithm")
    job_file.write_text(json.dumps(job), encoding="utf-8")
    archives = []
    monkeypatch.setattr(api, "_v48_archive_training_version", lambda *_args: archives.append(True))
    assert api.list_jobs("legacy")[0]["status"] == "done"
    assert archives == []
    assert api.sync_jobs_index("legacy")[0]["status"] == "done"
    assert archives == [True]


def test_legacy_queue_can_resume_after_busy_resource_without_any_get(tmp_path, monkeypatch):
    queued_file = _legacy_fixture(tmp_path, monkeypatch)
    running_file = queued_file.parent.parent / "old-running" / "job.json"
    running_file.parent.mkdir()
    running_file.write_text(json.dumps({"id": "old-running", "status": "running",
                                        "asset_algorithm_name": "历史算法", "resource_key": "local:default"}),
                            encoding="utf-8")
    launched = []

    def launch(_project_id, job):
        launched.append(job["id"])
        api.write_json(queued_file, {**job, "status": "running", "pid": 0})

    monkeypatch.setattr(api, "_v48_launch_saved_job", launch)
    assert api._v48_legacy_maintenance_tick() is True
    assert launched == []
    api.write_json(running_file, {"id": "old-running", "status": "done", "artifact_verified": False})
    assert api._v48_legacy_maintenance_tick() is True
    assert launched == ["old-queued"]
    assert api.list_jobs("legacy")[0]["status"] in {"running", "done"}
    assert launched == ["old-queued"]


def test_legacy_dispatch_obeys_existing_cross_process_file_fence(tmp_path, monkeypatch):
    job_file = _legacy_fixture(tmp_path, monkeypatch)
    launched = []
    monkeypatch.setattr(api, "_v48_launch_saved_job", lambda *_args: launched.append(True))
    lock_file = job_file.parent.parent / ".legacy-dispatch.lock"
    with FileLock(str(lock_file), timeout=0):
        assert api._v48_dispatch_training_queues("legacy") is None
    assert launched == []
    assert api._v48_dispatch_training_queues("legacy") is None
    assert launched == [True]


def test_durable_task_with_historical_job_shadow_cannot_be_dispatched(tmp_path, monkeypatch):
    _legacy_fixture(tmp_path, monkeypatch)
    repository = api.shared_task_repository()
    repository.create(TaskRecord.new("old-queued", "legacy", TaskKind.TRAINING, "payload.json", "cpu"))
    launched = []
    monkeypatch.setattr(api, "_v48_launch_saved_job", lambda *_args: launched.append(True))
    assert api._v48_legacy_maintenance_tick() is False
    assert launched == []
    assert api.list_jobs("legacy")[0]["id"] == "old-queued"


def test_bootstrap_hot_refresh_reuses_one_history_context(tmp_path, monkeypatch):
    _legacy_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(api, "algorithm_store_revision", lambda _path: 0)
    called = []
    original = api._training_history_context

    def history(project_id):
        called.append(project_id)
        return original(project_id)

    monkeypatch.setattr(api, "_training_history_context", history)
    payload = api._v53_snapshot_with_live_jobs({"algorithm_revision": 0, "algorithms": []}, "legacy")
    assert payload["jobs"][0]["id"] == "old-queued"
    assert called == ["legacy"]
