from __future__ import annotations

import uuid

import app as app_module
from platform_core.secrets import MemorySecretStore
from platform_core.storage.import_candidates import RescanCandidateStore
from platform_core.storage.import_tasks import MANIFEST_REF


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

    oss_id = "oss_" + uuid.uuid4().hex[:8]
    oss = client.post("/api/v61/storage-sources", json={
        "id": oss_id, "name": oss_id, "type": "oss",
        "config": {
            "endpoint": "http://127.0.0.1:1",
            "bucket": "unreachable-bucket",
            "timeout_seconds": 1,
        },
        "credentials": {
            "access_key_id": "invalid-id",
            "access_key_secret": "invalid-oss-secret",
        },
    })
    assert oss.status_code == 201, oss.text
    assert "invalid-oss-secret" not in oss.text
    oss_test = client.post(f"/api/v61/storage-sources/{oss_id}/test")
    assert oss_test.status_code == 503
    assert oss_test.json()["code"] == "STORAGE_HEALTH_CHECK_FAILED"
    assert "invalid-oss-secret" not in oss_test.text


def test_default_local_is_always_present_and_cannot_be_deleted(client):
    sources = client.get("/api/v61/storage-sources")
    assert sources.status_code == 200
    assert any(item["id"] == "default_local" for item in sources.json()["items"])
    deleted = client.delete("/api/v61/storage-sources/default_local")
    assert deleted.status_code == 409


def test_storage_rescan_agent_creation_freezes_baseline_and_uses_portable_contract(
    client, seeded_project, monkeypatch
):
    project_id, _seed = seeded_project
    source_id = "s3_rescan_" + uuid.uuid4().hex[:8]
    created = client.post("/api/v61/storage-sources", json={
        "id": source_id,
        "name": source_id,
        "type": "s3",
        "config": {"bucket": "materials", "region": "ap-southeast-1"},
        "enabled": True,
    })
    assert created.status_code == 201, created.text

    monkeypatch.setattr(
        app_module,
        "_storage_rescan_agent_preflight",
        lambda _project_id, _source_id: {
            "agent_available": True,
            "reason": "",
            "eligible_nodes": [{"node_id": "material-agent-1", "display_name": "素材节点"}],
        },
    )
    calls = {}

    class FakeTransport:
        def stage_material_storage_scan(self, **kwargs):
            calls.update(kwargs)
            return {
                "version": 1,
                "task_kind": "MATERIAL_IMPORT",
                "transport": "object-storage-v1",
                "material_import": {
                    "schema_version": 1,
                    "mode": "storage_scan",
                    "intent": "storage_rescan",
                    "import_format": "images",
                    "dataset_yaml": "",
                    "source": {
                        "storage_source_id": source_id,
                        "storage_type": "s3",
                        "prefix": "",
                        "recursive": True,
                    },
                    "target": {
                        "storage_source_id": source_id,
                        "storage_type": "s3",
                        "target_prefix": "",
                    },
                    "output": {
                        "storage_source_id": source_id,
                        "object_key": "remote-execution/rescan/review.zip",
                        "file_name": "material-review.zip",
                        "content_type": "application/zip",
                    },
                },
            }

    monkeypatch.setattr(app_module, "_remote_execution_transport_service", lambda: FakeTransport())

    response = client.post(
        f"/api/v61/projects/{project_id}/storage-sources/{source_id}/rescans",
        json={"execution_mode": "agent"},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["execution_mode"] == "agent"

    task = app_module.shared_task_repository().get(body["task_id"])
    assert task is not None
    assert task.required_capabilities == ("agent.remote",)
    request = app_module.shared_task_artifacts().read_json(
        task.task_id, task.payload_ref, default={}
    )
    assert request["mode"] == "storage_rescan"
    assert request["execution_mode"] == "agent"
    assert request["remote_execution"]["material_import"]["intent"] == "storage_rescan"
    assert calls["allow_root"] is True
    assert calls["intent"] == "storage_rescan"
    manifest = app_module.shared_task_artifacts().artifact_path(task.task_id, MANIFEST_REF)
    store = RescanCandidateStore(manifest)
    assert store.meta("baseline_complete") is True
    assert store.meta("source_fingerprint")
