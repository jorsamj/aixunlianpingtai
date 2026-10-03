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
