from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from platform_core.agent_execution import AgentExecutionError, AgentExecutionService
from platform_core.node_agent_model_install_runtime import AgentModelInstallRunner
from platform_core.task_node_assignments import CentralTaskAllocator
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository


class Source:
    def __init__(self, body, sha, *, corrupt=False):
        self.headers = {"Content-Length": str(len(body)), "X-Content-SHA256": sha}
        self.body = body[:-1] + b"X" if corrupt else body
        self.closed = False

    def iter_content(self, chunk_size):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start:start + chunk_size]

    def close(self):
        self.closed = True


class Client:
    def __init__(self, body, sha, *, corrupt=False):
        self.source = Source(body, sha, corrupt=corrupt)
        self.finished = []
        self.receipts = []

    def heartbeat(self, _lease, **_kwargs):
        return {"cancel_requested": False}

    def open_model_install_source(self, _lease):
        return self.source

    def confirm_model_install(self, _lease, receipt):
        self.receipts.append(receipt)
        return {"accepted": True}

    def begin_finalization(self, _lease):
        return {}

    def finish(self, _lease, status, **_kwargs):
        self.finished.append(status)
        return {}


def lease(body):
    return SimpleNamespace(kind="MODEL_INSTALL", generation=1, task_id="install-1", payload=body)


def contract(content):
    digest = hashlib.sha256(content).hexdigest()
    return {"schema_version": 1, "task_kind": "MODEL_INSTALL", "transport": "agent-artifact-v1",
            "asset_id": "pt_" + digest[:24], "sha256": digest, "size_bytes": len(content)}


def test_model_install_copies_exact_sha_and_is_idempotent(tmp_path):
    body = b"model-safe-synthetic" * 80
    payload = contract(body)
    client = Client(body, payload["sha256"])
    runner = AgentModelInstallRunner(client, install_dir=tmp_path)
    assert runner.ready
    first = runner.run(lease(payload))
    assert first.status == "SUCCEEDED"
    installed = tmp_path / f"managed-{payload['sha256']}.pt"
    assert installed.read_bytes() == body
    assert client.receipts[0]["path"] == str(installed)
    assert client.finished == ["SUCCEEDED"]

    # The second attempt verifies the already-installed digest. It never reads
    # the network stream again or overwrites an identical content-addressed PT.
    def forbidden(_lease):
        raise AssertionError("duplicate installation must reuse verified bytes")
    client.open_model_install_source = forbidden
    assert runner.run(lease(payload)).status == "SUCCEEDED"
    assert client.finished == ["SUCCEEDED", "SUCCEEDED"]


def test_model_install_corrupt_source_never_publishes_destination(tmp_path):
    body = b"model-safe-synthetic" * 80
    payload = contract(body)
    client = Client(body, payload["sha256"], corrupt=True)
    runner = AgentModelInstallRunner(client, install_dir=tmp_path)
    outcome = runner.run(lease(payload))
    assert outcome.status == "FAILED"
    assert "HASH_MISMATCH" in outcome.error
    assert not list(tmp_path.glob("*.pt"))
    assert not list(tmp_path.glob("*.part"))
    assert not client.receipts


def test_model_install_rejects_symlink_and_unconfigured_directory(tmp_path):
    body = b"model-safe-synthetic" * 80
    payload = contract(body)
    client = Client(body, payload["sha256"])
    assert not AgentModelInstallRunner(client, install_dir="").ready
    destination = tmp_path / f"managed-{payload['sha256']}.pt"
    destination.symlink_to(tmp_path / "elsewhere")
    outcome = AgentModelInstallRunner(client, install_dir=tmp_path).run(lease(payload))
    assert outcome.status == "FAILED"
    assert "SYMLINK_FORBIDDEN" in outcome.error
    assert destination.is_symlink()


def test_model_install_affinity_uses_existing_agent_assignment(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    task_id = "install-schedule"
    artifacts.atomic_write_json(task_id, "request.json", {
        "node_id": "node-B", "execution_mode": "agent",
        "scheduling": {"mode": "node", "node_id": "node-B"},
        "remote_execution": {"version": 1, "task_kind": "MODEL_INSTALL",
                             "transport": "agent-artifact-v1"},
    })
    repository.create(TaskRecord.new(task_id, "__system__", TaskKind.MODEL_INSTALL,
                                     "request.json", "model-install:node-B"), artifacts=artifacts)
    nodes = ServiceNodeRepository(repository)
    for node_id in ("node-A", "node-B"):
        _node, token = nodes.create({"node_id": node_id, "display_name": node_id,
                                     "connection_mode": "agent", "allowed_capabilities": ["model-upload"]})
        nodes.heartbeat(node_id, token, {"build_id": "agent-install", "reported_capabilities": ["model-upload"]})
    assigned = CentralTaskAllocator(repository, artifacts).assign_next()
    assert assigned is not None
    assert assigned["node_id"] == "node-B"
    assert assigned["capability"] == "model-upload"


def test_install_receipt_is_required_before_success_and_bound_to_exact_node(tmp_path):
    body = b"model-safe-synthetic" * 80
    evidence = contract(body)
    node_id = "gpu-agent"
    task_id = "install-receipt"
    model = tmp_path / "source.pt"
    model.write_bytes(body)
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    artifacts.atomic_write_json(task_id, "request.json", {
        **{key: evidence[key] for key in ("asset_id", "sha256", "size_bytes")},
        "node_id": node_id, "execution_mode": "agent",
        "scheduling": {"mode": "node", "node_id": node_id},
        "remote_execution": {"version": 1, "task_kind": "MODEL_INSTALL", "transport": "agent-artifact-v1"},
    })
    repository.create(TaskRecord.new(task_id, "__system__", TaskKind.MODEL_INSTALL,
                                     "request.json", "model-install:gpu-agent"), artifacts=artifacts)
    nodes = ServiceNodeRepository(repository)
    _node, token = nodes.create({"node_id": node_id, "display_name": "GPU Agent",
                                 "connection_mode": "agent", "allowed_capabilities": ["model-upload"]})
    nodes.heartbeat(node_id, token, {"build_id": "model-install-test", "reported_capabilities": ["model-upload"]})
    service = AgentExecutionService(
        repository, artifacts,
        execution_payload_resolver=lambda _task, _payload, _assignment: evidence,
        model_install_asset_provider=lambda _asset_id: {**evidence, "path": str(model)},
    )
    assert service.allocator.assign_next()["node_id"] == node_id
    claimed = service.claim_assignment(node_id, token)
    started = service.start_execution(node_id, token, task_id,
                                      claimed["assignment"]["assignment_lease_token"])
    generation = started["execution"]["generation"]
    lease_token = started["execution"]["lease_token"]
    with pytest.raises(AgentExecutionError, match="receipt"):
        service.finish_execution(node_id, token, task_id, lease_token, generation, status="SUCCEEDED")
    with pytest.raises(AgentExecutionError, match="mismatch"):
        service.model_install_receipt(node_id, token, task_id, lease_token, generation, {
            **evidence, "path": "/var/models/managed.pt", "sha256": "0" * 64,
        })
    accepted = service.model_install_receipt(node_id, token, task_id, lease_token, generation, {
        **evidence, "path": "/var/models/managed.pt",
    })
    assert accepted["accepted"] is True
    service.begin_finalization(node_id, token, task_id, lease_token, generation)
    finished = service.finish_execution(node_id, token, task_id, lease_token, generation, status="SUCCEEDED")
    assert finished["task"]["status"] == "SUCCEEDED"
    assert repository.get(task_id).result_ref == accepted["result_ref"]

