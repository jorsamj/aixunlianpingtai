from __future__ import annotations

from pathlib import Path

import pytest

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
    def __init__(self, result=None, error=None, calibration_result=None, calibration_error=None):
        self.result = result
        self.error = error
        self.calls = []
        self.calibration_result = calibration_result
        self.calibration_error = calibration_error
        self.calibration_calls = []

    def build_rknn_calibration_snapshot(self, **kwargs):
        self.calibration_calls.append(dict(kwargs))
        if self.calibration_error is not None:
            raise self.calibration_error
        return dict(self.calibration_result or {})

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


def _agent_rknn_resource():
    return {
        "id": "agent-rknn",
        "name": "Agent RKNN",
        "mode": "agent",
        "status": "ready",
        "targets": ["rockchip"],
        "kind": "rockchip",
        "supported_chips": ["rk3568", "rk3576"],
        "supported_precisions": ["fp16", "int8"],
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


def _rknn_contract():
    value = _contract()
    value["conversion"] = dict(value["conversion"])
    value["conversion"]["target"] = "rockchip"
    value["conversion"]["params"] = {
        "input_size": 640,
        "batch": 1,
        "opset": 12,
        "dynamic": False,
        "simplify": False,
        "chip": "rk3568",
        "precision": "fp16",
        "mean": "0,0,0",
        "rknn_std": "255,255,255",
    }
    value["conversion"]["output"] = {
        "storage_source_id": "remote-models",
        "object_key": "remote-execution/p1/task/conversion-output/model_rk3568.rknn",
        "file_name": "model_rk3568.rknn",
        "content_type": "application/octet-stream",
    }
    return value


def _rknn_int8_snapshot():
    return {
        "schema_version": 1,
        "snapshot_id": "c" * 64,
        "dataset_id": "default",
        "split": "train",
        "material_revision": 7,
        "requested_count": 100,
        "item_count": 2,
        "items": [
            {
                "image_id": "cal-1",
                "file_name": "a.jpg",
                "storage_source_id": "remote-models",
                "storage_type": "s3",
                "object_key": "datasets/calibration/a.jpg",
                "size_bytes": 11,
                "etag": "etag-a",
                "sha256": "1" * 64,
            },
            {
                "image_id": "cal-2",
                "file_name": "b.jpg",
                "storage_source_id": "remote-models",
                "storage_type": "s3",
                "object_key": "datasets/calibration/b.jpg",
                "size_bytes": 12,
                "etag": "etag-b",
                "sha256": "2" * 64,
            },
        ],
    }


def _rknn_int8_contract(snapshot=None):
    snapshot = dict(snapshot or _rknn_int8_snapshot())
    value = _rknn_contract()
    value["conversion"] = dict(value["conversion"])
    value["conversion"]["params"] = {
        **dict(value["conversion"]["params"]),
        "precision": "int8",
        "calibration_count": int(snapshot["item_count"]),
        "calibration_snapshot": str(snapshot["snapshot_id"]),
    }
    value["conversion"]["calibration"] = snapshot
    return value


def _patch_creation(monkeypatch, tmp_path, transport):
    model = tmp_path / "source.pt"
    model.write_bytes(b"model-data")
    jobs = {}
    artifacts = FakeArtifacts()
    repository = FakeRepository()

    monkeypatch.setattr(
        app_module,
        "_resolve_deploy_source",
        lambda _project_id, _source_id: _source(model),
    )
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
        "capability": "conversion",
        "supported_chips": [],
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


def test_agent_rknn_resource_requires_effective_rknn_capability_and_probe(monkeypatch):
    class FakeNodes:
        def __init__(self, _repository):
            pass

        def list_public(self):
            return [
                {
                    "node_id": "generic-conversion",
                    "display_name": "generic",
                    "connection_mode": "agent",
                    "online": True,
                    "effective_capabilities": ["conversion"],
                    "runtime": {},
                    "build_id": "b1",
                },
                {
                    "node_id": "rknn-no-probe",
                    "display_name": "rknn-no-probe",
                    "connection_mode": "agent",
                    "online": True,
                    "effective_capabilities": ["conversion.rknn"],
                    "runtime": {"rknn_toolkit2": {"available": False}},
                    "build_id": "b2",
                },
                {
                    "node_id": "rknn-ready",
                    "display_name": "RKNN Ready",
                    "connection_mode": "agent",
                    "online": True,
                    "effective_capabilities": ["conversion.rknn"],
                    "runtime": {
                        "rknn_toolkit2": {
                            "available": True,
                            "version": "2.3.2",
                            "supported_chips": ["rk3568", "rk3576"],
                        }
                    },
                    "build_id": "b3",
                },
            ]

    monkeypatch.setattr(app_module, "ServiceNodeRepository", FakeNodes)
    monkeypatch.setattr(app_module, "shared_task_repository", lambda: object())

    checked = app_module._detect_agent_deploy_resource(_agent_rknn_resource())

    assert checked["status"] == "ready"
    assert checked["targets"] == ["rockchip"]
    assert checked["supported_chips"] == ["rk3568", "rk3576"]
    assert [row["node_id"] for row in checked["agent_nodes"]] == ["rknn-ready"]
    assert checked["agent_nodes"][0]["capability"] == "conversion.rknn"


def test_explicit_agent_rknn_creation_persists_target_and_portable_contract(
    tmp_path, monkeypatch
):
    transport = FakeTransport(result=_rknn_contract())
    _model, _jobs, artifacts, repository = _patch_creation(
        monkeypatch, tmp_path, transport
    )
    monkeypatch.setattr(
        app_module,
        "_deploy_resource_by_id",
        lambda _resource_id: _agent_rknn_resource(),
    )
    monkeypatch.setattr(
        app_module,
        "_detect_agent_deploy_resource",
        lambda resource: dict(resource),
    )

    response = app_module.v39_create_deploy_job(
        "p1",
        app_module.DeployJobReq(
            source_id="version::algorithm-a::version-1",
            target="rockchip",
            resource_id="agent-rknn",
            params={
                "input_size": 640,
                "batch": 1,
                "chip": "rk3568",
                "precision": "fp16",
            },
        ),
    )

    assert response["job"]["remote_portability"]["status"] == "ready"
    assert transport.calls[0]["target"] == "rockchip"
    task = repository.created[0]
    assert task.kind is TaskKind.MODEL_CONVERSION
    assert task.required_capabilities == ("agent.remote",)
    request = artifacts.rows[(task.task_id, "request.json")]
    assert request["execution_mode"] == "agent"
    assert request["target"] == "rockchip"
    assert request["remote_execution"]["conversion"]["target"] == "rockchip"


def test_agent_rknn_int8_freezes_calibration_snapshot_before_task_staging(
    tmp_path, monkeypatch
):
    snapshot = _rknn_int8_snapshot()
    transport = FakeTransport(
        result=_rknn_int8_contract(snapshot),
        calibration_result=snapshot,
    )
    _model, jobs, artifacts, repository = _patch_creation(
        monkeypatch, tmp_path, transport
    )
    monkeypatch.setattr(
        app_module,
        "_deploy_resource_by_id",
        lambda _resource_id: _agent_rknn_resource(),
    )
    monkeypatch.setattr(
        app_module,
        "_detect_agent_deploy_resource",
        lambda resource: dict(resource),
    )
    monkeypatch.setattr(
        app_module,
        "_deploy_prepare_calibration",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Agent INT8 must not build a central calibration_dir")
        ),
    )

    response = app_module.v39_create_deploy_job(
        "p1",
        app_module.DeployJobReq(
            source_id="version::algorithm-a::version-1",
            target="rockchip",
            resource_id="agent-rknn",
            params={
                "input_size": 640,
                "batch": 1,
                "chip": "rk3568",
                "precision": "int8",
            },
            dataset_id="default",
            calibration_split="train",
            calibration_count=100,
        ),
    )

    assert transport.calibration_calls == [{
        "project_id": "p1",
        "dataset_id": "default",
        "split": "train",
        "limit": 100,
    }]
    assert len(transport.calls) == 1
    assert transport.calls[0]["calibration_snapshot"] == snapshot
    assert transport.calls[0]["params"]["precision"] == "int8"
    assert transport.calls[0]["params"]["calibration_count"] == 2
    assert transport.calls[0]["params"]["calibration_snapshot"] == snapshot["snapshot_id"]
    job = response["job"]
    assert job["params"]["precision"] == "int8"
    assert job["params"]["calibration_count"] == 2
    assert job["params"]["calibration_snapshot"] == snapshot["snapshot_id"]
    assert job["calibration_dir"] == ""
    task = repository.created[0]
    assert task.kind is TaskKind.MODEL_CONVERSION
    assert task.required_capabilities == ("agent.remote",)
    request = artifacts.rows[(task.task_id, "request.json")]
    assert request["execution_mode"] == "agent"
    assert request["remote_execution"]["conversion"]["calibration"]["snapshot_id"] == snapshot["snapshot_id"]


def test_agent_rknn_int8_calibration_failure_leaves_no_task(
    tmp_path, monkeypatch
):
    transport = FakeTransport(
        result=_rknn_int8_contract(),
        calibration_error=RemoteExecutionTransportError(
            "REMOTE_CONVERSION_CALIBRATION_EMPTY",
            "no portable calibration images",
            409,
        ),
    )
    _model, _jobs, _artifacts, repository = _patch_creation(
        monkeypatch, tmp_path, transport
    )
    monkeypatch.setattr(
        app_module,
        "_deploy_resource_by_id",
        lambda _resource_id: _agent_rknn_resource(),
    )
    monkeypatch.setattr(
        app_module,
        "_detect_agent_deploy_resource",
        lambda resource: dict(resource),
    )

    with pytest.raises(PlatformError) as failure:
        app_module.v39_create_deploy_job(
            "p1",
            app_module.DeployJobReq(
                source_id="version::algorithm-a::version-1",
                target="rockchip",
                resource_id="agent-rknn",
                params={"chip": "rk3568", "precision": "int8"},
            ),
        )
    assert failure.value.code == "REMOTE_CONVERSION_CALIBRATION_EMPTY"
    assert repository.created == []
    assert transport.calls == []


def test_agent_rknn_unsupported_chip_is_rejected_before_job_staging(
    tmp_path, monkeypatch
):
    transport = FakeTransport(result=_rknn_contract())
    _model, _jobs, _artifacts, repository = _patch_creation(
        monkeypatch, tmp_path, transport
    )
    monkeypatch.setattr(
        app_module,
        "_deploy_resource_by_id",
        lambda _resource_id: _agent_rknn_resource(),
    )
    monkeypatch.setattr(
        app_module,
        "_detect_agent_deploy_resource",
        lambda resource: dict(resource),
    )

    with pytest.raises(app_module.HTTPException) as failure:
        app_module.v39_create_deploy_job(
            "p1",
            app_module.DeployJobReq(
                source_id="version::algorithm-a::version-1",
                target="rockchip",
                resource_id="agent-rknn",
                params={"chip": "rk3588", "precision": "fp16"},
            ),
        )
    assert failure.value.status_code == 400
    assert "rk3588" in str(failure.value.detail)
    assert repository.created == []
    assert transport.calls == []
