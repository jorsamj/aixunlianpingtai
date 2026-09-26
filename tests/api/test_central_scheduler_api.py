from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_node_assignments import central_scheduler_router
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository


def client_for(tmp_path):
    repository = TaskRepository(tmp_path / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "task_runtime" / "artifacts")
    app = FastAPI()
    app.include_router(central_scheduler_router(lambda: repository, lambda: artifacts))
    return TestClient(app), repository, artifacts


def create_training_task(repository, artifacts, task_id="train-api", *, remote_execution=None):
    payload = {"epochs": 30}
    if remote_execution is not None:
        payload["remote_execution"] = remote_execution
    artifacts.atomic_write_json(task_id, "request.json", payload)
    repository.create(
        TaskRecord.new(
            task_id=task_id,
            project_id="project-api",
            kind=TaskKind.TRAINING,
            payload_ref="request.json",
            resource_key=f"training:{task_id}",
        ),
        artifacts=artifacts,
    )


def create_training_node(repository, *, node_id="gpu-api", connection_mode="local"):
    nodes = ServiceNodeRepository(repository)
    _node, token = nodes.create({
        "node_id": node_id,
        "display_name": node_id,
        "connection_mode": connection_mode,
        "allowed_capabilities": ["training"],
    })
    nodes.heartbeat(node_id, token, {
        "build_id": "build-api",
        "reported_capabilities": ["training"],
        "resources": {
            "memory": {"available_bytes": 32 * 1024**3},
            "gpu": {
                "available": True,
                "gpus": [{
                    "id": "cuda:0",
                    "index": 0,
                    "name": "NVIDIA A800",
                    "memory_free_bytes": 30 * 1024**3,
                    "memory_total_bytes": 40 * 1024**3,
                }],
            },
        },
        "runtime": {"torch_version": "2.5.0+cu124", "cuda_version": "12.4"},
    })


def test_scheduler_allocate_list_and_release_api(tmp_path):
    client, repository, artifacts = client_for(tmp_path)
    create_training_task(repository, artifacts)
    create_training_node(repository)

    allocated = client.post("/api/v63/scheduler/allocate-next")
    assert allocated.status_code == 200, allocated.text
    body = allocated.json()
    assert body["assigned"] is True
    assignment = body["assignment"]
    assert assignment["task_id"] == "train-api"
    assert assignment["node_id"] == "gpu-api"
    assert assignment["state"] == "ASSIGNED"
    assert assignment["resolved_execution_config"]["selected_device"] == "cuda:0"

    listing = client.get("/api/v63/scheduler/assignments")
    assert listing.status_code == 200
    assert [item["task_id"] for item in listing.json()["items"]] == ["train-api"]

    filtered = client.get("/api/v63/scheduler/assignments", params={"node_id": "gpu-api"})
    assert filtered.status_code == 200
    assert len(filtered.json()["items"]) == 1

    released = client.post(
        "/api/v63/scheduler/assignments/train-api/release",
        json={"reason": "api-test"},
    )
    assert released.status_code == 200, released.text
    assert released.json()["assignment"]["state"] == "RELEASED"
    assert released.json()["assignment"]["release_reason"] == "api-test"

    assert client.get("/api/v63/scheduler/assignments").json()["items"] == []
    history = client.get(
        "/api/v63/scheduler/assignments",
        params={"active_only": "false"},
    )
    assert len(history.json()["items"]) == 1
    assert history.json()["items"][0]["state"] == "RELEASED"


def test_scheduler_api_fails_closed_for_remote_agent_without_portable_contract(tmp_path):
    client, repository, artifacts = client_for(tmp_path)
    create_training_task(repository, artifacts, "train-legacy-agent")
    create_training_node(
        repository,
        node_id="gpu-agent-only",
        connection_mode="agent",
    )

    response = client.post("/api/v63/scheduler/allocate-next")
    assert response.status_code == 200
    assert response.json() == {"assigned": False, "assignment": None}


def test_scheduler_api_allows_explicit_portable_task_on_remote_agent(tmp_path):
    client, repository, artifacts = client_for(tmp_path)
    create_training_task(
        repository,
        artifacts,
        "train-portable-agent",
        remote_execution={
            "version": 1,
            "task_kind": "TRAINING",
            "transport": "object-storage-v1",
            "signed_url": "https://must-not-be-copied.example.test",
        },
    )
    create_training_node(
        repository,
        node_id="gpu-agent-portable",
        connection_mode="agent",
    )

    response = client.post("/api/v63/scheduler/allocate-next")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assigned"] is True
    assignment = body["assignment"]
    assert assignment["node_id"] == "gpu-agent-portable"
    resolved = assignment["resolved_execution_config"]
    assert resolved["connection_mode"] == "agent"
    assert resolved["remote_execution"] == {
        "version": 1,
        "task_kind": "TRAINING",
        "transport": "object-storage-v1",
    }
    assert "must-not-be-copied.example.test" not in str(resolved)


def test_scheduler_release_missing_assignment_is_structured_404(tmp_path):
    client, _repository, _artifacts = client_for(tmp_path)
    response = client.post(
        "/api/v63/scheduler/assignments/missing/release",
        json={},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NODE_ASSIGNMENT_NOT_FOUND"


def test_scheduler_allocate_returns_false_when_no_eligible_node_exists(tmp_path):
    client, repository, artifacts = client_for(tmp_path)
    create_training_task(repository, artifacts, "train-no-node")
    response = client.post("/api/v63/scheduler/allocate-next")
    assert response.status_code == 200
    assert response.json() == {"assigned": False, "assignment": None}
