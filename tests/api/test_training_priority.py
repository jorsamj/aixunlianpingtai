import pytest
from fastapi import HTTPException
from pydantic import ValidationError


@pytest.mark.parametrize("value", [1, 50, 999])
def test_training_priority_accepts_integer_range(value):
    import app as app_module

    payload = app_module.TrainReq(queue_priority=value)
    app_module.validate_train_request(payload)

    assert payload.queue_priority == value


@pytest.mark.parametrize("value", [0, -1, 1000])
def test_training_priority_rejects_out_of_range_integer(value):
    import app as app_module

    payload = app_module.TrainReq(queue_priority=value)
    with pytest.raises(HTTPException, match="1~999"):
        app_module.validate_train_request(payload)


@pytest.mark.parametrize("value", [True, 1.5, "1", ""])
def test_training_priority_rejects_non_integer_input(value):
    import app as app_module

    with pytest.raises(ValidationError):
        app_module.TrainReq(queue_priority=value)


def test_new_priority_sort_key_uses_lower_number_then_fifo():
    import app as app_module

    jobs = [
        {"id": "late-high", "queue_priority": 1, "priority_scheme": "lower_number_first", "queued_at": "2026-08-30T10:01:00"},
        {"id": "normal", "queue_priority": 50, "priority_scheme": "lower_number_first", "queued_at": "2026-08-30T09:00:00"},
        {"id": "early-high", "queue_priority": 1, "priority_scheme": "lower_number_first", "queued_at": "2026-08-30T10:00:00"},
        {"id": "medium", "queue_priority": 2, "priority_scheme": "lower_number_first", "queued_at": "2026-08-30T08:00:00"},
    ]

    ordered = sorted(jobs, key=app_module._v56_training_queue_sort_key)

    assert [job["id"] for job in ordered] == ["early-high", "late-high", "medium", "normal"]


@pytest.mark.parametrize(("legacy", "normalized"), [(100, 1), (80, 20), (50, 50)])
def test_legacy_active_priority_mapping_preserves_old_levels(legacy, normalized):
    import app as app_module

    assert app_module._v56_normalize_priority({"status": "queued", "queue_priority": legacy}) == normalized


def test_legacy_priority_migration_only_rewrites_queued_job(tmp_path):
    import app as app_module

    queued_file = tmp_path / "queued.json"
    completed_file = tmp_path / "completed.json"
    queued = {"id": "queued", "status": "queued", "queue_priority": 100}
    completed = {"id": "completed", "status": "done", "queue_priority": 100}
    app_module.write_json(queued_file, queued)
    app_module.write_json(completed_file, completed)

    migrated = app_module._v56_migrate_queued_priority(queued_file, queued)
    unchanged = app_module._v56_migrate_queued_priority(completed_file, completed)

    assert migrated["queue_priority"] == 1
    assert migrated["priority_scheme"] == "lower_number_first"
    assert migrated["legacy_queue_priority"] == 100
    assert app_module.read_json(queued_file, {})["priority_scheme"] == "lower_number_first"
    assert unchanged == completed
    assert app_module.read_json(completed_file, {}) == completed


def test_dispatch_selects_highest_priority_per_resource(tmp_path, monkeypatch):
    import app as app_module

    job_files = []
    for job in [
        {"id": "local-low", "status": "queued", "resource_key": "local:default", "queue_priority": 50, "priority_scheme": "lower_number_first", "queued_at": "2026-08-30T09:00:00"},
        {"id": "local-high", "status": "queued", "resource_key": "local:default", "queue_priority": 1, "priority_scheme": "lower_number_first", "queued_at": "2026-08-30T10:00:00"},
        {"id": "remote", "status": "queued", "resource_key": "remote:a", "queue_priority": 20, "priority_scheme": "lower_number_first", "queued_at": "2026-08-30T08:00:00"},
    ]:
        job_dir = tmp_path / job["id"]
        job_dir.mkdir()
        job_file = job_dir / "job.json"
        app_module.write_json(job_file, job)
        job_files.append(job_file)
    launched = []
    monkeypatch.setattr(app_module, "_v48_all_job_files", lambda _project_id: job_files)
    monkeypatch.setattr(app_module, "_v48_launch_saved_job", lambda _project_id, job: launched.append(job["id"]))

    app_module._v48_dispatch_training_queues("project")

    assert launched == ["local-high", "remote"]
