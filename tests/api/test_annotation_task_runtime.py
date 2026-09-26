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


def test_material_state_projection_distinguishes_pending_review_from_commit(client, seeded_project, isolated_task_runtime):
    project_id, _image = seeded_project
    repository, artifacts = isolated_task_runtime
    task_id = _awaiting(project_id, 2, repository, artifacts)

    pending = client.get(
        f"/api/v60/projects/{project_id}/annotation-material-states"
        "?image_ids=image-0,image-1,missing"
    )
    assert pending.status_code == 200, pending.text
    assert pending.json()["items"] == [
        {"image_id": "image-0", "state": "awaiting_confirmation", "task_id": task_id},
        {"image_id": "image-1", "state": "awaiting_confirmation", "task_id": task_id},
    ]

    accepted = client.post(
        f"/api/v60/projects/{project_id}/annotation-tasks/{task_id}/decisions",
        json={
            "decisions": [{"image_id": "image-0", "accepted": True}],
            "reject_unmentioned": True,
            "accept_unmentioned": False,
            "commit": True,
        },
    )
    assert accepted.status_code == 200, accepted.text
    committing = client.get(
        f"/api/v60/projects/{project_id}/annotation-material-states"
        "?image_ids=image-0,image-1"
    )
    assert committing.status_code == 200, committing.text
    assert committing.json()["items"] == [
        {"image_id": "image-0", "state": "committing", "task_id": task_id},
    ]


def test_material_state_projection_is_bounded(client, seeded_project):
    project_id, _image = seeded_project
    image_ids = ",".join(f"image-{index}" for index in range(101))
    response = client.get(
        f"/api/v60/projects/{project_id}/annotation-material-states?image_ids={image_ids}"
    )
    assert response.status_code == 422


def test_material_state_projection_filters_terminal_task_history(client, seeded_project, isolated_task_runtime):
    project_id, _image = seeded_project
    repository, artifacts = isolated_task_runtime
    pending_id = _awaiting(project_id, 1, repository, artifacts)
    for index in range(105):
        task_id = _queued(project_id, repository, artifacts)
        lease = repository.claim_next(
            f"terminal-worker-{index}", {TaskKind.AI_ANNOTATION}, {"vision_provider"}
        )
        assert lease is not None
        repository.finish(task_id, lease.lease_token, TaskStatus.FAILED, error="historical failure")
    response = client.get(
        f"/api/v60/projects/{project_id}/annotation-material-states?image_ids=image-0"
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"] == [
        {"image_id": "image-0", "state": "awaiting_confirmation", "task_id": pending_id},
    ]


def test_material_state_projection_includes_ai_annotation_material_batches(
    client, seeded_project, isolated_task_runtime
):
    project_id, _image = seeded_project
    repository, artifacts = isolated_task_runtime
    task_id = uuid.uuid4().hex[:12]
    artifacts.atomic_write_json(task_id, "request.json", {
        "operation": "AI_ANNOTATE",
        "options": {"image_ids": ["batch-image"], "labels": ["fire"]},
    })
    repository.create(TaskRecord.new(
        task_id, project_id, TaskKind.MATERIAL_BATCH, "request.json",
        f"material-batch:{task_id}", required_capabilities=("vision_provider",),
    ))
    store = CandidateStore(artifacts, task_id=task_id, page_size=50)
    store.initialize(labels=["fire"], total_images=1)
    store.append_items([
        {"image_id": "batch-image", "status": "success", "boxes": [{"label": "fire"}]},
    ])
    lease = repository.claim_next(
        "batch-worker", {TaskKind.MATERIAL_BATCH}, {"vision_provider"}
    )
    assert lease and lease.task.task_id == task_id
    repository.finish(
        task_id, lease.lease_token, TaskStatus.AWAITING_CONFIRMATION,
        "candidates/manifest.json",
    )

    response = client.get(
        f"/api/v60/projects/{project_id}/annotation-material-states"
        "?image_ids=batch-image"
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"] == [
        {"image_id": "batch-image", "state": "awaiting_confirmation", "task_id": task_id},
    ]


def test_material_state_projection_ignores_non_ai_material_batches(
    client, seeded_project, isolated_task_runtime
):
    project_id, _image = seeded_project
    repository, artifacts = isolated_task_runtime
    task_id = uuid.uuid4().hex[:12]
    artifacts.atomic_write_json(task_id, "request.json", {
        "operation": "CLEAN",
        "options": {"image_ids": ["clean-image"]},
    })
    repository.create(TaskRecord.new(
        task_id, project_id, TaskKind.MATERIAL_BATCH, "request.json",
        f"material-batch:{task_id}",
    ))
    store = CandidateStore(artifacts, task_id=task_id, page_size=50)
    store.initialize(labels=["fire"], total_images=1)
    store.append_items([
        {"image_id": "clean-image", "status": "success", "boxes": [{"label": "fire"}]},
    ])
    lease = repository.claim_next("clean-worker", {TaskKind.MATERIAL_BATCH}, set())
    assert lease and lease.task.task_id == task_id
    repository.finish(
        task_id, lease.lease_token, TaskStatus.AWAITING_CONFIRMATION,
        "candidates/manifest.json",
    )

    response = client.get(
        f"/api/v60/projects/{project_id}/annotation-material-states"
        "?image_ids=clean-image"
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []



def test_retired_v47_annotation_routes_fail_closed(client, seeded_project):
    project_id, image = seeded_project

    created = client.post(
        f"/api/v47/projects/{project_id}/ai-label-tasks",
        json={
            "image_ids": [image["id"]],
            "labels_text": "fire",
            "provider_id": "fake-provider",
        },
    )
    assert created.status_code == 410
    assert "/api/v60/projects/{project_id}/annotation-tasks" in created.json()["detail"]

    result = client.get(
        f"/api/v47/projects/{project_id}/ai-label-tasks/legacy-task/result"
    )
    assert result.status_code == 410

    confirmed = client.post(
        f"/api/v47/projects/{project_id}/ai-label-tasks/legacy-task/confirm",
        json={"image_ids": [image["id"]]},
    )
    assert confirmed.status_code == 410

    assert not hasattr(app_module, "_v47_run_ai_label_task")



def test_canonical_annotation_helpers_are_not_named_after_retired_v47():
    assert hasattr(app_module, "_annotation_label_catalog")
    assert hasattr(app_module, "_annotation_runtime_provider")
    assert not hasattr(app_module, "_v47_label_catalog")
    assert not hasattr(app_module, "_v47_runtime_provider")


def test_annotation_create_payload_uses_bounded_material_and_reference_lookups(monkeypatch):
    project = {
        "id": "scale-project",
        "labels": ["fire"],
        "label_meta": [{"code": "fire", "display_name": "火焰", "status": "active"}],
    }
    image_ids = [f"image-{index:05d}" for index in range(1_200)]
    reference_ids = [f"reference-{index:04d}" for index in range(1_001)]
    material_batches = []
    annotation_batches = []

    class FakeMaterials:
        def get_many(self, ids):
            batch = list(ids)
            material_batches.append(batch)
            assert len(batch) <= 500
            return [{"id": image_id} for image_id in batch]

    class FakeAnnotations:
        def get_many(self, ids):
            batch = list(ids)
            annotation_batches.append(batch)
            assert len(batch) <= 500
            return {
                image_id: {
                    "image_id": image_id,
                    "annotation_state": "annotated",
                    "boxes": [{"label": "fire", "class_id": 0}],
                }
                for image_id in batch
            }

    monkeypatch.setattr(app_module, "get_project", lambda _project_id: project)
    monkeypatch.setattr(app_module, "material_store", lambda _project_id: FakeMaterials())
    monkeypatch.setattr(app_module, "_v50_annotation_repository", lambda _project_id: FakeAnnotations())
    monkeypatch.setattr(
        app_module,
        "load_images",
        lambda *_args, **_kwargs: pytest.fail("AI task creation must not scan the whole material library"),
    )
    monkeypatch.setattr(
        app_module,
        "read_annotation",
        lambda *_args, **_kwargs: pytest.fail("AI reference labels must use bounded AnnotationRepository.get_many"),
    )

    request, provider_key = app_module._annotation_create_payload(
        "scale-project",
        app_module.AnnotationTaskCreateReq(
            image_ids=image_ids,
            reference_image_ids=reference_ids,
            labels_text="fire",
            provider_id="fake-provider",
        ),
    )

    assert [len(batch) for batch in material_batches] == [500, 500, 200]
    assert [len(batch) for batch in annotation_batches] == [500, 500, 1]
    assert request["image_ids"] == image_ids
    assert request["labels"] == ["fire"]
    assert provider_key == "fake-provider"


def test_annotation_task_frontend_cannot_make_alias_valid_for_backend(client, seeded_project, isolated_task_runtime):
    project_id, image = seeded_project
    project = app_module.get_project(project_id)
    project.setdefault("label_meta", [])[0]["aliases"] = ["flame", "火"]
    app_module.save_project(project)

    for value in ("flame", "火"):
        response = client.post(f"/api/v60/projects/{project_id}/annotation-tasks", json={
            "image_ids": [image["id"]],
            "labels_text": value,
            "provider_id": "fake-provider",
        })
        assert response.status_code == 400
        assert "不会根据中文名、别名或历史映射自动选择标签" in response.json()["detail"]
