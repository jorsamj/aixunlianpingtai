import json
import uuid
from pathlib import Path

import app as platform_app


def test_completed_deployment_artifact_is_listed_downloadable_and_persistent(client, seeded_project):
    project_id, _image = seeded_project
    job_id = f"artifact-{uuid.uuid4().hex[:8]}"
    job_dir = platform_app.deploy_root(project_id) / "jobs" / job_id
    artifacts = job_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    model = artifacts / "model.onnx"
    model.write_bytes(b"real-conversion-output")
    manifest = artifacts / "manifest.json"
    manifest.write_text(json.dumps({"job_id": job_id, "outputs": [{"name": model.name}]}), encoding="utf-8")
    outputs = [
        {"name": model.name, "path": str(model), "rel": "artifacts/model.onnx", "size_mb": 0.001},
        {"name": manifest.name, "path": str(manifest), "rel": "artifacts/manifest.json", "size_mb": 0.001},
    ]
    (job_dir / "job.json").write_text(json.dumps({
        "id": job_id,
        "project_id": project_id,
        "status": "done",
        "target": "onnx",
        "source_name": "best.pt",
        "resource": {"name": "Ultralytics"},
        "params": {"precision": "fp16", "input_size": 640},
        "created_at": "2026-09-13 00:00:00",
        "finished_at": "2026-09-13 00:01:00",
        "outputs": outputs,
    }, ensure_ascii=False), encoding="utf-8")

    response = client.get(f"/api/v39/projects/{project_id}/deploy/artifacts")
    response.raise_for_status()
    items = response.json()["items"]
    item = next(row for row in items if row["job_id"] == job_id and row["name"] == "model.onnx")
    assert item["target"] == "onnx"
    assert item["source_name"] == "best.pt"
    assert item["download_url"]
    download = client.get(item["download_url"])
    assert download.status_code == 200
    assert download.content == b"real-conversion-output"

    # The listing is rebuilt from persisted job metadata + real files, so another API read
    # after in-memory state changes still returns the artifact.
    second = client.get(f"/api/v39/projects/{project_id}/deploy/artifacts")
    second.raise_for_status()
    assert any(row["job_id"] == job_id and row["name"] == "model.onnx" for row in second.json()["items"])


def test_failed_or_missing_deployment_outputs_are_not_exposed_as_artifacts(client, seeded_project):
    project_id, _image = seeded_project
    root = platform_app.deploy_root(project_id) / "jobs"

    failed_id = f"failed-{uuid.uuid4().hex[:8]}"
    failed_dir = root / failed_id
    failed_artifacts = failed_dir / "artifacts"
    failed_artifacts.mkdir(parents=True, exist_ok=True)
    fake = failed_artifacts / "fake.onnx"
    fake.write_bytes(b"must-not-be-listed")
    (failed_dir / "job.json").write_text(json.dumps({
        "id": failed_id, "status": "failed", "target": "onnx",
        "outputs": [{"name": fake.name, "path": str(fake), "rel": "artifacts/fake.onnx"}],
    }), encoding="utf-8")

    missing_id = f"missing-{uuid.uuid4().hex[:8]}"
    missing_dir = root / missing_id
    missing_dir.mkdir(parents=True, exist_ok=True)
    missing_path = missing_dir / "artifacts" / "gone.onnx"
    (missing_dir / "job.json").write_text(json.dumps({
        "id": missing_id, "status": "done", "target": "onnx",
        "outputs": [{"name": "gone.onnx", "path": str(missing_path), "rel": "artifacts/gone.onnx"}],
    }), encoding="utf-8")

    response = client.get(f"/api/v39/projects/{project_id}/deploy/artifacts")
    response.raise_for_status()
    ids = {row["job_id"] for row in response.json()["items"]}
    assert failed_id not in ids
    assert missing_id not in ids
