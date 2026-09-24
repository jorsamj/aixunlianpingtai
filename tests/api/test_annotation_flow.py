def test_save_reload_and_thumbnail_summary_match(client, seeded_project):
    pid, image = seeded_project
    saved = client.post(
        f"/api/projects/{pid}/annotations/{image['id']}",
        json={"boxes": [{"label": "fire", "x1": 10, "y1": 10, "x2": 80, "y2": 90}]},
    )
    assert saved.status_code == 200
    material = saved.json()["image"]
    assert material["labels"] == ["fire"]
    assert material["box_count"] == 1
    assert material["annotation_status"] == "annotated"
    reloaded = client.get(f"/api/projects/{pid}/annotations/{image['id']}").json()
    assert reloaded["boxes"] == saved.json()["annotation"]["boxes"]
    listed = client.get(f"/api/projects/{pid}/images?dataset_id=default").json()
    row = next(item for item in listed if item["id"] == image["id"])
    assert row["annotation_preview"] == material["annotation_preview"]


def test_unknown_annotation_label_is_rejected(client, seeded_project):
    pid, image = seeded_project
    response = client.post(
        f"/api/projects/{pid}/annotations/{image['id']}",
        json={"boxes": [{"label": "not-in-library", "x1": 1, "y1": 1, "x2": 20, "y2": 20}]},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "ANNOTATION_LABEL_NOT_FOUND"



def test_empty_annotation_requires_explicit_no_target_confirmation(client, seeded_project):
    pid, image = seeded_project
    rejected = client.post(
        f"/api/projects/{pid}/annotations/{image['id']}",
        json={"boxes": []},
    )
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "ANNOTATION_EMPTY_CONFIRMATION_REQUIRED"

    confirmed = client.post(
        f"/api/projects/{pid}/annotations/{image['id']}",
        json={"boxes": [], "annotation_state": "confirmed_empty"},
    )
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["saved_boxes"] == 0
    assert body["annotation"]["boxes"] == []
    assert body["annotation"]["annotation_state"] == "confirmed_empty"
