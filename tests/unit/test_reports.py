from platform_core.reports import build_algorithm_report, build_version_report


def test_generalization_signal_requires_paired_evidence_and_never_proves_cause():
    from platform_core.reports import diagnose_training_history
    rows = [{"epoch": i + 1, "box_loss": 2 - i * .06,
             "val_box_loss": 1 + i * .05, "map50": .6 - abs(i - 8) * .01}
            for i in range(20)]
    report = diagnose_training_history(rows)
    assert report["best_observed_epoch"] == 9
    assert report["findings"][0]["code"] == "GENERALIZATION_GAP"
    assert report["findings"][0]["confidence"] == "trend_signal"
    assert report["findings"][0]["evidence"]["paired_epochs"] == 20
    assert diagnose_training_history(rows[:9])["status"] == "insufficient_evidence"
    assert diagnose_training_history([{"epoch":1,"map50":.9}])["findings"] == []


def test_metric_diagnoses_distinguish_plateau_instability_and_observed_late_improvement():
    from platform_core.reports import diagnose_training_history
    def diagnose(values):
        return diagnose_training_history([{"epoch":i+1,"map50":value} for i,value in enumerate(values)])
    assert diagnose([.5]*12)["findings"][0]["code"] == "METRIC_PLATEAU"
    assert diagnose([.2,.8]*6)["findings"][0]["code"] == "METRIC_INSTABILITY"
    result=diagnose([.1+i*.025 for i in range(20)])
    assert result["findings"][0]["code"] == "LATE_IMPROVEMENT"
    assert result["findings"][0]["confidence"] == "trend_signal"


def test_version_report_keeps_snapshot_and_base_version():
    report = build_version_report(
        {"metrics": {"map50": 0.91}, "snapshot_id": "s1", "base_version_id": "v1"}
    )

    assert report["report_type"] == "version"
    assert report["snapshot_id"] == "s1"
    assert report["base_version_id"] == "v1"
    assert report["metrics"]["map50"] == 0.91


def test_algorithm_report_compares_latest_two_versions():
    report = build_algorithm_report(
        [
            {"version_name": "20260827120000", "metrics": {"map50": 0.80}},
            {"version_name": "20260828120000", "metrics": {"map50": 0.90}},
        ]
    )

    assert report["report_type"] == "algorithm"
    assert report["latest_vs_previous"]["map50_delta"] == 0.10
    assert report["best_version"] == "20260828120000"


def test_representative_samples_are_frozen_bounded_stratified_and_deterministic():
    from platform_core.reports import representative_error_samples
    samples=[{'image':f'{i}.jpg','image_id':str(i),'image_content_sha256':'b'*64,'fp_count':1 if i<8 else 0,'fn_count':1 if i>=8 else 0,'fp_labels':['person'],'fn_labels':['Car'],'gt_boxes':[],'pred_boxes':[]} for i in range(20)]
    evaluation={'status':'succeeded','evaluation_id':'e'*64,'task_id':'j','snapshot_id':'s','model_sha256':'a'*64,'error_samples':samples}
    selected=representative_error_samples(evaluation,job_id='j',snapshot_id='s')
    assert selected['status']=='available' and len(selected['items'])==8
    assert any(s['fp_count'] for s in selected['items']) and any(s['fn_count'] for s in selected['items'])
    assert selected==representative_error_samples({**evaluation,'error_samples':list(reversed(samples))},job_id='j',snapshot_id='s')
    assert len(representative_error_samples(evaluation,job_id='j',snapshot_id='s',limit=999)['items'])<=12
    assert representative_error_samples(evaluation,job_id='other',snapshot_id='s')['items']==[]
    assert representative_error_samples(evaluation,job_id='j',snapshot_id='wrong')['items']==[]
    assert representative_error_samples({**evaluation,'evaluation_id':''},job_id='j',snapshot_id='s')['items']==[]


def test_report_completed_zero_and_resource_coverage_remain_observed():
    from platform_core.reports import build_version_report, report_resource_evidence
    assert build_version_report({'completed_epochs': 0, 'current_epoch': 99})['completed_epochs'] == 0
    job = {'status': 'done', 'started_at': '2026-10-21T01:00:00Z', 'finished_at': '2026-10-21T01:10:00Z'}
    telemetry = {'samples': [
        {'sampled_at': '2026-10-21T00:59:00Z', 'cpu_percent': 99},
        {'sampled_at': '2026-10-21T01:01:00Z', 'cpu_percent': 0, 'gpu_utilization': True},
        {'sampled_at': '2026-10-21T01:02:00Z', 'cpu_percent': 20},
        {'sampled_at': '2026-10-21T01:11:00Z', 'cpu_percent': 100},
    ]}
    facts = report_resource_evidence(job, telemetry)
    assert facts['resource_coverage']['samples'] == 2
    assert facts['resource_summary']['cpu_percent'] == {'mean': 10, 'maximum': 20, 'samples': 2}
    assert facts['resource_summary']['gpu_utilization'] is None
    assert report_resource_evidence({'status': 'done'}, telemetry)['resource_coverage']['status'] == 'unavailable'
