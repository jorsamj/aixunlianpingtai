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
