from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from platform_core.agent_execution import AgentExecutionService, agent_executor_router
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository


def safe_payload(task, _payload, _assignment):
    return {
        "schema_version": 1,
        "task_kind": task.kind.value,
        "transport": "object-storage-v1",
        "output": {
            "type": "object",
            "storage_ref": {
                "storage_source_id": "s3-main",
                "object_key": "results/result.jpg",
                "file_name": "result.jpg",
                "content_type": "image/jpeg",
            },
            "upload_protocol": "prepare-after-local-hash-v1",
        },
    }


def result_preparer(_task, _payload, evidence):
    generation = int(evidence["execution_generation"])
    return {
        "already_uploaded": False,
        "storage_ref": {
            "storage_source_id": "s3-main",
            "object_key": f"results/generation-{generation}/result.jpg",
            "file_name": "result.jpg",
            "content_type": "image/jpeg",
        },
        "sha256": evidence["sha256"],
        "size_bytes": evidence["size_bytes"],
        "upload": {
            "method": "PUT",
            "url": "https://signed.example.test/result",
            "headers": {
                "Content-Length": str(evidence["size_bytes"]),
                "x-amz-meta-sha256": evidence["sha256"],
                "If-None-Match": "*",
            },
            "overwrite_protected": True,
        },
    }


def result_confirmer(task, _payload, evidence):
    generation = int(evidence["execution_generation"])
    return {
        "result": {
            "task_id": task.task_id,
            "project_id": task.project_id,
            "remote_execution": True,
            "output_storage": {
                "storage_source_id": "s3-main",
                "object_key": f"results/generation-{generation}/result.jpg",
                "file_name": "result.jpg",
                "content_type": "image/jpeg",
            },
            "output_sha256": evidence["sha256"],
            "output_size_bytes": evidence["size_bytes"],
        },
    }


def client_for(tmp_path):
    repository = TaskRepository(tmp_path / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "task_runtime" / "artifacts")
    app = FastAPI()
    app.include_router(agent_executor_router(
        lambda: repository,
        lambda: artifacts,
        execution_payload_resolver=safe_payload,
        result_upload_preparer=result_preparer,
        result_upload_confirmer=result_confirmer,
    ))
    return TestClient(app), repository, artifacts


def create_task(repository, artifacts):
    task_id = "deploy-result-api"
    artifacts.atomic_write_json(task_id, "request.json", {
        "remote_execution": {
            "version": 1,
            "task_kind": "DEPLOYMENT_TEST",
            "transport": "object-storage-v1",
            "deployment": {
                "framework": "ultralytics",
                "runtime_format": "pt",
                "confidence": 0.25,
                "input": {
                    "storage_source_id": "s3-main",
                    "object_key": "inputs/input.jpg",
                    "file_name": "input.jpg",
                    "size_bytes": 10,
                    "sha256": "a" * 64,
                    "content_type": "image/jpeg",
                },
                "model": {"type": "official", "reference": "yolo11n.pt"},
                "output": {
                    "storage_source_id": "s3-main",
                    "object_key": "results/result.jpg",
                    "file_name": "result.jpg",
                    "content_type": "image/jpeg",
                },
            },
        },
    })
    repository.create(
        TaskRecord.new(
            task_id=task_id,
            project_id="project-result-api",
            kind=TaskKind.DEPLOYMENT_TEST,
            payload_ref="request.json",
            resource_key="deployment-runtime:pt",
        ),
        artifacts=artifacts,
    )


def create_node(repository):
    nodes = ServiceNodeRepository(repository)
    _node, token = nodes.create({
        "node_id": "deploy-api-agent",
        "display_name": "deploy-api-agent",
        "connection_mode": "agent",
        "allowed_capabilities": ["deployment-test"],
    })
    nodes.heartbeat("deploy-api-agent", token, {
        "hostname": "deploy-api-agent",
        "reported_capabilities": ["deployment-test"],
        "resources": {
            "cpu": {"logical_cores": 8},
            "memory": {"available_bytes": 16 * 1024**3},
            "disk": {"free_bytes": 100 * 1024**3},
            "gpu": {"available": False, "gpus": []},
        },
        "runtime": {"python_version": "3.12"},
    })
    return token


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def start_remote(client, repository, artifacts, token):
    allocator = AgentExecutionService(repository, artifacts).allocator
    assigned = allocator.assign_next()
    assert assigned is not None

    claimed = client.post(
        "/api/v63/node-executor/deploy-api-agent/assignments/claim",
        headers=auth(token),
    )
    assert claimed.status_code == 200, claimed.text
    assignment_token = claimed.json()["item"]["assignment"]["assignment_lease_token"]

    started = client.post(
        "/api/v63/node-executor/deploy-api-agent/assignments/deploy-result-api/start",
        headers=auth(token),
        json={"assignment_lease_token": assignment_token},
    )
    assert started.status_code == 200, started.text
    return started.json()["execution"]


def execution_body(execution):
    return {
        "execution_lease_token": execution["lease_token"],
        "execution_generation": execution["generation"],
    }


def test_result_upload_http_protocol_requires_confirm_before_success(tmp_path):
    client, repository, artifacts = client_for(tmp_path)
    create_task(repository, artifacts)
    token = create_node(repository)
    execution = start_remote(client, repository, artifacts, token)
    base = "/api/v63/node-executor/deploy-api-agent/executions/deploy-result-api"

    premature = client.post(
        f"{base}/begin-finalization",
        headers=auth(token),
        json=execution_body(execution),
    )
    assert premature.status_code == 409
    assert premature.json()["detail"]["code"] == "REMOTE_RESULT_NOT_CONFIRMED"

    invalid = client.post(
        f"{base}/result-upload/prepare",
        headers=auth(token),
        json={
            **execution_body(execution),
            "sha256": "bad",
            "size_bytes": 123,
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "REMOTE_RESULT_EVIDENCE_INVALID"

    prepared = client.post(
        f"{base}/result-upload/prepare",
        headers=auth(token),
        json={
            **execution_body(execution),
            "sha256": "b" * 64,
            "size_bytes": 123,
        },
    )
    assert prepared.status_code == 200, prepared.text
    prepare_body = prepared.json()
    assert prepare_body["confirmed"] is False
    assert prepare_body["storage_ref"]["object_key"] == "results/generation-1/result.jpg"
    assert prepare_body["upload"]["url"] == "https://signed.example.test/result"

    durable = artifacts.read_json(
        "deploy-result-api",
        "remote-results/1/upload.json",
        default={},
    )
    assert durable["sha256"] == "b" * 64
    assert "signed.example.test" not in str(durable)

    confirmed = client.post(
        f"{base}/result-upload/confirm",
        headers=auth(token),
        json={
            **execution_body(execution),
            "runtime_result": {
                "engine": "ultralytics",
                "model": "yolo11n.pt",
                "elapsed_ms": 22.5,
                "detections": [{"class_id": 0, "label": "person", "confidence": 0.9}],
            },
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["result_ref"] == "remote-results/1/result.json"
    assert confirmed.json()["result"]["execution_generation"] == 1
    assert confirmed.json()["result"]["engine"] == "ultralytics"
    assert confirmed.json()["result"]["model"] == "yolo11n.pt"

    finalizing = client.post(
        f"{base}/begin-finalization",
        headers=auth(token),
        json=execution_body(execution),
    )
    assert finalizing.status_code == 200, finalizing.text
    assert finalizing.json()["task"]["stage"] == "finalizing_commit"

    finished = client.post(
        f"{base}/finish",
        headers=auth(token),
        json={
            **execution_body(execution),
            "status": "SUCCEEDED",
            "result_ref": "attacker.json",
        },
    )
    assert finished.status_code == 200, finished.text
    assert finished.json()["task"]["status"] == "SUCCEEDED"

    task = repository.get("deploy-result-api")
    assert task is not None
    assert task.result_ref == "remote-results/1/result.json"
    result = artifacts.read_json(task.task_id, task.result_ref, default={})
    assert result["output_sha256"] == "b" * 64
    assert result["output_size_bytes"] == 123


def test_result_upload_http_protocol_is_execution_fenced(tmp_path):
    client, repository, artifacts = client_for(tmp_path)
    create_task(repository, artifacts)
    token = create_node(repository)
    execution = start_remote(client, repository, artifacts, token)
    base = "/api/v63/node-executor/deploy-api-agent/executions/deploy-result-api"

    repository.request_cancel("deploy-result-api")
    cancelled = client.post(
        f"{base}/result-upload/prepare",
        headers=auth(token),
        json={
            **execution_body(execution),
            "sha256": "c" * 64,
            "size_bytes": 50,
        },
    )
    assert cancelled.status_code == 409
    assert cancelled.json()["detail"]["code"] == "CANCELLATION_WON"

    wrong_generation = client.post(
        f"{base}/result-upload/confirm",
        headers=auth(token),
        json={
            "execution_lease_token": execution["lease_token"],
            "execution_generation": execution["generation"] + 1,
        },
    )
    assert wrong_generation.status_code == 409
    assert wrong_generation.json()["detail"]["code"] == "EXECUTION_FENCED"



def training_payload_resolver(task, _payload, assignment):
    resolved = assignment.get("resolved_execution_config") or {}
    return {
        "schema_version": 1,
        "task_kind": "TRAINING",
        "transport": "object-storage-v1",
        "framework": "ultralytics",
        "snapshot_id": "snapshot-api",
        "selected_device": resolved.get("selected_device") or "cuda:0",
        "result": {
            "type": "object",
            "storage_ref": {
                "storage_source_id": "s3-main",
                "object_key": "training-result.zip",
                "file_name": "training-result.zip",
                "content_type": "application/zip",
            },
            "upload_protocol": "prepare-after-local-hash-v1",
        },
    }


def training_model_preparer(_task, _payload, *, execution_generation, models):
    items = []
    for item in models:
        role = str(item["role"])
        items.append({
            **dict(item),
            "artifact_id": f"artifact-{role}",
            "storage_ref": {
                "storage_source_id": "s3-main",
                "object_key": f"model-assets/rt-api/{role}.pt",
                "file_name": str(item["file_name"]),
                "content_type": "application/octet-stream",
            },
            "already_uploaded": False,
            "upload": {
                "method": "PUT",
                "url": f"https://signed.example.test/{role}",
                "headers": {
                    "Content-Length": str(item["size_bytes"]),
                    "x-amz-meta-sha256": str(item["sha256"]),
                    "If-None-Match": "*",
                },
            },
        })
    return {
        "version_id": "rt-api",
        "execution_generation": int(execution_generation),
        "items": items,
    }


def training_model_confirmer(_task, _payload, *, execution_generation, models):
    return {
        "confirmed": True,
        "version_id": "rt-api",
        "execution_generation": int(execution_generation),
        "items": [dict(item) for item in models],
    }


def training_client_for(tmp_path):
    repository = TaskRepository(tmp_path / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "task_runtime" / "artifacts")
    app = FastAPI()
    app.include_router(agent_executor_router(
        lambda: repository,
        lambda: artifacts,
        execution_payload_resolver=training_payload_resolver,
        result_upload_preparer=result_preparer,
        result_upload_confirmer=result_confirmer,
        training_model_upload_preparer=training_model_preparer,
        training_model_upload_confirmer=training_model_confirmer,
    ))
    return TestClient(app), repository, artifacts


def create_training_task(repository, artifacts):
    task_id = "train-model-api"
    artifacts.atomic_write_json(task_id, "payload.json", {
        "target": "remote",
        "algorithm_asset_id": "algorithm-one",
        "remote_execution": {
            "version": 1,
            "task_kind": "TRAINING",
            "transport": "object-storage-v1",
            "training": {
                "schema_version": 1,
                "framework": "ultralytics",
                "snapshot_id": "snapshot-api",
                "bundle": {"storage_source_id": "s3-main", "object_key": "bundle.zip"},
                "model": {"type": "official", "reference": "yolo11n.pt"},
                "result": {
                    "storage_source_id": "s3-main",
                    "object_key": "training-result.zip",
                    "file_name": "training-result.zip",
                    "content_type": "application/zip",
                },
            },
        },
    })
    repository.create(
        TaskRecord.new(
            task_id=task_id,
            project_id="project-training-api",
            kind=TaskKind.TRAINING,
            payload_ref="payload.json",
            resource_key="training:remote:scheduler",
            required_capabilities=("training.ultralytics",),
        ),
        artifacts=artifacts,
    )


def create_training_node(repository):
    nodes = ServiceNodeRepository(repository)
    _node, token = nodes.create({
        "node_id": "training-api-agent",
        "display_name": "training-api-agent",
        "connection_mode": "agent",
        "allowed_capabilities": ["training"],
    })
    nodes.heartbeat("training-api-agent", token, {
        "hostname": "training-api-agent",
        "reported_capabilities": ["training"],
        "resources": {
            "cpu": {"logical_cores": 16},
            "memory": {"available_bytes": 32 * 1024**3},
            "disk": {"free_bytes": 100 * 1024**3},
            "gpu": {
                "available": True,
                "gpus": [{
                    "id": "cuda:0",
                    "index": 0,
                    "uuid": "GPU-API",
                    "name": "NVIDIA Test",
                    "memory_free_bytes": 16 * 1024**3,
                    "memory_total_bytes": 24 * 1024**3,
                }],
            },
        },
        "runtime": {"python_version": "3.12"},
    })
    return token


def start_training_remote(client, repository, artifacts, token):
    allocator = AgentExecutionService(repository, artifacts).allocator
    assigned = allocator.assign_next()
    assert assigned is not None
    claimed = client.post(
        "/api/v63/node-executor/training-api-agent/assignments/claim",
        headers=auth(token),
    )
    assert claimed.status_code == 200, claimed.text
    assignment_token = claimed.json()["item"]["assignment"]["assignment_lease_token"]
    started = client.post(
        "/api/v63/node-executor/training-api-agent/assignments/train-model-api/start",
        headers=auth(token),
        json={"assignment_lease_token": assignment_token},
    )
    assert started.status_code == 200, started.text
    return started.json()["execution"]


def test_training_model_upload_http_routes_are_execution_fenced(tmp_path):
    client, repository, artifacts = training_client_for(tmp_path)
    create_training_task(repository, artifacts)
    token = create_training_node(repository)
    execution = start_training_remote(client, repository, artifacts, token)
    base = "/api/v63/node-executor/training-api-agent/executions/train-model-api"
    models = [
        {"role": "best", "file_name": "best.pt", "sha256": "d" * 64, "size_bytes": 101},
        {"role": "last", "file_name": "last.pt", "sha256": "e" * 64, "size_bytes": 102},
    ]

    wrong_generation = client.post(
        f"{base}/training-models/prepare",
        headers=auth(token),
        json={
            "execution_lease_token": execution["lease_token"],
            "execution_generation": execution["generation"] + 1,
            "models": models,
        },
    )
    assert wrong_generation.status_code == 409
    assert wrong_generation.json()["detail"]["code"] == "EXECUTION_FENCED"

    prepared = client.post(
        f"{base}/training-models/prepare",
        headers=auth(token),
        json={
            **execution_body(execution),
            "models": models,
        },
    )
    assert prepared.status_code == 200, prepared.text
    body = prepared.json()
    assert body["version_id"] == "rt-api"
    assert {item["role"] for item in body["items"]} == {"best", "last"}
    assert all(item["upload"]["method"] == "PUT" for item in body["items"])

    durable = artifacts.read_json(
        "train-model-api",
        f"remote-results/{execution['generation']}/training-models.json",
        default={},
    )
    assert durable["confirmed"] is False
    assert "signed.example.test" not in str(durable)

    confirmed = client.post(
        f"{base}/training-models/confirm",
        headers=auth(token),
        json=execution_body(execution),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["confirmed"] is True
    assert confirmed.json()["version_id"] == "rt-api"

    repository.request_cancel("train-model-api")
    after_cancel = client.post(
        f"{base}/training-models/confirm",
        headers=auth(token),
        json=execution_body(execution),
    )
    assert after_cancel.status_code == 409
    assert after_cancel.json()["detail"]["code"] == "CANCELLATION_WON"
