import app as app_module

from platform_core.annotation_task_service import AnnotationHandler
from platform_core.task_runtime import ArtifactStore, Scheduler, TaskKind, TaskRepository


class FakeVisionProvider:
    def annotate(self, *, image_bytes, prompt, output_schema):
        assert image_bytes and "fire" in prompt and output_schema["required"] == ["boxes"]
        return {
            "text": '{"boxes":[{"label":"fire","confidence":0.97,"x1":10,"y1":10,"x2":80,"y2":80}]}',
            "request_id": "persistent-e2e",
            "latency_ms": 7,
            "provider": "fake",
            "model": "fake-vlm",
        }


def test_persistent_ai_task_generates_review_then_commits_formal_annotation(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, image = seeded_project
    external_root = tmp_path / "annotation-source"
    (external_root / "incoming").mkdir(parents=True)
    source_id = "annotation_external"
    source_response = client.post(
        "/api/v61/storage-sources",
        json={
            "id": source_id,
            "name": "Annotation external",
            "type": "local",
            "config": {"root": str(external_root)},
        },
    )
    assert source_response.status_code == 201, source_response.text
    source_path = app_module.project_dir(project_id) / "uploads" / image["stored_name"]
    object_key = f"incoming/{image['stored_name']}"
    source_path.replace(external_root / object_key)
    app_module.material_store(project_id).patch(
        {
            image["id"]: {
                "storage_source_id": source_id,
                "storage_type": "local",
                "object_key": object_key,
            }
        }
    )
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    monkeypatch.setattr(app_module, "_SHARED_TASK_REPOSITORY", repository)
    monkeypatch.setattr(app_module, "_SHARED_TASK_ARTIFACTS", artifacts)
    monkeypatch.setattr("platform_core.auto_label.provider_factory", lambda _value: FakeVisionProvider())

    created = client.post(f"/api/v60/projects/{project_id}/annotation-tasks", json={
        "image_ids": [image["id"]],
        "labels_text": "fire",
        "provider_id": "fake-provider",
        "prompt_template_id": "default",
    })
    assert created.status_code == 202, created.text
    task_id = created.json()["id"]

    scheduler = Scheduler(
        repository,
        artifacts,
        "annotation-e2e-worker",
        {TaskKind.AI_ANNOTATION: AnnotationHandler()},
        {"vision_provider"},
        lease_seconds=10,
    )
    assert scheduler.run_once() is True
    waiting = client.get(f"/api/v60/projects/{project_id}/annotation-tasks/{task_id}").json()
    assert waiting["status"] == "AWAITING_CONFIRMATION"
    assert waiting["progress"] == 100
    assert waiting["summary"]["boxes"] == 1
    assert client.get(f"/api/projects/{project_id}/annotations/{image['id']}").json()["boxes"] == []

    candidates = client.get(
        f"/api/v60/projects/{project_id}/annotation-tasks/{task_id}/candidates"
    ).json()["items"]
    accepted = client.post(
        f"/api/v60/projects/{project_id}/annotation-tasks/{task_id}/decisions",
        json={
            "decisions": [{"image_id": image["id"], "accepted": True}],
            "reject_unmentioned": True,
            "commit": True,
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["task"]["status"] == "SUCCEEDED"
    assert candidates[0]["request_id"] == "persistent-e2e"
    formal = client.get(f"/api/projects/{project_id}/annotations/{image['id']}").json()["boxes"]
    assert len(formal) == 1
    assert formal[0]["source"] == "ai_candidate_confirmed"
    assert formal[0]["source_task_id"] == task_id
    assert not source_path.exists()
