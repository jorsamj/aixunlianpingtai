import app as app_module


def test_legacy_annotated_import_endpoints_fail_closed_without_mutation(
    client, seeded_project
):
    project_id, image = seeded_project
    before_labels = client.get(
        f"/api/v12/projects/{project_id}/labels"
    ).json()["items"]
    assert client.get(
        f"/api/projects/{project_id}/annotations/{image['id']}"
    ).json()["boxes"] == []

    requests = [
        (
            f"/api/projects/{project_id}/import/yolo_zip",
            {"file": ("legacy-yolo.zip", b"legacy", "application/zip")},
        ),
        (
            f"/api/projects/{project_id}/import/coco_zip",
            {"file": ("legacy-coco.zip", b"legacy", "application/zip")},
        ),
        (
            f"/api/projects/{project_id}/import/voc_zip",
            {"file": ("legacy-voc.zip", b"legacy", "application/zip")},
        ),
    ]
    for endpoint, files in requests:
        response = client.post(endpoint, files=files, data={"dataset_id": "default"})
        assert response.status_code == 409, response.text
        assert "上传并检查标注" in response.text
        assert "先确认外部标签到平台标签的映射" in response.text

    label_response = client.post(
        f"/api/projects/{project_id}/import/labels",
        files=[
            (
                "files",
                ("seed.txt", b"0 0.5 0.5 0.2 0.2", "text/plain"),
            )
        ],
    )
    assert label_response.status_code == 409, label_response.text
    assert "上传并检查标注" in label_response.text

    after_labels = client.get(
        f"/api/v12/projects/{project_id}/labels"
    ).json()["items"]
    assert [row["code"] for row in after_labels] == [
        row["code"] for row in before_labels
    ]
    assert client.get(
        f"/api/projects/{project_id}/annotations/{image['id']}"
    ).json()["boxes"] == []


def test_legacy_annotated_import_guard_preserves_project_not_found(client):
    response = client.post(
        "/api/projects/missing-project/import/yolo_zip",
        files={"file": ("legacy.zip", b"legacy", "application/zip")},
        data={"dataset_id": "default"},
    )
    assert response.status_code == 404


def test_legacy_direct_prelabel_endpoints_require_human_review(client, seeded_project):
    project_id, image = seeded_project
    before_labels = client.get(
        f"/api/v12/projects/{project_id}/labels"
    ).json()["items"]
    before_boxes = client.get(
        f"/api/projects/{project_id}/annotations/{image['id']}"
    ).json()["boxes"]
    before_tasks = client.get(
        f"/api/v33/projects/{project_id}/prelabel-tasks"
    ).json()["items"]

    endpoints = [
        f"/api/projects/{project_id}/prelabel/run",
        f"/api/v33/projects/{project_id}/prelabel-tasks",
        f"/api/v35/projects/{project_id}/prelabel-tasks",
    ]
    for endpoint in endpoints:
        response = client.post(endpoint, json={})
        assert response.status_code == 409, response.text
        assert "旧版自动标注直写接口已关闭" in response.text
        assert "人工二次确认" in response.text

    after_labels = client.get(
        f"/api/v12/projects/{project_id}/labels"
    ).json()["items"]
    after_boxes = client.get(
        f"/api/projects/{project_id}/annotations/{image['id']}"
    ).json()["boxes"]
    after_tasks = client.get(
        f"/api/v33/projects/{project_id}/prelabel-tasks"
    ).json()["items"]

    assert [row["code"] for row in after_labels] == [
        row["code"] for row in before_labels
    ]
    assert after_boxes == before_boxes
    assert after_tasks == before_tasks


def test_legacy_direct_prelabel_guard_preserves_project_not_found(client):
    response = client.post(
        "/api/v35/projects/missing-project/prelabel-tasks",
        json={},
    )
    assert response.status_code == 404
