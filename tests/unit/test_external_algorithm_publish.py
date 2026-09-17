import json
from pathlib import Path

from platform_core.algorithms import list_algorithms, save_algorithms
from platform_core.external_algorithm_platform import ExternalPlatformRepository
from platform_core.external_algorithm_publish import (
    ExternalAlgorithmPublishService,
    ExternalPublishConfigPayload,
    TargetMapping,
    request_external_auto_publish_if_enabled,
)
from platform_core.secrets import MemorySecretStore, SecretCredentialStore
from platform_core.storage.source_repository import StorageSourceRepository


class FakePublishingClient:
    versions = []
    weights = []
    version_creates = 0
    weight_creates = 0

    def __init__(self, **_kwargs):
        pass

    @classmethod
    def reset(cls):
        cls.versions = []
        cls.weights = []
        cls.version_creates = 0
        cls.weight_creates = 0

    def list_product_versions(self, _path):
        return {"code": 200, "data": list(self.versions)}

    def create_algorithm_version(self, _path, payload):
        type(self).version_creates += 1
        row = {
            "algoVersionId": f"av-{type(self).version_creates}",
            "versionName": payload["versionName"],
            "versionNo": payload["versionNo"],
        }
        type(self).versions.append(row)
        return {"code": 200, "data": {"algoVersionId": row["algoVersionId"]}}

    def list_version_weights(self, _path):
        return {"code": 200, "data": list(self.weights)}

    def create_weight(self, _path, payload):
        type(self).weight_creates += 1
        row = {"weightId": f"w-{type(self).weight_creates}", **dict(payload)}
        type(self).weights.append(row)
        return {"code": 200, "data": {"weightId": row["weightId"]}}


class RecoveringPublishingClient(FakePublishingClient):
    def create_algorithm_version(self, _path, payload):
        type(self).version_creates += 1
        row = {
            "algoVersionId": "recovered-version",
            "versionName": payload["versionName"],
            "versionNo": payload["versionNo"],
        }
        type(self).versions.append(row)
        raise RuntimeError("connection reset after server commit")

    def create_weight(self, _path, payload):
        type(self).weight_creates += 1
        row = {"weightId": "recovered-weight", **dict(payload)}
        type(self).weights.append(row)
        raise RuntimeError("connection reset after server commit")


def _project_dir(root: Path, project_id: str) -> Path:
    path = root / "projects" / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _algorithms_file(root: Path, project_id: str) -> Path:
    return _project_dir(root, project_id) / "algorithms.json"


def _configure_external(root: Path, memory: MemorySecretStore, *, auto_publish=True):
    repository = ExternalPlatformRepository(root)
    repository.save_config({
        "mode": "external",
        "provider": "changlian",
        "base_url": "https://changlian.example",
        "auto_sync_enabled": False,
        "auto_publish_enabled": auto_publish,
        "endpoints": {},
    })
    ref = repository.config()["credential_ref"]
    SecretCredentialStore(memory).set(ref, {"access_key_id": "ak", "access_secret": "secret"})


def _seed_external_algorithm(root: Path, *, project_id="p1", version_id="v1"):
    model = _project_dir(root, project_id) / "algorithm_versions" / "a1" / version_id / "best.pt"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"source-model")
    algorithms = [{
        "id": "a1",
        "name": "抽烟检测",
        "source_type": "EXTERNAL",
        "provider_type": "CHANG_LIAN",
        "external_product_id": "product-1",
        "external_analysis_id": "analysis-1",
        "versions": [{
            "id": version_id,
            "version_name": "20260917120000",
            "training_status": "SUCCEEDED",
            "artifact_verified": True,
            "stored_path": str(model),
            "model_name": model.name,
        }],
        "current_version_id": version_id,
    }]
    save_algorithms(_algorithms_file(root, project_id), algorithms)
    return model


def _seed_conversion(root: Path, *, project_id="p1", version_id="v1", target="rockchip"):
    job_root = _project_dir(root, project_id) / "deployment" / "jobs" / "convert-1"
    output = job_root / "outputs" / "model.rknn"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"converted-rknn")
    (job_root / "job.json").write_text(json.dumps({
        "id": "convert-1",
        "status": "done",
        "target": target,
        "source_id": f"version::a1::{version_id}",
        "source_meta": {"algorithm_id": "a1", "version_id": version_id},
        "params": {"chip": "rk3588"},
        "outputs": [{"path": str(output), "available": True}],
    }), encoding="utf-8")
    return output


def _service(root: Path, memory: MemorySecretStore, client_factory=FakePublishingClient):
    sources = StorageSourceRepository(root / "storage" / "storage_sources.sqlite3")
    credentials = SecretCredentialStore(memory)
    service = ExternalAlgorithmPublishService(
        data_dir=root,
        project_dir=lambda pid: _project_dir(root, pid),
        algorithms_file=lambda pid: _algorithms_file(root, pid),
        external_secret_store_factory=lambda: memory,
        storage_sources_factory=lambda: sources,
        storage_credentials_factory=lambda: credentials,
        client_factory=client_factory,
    )
    service.save_config(ExternalPublishConfigPayload(
        storage_source_id="default_local",
        public_base_url="https://platform.example",
        target_mappings={
            "rockchip": TargetMapping(compute_platform_id="cp-rk", chip_code="RK3588"),
        },
    ))
    return service


def test_publish_uploads_artifact_and_registers_version_and_weight(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    _seed_conversion(tmp_path)
    service = _service(tmp_path, memory)

    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert result["ok"] is True
    assert result["publication"]["status"] == "PUBLISHED"
    assert result["external_algo_version_id"] == "av-1"
    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.weight_creates == 1
    artifact = result["artifacts"][0]
    assert artifact["upload_status"] == "UPLOADED"
    assert artifact["sync_status"] == "SYNCED"
    assert artifact["compute_platform_id"] == "cp-rk"
    assert artifact["chip_code"] == "RK3588"
    assert artifact["public_url"].startswith("https://platform.example/api/v64/model-artifacts/")
    uploaded = _project_dir(tmp_path, "p1") / artifact["object_key"]
    assert uploaded.read_bytes() == b"converted-rknn"
    version = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]["versions"][0]
    assert version["external_publish_status"] == "published"
    assert version["external_algo_version_id"] == "av-1"


def test_republish_is_idempotent(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    _seed_conversion(tmp_path)
    service = _service(tmp_path, memory)

    service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.weight_creates == 1


def test_timeout_after_remote_commit_recovers_ids_without_duplicate(tmp_path: Path):
    RecoveringPublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    _seed_conversion(tmp_path)
    service = _service(tmp_path, memory, client_factory=RecoveringPublishingClient)

    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert result["publication"]["status"] == "PUBLISHED"
    assert result["external_algo_version_id"] == "recovered-version"
    assert result["artifacts"][0]["external_weight_id"] == "recovered-weight"
    assert RecoveringPublishingClient.version_creates == 1
    assert RecoveringPublishingClient.weight_creates == 1


def test_auto_publish_request_only_marks_external_version_when_enabled(tmp_path: Path):
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory, auto_publish=True)
    _seed_external_algorithm(tmp_path)

    marked = request_external_auto_publish_if_enabled(
        data_dir=tmp_path,
        algorithms_path=_algorithms_file(tmp_path, "p1"),
        algorithm_id="a1",
        version_id="v1",
        now="2026-09-17T12:00:00Z",
    )

    assert marked is True
    version = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]["versions"][0]
    assert version["external_publish_requested_at"] == "2026-09-17T12:00:00Z"
    assert version["external_publish_status"] == "pending"


def test_conversion_in_progress_blocks_publish(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    _seed_conversion(tmp_path)
    job_path = _project_dir(tmp_path, "p1") / "deployment" / "jobs" / "convert-1" / "job.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job["status"] = "running"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    service = _service(tmp_path, memory)

    try:
        service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
        assert False, "publish should have been blocked"
    except Exception as error:
        assert getattr(error, "code", "") == "MODEL_CONVERSION_STILL_RUNNING"
