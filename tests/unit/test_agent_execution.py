from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from platform_core.agent_execution import (
    AgentExecutionError,
    AgentExecutionService,
    MAX_REMOTE_LOG_BYTES,
)
from platform_core.service_nodes import ServiceNodeError, ServiceNodeRepository
from platform_core.task_node_assignments import CentralTaskAllocator
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository, TaskStatus


def runtime(tmp_path):
    repository = TaskRepository(tmp_path / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "task_runtime" / "artifacts")
    return repository, artifacts


def create_task(repository, artifacts, task_id="train-agent", *, write_payload=True):
    if write_payload:
        artifacts.atomic_write_json(task_id, "request.json", {"epochs": 30, "imgsz": 640})
    return repository.create(
        TaskRecord.new(
            task_id=task_id,
            project_id="project-agent",
            kind=TaskKind.TRAINING,
            payload_ref="request.json",
            resource_key=f"training:{task_id}",
        ),
        artifacts=artifacts,
    )


def create_node(repository, node_id="gpu-agent", *, enabled=True):
    nodes = ServiceNodeRepository(repository)
    _node, token = nodes.create({
        "node_id": node_id,
        "display_name": node_id,
        "enabled": enabled,
        "allowed_capabilities": ["training"],
    })
    nodes.heartbeat(node_id, token, {
        "hostname": node_id,
        "build_id": f"build-{node_id}",
        "reported_capabilities": ["training"],
        "resources": {
            "memory": {"available_bytes": 32 * 1024**3},
            "gpu": {
                "available": True,
                "gpus": [{
                    "id": "cuda:0",
                    "index": 0,
                    "uuid": f"GPU-{node_id}",
                    "name": "NVIDIA A800",
                    "memory_free_bytes": 30 * 1024**3,
                    "memory_total_bytes": 40 * 1024**3,
                }],
            },
        },
        "runtime": {"torch_version": "2.5.0+cu124", "cuda_version": "12.4"},
    })
    return nodes, token


def allocate_claim(service, task_id, node_id, token):
    assignment = service.allocator.assign_next()
    assert assignment is not None
    assert assignment["task_id"] == task_id
    assert assignment["node_id"] == node_id
    claimed = service.claim_assignment(node_id, token)
    assert claimed is not None
    assert claimed["assignment"]["task_id"] == task_id
    return claimed


def start(service, task_id, node_id, token, claimed):
    return service.start_execution(
        node_id,
        token,
        task_id,
        claimed["assignment"]["assignment_lease_token"],
    )


def test_agent_start_is_single_atomic_queued_to_running_transition(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts)
    _nodes, token = create_node(repository)
    service = AgentExecutionService(repository, artifacts)
    claimed = allocate_claim(service, "train-agent", "gpu-agent", token)

    started = start(service, "train-agent", "gpu-agent", token, claimed)

    task = repository.get("train-agent")
    assert task is not None
    assert task.status is TaskStatus.RUNNING
    assert task.attempt == 1
    assert task.worker_id == "agent:gpu-agent"
    assert task.lease_expires_at
    assert started["execution"]["generation"] == 1
    assert started["execution"]["lease_token"]
    assert started["payload"] == {"epochs": 30, "imgsz": 640}
    assert started["transport"] == {
        "protocol": "agent-http-control-v1",
        "large_artifacts": "object-storage-required",
        "shared_sqlite_required": False,
        "shared_nfs_required": False,
    }
    history = service.allocator.list(active_only=False)
    assert history[0]["state"] == "RELEASED"
    assert history[0]["release_reason"] == "execution_started"
    assert service.allocator.list(active_only=True) == []


def test_invalid_assignment_token_and_duplicate_start_are_fenced(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts)
    _nodes, token = create_node(repository)
    service = AgentExecutionService(repository, artifacts)
    claimed = allocate_claim(service, "train-agent", "gpu-agent", token)

    with pytest.raises(AgentExecutionError) as bad:
        service.start_execution("gpu-agent", token, "train-agent", "wrong-assignment-token")
    assert bad.value.code == "INVALID_ASSIGNMENT_LEASE"
    assert repository.get("train-agent").status is TaskStatus.QUEUED

    started = start(service, "train-agent", "gpu-agent", token, claimed)
    with pytest.raises(AgentExecutionError) as duplicate:
        start(service, "train-agent", "gpu-agent", token, claimed)
    assert duplicate.value.code == "ASSIGNMENT_NOT_CLAIMED"
    assert repository.get("train-agent").attempt == 1
    assert started["execution"]["generation"] == 1


def test_cross_node_cannot_use_another_nodes_execution_lease(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts)
    _nodes_a, token_a = create_node(repository, "gpu-a")
    _nodes_b, token_b = create_node(repository, "gpu-b")
    service = AgentExecutionService(repository, artifacts)
    claimed = allocate_claim(service, "train-agent", "gpu-a", token_a)
    started = start(service, "train-agent", "gpu-a", token_a, claimed)

    with pytest.raises(AgentExecutionError) as failure:
        service.heartbeat_execution(
            "gpu-b",
            token_b,
            "train-agent",
            started["execution"]["lease_token"],
            started["execution"]["generation"],
            progress=10,
        )
    assert failure.value.code == "EXECUTION_NODE_MISMATCH"
    assert failure.value.status_code == 403


def test_disabled_node_cannot_claim_new_work_but_can_finish_existing_execution(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts, "train-running")
    nodes, token = create_node(repository)
    service = AgentExecutionService(repository, artifacts)
    claimed = allocate_claim(service, "train-running", "gpu-agent", token)
    started = start(service, "train-running", "gpu-agent", token, claimed)

    nodes.update("gpu-agent", {"enabled": False})
    heartbeat = service.heartbeat_execution(
        "gpu-agent",
        token,
        "train-running",
        started["execution"]["lease_token"],
        started["execution"]["generation"],
        progress=55,
        stage="training",
    )
    assert heartbeat["task"]["progress"] == 55

    create_task(repository, artifacts, "train-new")
    # No central assignment will be created for a disabled node.
    assert service.allocator.assign_next() is None
    with pytest.raises(AgentExecutionError) as disabled:
        service.claim_assignment("gpu-agent", token)
    assert disabled.value.code == "NODE_DISABLED"

    finished = service.finish_execution(
        "gpu-agent",
        token,
        "train-running",
        started["execution"]["lease_token"],
        started["execution"]["generation"],
        status="SUCCEEDED",
        result_ref="result.json",
    )
    assert finished["task"]["status"] == "SUCCEEDED"


def test_cancel_request_wins_and_agent_can_only_finish_cancelled(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts)
    _nodes, token = create_node(repository)
    service = AgentExecutionService(repository, artifacts)
    claimed = allocate_claim(service, "train-agent", "gpu-agent", token)
    started = start(service, "train-agent", "gpu-agent", token, claimed)
    lease = started["execution"]

    repository.request_cancel("train-agent")
    heartbeat = service.heartbeat_execution(
        "gpu-agent",
        token,
        "train-agent",
        lease["lease_token"],
        lease["generation"],
        progress=60,
    )
    assert heartbeat["cancel_requested"] is True
    with pytest.raises(AgentExecutionError) as lost:
        service.finish_execution(
            "gpu-agent",
            token,
            "train-agent",
            lease["lease_token"],
            lease["generation"],
            status="SUCCEEDED",
        )
    assert lost.value.code == "CANCELLATION_WON"

    cancelled = service.finish_execution(
        "gpu-agent",
        token,
        "train-agent",
        lease["lease_token"],
        lease["generation"],
        status="CANCELLED",
    )
    assert cancelled["task"]["status"] == "CANCELLED"


def test_finalization_fences_late_cancel_and_allows_successful_finish(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts)
    _nodes, token = create_node(repository)
    service = AgentExecutionService(repository, artifacts)
    claimed = allocate_claim(service, "train-agent", "gpu-agent", token)
    started = start(service, "train-agent", "gpu-agent", token, claimed)
    lease = started["execution"]

    finalizing = service.begin_finalization(
        "gpu-agent",
        token,
        "train-agent",
        lease["lease_token"],
        lease["generation"],
    )
    assert finalizing["task"]["stage"] == "finalizing_commit"
    with pytest.raises(ValueError):
        repository.request_cancel("train-agent")

    finished = service.finish_execution(
        "gpu-agent",
        token,
        "train-agent",
        lease["lease_token"],
        lease["generation"],
        status="SUCCEEDED",
        result_ref="result.json",
    )
    assert finished["task"]["status"] == "SUCCEEDED"
    current = repository.get("train-agent")
    assert current.worker_id is None
    assert current.lease_expires_at is None


def test_remote_log_is_server_owned_size_bounded_and_execution_fenced(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts)
    _nodes, token = create_node(repository)
    service = AgentExecutionService(repository, artifacts)
    claimed = allocate_claim(service, "train-agent", "gpu-agent", token)
    started = start(service, "train-agent", "gpu-agent", token, claimed)
    lease = started["execution"]

    appended = service.append_log(
        "gpu-agent",
        token,
        "train-agent",
        lease["lease_token"],
        lease["generation"],
        "epoch 1/30\n",
    )
    assert appended["bytes"] == len("epoch 1/30\n".encode())
    task = repository.get("train-agent")
    assert "epoch 1/30" in artifacts.artifact_path(task.task_id, task.log_ref).read_text(encoding="utf-8")

    with pytest.raises(AgentExecutionError) as oversized:
        service.append_log(
            "gpu-agent",
            token,
            "train-agent",
            lease["lease_token"],
            lease["generation"],
            "x" * (MAX_REMOTE_LOG_BYTES + 1),
        )
    assert oversized.value.code == "REMOTE_LOG_TOO_LARGE"
    assert oversized.value.status_code == 413

    service.finish_execution(
        "gpu-agent",
        token,
        "train-agent",
        lease["lease_token"],
        lease["generation"],
        status="FAILED",
        error="test finish",
    )
    with pytest.raises(AgentExecutionError) as stale:
        service.append_log(
            "gpu-agent",
            token,
            "train-agent",
            lease["lease_token"],
            lease["generation"],
            "must-not-write\n",
        )
    assert stale.value.code == "EXECUTION_FENCED"


def test_expired_generation_cannot_mutate_new_execution(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts)
    _nodes, token = create_node(repository)
    service = AgentExecutionService(repository, artifacts)
    claimed1 = allocate_claim(service, "train-agent", "gpu-agent", token)
    first = start(service, "train-agent", "gpu-agent", token, claimed1)
    old_lease = first["execution"]

    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with repository._connect() as database:
        database.execute(
            "UPDATE tasks SET lease_expires_at=? WHERE task_id=?",
            (expired, "train-agent"),
        )
    assert service.fenced.release_expired() == 1
    assert repository.get("train-agent").status is TaskStatus.QUEUED

    claimed2 = allocate_claim(service, "train-agent", "gpu-agent", token)
    second = start(service, "train-agent", "gpu-agent", token, claimed2)
    assert second["execution"]["generation"] == 2

    with pytest.raises(AgentExecutionError) as stale:
        service.heartbeat_execution(
            "gpu-agent",
            token,
            "train-agent",
            old_lease["lease_token"],
            old_lease["generation"],
            progress=99,
        )
    assert stale.value.code == "EXECUTION_FENCED"
    assert repository.get("train-agent").attempt == 2


def test_token_rotation_between_preflight_and_transaction_blocks_start(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts)
    nodes, token = create_node(repository)
    service = AgentExecutionService(repository, artifacts)
    claimed = allocate_claim(service, "train-agent", "gpu-agent", token)
    original_authenticate = service.nodes.authenticate

    def authenticate_then_rotate(node_id, supplied):
        original_authenticate(node_id, supplied)
        nodes.rotate_token(node_id)

    service.nodes.authenticate = authenticate_then_rotate
    with pytest.raises(AgentExecutionError) as rotated:
        start(service, "train-agent", "gpu-agent", token, claimed)
    assert rotated.value.code == "INVALID_NODE_TOKEN"
    assert rotated.value.status_code == 401
    assert repository.get("train-agent").status is TaskStatus.QUEUED


def test_missing_payload_never_transitions_task_to_running(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts, write_payload=False)
    _nodes, token = create_node(repository)
    service = AgentExecutionService(repository, artifacts)
    claimed = allocate_claim(service, "train-agent", "gpu-agent", token)

    with pytest.raises(AgentExecutionError) as missing:
        start(service, "train-agent", "gpu-agent", token, claimed)
    assert missing.value.code == "TASK_PAYLOAD_UNAVAILABLE"
    assert repository.get("train-agent").status is TaskStatus.QUEUED


def test_wrong_node_token_cannot_claim_assignment(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts)
    _nodes, _token = create_node(repository)
    service = AgentExecutionService(repository, artifacts)
    assert service.allocator.assign_next() is not None

    with pytest.raises(ServiceNodeError) as denied:
        service.claim_assignment("gpu-agent", "wrong-token")
    assert denied.value.code == "INVALID_NODE_TOKEN"
    assert denied.value.status_code == 401
