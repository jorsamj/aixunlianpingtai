from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from platform_core.remote_execution_transport import (
    REMOTE_TRANSFER_TTL_SECONDS,
    RemoteExecutionTransportError,
    RemoteExecutionTransportService,
)
from platform_core.storage.models import ObjectMetadata
from platform_core.storage.source_repository import StorageSource
from platform_core.task_runtime import TaskKind


class FakeConfigRepository:
    def __init__(self, source_id="remote-models"):
        self.source_id = source_id

    def config(self):
        return {
            "schema_version": 1,
            "storage_source_id": self.source_id,
            "object_prefix": "model-assets",
            "auto_upload_enabled": True,
        }


class FakeModelArtifacts:
    def __init__(self, source_id="remote-models", model_row=None):
        self.repository = FakeConfigRepository(source_id)
        self.model_row = model_row
        self.discovered = []

    def discover_version_artifacts(self, project_id, algorithm, version):
        return list(self.discovered)

    def ensure_uploaded(self, _candidate):
        return dict(self.model_row or {})


class FakeSources:
    def __init__(self, *sources):
        self.values = {source.id: source for source in sources}

    def get(self, source_id):
        return self.values.get(str(source_id))


class FakeCredentials:
    def get(self, _ref):
        return {"access_key_id": "hidden", "secret_access_key": "hidden"}


class FakeProvider:
    def __init__(self):
        self.objects = {}
        self.uploads = []
        self.download_signatures = []
        self.upload_signatures = []
        self.overwrite_protected = True

    def exists(self, key):
        return str(key) in self.objects

    def upload(self, key, source, *, content_type="application/octet-stream", metadata=None):
        data = Path(source).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        self.objects[str(key)] = {
            "data": data,
            "content_type": content_type,
            "sha256": str((metadata or {}).get("sha256") or digest),
        }
        self.uploads.append((str(key), dict(metadata or {})))
        return self.stat(key)

    def stat(self, key):
        item = self.objects[str(key)]
        return ObjectMetadata(
            key=str(key),
            size_bytes=len(item["data"]),
            content_type=item["content_type"],
            sha256=item["sha256"],
        )

    def generate_preview_url(self, key, *, expires_seconds=900):
        self.download_signatures.append((str(key), int(expires_seconds)))
        return f"https://signed.example.test/get/{key}?secret=ephemeral"

    def generate_upload_contract(
        self,
        key,
        *,
        expires_seconds=900,
        content_type="application/octet-stream",
        metadata=None,
        size_bytes=None,
    ):
        normalized_metadata = dict(metadata or {})
        self.upload_signatures.append({
            "key": str(key),
            "expires_seconds": int(expires_seconds),
            "content_type": content_type,
            "metadata": normalized_metadata,
            "size_bytes": size_bytes,
        })
        headers = {
            "Content-Type": content_type,
            "If-None-Match": "*",
            "Content-Length": str(int(size_bytes)) if size_bytes is not None else "",
            **{f"x-amz-meta-{name}": str(value) for name, value in normalized_metadata.items()},
        }
        return {
            "url": f"https://signed.example.test/put/{key}?secret=ephemeral",
            "method": "PUT",
            "headers": headers,
            "expires_seconds": int(expires_seconds),
            "overwrite_protected": self.overwrite_protected,
        }


def source(source_id="remote-models", source_type="s3"):
    return StorageSource(
        id=source_id,
        name=source_id,
        type=source_type,
        config={"bucket": "test"},
        secret_ref="secret-ref",
        enabled=True,
        is_default=False,
    )


def service(tmp_path, provider, *, source_type="s3", model_artifacts=None):
    sources = FakeSources(source(source_type=source_type))
    return RemoteExecutionTransportService(
        data_dir=tmp_path,
        project_dir=lambda project_id: tmp_path / "projects" / project_id,
        algorithms_file=lambda project_id: tmp_path / "projects" / project_id / "algorithms.json",
        storage_sources_factory=lambda: sources,
        storage_credentials_factory=lambda: FakeCredentials(),
        provider_factory=lambda _project_id, _source, _secret: provider,
        model_artifacts=model_artifacts or FakeModelArtifacts(),
    )


def test_local_storage_is_not_silently_treated_as_remote_execution(tmp_path):
    provider = FakeProvider()
    transport = service(tmp_path, provider, source_type="local")
    image = tmp_path / "input.jpg"
    image.write_bytes(b"image-bytes")

    contract = transport.stage_deployment_test(
        project_id="p1",
        task_id="task1",
        input_path=image,
        model_path="",
        model_reference="yolo11n.pt",
        model_reference_type="official_downloadable",
        algorithm_id="",
        version_id="",
        framework="ultralytics",
        runtime_format="pt",
        confidence=0.25,
    )

    assert contract is None
    assert provider.uploads == []


def test_stage_official_model_uploads_input_and_persists_only_durable_object_refs(tmp_path):
    provider = FakeProvider()
    transport = service(tmp_path, provider)
    image = tmp_path / "camera.jpg"
    image.write_bytes(b"portable-image")
    expected_sha = hashlib.sha256(image.read_bytes()).hexdigest()

    contract = transport.stage_deployment_test(
        project_id="p1",
        task_id="deploy123",
        input_path=image,
        model_path="",
        model_reference="yolo11n.pt",
        model_reference_type="official_downloadable",
        algorithm_id="",
        version_id="",
        framework="ultralytics",
        runtime_format="pt",
        confidence=0.35,
    )

    assert contract["version"] == 1
    assert contract["task_kind"] == "DEPLOYMENT_TEST"
    assert contract["transport"] == "object-storage-v1"
    deployment = contract["deployment"]
    assert deployment["model"] == {"type": "official", "reference": "yolo11n.pt"}
    assert deployment["input"]["sha256"] == expected_sha
    assert deployment["input"]["size_bytes"] == len(b"portable-image")
    assert deployment["input"]["storage_source_id"] == "remote-models"
    assert deployment["output"]["object_key"].endswith("/output/result.jpg")
    serialized = str(contract)
    assert "signed.example.test" not in serialized
    assert "ephemeral" not in serialized
    assert str(image.resolve()) not in serialized
    assert provider.uploads[0][1]["sha256"] == expected_sha


def test_stage_project_model_reuses_uploaded_model_artifact_reference(tmp_path, monkeypatch):
    provider = FakeProvider()
    image = tmp_path / "input.jpg"
    image.write_bytes(b"image")
    model = tmp_path / "best.pt"
    model.write_bytes(b"model")
    model_sha = hashlib.sha256(model.read_bytes()).hexdigest()
    provider.objects["model-assets/p1/a1/v1/original/best.pt"] = {
        "data": model.read_bytes(),
        "content_type": "application/octet-stream",
        "sha256": model_sha,
    }
    model_artifacts = FakeModelArtifacts(model_row={
        "artifact_id": "artifact-1",
        "storage_status": "UPLOADED",
        "storage_source_id": "remote-models",
        "object_key": "model-assets/p1/a1/v1/original/best.pt",
        "file_name": "best.pt",
        "size_bytes": model.stat().st_size,
        "sha256": model_sha,
    })
    model_artifacts.discovered = [{
        "target": "original",
        "source_path": str(model),
    }]
    transport = service(tmp_path, provider, model_artifacts=model_artifacts)
    monkeypatch.setattr(
        "platform_core.remote_execution_transport.list_algorithms",
        lambda _path: [{"id": "a1", "versions": [{"id": "v1"}]}],
    )

    contract = transport.stage_deployment_test(
        project_id="p1",
        task_id="task-model",
        input_path=image,
        model_path=str(model),
        model_reference="",
        model_reference_type="",
        algorithm_id="a1",
        version_id="v1",
        framework="ultralytics",
        runtime_format="pt",
        confidence=0.2,
    )

    model_ref = contract["deployment"]["model"]
    assert model_ref["type"] == "object"
    assert model_ref["artifact_id"] == "artifact-1"
    assert model_ref["sha256"] == model_sha
    assert model_ref["object_key"].endswith("best.pt")


def test_resolve_execution_payload_mints_short_lived_urls_without_central_paths(tmp_path):
    provider = FakeProvider()
    transport = service(tmp_path, provider)
    image = tmp_path / "input.jpg"
    image.write_bytes(b"image")
    contract = transport.stage_deployment_test(
        project_id="p1",
        task_id="task-resolve",
        input_path=image,
        model_path="",
        model_reference="yolo11n.pt",
        model_reference_type="official_downloadable",
        algorithm_id="",
        version_id="",
        framework="ultralytics",
        runtime_format="pt",
        confidence=0.4,
    )
    task = SimpleNamespace(kind=TaskKind.DEPLOYMENT_TEST, project_id="p1")
    original_payload = {
        "model_path": "/central/private/model.pt",
        "input_path": "C:\\central\\private\\input.jpg",
        "runner_path": "/central/app/predict_ultralytics_runner.py",
        "python_path": "/central/venv/python",
        "remote_execution": contract,
    }

    resolved = transport.resolve_execution_payload(
        task,
        original_payload,
        {"resolved_execution_config": {"selected_device": "cuda:0"}},
    )

    assert resolved["task_kind"] == "DEPLOYMENT_TEST"
    assert resolved["selected_device"] == "cuda:0"
    assert resolved["model"] == {"type": "official", "reference": "yolo11n.pt"}
    assert resolved["input"]["download"]["method"] == "GET"
    assert "signed.example.test/get/" in resolved["input"]["download"]["url"]
    assert resolved["output"]["upload_protocol"] == "prepare-after-local-hash-v1"
    assert "upload" not in resolved["output"]
    assert provider.download_signatures[0][1] == REMOTE_TRANSFER_TTL_SECONDS
    assert provider.upload_signatures == []
    serialized = str(resolved)
    assert "/central/private/model.pt" not in serialized
    assert "C:\\central\\private\\input.jpg" not in serialized
    assert "runner_path" not in serialized
    assert "python_path" not in serialized


def test_resolve_object_model_checks_durable_size_and_sha_before_signing(tmp_path):
    provider = FakeProvider()
    transport = service(tmp_path, provider)
    model_data = b"real-model"
    model_sha = hashlib.sha256(model_data).hexdigest()
    provider.objects["models/best.pt"] = {
        "data": model_data,
        "content_type": "application/octet-stream",
        "sha256": model_sha,
    }
    input_data = b"image"
    input_sha = hashlib.sha256(input_data).hexdigest()
    provider.objects["inputs/x.jpg"] = {
        "data": input_data,
        "content_type": "image/jpeg",
        "sha256": input_sha,
    }
    remote = {
        "version": 1,
        "task_kind": "DEPLOYMENT_TEST",
        "transport": "object-storage-v1",
        "deployment": {
            "framework": "ultralytics",
            "runtime_format": "pt",
            "confidence": 0.25,
            "input": {
                "storage_source_id": "remote-models",
                "object_key": "inputs/x.jpg",
                "file_name": "x.jpg",
                "size_bytes": len(input_data),
                "sha256": input_sha,
                "content_type": "image/jpeg",
            },
            "model": {
                "type": "object",
                "artifact_id": "artifact-1",
                "storage_source_id": "remote-models",
                "object_key": "models/best.pt",
                "file_name": "best.pt",
                "size_bytes": len(model_data),
                "sha256": model_sha,
                "content_type": "application/octet-stream",
            },
            "output": {
                "storage_source_id": "remote-models",
                "object_key": "outputs/result.jpg",
                "file_name": "result.jpg",
                "content_type": "image/jpeg",
            },
        },
    }
    task = SimpleNamespace(kind=TaskKind.DEPLOYMENT_TEST, project_id="p1")

    resolved = transport.resolve_execution_payload(
        task,
        {"remote_execution": remote},
        {"resolved_execution_config": {}},
    )
    assert resolved["model"]["type"] == "object"
    assert resolved["model"]["artifact_id"] == "artifact-1"
    assert resolved["model"]["download"]["sha256"] == model_sha

    provider.objects["models/best.pt"]["data"] = b"different-size"
    with pytest.raises(RemoteExecutionTransportError) as changed:
        transport.resolve_execution_payload(
            task,
            {"remote_execution": remote},
            {"resolved_execution_config": {}},
        )
    assert changed.value.code == "REMOTE_OBJECT_CHANGED"


def _portable_result_fixture():
    input_data = b"image"
    input_sha = hashlib.sha256(input_data).hexdigest()
    remote = {
        "version": 1,
        "task_kind": "DEPLOYMENT_TEST",
        "transport": "object-storage-v1",
        "deployment": {
            "framework": "ultralytics",
            "runtime_format": "pt",
            "confidence": 0.25,
            "input": {
                "storage_source_id": "remote-models",
                "object_key": "inputs/x.jpg",
                "file_name": "x.jpg",
                "size_bytes": len(input_data),
                "sha256": input_sha,
                "content_type": "image/jpeg",
            },
            "model": {"type": "official", "reference": "yolo11n.pt"},
            "output": {
                "storage_source_id": "remote-models",
                "object_key": "outputs/result.jpg",
                "file_name": "result.jpg",
                "content_type": "image/jpeg",
            },
        },
    }
    task = SimpleNamespace(
        task_id="deploy-result",
        kind=TaskKind.DEPLOYMENT_TEST,
        project_id="p1",
        log_ref="logs/task.log",
    )
    return task, {"remote_execution": remote}, input_data, input_sha


def test_result_upload_contract_is_minted_only_after_agent_reports_hash_and_size(tmp_path):
    provider = FakeProvider()
    transport = service(tmp_path, provider)
    task, payload, input_data, input_sha = _portable_result_fixture()
    provider.objects["inputs/x.jpg"] = {
        "data": input_data,
        "content_type": "image/jpeg",
        "sha256": input_sha,
    }
    result_bytes = b"rendered-result"
    result_sha = hashlib.sha256(result_bytes).hexdigest()

    prepared = transport.prepare_result_upload(
        task,
        payload,
        {"sha256": result_sha, "size_bytes": len(result_bytes)},
    )

    assert prepared["already_uploaded"] is False
    assert prepared["sha256"] == result_sha
    assert prepared["size_bytes"] == len(result_bytes)
    assert prepared["storage_ref"]["object_key"] == "outputs/result.jpg"
    assert prepared["upload"]["method"] == "PUT"
    assert prepared["upload"]["headers"]["Content-Length"] == str(len(result_bytes))
    assert prepared["upload"]["headers"]["x-amz-meta-sha256"] == result_sha
    assert prepared["upload"]["headers"]["If-None-Match"] == "*"
    signature = provider.upload_signatures[-1]
    assert signature["metadata"] == {"sha256": result_sha}
    assert signature["size_bytes"] == len(result_bytes)
    assert signature["expires_seconds"] == REMOTE_TRANSFER_TTL_SECONDS


def test_result_confirm_requires_object_size_and_sha256_metadata_to_match(tmp_path):
    provider = FakeProvider()
    transport = service(tmp_path, provider)
    task, payload, _input_data, _input_sha = _portable_result_fixture()
    result_bytes = b"rendered-result"
    result_sha = hashlib.sha256(result_bytes).hexdigest()

    provider.objects["outputs/result.jpg"] = {
        "data": result_bytes,
        "content_type": "image/jpeg",
        "sha256": result_sha,
    }
    confirmed = transport.confirm_result_upload(
        task,
        payload,
        {"sha256": result_sha, "size_bytes": len(result_bytes)},
    )
    assert confirmed["result_ref"] == "result.json"
    result = confirmed["result"]
    assert result["task_id"] == "deploy-result"
    assert result["output_sha256"] == result_sha
    assert result["output_size_bytes"] == len(result_bytes)
    assert result["output_storage"]["object_key"] == "outputs/result.jpg"
    assert "signed.example.test" not in str(result)

    provider.objects["outputs/result.jpg"]["sha256"] = ""
    with pytest.raises(RemoteExecutionTransportError) as missing_hash:
        transport.confirm_result_upload(
            task,
            payload,
            {"sha256": result_sha, "size_bytes": len(result_bytes)},
        )
    assert missing_hash.value.code == "REMOTE_RESULT_HASH_UNVERIFIED"

    provider.objects["outputs/result.jpg"]["sha256"] = "f" * 64
    with pytest.raises(RemoteExecutionTransportError) as wrong_hash:
        transport.confirm_result_upload(
            task,
            payload,
            {"sha256": result_sha, "size_bytes": len(result_bytes)},
        )
    assert wrong_hash.value.code == "REMOTE_RESULT_HASH_MISMATCH"


def test_prepare_result_upload_recovers_idempotently_after_upload_before_confirm(tmp_path):
    provider = FakeProvider()
    transport = service(tmp_path, provider)
    task, payload, _input_data, _input_sha = _portable_result_fixture()
    result_bytes = b"already-uploaded"
    result_sha = hashlib.sha256(result_bytes).hexdigest()
    provider.objects["outputs/result.jpg"] = {
        "data": result_bytes,
        "content_type": "image/jpeg",
        "sha256": result_sha,
    }

    prepared = transport.prepare_result_upload(
        task,
        payload,
        {"sha256": result_sha, "size_bytes": len(result_bytes)},
    )

    assert prepared["already_uploaded"] is True
    assert prepared["upload"] is None
    assert provider.upload_signatures == []


def test_prepare_result_upload_rejects_existing_conflicting_object(tmp_path):
    provider = FakeProvider()
    transport = service(tmp_path, provider)
    task, payload, _input_data, _input_sha = _portable_result_fixture()
    provider.objects["outputs/result.jpg"] = {
        "data": b"other",
        "content_type": "image/jpeg",
        "sha256": hashlib.sha256(b"other").hexdigest(),
    }

    with pytest.raises(RemoteExecutionTransportError) as conflict:
        transport.prepare_result_upload(
            task,
            payload,
            {"sha256": hashlib.sha256(b"expected").hexdigest(), "size_bytes": len(b"expected")},
        )
    assert conflict.value.code == "REMOTE_RESULT_OBJECT_CONFLICT"


def test_result_upload_contract_must_be_overwrite_protected(tmp_path):
    provider = FakeProvider()
    provider.overwrite_protected = False
    transport = service(tmp_path, provider)
    task, payload, _input_data, _input_sha = _portable_result_fixture()
    result_bytes = b"rendered-result"
    result_sha = hashlib.sha256(result_bytes).hexdigest()

    with pytest.raises(RemoteExecutionTransportError) as unsafe:
        transport.prepare_result_upload(
            task,
            payload,
            {"sha256": result_sha, "size_bytes": len(result_bytes)},
        )
    assert unsafe.value.code == "REMOTE_UPLOAD_NOT_PROTECTED"


def test_result_upload_evidence_must_be_valid_before_signing(tmp_path):
    provider = FakeProvider()
    transport = service(tmp_path, provider)
    task, payload, _input_data, _input_sha = _portable_result_fixture()

    with pytest.raises(RemoteExecutionTransportError) as invalid_hash:
        transport.prepare_result_upload(
            task,
            payload,
            {"sha256": "not-a-sha", "size_bytes": 10},
        )
    assert invalid_hash.value.code == "REMOTE_RESULT_EVIDENCE_INVALID"
    assert provider.upload_signatures == []

    with pytest.raises(RemoteExecutionTransportError) as invalid_size:
        transport.prepare_result_upload(
            task,
            payload,
            {"sha256": "a" * 64, "size_bytes": 0},
        )
    assert invalid_size.value.code == "REMOTE_OBJECT_CONTRACT_INVALID"
    assert provider.upload_signatures == []
