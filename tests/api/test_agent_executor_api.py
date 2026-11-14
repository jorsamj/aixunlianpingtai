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


def client_for(
    tmp_path,
    *,
    material_scan_page_provider=None,
    material_scan_read_provider=None,
    clean_selection_page_provider=None,
    clean_selection_read_provider=None,
):
    repository = TaskRepository(tmp_path / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "task_runtime" / "artifacts")
    app = FastAPI()
    app.include_router(agent_executor_router(
        lambda: repository,
        lambda: artifacts,
        execution_payload_resolver=safe_remote_payload,
        material_scan_page_provider=material_scan_page_provider,
        material_scan_read_provider=material_scan_read_provider,
        clean_selection_page_provider=clean_selection_page_provider,
        clean_selection_read_provider=clean_selection_read_provider,
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


def test_agent_claim_http_auto_assignment_is_explicitly_opt_in(tmp_path, monkeypatch):
    monkeypatch.delenv("CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM", raising=False)
    client, repository, artifacts = client_for(tmp_path)
    create_task(repository, artifacts)
    artifacts.atomic_write_json("train-api-agent", "request.json", {
        "target": "remote", "epochs": 30,
        "remote_execution": {
            "version": 1, "task_kind": "TRAINING",
            "transport": "object-storage-v1",
        },
    })
    _nodes, token = create_node(repository)

    url = "/api/v63/node-executor/gpu-api-agent/assignments/claim"
    disabled = client.post(url, headers=auth(token))
    assert disabled.status_code == 200
    assert disabled.json() == {"claimed": False, "item": None}
    assert AgentExecutionService(repository, artifacts).allocator.list(active_only=True) == []

    monkeypatch.setenv("CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM", "1")
    claimed = client.post(url, headers=auth(token))
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["claimed"] is True
    assert claimed.json()["item"]["task"]["task_id"] == "train-api-agent"
    assert claimed.json()["item"]["assignment"]["resolved_execution_config"]["connection_mode"] == "agent"
    assert len(AgentExecutionService(repository, artifacts).allocator.list(active_only=True)) == 1

    again = client.post(url, headers=auth(token))
    assert again.status_code == 200
    assert again.json() == {"claimed": False, "item": None}


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


def test_clean_selection_broker_requires_material_batch_clean_and_current_execution_lease(tmp_path):
    page_calls = []
    read_calls = []

    def page_provider(task, payload, *, cursor=None, limit=100):
        page_calls.append((task.task_id, payload.get("operation"), cursor, limit))
        return {
            "items": [{"image_id": "img-1", "size_bytes": 12, "sha256": "a" * 64}],
            "next_cursor": None,
            "total": 1,
        }

    def read_provider(task, payload, *, image_id):
        read_calls.append((task.task_id, image_id))
        return {
            "image_id": image_id,
            "download": {"method": "GET", "url": "https://objects.example.test/img-1.jpg"},
        }

    client, repository, artifacts = client_for(
        tmp_path,
        clean_selection_page_provider=page_provider,
        clean_selection_read_provider=read_provider,
    )
    task_id = "clean-api-agent"
    artifacts.atomic_write_json(task_id, "request.json", {
        "operation": "CLEAN",
        "execution_mode": "agent",
        "options": {},
        "remote_execution": {
            "version": 1,
            "task_kind": "MATERIAL_BATCH",
            "transport": "object-storage-v1",
            "cleaning": {
                "schema_version": 1,
                "selection_protocol": "exact-material-selection-v1",
                "output": {
                    "storage_source_id": "objects",
                    "object_key": "remote-execution/p/t/cleaning-review/review.jsonl",
                },
            },
        },
    })
    repository.create(TaskRecord.new(
        task_id=task_id,
        project_id="project-api-agent",
        kind=TaskKind.MATERIAL_BATCH,
        payload_ref="request.json",
        resource_key=f"materials:{task_id}",
        required_capabilities=("agent.remote",),
    ), artifacts=artifacts)

    nodes = ServiceNodeRepository(repository)
    _node, token = nodes.create({
        "node_id": "clean-api-node",
        "display_name": "clean-api-node",
        "connection_mode": "agent",
        "allowed_capabilities": ["cleaning"],
    })
    nodes.heartbeat("clean-api-node", token, {
        "hostname": "clean-api-node",
        "reported_capabilities": ["cleaning"],
        "resources": {"memory": {"available_bytes": 8 * 1024**3}, "disk": {"free_bytes": 100 * 1024**3}},
        "runtime": {},
    })
    service = AgentExecutionService(repository, artifacts)
    assignment = service.allocator.assign_next()
    assert assignment is not None
    assert assignment["capability"] == "cleaning"

    claimed = client.post(
        "/api/v63/node-executor/clean-api-node/assignments/claim",
        headers=auth(token),
    ).json()
    started = client.post(
        f"/api/v63/node-executor/clean-api-node/assignments/{task_id}/start",
        headers=auth(token),
        json={"assignment_lease_token": claimed["item"]["assignment"]["assignment_lease_token"]},
    )
    assert started.status_code == 200, started.text
    execution = started.json()["execution"]

    page = client.post(
        f"/api/v63/node-executor/clean-api-node/executions/{task_id}/clean-selection/page",
        headers=auth(token),
        json={
            "execution_lease_token": execution["lease_token"],
            "execution_generation": execution["generation"],
            "limit": 25,
        },
    )
    assert page.status_code == 200, page.text
    assert page.json()["items"][0]["image_id"] == "img-1"
    assert page_calls[-1][3] == 25

    read = client.post(
        f"/api/v63/node-executor/clean-api-node/executions/{task_id}/clean-selection/read",
        headers=auth(token),
        json={
            "execution_lease_token": execution["lease_token"],
            "execution_generation": execution["generation"],
            "image_id": "img-1",
        },
    )
    assert read.status_code == 200, read.text
    assert read.json()["image_id"] == "img-1"
    assert read_calls[-1][1] == "img-1"

    fenced = client.post(
        f"/api/v63/node-executor/clean-api-node/executions/{task_id}/clean-selection/page",
        headers=auth(token),
        json={
            "execution_lease_token": "wrong-token",
            "execution_generation": execution["generation"],
        },
    )
    assert fenced.status_code == 409
    assert fenced.json()["detail"]["code"] == "EXECUTION_FENCED"


def test_two_agents_http_auto_assignment_and_fenced_execution(tmp_path, monkeypatch):
    """Two independently authenticated Agents share one authoritative queue.

    Exercise the actual FastAPI router without production GPU, OSS or network.
    The first Agent owns one running task, the second must receive a distinct
    task, and neither may start work using the other's assignment lease.
    """
    monkeypatch.setenv("CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM", "1")
    client, repository, artifacts = client_for(tmp_path)
    _, token_a = create_node(repository, "http-agent-a")
    _, token_b = create_node(repository, "http-agent-b")

    def make_remote(task_id):
        create_task(repository, artifacts, task_id)
        artifacts.atomic_write_json(task_id, "request.json", {
            "target": "remote",
            "epochs": 8,
            "remote_execution": {
                "version": 1, "task_kind": "TRAINING",
                "transport": "object-storage-v1",
            },
        })

    def poll(node, token):
        result = client.post(
            f"/api/v63/node-executor/{node}/assignments/claim",
            headers=auth(token),
        )
        assert result.status_code == 200, result.text
        return result.json()

    def start(node, token, task_id, assignment_token):
        return client.post(
            f"/api/v63/node-executor/{node}/assignments/{task_id}/start",
            headers=auth(token),
            json={"assignment_lease_token": assignment_token},
        )

    make_remote("http-agent-task-1")
    first = poll("http-agent-a", token_a)
    assert first["claimed"] is True
    assert first["item"]["task"]["task_id"] == "http-agent-task-1"
    first_assignment = first["item"]["assignment"]
    assert first_assignment["node_id"] == "http-agent-a"
    assert first_assignment["resolved_execution_config"]["node_id"] == "http-agent-a"

    wrong_node = start(
        "http-agent-b", token_b, "http-agent-task-1",
        first_assignment["assignment_lease_token"],
    )
    assert wrong_node.status_code in (401, 403, 404, 409)
    started_a = start(
        "http-agent-a", token_a, "http-agent-task-1",
        first_assignment["assignment_lease_token"],
    )
    assert started_a.status_code == 200, started_a.text
    assert started_a.json()["task"]["status"] == "RUNNING"

    make_remote("http-agent-task-2")
    second = poll("http-agent-b", token_b)
    assert second["claimed"] is True
    assert second["item"]["task"]["task_id"] == "http-agent-task-2"
    second_assignment = second["item"]["assignment"]
    assert second_assignment["node_id"] == "http-agent-b"
    assert second_assignment["resolved_execution_config"]["node_id"] == "http-agent-b"
    assert second_assignment["assignment_lease_token"] != first_assignment["assignment_lease_token"]
    started_b = start(
        "http-agent-b", token_b, "http-agent-task-2",
        second_assignment["assignment_lease_token"],
    )
    assert started_b.status_code == 200, started_b.text
    assert started_b.json()["task"]["status"] == "RUNNING"

    make_remote("http-agent-task-3")
    assert poll("http-agent-a", token_a) == {"claimed": False, "item": None}
    assert poll("http-agent-b", token_b) == {"claimed": False, "item": None}
    assert repository.get("http-agent-task-3").status.value == "QUEUED"

    repository.request_cancel("http-agent-task-1")
    execution_a = started_a.json()["execution"]
    cancelled = client.post(
        "/api/v63/node-executor/http-agent-a/executions/http-agent-task-1/finish",
        headers=auth(token_a),
        json={
            "execution_lease_token": execution_a["lease_token"],
            "execution_generation": execution_a["generation"],
            "status": "CANCELLED",
        },
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["task"]["status"] == "CANCELLED"

    resumed = poll("http-agent-a", token_a)
    assert resumed["claimed"] is True
    assert resumed["item"]["task"]["task_id"] == "http-agent-task-3"
    assert resumed["item"]["assignment"]["node_id"] == "http-agent-a"
    assert repository.get("http-agent-task-2").status.value == "RUNNING"


def test_two_agents_http_strict_pin_survives_offline_and_reconnect(tmp_path, monkeypatch):
    """An Agent-only portable task pinned to a disconnected node remains
    queued, never silently spills to the other online Agent.
    """
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv("CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM", "1")
    client, repository, artifacts = client_for(tmp_path)
    _, token_a = create_node(repository, "pin-agent-a")
    nodes, token_b = create_node(repository, "pin-agent-b")
    create_task(repository, artifacts, "pin-agent-task")
    artifacts.atomic_write_json("pin-agent-task", "request.json", {
        "target": "remote",
        "epochs": 8,
        "scheduling": {
            "mode": "node",
            "node_id": "pin-agent-b",
            "queue_policy": "wait",
        },
        "remote_execution": {
            "version": 1, "task_kind": "TRAINING",
            "transport": "object-storage-v1",
        },
    })
    stale_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with repository._connect() as database:
        database.execute(
            "UPDATE service_nodes SET last_heartbeat_at=? WHERE node_id=?",
            (stale_time, "pin-agent-b"),
        )

    poll_url = "/api/v63/node-executor/{}/assignments/claim"
    online_a = client.post(poll_url.format("pin-agent-a"), headers=auth(token_a))
    assert online_a.status_code == 200, online_a.text
    assert online_a.json() == {"claimed": False, "item": None}
    offline_b = client.post(poll_url.format("pin-agent-b"), headers=auth(token_b))
    assert offline_b.status_code == 409
    assert repository.get("pin-agent-task").status.value == "QUEUED"

    nodes.heartbeat("pin-agent-b", token_b, {
        "reported_capabilities": ["training"],
        "resources": {
            "memory": {"available_bytes": 32 * 1024**3},
            "gpu": {"available": True, "gpus": [{
                "id": "cuda:0", "index": 0,
                "memory_free_bytes": 30 * 1024**3,
                "memory_total_bytes": 40 * 1024**3,
            }]},
        },
    })
    online_b = client.post(poll_url.format("pin-agent-b"), headers=auth(token_b))
    assert online_b.status_code == 200, online_b.text
    claimed = online_b.json()
    assert claimed["claimed"] is True
    assert claimed["item"]["task"]["task_id"] == "pin-agent-task"
    assert claimed["item"]["assignment"]["node_id"] == "pin-agent-b"
    assert claimed["item"]["assignment"]["resolved_execution_config"]["node_id"] == "pin-agent-b"
    assert client.post(poll_url.format("pin-agent-a"), headers=auth(token_a)).json() == {
        "claimed": False, "item": None,
    }


def test_remote_agent_recovery_diagnosis_is_read_only_and_node_scoped(tmp_path):
    """Diagnosis may expose a hold, never unlock one or reveal lease secrets."""
    from datetime import datetime, timedelta, timezone

    from platform_core.task_runtime import FencedTaskRepository

    client, repository, artifacts = client_for(tmp_path)
    create_task(repository, artifacts, task_id="remote-held")
    _, token_a = create_node(repository, node_id="gpu-api-agent")
    _, token_b = create_node(repository, node_id="gpu-api-other")

    allocator = AgentExecutionService(repository, artifacts).allocator
    assigned = allocator.assign_next()
    assert assigned is not None
    assert assigned["task_id"] == "remote-held"
    assert assigned["node_id"] == "gpu-api-agent"
    claimed = client.post(
        "/api/v63/node-executor/gpu-api-agent/assignments/claim",
        headers=auth(token_a),
    )
    assert claimed.status_code == 200
    assert claimed.json()["claimed"] is True
    started = client.post(
        "/api/v63/node-executor/gpu-api-agent/assignments/remote-held/start",
        headers=auth(token_a),
        json={
            "assignment_lease_token": claimed.json()["item"]["assignment"][
                "assignment_lease_token"
            ],
        },
    )
    assert started.status_code == 200, started.text
    generation = started.json()["execution"]["generation"]
    assert generation == 1

    expired = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    with repository._connect() as database:
        database.execute(
            "UPDATE tasks SET lease_expires_at=? WHERE task_id=?",
            (expired, "remote-held"),
        )
    assert FencedTaskRepository(repository.path).release_expired() == 0
    path = "/api/v63/node-executor/gpu-api-agent/executions/remote-held/recovery"
    response = client.get(path, headers=auth(token_a))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["task_id"] == "remote-held"
    assert result["node_id"] == "gpu-api-agent"
    assert result["execution_generation"] == generation
    assert result["task_status"] == "RUNNING"
    assert result["recovery_state"] == "STOP_PROOF_REQUIRED"
    assert result["automatic_reassignment_allowed"] is False
    assert result["stop_proof_verified"] is False
    assert "lease_token" not in str(result)
    assert "token_hash" not in str(result)

    assert client.get(path).status_code == 401
    assert client.get(path, headers=auth(token_b)).status_code == 401
    wrong_path = "/api/v63/node-executor/gpu-api-other/executions/remote-held/recovery"
    wrong = client.get(wrong_path, headers=auth(token_b))
    assert wrong.status_code in {403, 404}
    assert client.get(path.replace("remote-held", "no-such-task"), headers=auth(token_a)).status_code == 404

    task = repository.get("remote-held")
    assert task.status.value == "RUNNING"
    assert task.stage == "recovery_blocked_remote_agent_unverified"
    assert task.attempt == generation
    assert task.worker_id == "agent:gpu-api-agent"
    assert FencedTaskRepository(repository.path).release_expired() == 0


def test_remote_agent_recovery_diagnosis_refuses_nonheld_execution(tmp_path):
    client, repository, artifacts = client_for(tmp_path)
    create_task(repository, artifacts)
    _, token = create_node(repository)
    diagnosis = client.get(
        "/api/v63/node-executor/gpu-api-agent/executions/train-api-agent/recovery",
        headers=auth(token),
    )
    assert diagnosis.status_code == 409
    assert diagnosis.json()["detail"]["code"] == "REMOTE_RECOVERY_NOT_HELD"
    assert repository.get("train-api-agent").status.value == "QUEUED"
