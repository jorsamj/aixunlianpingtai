"""N5: read-only HTTP quality projection for registered ModelArtifacts.

The router is mounted on an isolated FastAPI app (same pattern as the existing
external-publish router test) so the real route body and response contract are
exercised without touching the real data directory or any external platform.
"""
import hashlib
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import platform_core.external_algorithm_publish as publish_module
from platform_core.secrets import MemorySecretStore, SecretCredentialStore
from platform_core.storage.source_repository import StorageSourceRepository


def _project_dir(root: Path, project_id: str = "p1") -> Path:
    path = root / "projects" / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _service(root: Path, memory, sources, credentials):
    return publish_module.ExternalAlgorithmPublishService(
        data_dir=root,
        project_dir=lambda pid: _project_dir(root, pid),
        algorithms_file=lambda pid: _project_dir(root, pid) / "algorithms.json",
        external_secret_store_factory=lambda: memory,
        storage_sources_factory=lambda: sources,
        storage_credentials_factory=lambda: credentials,
    )


def _mount_router(root: Path, monkeypatch, service):
    memory = MemorySecretStore()
    sources = StorageSourceRepository(root / "storage" / "storage_sources.sqlite3")
    credentials = SecretCredentialStore(memory)
    api = FastAPI()
    with monkeypatch.context() as patch:
        patch.setattr(
            publish_module, "ExternalAlgorithmPublishService",
            lambda **_: service,
        )
        patch.setattr(publish_module.threading.Thread, "start", lambda _self: None)
        router = publish_module.external_algorithm_publish_router(
            data_dir=root,
            get_project=lambda pid: {"id": pid},
            project_dir=lambda pid: _project_dir(root, pid),
            algorithms_file=lambda pid: _project_dir(root, pid) / "algorithms.json",
            external_secret_store_factory=lambda: memory,
            storage_sources_factory=lambda: sources,
            storage_credentials_factory=lambda: credentials,
        )
    api.include_router(router)
    return api


def _artifact_rows(root: Path, project_id: str = "p1"):
    memory = MemorySecretStore()
    sources = StorageSourceRepository(root / "storage" / "storage_sources.sqlite3")
    credentials = SecretCredentialStore(memory)
    service = _service(root, memory, sources, credentials)
    return service.model_assets.repository.list(project_id=project_id, limit=100)


def test_model_artifact_list_projects_delivery_quality_without_writes(tmp_path, monkeypatch):
    memory = MemorySecretStore()
    sources = StorageSourceRepository(tmp_path / "storage" / "storage_sources.sqlite3")
    credentials = SecretCredentialStore(memory)
    service = _service(tmp_path, memory, sources, credentials)

    original = tmp_path / "original.pt"
    original.write_bytes(b"original-model-bytes")
    converted = tmp_path / "model.onnx"
    converted.write_bytes(b"converted-onnx-bytes")
    service.model_assets.repository.upsert({
        "artifact_id": "a-original", "project_id": "p1", "algorithm_id": "a1",
        "version_id": "v1", "artifact_kind": "original", "target": "original",
        "chip_code": "", "conversion_job_id": "", "file_name": original.name,
        "source_path": str(original),
        "sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
        "size_bytes": original.stat().st_size, "metadata": {},
    })
    service.model_assets.repository.upsert({
        "artifact_id": "a-onnx", "project_id": "p1", "algorithm_id": "a1",
        "version_id": "v1", "artifact_kind": "conversion", "target": "onnx",
        "chip_code": "", "conversion_job_id": "j1", "file_name": converted.name,
        "source_path": str(converted),
        "sha256": hashlib.sha256(converted.read_bytes()).hexdigest(),
        "size_bytes": converted.stat().st_size,
        "metadata": {
            "numeric_status": "consistent", "numeric_validation": {},
            "manifest_integrity_status": "unverified",
            "conversion_identity_verified": False, "runtime_verified": False,
            "hardware_verified": False,
        },
    })
    files_before = {path.name: path.read_bytes() for path in (original, converted)}
    rows_before = _artifact_rows(tmp_path)

    app = _mount_router(tmp_path, monkeypatch, service)
    with TestClient(app) as client:
        response = client.get("/api/v64/model-artifacts?project_id=p1")
        missing = client.get("/api/v64/model-artifacts?project_id=other")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    items = {row["artifact_id"]: row for row in payload["items"]}
    assert set(items) == {"a-original", "a-onnx"}
    for row in items.values():
        for field in (
            "quality_preflight", "formal_activation_eligible",
            "delivery_presentation", "hardware_acceptance",
        ):
            assert field in row

    original_row = items["a-original"]
    assert original_row["quality_preflight"]["schema"] == "delivery-quality-preflight-v1"
    assert original_row["formal_activation_eligible"] is True
    assert original_row["delivery_presentation"] == "FORMAL_ACTIVATION"
    assert original_row["present_as_formal_activation"] is True
    assert original_row["hardware_acceptance"] == "NOT_VERIFIED"
    assert original_row["present_as_hardware_accepted"] is False

    converted_row = items["a-onnx"]
    # Legal but unverified conversion: attachment/archive delivery stays allowed,
    # never presented as formal activation or hardware acceptance.
    assert converted_row["formal_activation_eligible"] is False
    assert converted_row["delivery_presentation"] == "UNVERIFIED_ATTACHMENT"
    assert converted_row["attachment_delivery_allowed"] is True
    assert converted_row["hardware_acceptance"] == "NOT_VERIFIED"
    assert converted_row["quality_preflight"]["numeric_status_alone_is_sufficient"] is False
    assert "NUMERIC_EVIDENCE_MISSING" in converted_row["quality_preflight"]["reasons"]
    assert "MANIFEST_DIGEST_UNVERIFIED" in converted_row["quality_preflight"]["reasons"]

    quality = payload["delivery_quality"]
    assert quality["formal_activation_eligible_count"] == 1
    assert quality["attachment_delivery_allowed_count"] >= 1
    assert quality["hardware_accepted_count"] == 0
    assert quality["numeric_status_alone_is_sufficient"] is False

    # Read-only: rows and bytes are unchanged, and the scoped query is empty.
    assert _artifact_rows(tmp_path) == rows_before
    assert {path.name: path.read_bytes() for path in (original, converted)} == files_before
    assert missing.status_code == 200
    assert missing.json()["items"] == []
