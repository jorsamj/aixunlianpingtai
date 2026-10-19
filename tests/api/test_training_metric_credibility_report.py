"""TQ-04 frontend/API acceptance: do not invent historic credibility."""
import json
from types import SimpleNamespace

from platform_core.reports import build_version_report


def _setup_report(monkeypatch, tmp_path, *, durable_result=None):
    import app as platform
    project = tmp_path / "project"
    jobs = project / "jobs" / "training-1"
    jobs.mkdir(parents=True)
    job = {
        "id": "training-1",
        "status": "done",
        "snapshot_id": "a" * 64,
        "metrics": {"metrics/mAP50(B)": .80},
        "training_report": {
            "metrics": {"metrics/mAP50(B)": .96},
            "test_result": {"status": "not_requested"},
        },
    }
    (jobs / "job.json").write_text(json.dumps(job), encoding="utf-8")
    monkeypatch.setattr(platform, "get_project", lambda _: {"id": "p"})
    monkeypatch.setattr(platform, "project_dir", lambda _: project)
    monkeypatch.setattr(platform, "enrich_job_runtime", lambda _p, value: value)
    monkeypatch.setattr(platform, "_v45_training_history", lambda _job: [])
    monkeypatch.setattr(
        platform, "_durable_training_task",
        lambda _p, _task: SimpleNamespace(project_id="p") if durable_result is not None else None,
    )

    class Artifacts:
        def read_json(self, task_id, name, default=None):
            assert task_id == "training-1"
            assert name == "result.json"
            return durable_result
        def artifact_path(self, *_args):
            return tmp_path / "no-telemetry.sqlite3"

    monkeypatch.setattr(platform, "shared_task_artifacts", lambda: Artifacts())
    import platform_core.training_metrics as metrics
    monkeypatch.setattr(metrics, "read_metrics", lambda *_a, **_kw: {"epochs": []})
    return platform


def test_version_report_preserves_authoritative_credibility_without_inference():
    evidence = {
        "schema_version": 1, "status": "review_required",
        "validation_map50": .97, "reason_codes": ["independent_test_unavailable"],
    }
    saved = build_version_report({
        "id": "training-1", "metrics": {"metrics/mAP50(B)": .97},
        "metric_credibility": evidence,
        "evaluation": {"status": "failed"},
    })
    assert saved["metric_credibility"] == evidence
    assert saved["evaluation"]["status"] == "failed"
    assert build_version_report({"id": "legacy"})["metric_credibility"] is None


def test_training_report_api_prefers_durable_result_test_and_matching_validation(monkeypatch, tmp_path):
    durable = {
        "training_report": {
            "metrics": {"metrics/mAP50(B)": .97},
            "test_result": {"status": "succeeded", "metrics": {"metrics/mAP50(B)": .51}},
            "history": [],
        },
        "evaluation": {
            "status": "succeeded", "metrics": {"metrics/mAP50(B)": .51},
            "image_count": 20,
        },
        "metric_credibility": {
            "schema_version": 1, "status": "review_required",
            "validation_map50": .97, "independent_test_map50": .51,
            "val_minus_test_map50": .46,
            "reason_codes": ["validation_test_map50_gap_at_least_10pp"],
        },
    }
    platform = _setup_report(monkeypatch, tmp_path, durable_result=durable)
    response = platform.v44_training_report("p", "training-1")
    report = response["report"]
    assert report["metrics"]["metrics/mAP50(B)"] == .97
    assert report["evaluation"]["metrics"]["metrics/mAP50(B)"] == .51
    assert report["metric_credibility"]["validation_map50"] == .97
    assert report["metric_credibility"]["independent_test_map50"] == .51
    assert report["metric_credibility"]["status"] == "review_required"


def test_legacy_report_api_retains_real_record_but_marks_credibility_unavailable(monkeypatch, tmp_path):
    platform = _setup_report(monkeypatch, tmp_path)
    report = platform.v44_training_report("p", "training-1")["report"]
    # training_report.metrics is this legacy task's real finalized Val result;
    # job.metrics (.80) is an older cache, not the authoritative report value.
    assert report["metrics"]["metrics/mAP50(B)"] == .96
    assert report["metric_credibility"] is None
    assert report["evaluation"]["status"] == "not_requested"


def test_version_and_algorithm_reports_prefer_finalized_val_over_stale_job_cache():
    from platform_core.reports import build_algorithm_report
    record = {
        "id": "v1",
        "version_name": "v1",
        "metrics": {"metrics/mAP50(B)": 0.80},
        "training_report": {"metrics": {"metrics/mAP50(B)": 0.96}},
    }
    assert build_version_report(record)["metrics"]["metrics/mAP50(B)"] == 0.96
    assert build_algorithm_report([record])["trend"][0]["map50"] == 0.96
    legacy = {"id": "v0", "metrics": {"metrics/mAP50(B)": 0.80}}
    assert build_version_report(legacy)["metrics"]["metrics/mAP50(B)"] == 0.80
