from platform_core.reports import build_algorithm_report, build_version_report


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
