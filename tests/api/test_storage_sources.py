from __future__ import annotations

import uuid

import app as app_module
from platform_core.secrets import MemorySecretStore


def test_storage_source_crud_masks_secret_and_runs_real_local_health(client, tmp_path):
    app_module.MODEL_SECRET_STORE = MemorySecretStore()
    source_id = "local_" + uuid.uuid4().hex[:8]
    root = tmp_path / "external-materials"
    created = client.post("/api/v61/storage-sources", json={
        "id": source_id,
        "name": "本地素材 " + source_id,
        "type": "local",
        "config": {"root": str(root)},
        "credentials": {"token": "must-never-be-returned"},
        "enabled": True,
    })
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["id"] == source_id
    assert body["secret_configured"] is True
    assert "must-never-be-returned" not in created.text

    health = client.post(f"/api/v61/storage-sources/{source_id}/test")
    assert health.status_code == 200, health.text
    assert health.json()["health"]["ok"] is True
    assert root.is_dir()

    updated = client.patch(f"/api/v61/storage-sources/{source_id}", json={"name": "已更新 " + source_id})
    assert updated.status_code == 200
    assert updated.json()["name"].startswith("已更新")
    assert "must-never-be-returned" not in updated.text

    defaulted = client.post(f"/api/v61/storage-sources/{source_id}/default")
    assert defaulted.status_code == 200
    assert defaulted.json()["is_default"] is True
    client.post("/api/v61/storage-sources/default_local/default").raise_for_status()
    deleted = client.delete(f"/api/v61/storage-sources/{source_id}")
    assert deleted.status_code == 200


def test_storage_source_validation_and_wrong_remote_credentials_are_truthful(client):
    app_module.MODEL_SECRET_STORE = MemorySecretStore()
    invalid = client.post("/api/v61/storage-sources", json={
        "id": "bad_" + uuid.uuid4().hex[:6], "name": "bad", "type": "oss",
        "config": {"bucket": "missing-endpoint"},
    })
    assert invalid.status_code == 422
    assert "Endpoint" in invalid.text

    source_id = "remote_" + uuid.uuid4().hex[:8]
    created = client.post("/api/v61/storage-sources", json={
        "id": source_id, "name": source_id, "type": "remote",
        "config": {"base_url": "http://127.0.0.1:1", "namespace": "main", "timeout_seconds": 1},
        "credentials": {"token": "wrong-secret"},
    })
    assert created.status_code == 201
    tested = client.post(f"/api/v61/storage-sources/{source_id}/test")
    assert tested.status_code == 503
    assert tested.json()["code"] == "STORAGE_HEALTH_CHECK_FAILED"
    assert "wrong-secret" not in tested.text


def test_default_local_is_always_present_and_cannot_be_deleted(client):
    sources = client.get("/api/v61/storage-sources")
    assert sources.status_code == 200
    assert any(item["id"] == "default_local" for item in sources.json()["items"])
    deleted = client.delete("/api/v61/storage-sources/default_local")
    assert deleted.status_code == 409
