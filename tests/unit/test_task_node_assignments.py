from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_node_assignments import (
    AssignmentAwareFencedTaskRepository,
    CentralTaskAllocator,
    task_node_capability,
    task_node_connection_mode,
    task_remote_execution_contract,
)
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository, TaskStatus


def runtime(tmp_path, repository_cls=TaskRepository):
    repository = repository_cls(tmp_path / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "task_runtime" / "artifacts")
    return repository, artifacts


def create_task(repository, artifacts, task_id, kind, payload=None, *, priority=50):
    payload_ref = "request.json"
    artifacts.atomic_write_json(task_id, payload_ref, payload or {})
    return repository.create(
        TaskRecord.new(
            task_id=task_id,
            project_id="project-1",
            kind=kind,
            payload_ref=payload_ref,
            resource_key=f"{kind.value.lower()}:{task_id}",
            priority=priority,
        ),
        artifacts=artifacts,
    )


def create_online_node(
    repository,
    node_id,
    capabilities,
    *,
    resources=None,
    runtime_payload=None,
    enabled=True,
    connection_mode="local",
):
    nodes = ServiceNodeRepository(repository)
    _node, token = nodes.create({
        "node_id": node_id,
        "display_name": node_id,
        "enabled": enabled,
        "connection_mode": connection_mode,
        "allowed_capabilities": capabilities,
    })
    return nodes.heartbeat(node_id, token, {
        "hostname": node_id,
        "build_id": f"build-{node_id}",
        "reported_capabilities": capabilities,
        "resources": resources or {},
        "runtime": runtime_payload or {},
    })


def training_resources(*, free0, free1=0, memory=32 * 1024**3):
    gpus = [{
        "id": "cuda:0",
        "index": 0,
        "uuid": "GPU-0",
        "name": "NVIDIA A800",
        "memory_free_bytes": free0,
        "memory_total_bytes": 40 * 1024**3,
    }]
    if free1:
        gpus.append({
            "id": "cuda:1",
            "index": 1,
            "uuid": "GPU-1",
            "name": "NVIDIA A800",
            "memory_free_bytes": free1,
            "memory_total_bytes": 40 * 1024**3,
        })
    return {
        "cpu": {"logical_cores": 16},
        "memory": {"available_bytes": memory},
        "disk": {"free_bytes": 500 * 1024**3},
        "gpu": {"available": True, "gpus": gpus},
    }


def test_allocator_requires_online_allowed_and_reported_capability(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts, "train-eligible", TaskKind.TRAINING)
    create_online_node(
        repository,
        "gpu-good",
        ["training"],
        resources=training_resources(free0=20 * 1024**3),
    )
    create_online_node(
        repository,
        "gpu-disabled",
        ["training"],
        enabled=False,
        resources=training_resources(free0=39 * 1024**3),
    )

    nodes = ServiceNodeRepository(repository)
    _node, mismatch_token = nodes.create({
        "node_id": "gpu-mismatch",
        "display_name": "gpu-mismatch",
        "connection_mode": "local",
        "allowed_capabilities": ["training", "conversion"],
    })
    nodes.heartbeat("gpu-mismatch", mismatch_token, {
        "reported_capabilities": ["conversion"],
        "resources": training_resources(free0=39 * 1024**3),
    })

    _node, stale_token = nodes.create({
        "node_id": "gpu-stale",
        "display_name": "gpu-stale",
        "connection_mode": "local",
        "allowed_capabilities": ["training"],
    })
    nodes.heartbeat("gpu-stale", stale_token, {
        "reported_capabilities": ["training"],
        "resources": training_resources(free0=39 * 1024**3),
    })
    stale_at = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    with repository._connect() as database:
        database.execute(
            "UPDATE service_nodes SET last_heartbeat_at=? WHERE node_id=?",
            (stale_at, "gpu-stale"),
        )

    assignment = CentralTaskAllocator(repository, artifacts).assign_next()
    assert assignment is not None
    assert assignment["node_id"] == "gpu-good"
    assert assignment["capability"] == "training"


def test_training_assignment_chooses_best_node_and_gpu_and_persists_execution_snapshot(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts, "train-gpu-choice", TaskKind.TRAINING)
    create_online_node(
        repository,
        "gpu-small",
        ["training"],
        resources=training_resources(free0=8 * 1024**3),
    )
    create_online_node(
        repository,
        "gpu-large",
        ["training"],
        resources=training_resources(free0=12 * 1024**3, free1=30 * 1024**3),
        runtime_payload={"torch_version": "2.5.0+cu124", "cuda_version": "12.4"},
    )

    assignment = CentralTaskAllocator(repository, artifacts).assign_next()
    assert assignment["node_id"] == "gpu-large"
    resolved = assignment["resolved_execution_config"]
    assert resolved["protocol"] == "agent-http-v1"
    assert resolved["selected_device"] == "cuda:1"
    assert resolved["selected_gpu"]["memory_free_bytes"] == 30 * 1024**3
    assert resolved["node_build_id"] == "build-gpu-large"
    assert resolved["node_runtime"]["cuda_version"] == "12.4"


def test_material_batch_operation_maps_to_real_node_capability(tmp_path):
    repository, artifacts = runtime(tmp_path)
    clean = create_task(repository, artifacts, "batch-clean", TaskKind.MATERIAL_BATCH, {"operation": "CLEAN"})
    annotate = create_task(repository, artifacts, "batch-ai", TaskKind.MATERIAL_BATCH, {"operation": "AI_ANNOTATE"})
    default = create_task(repository, artifacts, "batch-import", TaskKind.MATERIAL_BATCH, {"operation": "MOVE"})
    assert task_node_capability(clean, artifacts) == "cleaning"
    assert task_node_capability(annotate, artifacts) == "annotation"
    assert task_node_capability(default, artifacts) == "material-import"


def test_portable_clean_material_batch_selects_only_agent_node(tmp_path):
    repository, artifacts = runtime(tmp_path)
    task = create_task(
        repository,
        artifacts,
        "batch-clean-agent",
        TaskKind.MATERIAL_BATCH,
        {
            "operation": "CLEAN",
            "execution_mode": "agent",
            "remote_execution": {
                "version": 1,
                "task_kind": "MATERIAL_BATCH",
                "transport": "object-storage-v1",
            },
        },
    )
    create_online_node(repository, "clean-local", ["cleaning"], connection_mode="local")
    create_online_node(repository, "clean-agent", ["cleaning"], connection_mode="agent")

    assert task_node_connection_mode(task, artifacts) == "agent"
    assignment = CentralTaskAllocator(repository, artifacts).assign_next()
    assert assignment is not None
    assert assignment["node_id"] == "clean-agent"
    assert assignment["capability"] == "cleaning"
    assert assignment["resolved_execution_config"]["connection_mode"] == "agent"


def test_agent_clean_material_batch_without_portable_contract_never_falls_back_local(tmp_path):
    repository, artifacts = runtime(tmp_path)
    task = create_task(
        repository,
        artifacts,
        "batch-clean-agent-unprepared",
        TaskKind.MATERIAL_BATCH,
        {"operation": "CLEAN", "execution_mode": "agent"},
    )
    create_online_node(repository, "clean-local", ["cleaning"], connection_mode="local")
    create_online_node(repository, "clean-agent", ["cleaning"], connection_mode="agent")

    assert task_node_connection_mode(task, artifacts) == "agent"
    assert CentralTaskAllocator(repository, artifacts).assign_next() is None


def test_training_prepare_remains_control_plane_local_work(tmp_path):
    repository, artifacts = runtime(tmp_path)
    task = create_task(
        repository,
        artifacts,
        "train-prep",
        TaskKind.TRAINING_PREPARE,
        {"training_task_id": "train-target"},
    )
    assert task_node_capability(task, artifacts) is None


def test_explicit_remote_training_never_falls_back_to_local_node_while_unprepared(tmp_path):
    repository, artifacts = runtime(tmp_path)
    task = create_task(
        repository,
        artifacts,
        "train-remote-preparing",
        TaskKind.TRAINING,
        {"target": "remote", "epochs": 30},
    )
    create_online_node(
        repository,
        "gpu-local-fast",
        ["training"],
        connection_mode="local",
        resources=training_resources(free0=39 * 1024**3),
    )
    create_online_node(
        repository,
        "gpu-agent",
        ["training"],
        connection_mode="agent",
        resources=training_resources(free0=20 * 1024**3),
    )

    assert task_node_connection_mode(task, artifacts) == "agent"
    assert CentralTaskAllocator(repository, artifacts).assign_next() is None
    assert repository.get("train-remote-preparing").status is TaskStatus.QUEUED


def test_explicit_remote_training_with_portable_contract_uses_agent_even_if_local_scores_higher(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(
        repository,
        artifacts,
        "train-remote-ready",
        TaskKind.TRAINING,
        {
            "target": "remote",
            "remote_execution": {
                "version": 1,
                "task_kind": "TRAINING",
                "transport": "object-storage-v1",
            },
        },
    )
    create_online_node(
        repository,
        "gpu-local-fast",
        ["training"],
        connection_mode="local",
        resources=training_resources(free0=39 * 1024**3),
    )
    create_online_node(
        repository,
        "gpu-agent-ready",
        ["training"],
        connection_mode="agent",
        resources=training_resources(free0=12 * 1024**3),
    )

    assignment = CentralTaskAllocator(repository, artifacts).assign_next()
    assert assignment is not None
    assert assignment["node_id"] == "gpu-agent-ready"
    assert assignment["resolved_execution_config"]["connection_mode"] == "agent"


def test_material_import_agent_mode_requires_portable_contract_and_never_falls_back_local(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(
        repository,
        artifacts,
        "material-agent-no-contract",
        TaskKind.MATERIAL_IMPORT,
        {"execution_mode": "agent"},
    )
    create_online_node(
        repository,
        "material-local",
        ["material-import"],
        connection_mode="local",
    )
    create_online_node(
        repository,
        "material-agent",
        ["material-import"],
        connection_mode="agent",
    )

    assert task_node_connection_mode(
        repository.get("material-agent-no-contract"),
        artifacts,
    ) == "agent"
    assert CentralTaskAllocator(repository, artifacts).assign_next() is None


def test_portable_material_import_agent_mode_selects_only_agent_node(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(
        repository,
        artifacts,
        "material-agent-ready",
        TaskKind.MATERIAL_IMPORT,
        {
            "execution_mode": "agent",
            "remote_execution": {
                "version": 1,
                "task_kind": "MATERIAL_IMPORT",
                "transport": "object-storage-v1",
            },
        },
    )
    create_online_node(
        repository,
        "material-local",
        ["material-import"],
        connection_mode="local",
    )
    create_online_node(
        repository,
        "material-agent",
        ["material-import"],
        connection_mode="agent",
    )

    assignment = CentralTaskAllocator(repository, artifacts).assign_next()
    assert assignment is not None
    assert assignment["node_id"] == "material-agent"
    assert assignment["resolved_execution_config"]["connection_mode"] == "agent"


def test_portable_conversion_stays_local_until_execution_mode_is_agent(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(
        repository,
        artifacts,
        "convert-portable-local",
        TaskKind.MODEL_CONVERSION,
        {
            "execution_mode": "local",
            "remote_execution": {
                "version": 1,
                "task_kind": "MODEL_CONVERSION",
                "transport": "object-storage-v1",
            },
        },
    )
    create_online_node(
        repository,
        "conversion-local",
        ["conversion"],
        connection_mode="local",
    )
    create_online_node(
        repository,
        "conversion-agent",
        ["conversion"],
        connection_mode="agent",
    )

    assignment = CentralTaskAllocator(repository, artifacts).assign_next()
    assert assignment is not None
    assert assignment["node_id"] == "conversion-local"
    assert assignment["resolved_execution_config"]["connection_mode"] == "local"


def test_explicit_agent_conversion_requires_portable_contract_and_agent_node(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(
        repository,
        artifacts,
        "convert-agent-no-contract",
        TaskKind.MODEL_CONVERSION,
        {"execution_mode": "agent"},
    )
    create_online_node(
        repository,
        "conversion-local",
        ["conversion"],
        connection_mode="local",
    )
    create_online_node(
        repository,
        "conversion-agent",
        ["conversion"],
        connection_mode="agent",
    )
    assert CentralTaskAllocator(repository, artifacts).assign_next() is None

    repository2, artifacts2 = runtime(tmp_path / "ready")
    create_task(
        repository2,
        artifacts2,
        "convert-agent-ready",
        TaskKind.MODEL_CONVERSION,
        {
            "execution_mode": "agent",
            "remote_execution": {
                "version": 1,
                "task_kind": "MODEL_CONVERSION",
                "transport": "object-storage-v1",
            },
        },
    )
    create_online_node(
        repository2,
        "conversion-local",
        ["conversion"],
        connection_mode="local",
    )
    create_online_node(
        repository2,
        "conversion-agent",
        ["conversion"],
        connection_mode="agent",
    )
    assignment = CentralTaskAllocator(repository2, artifacts2).assign_next()
    assert assignment is not None
    assert assignment["node_id"] == "conversion-agent"
    assert assignment["resolved_execution_config"]["connection_mode"] == "agent"


def test_legacy_task_is_never_assigned_to_remote_agent_without_portable_contract(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(
        repository,
        artifacts,
        "train-legacy-remote",
        TaskKind.TRAINING,
        {
            "model_path": "/control-plane/models/base.pt",
            "dataset_path": "C:\\control-plane\\datasets\\train",
        },
    )
    create_online_node(
        repository,
        "gpu-remote-only",
        ["training"],
        connection_mode="agent",
        resources=training_resources(free0=39 * 1024**3),
    )

    allocator = CentralTaskAllocator(repository, artifacts)
    assert allocator.assign_next() is None
    assert allocator.list(active_only=True) == []
    assert repository.get("train-legacy-remote").status is TaskStatus.QUEUED


def test_local_node_can_execute_legacy_path_bound_task_without_remote_contract(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(
        repository,
        artifacts,
        "train-local-legacy",
        TaskKind.TRAINING,
        {"model_path": "/control-plane/models/base.pt"},
    )
    create_online_node(
        repository,
        "gpu-local",
        ["training"],
        connection_mode="local",
        resources=training_resources(free0=20 * 1024**3),
    )
    create_online_node(
        repository,
        "gpu-remote",
        ["training"],
        connection_mode="agent",
        resources=training_resources(free0=39 * 1024**3),
    )

    assignment = CentralTaskAllocator(repository, artifacts).assign_next()
    assert assignment is not None
    assert assignment["node_id"] == "gpu-local"
    resolved = assignment["resolved_execution_config"]
    assert resolved["connection_mode"] == "local"
    assert resolved["remote_execution"] is None


def test_portable_contract_allows_remote_agent_and_scheduler_snapshot_is_sanitized(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(
        repository,
        artifacts,
        "train-portable",
        TaskKind.TRAINING,
        {
            "epochs": 30,
            "remote_execution": {
                "version": 1,
                "task_kind": "TRAINING",
                "transport": "object-storage-v1",
                "credentials": {"secret": "must-not-enter-scheduler-truth"},
                "download_url": "https://signed.example.test/private",
                "control_plane_path": "/srv/private/model.pt",
            },
        },
    )
    create_online_node(
        repository,
        "gpu-portable-agent",
        ["training"],
        connection_mode="agent",
        resources=training_resources(free0=30 * 1024**3),
    )

    assignment = CentralTaskAllocator(repository, artifacts).assign_next()
    assert assignment is not None
    assert assignment["node_id"] == "gpu-portable-agent"
    resolved = assignment["resolved_execution_config"]
    assert resolved["connection_mode"] == "agent"
    assert resolved["remote_execution"] == {
        "version": 1,
        "task_kind": "TRAINING",
        "transport": "object-storage-v1",
    }
    serialized = str(resolved)
    assert "must-not-enter-scheduler-truth" not in serialized
    assert "signed.example.test" not in serialized
    assert "/srv/private/model.pt" not in serialized


@pytest.mark.parametrize(
    "contract",
    [
        None,
        "not-an-object",
        {"version": 2, "task_kind": "TRAINING", "transport": "object-storage-v1"},
        {"version": 1, "task_kind": "MODEL_CONVERSION", "transport": "object-storage-v1"},
        {"version": 1, "task_kind": "TRAINING", "transport": "shared-nfs"},
    ],
)
def test_invalid_remote_execution_contracts_fail_closed(tmp_path, contract):
    repository, artifacts = runtime(tmp_path)
    payload = {"epochs": 30}
    if contract is not None:
        payload["remote_execution"] = contract
    task = create_task(
        repository,
        artifacts,
        "train-contract-check",
        TaskKind.TRAINING,
        payload,
    )
    assert task_remote_execution_contract(task, artifacts) is None


def test_repeated_and_concurrent_allocate_next_create_only_one_active_assignment(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts, "train-once", TaskKind.TRAINING)
    create_online_node(
        repository,
        "gpu-one",
        ["training"],
        resources=training_resources(free0=20 * 1024**3),
    )

    allocator = CentralTaskAllocator(repository, artifacts)

    def allocate():
        return allocator.assign_next()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: allocate(), range(2)))

    assert sum(result is not None for result in results) == 1
    active = allocator.list(active_only=True)
    assert len(active) == 1
    assert active[0]["task_id"] == "train-once"


def test_assignment_claim_is_node_scoped_reclaimable_and_keeps_task_queued(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts, "train-claim", TaskKind.TRAINING)
    create_online_node(
        repository,
        "gpu-claim",
        ["training"],
        resources=training_resources(free0=20 * 1024**3),
    )
    allocator = CentralTaskAllocator(repository, artifacts)
    assignment = allocator.assign_next()
    assert assignment["state"] == "ASSIGNED"
    assert allocator.claim_for_node("other-node") is None

    first = allocator.claim_for_node("gpu-claim", lease_seconds=5)
    assert first["state"] == "CLAIMED"
    assert first["assignment_lease_token"]
    assert repository.get("train-claim").status is TaskStatus.QUEUED

    with repository._connect() as database:
        database.execute(
            "UPDATE task_node_assignments SET lease_expires_at=? WHERE task_id=? AND state='CLAIMED'",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), "train-claim"),
        )
    second = allocator.claim_for_node("gpu-claim", lease_seconds=5)
    assert second["state"] == "CLAIMED"
    assert second["assignment_lease_token"] != first["assignment_lease_token"]
    assert repository.get("train-claim").status is TaskStatus.QUEUED


def test_release_allows_new_generation_assignment(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts, "train-generation", TaskKind.TRAINING)
    create_online_node(
        repository,
        "gpu-generation",
        ["training"],
        resources=training_resources(free0=20 * 1024**3),
    )
    allocator = CentralTaskAllocator(repository, artifacts)
    first = allocator.assign_next()
    released = allocator.release("train-generation", "manual-test")
    second = allocator.assign_next()

    assert first["generation"] == 1
    assert released["state"] == "RELEASED"
    assert released["release_reason"] == "manual-test"
    assert second["generation"] == 2
    assert len(allocator.list(active_only=True)) == 1


def test_central_assignment_fences_legacy_worker_until_release(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts, "train-fenced", TaskKind.TRAINING)
    create_online_node(
        repository,
        "gpu-central",
        ["training"],
        resources=training_resources(free0=20 * 1024**3),
    )
    allocator = CentralTaskAllocator(repository, artifacts)
    allocator.assign_next()

    legacy = AssignmentAwareFencedTaskRepository(repository.path)
    blocked = legacy.claim_next("legacy-worker", [TaskKind.TRAINING], [], lease_seconds=30)
    assert blocked is None
    queued = legacy.get("train-fenced")
    assert queued.status is TaskStatus.QUEUED
    assert queued.stage == "resource_waiting"
    assert queued.resource_wait_reason.startswith("CENTRAL_NODE_ASSIGNED:")
    assert "gpu-central" in queued.resource_wait_reason

    allocator.release("train-fenced", "return-to-legacy")
    lease = legacy.claim_next("legacy-worker", [TaskKind.TRAINING], [], lease_seconds=30)
    assert lease is not None
    assert lease.task.task_id == "train-fenced"
    assert lease.task.status is TaskStatus.RUNNING
    assert lease.task.attempt == 1


class TracedRepository(TaskRepository):
    def __init__(self, path):
        self.sql_trace = []
        super().__init__(path)

    def _connect(self):
        database = super()._connect()
        database.set_trace_callback(self.sql_trace.append)
        return database


def test_allocator_never_runs_schema_script_inside_assignment_transaction(tmp_path):
    repository, artifacts = runtime(tmp_path, TracedRepository)
    create_task(repository, artifacts, "train-atomic", TaskKind.TRAINING)
    create_online_node(
        repository,
        "gpu-atomic",
        ["training"],
        resources=training_resources(free0=20 * 1024**3),
    )
    allocator = CentralTaskAllocator(repository, artifacts)
    repository.sql_trace.clear()

    assignment = allocator.assign_next()
    assert assignment is not None
    normalized = [statement.strip().upper() for statement in repository.sql_trace]
    assert any(statement.startswith("BEGIN IMMEDIATE") for statement in normalized)
    assert not any(statement.startswith("CREATE TABLE") for statement in normalized)
    assert not any(statement.startswith("CREATE INDEX") for statement in normalized)


def test_agent_rockchip_conversion_requires_dedicated_rknn_capability(tmp_path):
    repository, artifacts = runtime(tmp_path)
    task = create_task(
        repository,
        artifacts,
        "convert-rknn-agent",
        TaskKind.MODEL_CONVERSION,
        {
            "execution_mode": "agent",
            "target": "rockchip",
            "remote_execution": {
                "version": 1,
                "task_kind": "MODEL_CONVERSION",
                "transport": "object-storage-v1",
                "conversion": {"target": "rockchip"},
            },
        },
    )
    create_online_node(
        repository,
        "generic-conversion-agent",
        ["conversion"],
        connection_mode="agent",
    )
    create_online_node(
        repository,
        "rknn-conversion-agent",
        ["conversion.rknn"],
        connection_mode="agent",
        runtime_payload={
            "rknn_toolkit2": {
                "available": True,
                "version": "2.3.2",
                "supported_chips": ["rk3568", "rk3576"],
            },
        },
    )

    assert task_node_capability(task, artifacts) == "conversion.rknn"
    assignment = CentralTaskAllocator(repository, artifacts).assign_next()
    assert assignment is not None
    assert assignment["node_id"] == "rknn-conversion-agent"
    assert assignment["capability"] == "conversion.rknn"
    assert assignment["resolved_execution_config"]["capability"] == "conversion.rknn"
    assert assignment["resolved_execution_config"]["connection_mode"] == "agent"


def test_local_rockchip_conversion_keeps_existing_conversion_capability(tmp_path):
    repository, artifacts = runtime(tmp_path)
    task = create_task(
        repository,
        artifacts,
        "convert-rknn-local",
        TaskKind.MODEL_CONVERSION,
        {
            "execution_mode": "local",
            "target": "rockchip",
        },
    )
    assert task_node_capability(task, artifacts) == "conversion"


def test_rknn_board_deployment_test_routes_only_to_matching_agent_capability(tmp_path):
    repository, artifacts = runtime(tmp_path)
    task = create_task(
        repository,
        artifacts,
        "rknn-board-test",
        TaskKind.DEPLOYMENT_TEST,
        {
            "execution_mode": "agent",
            "runtime_format": "rknn",
            "remote_execution": {
                "version": 1,
                "task_kind": "DEPLOYMENT_TEST",
                "transport": "object-storage-v1",
            },
        },
    )
    create_online_node(
        repository, "generic-deploy", ["deployment-test"], connection_mode="agent"
    )
    create_online_node(
        repository, "rknn-board", ["deployment-test.rknn"], connection_mode="agent"
    )

    assert task_node_capability(task, artifacts) == "deployment-test.rknn"
    assert task_node_connection_mode(task, artifacts) == "agent"
    assignment = CentralTaskAllocator(repository, artifacts).assign_next()
    assert assignment is not None
    assert assignment["node_id"] == "rknn-board"
    assert assignment["capability"] == "deployment-test.rknn"


def test_legacy_deployment_test_keeps_generic_capability_and_no_forced_connection_mode(tmp_path):
    repository, artifacts = runtime(tmp_path)
    task = create_task(
        repository,
        artifacts,
        "legacy-deploy-test",
        TaskKind.DEPLOYMENT_TEST,
        {"runtime_format": "onnx"},
    )
    assert task_node_capability(task, artifacts) == "deployment-test"
    assert task_node_connection_mode(task, artifacts) is None
