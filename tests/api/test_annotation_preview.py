"""The optional AI preview uses the durable inference contract without writes."""
import app as app_module
from platform_core import annotation_runtime, annotation_task_service
from platform_core.task_runtime import ArtifactStore, TaskRepository


def test_one_image_preview_reuses_inference_without_creating_candidates_or_gt(
    client, seeded_project, monkeypatch, tmp_path,
):
    project_id, image = seeded_project
    repository = TaskRepository(tmp_path / "preview-tasks.sqlite3")
    monkeypatch.setattr(app_module, "_SHARED_TASK_REPOSITORY", repository)
    monkeypatch.setattr(app_module, "_SHARED_TASK_ARTIFACTS", ArtifactStore(tmp_path / "preview-artifacts"))
    source = tmp_path / "preview.jpg"
    source.write_bytes(b"bounded-image")
    observed = []

    def freeze(project, payload):
        observed.append(("freeze", project, list(payload.image_ids), payload.labels_text))
        return {"image_ids": list(payload.image_ids), "labels": ["fire"]}, "model-1"

    def runtime(root, project, request, *, runtime):
        observed.append(("runtime", project, runtime, list(request["image_ids"])))
        return {"_provider": object(), "label_ids": {"fire": 0}}

    def resolve(project, ids):
        observed.append(("source", project, list(ids)))
        return [{"id": image["id"], "filename": "scene.jpg", "url": "/media/scene.jpg",
                 "width": 640, "height": 480, "path": str(source)}]

    def infer(request, row):
        observed.append(("infer", row["id"], sorted(request["label_ids"])))
        return {"boxes": [{"label": "fire", "confidence": 0.93, "x1": 1, "y1": 2, "x2": 40, "y2": 50}],
                "latency_ms": 145, "model": "vision-1", "provider": "local"}

    monkeypatch.setattr(app_module, "_annotation_create_payload", freeze)
    monkeypatch.setattr(annotation_runtime, "prepare_request", runtime)
    monkeypatch.setattr(annotation_task_service, "load_task_images", resolve)
    monkeypatch.setattr(annotation_task_service, "annotate_one", infer)
    monkeypatch.setattr(app_module, "write_annotation", lambda *args, **kwargs: 1 / 0)
    response = client.post(f"/api/v60/projects/{project_id}/annotation-preview", json={
        "image_ids": [image["id"]], "labels_text": "fire", "model_config_id": "model-1",
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["preview_only"] is True
    assert result["image"]["id"] == image["id"]
    assert result["image"]["url"] == "/media/scene.jpg"
    assert result["boxes"][0]["label"] == "fire"
    assert result["latency_ms"] == 145
    assert [row[0] for row in observed] == ["freeze", "runtime", "source", "infer"]
    assert not repository.list(project_id=project_id).items
    assert not list((tmp_path / "preview-artifacts").iterdir())


def test_preview_rejects_multi_image_and_unknown_image_before_model_call(
    client, seeded_project, monkeypatch,
):
    project_id, image = seeded_project
    monkeypatch.setattr(app_module, "_annotation_create_payload", lambda *args: 1 / 0)
    path = f"/api/v60/projects/{project_id}/annotation-preview"
    multi = client.post(path, json={"image_ids": [image["id"], "another"], "labels_text": "fire"})
    assert multi.status_code == 422
    unknown = client.post(path, json={"image_ids": ["does-not-exist"], "labels_text": "fire"})
    assert unknown.status_code == 409


def test_preview_rejects_oversized_material_before_materializing(
    client, seeded_project, monkeypatch,
):
    project_id, image = seeded_project

    class BigMaterial:
        def get_many(self, ids):
            return [{"id": image["id"], "size_bytes": 16 * 1024 * 1024 + 1}]

    monkeypatch.setattr(app_module, "material_store", lambda *_: BigMaterial())
    monkeypatch.setattr(app_module, "_annotation_create_payload", lambda *args: 1 / 0)
    result = client.post(f"/api/v60/projects/{project_id}/annotation-preview", json={
        "image_ids": [image["id"]], "labels_text": "fire",
    })
    assert result.status_code == 413


def test_preview_redacts_provider_exceptions(client, seeded_project, monkeypatch, tmp_path):
    project_id, image = seeded_project
    source = tmp_path / "source.jpg"
    source.write_bytes(b"safe")
    monkeypatch.setattr(app_module, "_annotation_create_payload", lambda *args: ({"image_ids": [image["id"]]}, "provider"))
    monkeypatch.setattr(annotation_runtime, "prepare_request", lambda *args, **kwargs: {})
    monkeypatch.setattr(annotation_task_service, "load_task_images", lambda *args: [{"id": image["id"], "path": str(source)}])
    monkeypatch.setattr(annotation_task_service, "annotate_one", lambda *args: (_ for _ in ()).throw(RuntimeError("Authorization: Bearer sk-test-secret")))
    result = client.post(f"/api/v60/projects/{project_id}/annotation-preview", json={
        "image_ids": [image["id"]], "labels_text": "fire",
    })
    assert result.status_code == 502
    assert "sk-test-secret" not in result.text
