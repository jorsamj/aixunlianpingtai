def test_finished_worker_is_not_downgraded_to_failed(client):
    import app as app_module

    project = client.post("/api/projects", json={"name": "job-race", "labels": []}).json()
    job_id = "finishedrace"
    job_file = app_module.project_dir(project["id"]) / "jobs" / job_id / "job.json"
    app_module.write_json(job_file, {
        "id": job_id,
        "status": "running",
        "target": "local",
        "pid": 999_999_999,
        "epochs": 1,
    })

    class FinishedProcess:
        def poll(self):
            return 0

    app_module.PROCESS_REGISTRY[job_id] = FinishedProcess()
    response = client.get(f"/api/projects/{project['id']}/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "done"
