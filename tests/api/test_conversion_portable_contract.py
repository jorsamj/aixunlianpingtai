from __future__ import annotations

from pathlib import Path

import app as app_module
from platform_core.errors import PlatformError
from platform_core.remote_execution_transport import RemoteExecutionTransportError
from platform_core.task_runtime import TaskKind


class FakeArtifacts:
    def __init__(self):
        self.rows = {}

    def atomic_write_json(self, task_id, ref, value):
        self.rows[(str(task_id), str(ref))] = dict(value)


class FakeRepository:
    def __init__(self):
        self.created = []

    def create(self, task):
        self.created.append(task)
        return task


class FakeTransport:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def stage_model_conversion(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return dict(self.result or {})


def _source(model: Path):
    return {
        "id": "version::algorithm-a::version-1",
        "path": str(model),
        "name": model.name,
        "algorithm_id": "algorithm-a",
        "version_id": "version-1",
        "config_path": "",
    }


def _resource():
    return {
        "id": "local-onnx",
        "name": "Local ONNX",
        "mode": "local",
        "status": "ready",
        "targets": ["onnx"],
        "kind": "onnx",
    }


def _agent_resource():
    return {
        "id": "agent-onnx",
        "name": "Agent ONNX",
        "mode": "agent",
        "status": "ready",
        "targets": ["onnx"],
        "kind": "onnx",
    }


def _contract():
    return {
        "version": 1,
        "task_kind": "MODEL_CONVERSION",
        "transport": "object-storage-v1",
        "conversion": {
            "schema_version": 1,
            "target": "onnx",
            "source": {
                "type": "object",
                "artifact_id": "artifact-source",
                "storage_source_id": "remote-models",
                "object_key": "model-assets/source.pt",
                "file_name": "source.pt",
                "size_bytes": 10,
                "sha256": "a" * 64,
                "content_type": "application/octet-stream",
            },
            "source_trace": {
                "source_id": "version::algorithm-a::version-1",
                "algorithm_id": "algorithm-a",
                "version_id": "version-1",
                "sha256": "a" * 64,
            },
            "params": {
                "input_size": 640,
                "batch": 1,
                "opset": 12,
                "dynamic": False,
                "simplify": False,
            },
            "output": {
                "storage_source_id": "remote-models",
                "object_key": "remote-execution/p1/task/conversion-output/model.onnx",
                "file_name": "model.onnx",
                "content_type": "application/octet-stream",
            },
        },
    }


def _patch_creation(monkeypatch, tmp_path, transport):
    model = tmp_path / "source.pt"
    model.write_bytes(b"model-data")
    jobs = {}
    artifacts = FakeArtifacts()
    repository = FakeRepository()

    monkeypatch.setattr(app_module, "_resolve_deploy_source", lambda _project, _source: _source(model))
    monkeypatch.setattr(app_module, "_deploy_resource_by_id", lambda _resource_id: _resource())
    monkeypatch.setattr(
        app_module,
        "_deploy_job_dir",
        lambda _project_id, job_id: tmp_path / "deploy" / "jobs" / str(job_id),
    )
    monkeypatch.setattr(
        app_module,
        "_write_deploy_job",
        lambda _project_id, job: jobs.__setitem__(str(job["id"]), dict(job)),
    )
    monkeypatch.setattr(app_module, "get_active_ultralytics_env", lambda: {})
    monkeypatch.setattr(app_module, "get_active_paddle_env", lambda: {})
    monkeypatch.setattr(app_module, "shared_task_artifacts", lambda: artifacts)
    monkeypatch.setattr(app_module, "shared_task_repository", lambda: repository)
    monkeypatch.setattr(app_module, "_remote_execution_transport_service", lambda: transport)
    return model, jobs, artifacts, repository


def test_local_onnx_creation_persists_portable_contract_without_changing_local_execution(
    tmp_path, monkeypatch
):
    transport = FakeTransport(result=_contract())
    model, jobs, artifacts, repository = _patch_creation(monkeypatch, tmp_path, transport)

    response = app_module.v39_create_deploy_job(
        "p1",
        app_module.DeployJobReq(
            source_id="version::algorithm-a::version-1",
            target="onnx",
            resource_id="local-onnx",
            params={"input_size": 640, "opset": 12},
        ),
    )

    job = response["job"]
    assert job["remote_portability"] == {
        "status": "ready",
        "transport": "object-storage-v1",
        "task_kind": "MODEL_CONVERSION",
    }
    assert len(repository.created) == 1
    task = repository.created[0]
    assert task.kind is TaskKind.MODEL_CONVERSION
    request = artifacts.rows[(task.task_id, "request.json")]
    assert request["execution_mode"] == "local"
    assert request["remote_execution"]["task_kind"] == "MODEL_CONVERSION"
    assert request["job_dir"]
    assert request["worker_path"].endswith("deployment_worker.py")
    assert request["python_path"]
    assert transport.calls[0]["source_path"] == model
    assert transport.calls[0]["algorithm_id"] == "algorithm-a"
    assert transport.calls[0]["version_id"] == "version-1"
    assert transport.calls[0]["target"] == "onnx"


def test_local_onnx_creation_survives_portable_staging_unavailable(tmp_path, monkeypatch):
    transport = FakeTransport(
        error=RemoteExecutionTransportError(
            "REMOTE_CONVERSION_STORAGE_REQUIRED",
            "portable model conversion requires object storage",
            409,
        )
    )
    _model, _jobs, artifacts, repository = _patch_creation(monkeypatch, tmp_path, transport)

    response = app_module.v39_create_deploy_job(
        "p1",
        app_module.DeployJobReq(
            source_id="version::algorithm-a::version-1",
            target="onnx",
            resource_id="local-onnx",
            params={},
        ),
    )

    job = response["job"]
    assert job["remote_portability"]["status"] == "unavailable"
    assert job["remote_portability"]["code"] == "REMOTE_CONVERSION_STORAGE_REQUIRED"
    task = repository.created[0]
    request = artifacts.rows[(task.task_id, "request.json")]
    assert request["execution_mode"] == "local"
    assert "remote_execution" not in request


def test_vendor_conversion_does_not_pretend_portable_agent_support(tmp_path, monkeypatch):
    transport = FakeTransport(result=_contract())
    model, jobs, artifacts, repository = _patch_creation(monkeypatch, tmp_path, transport)
    monkeypatch.setattr(
        app_module,
        "_deploy_resource_by_id",
        lambda _resource_id: {
            "id": "local-trt",
            "name": "Local TensorRT",
            "mode": "local",
            "status": "ready",
            "targets": ["tensorrt"],
            "kind": "tensorrt",
        },
    )

    response = app_module.v39_create_deploy_job(
        "p1",
        app_module.DeployJobReq(
            source_id="version::algorithm-a::version-1",
            target="tensorrt",
            resource_id="local-trt",
            params={
                "precision": "fp16",
                "target_environment": "gpu/cuda/tensorrt",
            },
        ),
    )

    assert response["job"].get("remote_portability") is None
    assert transport.calls == []
    request = artifacts.rows[(repository.created[0].task_id, "request.json")]
    assert request["execution_mode"] == "local"
    assert "remote_execution" not in request



def test_agent_resource_detection_requires_fresh_effective_conversion_capability(monkeypatch):
    class FakeNodes:
        def __init__(self, _repository):
            pass

        def list_public(self):
            return [
                {
                    "node_id": "offline",
                    "display_name": "offline",
                    "connection_mode": "agent",
                    "online": False,
                    "effective_capabilities": ["conversion"],
                    "build_id": "b1",
                },
                {
                    "node_id": "online-no-conversion",
                    "display_name": "other",
                    "connection_mode": "agent",
                    "online": True,
                    "effective_capabilities": ["training"],
                    "build_id": "b2",
                },
                {
                    "node_id": "conversion-node",
                    "display_name": "conversion",
                    "connection_mode": "agent",
                    "online": True,
                    "effective_capabilities": ["conversion"],
                    "build_id": "b3",
                },
            ]

    monkeypatch.setattr(app_module, "ServiceNodeRepository", FakeNodes)
    monkeypatch.setattr(app_module, "shared_task_repository", lambda: object())

    checked = app_module._detect_agent_deploy_resource(_agent_resource())

    assert checked["status"] == "ready"
    assert checked["targets"] == ["onnx"]
    assert checked["agent_nodes"] == [{
        "node_id": "conversion-node",
        "display_name": "conversion",
        "build_id": "b3",
    }]


def test_agent_resource_detection_is_missing_without_eligible_conversion_node(monkeypatch):
    class FakeNodes:
        def __init__(self, _repository):
            pass

        def list_public(self):
            return [{
                "node_id": "training-only",
                "display_name": "training",
                "connection_mode": "agent",
                "online": True,
                "effective_capabilities": ["training"],
                "build_id": "b1",
            }]

    monkeypatch.setattr(app_module, "ServiceNodeRepository", FakeNodes)
    monkeypatch.setattr(app_module, "shared_task_repository", lambda: object())

    checked = app_module._detect_agent_deploy_resource(_agent_resource())

    assert checked["status"] == "missing"
    assert checked["targets"] == []
    assert checked["agent_nodes"] == []


def test_explicit_agent_onnx_creation_routes_only_to_agent_executor(
    tmp_path, monkeypatch
):
    transport = FakeTransport(result=_contract())
    _model, jobs, artifacts, repository = _patch_creation(monkeypatch, tmp_path, transport)
    monkeypatch.setattr(app_module, "_deploy_resource_by_id", lambda _resource_id: _agent_resource())
    monkeypatch.setattr(app_module, "_detect_agent_deploy_resource", lambda resource: dict(resource))

    response = app_module.v39_create_deploy_job(
        "p1",
        app_module.DeployJobReq(
            source_id="version::algorithm-a::version-1",
            target="onnx",
            resource_id="agent-onnx",
            params={"input_size": 640, "opset": 12},
        ),
    )

    job = response["job"]
    assert job["remote_portability"]["status"] == "ready"
    task = repository.created[0]
    assert task.kind is TaskKind.MODEL_CONVERSION
    assert task.required_capabilities == ("agent.remote",)
    request = artifacts.rows[(task.task_id, "request.json")]
    assert request["execution_mode"] == "agent"
    assert request["remote_execution"]["task_kind"] == "MODEL_CONVERSION"


def test_agent_onnx_creation_fails_closed_when_portable_staging_is_unavailable(
    tmp_path, monkeypatch
):
    transport = FakeTransport(
        error=RemoteExecutionTransportError(
            "REMOTE_CONVERSION_STORAGE_REQUIRED",
            "portable model conversion requires object storage",
            409,
        )
    )
    _model, _jobs, _artifacts, repository = _patch_creation(monkeypatch, tmp_path, transport)
    monkeypatch.setattr(app_module, "_deploy_resource_by_id", lambda _resource_id: _agent_resource())
    monkeypatch.setattr(app_module, "_detect_agent_deploy_resource", lambda resource: dict(resource))

    try:
        app_module.v39_create_deploy_job(
            "p1",
            app_module.DeployJobReq(
                source_id="version::algorithm-a::version-1",
                target="onnx",
                resource_id="agent-onnx",
                params={},
            ),
        )
    except PlatformError as error:
        assert error.code == "REMOTE_CONVERSION_STORAGE_REQUIRED"
        assert error.status_code == 409
    else:
        raise AssertionError("Agent conversion unexpectedly fell back to local execution")
    assert repository.created == []
