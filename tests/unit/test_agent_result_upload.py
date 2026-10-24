from __future__ import annotations

import pytest

from platform_core.agent_execution import AgentExecutionError, AgentExecutionService
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository, TaskStatus


def runtime(tmp_path):
    repository = TaskRepository(tmp_path / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "task_runtime" / "artifacts")
    return repository, artifacts


def create_portable_deployment(repository, artifacts, task_id="deploy-agent"):
    artifacts.atomic_write_json(task_id, "request.json", {
        "model_path": "/control-plane/private/model.pt",
        "input_path": "C:\\control-plane\\private\\input.jpg",
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
    return repository.create(
        TaskRecord.new(
            task_id=task_id,
            project_id="project-deploy",
            kind=TaskKind.DEPLOYMENT_TEST,
            payload_ref="request.json",
            resource_key="deployment-runtime:pt",
        ),
        artifacts=artifacts,
    )


def create_agent_node(repository, node_id="deploy-agent-node"):
    nodes = ServiceNodeRepository(repository)
    _node, token = nodes.create({
        "node_id": node_id,
        "display_name": node_id,
        "connection_mode": "agent",
        "allowed_capabilities": ["deployment-test"],
    })
    nodes.heartbeat(node_id, token, {
        "hostname": node_id,
        "reported_capabilities": ["deployment-test"],
        "resources": {
            "cpu": {"logical_cores": 8},
            "memory": {"available_bytes": 16 * 1024**3},
            "disk": {"free_bytes": 100 * 1024**3},
            "gpu": {"available": False, "gpus": []},
        },
        "runtime": {"python_version": "3.12"},
    })
    return nodes, token


def safe_payload(task, _payload, assignment):
    return {
        "schema_version": 1,
        "task_kind": task.kind.value,
        "transport": "object-storage-v1",
        "selected_device": str(
            (assignment.get("resolved_execution_config") or {}).get("selected_device") or ""
        ),
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
            "url": "https://signed.example.test/private-result",
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
        "result_ref": "ignored-by-control-plane.json",
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


def service(repository, artifacts, *, preparer=result_preparer, confirmer=result_confirmer):
    return AgentExecutionService(
        repository,
        artifacts,
        execution_payload_resolver=safe_payload,
        result_upload_preparer=preparer,
        result_upload_confirmer=confirmer,
    )


def start_execution(repository, artifacts, svc, token, task_id="deploy-agent", node_id="deploy-agent-node"):
    assignment = svc.allocator.assign_next()
    assert assignment is not None
    assert assignment["node_id"] == node_id
    claimed = svc.claim_assignment(node_id, token)
    assert claimed is not None
    return svc.start_execution(
        node_id,
        token,
        task_id,
        claimed["assignment"]["assignment_lease_token"],
    )


def test_portable_deployment_requires_verified_result_before_finalization_or_success(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_portable_deployment(repository, artifacts)
    _nodes, token = create_agent_node(repository)
    svc = service(repository, artifacts)
    started = start_execution(repository, artifacts, svc, token)
    execution = started["execution"]

    assert started["payload"]["output"]["upload_protocol"] == "prepare-after-local-hash-v1"
    assert "upload" not in started["payload"]["output"]
    assert "/control-plane/private/model.pt" not in str(started["payload"])
    assert "C:\\control-plane\\private\\input.jpg" not in str(started["payload"])

    with pytest.raises(AgentExecutionError) as too_early:
        svc.begin_finalization(
            "deploy-agent-node",
            token,
            "deploy-agent",
            execution["lease_token"],
            execution["generation"],
        )
    assert too_early.value.code == "REMOTE_RESULT_NOT_CONFIRMED"

    with pytest.raises(AgentExecutionError) as success_without_result:
        svc.finish_execution(
            "deploy-agent-node",
            token,
            "deploy-agent",
            execution["lease_token"],
            execution["generation"],
            status="SUCCEEDED",
            result_ref="attacker.json",
        )
    assert success_without_result.value.code == "REMOTE_RESULT_NOT_CONFIRMED"

    prepared = svc.prepare_result_upload(
        "deploy-agent-node",
        token,
        "deploy-agent",
        execution["lease_token"],
        execution["generation"],
        sha256="b" * 64,
        size_bytes=1234,
    )
    assert prepared["upload"]["url"] == "https://signed.example.test/private-result"
    assert prepared["storage_ref"]["object_key"] == "results/generation-1/result.jpg"

    durable_prepare = artifacts.read_json(
        "deploy-agent",
        "remote-results/1/upload.json",
        default={},
    )
    assert durable_prepare["sha256"] == "b" * 64
    assert durable_prepare["size_bytes"] == 1234
    assert durable_prepare["confirmed"] is False
    assert "signed.example.test" not in str(durable_prepare)

    with pytest.raises(AgentExecutionError) as conflicting:
        svc.prepare_result_upload(
            "deploy-agent-node",
            token,
            "deploy-agent",
            execution["lease_token"],
            execution["generation"],
            sha256="c" * 64,
            size_bytes=1234,
        )
    assert conflicting.value.code == "REMOTE_RESULT_EVIDENCE_CONFLICT"

    confirmed = svc.confirm_result_upload(
        "deploy-agent-node",
        token,
        "deploy-agent",
        execution["lease_token"],
        execution["generation"],
        runtime_result={
            "ok": True,
            "engine": "ultralytics",
            "model": "yolo11n.pt",
            "inference_ms": 11.5,
            "detections": [{
                "class_id": 0,
                "label": "person",
                "confidence": 0.91,
                "x1": 1,
                "y1": 2,
                "x2": 30,
                "y2": 40,
                "ignored": "not persisted",
            }],
            "ignored_top_level": "not persisted",
        },
    )
    assert confirmed["result_ref"] == "remote-results/1/result.json"
    assert confirmed["result"]["execution_generation"] == 1
    assert confirmed["result"]["output_sha256"] == "b" * 64
    assert confirmed["result"]["engine"] == "ultralytics"
    assert confirmed["result"]["inference_ms"] == 11.5
    assert confirmed["result"]["detections"][0]["label"] == "person"
    assert "ignored" not in confirmed["result"]["detections"][0]
    assert "ignored_top_level" not in confirmed["result"]
    assert artifacts.read_json(
        "deploy-agent",
        "remote-results/1/upload.json",
        default={},
    )["confirmed"] is True

    finalizing = svc.begin_finalization(
        "deploy-agent-node",
        token,
        "deploy-agent",
        execution["lease_token"],
        execution["generation"],
    )
    assert finalizing["task"]["stage"] == "finalizing_commit"

    finished = svc.finish_execution(
        "deploy-agent-node",
        token,
        "deploy-agent",
        execution["lease_token"],
        execution["generation"],
        status="SUCCEEDED",
        result_ref="attacker-controlled.json",
    )
    assert finished["task"]["status"] == "SUCCEEDED"
    task = repository.get("deploy-agent")
    assert task is not None
    assert task.result_ref == "remote-results/1/result.json"
    assert task.status is TaskStatus.SUCCEEDED

    with pytest.raises(AgentExecutionError) as stale:
        svc.confirm_result_upload(
            "deploy-agent-node",
            token,
            "deploy-agent",
            execution["lease_token"],
            execution["generation"],
        )
    assert stale.value.code == "EXECUTION_FENCED"


def test_runtime_result_metadata_rejects_local_paths_and_oversize_content(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_portable_deployment(repository, artifacts, "deploy-metadata")
    _nodes, token = create_agent_node(repository)
    svc = service(repository, artifacts)
    started = start_execution(
        repository,
        artifacts,
        svc,
        token,
        task_id="deploy-metadata",
    )
    execution = started["execution"]
    svc.prepare_result_upload(
        "deploy-agent-node",
        token,
        "deploy-metadata",
        execution["lease_token"],
        execution["generation"],
        sha256="f" * 64,
        size_bytes=77,
    )

    with pytest.raises(AgentExecutionError) as leaked_path:
        svc.confirm_result_upload(
            "deploy-agent-node",
            token,
            "deploy-metadata",
            execution["lease_token"],
            execution["generation"],
            runtime_result={"model": "C:\\private\\best.pt"},
        )
    assert leaked_path.value.code == "REMOTE_RESULT_METADATA_INVALID"

    with pytest.raises(AgentExecutionError) as too_large:
        svc.confirm_result_upload(
            "deploy-agent-node",
            token,
            "deploy-metadata",
            execution["lease_token"],
            execution["generation"],
            runtime_result={"note": "x" * 70000},
        )
    assert too_large.value.code in {
        "REMOTE_RESULT_METADATA_INVALID",
        "REMOTE_RESULT_METADATA_TOO_LARGE",
    }


def test_cancellation_wins_if_requested_while_result_upload_is_being_prepared(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_portable_deployment(repository, artifacts, "deploy-cancel-prepare")
    _nodes, token = create_agent_node(repository)

    def cancelling_preparer(task, payload, evidence):
        repository.request_cancel(task.task_id)
        return result_preparer(task, payload, evidence)

    svc = service(repository, artifacts, preparer=cancelling_preparer)
    started = start_execution(
        repository,
        artifacts,
        svc,
        token,
        task_id="deploy-cancel-prepare",
    )
    execution = started["execution"]

    with pytest.raises(AgentExecutionError) as cancelled:
        svc.prepare_result_upload(
            "deploy-agent-node",
            token,
            "deploy-cancel-prepare",
            execution["lease_token"],
            execution["generation"],
            sha256="d" * 64,
            size_bytes=321,
        )
    assert cancelled.value.code == "CANCELLATION_WON"
    assert artifacts.read_json(
        "deploy-cancel-prepare",
        "remote-results/1/upload.json",
        default={},
    ) == {}
    assert repository.get("deploy-cancel-prepare").status is TaskStatus.CANCEL_REQUESTED


def test_cancellation_wins_if_requested_during_result_confirmation(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_portable_deployment(repository, artifacts, "deploy-cancel-confirm")
    _nodes, token = create_agent_node(repository)

    def cancelling_confirmer(task, payload, evidence):
        repository.request_cancel(task.task_id)
        return result_confirmer(task, payload, evidence)

    svc = service(repository, artifacts, confirmer=cancelling_confirmer)
    started = start_execution(
        repository,
        artifacts,
        svc,
        token,
        task_id="deploy-cancel-confirm",
    )
    execution = started["execution"]
    svc.prepare_result_upload(
        "deploy-agent-node",
        token,
        "deploy-cancel-confirm",
        execution["lease_token"],
        execution["generation"],
        sha256="e" * 64,
        size_bytes=654,
    )

    with pytest.raises(AgentExecutionError) as cancelled:
        svc.confirm_result_upload(
            "deploy-agent-node",
            token,
            "deploy-cancel-confirm",
            execution["lease_token"],
            execution["generation"],
        )
    assert cancelled.value.code == "CANCELLATION_WON"
    assert artifacts.read_json(
        "deploy-cancel-confirm",
        "remote-results/1/result.json",
        default={},
    ) == {}
    assert artifacts.read_json(
        "deploy-cancel-confirm",
        "remote-results/1/upload.json",
        default={},
    )["confirmed"] is False

    with pytest.raises(AgentExecutionError) as finalization:
        svc.begin_finalization(
            "deploy-agent-node",
            token,
            "deploy-cancel-confirm",
            execution["lease_token"],
            execution["generation"],
        )
    assert finalization.value.code == "CANCELLATION_WON"

    finished = svc.finish_execution(
        "deploy-agent-node",
        token,
        "deploy-cancel-confirm",
        execution["lease_token"],
        execution["generation"],
        status="CANCELLED",
    )
    assert finished["task"]["status"] == "CANCELLED"



def create_portable_conversion(repository, artifacts, task_id="convert-agent"):
    artifacts.atomic_write_json(task_id, "request.json", {
        "execution_mode": "agent",
        "remote_execution": {
            "version": 1,
            "task_kind": "MODEL_CONVERSION",
            "transport": "object-storage-v1",
            "conversion": {
                "schema_version": 1,
                "target": "onnx",
                "source": {
                    "type": "object",
                    "artifact_id": "artifact-source",
                    "storage_source_id": "s3-main",
                    "object_key": "models/source.pt",
                    "file_name": "source.pt",
                    "size_bytes": 10,
                    "sha256": "a" * 64,
                    "content_type": "application/octet-stream",
                },
                "params": {
                    "input_size": 640,
                    "batch": 1,
                    "opset": 12,
                    "dynamic": False,
                    "simplify": False,
                },
                "output": {
                    "storage_source_id": "s3-main",
                    "object_key": "conversion/model.onnx",
                    "file_name": "model.onnx",
                    "content_type": "application/octet-stream",
                },
            },
        },
    })
    return repository.create(
        TaskRecord.new(
            task_id=task_id,
            project_id="project-conversion",
            kind=TaskKind.MODEL_CONVERSION,
            payload_ref="request.json",
            resource_key="conversion:agent",
        ),
        artifacts=artifacts,
    )


def create_conversion_agent_node(repository, node_id="conversion-agent-node"):
    nodes = ServiceNodeRepository(repository)
    _node, token = nodes.create({
        "node_id": node_id,
        "display_name": node_id,
        "connection_mode": "agent",
        "allowed_capabilities": ["conversion"],
    })
    nodes.heartbeat(node_id, token, {
        "hostname": node_id,
        "reported_capabilities": ["conversion"],
        "resources": {
            "cpu": {"logical_cores": 8},
            "memory": {"available_bytes": 16 * 1024**3},
            "disk": {"free_bytes": 100 * 1024**3},
            "gpu": {"available": False, "gpus": []},
        },
        "runtime": {"python_version": "3.12"},
    })
    return nodes, token


def test_portable_conversion_requires_confirmed_result_before_finalization(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_portable_conversion(repository, artifacts)
    _nodes, token = create_conversion_agent_node(repository)
    svc = service(repository, artifacts)

    assignment = svc.allocator.assign_next()
    assert assignment is not None
    assert assignment["node_id"] == "conversion-agent-node"
    claimed = svc.claim_assignment("conversion-agent-node", token)
    assert claimed is not None
    started = svc.start_execution(
        "conversion-agent-node",
        token,
        "convert-agent",
        claimed["assignment"]["assignment_lease_token"],
    )
    execution = started["execution"]

    with pytest.raises(AgentExecutionError) as early:
        svc.begin_finalization(
            "conversion-agent-node",
            token,
            "convert-agent",
            execution["lease_token"],
            execution["generation"],
        )
    assert early.value.code == "REMOTE_RESULT_NOT_CONFIRMED"

    svc.prepare_result_upload(
        "conversion-agent-node",
        token,
        "convert-agent",
        execution["lease_token"],
        execution["generation"],
        sha256="7" * 64,
        size_bytes=777,
    )
    confirmed = svc.confirm_result_upload(
        "conversion-agent-node",
        token,
        "convert-agent",
        execution["lease_token"],
        execution["generation"],
    )
    assert confirmed["confirmed"] is True
    assert confirmed["result_ref"] == "remote-results/1/result.json"

    finalizing = svc.begin_finalization(
        "conversion-agent-node",
        token,
        "convert-agent",
        execution["lease_token"],
        execution["generation"],
    )
    assert finalizing["task"]["stage"] == "finalizing_commit"


def create_portable_training(repository, artifacts, task_id="train-agent"):
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
                "snapshot_id": "snapshot-one",
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
    return repository.create(
        TaskRecord.new(
            task_id=task_id,
            project_id="project-training",
            kind=TaskKind.TRAINING,
            payload_ref="payload.json",
            resource_key="training:remote:scheduler",
            required_capabilities=("training.ultralytics",),
        ),
        artifacts=artifacts,
    )


def create_training_agent_node(repository, node_id="training-agent-node"):
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
            "cpu": {"logical_cores": 16},
            "memory": {"available_bytes": 32 * 1024**3},
            "disk": {"free_bytes": 500 * 1024**3},
            "gpu": {
                "available": True,
                "gpus": [{
                    "id": "cuda:0",
                    "index": 0,
                    "uuid": "GPU-TRAIN",
                    "name": "NVIDIA Test",
                    "memory_free_bytes": 20 * 1024**3,
                    "memory_total_bytes": 24 * 1024**3,
                }],
            },
        },
        "runtime": {"python_version": "3.12"},
    })
    return nodes, token


def training_safe_payload(task, _payload, assignment):
    resolved = assignment.get("resolved_execution_config") or {}
    return {
        "schema_version": 1,
        "task_kind": "TRAINING",
        "transport": "object-storage-v1",
        "framework": "ultralytics",
        "algorithm_id": "algorithm-one",
        "snapshot_id": "snapshot-one",
        "selected_device": resolved.get("selected_device") or "cuda:0",
        "selected_gpu": resolved.get("selected_gpu"),
        "bundle": {"type": "object", "download": {"sha256": "a" * 64, "size_bytes": 100}},
        "model": {"type": "official", "reference": "yolo11n.pt"},
        "params": {"epochs": 1},
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
            "role": role,
            "file_name": str(item["file_name"]),
            "sha256": str(item["sha256"]),
            "size_bytes": int(item["size_bytes"]),
            "artifact_id": f"artifact-{role}",
            "storage_ref": {
                "storage_source_id": "s3-main",
                "object_key": f"model-assets/rt-one/{role}.pt",
                "file_name": str(item["file_name"]),
                "content_type": "application/octet-stream",
            },
            "already_uploaded": False,
            "upload": {
                "method": "PUT",
                "url": f"https://signed.example.test/{role}",
                "headers": {
                    "Content-Length": str(int(item["size_bytes"])),
                    "x-amz-meta-sha256": str(item["sha256"]),
                    "If-None-Match": "*",
                },
            },
        })
    return {
        "version_id": "rt-one",
        "execution_generation": int(execution_generation),
        "items": items,
    }


def training_model_confirmer(_task, _payload, *, execution_generation, models):
    return {
        "version_id": "rt-one",
        "execution_generation": int(execution_generation),
        "confirmed": True,
        "items": [dict(item) for item in models],
    }


def training_result_confirmer(task, _payload, evidence):
    return {
        "result": {
            "task_id": task.task_id,
            "project_id": task.project_id,
            "snapshot_id": "snapshot-one",
            "training_outcome": "completed",
            "verified_models": [
                {
                    "role": "best",
                    "ref": "models/best.pt",
                    "file_name": "best.pt",
                    "sha256": "d" * 64,
                    "size_bytes": 101,
                },
                {
                    "role": "last",
                    "ref": "models/last.pt",
                    "file_name": "last.pt",
                    "sha256": "e" * 64,
                    "size_bytes": 102,
                },
            ],
            "output_sha256": evidence["sha256"],
            "output_size_bytes": evidence["size_bytes"],
        },
    }


def training_service(repository, artifacts, *, result_confirmer=training_result_confirmer, commits=None):
    commit_log = commits if commits is not None else []

    def commit_handler(task, _payload, _evidence, confirmed):
        current = repository.get(task.task_id)
        assert current is not None
        assert current.stage == "finalizing_commit"
        commit_log.append({
            "task_id": task.task_id,
            "training_models": confirmed.get("training_models"),
        })
        return {
            "algorithm_id": "algorithm-one",
            "version_id": str((confirmed.get("training_models") or {}).get("version_id") or ""),
            "model_artifacts_committed": True,
        }

    return AgentExecutionService(
        repository,
        artifacts,
        execution_payload_resolver=training_safe_payload,
        result_upload_preparer=result_preparer,
        result_upload_confirmer=result_confirmer,
        result_commit_handler=commit_handler,
        training_model_upload_preparer=training_model_preparer,
        training_model_upload_confirmer=training_model_confirmer,
    )


def start_training_execution(repository, artifacts, svc, token, task_id="train-agent", node_id="training-agent-node"):
    assignment = svc.allocator.assign_next()
    assert assignment is not None
    assert assignment["node_id"] == node_id
    claimed = svc.claim_assignment(node_id, token)
    assert claimed is not None
    return svc.start_execution(
        node_id,
        token,
        task_id,
        claimed["assignment"]["assignment_lease_token"],
    )


def _training_models():
    return [
        {"role": "best", "file_name": "best.pt", "sha256": "d" * 64, "size_bytes": 101},
        {"role": "last", "file_name": "last.pt", "sha256": "e" * 64, "size_bytes": 102},
    ]


def test_remote_training_models_are_generation_fenced_and_required_before_result_commit(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_portable_training(repository, artifacts)
    _nodes, token = create_training_agent_node(repository)
    commits = []
    svc = training_service(repository, artifacts, commits=commits)
    started = start_training_execution(repository, artifacts, svc, token)
    execution = started["execution"]

    svc.prepare_result_upload(
        "training-agent-node",
        token,
        "train-agent",
        execution["lease_token"],
        execution["generation"],
        sha256="f" * 64,
        size_bytes=77,
    )
    with pytest.raises(AgentExecutionError) as missing_models:
        svc.confirm_result_upload(
            "training-agent-node",
            token,
            "train-agent",
            execution["lease_token"],
            execution["generation"],
        )
    assert missing_models.value.code == "REMOTE_TRAINING_MODELS_NOT_CONFIRMED"
    assert repository.get("train-agent").stage != "finalizing_commit"
    assert commits == []

    prepared = svc.prepare_training_model_uploads(
        "training-agent-node",
        token,
        "train-agent",
        execution["lease_token"],
        execution["generation"],
        models=_training_models(),
    )
    assert prepared["version_id"] == "rt-one"
    durable = artifacts.read_json(
        "train-agent",
        f"remote-results/{execution['generation']}/training-models.json",
        default={},
    )
    assert durable["confirmed"] is False
    assert durable["models"][0]["role"] == "best"
    assert "signed.example.test" not in str(durable)

    with pytest.raises(AgentExecutionError) as conflict:
        svc.prepare_training_model_uploads(
            "training-agent-node",
            token,
            "train-agent",
            execution["lease_token"],
            execution["generation"],
            models=[
                {"role": "best", "file_name": "best.pt", "sha256": "1" * 64, "size_bytes": 101},
                {"role": "last", "file_name": "last.pt", "sha256": "e" * 64, "size_bytes": 102},
            ],
        )
    assert conflict.value.code == "REMOTE_TRAINING_MODEL_EVIDENCE_CONFLICT"

    confirmed_models = svc.confirm_training_model_uploads(
        "training-agent-node",
        token,
        "train-agent",
        execution["lease_token"],
        execution["generation"],
    )
    assert confirmed_models["confirmed"] is True
    assert confirmed_models["version_id"] == "rt-one"

    confirmed = svc.confirm_result_upload(
        "training-agent-node",
        token,
        "train-agent",
        execution["lease_token"],
        execution["generation"],
    )
    assert confirmed["confirmed"] is True
    assert confirmed["result"]["version_id"] == "rt-one"
    assert confirmed["result"]["model_artifacts_committed"] is True
    assert commits and commits[0]["task_id"] == "train-agent"
    assert commits[0]["training_models"]["version_id"] == "rt-one"
    assert repository.get("train-agent").stage == "finalizing_commit"


def test_remote_training_result_manifest_must_match_confirmed_model_objects(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_portable_training(repository, artifacts, "train-mismatch")
    _nodes, token = create_training_agent_node(repository)

    def mismatching_result(task, payload, evidence):
        result = training_result_confirmer(task, payload, evidence)
        result["result"]["verified_models"][0]["sha256"] = "9" * 64
        return result

    svc = training_service(repository, artifacts, result_confirmer=mismatching_result)
    started = start_training_execution(
        repository,
        artifacts,
        svc,
        token,
        task_id="train-mismatch",
    )
    execution = started["execution"]
    svc.prepare_training_model_uploads(
        "training-agent-node",
        token,
        "train-mismatch",
        execution["lease_token"],
        execution["generation"],
        models=_training_models(),
    )
    svc.confirm_training_model_uploads(
        "training-agent-node",
        token,
        "train-mismatch",
        execution["lease_token"],
        execution["generation"],
    )
    svc.prepare_result_upload(
        "training-agent-node",
        token,
        "train-mismatch",
        execution["lease_token"],
        execution["generation"],
        sha256="f" * 64,
        size_bytes=77,
    )

    with pytest.raises(AgentExecutionError) as mismatch:
        svc.confirm_result_upload(
            "training-agent-node",
            token,
            "train-mismatch",
            execution["lease_token"],
            execution["generation"],
        )
    assert mismatch.value.code == "REMOTE_TRAINING_RESULT_MODELS_MISMATCH"
    current = repository.get("train-mismatch")
    assert current is not None
    assert current.status is TaskStatus.RUNNING
    assert current.stage != "finalizing_commit"


def test_remote_training_model_uploads_reject_stale_generation_and_cancellation(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_portable_training(repository, artifacts, "train-fenced-models")
    _nodes, token = create_training_agent_node(repository)
    svc = training_service(repository, artifacts)
    started = start_training_execution(
        repository,
        artifacts,
        svc,
        token,
        task_id="train-fenced-models",
    )
    execution = started["execution"]

    with pytest.raises(AgentExecutionError) as stale:
        svc.prepare_training_model_uploads(
            "training-agent-node",
            token,
            "train-fenced-models",
            execution["lease_token"],
            execution["generation"] + 1,
            models=_training_models(),
        )
    assert stale.value.code == "EXECUTION_FENCED"

    repository.request_cancel("train-fenced-models")
    with pytest.raises(AgentExecutionError) as cancelled:
        svc.prepare_training_model_uploads(
            "training-agent-node",
            token,
            "train-fenced-models",
            execution["lease_token"],
            execution["generation"],
            models=_training_models(),
        )
    assert cancelled.value.code == "CANCELLATION_WON"



def create_portable_material_import(repository, artifacts, task_id="material-agent"):
    artifacts.atomic_write_json(task_id, "request.json", {
        "execution_mode": "agent",
        "remote_execution": {
            "version": 1,
            "task_kind": "MATERIAL_IMPORT",
            "transport": "object-storage-v1",
            "material_import": {
                "mode": "zip_scan",
                "output": {
                    "storage_source_id": "s3-main",
                    "object_key": "material-review/review.zip",
                    "file_name": "material-review.zip",
                    "content_type": "application/zip",
                },
            },
        },
    })
    return repository.create(
        TaskRecord.new(
            task_id=task_id,
            project_id="project-material",
            kind=TaskKind.MATERIAL_IMPORT,
            payload_ref="request.json",
            resource_key="material-import:agent",
            required_capabilities=("agent.remote",),
        ),
        artifacts=artifacts,
    )


def create_material_agent_node(repository, node_id="material-agent-node"):
    nodes = ServiceNodeRepository(repository)
    _node, token = nodes.create({
        "node_id": node_id,
        "display_name": node_id,
        "connection_mode": "agent",
        "allowed_capabilities": ["material-import"],
    })
    nodes.heartbeat(node_id, token, {
        "hostname": node_id,
        "reported_capabilities": ["material-import"],
        "resources": {
            "cpu": {"logical_cores": 8},
            "memory": {"available_bytes": 16 * 1024**3},
            "disk": {"free_bytes": 100 * 1024**3},
            "gpu": {"available": False, "gpus": []},
        },
        "runtime": {"python_version": "3.12"},
    })
    return nodes, token


def test_portable_material_import_requires_confirmed_review_before_awaiting_confirmation(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_portable_material_import(repository, artifacts)
    _nodes, token = create_material_agent_node(repository)
    svc = service(repository, artifacts)

    assignment = svc.allocator.assign_next()
    assert assignment is not None
    assert assignment["node_id"] == "material-agent-node"
    claimed = svc.claim_assignment("material-agent-node", token)
    started = svc.start_execution(
        "material-agent-node",
        token,
        "material-agent",
        claimed["assignment"]["assignment_lease_token"],
    )
    execution = started["execution"]

    with pytest.raises(AgentExecutionError) as unconfirmed:
        svc.finish_execution(
            "material-agent-node",
            token,
            "material-agent",
            execution["lease_token"],
            execution["generation"],
            status="AWAITING_CONFIRMATION",
            result_ref="attacker.json",
        )
    assert unconfirmed.value.code == "REMOTE_RESULT_NOT_CONFIRMED"

    svc.prepare_result_upload(
        "material-agent-node",
        token,
        "material-agent",
        execution["lease_token"],
        execution["generation"],
        sha256="d" * 64,
        size_bytes=4321,
    )
    confirmed = svc.confirm_result_upload(
        "material-agent-node",
        token,
        "material-agent",
        execution["lease_token"],
        execution["generation"],
        runtime_result={
            "ok": True,
            "engine": "material-import",
            "note": "review_bundle_verified",
        },
    )
    assert confirmed["confirmed"] is True
    assert confirmed["result_ref"] == "remote-results/1/result.json"

    finished = svc.finish_execution(
        "material-agent-node",
        token,
        "material-agent",
        execution["lease_token"],
        execution["generation"],
        status="AWAITING_CONFIRMATION",
        result_ref="attacker.json",
    )
    task = repository.get("material-agent")
    assert finished["task"]["status"] == "AWAITING_CONFIRMATION"
    assert task is not None
    assert task.status is TaskStatus.AWAITING_CONFIRMATION
    assert task.stage == "awaiting_confirmation"
    assert task.result_ref == "remote-results/1/result.json"
    assert task.finished_at is None


def test_only_material_import_may_finish_remote_execution_as_awaiting_confirmation(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_portable_deployment(repository, artifacts)
    _nodes, token = create_agent_node(repository)
    svc = service(repository, artifacts)
    started = start_execution(repository, artifacts, svc, token)
    execution = started["execution"]

    svc.prepare_result_upload(
        "deploy-agent-node",
        token,
        "deploy-agent",
        execution["lease_token"],
        execution["generation"],
        sha256="e" * 64,
        size_bytes=111,
    )
    svc.confirm_result_upload(
        "deploy-agent-node",
        token,
        "deploy-agent",
        execution["lease_token"],
        execution["generation"],
    )

    with pytest.raises(AgentExecutionError) as invalid:
        svc.finish_execution(
            "deploy-agent-node",
            token,
            "deploy-agent",
            execution["lease_token"],
            execution["generation"],
            status="AWAITING_CONFIRMATION",
        )
    assert invalid.value.code == "INVALID_FINISH_STATUS"


def test_remote_result_protocol_accepts_only_clean_material_batch_subtype():
    clean = TaskRecord.new(
        task_id="clean-protocol",
        project_id="project-clean",
        kind=TaskKind.MATERIAL_BATCH,
        payload_ref="request.json",
        resource_key="materials:project-clean",
    )
    portable = {
        "operation": "CLEAN",
        "execution_mode": "agent",
        "remote_execution": {
            "version": 1,
            "task_kind": "MATERIAL_BATCH",
            "transport": "object-storage-v1",
        },
    }
    assert AgentExecutionService._requires_remote_result_confirmation(clean, portable) is True
    assert AgentExecutionService._requires_remote_result_confirmation(
        clean,
        {**portable, "operation": "ADD_LABELS"},
    ) is False
    assert AgentExecutionService._requires_remote_result_confirmation(
        clean,
        {"operation": "CLEAN", "execution_mode": "agent"},
    ) is False
