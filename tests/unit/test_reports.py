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
