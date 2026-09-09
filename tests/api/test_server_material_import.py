from __future__ import annotations

import io
import uuid
import zipfile

import app as app_module
from PIL import Image

from platform_core.storage.import_candidates import ImportCandidateStore
from platform_core.storage.import_tasks import MANIFEST_REF, SCAN_RESULT_REF
from platform_core.task_runtime import TaskKind, TaskRecord, TaskStatus


def _project(client):
    response = client.post(
        "/api/projects",
        json={"name": f"server-import-{uuid.uuid4().hex[:8]}", "labels": []},
    )
    response.raise_for_status()
    return response.json()


def _source(client, tmp_path, *, source_type="local", enabled=True):
    source_id = f"import_{source_type}_{uuid.uuid4().hex[:8]}"
    config = {"root": str(tmp_path / source_id)} if source_type == "local" else {"bucket": "unit-test"}
    response = client.post("/api/v61/storage-sources", json={
        "id": source_id,
        "name": source_id,
        "type": source_type,
        "config": config,
        "enabled": enabled,
    })
    response.raise_for_status()
    return response.json()


def _write_zip(path):
    stream = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(stream, format="JPEG")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("frame.jpg", stream.getvalue())


def _waiting_import(project_id: str, keys=("a.jpg", "b.jpg")):
    task_id = uuid.uuid4().hex
    artifacts = app_module.shared_task_artifacts()
    repository = app_module.shared_task_repository()
    artifacts.atomic_write_json(task_id, "request.json", {
        "mode": "storage_scan",
        "storage_source_id": "default_local",
        "prefix": "",
        "recursive": True,
        "zip_path": None,
        "target_prefix": "",
    })
    store = ImportCandidateStore(artifacts.artifact_path(task_id, MANIFEST_REF))
    store.upsert_many({
        "object_key": key,
        "filename": key,
        "storage_source_id": "default_local",
        "storage_type": "local",
        "content_sha256": f"{index + 1:064x}",
        "size_bytes": 100,
        "etag": "",
        "width": 8,
        "height": 8,
        "status": "IMPORTABLE",
        "error": "",
        "duplicate": False,
    } for index, key in enumerate(keys))
    artifacts.atomic_write_json(task_id, SCAN_RESULT_REF, {
        "stage": "awaiting_confirmation",
        "scanned_files": len(keys),
        "importable_images": len(keys),
        "manifest_ref": MANIFEST_REF,
    })
    repository.create(TaskRecord.new(
        task_id,
        project_id,
        TaskKind.MATERIAL_IMPORT,
        "request.json",
        f"storage:confirm-{task_id}",
        priority=1,
        required_capabilities=("storage.import",),
    ))
    lease = repository.claim_next(
        f"confirm-test-{task_id}",
        (TaskKind.MATERIAL_IMPORT,),
        {"storage.import"},
    )
    assert lease is not None and lease.task.task_id == task_id
    repository.finish(
        task_id,
        lease.lease_token,
        TaskStatus.AWAITING_CONFIRMATION,
        SCAN_RESULT_REF,
    )
    return task_id


def test_server_zip_accepts_only_relative_path_for_enabled_local_source(
    client, tmp_path, monkeypatch,
):
    import_dir = tmp_path / "imports"
    import_dir.mkdir()
    _write_zip(import_dir / "fire.zip")
    monkeypatch.setenv("MC_SERVER_IMPORT_DIR", str(import_dir))
    project = _project(client)
    source = _source(client, tmp_path)

    response = client.post(
        f"/api/v61/projects/{project['id']}/storage-imports/scan",
        json={
            "mode": "server_zip",
            "zip_path": "fire.zip",
            "storage_source_id": source["id"],
            "target_prefix": "fire",
        },
    )

    assert response.status_code == 202, response.text
    task = response.json()
    assert task["status"] == "QUEUED"
    request = app_module.shared_task_artifacts().read_json(task["task_id"], "request.json")
    assert request["zip_path"] == "fire.zip"
    assert str(import_dir) not in str(request)

    outside = client.post(
        f"/api/v61/projects/{project['id']}/storage-imports/scan",
        json={
            "mode": "server_zip",
            "zip_path": "../fire.zip",
            "storage_source_id": source["id"],
            "target_prefix": "outside",
        },
    )
    assert outside.status_code == 422


def test_scan_modes_reject_invalid_source_or_field_combinations(client, tmp_path):
    project = _project(client)
    s3_source = _source(client, tmp_path, source_type="s3")

    storage_scan = client.post(
        f"/api/v61/projects/{project['id']}/storage-imports/scan",
        json={"mode": "storage_scan", "storage_source_id": s3_source["id"]},
    )
    assert storage_scan.status_code == 202, storage_scan.text

    directory_scan = client.post(
        f"/api/v61/projects/{project['id']}/storage-imports/scan",
        json={"mode": "directory_scan", "storage_source_id": s3_source["id"]},
    )
    assert directory_scan.status_code == 422
    assert "本地存储" in directory_scan.text

    unknown = client.post(
        f"/api/v61/projects/{project['id']}/storage-imports/scan",
        json={"mode": "unknown", "storage_source_id": s3_source["id"]},
    )
    assert unknown.status_code == 422

    invalid_fields = client.post(
        f"/api/v61/projects/{project['id']}/storage-imports/scan",
        json={
            "mode": "storage_scan",
            "storage_source_id": s3_source["id"],
            "zip_path": "fire.zip",
        },
    )
    assert invalid_fields.status_code == 422


def test_disabled_source_is_rejected_before_task_creation(client, tmp_path):
    project = _project(client)
    source = _source(client, tmp_path, enabled=False)
    response = client.post(
        f"/api/v61/projects/{project['id']}/storage-imports/scan",
        json={"mode": "directory_scan", "storage_source_id": source["id"]},
    )
    assert response.status_code == 409


def test_confirmation_only_requeues_and_identical_retry_is_idempotent(client):
    project = _project(client)
    task_id = _waiting_import(project["id"])
    endpoint = f"/api/v61/projects/{project['id']}/storage-imports/{task_id}/confirm"

    first = client.post(endpoint, json={"object_keys": ["a.jpg"]})
    assert first.status_code == 202, first.text
    assert first.json()["status"] == "QUEUED"
    assert first.json()["stage"] == "indexing_queued"
    assert app_module.material_store(project["id"]).count() == 0

    repeated = client.post(endpoint, json={"object_keys": ["a.jpg"]})
    assert repeated.status_code == 202, repeated.text
    assert repeated.json()["task_id"] == task_id

    conflicting = client.post(endpoint, json={"object_keys": ["b.jpg"]})
    assert conflicting.status_code == 409
    assert app_module.material_store(project["id"]).count() == 0


def test_confirmation_before_scan_completion_is_rejected(client):
    project = _project(client)
    response = client.post(
        f"/api/v61/projects/{project['id']}/storage-imports/scan",
        json={"storage_source_id": "default_local"},
    )
    response.raise_for_status()
    task_id = response.json()["task_id"]
    confirmation = client.post(
        f"/api/v61/projects/{project['id']}/storage-imports/{task_id}/confirm",
        json={},
    )
    assert confirmation.status_code == 409


def test_public_import_task_exposes_only_bounded_zip_checkpoint_metrics():
    task = TaskRecord.new(
        uuid.uuid4().hex,
        "project-public-metrics",
        TaskKind.MATERIAL_IMPORT,
        "request.json",
        "storage:public-metrics",
    )
    app_module.shared_task_artifacts().atomic_write_json(
        task.task_id,
        "checkpoints/worker.json",
        {
            "stage": "extracting",
            "zip_import": {
                "extracted_files": 17,
                "extracted_bytes": 4096,
                "declared_files": 31,
                "declared_bytes": 8192,
                "current_file": r"C:\private\frames\017.jpg",
                "completed_members": {"private.jpg": {"sha256": "secret"}},
                "zip_path": "private.zip",
                "target_prefix": "private-target",
            },
        },
    )

    public = app_module._public_storage_import_task(task)

    assert public["metrics"]["extracted_files"] == 17
    assert public["metrics"]["extracted_bytes"] == 4096
    assert public["metrics"]["declared_files"] == 31
    assert public["metrics"]["declared_bytes"] == 8192
    assert public["metrics"]["current_file"] == "[REDACTED PATH]"
    assert "completed_members" not in public["metrics"]
    assert "zip_path" not in public["metrics"]
    assert "target_prefix" not in public["metrics"]
