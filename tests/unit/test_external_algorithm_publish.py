import json
from pathlib import Path

from platform_core.algorithms import list_algorithms, save_algorithms
from platform_core.external_algorithm_platform import (
    EndpointPayload,
    ExternalAlgorithmPlatformService,
    ExternalPlatformConfigPayload,
    ExternalPlatformRepository,
    resolve_external_training_analysis,
)
from platform_core.external_algorithm_publish import (
    _remote_id,
    ExternalAlgorithmPublishService,
    ExternalPublicationRepository,
    ExternalPublishConfigPayload,
    TargetMapping,
    request_external_auto_publish_if_enabled,
)
from platform_core.model_artifacts import ModelArtifactConfigPayload
from platform_core.secrets import MemorySecretStore, SecretCredentialStore
from platform_core.storage.source_repository import StorageSourceRepository





def test_remote_id_accepts_official_scalar_data_ids():
    assert _remote_id({"code": 0, "data": 501}, ("algoVersionId",)) == "501"
    assert _remote_id({"code": 0, "data": 701}, ("weightId",)) == "701"

def test_publish_endpoint_defaults_and_legacy_config_use_internal_algorithm_namespace(tmp_path: Path):
    payload = ExternalPublishConfigPayload()
    assert payload.version_list_by_product == "/internal/algorithm/algorithm-version/listByProduct/{productId}"
    assert payload.weight_list_by_version == "/internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}"

    repository = ExternalPublicationRepository(tmp_path)
    repository.config_path.write_text(json.dumps({
        "version_list_by_product": "/algorithm-version/listByProduct/{productId}",
        "weight_list_by_version": "/algorithm-weight/listByVersion/{algoVersionId}",
    }), encoding="utf-8")
    config = repository.config()
    assert config["version_list_by_product"] == "/internal/algorithm/algorithm-version/listByProduct/{productId}"
    assert config["weight_list_by_version"] == "/internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}"


class FakePublishingClient:
    versions = []
    weights = []
    version_creates = 0
    weight_creates = 0
    last_version_payload = None
    last_weight_payload = None
    last_version_list_path = None
    last_version_create_path = None
    last_weight_list_path = None
    last_weight_create_path = None

    def __init__(self, **_kwargs):
        pass

    @classmethod
    def reset(cls):
        cls.versions = []
        cls.weights = []
        cls.version_creates = 0
        cls.weight_creates = 0
        cls.last_version_payload = None
        cls.last_weight_payload = None
        cls.last_version_list_path = None
        cls.last_version_create_path = None
        cls.last_weight_list_path = None
        cls.last_weight_create_path = None

    def list_product_versions(self, product_id):
        type(self).last_version_list_path = f"/internal/algorithm/algorithm-version/listByProduct/{product_id}"
        return {"code": 200, "data": list(self.versions)}

    def create_algorithm_version(self, payload):
        type(self).last_version_create_path = "/internal/algorithm/algorithm-version/add"
        type(self).version_creates += 1
        type(self).last_version_payload = dict(payload)
        row = {
            "algoVersionId": f"av-{type(self).version_creates}",
            "versionName": payload["versionName"],
            "versionNo": payload["versionNo"],
        }
        if payload.get("analysisId"):
            row["analysisId"] = payload["analysisId"]
        type(self).versions.append(row)
        return {"code": 200, "data": {"algoVersionId": row["algoVersionId"]}}

    def list_version_weights(self, algo_version_id):
        type(self).last_weight_list_path = f"/internal/algorithm/algorithm-weight/listByVersion/{algo_version_id}"
        return {"code": 200, "data": list(self.weights)}

    def create_weight(self, payload):
        type(self).last_weight_create_path = "/internal/algorithm/algorithm-weight/add"
        type(self).weight_creates += 1
        type(self).last_weight_payload = dict(payload)
        row = {"weightId": f"w-{type(self).weight_creates}", **dict(payload)}
        type(self).weights.append(row)
        return {"code": 200, "data": {"weightId": row["weightId"]}}


class FakeChangLianSyncClient:
    def __init__(self, **_kwargs):
        pass

    def category_tree(self):
        return {
            "code": 200,
            "data": [{
                "categoryId": "category-root",
                "categoryName": "园区安全",
                "children": [{
                    "categoryId": "category-smoking",
                    "categoryName": "抽烟行为",
                }],
            }],
        }

    def products(self):
        return {
            "code": 200,
            "data": [{
                "productId": "product-live-1",
                "productName": "抽烟检测",
                "categoryId": "category-smoking",
            }],
        }

    def analyses(self, product_id):
        assert product_id == "product-live-1"
        return {
            "code": 200,
            "data": [
                {"analysisId": "analysis-day", "analysisName": "白天视觉分析"},
                {"analysisId": "analysis-night", "analysisName": "夜间视觉分析"},
            ],
        }

    def compute_platforms(self):
        return {
            "code": 200,
            "data": [{
                "computePlatformId": "cp-rk",
                "computePlatformName": "瑞芯微 RKNN",
            }],
        }


class RecoveringPublishingClient(FakePublishingClient):
    def create_algorithm_version(self, payload):
        type(self).version_creates += 1
        row = {
            "algoVersionId": "recovered-version",
            "versionName": payload["versionName"],
            "versionNo": payload["versionNo"],
        }
        if payload.get("analysisId"):
            row["analysisId"] = payload["analysisId"]
        type(self).versions.append(row)
        raise RuntimeError("connection reset after server commit")

    def create_weight(self, payload):
        type(self).weight_creates += 1
        row = {"weightId": "recovered-weight", **dict(payload)}
        type(self).weights.append(row)
        raise RuntimeError("connection reset after server commit")


class AmbiguousAnalysisRecoveringClient(FakePublishingClient):
    def create_algorithm_version(self, payload):
        type(self).version_creates += 1
        type(self).versions.append({
            "algoVersionId": "ambiguous-version",
            "versionName": payload["versionName"],
            "versionNo": payload["versionNo"],
        })
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
    repository.save_cache({
        "provider": "changlian",
        "synced_at": "2026-09-19T12:00:00Z",
        "master_data_digest": "digest-current",
        "categories": [],
        "products": [{"productId": "product-1", "productName": "抽烟检测"}],
        "analyses_by_product": {"product-1": [{"analysisId": "analysis-1", "analysisName": "视觉智能分析"}]},
        "compute_platforms": [
            {"computePlatformId": "cp-rk", "computePlatformName": "瑞芯微 RKNN"},
            {"computePlatformId": "cp-onnx", "computePlatformName": "ONNX"},
        ],
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
        "external_analysis_ids": ["analysis-1"],
        "external_analyses": [{"analysis_id": "analysis-1", "analysis_name": "视觉智能分析"}],
        "external_active": True,
        "external_master_data_digest": "digest-current",
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


def _seed_conversion(
    root: Path,
    *,
    project_id="p1",
    version_id="v1",
    target="rockchip",
    job_id="convert-1",
    chip="rk3568",
    content=b"converted-rknn",
    algorithm_id="a1",
):
    job_root = _project_dir(root, project_id) / "deployment" / "jobs" / job_id
    suffix = {
        "onnx": ".onnx",
        "rockchip": ".rknn",
        "tensorrt": ".engine",
        "ascend": ".om",
        "sophon": ".bmodel",
    }.get(str(target).lower(), ".bin")
    output = job_root / "outputs" / f"model{suffix}"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)
    (job_root / "job.json").write_text(json.dumps({
        "id": job_id,
        "status": "done",
        "target": target,
        "source_id": f"version::{algorithm_id}::{version_id}",
        "source_meta": {"algorithm_id": algorithm_id, "version_id": version_id},
        "params": {"chip": chip},
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
            "rockchip": TargetMapping(compute_platform_id="cp-rk", chip_code="RK3568"),
        },
    ))
    return service


def test_synced_changlian_identity_survives_training_choice_conversion_and_publish(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()

    platform = ExternalAlgorithmPlatformService(
        data_dir=tmp_path,
        secret_store_factory=lambda: memory,
        client_factory=FakeChangLianSyncClient,
    )
    platform.save(ExternalPlatformConfigPayload(
        mode="external",
        provider="changlian",
        base_url="https://changlian.example",
        access_key="ak",
        access_secret="secret",
        endpoints=EndpointPayload(),
    ))

    algorithms_path = _algorithms_file(tmp_path, "p1")
    save_algorithms(algorithms_path, [])
    synced = platform.sync(project_id="p1", algorithms_path=algorithms_path)
    assert synced["ok"] is True

    algorithms = list_algorithms(algorithms_path)
    assert len(algorithms) == 1
    algorithm = algorithms[0]
    assert algorithm["external_product_id"] == "product-live-1"
    assert algorithm["external_category_id"] == "category-smoking"
    assert set(algorithm["external_analysis_ids"]) == {"analysis-day", "analysis-night"}

    selected_analysis = resolve_external_training_analysis(algorithm, "analysis-night")
    assert selected_analysis == "analysis-night"

    model = _project_dir(tmp_path, "p1") / "algorithm_versions" / algorithm["id"] / "v-live" / "best.pt"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"trained-model")
    algorithm["versions"] = [{
        "id": "v-live",
        "version_name": "20260919230000",
        "training_status": "SUCCEEDED",
        "artifact_verified": True,
        "stored_path": str(model),
        "model_name": model.name,
        "external_analysis_id": selected_analysis,
    }]
    algorithm["current_version_id"] = "v-live"
    save_algorithms(algorithms_path, algorithms)

    _seed_conversion(
        tmp_path,
        project_id="p1",
        version_id="v-live",
        target="rockchip",
        job_id="convert-rk3576-live",
        chip="rk3576",
        content=b"rk3576-live-model",
        algorithm_id=algorithm["id"],
    )

    publish = _service(tmp_path, memory)
    result = publish.publish(
        project_id="p1",
        algorithm_id=algorithm["id"],
        version_id="v-live",
    )

    assert result["publication"]["status"] == "PUBLISHED"
    assert result["publication"]["external_product_id"] == "product-live-1"
    assert result["publication"]["external_analysis_id"] == "analysis-night"
    assert FakePublishingClient.last_version_payload == {
        "versionName": "20260919230000",
        "versionNo": "20260919230000",
        "analysisId": "analysis-night",
    }
    assert FakePublishingClient.last_weight_payload["algoVersionId"] == "av-1"
    assert FakePublishingClient.last_weight_payload["computePlatformId"] == "cp-rk"
    assert FakePublishingClient.last_weight_payload["chipCode"] == "RK3576"
    assert FakePublishingClient.last_weight_payload["fileName"] == "model.rknn"
    assert FakePublishingClient.last_weight_payload["filePath"].startswith(
        "https://platform.example/api/v64/model-artifacts/"
    )


def test_legacy_publish_storage_cannot_overwrite_canonical_model_asset_storage(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    service = _service(tmp_path, memory)
    sources = service.storage_sources_factory()
    sources.create({
        "id": "archive_local",
        "name": "模型归档存储",
        "type": "local",
        "config": {},
        "enabled": True,
    })
    service.model_assets.save_config(ModelArtifactConfigPayload(
        storage_source_id="archive_local",
        object_prefix="model-assets",
        auto_upload_enabled=True,
    ))

    service.save_config(ExternalPublishConfigPayload(
        storage_source_id="default_local",
        public_base_url="https://platform.example",
        target_mappings={
            "rockchip": TargetMapping(compute_platform_id="cp-rk", chip_code="RK3568"),
        },
    ))

    canonical = service.model_assets.repository.config()
    assert canonical["storage_source_id"] == "archive_local"


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
    assert FakePublishingClient.last_version_list_path == "/internal/algorithm/algorithm-version/listByProduct/product-1"
    assert FakePublishingClient.last_version_create_path == "/internal/algorithm/algorithm-version/add"
    assert FakePublishingClient.last_weight_list_path == "/internal/algorithm/algorithm-weight/listByVersion/av-1"
    assert FakePublishingClient.last_weight_create_path == "/internal/algorithm/algorithm-weight/add"
    assert FakePublishingClient.last_version_payload == {
        "versionName": "20260917120000",
        "versionNo": "20260917120000",
        "analysisId": "analysis-1",
    }
    assert FakePublishingClient.last_weight_payload["algoVersionId"] == "av-1"
    assert FakePublishingClient.last_weight_payload["computePlatformId"] == "cp-rk"
    assert FakePublishingClient.last_weight_payload["chipCode"] == "RK3568"
    assert FakePublishingClient.last_weight_payload["fileName"] == "model.rknn"
    assert FakePublishingClient.last_weight_payload["filePath"].startswith(
        "https://platform.example/api/v64/model-artifacts/"
    )
    artifact = result["artifacts"][0]
    assert artifact["upload_status"] == "UPLOADED"
    assert artifact["sync_status"] == "SYNCED"
    assert artifact["compute_platform_id"] == "cp-rk"
    assert artifact["chip_code"] == "RK3568"
    assert artifact["public_url"].startswith("https://platform.example/api/v64/model-artifacts/")
    uploaded = _project_dir(tmp_path, "p1") / artifact["object_key"]
    assert uploaded.read_bytes() == b"converted-rknn"
    version = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]["versions"][0]
    assert version["external_publish_status"] == "published"
    assert version["external_algo_version_id"] == "av-1"


def test_rockchip_publish_ignores_intermediate_onnx_and_manifest_outputs(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)

    job_root = _project_dir(tmp_path, "p1") / "deployment" / "jobs" / "convert-rockchip-realistic"
    output_root = job_root / "outputs"
    output_root.mkdir(parents=True, exist_ok=True)
    intermediate = output_root / "model.onnx"
    final = output_root / "model_rk3568_fp.rknn"
    manifest = output_root / "manifest.json"
    intermediate.write_bytes(b"intermediate-onnx")
    final.write_bytes(b"final-rknn")
    manifest.write_text('{"status":"converted_unverified"}', encoding="utf-8")
    (job_root / "job.json").write_text(json.dumps({
        "id": "convert-rockchip-realistic",
        "status": "done",
        "target": "rockchip",
        "source_id": "version::a1::v1",
        "source_meta": {"algorithm_id": "a1", "version_id": "v1"},
        "params": {"chip": "rk3568"},
        "outputs": [
            {"path": str(intermediate), "available": True},
            {"path": str(final), "available": True},
            {"path": str(manifest), "available": True},
        ],
    }), encoding="utf-8")
    service = _service(tmp_path, memory)

    algorithm = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]
    version = algorithm["versions"][0]
    discovered = service.discover_artifacts("p1", algorithm, version)
    assert len(discovered) == 1
    assert discovered[0]["file_name"] == "model_rk3568_fp.rknn"
    assert discovered[0]["target"] == "rockchip"
    assert discovered[0]["chip_code"] == "RK3568"

    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    assert result["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.weight_creates == 1
    assert FakePublishingClient.last_weight_payload["fileName"] == "model_rk3568_fp.rknn"
    assert FakePublishingClient.last_weight_payload["chipCode"] == "RK3568"


def test_multiple_rockchip_artifacts_keep_each_conversion_chip_identity(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    shared_bytes = b"same-rknn-bytes-different-chip-contract"
    _seed_conversion(tmp_path, job_id="convert-rk3568", chip="rk3568", content=shared_bytes)
    _seed_conversion(tmp_path, job_id="convert-rk3576", chip="rk3576", content=shared_bytes)
    service = _service(tmp_path, memory)

    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert result["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.weight_creates == 2
    assert {row["chipCode"] for row in FakePublishingClient.weights} == {"RK3568", "RK3576"}
    assert {row["computePlatformId"] for row in FakePublishingClient.weights} == {"cp-rk"}
    artifacts = result["artifacts"]
    assert {row["chip_code"] for row in artifacts} == {"RK3568", "RK3576"}
    assert len({row["artifact_id"] for row in artifacts}) == 2
    assert len({row["source_sha256"] for row in artifacts}) == 1


def test_publication_status_blocks_stale_changlian_master_data(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    _seed_conversion(tmp_path)
    service = _service(tmp_path, memory)

    service.external_repository.save_cache({
        **service.external_repository.cache(),
        "master_data_digest": "digest-new",
    })

    status = service.publication_status("p1", "a1", "v1")
    assert status["identity_ready"] is False
    assert status["publish_ready"] is False
    assert status["identity_issues"][0]["code"] == "EXTERNAL_MASTER_DATA_STALE"

    try:
        service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
        assert False, "stale ChangLian master data must block before remote writes"
    except Exception as error:
        assert getattr(error, "code", "") == "EXTERNAL_MASTER_DATA_STALE"

    assert FakePublishingClient.version_creates == 0
    assert FakePublishingClient.weight_creates == 0


def test_publish_blocks_when_historical_version_analysis_is_no_longer_current(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    _seed_conversion(tmp_path)
    algorithms = list_algorithms(_algorithms_file(tmp_path, "p1"))
    algorithms[0]["external_analysis_id"] = "analysis-2"
    algorithms[0]["external_analysis_ids"] = ["analysis-2"]
    algorithms[0]["external_analyses"] = [
        {"analysis_id": "analysis-2", "analysis_name": "新版视觉智能分析"},
    ]
    algorithms[0]["versions"][0]["external_analysis_id"] = "analysis-1"
    save_algorithms(_algorithms_file(tmp_path, "p1"), algorithms)
    service = _service(tmp_path, memory)

    status = service.publication_status("p1", "a1", "v1")
    assert status["identity_ready"] is False
    assert status["publish_ready"] is False
    assert status["identity_issues"][0]["code"] == "EXTERNAL_VERSION_ANALYSIS_STALE"

    try:
        service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
        assert False, "removed analysis binding must not be silently remapped"
    except Exception as error:
        assert getattr(error, "code", "") == "EXTERNAL_VERSION_ANALYSIS_STALE"

    assert FakePublishingClient.version_creates == 0
    assert FakePublishingClient.weight_creates == 0


def test_publish_blocks_before_remote_version_when_public_base_url_missing(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    _seed_conversion(tmp_path)
    service = _service(tmp_path, memory)
    service.repository.save_config(ExternalPublishConfigPayload(
        storage_source_id="default_local",
        public_base_url="",
        target_mappings={
            "rockchip": TargetMapping(compute_platform_id="cp-rk", chip_code="RK3568"),
        },
    ))

    status = service.publication_status("p1", "a1", "v1")
    assert status["transport_ready"] is False
    assert status["public_base_url_configured"] is False
    assert status["publish_ready"] is False
    assert status["transport_issues"][0]["code"] == "EXTERNAL_PUBLISH_CONFIG_INCOMPLETE"

    try:
        service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
        assert False, "missing public URL must fail before remote version creation"
    except Exception as error:
        assert getattr(error, "code", "") == "EXTERNAL_PUBLISH_CONFIG_INCOMPLETE"

    assert FakePublishingClient.version_creates == 0
    assert FakePublishingClient.weight_creates == 0


def test_publish_blocks_before_remote_version_when_model_asset_storage_missing(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    _seed_conversion(tmp_path)
    service = _service(tmp_path, memory)
    service.model_assets.repository.save_config(ModelArtifactConfigPayload(
        storage_source_id="",
        object_prefix="model-assets",
        auto_upload_enabled=True,
    ))

    status = service.publication_status("p1", "a1", "v1")
    assert status["transport_ready"] is False
    assert status["model_asset_storage_source_id"] == ""
    assert status["publish_ready"] is False
    assert status["transport_issues"][0]["code"] == "MODEL_ARTIFACT_STORAGE_NOT_CONFIGURED"

    try:
        service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
        assert False, "missing model asset storage must fail before remote version creation"
    except Exception as error:
        assert getattr(error, "code", "") == "MODEL_ARTIFACT_STORAGE_NOT_CONFIGURED"

    assert FakePublishingClient.version_creates == 0
    assert FakePublishingClient.weight_creates == 0


def test_model_asset_upload_failure_happens_before_remote_version_creation(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    _seed_conversion(tmp_path)
    service = _service(tmp_path, memory)

    service.model_assets.ensure_uploaded = lambda _discovered: {
        "storage_status": "FAILED",
        "storage_error": "simulated storage outage",
    }

    try:
        service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
        assert False, "storage failure must stop before ChangLian version creation"
    except Exception as error:
        assert getattr(error, "code", "") == "MODEL_ARTIFACT_UPLOAD_FAILED"
        assert "storage outage" in str(getattr(error, "detail", error))

    assert FakePublishingClient.version_creates == 0
    assert FakePublishingClient.weight_creates == 0
    publication = service.repository.publication("p1", "a1", "v1")
    assert publication["status"] == "FAILED"


def test_publish_blocks_when_any_enabled_conversion_artifact_lacks_mapping(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    _seed_conversion(tmp_path, job_id="convert-rk3568", target="rockchip", chip="rk3568", content=b"rk")
    _seed_conversion(tmp_path, job_id="convert-onnx", target="onnx", chip="", content=b"onnx")
    service = _service(tmp_path, memory)

    status = service.publication_status("p1", "a1", "v1")
    assert status["mapped_artifact_count"] == 1
    assert status["blocked_artifact_count"] == 1
    assert status["ignored_artifact_count"] == 0
    assert status["publish_ready"] is False
    blocked = next(row for row in status["discovered"] if row["publish_mapping_status"] == "blocked")
    assert blocked["target"] == "onnx"
    assert "尚未配置畅联云算力环境" in blocked["publish_mapping_detail"]

    try:
        service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
        assert False, "partial mapping must not be silently published as complete"
    except Exception as error:
        assert getattr(error, "code", "") == "MODEL_ARTIFACT_MAPPING_INCOMPLETE"

    assert FakePublishingClient.version_creates == 0
    assert FakePublishingClient.weight_creates == 0


def test_publish_allows_explicitly_disabled_conversion_target_to_be_ignored(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    _seed_conversion(tmp_path, job_id="convert-rk3568", target="rockchip", chip="rk3568", content=b"rk")
    _seed_conversion(tmp_path, job_id="convert-onnx", target="onnx", chip="", content=b"onnx")
    service = _service(tmp_path, memory)
    service.save_config(ExternalPublishConfigPayload(
        storage_source_id="default_local",
        public_base_url="https://platform.example",
        target_mappings={
            "rockchip": TargetMapping(compute_platform_id="cp-rk", chip_code="RK3568", enabled=True),
            "onnx": TargetMapping(enabled=False),
        },
    ))

    status = service.publication_status("p1", "a1", "v1")
    assert status["mapped_artifact_count"] == 1
    assert status["blocked_artifact_count"] == 0
    assert status["ignored_artifact_count"] == 1
    assert status["publish_ready"] is True

    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    assert result["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.weight_creates == 1
    assert FakePublishingClient.weights[0]["chipCode"] == "RK3568"


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

def test_publication_persists_training_analysis_binding(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    algorithms = list_algorithms(_algorithms_file(tmp_path, "p1"))
    algorithms[0]["external_analysis_ids"] = ["analysis-1", "analysis-2"]
    algorithms[0]["external_analyses"] = [
        {"analysis_id": "analysis-1", "analysis_name": "视觉智能分析 A"},
        {"analysis_id": "analysis-2", "analysis_name": "视觉智能分析 B"},
    ]
    algorithms[0]["versions"][0]["external_analysis_id"] = "analysis-2"
    save_algorithms(_algorithms_file(tmp_path, "p1"), algorithms)
    _seed_conversion(tmp_path)
    service = _service(tmp_path, memory)

    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert result["publication"]["external_analysis_id"] == "analysis-2"
    assert FakePublishingClient.last_version_payload["analysisId"] == "analysis-2"
    assert "productId" not in FakePublishingClient.last_version_payload


def test_multi_analysis_version_recovery_matches_analysis_identity(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    algorithms = list_algorithms(_algorithms_file(tmp_path, "p1"))
    algorithms[0]["external_analysis_ids"] = ["analysis-1", "analysis-2"]
    algorithms[0]["external_analyses"] = [
        {"analysis_id": "analysis-1", "analysis_name": "视觉智能分析 A"},
        {"analysis_id": "analysis-2", "analysis_name": "视觉智能分析 B"},
    ]
    algorithms[0]["versions"][0]["external_analysis_id"] = "analysis-2"
    save_algorithms(_algorithms_file(tmp_path, "p1"), algorithms)
    _seed_conversion(tmp_path)
    FakePublishingClient.versions = [
        {
            "algoVersionId": "wrong-analysis-version",
            "versionName": "20260917120000",
            "versionNo": "20260917120000",
            "analysisId": "analysis-1",
        },
        {
            "algoVersionId": "right-analysis-version",
            "versionName": "20260917120000",
            "versionNo": "20260917120000",
            "analysisId": "analysis-2",
        },
    ]
    service = _service(tmp_path, memory)

    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert result["external_algo_version_id"] == "right-analysis-version"
    assert FakePublishingClient.version_creates == 0
    assert FakePublishingClient.last_weight_payload["algoVersionId"] == "right-analysis-version"


def test_multi_analysis_timeout_does_not_recover_version_without_analysis_identity(tmp_path: Path):
    AmbiguousAnalysisRecoveringClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    algorithms = list_algorithms(_algorithms_file(tmp_path, "p1"))
    algorithms[0]["external_analysis_ids"] = ["analysis-1", "analysis-2"]
    algorithms[0]["external_analyses"] = [
        {"analysis_id": "analysis-1", "analysis_name": "视觉智能分析 A"},
        {"analysis_id": "analysis-2", "analysis_name": "视觉智能分析 B"},
    ]
    algorithms[0]["versions"][0]["external_analysis_id"] = "analysis-2"
    save_algorithms(_algorithms_file(tmp_path, "p1"), algorithms)
    _seed_conversion(tmp_path)
    service = _service(tmp_path, memory, client_factory=AmbiguousAnalysisRecoveringClient)

    try:
        service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
        assert False, "ambiguous multi-analysis recovery must fail closed"
    except Exception as error:
        assert getattr(error, "code", "") == "EXTERNAL_VERSION_CREATE_UNKNOWN"

    assert AmbiguousAnalysisRecoveringClient.version_creates == 1
    assert AmbiguousAnalysisRecoveringClient.weight_creates == 0
    publication = service.repository.publication("p1", "a1", "v1")
    assert publication["status"] == "UNKNOWN"
    assert publication["external_algo_version_id"] == ""



def test_publish_config_rejects_stale_compute_platform_mapping(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    service = _service(tmp_path, memory)

    try:
        service.save_config(ExternalPublishConfigPayload(
            storage_source_id="default_local",
            public_base_url="https://platform.example",
            target_mappings={
                "rockchip": TargetMapping(compute_platform_id="cp-removed", chip_code="RK3568"),
            },
        ))
        assert False, "stale computePlatformId must be rejected"
    except Exception as error:
        assert getattr(error, "code", "") == "EXTERNAL_COMPUTE_PLATFORM_MAPPING_STALE"


def test_publish_fails_closed_if_compute_platform_mapping_becomes_stale_after_save(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    _seed_conversion(tmp_path)
    service = _service(tmp_path, memory)

    service.external_repository.save_cache({
        "provider": "changlian",
        "synced_at": "2026-09-19T13:00:00Z",
        "master_data_digest": "digest-current",
        "categories": [],
        "products": [{"productId": "product-1", "productName": "抽烟检测"}],
        "analyses_by_product": {"product-1": [{"analysisId": "analysis-1", "analysisName": "视觉智能分析"}]},
        "compute_platforms": [
            {"computePlatformId": "cp-new", "computePlatformName": "新的瑞芯微环境"},
        ],
    })

    try:
        service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
        assert False, "publish must fail closed when saved computePlatformId is stale"
    except Exception as error:
        assert getattr(error, "code", "") == "EXTERNAL_COMPUTE_PLATFORM_MAPPING_STALE"

    assert FakePublishingClient.version_creates == 0
    assert FakePublishingClient.weight_creates == 0
