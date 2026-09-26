import app as app_module


def test_project_label_mutation_refreshes_ready_bootstrap_snapshot(client, monkeypatch):
    project = client.post(
        "/api/projects",
        json={
            "name": "bootstrap-label-truth",
            "labels": [{"code": "object", "display_name": "对象"}],
        },
    ).json()
    project_id = project["id"]

    snapshot = app_module._v53_build_snapshot(project_id)
    snapshot["projects"] = [dict(project)]
    monkeypatch.setattr(app_module, "_V53_BOOTSTRAP_SNAPSHOT", snapshot)
    monkeypatch.setattr(
        app_module,
        "_V53_BOOTSTRAP_STATUS",
        {
            "status": "ready",
            "progress": 100,
            "active_project_id": project_id,
        },
    )

    created = client.post(
        f"/api/projects/{project_id}/labels",
        json={"label": "helmet", "display_name": "安全帽"},
    )
    assert created.status_code == 200, created.text

    cached = app_module._V53_BOOTSTRAP_SNAPSHOT
    assert [row["code"] for row in cached["labels"]] == ["object", "helmet"]
    assert cached["project"]["labels"] == ["object", "helmet"]

    response = client.get(
        "/api/v53/bootstrap/snapshot",
        params={"preferred_project_id": project_id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [row["code"] for row in body["labels"]] == ["object", "helmet"]
