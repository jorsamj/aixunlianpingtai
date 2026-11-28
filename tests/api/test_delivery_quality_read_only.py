"""N5: read-only delivery quality projection + zero-write Dry-Run HTTP boundary.

These tests call the real FastAPI endpoint functions (the project's API test
style) and assert the new read-only responses never change the algorithm
version pointer/version rows/artifact rows. No device, external platform or
network is touched: the endpoints are pure reads.
"""
import hashlib
import json
from pathlib import Path

import app as api
from platform_core.algorithms import algorithm_store_revision, list_algorithms, save_algorithms
from platform_core.model_artifacts import ModelArtifactService
from platform_core.secrets import MemorySecretStore, SecretCredentialStore
from platform_core.storage.source_repository import StorageSourceRepository


def _project_dir(root: Path, project_id: str = "p1") -> Path:
    path = root / "projects" / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _service(root: Path) -> ModelArtifactService:
    memory = MemorySecretStore()
    sources = StorageSourceRepository(root / "storage" / "storage_sources.sqlite3")
    credentials = SecretCredentialStore(memory)
    return ModelArtifactService(
        data_dir=root,
        project_dir=lambda pid: _project_dir(root, pid),
        algorithms_file=lambda pid: _project_dir(root, pid) / "algorithms.json",
        storage_sources_factory=lambda: sources,
        storage_credentials_factory=lambda: credentials,
    )


def _wire_app(root: Path, monkeypatch) -> None:
    monkeypatch.setattr(api, "DATA_DIR", root)
    monkeypatch.setattr(api, "get_project", lambda project_id: {"id": project_id})
    monkeypatch.setattr(api, "project_dir", lambda project_id: _project_dir(root, project_id))
    monkeypatch.setattr(
        api, "algorithms_file",
        lambda project_id: _project_dir(root, project_id) / "algorithms.json",
    )
    memory = MemorySecretStore()
    sources = StorageSourceRepository(root / "storage" / "storage_sources.sqlite3")
    credentials = SecretCredentialStore(memory)
    monkeypatch.setattr(api, "storage_source_repository", lambda: sources)
    monkeypatch.setattr(api, "storage_credentials", lambda: credentials)


def _seed_two_versions(root: Path) -> Path:
    project = _project_dir(root, "p1")
    models = {}
    for version_id in ("v1", "v2"):
        model = project / "algorithm_versions" / "a1" / version_id / "best.pt"
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_bytes(b"model-" + version_id.encode("ascii"))
        models[version_id] = model
    path = project / "algorithms.json"
    save_algorithms(path, [{
        "id": "a1", "name": "本地算法", "current_version_id": "v1",
        "versions": [
            {"id": version_id, "version_name": f"2026010{index}000000",
             "training_status": "SUCCEEDED", "artifact_verified": True,
             "stored_path": str(models[version_id]), "best_path": str(models[version_id]),
             "model_name": "best.pt"}
            for index, version_id in enumerate(("v1", "v2"), start=1)
        ],
        "version_operations": [],
    }])
    return path


def test_deployment_activation_dry_run_is_read_only_and_guards_operations(tmp_path, monkeypatch):
    _wire_app(tmp_path, monkeypatch)
    path = _seed_two_versions(tmp_path)
    service = _service(tmp_path)
    revision_before = algorithm_store_revision(path)
    assert service.repository.summary(project_id="p1")["total"] == 0

    plan = api.v12_deployment_activation_dry_run(
        "p1", "a1", "v2", operation_id="op-activate-1",
        expected_current_version_id="v1",
    )
    assert plan["ok"] is True
    assert plan["schema"] == "deployment-activation-dry-run-v1"
    assert plan["dry_run"] is True and plan["state_unchanged"] is True
    assert plan["would_change_state"] is True
    assert plan["activation_eligible"] is True
    assert plan["current_version_id"] == "v1"
    assert plan["device_calls"] is False and plan["external_platform_calls"] is False
    assert plan["side_effects"] == []
    assert plan["zero_write_assertion"] == "PASSED"
    assertion = plan["read_only_assertion"]
    assert assertion["state_unchanged"] is True
    assert assertion["algorithm_revision_unchanged"] is True
    assert assertion["current_version_unchanged"] is True
    assert assertion["version_rows_unchanged"] is True
    assert assertion["version_operation_rows_unchanged"] is True
    assert assertion["artifact_rows_unchanged"] is True
    assert assertion["before"]["artifact_rows"] == 0
    presentations = {row["target"]: row["delivery_presentation"] for row in plan["artifacts"]}
    assert presentations["original"] == "FORMAL_ACTIVATION"
    assert plan["hardware_acceptance"] == "NOT_VERIFIED"

    # Zero write independently verified after the call.
    algorithms = list_algorithms(path)
    assert algorithms[0]["current_version_id"] == "v1"
    assert algorithm_store_revision(path) == revision_before
    assert _service(tmp_path).repository.summary(project_id="p1")["total"] == 0

    # Late request bound to an obsolete pointer is refused, not replanned.
    stale = api.v12_deployment_activation_dry_run(
        "p1", "a1", "v2", operation_id="op-activate-2",
        expected_current_version_id="v0",
    )
    assert stale["stale_request"] is True
    assert stale["code"] == "ALGORITHM_VERSION_CONFLICT"
    assert stale["would_change_state"] is False
    # Unknown target version returns a readable plan, never a 500/write.
    missing = api.v12_deployment_activation_dry_run("p1", "a1", "v9")
    assert missing["code"] == "ALGORITHM_VERSION_NOT_FOUND"
    assert missing["would_change_state"] is False
    assert list_algorithms(path)[0]["current_version_id"] == "v1"


def test_rollback_dry_run_is_read_only_and_guards_operations(tmp_path, monkeypatch):
    _wire_app(tmp_path, monkeypatch)
    path = _seed_two_versions(tmp_path)
    revision_before = algorithm_store_revision(path)

    plan = api.v12_rollback_dry_run(
        "p1", "a1", "v2", operation_id="op-rollback-1",
        expected_current_version_id="v1",
    )
    assert plan["schema"] == "deployment-rollback-dry-run-v1"
    assert plan["dry_run"] is True and plan["state_unchanged"] is True
    assert plan["current_version_id"] == "v1"
    assert plan["target_version_id"] == "v2"
    assert plan["deleted_version_id"] == "v1"
    assert plan["would_change_state"] is True
    assert plan["remote_delete"] == "DRY_RUN_NOT_PERFORMED"
    assert plan["cleanup"] == "DRY_RUN_NOT_PERFORMED"
    assert plan["hardware_acceptance"] == "NOT_VERIFIED"
    assert plan["side_effects"] == []
    assert plan["zero_write_assertion"] == "PASSED"
    assert plan["read_only_assertion"]["state_unchanged"] is True
    assert all(row["delivery_presentation"] for row in plan["deletion_artifacts"])

    assert list_algorithms(path)[0]["current_version_id"] == "v1"
    assert algorithm_store_revision(path) == revision_before

    current = api.v12_rollback_dry_run(
        "p1", "a1", "v1", operation_id="op-rollback-2",
        expected_current_version_id="v1",
    )
    assert current["code"] == "ALGORITHM_VERSION_ALREADY_CURRENT"
    assert current["idempotent"] is True and current["would_change_state"] is False
    stale = api.v12_rollback_dry_run(
        "p1", "a1", "v2", operation_id="op-rollback-3",
        expected_current_version_id="v0",
    )
    assert stale["stale_request"] is True
    assert stale["code"] == "ALGORITHM_VERSION_CONFLICT"
    missing = api.v12_rollback_dry_run("p1", "a1", "v9")
    assert missing["code"] == "ALGORITHM_VERSION_NOT_FOUND"
    assert list_algorithms(path)[0]["current_version_id"] == "v1"


def test_version_delivery_quality_is_opt_in_read_only_projection(tmp_path, monkeypatch):
    _wire_app(tmp_path, monkeypatch)
    path = _seed_two_versions(tmp_path)
    revision_before = algorithm_store_revision(path)

    # The default asset view keeps its existing no-discovery/no-hashing contract.
    default = api.v12_get_algorithm("p1", "a1", asset_view=True, version_id="v2")
    assert "delivery_quality" not in default

    detail = api.v12_get_algorithm(
        "p1", "a1", asset_view=True, version_id="v2", quality_view=True,
    )
    quality = detail["delivery_quality"]
    assert quality["schema"] == "version-delivery-quality-v1"
    assert quality["device_calls"] is False and quality["external_platform_calls"] is False
    assert quality["numeric_status_alone_is_sufficient"] is False
    assert quality["formal_activation_eligible"] is True
    assert quality["delivery_presentation"] == "FORMAL_ACTIVATION"
    assert quality["hardware_acceptance"] == "NOT_VERIFIED"
    assert quality["present_as_hardware_accepted"] is False
    artifact = quality["artifacts"][0]
    assert artifact["target"] == "original"
    assert artifact["quality_preflight"]["schema"] == "delivery-quality-preflight-v1"
    assert artifact["formal_activation_eligible"] is True
    assert artifact["delivery_presentation"] == "FORMAL_ACTIVATION"
    assert artifact["hardware_acceptance"] == "NOT_VERIFIED"
    # Opt-in projection is still a pure read.
    assert algorithm_store_revision(path) == revision_before
    assert list_algorithms(path)[0]["current_version_id"] == "v1"
    assert _service(tmp_path).repository.summary(project_id="p1")["total"] == 0

    # A version without discovering artifacts fails closed rather than 500.
    empty_projection = api._version_delivery_quality("p1", "a1", "v9")
    assert empty_projection["formal_activation_eligible"] is False
    assert empty_projection["delivery_presentation"] == "UNVERIFIED_ATTACHMENT"
    assert "ALGORITHM_VERSION_NOT_FOUND" in empty_projection["reasons"]


def test_conversion_job_read_projects_delivery_quality_and_keeps_attachment_delivery(
    tmp_path, monkeypatch,
):
    _wire_app(tmp_path, monkeypatch)
    project = _project_dir(tmp_path, "p1")
    job_dir = project / "deployment" / "jobs" / "j1"
    artifacts_dir = job_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)
    model = artifacts_dir / "model.onnx"
    model.write_bytes(b"converted-onnx-bytes")
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    job = {
        "id": "j1", "project_id": "p1", "status": "done", "target": "onnx",
        "hardware_verified": False,
        "outputs": [{
            "name": model.name, "path": str(model), "rel": "artifacts/model.onnx",
            "sha256": digest, "size_bytes": model.stat().st_size,
        }],
    }
    job_file = job_dir / "job.json"
    job_file.write_text(json.dumps(job), encoding="utf-8")
    job_before = job_file.read_bytes()

    service = _service(tmp_path)
    service.repository.upsert({
        "artifact_id": "a-onnx", "project_id": "p1", "algorithm_id": "a1",
        "version_id": "v1", "artifact_kind": "conversion", "target": "onnx",
        "chip_code": "", "conversion_job_id": "j1", "file_name": model.name,
        "source_path": str(model), "sha256": digest, "size_bytes": model.stat().st_size,
        "metadata": {
            # A mutable numeric_status claiming consistency without readable
            # evidence must stay fail-closed.
            "numeric_status": "consistent", "numeric_validation": {},
            "manifest_integrity_status": "unverified",
            "conversion_identity_verified": False, "runtime_verified": False,
            "hardware_verified": False,
        },
    })
    rows_before = len(service.repository.list(project_id="p1", limit=50))

    response = api.v39_get_deploy_job("p1", "j1")
    assert response["id"] == "j1"  # Existing job fields stay at the top level.
    quality = response["delivery_quality"]
    assert quality["schema"] == "conversion-delivery-quality-v1"
    assert quality["device_calls"] is False and quality["external_platform_calls"] is False
    assert quality["formal_activation_eligible"] is False
    assert quality["present_as_formal_activation"] is False
    assert quality["delivery_presentation"] == "UNVERIFIED_ATTACHMENT"
    assert quality["hardware_acceptance"] == "NOT_VERIFIED"
    assert quality["present_as_hardware_accepted"] is False
    assert quality["attachment_delivery_allowed"] is True
    assert quality["archive_download_allowed"] is True
    artifact = quality["artifacts"][0]
    assert artifact["artifact_id"] == "a-onnx"
    assert artifact["formal_activation_eligible"] is False
    assert artifact["delivery_presentation"] == "UNVERIFIED_ATTACHMENT"
    assert artifact["hardware_acceptance"] == "NOT_VERIFIED"
    assert artifact["quality_preflight"]["numeric_status_alone_is_sufficient"] is False
    assert "NUMERIC_EVIDENCE_MISSING" in artifact["quality_preflight"]["reasons"]
    assert "MANIFEST_DIGEST_UNVERIFIED" in artifact["quality_preflight"]["reasons"]
    assert quality["unregistered_outputs"][0]["delivery_presentation"] == "ARCHIVE_DOWNLOAD_ONLY"
    assert quality["unregistered_outputs"][0]["formal_activation_eligible"] is False

    # The read-only projection performed zero writes.
    assert job_file.read_bytes() == job_before
    assert len(_service(tmp_path).repository.list(project_id="p1", limit=50)) == rows_before


def test_conversion_job_read_fails_closed_without_registered_artifacts(tmp_path, monkeypatch):
    _wire_app(tmp_path, monkeypatch)
    project = _project_dir(tmp_path, "p1")
    job_dir = project / "deployment" / "jobs" / "j2"
    artifacts_dir = job_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)
    model = artifacts_dir / "model.engine"
    model.write_bytes(b"engine-bytes")
    (job_dir / "job.json").write_text(json.dumps({
        "id": "j2", "project_id": "p1", "status": "done", "target": "tensorrt",
        "outputs": [{"name": model.name, "path": str(model), "rel": "artifacts/model.engine"}],
    }), encoding="utf-8")

    response = api.v39_get_deploy_job("p1", "j2")
    quality = response["delivery_quality"]
    assert quality["formal_activation_eligible"] is False
    assert quality["delivery_presentation"] == "UNVERIFIED_ATTACHMENT"
    assert "MODEL_ARTIFACT_NOT_REGISTERED" in quality["reasons"]
    # Archive/download of the legal but unregistered output stays allowed.
    assert quality["archive_download_allowed"] is True
    assert quality["unregistered_outputs"][0]["archive_download_allowed"] is True
