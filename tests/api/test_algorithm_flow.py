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
