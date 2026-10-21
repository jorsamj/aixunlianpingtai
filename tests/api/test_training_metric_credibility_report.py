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


def test_report_api_preserves_normalized_class_null_zero_and_failure(monkeypatch, tmp_path):
    from platform_core.training_evaluation import build_evaluation_truth
    truth = build_evaluation_truth({
        "status": "failed",
        "metrics": {"metrics/mAP50(B)": None},
        "per_class": [
            {"class_id": 0, "precision": 0.0, "recall": None},
            {"class_id": 1, "evaluation_status": "no_test_ground_truth",
             "ground_truth_count": 0, "false_positive": 3},
        ],
    }, task_id="training-1")
    durable = {"training_report": {"metrics": {"metrics/mAP50(B)": .97}},
               "evaluation": truth}
    platform = _setup_report(monkeypatch, tmp_path, durable_result=durable)
    response = platform.v44_training_report("p", "training-1")
    report = response["report"]
    assert report["evaluation"] == truth
    assert report["evaluation"]["status"] == "failed"
    assert report["evaluation"]["per_class"][0]["precision"] == 0.0
    assert report["evaluation"]["per_class"][0]["recall"] is None
    assert report["evaluation"]["per_class"][1]["false_positive"] == 3
    assert report["metrics"]["metrics/mAP50(B)"] == .97
    assert build_version_report(durable)["evaluation"] == truth


def test_report_context_is_bound_to_selected_version_and_frozen_labels(monkeypatch,tmp_path):
    platform=_setup_report(monkeypatch,tmp_path)
    monkeypatch.setattr(platform,'DATA_DIR',tmp_path)
    version={'id':'v-person','job_id':'training-1','label_codes':['person'],'label_schema':[{'class_id':0,'code':'person','display_name':'行人'}],'training_lineage':{'task_id':'training-1','base':{'model':'yolo11n.pt'}}}
    monkeypatch.setattr(platform,'list_algorithms_internal',lambda _path:[{'id':'a','name':'Person','versions':[version]}])
    response=platform.v44_training_report('p','training-1',algorithm_id='a',version_id='v-person')
    assert response['report']['identity']=={'project_id':'p','algorithm_id':'a','algorithm_name':'Person','version_id':'v-person','job_id':'training-1'}
    assert response['report']['class_mapping']==[{'class_id':0,'code':'person','name':'行人'}]
    assert response['report']['model_architecture']=='YOLOv11n'
    assert response['report']['conversions']==[]
    assert response['report']['representative_errors']['items']==[]


def test_report_rejects_unrelated_selected_version_instead_of_reusing_old_task(monkeypatch,tmp_path):
    import pytest
    from fastapi import HTTPException
    platform=_setup_report(monkeypatch,tmp_path)
    monkeypatch.setattr(platform,'DATA_DIR',tmp_path)
    monkeypatch.setattr(platform,'list_algorithms_internal',lambda _path:[{'id':'a','versions':[{'id':'v-other','job_id':'another-task'}]}])
    with pytest.raises(HTTPException) as error:
        platform.v44_training_report('p','training-1',algorithm_id='a',version_id='v-other')
    assert error.value.status_code==409


def test_report_rejects_conflicting_version_lineage_task(monkeypatch,tmp_path):
    import pytest
    from fastapi import HTTPException
    platform=_setup_report(monkeypatch,tmp_path)
    monkeypatch.setattr(platform,'list_algorithms_internal',lambda _path:[{'id':'a','versions':[{'id':'v','job_id':'training-1','training_lineage':{'task_id':'another-task'}}]}])
    with pytest.raises(HTTPException) as error:
        platform.v44_training_report('p','training-1',algorithm_id='a',version_id='v')
    assert error.value.status_code==409


def test_report_projects_frozen_source_negative_audit_and_preserves_unknown_elapsed(monkeypatch,tmp_path):
    platform=_setup_report(monkeypatch,tmp_path)
    monkeypatch.setattr(platform,'DATA_DIR',tmp_path)
    path=tmp_path/'project'/'snapshots';path.mkdir()
    coverage={'role_confirmed_negative_image_counts':{'train':0,'validation':2},'role_unknown_source_image_counts':{'train':3},'provenance_status':'partial_unknown'}
    (path/('a'*64+'.json')).write_text(json.dumps({'snapshot_id':'a'*64,'images':[], 'input_quality':{'class_coverage':coverage,'warnings':['来源未知']}}),encoding='utf-8')
    report=platform.v44_training_report('p','training-1')['report']
    assert report['frozen_data_quality']['negative_count']==coverage['role_confirmed_negative_image_counts']
    assert report['capture_source_summary']['role_unknown_source_image_counts']=={'train':3}
    assert report['frozen_audit']['warnings']==['来源未知']
    assert report['elapsed_seconds'] is None
    job_file=tmp_path/'project'/'jobs'/'training-1'/'job.json'
    job=json.loads(job_file.read_text(encoding='utf-8'));job['training_report']={}
    job_file.write_text(json.dumps(job),encoding='utf-8')
    assert platform.v44_training_report('p','training-1')['report']['elapsed_seconds'] is None


def test_report_without_run_dir_never_reads_unrelated_working_directory_csv(monkeypatch,tmp_path):
    import app as platform
    monkeypatch.chdir(tmp_path)
    (tmp_path/'results.csv').write_text('epoch,metrics/mAP50(B)\n1,0.95\n',encoding='utf-8')
    assert platform._v45_training_history({}) == []
    assert platform._v45_training_history({'run_dir':str(tmp_path)})[0]['map50'] == .95
