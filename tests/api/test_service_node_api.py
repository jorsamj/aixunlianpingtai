from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from platform_core.service_nodes import service_node_router
from platform_core.task_runtime import TaskRepository


def client_for(tmp_path):
    repository = TaskRepository(tmp_path / "task_runtime" / "tasks.sqlite3")
    app = FastAPI()
    app.include_router(service_node_router(lambda: repository))
    return TestClient(app), repository


def test_service_node_management_and_authenticated_heartbeat(tmp_path):
    client, _repository = client_for(tmp_path)
    created = client.post("/api/v63/service-nodes", json={
        "node_id": "gpu-node-api",
        "display_name": "GPU Node API",
        "connection_mode": "agent",
        "allowed_capabilities": ["training", "conversion"],
    })
    assert created.status_code == 201, created.text
    body = created.json()
    token = body["agent_token"]
    assert token
    assert body["node"]["status"] == "NEVER_CONNECTED"

    denied = client.post(
        "/api/v63/service-nodes/gpu-node-api/heartbeat",
        headers={"Authorization": "Bearer wrong"},
        json={"reported_capabilities": ["training"]},
    )
    assert denied.status_code == 401
    assert denied.json()["detail"]["code"] == "INVALID_NODE_TOKEN"

    heartbeat = client.post(
        "/api/v63/service-nodes/gpu-node-api/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "hostname": "gpu-host",
            "os_name": "Linux",
            "reported_capabilities": ["training", "annotation"],
            "resources": {"gpu": {"available": True, "gpus": [{"id": "cuda:0"}]}},
            "runtime": {"cuda_version": "12.4"},
            "process": {"pid": 101},
        },
    )
    assert heartbeat.status_code == 200, heartbeat.text
    node = heartbeat.json()["node"]
    assert node["status"] == "ONLINE"
    assert node["effective_capabilities"] == ["training"]
    assert heartbeat.json()["desired"]["allowed_capabilities"] == ["conversion", "training"]

    updated = client.patch(
        "/api/v63/service-nodes/gpu-node-api",
        json={"enabled": False, "allowed_capabilities": ["material-import"]},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "DISABLED"
    assert updated.json()["allowed_capabilities"] == ["material-import"]

    rotated = client.post("/api/v63/service-nodes/gpu-node-api/rotate-token")
    assert rotated.status_code == 200
    replacement = rotated.json()["agent_token"]
    assert replacement != token
    old_token = client.post(
        "/api/v63/service-nodes/gpu-node-api/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={"reported_capabilities": []},
    )
    assert old_token.status_code == 401

    listing = client.get("/api/v63/service-nodes")
    assert listing.status_code == 200
    assert listing.json()["items"][0]["node_id"] == "gpu-node-api"
    assert "model-upload" in listing.json()["supported_capabilities"]


def test_service_node_api_never_returns_token_hash(tmp_path):
    client, _repository = client_for(tmp_path)
    created = client.post("/api/v63/service-nodes", json={
        "node_id": "node-secret-shape",
        "display_name": "Secret Shape",
    })
    assert created.status_code == 201
    listing_text = client.get("/api/v63/service-nodes").text
    assert "token_hash" not in listing_text
    assert created.json()["agent_token"] not in listing_text
