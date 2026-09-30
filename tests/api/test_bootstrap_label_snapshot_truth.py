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



def test_algorithm_mutation_invalidates_only_bootstrap_algorithm_overlay(client, monkeypatch):
    project = client.post(
        "/api/projects",
        json={
            "name": "bootstrap-algorithm-revision",
            "labels": [{"code": "object", "display_name": "对象"}],
        },
    ).json()
    project_id = project["id"]

    snapshot = app_module._v53_build_snapshot(project_id)
    snapshot["projects"] = [dict(project)]
    cached_revision = snapshot["algorithm_revision"]
    assert snapshot["algorithms"] == []
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
        f"/api/v12/projects/{project_id}/algorithms",
        json={
            "name": "同步后立即可见",
            "industry": "工业安全",
            "algorithm_type": "yolo_ultralytics",
            "remark": "",
        },
    )
    assert created.status_code == 200, created.text
    algorithm_id = created.json()["algorithm"]["id"]

    # The cached startup object is deliberately still stale before the GET.
    assert algorithm_id not in {
        row["id"] for row in snapshot["algorithms"]
    }

    response = client.get(
        "/api/v53/bootstrap/snapshot",
        params={"preferred_project_id": project_id},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["algorithm_revision"] > cached_revision
    assert algorithm_id in {row["id"] for row in body["algorithms"]}
    assert app_module._V53_BOOTSTRAP_SNAPSHOT["algorithm_revision"] == body["algorithm_revision"]
    assert algorithm_id in {
        row["id"] for row in app_module._V53_BOOTSTRAP_SNAPSHOT["algorithms"]
    }


def test_bootstrap_snapshot_carries_canonical_platform_identity(client):
    project = client.post(
        "/api/projects",
        json={
            "name": "bootstrap-version-truth",
            "labels": [],
        },
    ).json()

    snapshot = app_module._v53_build_snapshot(project["id"])

    assert snapshot["platform_version"] == app_module.APP_VERSION
    assert snapshot["build_id"] == app_module.BUILD_ID
    assert snapshot["platform_version"]
