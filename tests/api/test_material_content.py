from __future__ import annotations

from types import SimpleNamespace


def test_material_thumbnail_is_lazily_cached_without_changing_original_or_gt(client, seeded_project):
    import io
    from PIL import Image
    project_id, uploaded = seeded_project
    url = f"/api/v61/projects/{project_id}/materials/{uploaded['id']}/content"
    original = client.get(url).content
    annotation_url = f"/api/projects/{project_id}/annotations/{uploaded['id']}"
    annotation = client.get(annotation_url).json()
    response = client.get(url + "/thumbnail?edge=32")
    assert response.status_code == 200, response.text
    assert response.headers['content-type'] == 'image/jpeg'
    assert max(Image.open(io.BytesIO(response.content)).size) <= 32
    assert client.get(url + "/thumbnail?edge=32").content == response.content
    assert client.get(url).content == original
    assert client.get(annotation_url).json() == annotation

import app as app_module


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


def test_remote_material_content_is_backend_proxied_without_browser_redirect(
    client, seeded_project, tmp_path, monkeypatch,
):
    project_id, uploaded = seeded_project
    content = tmp_path / "remote.jpg"
    content.write_bytes(b"remote-image")

    class _Manager:
        def material(self, image_id):
            assert image_id == uploaded["id"]
            return {
                "id": image_id,
                "storage_type": "remote",
                "storage_source_id": "remote-a",
                "object_key": "images/remote.jpg",
            }

        def preview_url(self, _row):
            return "http://remote-storage.invalid/images/remote.jpg"

        def materialize(self, _row):
            return SimpleNamespace(path=content)

    monkeypatch.setattr(app_module, "storage_manager", lambda _project_id: _Manager())
    response = client.get(
        f"/api/v61/projects/{project_id}/materials/{uploaded['id']}/content",
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert response.content == b"remote-image"
    assert "location" not in response.headers


def test_material_source_and_multi_label_or_filters(client, seeded_project):
    project_id, uploaded = seeded_project
    current = client.get(
        f"/api/projects/{project_id}/annotations/{uploaded['id']}"
    ).json()
    client.post(f"/api/projects/{project_id}/annotations/{uploaded['id']}", json={"boxes": [{
        "id": "box-1", "label": "fire", "class_id": 0,
        "x1": 1, "y1": 1, "x2": 30, "y2": 30,
    }], "expected_version": current["annotation"]["version"],
        "source_content_sha256": current["image"]["content_sha256"]}).raise_for_status()
    page = client.get(
        f"/api/v61/projects/{project_id}/materials",
        params=[("storage_source_id", "default_local"), ("label", "fire"), ("label", "not-present")],
    )
    assert page.status_code == 200
    assert uploaded["id"] in {item["id"] for item in page.json()["items"]}

    ids = client.get(f"/api/v61/projects/{project_id}/materials/ids", params=[("label", "fire")])
    assert ids.status_code == 200
    assert uploaded["id"] in ids.json()["items"]


def test_material_id_only_cursor_keeps_full_filter_and_revision_contract(client, seeded_project):
    project_id, uploaded = seeded_project
    endpoint = f"/api/v61/projects/{project_id}/materials/ids"
    first = client.get(endpoint, params={
        "narrow": "true", "annotated": "false", "query": uploaded["filename"],
        "limit": 1,
    })
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["items"] == [uploaded["id"]]
    assert body["total"] == 1
    assert isinstance(body["repository_revision"], int)

    matching = client.get(endpoint, params={
        "narrow": "true", "annotated": "false", "query": uploaded["filename"],
        "expected_revision": body["repository_revision"],
    })
    assert matching.status_code == 200, matching.text
    assert matching.json()["items"] == body["items"]

    outdated = client.get(endpoint, params={
        "narrow": "true", "annotated": "false", "query": uploaded["filename"],
        "expected_revision": body["repository_revision"] + 1,
    })
    assert outdated.status_code == 409
