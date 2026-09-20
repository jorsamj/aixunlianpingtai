import hashlib
import json
from pathlib import Path

import pytest

from platform_core.algorithms import list_algorithms, save_algorithms
from platform_core.errors import PlatformError
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
        "version_list_by_product": "/custom/wrong-version-path/{productId}",
        "weight_list_by_version": "/custom/wrong-weight-path/{algoVersionId}",
    }), encoding="utf-8")
    config = repository.config()
    assert config["version_list_by_product"] == "/internal/algorithm/algorithm-version/listByProduct/{productId}"
    assert config["weight_list_by_version"] == "/internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}"


class FakePublishingClient:
    versions = []
    weights = []
    version_creates = 0
    weight_creates = 0
    weight_edits = 0
    version_removes = 0
    removed_version_ids = []
    last_version_payload = None
    last_weight_payload = None
    last_version_list_path = None
    last_version_create_path = None
    last_weight_list_path = None
    last_weight_create_path = None
    last_weight_edit_path = None
    last_weight_edit_payload = None

    def __init__(self, **_kwargs):
        pass

    @classmethod
    def reset(cls):
        cls.versions = []
        cls.weights = []
        cls.version_creates = 0
        cls.weight_creates = 0
        cls.weight_edits = 0
        cls.version_removes = 0
        cls.removed_version_ids = []
        cls.last_version_payload = None
        cls.last_weight_payload = None
        cls.last_version_list_path = None
        cls.last_version_create_path = None
        cls.last_weight_list_path = None
        cls.last_weight_create_path = None
        cls.last_weight_edit_path = None
        cls.last_weight_edit_payload = None

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

    def version_remove(self, algo_version_ids):
        ids = [str(value) for value in algo_version_ids]
        type(self).version_removes += 1
        type(self).removed_version_ids.extend(ids)
        type(self).versions = [row for row in self.versions if str(row.get("algoVersionId") or "") not in set(ids)]
        return {"code": 200, "data": True}

    def create_weight(self, payload):
        type(self).last_weight_create_path = "/internal/algorithm/algorithm-weight/add"
        type(self).weight_creates += 1
        type(self).last_weight_payload = dict(payload)
        row = {"weightId": f"w-{type(self).weight_creates}", **dict(payload)}
        type(self).weights.append(row)
        return {"code": 200, "data": {"weightId": row["weightId"]}}

    def edit_weight(self, payload):
        type(self).last_weight_edit_path = "/internal/algorithm/algorithm-weight/edit"
        type(self).last_weight_edit_payload = dict(payload)
        weight_id = str(payload.get("weightId") or "")
        for row in type(self).weights:
            if str(row.get("weightId") or "") != weight_id:
                continue
            type(self).weight_edits += 1
            row.update({key: value for key, value in dict(payload).items() if key != "weightId"})
            return {"code": 200, "data": 1}
        raise RuntimeError(f"weight not found: {weight_id}")


class TimeoutAfterDeletePublishingClient(FakePublishingClient):
    def version_remove(self, algo_version_ids):
        ids = [str(value) for value in algo_version_ids]
        type(self).version_removes += 1
        type(self).removed_version_ids.extend(ids)
        type(self).versions = [
            row for row in self.versions
            if str(row.get("algoVersionId") or "") not in set(ids)
        ]
        raise RuntimeError("timeout after remote commit")


class TimeoutBeforeDeletePublishingClient(FakePublishingClient):
    def version_remove(self, algo_version_ids):
        ids = [str(value) for value in algo_version_ids]
        type(self).version_removes += 1
        type(self).removed_version_ids.extend(ids)
        raise RuntimeError("timeout before remote commit")


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
                {"analysisId": "analysis-day", "analysisName": "白天视觉分析", "analysisType": 1, "status": 1},
                {"analysisId": "analysis-night", "analysisName": "夜间视觉分析", "analysisType": 1, "status": 1},
            ],
        }

    def analysis_info(self, analysis_id):
        details = {
            "analysis-day": {
                "analysisId": "analysis-day",
                "productId": "product-live-1",
                "analysisName": "白天视觉分析",
                "analysisType": 1,
                "status": 1,
            },
            "analysis-night": {
                "analysisId": "analysis-night",
                "productId": "product-live-1",
                "analysisName": "夜间视觉分析",
                "analysisType": 1,
                "status": 1,
            },
        }
        return {"code": 200, "data": details[str(analysis_id)]}

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
        "analyses_by_product": {"product-1": [{"analysisId": "analysis-1", "analysisName": "视觉智能分析", "analysisType": 1, "status": 1}]},
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
        "external_analyses": [{"analysis_id": "analysis-1", "analysis_name": "视觉智能分析", "analysis_type": "1", "status": "1"}],
        "external_active": True,
        "external_master_data_digest": "digest-current",
        "versions": [{
            "id": version_id,
            "version_name": "20260917120000",
            "training_status": "SUCCEEDED",
            "artifact_verified": True,
            "stored_path": str(model),
            "model_name": model.name,
            "external_analysis_id": "analysis-1",
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
            "original": TargetMapping(compute_platform_id="cp-rk", chip_code=""),
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
        "https://platform.example/model-assets/"
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
    assert FakePublishingClient.weight_creates == 2
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
        "https://platform.example/model-assets/"
    )
    artifact = next(row for row in result["artifacts"] if row["target"] == "rockchip")
    assert artifact["upload_status"] == "UPLOADED"
    assert artifact["sync_status"] == "SYNCED"
    assert artifact["compute_platform_id"] == "cp-rk"
    assert artifact["chip_code"] == "RK3568"
    assert artifact["public_url"].startswith("https://platform.example/model-assets/")
    uploaded = _project_dir(tmp_path, "p1") / artifact["object_key"]
    assert uploaded.read_bytes() == b"converted-rknn"
    version = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]["versions"][0]
    assert version["external_publish_status"] == "published"
    assert version["external_algo_version_id"] == "av-1"


def test_published_weight_mapping_change_edits_existing_weight_without_duplicate_create(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    _seed_conversion(tmp_path)
    service = _service(tmp_path, memory)

    first = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    publication = first["publication"]
    assert FakePublishingClient.weight_creates == 2
    assert FakePublishingClient.weight_edits == 0

    service.save_config(ExternalPublishConfigPayload(
        storage_source_id="default_local",
        public_base_url="https://platform.example",
        target_mappings={
            "original": TargetMapping(compute_platform_id="cp-rk", chip_code=""),
            "rockchip": TargetMapping(compute_platform_id="cp-onnx", chip_code="RK3568"),
        },
    ))
    algorithm = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]
    version = algorithm["versions"][0]
    assert service.publication_requires_sync("p1", algorithm, version, publication) is True

    second = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert second["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.weight_creates == 2
    assert FakePublishingClient.weight_edits == 1
    assert FakePublishingClient.last_weight_edit_path == "/internal/algorithm/algorithm-weight/edit"
    remote = next(row for row in FakePublishingClient.weights if row["fileName"] == "model.rknn")
    assert remote["computePlatformId"] == "cp-onnx"
    artifact = next(row for row in second["artifacts"] if row["target"] == "rockchip")
    assert artifact["external_weight_id"] == remote["weightId"]
    assert artifact["sync_status"] == "SYNCED"


def test_published_weight_public_url_change_edits_existing_file_path_without_duplicate_create(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    _seed_conversion(tmp_path)
    service = _service(tmp_path, memory)

    first = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    publication = first["publication"]
    assert FakePublishingClient.weight_creates == 2

    model_config = service.model_assets.repository.config()
    service.model_assets.save_config(ModelArtifactConfigPayload(
        storage_source_id=str(model_config["storage_source_id"]),
        object_prefix=str(model_config["object_prefix"]),
        public_base_url="https://cdn.example",
        auto_upload_enabled=True,
    ))
    algorithm = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]
    version = algorithm["versions"][0]
    assert service.publication_requires_sync("p1", algorithm, version, publication) is True

    second = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert second["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.weight_creates == 2
    assert FakePublishingClient.weight_edits == 2
    assert all(str(row["filePath"]).startswith("https://cdn.example/") for row in FakePublishingClient.weights)
    assert all(row["sync_status"] == "SYNCED" for row in second["artifacts"])


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
    assert {row["target"] for row in discovered} == {"original", "rockchip"}
    rockchip = [row for row in discovered if row["target"] == "rockchip"]
    assert len(rockchip) == 1
    assert rockchip[0]["file_name"] == "model_rk3568_fp.rknn"
    assert rockchip[0]["chip_code"] == "RK3568"

    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    assert result["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.weight_creates == 2
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
    assert FakePublishingClient.weight_creates == 3
    assert {row["chipCode"] for row in FakePublishingClient.weights if str(row["fileName"]).endswith(".rknn")} == {"RK3568", "RK3576"}
    assert {row["computePlatformId"] for row in FakePublishingClient.weights} == {"cp-rk"}
    artifacts = [row for row in result["artifacts"] if row["target"] == "rockchip"]
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
        {"analysis_id": "analysis-2", "analysis_name": "新版视觉智能分析", "analysis_type": "1", "status": "1"},
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
    service.model_assets.save_config(ModelArtifactConfigPayload(
        storage_source_id="default_local",
        object_prefix="model-assets",
        public_base_url="",
        auto_upload_enabled=True,
    ))
    service.repository.save_config(ExternalPublishConfigPayload(
        storage_source_id="",
        public_base_url="",
        target_mappings={
            "original": TargetMapping(compute_platform_id="cp-rk"),
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
    assert status["mapped_artifact_count"] == 2
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
    assert status["mapped_artifact_count"] == 2
    assert status["blocked_artifact_count"] == 0
    assert status["ignored_artifact_count"] == 1
    assert status["publish_ready"] is True

    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    assert result["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.weight_creates == 2
    assert next(row for row in FakePublishingClient.weights if str(row["fileName"]).endswith(".rknn"))["chipCode"] == "RK3568"


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
    assert FakePublishingClient.weight_creates == 2


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
    assert RecoveringPublishingClient.weight_creates == 2


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


def test_conversion_in_progress_does_not_block_training_version_and_original_weight(tmp_path: Path):
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

    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert result["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.weight_creates == 1
    assert FakePublishingClient.weights[0]["fileName"] == "best.pt"

def test_publication_persists_training_analysis_binding(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    algorithms = list_algorithms(_algorithms_file(tmp_path, "p1"))
    algorithms[0]["external_analysis_ids"] = ["analysis-1", "analysis-2"]
    algorithms[0]["external_analyses"] = [
        {"analysis_id": "analysis-1", "analysis_name": "视觉智能分析 A", "analysis_type": "1", "status": "1"},
        {"analysis_id": "analysis-2", "analysis_name": "视觉智能分析 B", "analysis_type": "1", "status": "1"},
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
        {"analysis_id": "analysis-1", "analysis_name": "视觉智能分析 A", "analysis_type": "1", "status": "1"},
        {"analysis_id": "analysis-2", "analysis_name": "视觉智能分析 B", "analysis_type": "1", "status": "1"},
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
        {"analysis_id": "analysis-1", "analysis_name": "视觉智能分析 A", "analysis_type": "1", "status": "1"},
        {"analysis_id": "analysis-2", "analysis_name": "视觉智能分析 B", "analysis_type": "1", "status": "1"},
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
        "analyses_by_product": {"product-1": [{"analysisId": "analysis-1", "analysisName": "视觉智能分析", "analysisType": 1, "status": 1}]},
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


def test_rollback_remote_delete_uses_official_version_remove(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory)
    algorithms = list_algorithms(_algorithms_file(tmp_path, "p1"))
    algorithm = algorithms[0]
    version = algorithm["versions"][0]
    version["external_algo_version_id"] = "remote-version-1"

    result = service.delete_version_for_rollback(
        project_id="p1",
        algorithm=algorithm,
        version=version,
    )

    assert result["status"] == "deleted"
    assert result["external_algo_version_id"] == "remote-version-1"
    assert FakePublishingClient.version_removes == 1
    assert FakePublishingClient.removed_version_ids == ["remote-version-1"]


def test_published_version_detects_and_appends_late_conversion_weight(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory)

    first = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    assert first["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.weight_creates == 1

    _seed_conversion(tmp_path, job_id="convert-late", target="rockchip", chip="rk3568")
    algorithm = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]
    version = algorithm["versions"][0]
    publication = service.repository.publication("p1", "a1", "v1")
    assert service.publication_requires_sync("p1", algorithm, version, publication) is True

    second = service.publish(project_id="p1", algorithm_id="a1", version_id="v1", automatic=True)
    assert second["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.weight_creates == 2

    publication = service.repository.publication("p1", "a1", "v1")
    algorithm = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]
    assert service.publication_requires_sync("p1", algorithm, algorithm["versions"][0], publication) is False


def test_published_version_resyncs_when_canonical_model_artifact_is_not_uploaded(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory)

    first = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    assert first["publication"]["status"] == "PUBLISHED"

    model_rows = service.model_assets.repository.list(
        project_id="p1",
        algorithm_id="a1",
        version_id="v1",
    )
    original = next(row for row in model_rows if row["target"] == "original")
    service.model_assets.repository.patch(
        original["artifact_id"],
        storage_status="FAILED",
        storage_error="simulated canonical artifact loss",
    )

    algorithm = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]
    publication = service.repository.publication("p1", "a1", "v1")
    assert service.publication_requires_sync(
        "p1",
        algorithm,
        algorithm["versions"][0],
        publication,
    ) is True


def test_auto_publish_readiness_uses_canonical_model_storage_url(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory)

    service.repository.save_config(ExternalPublishConfigPayload(
        storage_source_id="",
        public_base_url="",
        target_mappings={
            "original": TargetMapping(compute_platform_id="cp-rk"),
            "rockchip": TargetMapping(compute_platform_id="cp-rk", chip_code="RK3568"),
        },
    ))
    service.model_assets.save_config(ModelArtifactConfigPayload(
        storage_source_id="default_local",
        object_prefix="model-assets",
        public_base_url="https://oss.example.com",
        auto_upload_enabled=True,
    ))

    assert service.auto_publish_ready() is True


def test_auto_publish_worker_recovers_successful_external_version_without_request_marker(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    (tmp_path / "projects.json").write_text(
        json.dumps([{"id": "p1", "name": "项目1"}]),
        encoding="utf-8",
    )
    service = _service(tmp_path, memory)

    algorithm = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]
    assert "external_publish_requested_at" not in algorithm["versions"][0]

    result = service.run_auto_publish_once()

    assert result["checked"] == 1
    assert result["published"] == 1
    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.weight_creates == 1
    version = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]["versions"][0]
    assert version["external_publish_requested_at"]
    assert version["external_publish_status"] == "published"


def test_rollback_remote_delete_fails_closed_when_same_name_remote_version_is_ambiguous(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory)
    algorithm = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]
    version = algorithm["versions"][0]
    FakePublishingClient.versions = [
        {"algoVersionId": "remote-a", "versionName": version["version_name"]},
        {"algoVersionId": "remote-b", "versionName": version["version_name"]},
    ]

    try:
        service.delete_version_for_rollback(
            project_id="p1",
            algorithm=algorithm,
            version=version,
        )
        assert False, "ambiguous same-name remote versions must stop local deletion"
    except Exception as error:
        assert getattr(error, "code", "") == "EXTERNAL_VERSION_DELETE_AMBIGUOUS"

    assert FakePublishingClient.version_removes == 0


def test_durable_remote_conversion_root_is_discovered_and_appended(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory)

    first = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    assert first["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.weight_creates == 1

    job_root = _project_dir(tmp_path, "p1") / "deploy" / "jobs" / "remote-rknn"
    output = job_root / "artifacts" / "model_rk3576.rknn"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"remote-rknn-result")
    (job_root / "job.json").write_text(json.dumps({
        "id": "remote-rknn",
        "status": "done",
        "target": "rockchip",
        "source_trace": {"algorithm_id": "a1", "version_id": "v1"},
        "params": {"chip": "rk3576"},
        "outputs": [{"path": str(output), "available": True}],
    }), encoding="utf-8")

    second = service.publish(project_id="p1", algorithm_id="a1", version_id="v1", automatic=True)

    assert second["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.weight_creates == 2
    remote_weight = next(row for row in FakePublishingClient.weights if row["fileName"] == "model_rk3576.rknn")
    assert remote_weight["chipCode"] == "RK3576"


def test_publish_prefers_durable_remote_conversion_when_job_id_exists_in_both_roots(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory)

    first = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    assert first["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.weight_creates == 1

    project = _project_dir(tmp_path, "p1")
    job_id = "remote-rknn-collision"
    legacy_job = project / "deployment" / "jobs" / job_id
    legacy_job.mkdir(parents=True, exist_ok=True)
    (legacy_job / "job.json").write_text(json.dumps({
        "id": job_id,
        "status": "queued",
        "target": "rockchip",
        "source_trace": {"algorithm_id": "a1", "version_id": "v1"},
        "params": {"chip": "rk3576"},
        "outputs": [],
    }), encoding="utf-8")

    remote_job = project / "deploy" / "jobs" / job_id
    output = remote_job / "artifacts" / "model_rk3576.rknn"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"remote-rknn-collision-result")
    (remote_job / "job.json").write_text(json.dumps({
        "id": job_id,
        "status": "done",
        "target": "rockchip",
        "source_trace": {"algorithm_id": "a1", "version_id": "v1"},
        "params": {"chip": "rk3576"},
        "outputs": [{"path": str(output), "available": True}],
    }), encoding="utf-8")

    status = service.publication_status("p1", "a1", "v1")
    assert status["conversion_active"] is False
    algorithm = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]
    publication = service.repository.publication("p1", "a1", "v1")
    assert service.publication_requires_sync("p1", algorithm, algorithm["versions"][0], publication) is True

    second = service.publish(project_id="p1", algorithm_id="a1", version_id="v1", automatic=True)

    assert second["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.weight_creates == 2
    remote_weight = next(row for row in FakePublishingClient.weights if row["fileName"] == "model_rk3576.rknn")
    assert remote_weight["chipCode"] == "RK3576"


def test_publish_reuses_existing_verified_remote_training_object(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    model_path = _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory)

    object_key = "model-assets/remote-training/a1/v1/best.pt"
    stored = _project_dir(tmp_path, "p1") / object_key
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes(model_path.read_bytes())
    digest = hashlib.sha256(stored.read_bytes()).hexdigest()
    existing = service.model_assets.register_verified_remote_artifact(
        project_id="p1",
        algorithm_id="a1",
        version_id="v1",
        target="best",
        file_name="best.pt",
        sha256=digest,
        size_bytes=stored.stat().st_size,
        storage_source_id="default_local",
        object_key=object_key,
        source_path=str(model_path),
        artifact_kind="original",
        metadata={"remote_training": True, "role": "best"},
    )
    before = service.model_assets.repository.list(
        project_id="p1", algorithm_id="a1", version_id="v1"
    )
    assert len(before) == 1

    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert result["publication"]["status"] == "PUBLISHED"
    after = service.model_assets.repository.list(
        project_id="p1", algorithm_id="a1", version_id="v1"
    )
    assert len(after) == 1
    assert after[0]["artifact_id"] == existing["artifact_id"]
    assert FakePublishingClient.weight_creates == 1
    assert FakePublishingClient.weights[0]["filePath"] == existing["public_url"]


def test_publish_blocks_when_version_has_no_persisted_analysis_identity(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    algorithms = list_algorithms(_algorithms_file(tmp_path, "p1"))
    algorithms[0]["versions"][0].pop("external_analysis_id", None)
    save_algorithms(_algorithms_file(tmp_path, "p1"), algorithms)
    service = _service(tmp_path, memory)

    status = service.publication_status("p1", "a1", "v1")

    assert status["identity_ready"] is False
    assert status["publish_ready"] is False
    assert status["identity_issues"][0]["code"] == "EXTERNAL_VERSION_ANALYSIS_MISSING"

    with pytest.raises(Exception) as blocked:
        service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert getattr(blocked.value, "code", "") == "EXTERNAL_VERSION_ANALYSIS_MISSING"
    assert FakePublishingClient.version_creates == 0
    assert FakePublishingClient.weight_creates == 0


@pytest.mark.parametrize(
    ("analysis_type", "status"),
    [("1", "0"), ("3", "1")],
)
def test_publish_blocks_when_version_analysis_is_not_current_trainable_visual(
    tmp_path: Path,
    analysis_type: str,
    status: str,
):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    algorithms = list_algorithms(_algorithms_file(tmp_path, "p1"))
    algorithms[0]["external_analyses"] = [{
        "analysis_id": "analysis-1",
        "analysis_name": "当前分析方式",
        "analysis_type": analysis_type,
        "status": status,
    }]
    algorithms[0]["external_analysis_ids"] = (
        ["analysis-1"] if analysis_type == "1" and status == "1" else []
    )
    save_algorithms(_algorithms_file(tmp_path, "p1"), algorithms)
    service = _service(tmp_path, memory)

    with pytest.raises(Exception) as blocked:
        service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert getattr(blocked.value, "code", "") == "EXTERNAL_VERSION_ANALYSIS_STALE"
    assert FakePublishingClient.version_creates == 0
    assert FakePublishingClient.weight_creates == 0


def test_remote_version_creation_never_falls_back_to_product_id(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory)

    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert result["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.last_version_payload["analysisId"] == "analysis-1"
    assert "productId" not in FakePublishingClient.last_version_payload


def test_remote_delete_recovers_when_timeout_happens_after_remote_commit(tmp_path: Path):
    TimeoutAfterDeletePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory, client_factory=TimeoutAfterDeletePublishingClient)
    algorithm = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]
    version = algorithm["versions"][0]
    version["external_algo_version_id"] = "remote-version-timeout"
    TimeoutAfterDeletePublishingClient.versions = [{
        "algoVersionId": "remote-version-timeout",
        "versionName": version["version_name"],
    }]

    result = service.delete_version_for_rollback(
        project_id="p1",
        algorithm=algorithm,
        version=version,
    )

    assert result["status"] == "deleted"
    assert TimeoutAfterDeletePublishingClient.version_removes == 1
    assert TimeoutAfterDeletePublishingClient.versions == []


def test_remote_delete_timeout_fails_closed_when_version_still_exists(tmp_path: Path):
    TimeoutBeforeDeletePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory, client_factory=TimeoutBeforeDeletePublishingClient)
    algorithm = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]
    version = algorithm["versions"][0]
    version["external_algo_version_id"] = "remote-version-still-there"
    TimeoutBeforeDeletePublishingClient.versions = [{
        "algoVersionId": "remote-version-still-there",
        "versionName": version["version_name"],
    }]

    with pytest.raises(PlatformError) as blocked:
        service.delete_version_for_rollback(
            project_id="p1",
            algorithm=algorithm,
            version=version,
        )

    assert blocked.value.code == "EXTERNAL_VERSION_DELETE_FAILED"
    assert TimeoutBeforeDeletePublishingClient.version_removes == 1
    assert TimeoutBeforeDeletePublishingClient.versions[0]["algoVersionId"] == "remote-version-still-there"
