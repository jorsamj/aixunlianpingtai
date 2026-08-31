import uuid

import pytest

import app as app_module
from platform_core.annotation_candidates import CandidateStore
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository, TaskStatus


@pytest.fixture(autouse=True)
def isolated_task_runtime(tmp_path, monkeypatch):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    monkeypatch.setattr(app_module, "_SHARED_TASK_REPOSITORY", repository)
    monkeypatch.setattr(app_module, "_SHARED_TASK_ARTIFACTS", artifacts)
    return repository, artifacts


def _queued(project_id, repository, artifacts):
    task_id = uuid.uuid4().hex[:12]
    artifacts.atomic_write_json(task_id, "request.json", {"image_ids": ["x"], "labels": ["fire"]})
    repository.create(TaskRecord.new(
        task_id, project_id, TaskKind.AI_ANNOTATION, "request.json", f"vision:{task_id}",
        required_capabilities=("vision_provider",),
    ))
    return task_id


def _awaiting(project_id, count, repository, artifacts):
    task_id = _queued(project_id, repository, artifacts)
    store = CandidateStore(artifacts, task_id=task_id, page_size=50)
    store.initialize(labels=["fire"], total_images=count)
    store.append_items([
        {"image_id": f"image-{index}", "status": "empty", "boxes": []}
        for index in range(count)
    ])
    lease = repository.claim_next("test-worker", {TaskKind.AI_ANNOTATION}, {"vision_provider"})
    assert lease and lease.task.task_id == task_id
    repository.finish(task_id, lease.lease_token, TaskStatus.AWAITING_CONFIRMATION, "candidates/manifest.json")
    return task_id


def test_annotation_task_create_is_private_and_worker_queued(client, seeded_project, isolated_task_runtime):
    project_id, image = seeded_project
    response = client.post(f"/api/v60/projects/{project_id}/annotation-tasks", json={
        "image_ids": [image["id"]], "labels_text": "fire", "provider_id": "fake-provider",
        "business_instruction": "find fire",
    })
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "QUEUED"
    assert body["total_count"] == 1
    assert body["completed_count"] == 0
    assert body["failed_count"] == 0
    assert "payload_ref" not in body and "business_instruction" not in body
    request = isolated_task_runtime[1].read_json(body["id"], "request.json")
    assert request["image_ids"] == [image["id"]]


def test_annotation_task_detail_reads_real_worker_checkpoint_counts(client, seeded_project, isolated_task_runtime):
    project_id, _image = seeded_project
    repository, artifacts = isolated_task_runtime
    task_id = _queued(project_id, repository, artifacts)
    artifacts.atomic_write_json(task_id, "request.json", {"image_ids": ["a", "b", "c"], "labels": ["fire"]})
    artifacts.atomic_write_json(task_id, "checkpoints/worker.json", {"next_index": 2, "succeeded": 1, "failed": 1})
    response = client.get(f"/api/v60/projects/{project_id}/annotation-tasks/{task_id}")
    assert response.status_code == 200
    assert response.json()["total_count"] == 3
    assert response.json()["completed_count"] == 2
    assert response.json()["failed_count"] == 1


def test_annotation_task_list_is_bounded_and_private_fields_are_absent(client, seeded_project, isolated_task_runtime):
    project_id, _image = seeded_project
    repository, artifacts = isolated_task_runtime
    for _ in range(25):
        _queued(project_id, repository, artifacts)
    response = client.get(f"/api/v60/projects/{project_id}/annotation-tasks?limit=20")
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 20
    forbidden = {"request_payload", "payload_ref", "candidate_file", "video_path", "api_key", "secret_ref"}
    assert all(forbidden.isdisjoint(item) for item in body["items"])


def test_candidate_result_is_paged_and_all_rejected_remains_false(client, seeded_project, isolated_task_runtime):
    project_id, _image = seeded_project
    repository, artifacts = isolated_task_runtime
    task_id = _awaiting(project_id, 55, repository, artifacts)
    first = client.get(f"/api/v60/projects/{project_id}/annotation-tasks/{task_id}/candidates?limit=50")
    assert first.status_code == 200, first.text
    assert len(first.json()["items"]) == 50
    assert first.json()["next_cursor"] == "50"
    second = client.get(
        f"/api/v60/projects/{project_id}/annotation-tasks/{task_id}/candidates?limit=50&cursor=50"
    ).json()
    assert len(second["items"]) == 5
    rejected = client.post(
        f"/api/v60/projects/{project_id}/annotation-tasks/{task_id}/decisions",
        json={"decisions": [], "reject_unmentioned": True, "commit": True},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["review"]["accepted"] == 0
    assert rejected.json()["review"]["rejected"] == 55
    assert rejected.json()["task"]["accepted"] is False
    reloaded = client.get(
        f"/api/v60/projects/{project_id}/annotation-tasks/{task_id}/candidates?limit=50"
    ).json()
    assert all(item["accepted"] is False for item in reloaded["items"])


def test_candidate_result_can_accept_every_page_without_sending_all_ids(client, seeded_project, isolated_task_runtime):
    project_id, _image = seeded_project
    repository, artifacts = isolated_task_runtime
    task_id = _awaiting(project_id, 55, repository, artifacts)
    accepted = client.post(
        f"/api/v60/projects/{project_id}/annotation-tasks/{task_id}/decisions",
        json={"decisions": [], "accept_unmentioned": True, "reject_unmentioned": False, "commit": True},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["review"]["accepted"] == 55
    assert accepted.json()["review"]["unreviewed"] == 0
    assert accepted.json()["task"]["accepted"] is True


def test_cancel_and_retry_use_shared_runtime_states(client, seeded_project, isolated_task_runtime):
    project_id, _image = seeded_project
    repository, artifacts = isolated_task_runtime
    task_id = _queued(project_id, repository, artifacts)
    cancelled = client.post(f"/api/v60/projects/{project_id}/annotation-tasks/{task_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    retried = client.post(f"/api/v60/projects/{project_id}/annotation-tasks/{task_id}/retry")
    assert retried.status_code == 200, retried.text
    assert retried.json()["id"] != task_id
    assert retried.json()["retry_of"] == task_id
    assert retried.json()["status"] == "QUEUED"
