from platform_core.task_runtime import TaskKind, TaskRecord, TaskRepository, TaskStatus


def test_completed_training_elapsed_time_is_frozen_at_finished_at(tmp_path, monkeypatch):
    import app as app_module

    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    monkeypatch.setattr(app_module, "shared_task_repository", lambda: repository)

    source = {
        "id": "terminal-legacy",
        "status": "done",
        "started_at": "2026-09-14 10:00:00",
        "finished_at": "2026-09-14 10:10:00",
        "epochs": 300,
        "current_epoch": 180,
        "total_epochs": 300,
        "progress_percent": 100,
        "paused_seconds": 0,
    }

    first = app_module.enrich_job_runtime("project-1", dict(source))
    second = app_module.enrich_job_runtime("project-1", dict(source))

    assert first["status"] == "done"
    assert first["elapsed_seconds"] == 600
    assert second["elapsed_seconds"] == 600
    assert first["eta_seconds"] == 0
    assert first["current_epoch"] == 180
    assert first["total_epochs"] == 300


def test_durable_terminal_truth_closes_legacy_running_job(tmp_path, monkeypatch):
    import app as app_module

    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(TaskRecord.new(
        "train-terminal", "project-1", TaskKind.TRAINING, "payload.json", "training:gpu:0",
        priority=1, required_capabilities=("training.ultralytics",),
    ))
    lease = repository.claim_next("a800-worker-01", [TaskKind.TRAINING], {"training.ultralytics"})
    assert lease is not None
    repository.heartbeat(
        "train-terminal", lease.lease_token, progress=95, stage="training", current_item="Epoch 180/300"
    )
    terminal = repository.finish(
        "train-terminal", lease.lease_token, TaskStatus.SUCCEEDED, result_ref="result.json"
    )
    monkeypatch.setattr(app_module, "shared_task_repository", lambda: repository)

    job = app_module.enrich_job_runtime("project-1", {
        "id": "train-terminal",
        "status": "running",
        "started_at": terminal.created_at,
        "epochs": 300,
        "current_epoch": 180,
        "total_epochs": 300,
        "progress_percent": 95,
    })

    assert job["status"] == "done"
    assert job["task_status"] == "SUCCEEDED"
    assert job["progress_percent"] == 100
    assert job["finished_at"] == terminal.finished_at
    assert job["current_epoch"] == 180
    assert job["total_epochs"] == 300
    assert job["eta_seconds"] == 0

def test_success_aliases_are_terminal_and_attempt_version_archive(tmp_path, monkeypatch):
    import app as app_module

    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    monkeypatch.setattr(app_module, "shared_task_repository", lambda: repository)
    archived = []

    def fake_archive(project_id, job):
        archived.append((project_id, dict(job)))
        return {"id": "version-one"}

    monkeypatch.setattr(app_module, "_v48_archive_training_version", fake_archive)

    for status in ("done", "finished", "completed", "succeeded", "success"):
        job = app_module.enrich_job_runtime("project-1", {
            "id": f"terminal-{status}",
            "status": status,
            "asset_algorithm_id": "algorithm-one",
            "started_at": "2026-09-14 10:00:00",
            "finished_at": "2026-09-14 10:10:00",
            "epochs": 30,
            "current_epoch": 18,
            "total_epochs": 30,
            "progress_percent": 60,
        })
        assert job["status_text"] == "已完成"
        assert job["progress_percent"] == 100
        assert job["elapsed_seconds"] == 600
        assert job["eta_seconds"] == 0

    assert [row[1]["status"] for row in archived] == [
        "done", "finished", "completed", "succeeded", "success",
    ]


def test_cancel_aliases_freeze_elapsed_without_fabricating_success_progress(tmp_path, monkeypatch):
    import app as app_module

    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    monkeypatch.setattr(app_module, "shared_task_repository", lambda: repository)

    for status in ("cancelled", "canceled"):
        job = app_module.enrich_job_runtime("project-1", {
            "id": f"terminal-{status}",
            "status": status,
            "started_at": "2026-09-14 10:00:00",
            "finished_at": "2026-09-14 10:10:00",
            "epochs": 30,
            "current_epoch": 18,
            "total_epochs": 30,
            "progress_percent": 60,
        })
        assert job["status_text"] == "已取消"
        assert job["progress_percent"] == 60
        assert job["elapsed_seconds"] == 600
        assert job["eta_seconds"] == 0


def test_training_success_rate_uses_all_ended_jobs_without_calling_cancellations_failures():
    import app as app_module

    stats = app_module._training_success_rate_stats([
        {"status": "done"},
        {"status": "success"},
        {"status": "failed"},
        {"status": "stopped"},
        {"status": "cancelled"},
        {"status": "canceled"},
        {"status": "running"},
    ])

    assert stats == {
        "success_count": 2,
        "failure_count": 1,
        "ended_count": 6,
        "success_rate": 33.3,
    }
    assert app_module._training_success_rate_stats([{"status": "queued"}])["success_rate"] is None


def test_version_archive_accepts_success_alias_source_contract():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "app.py").read_text(encoding="utf-8")
    start = source.index("def _v48_archive_training_version")
    end = source.index("\n\n", source.index("successful_statuses =", start))
    block = source[start:end]

    assert '"SUCCEEDED"' in block
    assert '"SUCCESS"' in block

