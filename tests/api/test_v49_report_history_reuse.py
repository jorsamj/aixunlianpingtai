"""P1: algorithm report reuses its already-read task history for success counts."""
import pytest
import app as platform

@pytest.mark.parametrize("lightweight", [True, False])
def test_algorithm_report_reuses_one_history_snapshot(client, monkeypatch, lightweight):
    project = client.post("/api/projects", json={"name": "report-history-reuse", "labels": []}).json()["id"]
    algorithm = client.post(
        f"/api/v12/projects/{project}/algorithms",
        json={"name": "reused-history"},
    ).json()["algorithm"]["id"]
    for task_id, status, seconds in [("report-success", "done", 11), ("report-failure", "failed", 17)]:
        platform.write_json(
            platform.project_dir(project) / "jobs" / task_id / "job.json",
            {"id": task_id, "asset_algorithm_id": algorithm,
             "asset_algorithm_name": "reused-history",
             "status": status, "elapsed_seconds": seconds,
             "artifact_verified": status == "done"},
        )
    original = platform._training_history_context
    reads = []
    def counted(project_id):
        reads.append(project_id)
        return original(project_id)
    monkeypatch.setattr(platform, "_training_history_context", counted)

    response = client.get(
        f"/api/v49/projects/{project}/algorithms/{algorithm}/report",
        params={"lightweight": str(lightweight).lower()},
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert reads == [project], "the success count must not rescan task history"
    assert report["summary"]["attempt_count"] == 2
    assert report["summary"]["successful_count"] == 1
    assert report["summary"]["total_duration_seconds"] == 28
    assert report["summary"]["duration_record_count"] == 2
    assert report["jobs_total"] == 2
    assert report["summary"]["label_counts_scope"] == (
        "not_computed_fast" if lightweight else "cumulative_training_boxes"
    )
