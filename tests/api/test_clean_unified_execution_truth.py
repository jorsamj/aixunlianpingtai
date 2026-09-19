import hashlib
import io
import uuid
from pathlib import Path

from PIL import Image

import app as app_module
from platform_core.model_artifacts import ModelArtifactConfigPayload, ModelArtifactRepository
from platform_core.service_nodes import ServiceNodeRepository
import platform_core.cleaning_batches as cleaning_batches
from platform_core.cleaning import image_metrics
from platform_core.cleaning_analysis_runtime import CleaningAnalysisTimeout
from platform_core.task_runtime import (
    ArtifactStore, FencedTaskRepository, Scheduler, TaskKind, TaskStatus,
)
from platform_core.worker_registry import build_worker_registration


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (400, 300), "gray").save(output, format="PNG")
    return output.getvalue()


def _create_project(client, name: str) -> str:
    response = client.post("/api/projects", json={"name": name, "labels": []})
    response.raise_for_status()
    return response.json()["id"]


def _upload(client, project_id: str, *names: str) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", (name, _png_bytes(), "image/png")) for name in names],
        data={"dataset_id": "default"},
    )
    response.raise_for_status()
    return response.json()


def _assert_durable_clean_task(project_id: str, task_id: str, expected_ids: list[str]):
    repository = app_module.shared_task_repository()
    task = repository.get(task_id)
    assert task is not None, "cleaning execution must be published to TaskRepository"
    assert task.project_id == project_id
    assert task.kind is TaskKind.MATERIAL_BATCH
    assert task.status is TaskStatus.QUEUED
    assert task.resource_key == f"materials:{project_id}"
    request = app_module.shared_task_artifacts().read_json(task_id, task.payload_ref, default={})
    assert request["operation"] == "CLEAN"
    assert sorted(request["selection_spec"]["image_ids"]) == sorted(expected_ids)


def _materials_scheduler(project_id: str):
    runtime = app_module.DATA_DIR / "task_runtime"
    repository = FencedTaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")
    handlers, capabilities = build_worker_registration(app_module.DATA_DIR, {"materials"})
    scheduler = Scheduler(
        repository,
        artifacts,
        f"clean-contract-{project_id}-{uuid.uuid4().hex[:8]}",
        handlers,
        capabilities,
        lease_seconds=5,
        poll_seconds=0.01,
    )
    return scheduler, repository, artifacts


def test_v47_manual_clean_creation_publishes_material_batch_truth(client):
    project_id = _create_project(client, "manual-clean-unified-truth")
    uploaded = _upload(client, project_id, "manual-clean.png")
    image_id = uploaded["uploaded"][0]["id"]

    response = client.post(
        f"/api/v47/projects/{project_id}/clean-tasks",
        json={"image_ids": [image_id], "task_name": "manual durable clean"},
    )
    response.raise_for_status()
    body = response.json()
    task_id = body["id"]
    assert "resource_queue_position" in body
    assert "resource_wait_reason" in body
    queue_position = body["resource_queue_position"]
    if queue_position is not None:
        assert isinstance(queue_position, int)
        assert queue_position >= 1
    wait_reason = body["resource_wait_reason"]
    if wait_reason is not None:
        assert isinstance(wait_reason, str)

    _assert_durable_clean_task(project_id, task_id, [image_id])



def test_clean_agent_preflight_rejects_local_material_and_create_does_not_fallback(client):
    project_id = _create_project(client, "clean-agent-local-rejected")
    uploaded = _upload(client, project_id, "local-only.png")
    image_id = uploaded["uploaded"][0]["id"]

    preflight = client.post(
        f"/api/v47/projects/{project_id}/clean-runtime/preflight",
        json={"image_ids": [image_id]},
    )
    preflight.raise_for_status()
    truth = preflight.json()
    assert truth["local_available"] is True
    assert truth["default_execution_mode"] == "local"
    assert truth["agent_available"] is False
    assert truth["selected_count"] == 1
    assert truth["reason"]

    rejected = client.post(
        f"/api/v47/projects/{project_id}/clean-tasks",
        json={
            "image_ids": [image_id],
            "task_name": "must not fall back local",
            "execution_mode": "agent",
        },
    )
    assert rejected.status_code == 409
    assert not app_module.shared_task_repository().list(
        project_id=project_id,
        kinds={TaskKind.MATERIAL_BATCH},
        limit=20,
    ).items


def test_v47_agent_clean_publishes_agent_remote_capability_when_portable(client):
    project_id = _create_project(client, "clean-agent-portable")
    uploaded = _upload(client, project_id, "portable.png")
    image_id = uploaded["uploaded"][0]["id"]
    payload_bytes = _png_bytes()
    digest = hashlib.sha256(payload_bytes).hexdigest()

    source_id = f"clean-s3-{uuid.uuid4().hex[:8]}"
    app_module.storage_source_repository().create({
        "id": source_id,
        "name": "cleaning test object storage",
        "type": "s3",
        "config": {"bucket": "test-bucket"},
        "enabled": True,
    })
    materials = app_module.material_store(project_id)
    row = materials.get(image_id)
    assert row is not None
    row.update({
        "storage_source_id": source_id,
        "storage_type": "s3",
        "object_key": f"clean/{image_id}.png",
        "content_sha256": digest,
        "size_bytes": len(payload_bytes),
        "etag": "etag-clean-test",
    })
    materials.upsert(row)

    ModelArtifactRepository(app_module.DATA_DIR).save_config(
        ModelArtifactConfigPayload(
            storage_source_id=source_id,
            object_prefix="remote-execution",
            auto_upload_enabled=True,
        )
    )

    nodes = ServiceNodeRepository(app_module.shared_task_repository())
    node_id = f"clean-agent-{uuid.uuid4().hex[:8]}"
    _node, token = nodes.create({
        "node_id": node_id,
        "display_name": node_id,
        "connection_mode": "agent",
        "allowed_capabilities": ["cleaning"],
    })
    nodes.heartbeat(node_id, token, {
        "hostname": node_id,
        "reported_capabilities": ["cleaning"],
        "resources": {
            "memory": {"available_bytes": 8 * 1024**3},
            "disk": {"free_bytes": 100 * 1024**3},
            "gpu": {"available": False, "gpus": []},
        },
        "runtime": {},
    })

    preflight = client.post(
        f"/api/v47/projects/{project_id}/clean-runtime/preflight",
        json={"image_ids": [image_id]},
    )
    preflight.raise_for_status()
    truth = preflight.json()
    assert truth["agent_available"] is True
    assert truth["selected_count"] == 1
    assert truth["eligible_nodes"][0]["node_id"] == node_id

    response = client.post(
        f"/api/v47/projects/{project_id}/clean-tasks",
        json={
            "image_ids": [image_id],
            "task_name": "portable remote clean",
            "execution_mode": "agent",
        },
    )
    response.raise_for_status()
    body = response.json()
    assert body["execution_mode"] == "agent"

    task = app_module.shared_task_repository().get(body["id"])
    assert task is not None
    assert task.kind is TaskKind.MATERIAL_BATCH
    assert tuple(task.required_capabilities) == ("agent.remote",)
    request = app_module.shared_task_artifacts().read_json(
        task.task_id, task.payload_ref, default={}
    )
    assert request["operation"] == "CLEAN"
    assert request["execution_mode"] == "agent"
    assert request["remote_execution"]["task_kind"] == "MATERIAL_BATCH"
    assert request["remote_execution"]["transport"] == "object-storage-v1"


def test_upload_batch_clean_association_points_to_same_durable_task(client):
    project_id = _create_project(client, "upload-clean-unified-truth")
    uploaded = _upload(client, project_id, "needs-clean.png", "ready.png")
    clean_id = uploaded["uploaded"][0]["id"]
    ready_id = uploaded["uploaded"][1]["id"]

    response = client.post(
        f"/api/v55/projects/{project_id}/upload-batches/{uploaded['batch_id']}/decisions",
        json={"clean_image_ids": [clean_id], "ready_image_ids": [ready_id]},
    )
    response.raise_for_status()
    task_id = response.json()["clean_task_id"]
    assert task_id

    _assert_durable_clean_task(project_id, task_id, [clean_id])
    repeated = client.post(
        f"/api/v55/projects/{project_id}/upload-batches/{uploaded['batch_id']}/decisions",
        json={"clean_image_ids": [clean_id], "ready_image_ids": [ready_id]},
    )
    repeated.raise_for_status()
    assert repeated.json()["clean_task_id"] == task_id
    assert app_module.shared_task_repository().get(task_id).task_id == task_id


def test_clean_executes_through_real_fenced_material_worker(client):
    project_id = _create_project(client, "clean-real-fenced-worker")
    uploaded = _upload(client, project_id, "real-worker.png")
    image_id = uploaded["uploaded"][0]["id"]
    response = client.post(
        f"/api/v47/projects/{project_id}/clean-tasks",
        json={"image_ids": [image_id], "task_name": "real worker clean"},
    )
    response.raise_for_status()
    task_id = response.json()["id"]

    scheduler, _repository, _artifacts = _materials_scheduler(project_id)
    for _ in range(10):
        current = app_module.shared_task_repository().get(task_id)
        assert current is not None
        if current.status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.PARTIAL_SUCCESS}:
            break
        assert scheduler.run_once() is True
    current = app_module.shared_task_repository().get(task_id)
    assert current is not None
    assert current.status is TaskStatus.SUCCEEDED, current.error
    assert current.stage == "succeeded"
    assert current.progress == 100

    result_response = client.get(f"/api/v47/projects/{project_id}/clean-tasks/{task_id}/result")
    result_response.raise_for_status()
    body = result_response.json()
    assert body["task"]["status"] == "awaiting_confirmation"
    assert body["task"]["stage"] == "review"
    assert body["task"]["processed_images"] == 1
    assert body["task"]["progress"] == 100
    assert [item["image_id"] for item in body["result"]["items"]] == [image_id]

    durable_after_projection = app_module.shared_task_repository().get(task_id)
    assert durable_after_projection is not None
    assert durable_after_projection.status is TaskStatus.SUCCEEDED
    assert durable_after_projection.stage == "succeeded"


def test_clean_analysis_timeout_fails_one_image_and_continues_next(client, monkeypatch):
    project_id = _create_project(client, "clean-analysis-timeout-continues")
    uploaded = _upload(client, project_id, "timeout-first.png", "continue-second.png")
    image_ids = [item["id"] for item in uploaded["uploaded"]]
    response = client.post(
        f"/api/v47/projects/{project_id}/clean-tasks",
        json={"image_ids": image_ids, "task_name": "timeout must not freeze batch"},
    )
    response.raise_for_status()
    task_id = response.json()["id"]

    class TimeoutThenAnalyzeRuntime:
        calls = 0

        def analyze(self, path, *, require_blur, content_sha256, check_active=None):
            type(self).calls += 1
            if check_active is not None:
                check_active()
            if type(self).calls == 1:
                raise CleaningAnalysisTimeout("CLEAN_ANALYSIS_TIMEOUT: simulated stalled image")
            return image_metrics(
                Path(path),
                require_blur=require_blur,
                content_sha256=content_sha256,
            )

        def close(self):
            return None

    monkeypatch.setattr(cleaning_batches, "CleaningAnalysisRuntime", TimeoutThenAnalyzeRuntime)
    scheduler, repository, artifacts = _materials_scheduler(project_id)
    assert scheduler.run_once() is True

    current = repository.get(task_id)
    assert current is not None
    assert current.status is TaskStatus.PARTIAL_SUCCESS, current.error
    assert current.progress == 100

    result = artifacts.read_json(task_id, "result.json", default={})
    assert result["total"] == 2
    assert result["processed"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert TimeoutThenAnalyzeRuntime.calls == 2

    states = [app_module.material_store(project_id).get(image_id)["clean_status"] for image_id in image_ids]
    assert states.count("failed") == 1
    completed_states = [state for state in states if state != "failed"]
    assert len(completed_states) == 1
    assert completed_states[0] in {"passed", "needs_review"}
