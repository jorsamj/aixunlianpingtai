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
    )
    assert confirmed["result_ref"] == "remote-results/1/result.json"
    assert confirmed["result"]["execution_generation"] == 1
    assert confirmed["result"]["output_sha256"] == "b" * 64
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
