from __future__ import annotations


def test_paginated_material_api_and_unified_content_endpoint(client, seeded_project):
    project_id, uploaded = seeded_project
    page = client.get(f"/api/v61/projects/{project_id}/materials", params={"limit": 1})
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["total"] >= 1
    row = next(item for item in body["items"] if item["id"] == uploaded["id"])
    assert row["storage_source_id"] == "default_local"
    assert row["storage_type"] == "local"
    assert row["object_key"].startswith("uploads/")
    assert row["url"] == f"/api/v61/projects/{project_id}/materials/{row['id']}/content"

    content = client.get(row["url"])
    assert content.status_code == 200
    assert content.content[:2] == b"\xff\xd8"
    assert len(row["content_sha256"]) == 64


def test_material_source_and_multi_label_or_filters(client, seeded_project):
    project_id, uploaded = seeded_project
    client.post(f"/api/projects/{project_id}/annotations/{uploaded['id']}", json={"boxes": [{
        "id": "box-1", "label": "fire", "class_id": 0,
        "x1": 1, "y1": 1, "x2": 30, "y2": 30,
    }]}).raise_for_status()
    page = client.get(
        f"/api/v61/projects/{project_id}/materials",
        params=[("storage_source_id", "default_local"), ("label", "fire"), ("label", "not-present")],
    )
    assert page.status_code == 200
    assert uploaded["id"] in {item["id"] for item in page.json()["items"]}

    ids = client.get(f"/api/v61/projects/{project_id}/materials/ids", params=[("label", "fire")])
    assert ids.status_code == 200
    assert uploaded["id"] in ids.json()["items"]
