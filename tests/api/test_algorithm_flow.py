def test_create_algorithm_returns_persisted_asset(client, seeded_project):
    project_id, _ = seeded_project
    payload = {
        "name": "烟火判断",
        "industry": "工业安全",
        "algorithm_type": "yolo_ultralytics",
        "remark": "",
    }
    response = client.post(f"/api/v12/projects/{project_id}/algorithms", json=payload)

    assert response.status_code == 200
    algorithm = response.json()["algorithm"]
    assert algorithm["name"] == "烟火判断"
    listed = client.get(f"/api/v12/projects/{project_id}/algorithms").json()["items"]
    assert [item["id"] for item in listed].count(algorithm["id"]) == 1


def test_duplicate_algorithm_name_is_actionable(client, seeded_project):
    project_id, _ = seeded_project
    payload = {
        "name": "烟火判断",
        "industry": "工业安全",
        "algorithm_type": "yolo_ultralytics",
        "remark": "",
    }
    client.post(f"/api/v12/projects/{project_id}/algorithms", json=payload)
    response = client.post(f"/api/v12/projects/{project_id}/algorithms", json=payload)

    assert response.status_code == 409
    assert response.json()["code"] == "ALGORITHM_NAME_EXISTS"
    assert response.json()["solution"]


def test_algorithm_detail_endpoint_returns_current_asset_and_missing_is_404(client, seeded_project):
    project_id, _ = seeded_project
    created = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={
            "name": "训练前详情校验",
            "industry": "工业安全",
            "algorithm_type": "yolo_ultralytics",
            "remark": "",
        },
    ).json()["algorithm"]

    fetched = client.get(
        f"/api/v12/projects/{project_id}/algorithms/{created['id']}"
    )
    assert fetched.status_code == 200
    assert fetched.json()["algorithm"]["id"] == created["id"]
    assert fetched.json()["algorithm"]["name"] == "训练前详情校验"

    missing = client.get(
        f"/api/v12/projects/{project_id}/algorithms/algorithm-does-not-exist"
    )
    assert missing.status_code == 404


def test_quality_center_uses_no_data_instead_of_fake_zero_success_rate(client, seeded_project):
    project_id, _ = seeded_project
    response = client.get(f"/api/v44/projects/{project_id}/quality-center")
    assert response.status_code == 200
    algorithm = response.json()["algorithm"]
    assert algorithm["train_completed_count"] == 0
    assert algorithm["train_success_count"] == 0
    assert algorithm["train_failure_count"] == 0
    assert algorithm["train_success_rate"] is None
