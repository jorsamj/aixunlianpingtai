from __future__ import annotations

import json

from platform_core.task_runtime import TaskRepository


def _empty_task_repository(tmp_path):
    return TaskRepository(tmp_path / "tasks.sqlite3")


def test_training_job_frozen_algorithm_name_never_reads_repository(tmp_path, monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "shared_task_repository", lambda: _empty_task_repository(tmp_path))
    monkeypatch.setattr(
        app_module,
        "list_algorithms_internal",
        lambda _project_id: (_ for _ in ()).throw(AssertionError("frozen name must win")),
    )

    job = app_module.enrich_job_runtime("project-1", {
        "id": "training-frozen-name",
        "status": "queued",
        "asset_algorithm_id": "algorithm-1",
        "asset_algorithm_name": "已冻结算法名称",
    })

    assert job["asset_algorithm_name"] == "已冻结算法名称"


def test_training_job_historical_algorithm_id_resolves_current_name(tmp_path, monkeypatch):
    import app as app_module

    repository = _empty_task_repository(tmp_path)
    monkeypatch.setattr(app_module, "shared_task_repository", lambda: repository)
    monkeypatch.setattr(
        app_module,
        "list_algorithms_internal",
        lambda _project_id: [{"id": "algorithm-1", "name": "当前算法名称"}],
    )

    job = app_module.enrich_job_runtime("project-1", {
        "id": "training-historical-id",
        "status": "queued",
        "asset_algorithm_id": "algorithm-1",
    })

    assert job["asset_algorithm_name"] == "当前算法名称"


def test_training_job_deleted_algorithm_uses_safe_display_name(tmp_path, monkeypatch):
    import app as app_module

    repository = _empty_task_repository(tmp_path)
    monkeypatch.setattr(app_module, "shared_task_repository", lambda: repository)
    monkeypatch.setattr(app_module, "list_algorithms_internal", lambda _project_id: [])

    job = app_module.enrich_job_runtime("project-1", {
        "id": "training-deleted-algorithm",
        "status": "queued",
        "asset_algorithm_id": "algorithm-deleted",
    })

    assert job["asset_algorithm_name"] == "已删除算法"


def test_training_job_missing_historical_project_does_not_break_projection(tmp_path, monkeypatch):
    import app as app_module

    repository = _empty_task_repository(tmp_path)
    monkeypatch.setattr(app_module, "shared_task_repository", lambda: repository)
    monkeypatch.setattr(
        app_module,
        "list_algorithms_internal",
        lambda _project_id: (_ for _ in ()).throw(
            app_module.HTTPException(status_code=404, detail="项目不存在")
        ),
    )

    job = app_module.enrich_job_runtime("missing-project", {
        "id": "training-missing-project",
        "status": "queued",
        "asset_algorithm_id": "algorithm-historical",
    })

    assert job["asset_algorithm_name"] == "已删除算法"


def test_training_job_index_keeps_all_active_tasks_beyond_history_limit():
    import app as app_module

    jobs = [
        {
            "id": f"done-{index:02d}",
            "status": "done",
            "created_at": f"2026-09-21T12:{59 - index:02d}:00Z",
        }
        for index in range(55)
    ]
    jobs.append({
        "id": "old-running",
        "status": "running",
        "task_status": "RUNNING",
        "created_at": "2026-09-20T00:00:00Z",
    })

    rows = app_module._training_job_index_rows(jobs, history_limit=50)

    assert any(row["id"] == "old-running" for row in rows)
    assert len([row for row in rows if row["status"] == "done"]) == 50
    assert len(rows) == 51


def test_training_job_index_treats_paused_and_cancel_requested_as_active():
    import app as app_module

    rows = app_module._training_job_index_rows([
        {"id": "paused", "status": "paused", "created_at": "2026-09-20T00:00:00Z"},
        {
            "id": "cancel-requested",
            "status": "done",
            "task_status": "CANCEL_REQUESTED",
            "created_at": "2026-09-19T00:00:00Z",
        },
    ], history_limit=0)

    assert [row["id"] for row in rows] == ["paused", "cancel-requested"]


def test_training_job_index_emits_one_row_per_canonical_training_task():
    import app as app_module

    rows = app_module._training_job_index_rows([
        {
            "id": "legacy-shadow",
            "task_id": "train_0123456789abcdef",
            "status": "queued",
            "asset_algorithm_name": "旧投影",
            "created_at": "2026-09-20T00:00:00Z",
        },
        {
            "id": "train_0123456789abcdef",
            "task_id": "train_0123456789abcdef",
            "status": "running",
            "task_status": "RUNNING",
            "asset_algorithm_name": "正式算法",
            "created_at": "2026-09-20T00:00:01Z",
        },
    ])

    assert len(rows) == 1
    assert rows[0]["id"] == "train_0123456789abcdef"
    assert rows[0]["asset_algorithm_name"] == "正式算法"


def test_cached_bootstrap_snapshot_overlays_live_jobs_without_mutating_core_cache(tmp_path, monkeypatch):
    import app as app_module

    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    live_jobs = [{
        "id": "live-running",
        "status": "running",
        "task_status": "RUNNING",
        "progress_percent": 37,
    }]
    (jobs_dir / "index.json").write_text(json.dumps(live_jobs), encoding="utf-8")

    monkeypatch.setattr(app_module, "project_dir", lambda _project_id: tmp_path)
    monkeypatch.setattr(app_module, "sync_jobs_index", lambda _project_id: None)

    cached = {
        "project": {"id": "project-1"},
        "jobs": [{"id": "stale-done", "status": "done"}],
        "generated_at": "2026-09-21T10:00:00Z",
    }
    payload = app_module._v53_snapshot_with_live_jobs(cached, "project-1")

    assert payload["jobs"] == live_jobs
    assert cached["jobs"] == [{"id": "stale-done", "status": "done"}]
    assert payload["generated_at"] == cached["generated_at"]
    assert payload["jobs_generated_at"]

def test_sync_jobs_index_never_writes_read_projection_back_to_worker_job(tmp_path, monkeypatch):
    import app as app_module

    jobs_dir = tmp_path / "jobs"
    job_dir = jobs_dir / "train-live"
    job_dir.mkdir(parents=True)
    job_file = job_dir / "job.json"
    original = {
        "id": "train-live",
        "status": "running",
        "task_status": "RUNNING",
        "progress_percent": 31,
        "current_item": "Epoch 2/10 · Batch 4/100",
        "updated_at": "2026-09-23 23:00:00",
    }
    job_file.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(app_module, "project_dir", lambda _project_id: tmp_path)
    monkeypatch.setattr(
        app_module,
        "enrich_job_runtime",
        lambda _project_id, job, **_kwargs: {
            **job,
            "progress_percent": 35,
            "elapsed_seconds": 10,
        },
    )

    app_module.sync_jobs_index("project-1")

    assert json.loads(job_file.read_text(encoding="utf-8")) == original
    index = json.loads((jobs_dir / "index.json").read_text(encoding="utf-8"))
    assert index[0]["progress_percent"] == 35

def test_training_log_tail_reader_is_bounded_and_keeps_latest_text(tmp_path):
    import app as app_module

    path = tmp_path / "huge-train.log"
    early_marker = "EARLY-ONLY-MARKER\n"
    latest_marker = "LATEST-TRAINING-LINE"
    path.write_text(
        early_marker + ("epoch output\n" * 100_000) + latest_marker,
        encoding="utf-8",
    )

    tail = app_module._tail_training_log_text(path, max_chars=120_000)

    assert len(tail) <= 120_000
    assert tail.endswith(latest_marker)
    assert early_marker.strip() not in tail


def test_training_job_log_endpoint_uses_bounded_tail_helper():
    import inspect
    import app as app_module

    source = inspect.getsource(app_module.job_log)
    assert "_tail_training_log_text(log_file)" in source
    assert "_tail_training_log_text(durable_log)" in source
    assert ".read_text(" not in source

