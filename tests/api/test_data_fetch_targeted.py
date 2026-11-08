"""Non-mutating data-fetch projections: optional UI summaries cannot drop canonical truth."""

import app as api


def test_jobs_summary_is_opt_in_and_cannot_mutate_full_report(monkeypatch):
    original = {
        "id": "job-1", "status": "done", "history": [{"epoch": 1}],
        "evaluation": {"large": "evidence"},
        "training_report": {"status": "succeeded", "epoch_history": [1, 2]},
    }
    monkeypatch.setattr(api, "get_project", lambda project_id: {"id": project_id})
    monkeypatch.setattr(api, "sync_jobs_index", lambda project_id, read_only: [original])

    projected = api.list_jobs("fixture", summary_only=True)
    assert projected[0]["id"] == "job-1"
    assert projected[0]["status"] == "done"
    assert "history" not in projected[0]
    assert "evaluation" not in projected[0]
    assert "epoch_history" not in projected[0]["training_report"]

    canonical = api.list_jobs("fixture")
    assert canonical[0] == original
    assert original["evaluation"]["large"] == "evidence"


def test_recommendation_is_neutral_and_never_probes_web_cuda_by_default(monkeypatch):
    monkeypatch.setattr(api.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("default recommendation must not start a GPU probe")
    ))
    payload = api.system_recommendation()
    assert payload["recommendation_source"] == "unverified_fallback"
    assert payload["worker_verified"] is False
    assert payload["cuda"] is None
    assert payload["recommendation"]["device"] == "auto"
