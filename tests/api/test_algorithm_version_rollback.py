import hashlib
import json
import uuid
from pathlib import Path

import app as app_module
from platform_core.algorithms import save_algorithms


def _create_algorithm(client, project_id: str) -> dict:
    response = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": f"rollback-{uuid.uuid4().hex[:8]}", "algorithm_type": "yolo_ultralytics"},
    )
    response.raise_for_status()
    return response.json()["algorithm"]


def _version(project_id: str, algorithm_id: str, version_id: str, finished_at: str) -> dict:
    folder = app_module.project_dir(project_id) / "algorithm_versions" / algorithm_id / version_id
    folder.mkdir(parents=True, exist_ok=True)
    model = folder / f"{version_id}.pt"
    model.write_bytes(version_id.encode("utf-8"))
    return {
        "id": version_id,
        "version_name": version_id.upper(),
        "finished_at": finished_at,
        "stored_path": str(model),
        "model_name": model.name,
        "artifact_verified": True,
        "training_status": "SUCCEEDED",
        "trainable": True,
        "framework": "ultralytics",
    }


def _seed_versions(project_id: str, algorithm_id: str, *, explicit_current: bool = True) -> tuple[dict, dict]:
    rows = app_module.list_algorithm_assets(app_module.algorithms_file(project_id))
    algorithm = next(row for row in rows if row["id"] == algorithm_id)
    v5 = _version(project_id, algorithm_id, "v5", "2026-09-15T00:00:00+00:00")
    v3 = _version(project_id, algorithm_id, "v3", "2026-09-13T00:00:00+00:00")
    algorithm["versions"] = [v5, v3]
    algorithm.pop("current_version_id", None)
    if explicit_current:
        algorithm["current_version_id"] = "v5"
    save_algorithms(app_module.algorithms_file(project_id), rows)
    return v5, v3


def test_algorithm_list_projects_legacy_current_version_without_persisting_it(client, seeded_project):
    project_id, _ = seeded_project
    algorithm = _create_algorithm(client, project_id)
    _seed_versions(project_id, algorithm["id"], explicit_current=False)

    listed = client.get(f"/api/v12/projects/{project_id}/algorithms")

    assert listed.status_code == 200
    item = next(row for row in listed.json()["items"] if row["id"] == algorithm["id"])
    assert item["current_version_id"] == "v5"
    assert item["current_version_inferred"] is True
    raw = next(
        row for row in app_module.list_algorithm_assets(app_module.algorithms_file(project_id))
        if row["id"] == algorithm["id"]
    )
    assert raw.get("current_version_id") is None


def test_rollback_api_deletes_current_and_iteration_base_uses_target(client, seeded_project, monkeypatch):
    project_id, _ = seeded_project
    algorithm = _create_algorithm(client, project_id)
    _seed_versions(project_id, algorithm["id"])
    monkeypatch.setattr(app_module, "_v54_validate_iteration_artifact", lambda _path, _framework: True)

    response = client.post(
        f"/api/v12/projects/{project_id}/algorithms/{algorithm['id']}/versions/v3/rollback",
        json={"delete_current_version": True, "expected_current_version_id": "v5"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["current_version_id"] == "v3"
    assert response.json()["deleted_version_id"] == "v5"
    base = client.get(
        f"/api/v54/projects/{project_id}/algorithms/{algorithm['id']}/iteration-base?framework=ultralytics"
    )
    assert base.status_code == 200, base.text
    assert base.json()["base"]["version_id"] == "v3"
    stored = next(
        row for row in app_module.list_algorithm_assets(app_module.algorithms_file(project_id))
        if row["id"] == algorithm["id"]
    )
    assert stored["current_version_id"] == "v3"
    assert {row["id"] for row in stored["versions"]} == {"v3"}

    test_models = client.get(
        f"/api/v12/projects/{project_id}/test_models?probe_optional=false"
    )
    assert test_models.status_code == 200, test_models.text
    algorithm_test_models = [
        row for row in test_models.json()["items"]
        if row.get("algorithm_id") == algorithm["id"]
    ]
    assert [row["version_id"] for row in algorithm_test_models] == ["v3"]
    assert algorithm_test_models[0]["is_current_version"] is True

    deploy_sources = client.get(
        f"/api/v39/projects/{project_id}/deploy/source-models"
    )
    assert deploy_sources.status_code == 200, deploy_sources.text
    algorithm_deploy_sources = [
        row for row in deploy_sources.json()["items"]
        if row.get("algorithm_id") == algorithm["id"]
    ]
    assert [row["version_id"] for row in algorithm_deploy_sources] == ["v3"]
    assert algorithm_deploy_sources[0]["is_current_version"] is True


def test_rollback_and_delete_preflight_blocks_active_conversion_before_pointer_change(client, seeded_project):
    project_id, _ = seeded_project
    algorithm = _create_algorithm(client, project_id)
    _seed_versions(project_id, algorithm["id"])
    job_dir = app_module.deploy_root(project_id) / "jobs" / "active-conversion"
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "job.json").write_text(
        json.dumps({
            "id": "active-conversion",
            "status": "running",
            "source_id": f"version::{algorithm['id']}::v5",
            "source_meta": {"algorithm_id": algorithm["id"], "version_id": "v5"},
        }),
        encoding="utf-8",
    )

    response = client.post(
        f"/api/v12/projects/{project_id}/algorithms/{algorithm['id']}/versions/v3/rollback",
        json={"delete_current_version": True, "expected_current_version_id": "v5"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "ALGORITHM_VERSION_IN_USE"
    stored = next(
        row for row in app_module.list_algorithm_assets(app_module.algorithms_file(project_id))
        if row["id"] == algorithm["id"]
    )
    assert stored["current_version_id"] == "v5"
    assert {row["id"] for row in stored["versions"]} == {"v3", "v5"}


def test_rollback_and_delete_blocks_active_rknn_board_validation_by_conversion_lineage(
    client, seeded_project,
):
    project_id, _ = seeded_project
    algorithm = _create_algorithm(client, project_id)
    _seed_versions(project_id, algorithm["id"])

    conversion_id = f"convert-{uuid.uuid4().hex[:8]}"
    conversion_dir = app_module.deploy_root(project_id) / "jobs" / conversion_id
    artifacts_dir = conversion_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    model = artifacts_dir / "model_rk3568.rknn"
    model.write_bytes(b"rknn-model")
    (conversion_dir / "job.json").write_text(
        json.dumps({
            "id": conversion_id,
            "status": "done",
            "source_id": f"version::{algorithm['id']}::v5",
            "source_trace": {
                "algorithm_id": algorithm["id"],
                "version_id": "v5",
            },
            "target": "rockchip",
            "params": {"chip": "rk3568", "precision": "fp16"},
        }),
        encoding="utf-8",
    )

    task_id = f"board-{uuid.uuid4().hex[:8]}"
    app_module.shared_task_artifacts().atomic_write_json(
        task_id,
        "request.json",
        {
            "execution_mode": "agent",
            "framework": "rknn",
            "runtime_format": "rknn",
            "source_conversion_job_id": conversion_id,
            "model_path": str(model),
            "remote_execution": {
                "version": 1,
                "task_kind": "DEPLOYMENT_TEST",
                "transport": "object-storage-v1",
                "deployment": {
                    "runtime_format": "rknn",
                    "board": {
                        "conversion_job_id": conversion_id,
                        "chip": "rk3568",
                    },
                },
            },
        },
    )
    app_module.shared_task_repository().create(
        app_module.TaskRecord.new(
            task_id,
            project_id,
            app_module.TaskKind.DEPLOYMENT_TEST,
            "request.json",
            "deployment-rknn-board:rk3568",
            required_capabilities=("agent.remote",),
        ),
        artifacts=app_module.shared_task_artifacts(),
    )

    response = client.post(
        f"/api/v12/projects/{project_id}/algorithms/{algorithm['id']}/versions/v3/rollback",
        json={"delete_current_version": True, "expected_current_version_id": "v5"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ALGORITHM_VERSION_IN_USE"
    assert "板端验证" in response.json()["detail"]
    stored = next(
        row for row in app_module.list_algorithm_assets(app_module.algorithms_file(project_id))
        if row["id"] == algorithm["id"]
    )
    assert stored["current_version_id"] == "v5"
    assert {row["id"] for row in stored["versions"]} == {"v3", "v5"}


def test_rollback_and_delete_removes_only_owned_version_folder_and_keeps_training_history(client, seeded_project):
    project_id, _ = seeded_project
    algorithm = _create_algorithm(client, project_id)
    v5, _ = _seed_versions(project_id, algorithm["id"])
    history_dir = app_module.project_dir(project_id) / "jobs" / "historical-training"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_file = history_dir / "job.json"
    history_file.write_text(
        json.dumps({"id": "historical-training", "status": "done", "asset_algorithm_id": algorithm["id"], "base_version_id": "v5"}),
        encoding="utf-8",
    )

    response = client.post(
        f"/api/v12/projects/{project_id}/algorithms/{algorithm['id']}/versions/v3/rollback",
        json={"delete_current_version": True, "expected_current_version_id": "v5"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] == "rollback_and_delete"
    assert body["cleanup_status"] == "cleanup_completed"
    assert not Path(v5["stored_path"]).parent.exists()
    assert history_file.exists()
    stored = next(
        row for row in app_module.list_algorithm_assets(app_module.algorithms_file(project_id))
        if row["id"] == algorithm["id"]
    )
    assert stored["current_version_id"] == "v3"
    assert [row["id"] for row in stored["versions"]] == ["v3"]
    assert stored["version_operations"][-1]["cleanup_status"] == "cleanup_completed"


def test_rollback_retires_rknn_board_result_output_with_legacy_upload_evidence(
    client, seeded_project, monkeypatch,
):
    project_id, _ = seeded_project
    algorithm = _create_algorithm(client, project_id)
    _seed_versions(project_id, algorithm["id"])

    task_id = f"board-retire-{uuid.uuid4().hex[:8]}"
    generation = 2
    source_id = "remote-models"
    result_bytes = b"board-result-image"
    result_sha = hashlib.sha256(result_bytes).hexdigest()
    result_key = (
        f"remote-execution/{project_id}/{task_id}/"
        f"rknn-board-output/generation-{generation}/result.jpg"
    )

    class FakeMetadata:
        size_bytes = len(result_bytes)
        sha256 = result_sha

    class FakeProvider:
        def __init__(self):
            self.objects = {result_key}
            self.deleted = []

        def exists(self, key):
            return str(key) in self.objects

        def stat(self, key):
            assert str(key) == result_key
            return FakeMetadata()

        def delete(self, key):
            self.deleted.append(str(key))
            self.objects.discard(str(key))

    provider = FakeProvider()
    monkeypatch.setattr(
        app_module,
        "_version_cleanup_storage_provider",
        lambda pid, ref: provider,
    )

    conversion_id = f"convert-retire-{uuid.uuid4().hex[:8]}"
    job_dir = app_module.deploy_root(project_id) / "jobs" / conversion_id
    artifacts_dir = job_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    verification = {
        "task_id": task_id,
        "execution_generation": generation,
        "node_id": "rk3568-board-01",
        "chip": "rk3568",
        "engine": "rknn-lite2",
        "model_sha256": "b" * 64,
        "model_size_bytes": 123,
        "input": {
            "file_name": "verify.jpg",
            "sha256": "c" * 64,
            "size_bytes": 456,
        },
        # Legacy pre-42.24.101 evidence intentionally lacks size/SHA256 here.
        "result_output_storage": {
            "storage_source_id": source_id,
            "object_key": result_key,
            "file_name": "result.jpg",
            "content_type": "image/jpeg",
        },
    }
    job = {
        "id": conversion_id,
        "status": "done",
        "source_id": f"version::{algorithm['id']}::v5",
        "source_trace": {
            "algorithm_id": algorithm["id"],
            "version_id": "v5",
        },
        "target": "rockchip",
        "params": {"chip": "rk3568", "precision": "fp16"},
        "hardware_verified": True,
        "validation_status": "hardware_verified",
        "hardware_verification": verification,
        "outputs": [],
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    (artifacts_dir / "manifest.json").write_text(
        json.dumps({
            "status": "hardware_verified",
            "hardware_verified": True,
            "hardware_verification": verification,
        }),
        encoding="utf-8",
    )
    app_module.shared_task_artifacts().atomic_write_json(
        task_id,
        f"remote-results/{generation}/upload.json",
        {
            "execution_generation": generation,
            "storage_ref": {
                "storage_source_id": source_id,
                "object_key": result_key,
                "file_name": "result.jpg",
            },
            "sha256": result_sha,
            "size_bytes": len(result_bytes),
        },
    )

    response = client.post(
        f"/api/v12/projects/{project_id}/algorithms/{algorithm['id']}/versions/v3/rollback",
        json={"delete_current_version": True, "expected_current_version_id": "v5"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cleanup_status"] == "cleanup_completed"
    assert provider.deleted == [result_key]
    assert not provider.exists(result_key)
    assert any(result_key in target for target in body["cleanup_targets"])

    retired_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    retired_ref = retired_job["hardware_verification"]["result_output_storage"]
    assert retired_ref["available"] is False
    assert retired_ref["sha256"] == result_sha
    assert retired_ref["size_bytes"] == len(result_bytes)
    assert retired_ref["deleted_with_version_at"]
    assert retired_job["source_version_status"] == "deleted"

    retired_manifest = json.loads(
        (artifacts_dir / "manifest.json").read_text(encoding="utf-8")
    )
    manifest_ref = retired_manifest["hardware_verification"]["result_output_storage"]
    assert manifest_ref["available"] is False
    assert manifest_ref["sha256"] == result_sha
    assert manifest_ref["size_bytes"] == len(result_bytes)
    assert retired_manifest["hardware_verification"]["task_id"] == task_id


def test_direct_delete_api_rejects_current_version(client, seeded_project):
    project_id, _ = seeded_project
    algorithm = _create_algorithm(client, project_id)
    _seed_versions(project_id, algorithm["id"])

    response = client.delete(
        f"/api/v12/projects/{project_id}/algorithms/{algorithm['id']}/versions/v5"
    )

    assert response.status_code == 409
    assert response.json()["code"] == "ALGORITHM_CURRENT_VERSION_DELETE_FORBIDDEN"


def test_rollback_delete_preserves_directory_used_by_target_version(client, seeded_project):
    project_id, _ = seeded_project
    algorithm = _create_algorithm(client, project_id)
    v5, v3 = _seed_versions(project_id, algorithm["id"])
    shared_root = Path(v5["stored_path"]).parent
    target_model = shared_root / "target-v3.pt"
    target_model.write_bytes(b"target-v3")
    rows = app_module.list_algorithm_assets(app_module.algorithms_file(project_id))
    stored_algorithm = next(row for row in rows if row["id"] == algorithm["id"])
    next(row for row in stored_algorithm["versions"] if row["id"] == "v3")["stored_path"] = str(target_model)
    save_algorithms(app_module.algorithms_file(project_id), rows)

    response = client.post(
        f"/api/v12/projects/{project_id}/algorithms/{algorithm['id']}/versions/v3/rollback",
        json={"delete_current_version": True, "expected_current_version_id": "v5"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["cleanup_status"] == "cleanup_failed"
    assert shared_root.exists()
    assert target_model.exists()



def test_rollback_cleanup_failure_can_retry_without_recreating_deleted_version(
    client, seeded_project, monkeypatch,
):
    project_id, _ = seeded_project
    algorithm = _create_algorithm(client, project_id)
    _seed_versions(project_id, algorithm["id"])
    calls = {"artifacts": 0, "publications": 0}

    def purge_version(_self, pid, aid, vid):
        assert (pid, aid, vid) == (project_id, algorithm["id"], "v5")
        calls["artifacts"] += 1
        if calls["artifacts"] == 1:
            raise PermissionError("temporary object delete failure")
        return {"artifacts_deleted": 1, "remote_objects_deleted": 1}

    def delete_publication_version(_self, pid, aid, vid, **_kwargs):
        assert (pid, aid, vid) == (project_id, algorithm["id"], "v5")
        calls["publications"] += 1
        return {
            "publications_deleted": 1,
            "legacy_artifacts_deleted": 0,
            "artifact_mappings_deleted": 1,
        }

    monkeypatch.setattr(app_module.ModelArtifactService, "purge_version", purge_version)
    monkeypatch.setattr(
        app_module.ExternalPublicationRepository,
        "delete_version",
        delete_publication_version,
    )

    first = client.post(
        f"/api/v12/projects/{project_id}/algorithms/{algorithm['id']}/versions/v3/rollback",
        json={"delete_current_version": True, "expected_current_version_id": "v5"},
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["cleanup_status"] == "cleanup_failed"
    assert calls == {"artifacts": 1, "publications": 0}

    stored = next(
        row for row in app_module.list_algorithm_assets(app_module.algorithms_file(project_id))
        if row["id"] == algorithm["id"]
    )
    assert [row["id"] for row in stored["versions"]] == ["v3"]
    operation = stored["version_operations"][-1]
    assert operation["cleanup_version"]["id"] == "v5"
    operation_id = operation["id"]

    retried = client.post(
        f"/api/v12/projects/{project_id}/algorithms/{algorithm['id']}/version-operations/{operation_id}/retry-cleanup"
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["cleanup_status"] == "cleanup_completed"
    assert retried.json()["already_completed"] is False
    assert calls == {"artifacts": 2, "publications": 1}

    repeated = client.post(
        f"/api/v12/projects/{project_id}/algorithms/{algorithm['id']}/version-operations/{operation_id}/retry-cleanup"
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["cleanup_status"] == "cleanup_completed"
    assert repeated.json()["already_completed"] is True
    assert calls == {"artifacts": 2, "publications": 1}


def test_rollback_cleanup_purges_deleted_version_delivery_state_only(
    client, seeded_project, monkeypatch,
):
    project_id, _ = seeded_project
    algorithm = _create_algorithm(client, project_id)
    _seed_versions(project_id, algorithm["id"])
    monkeypatch.setattr(
        app_module, "_v54_validate_iteration_artifact",
        lambda _path, _framework: True,
    )

    calls = {"artifacts": [], "publications": []}

    def purge_version(_self, pid, aid, vid):
        calls["artifacts"].append((pid, aid, vid))
        return {"artifacts_deleted": 2, "remote_objects_deleted": 2}

    def delete_publication_version(_self, pid, aid, vid, **_kwargs):
        calls["publications"].append((pid, aid, vid))
        return {
            "publications_deleted": 1,
            "legacy_artifacts_deleted": 0,
            "artifact_mappings_deleted": 2,
        }

    monkeypatch.setattr(
        app_module.ModelArtifactService,
        "purge_version",
        purge_version,
    )
    monkeypatch.setattr(
        app_module.ExternalPublicationRepository,
        "delete_version",
        delete_publication_version,
    )

    response = client.post(
        f"/api/v12/projects/{project_id}/algorithms/{algorithm['id']}/versions/v3/rollback",
        json={
            "delete_current_version": True,
            "expected_current_version_id": "v5",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["cleanup_status"] == "cleanup_completed"
    assert calls["artifacts"] == [(project_id, algorithm["id"], "v5")]
    assert calls["publications"] == [(project_id, algorithm["id"], "v5")]
    stored = next(
        row
        for row in app_module.list_algorithm_assets(
            app_module.algorithms_file(project_id)
        )
        if row["id"] == algorithm["id"]
    )
    assert stored["current_version_id"] == "v3"
    assert [row["id"] for row in stored["versions"]] == ["v3"]
