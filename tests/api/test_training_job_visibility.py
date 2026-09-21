from __future__ import annotations

import json


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
