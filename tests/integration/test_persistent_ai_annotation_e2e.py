import pytest
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
    monkeypatch.setattr(app_module, "_v35_model_items", lambda: [{
        "id": "fake-model-config",
        "name": "Fake Vision",
        "model_name": "fake-vlm",
        "provider_type": "local_openai",
        "provider_adapter": "local_openai",
        "detect_url": "http://fake-vision.local/v1",
    }])
    monkeypatch.setattr(
        "platform_core.annotation_runtime.provider_factory",
        lambda _value: FakeVisionProvider(),
    )

    created = client.post(f"/api/v60/projects/{project_id}/annotation-tasks", json={
        "image_ids": [image["id"]],
        "labels_text": "fire",
        "model_config_id": "fake-model-config",
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
    assert waiting["progress"] == 70
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
            "label_mapping": {"fire": "smoke"},
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["queued_for_commit"] is True
    assert accepted.json()["task"]["status"] == "QUEUED"
    assert accepted.json()["task"]["stage"] == "review_queued"
    assert client.get(f"/api/projects/{project_id}/annotations/{image['id']}").json()["boxes"] == []
    assert scheduler.run_once() is True
    finished = client.get(f"/api/v60/projects/{project_id}/annotation-tasks/{task_id}").json()
    assert finished["status"] == "SUCCEEDED"
    assert candidates[0]["request_id"] == "persistent-e2e"
    formal = client.get(f"/api/projects/{project_id}/annotations/{image['id']}").json()["boxes"]
    assert len(formal) == 1
    assert formal[0]["source"] == "ai_candidate_confirmed"
    assert formal[0]["source_task_id"] == task_id
    assert formal[0]["label"] == "smoke"
    assert formal[0]["class_id"] == 1
    labels = client.get(f"/api/v12/projects/{project_id}/labels").json()["items"]
    smoke = next(row for row in labels if row["code"] == "smoke")
    assert "fire" not in smoke["aliases"]
    assert not source_path.exists()


@pytest.mark.parametrize("mode", ["valid", "invalid_label", "incomplete"])
def test_responses_connection_and_formal_task_share_real_adapter_and_gt_gate(client, seeded_project, tmp_path, monkeypatch, mode):
    from types import SimpleNamespace
    import platform_core.providers.openai_vision as vision
    pid, image = seeded_project
    repository = TaskRepository(tmp_path / "protocol-tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "protocol-artifacts")
    monkeypatch.setattr(app_module, "_SHARED_TASK_REPOSITORY", repository)
    monkeypatch.setattr(app_module, "_SHARED_TASK_ARTIFACTS", artifacts)
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        label = "fire" if mode != "invalid_label" else "not-in-catalog"
        text = '{"boxes":[{"label":"'+label+'","confidence":0.99,"x1":0.1,"y1":0.1,"x2":0.8,"y2":0.8}]}'
        payload = {"id":"resp-mock", "status":"incomplete" if mode == "incomplete" else "completed", "output":[{"type":"reasoning","summary":[{"text":"ignore"}]},{"type":"message","role":"assistant","status":"completed","content":[{"type":"output_text","text":text}]}]}
        return SimpleNamespace(status_code=200, ok=True, headers={"x-request-id":"req-mock"}, json=lambda:payload)
    monkeypatch.setattr(vision.requests, "post", post)
    saved = client.post("/api/v35/model-configs", json={"name":"Responses HTTP mock", "provider_type":"volcengine_ark", "model_kind":"vlm", "api_protocol":"responses", "base_url":"https://ark.cn-beijing.volces.com/api/v3", "model_name":"glm-5-3-flash-260828"}).json()
    before = client.get(f"/api/projects/{pid}/annotations/{image['id']}").json()
    tested = client.post(f"/api/v35/model-configs/{saved['id']}/test-annotation")
    assert tested.status_code == (200 if mode == "valid" else 400), tested.text
    if mode == "valid":
        assert tested.json()["api_protocol"] == "responses"
        assert tested.json()["request_id"] == "req-mock"
    else:
        assert tested.json()["code"] in {"MODEL_OUTPUT_PARSE_ERROR", "MODEL_OUTPUT_INCOMPLETE"}
    created = client.post(f"/api/v60/projects/{pid}/annotation-tasks", json={"image_ids":[image["id"]], "labels_text":"fire", "model_config_id":saved["id"], "preview_count":1})
    assert created.status_code == 202, created.text
    task_id = created.json()["id"]
    frozen = artifacts.read_json(task_id, "request.json")
    assert frozen["model_config_snapshot"]["api_protocol"] == "responses"
    scheduler = Scheduler(repository, artifacts, "protocol-worker", {TaskKind.AI_ANNOTATION:AnnotationHandler()}, {"vision_provider"}, lease_seconds=10)
    assert scheduler.run_once()
    completed = client.get(f"/api/v60/projects/{pid}/annotation-tasks/{task_id}").json()
    assert completed["status"] == ("AWAITING_CONFIRMATION" if mode == "valid" else "FAILED")
    assert calls and len(calls) == 2
    for url, body in calls:
        assert url == "https://ark.cn-beijing.volces.com/api/v3/responses"
        assert body["input"][0]["content"][1]["type"] == "input_image" and "messages" not in body
    assert client.get(f"/api/projects/{pid}/annotations/{image['id']}").json() == before
    row = client.get(f"/api/v60/projects/{pid}/annotation-tasks/{task_id}/candidates").json()["items"][0]
    assert row["status"] == ("success" if mode == "valid" else "failed")
    assert len(row["boxes"]) == (1 if mode == "valid" else 0)
    if mode != "valid":
        rejected = client.post(f"/api/v60/projects/{pid}/annotation-tasks/{task_id}/decisions", json={"decisions":[{"image_id":image["id"], "accepted":True}], "commit":True})
        assert rejected.status_code in {400,409}
        assert client.get(f"/api/projects/{pid}/annotations/{image['id']}").json() == before
