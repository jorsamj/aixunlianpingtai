from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from platform_core.agent_execution import AgentExecutionService, agent_executor_router
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository


def client_for(tmp_path):
    repository = TaskRepository(tmp_path / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "task_runtime" / "artifacts")
    app = FastAPI()
    app.include_router(agent_executor_router(lambda: repository, lambda: artifacts))
    return TestClient(app), repository, artifacts


def create_task(repository, artifacts, task_id="train-api-agent"):
    artifacts.atomic_write_json(task_id, "request.json", {"epochs": 30})
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
    assert start_body["payload"] == {"epochs": 30}
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
