from __future__ import annotations

import io
import uuid

import app as app_module
from PIL import Image


def image_bytes(color="orange"):
    stream = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(stream, format="JPEG")
    return stream.getvalue()


def test_upload_to_selected_storage_source_enters_unified_pool(client, tmp_path):
    source_id = "local_upload_" + uuid.uuid4().hex[:8]
    source_root = tmp_path / "external-source"
    created = client.post("/api/v61/storage-sources", json={
        "id": source_id, "name": source_id, "type": "local",
        "config": {"root": str(source_root)}, "enabled": True,
    })
    assert created.status_code == 201, created.text
    project = client.post("/api/projects", json={"name": "storage-upload", "labels": []}).json()

    uploaded = client.post(
        f"/api/projects/{project['id']}/images",
        files=[("files", ("outside.jpg", image_bytes(), "image/jpeg"))],
        data={"storage_source_id": source_id},
    )
    assert uploaded.status_code == 200, uploaded.text
    row = uploaded.json()["uploaded"][0]
    assert row["storage_source_id"] == source_id
    assert row["storage_type"] == "local"
    assert row["object_key"].startswith("uploads/")
    assert len(row["content_sha256"]) == 64
    assert row["size_bytes"] > 0
    assert (source_root / row["object_key"]).is_file()
    assert not (app_module.project_dir(project["id"]) / "uploads" / row["stored_name"]).exists()

    page = client.get(f"/api/v61/projects/{project['id']}/materials", params={"storage_source_id": source_id})
    assert [item["id"] for item in page.json()["items"]] == [row["id"]]
    assert client.get(row["url"]).content == image_bytes()


def test_failed_provider_upload_does_not_create_material_index(client, tmp_path):
    source_id = "disabled_" + uuid.uuid4().hex[:8]
    client.post("/api/v61/storage-sources", json={
        "id": source_id, "name": source_id, "type": "local",
        "config": {"root": str(tmp_path / "disabled")}, "enabled": False,
    }).raise_for_status()
    project = client.post("/api/projects", json={"name": "failed-upload", "labels": []}).json()
    response = client.post(
        f"/api/projects/{project['id']}/images",
        files=[("files", ("failed.jpg", image_bytes(), "image/jpeg"))],
        data={"storage_source_id": source_id},
    )
    assert response.status_code == 200
    assert response.json()["uploaded_count"] == 0
    assert response.json()["failed_count"] == 1
    assert "停用" in response.json()["failed"][0]["reason"]
    assert app_module.material_store(project["id"]).count() == 0


def test_storage_scan_api_creates_a_durable_background_task(client, tmp_path):
    source_id = "scan_" + uuid.uuid4().hex[:8]
    client.post("/api/v61/storage-sources", json={
        "id": source_id, "name": source_id, "type": "local",
        "config": {"root": str(tmp_path / "scan-source")}, "enabled": True,
    }).raise_for_status()
    project = client.post("/api/projects", json={"name": "scan-api", "labels": []}).json()
    created = client.post(f"/api/v61/projects/{project['id']}/storage-imports/scan", json={
        "storage_source_id": source_id, "prefix": "incoming", "recursive": True,
    })
    assert created.status_code == 202, created.text
    task = created.json()
    assert task["status"] == "QUEUED"
    persisted = client.get(f"/api/v61/projects/{project['id']}/storage-imports/{task['task_id']}")
    assert persisted.status_code == 200
    assert persisted.json()["task_id"] == task["task_id"]
    assert persisted.json()["kind"] == "MATERIAL_IMPORT"
