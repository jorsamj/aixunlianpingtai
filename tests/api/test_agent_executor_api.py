from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from platform_core.agent_execution import AgentExecutionService, agent_executor_router
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository


def safe_remote_payload(task, payload, assignment):
    return {
        "schema_version": 1,
        "task_kind": task.kind.value,
        "transport": "test-safe-v1",
        "epochs": int(payload.get("epochs") or 0),
        "selected_device": str(
            (assignment.get("resolved_execution_config") or {}).get("selected_device") or ""
        ),
    }


def client_for(tmp_path, *, material_scan_page_provider=None, material_scan_read_provider=None):
    repository = TaskRepository(tmp_path / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "task_runtime" / "artifacts")
    app = FastAPI()
    app.include_router(agent_executor_router(
        lambda: repository,
        lambda: artifacts,
        execution_payload_resolver=safe_remote_payload,
        material_scan_page_provider=material_scan_page_provider,
        material_scan_read_provider=material_scan_read_provider,
    ))
    return TestClient(app), repository, artifacts


def create_task(repository, artifacts, task_id="train-api-agent"):
    artifacts.atomic_write_json(task_id, "request.json", {
        "epochs": 30,
        "remote_execution": {
            "version": 1,
            "task_kind": TaskKind.TRAINING.value,
            "transport": "object-storage-v1",
        },
    })
    repository.create(
        TaskRecord.new(
            task_id=task_id,
            project_id="project-api-agent",
            kind=TaskKind.TRAINING,
            payload_ref="request.json",
            resource_key=f"training:{task_id}",
        ),
        artifacts=artifacts,
    )


def create_node(repository, node_id="gpu-api-agent"):
    nodes = ServiceNodeRepository(repository)
    _node, token = nodes.create({
        "node_id": node_id,
        "display_name": node_id,
        "connection_mode": "agent",
        "allowed_capabilities": ["training"],
    })
    nodes.heartbeat(node_id, token, {
        "hostname": node_id,
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
    return nodes, token


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def prepare(client, repository, artifacts):
    create_task(repository, artifacts)
    nodes, token = create_node(repository)
    service = AgentExecutionService(repository, artifacts)
    assignment = service.allocator.assign_next()
    assert assignment is not None
    return nodes, token


def test_agent_executor_http_happy_flow_and_cancellation_truth(tmp_path):
    client, repository, artifacts = client_for(tmp_path)
    _nodes, token = prepare(client, repository, artifacts)

    claimed = client.post(
        "/api/v63/node-executor/gpu-api-agent/assignments/claim",
        headers=auth(token),
    )
    assert claimed.status_code == 200, claimed.text
    claim_body = claimed.json()
    assert claim_body["claimed"] is True
    assignment_token = claim_body["item"]["assignment"]["assignment_lease_token"]

    started = client.post(
        "/api/v63/node-executor/gpu-api-agent/assignments/train-api-agent/start",
        headers=auth(token),
        json={"assignment_lease_token": assignment_token},
    )
    assert started.status_code == 200, started.text
    start_body = started.json()
    execution = start_body["execution"]
    assert start_body["task"]["status"] == "RUNNING"
    assert start_body["task"]["worker_id"] == "agent:gpu-api-agent"
    assert execution["generation"] == 1
    assert start_body["payload"] == {
        "schema_version": 1,
        "task_kind": "TRAINING",
        "transport": "test-safe-v1",
        "epochs": 30,
        "selected_device": "cuda:0",
    }
    assert "remote_execution" not in start_body["payload"]
    assert start_body["transport"]["shared_sqlite_required"] is False
    assert start_body["transport"]["shared_nfs_required"] is False

    invalid_generation = client.post(
        "/api/v63/node-executor/gpu-api-agent/executions/train-api-agent/heartbeat",
        headers=auth(token),
        json={
            "execution_lease_token": execution["lease_token"],
            "execution_generation": "not-a-number",
            "progress": 5,
        },
    )
    assert invalid_generation.status_code == 422
    assert invalid_generation.json()["detail"]["code"] == "INVALID_EXECUTION_GENERATION"

    heartbeat = client.post(
        "/api/v63/node-executor/gpu-api-agent/executions/train-api-agent/heartbeat",
        headers=auth(token),
        json={
            "execution_lease_token": execution["lease_token"],
            "execution_generation": execution["generation"],
            "progress": 40,
            "stage": "training",
            "current_item": "epoch 12/30",
        },
    )
    assert heartbeat.status_code == 200, heartbeat.text
    assert heartbeat.json()["task"]["progress"] == 40
    assert heartbeat.json()["cancel_requested"] is False

    log = client.post(
        "/api/v63/node-executor/gpu-api-agent/executions/train-api-agent/logs",
        headers=auth(token),
        json={
            "execution_lease_token": execution["lease_token"],
            "execution_generation": execution["generation"],
            "text": "epoch 12/30\n",
        },
    )
    assert log.status_code == 200, log.text
    assert log.json()["bytes"] > 0

    repository.request_cancel("train-api-agent")
    cancellation = client.post(
        "/api/v63/node-executor/gpu-api-agent/executions/train-api-agent/heartbeat",
        headers=auth(token),
        json={
            "execution_lease_token": execution["lease_token"],
            "execution_generation": execution["generation"],
        },
    )
    assert cancellation.status_code == 200
    assert cancellation.json()["cancel_requested"] is True

    rejected_success = client.post(
        "/api/v63/node-executor/gpu-api-agent/executions/train-api-agent/finish",
        headers=auth(token),
        json={
            "execution_lease_token": execution["lease_token"],
            "execution_generation": execution["generation"],
            "status": "SUCCEEDED",
        },
    )
    assert rejected_success.status_code == 409
    assert rejected_success.json()["detail"]["code"] == "CANCELLATION_WON"

    cancelled = client.post(
        "/api/v63/node-executor/gpu-api-agent/executions/train-api-agent/finish",
        headers=auth(token),
        json={
            "execution_lease_token": execution["lease_token"],
            "execution_generation": execution["generation"],
            "status": "CANCELLED",
        },
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["task"]["status"] == "CANCELLED"


def test_agent_executor_rejects_wrong_node_and_assignment_tokens(tmp_path):
    client, repository, artifacts = client_for(tmp_path)
    _nodes, token = prepare(client, repository, artifacts)

    denied_claim = client.post(
        "/api/v63/node-executor/gpu-api-agent/assignments/claim",
        headers=auth("wrong-node-token"),
    )
    assert denied_claim.status_code == 401
    assert denied_claim.json()["detail"]["code"] == "INVALID_NODE_TOKEN"

    claimed = client.post(
        "/api/v63/node-executor/gpu-api-agent/assignments/claim",
        headers=auth(token),
    )
    assignment_token = claimed.json()["item"]["assignment"]["assignment_lease_token"]
    denied_start = client.post(
        "/api/v63/node-executor/gpu-api-agent/assignments/train-api-agent/start",
        headers=auth(token),
        json={"assignment_lease_token": "wrong-assignment-token"},
    )
    assert denied_start.status_code == 401
    assert denied_start.json()["detail"]["code"] == "INVALID_ASSIGNMENT_LEASE"

    valid_start = client.post(
        "/api/v63/node-executor/gpu-api-agent/assignments/train-api-agent/start",
        headers=auth(token),
        json={"assignment_lease_token": assignment_token},
    )
    assert valid_start.status_code == 200

    duplicate = client.post(
        "/api/v63/node-executor/gpu-api-agent/assignments/train-api-agent/start",
        headers=auth(token),
        json={"assignment_lease_token": assignment_token},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "ASSIGNMENT_NOT_CLAIMED"


def test_node_token_rotation_immediately_revokes_remote_execution_api(tmp_path):
    client, repository, artifacts = client_for(tmp_path)
    nodes, token = prepare(client, repository, artifacts)

    claim = client.post(
        "/api/v63/node-executor/gpu-api-agent/assignments/claim",
        headers=auth(token),
    ).json()
    started = client.post(
        "/api/v63/node-executor/gpu-api-agent/assignments/train-api-agent/start",
        headers=auth(token),
        json={
            "assignment_lease_token": claim["item"]["assignment"]["assignment_lease_token"]
        },
    )
    execution = started.json()["execution"]

    _node, replacement = nodes.rotate_token("gpu-api-agent")
    revoked = client.post(
        "/api/v63/node-executor/gpu-api-agent/executions/train-api-agent/heartbeat",
        headers=auth(token),
        json={
            "execution_lease_token": execution["lease_token"],
            "execution_generation": execution["generation"],
            "progress": 50,
        },
    )
    assert revoked.status_code == 401
    assert revoked.json()["detail"]["code"] == "INVALID_NODE_TOKEN"

    accepted = client.post(
        "/api/v63/node-executor/gpu-api-agent/executions/train-api-agent/heartbeat",
        headers=auth(replacement),
        json={
            "execution_lease_token": execution["lease_token"],
            "execution_generation": execution["generation"],
            "progress": 50,
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["task"]["progress"] == 50



def test_material_scan_broker_requires_current_execution_lease(tmp_path):
    page_calls = []
    read_calls = []

    def page_provider(task, payload, *, cursor=None, limit=100):
        page_calls.append((task.task_id, payload.get("remote_execution"), cursor, limit))
        return {"items": [{"key": "incoming/a.jpg", "size_bytes": 12}], "next_cursor": None}

    def read_provider(task, payload, *, object_key):
        read_calls.append((task.task_id, object_key))
        return {"method": "GET", "url": "https://objects.example.test/a.jpg", "key": object_key}

    client, repository, artifacts = client_for(
        tmp_path,
        material_scan_page_provider=page_provider,
        material_scan_read_provider=read_provider,
    )
    task_id = "material-api-agent"
    artifacts.atomic_write_json(task_id, "request.json", {
        "execution_mode": "agent",
        "remote_execution": {
            "version": 1,
            "task_kind": "MATERIAL_IMPORT",
            "transport": "object-storage-v1",
        },
    })
    repository.create(TaskRecord.new(
        task_id=task_id,
        project_id="project-api-agent",
        kind=TaskKind.MATERIAL_IMPORT,
        payload_ref="request.json",
        resource_key=f"material-import:{task_id}",
    ), artifacts=artifacts)

    nodes = ServiceNodeRepository(repository)
    _node, token = nodes.create({
        "node_id": "material-api-node",
        "display_name": "material-api-node",
        "connection_mode": "agent",
        "allowed_capabilities": ["material-import"],
    })
    nodes.heartbeat("material-api-node", token, {
        "hostname": "material-api-node",
        "reported_capabilities": ["material-import"],
        "resources": {"memory": {"available_bytes": 8 * 1024**3}, "gpu": {"available": False, "gpus": []}},
        "runtime": {},
    })
    service = AgentExecutionService(repository, artifacts)
    assignment = service.allocator.assign_next()
    assert assignment is not None
    claimed = client.post(
        "/api/v63/node-executor/material-api-node/assignments/claim",
        headers=auth(token),
    ).json()
    started = client.post(
        f"/api/v63/node-executor/material-api-node/assignments/{task_id}/start",
        headers=auth(token),
        json={"assignment_lease_token": claimed["item"]["assignment"]["assignment_lease_token"]},
    )
    assert started.status_code == 200, started.text
    execution = started.json()["execution"]

    page = client.post(
        f"/api/v63/node-executor/material-api-node/executions/{task_id}/material-scan/page",
        headers=auth(token),
        json={
            "execution_lease_token": execution["lease_token"],
            "execution_generation": execution["generation"],
            "limit": 25,
        },
    )
    assert page.status_code == 200, page.text
    assert page.json()["items"][0]["key"] == "incoming/a.jpg"
    assert page_calls[-1][3] == 25

    read = client.post(
        f"/api/v63/node-executor/material-api-node/executions/{task_id}/material-scan/read",
        headers=auth(token),
        json={
            "execution_lease_token": execution["lease_token"],
            "execution_generation": execution["generation"],
            "object_key": "incoming/a.jpg",
        },
    )
    assert read.status_code == 200, read.text
    assert read.json()["key"] == "incoming/a.jpg"
    assert read_calls[-1][1] == "incoming/a.jpg"

    fenced = client.post(
        f"/api/v63/node-executor/material-api-node/executions/{task_id}/material-scan/page",
        headers=auth(token),
        json={
            "execution_lease_token": "wrong-token",
            "execution_generation": execution["generation"],
        },
    )
    assert fenced.status_code == 409
    assert fenced.json()["detail"]["code"] == "EXECUTION_FENCED"
