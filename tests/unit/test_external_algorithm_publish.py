from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
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
    PROVIDER_CHANGLIAN,
)
from platform_core.external_algorithm_publish import (
    _canonical_chip_code,
    _remote_id,
    DEFAULT_PUBLISH_CONFIG,
    ExternalAlgorithmPublishService,
    ExternalPublicationRepository,
    ExternalPublishConfigPayload,
    TargetMapping,
    request_external_auto_publish_for_conversion_if_enabled,
    request_external_auto_publish_if_enabled,
    wait_for_external_publish_owner,
)
from platform_core.model_artifacts import ModelArtifactConfigPayload
from platform_core.secrets import MemorySecretStore, SecretCredentialStore
from platform_core.storage.source_repository import StorageSourceRepository





def test_remote_id_accepts_official_scalar_data_ids():
    assert _remote_id({"code": 0, "data": 501}, ("algoVersionId",)) == "501"
    assert _remote_id({"code": 0, "data": 701}, ("weightId",)) == "701"

def test_canonical_chip_code_supports_current_rockchip_targets_without_adding_rk3588():
    assert _canonical_chip_code("rk3568") == "RK3568"
    assert _canonical_chip_code("rk-3578") == "RK3578"
    assert _canonical_chip_code("RK3578") == "RK3578"
    assert _canonical_chip_code("rk3576") == "RK3576"
    assert _canonical_chip_code("rk3588") == "rk3588"


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


def test_publication_repository_delete_algorithm_cascades_version_and_weight_mappings(tmp_path: Path):
    repository = ExternalPublicationRepository(tmp_path)
    algorithm = {"id": "a1", "external_product_id": "p1"}
    version = {
        "id": "v1",
        "version_name": "20260924090000",
        "version_no": "20260924090000",
        "external_analysis_id": "analysis-1",
    }
    publication = repository.ensure_publication(
        project_id="project-1",
        algorithm=algorithm,
        version=version,
    )
    repository.ensure_artifact_publication(
        publication["publication_key"],
        {
            "artifact_id": "artifact-a1",
            "chip_code": "",
        },
        {
            "compute_platform_id": "cp-general",
            "chip_code": "",
        },
    )

    result = repository.delete_algorithm("project-1", "a1")

    assert result["publications_deleted"] == 1
    assert result["artifact_mappings_deleted"] == 1
    assert repository.publication("project-1", "a1", "v1") is None
    assert repository.artifact_publication("artifact-a1") is None


def test_publication_repository_delete_version_cascades_only_target_version(
    tmp_path: Path,
):
    repository = ExternalPublicationRepository(tmp_path)
    algorithm = {"id": "a1", "external_product_id": "p1"}

    for version_id in ("v1", "v2"):
        version = {
            "id": version_id,
            "version_name": version_id.upper(),
            "version_no": version_id,
            "external_analysis_id": "analysis-1",
        }
        publication = repository.ensure_publication(
            project_id="project-1",
            algorithm=algorithm,
            version=version,
        )
        repository.ensure_artifact_publication(
            publication["publication_key"],
            {"artifact_id": f"artifact-{version_id}", "chip_code": ""},
            {"compute_platform_id": "cp-general", "chip_code": ""},
        )

    result = repository.delete_version("project-1", "a1", "v1")

    assert result["publications_deleted"] == 1
    assert result["artifact_mappings_deleted"] == 1
    assert repository.publication("project-1", "a1", "v1") is None
    assert repository.artifact_publication("artifact-v1") is None
    assert repository.publication("project-1", "a1", "v2") is not None
    assert repository.artifact_publication("artifact-v2") is not None


def test_new_external_publish_save_does_not_persist_legacy_storage_fields(tmp_path: Path):
    repository = ExternalPublicationRepository(tmp_path)

    assert "storage_source_id" not in DEFAULT_PUBLISH_CONFIG
    assert "public_base_url" not in DEFAULT_PUBLISH_CONFIG

    saved = repository.save_config(ExternalPublishConfigPayload(
        storage_source_id="legacy-oss",
        public_base_url="https://legacy.example.com",
        target_mappings={"onnx": TargetMapping(compute_platform_id="cp-onnx", chip_code="ONNX")},
    ))
    durable = json.loads(repository.config_path.read_text(encoding="utf-8"))

    assert "storage_source_id" not in durable
    assert "public_base_url" not in durable
    assert "storage_source_id" not in saved
    assert "public_base_url" not in saved
    assert durable["target_mappings"]["onnx"]["compute_platform_id"] == "cp-onnx"


def test_legacy_external_publish_storage_is_migrated_to_new_owners(tmp_path: Path):
    repository = ExternalPublicationRepository(tmp_path)
    repository.config_path.write_text(json.dumps({
        "schema_version": 2,
        "storage_source_id": "default_local",
        "public_base_url": "https://legacy-models.example.com",
        "target_mappings": {},
    }), encoding="utf-8")
    memory = MemorySecretStore()
    sources = StorageSourceRepository(tmp_path / "storage" / "storage_sources.sqlite3")
    credentials = SecretCredentialStore(memory)

    service = ExternalAlgorithmPublishService(
        data_dir=tmp_path,
        project_dir=lambda pid: _project_dir(tmp_path, pid),
        algorithms_file=lambda pid: _algorithms_file(tmp_path, pid),
        external_secret_store_factory=lambda: memory,
        storage_sources_factory=lambda: sources,
        storage_credentials_factory=lambda: credentials,
        client_factory=FakePublishingClient,
        artifact_url_probe=lambda _url: None,
    )

    assert service.model_assets.repository.config()["storage_source_id"] == "default_local"
    source = sources.get("default_local")
    assert source is not None
    assert source.config["public_base_url"] == "https://legacy-models.example.com"


def test_runtime_ignores_stale_legacy_publish_storage_fields(tmp_path: Path):
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    service = _service(tmp_path, memory)
    sources = service.storage_sources_factory()
    source = sources.get("default_local")
    assert source is not None
    current_config = dict(source.config)
    current_config.pop("public_base_url", None)
    sources.update("default_local", {"config": current_config})
    service.repository.config_path.write_text(json.dumps({
        "schema_version": 2,
        "storage_source_id": "default_local",
        "public_base_url": "https://stale-legacy.example.com",
        "target_mappings": {},
    }), encoding="utf-8")

    state = service._publish_transport_state()

    assert state["ready"] is False
    assert state["public_base_url"] == ""
    assert state["storage_source_id"] == "default_local"


class FakePublishingClient:
    versions = []
    weights = []
    version_creates = 0
    weight_creates = 0
    weight_edits = 0
    weight_lists = 0
    version_lists = 0
    version_removes = 0
    removed_version_ids = []
    last_version_payload = None
    last_weight_payload = None
    last_version_list_path = None
    last_analysis_version_list_path = None
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
        cls.weight_lists = 0
        cls.version_lists = 0
        cls.version_removes = 0
        cls.removed_version_ids = []
        cls.last_version_payload = None
        cls.last_weight_payload = None
        cls.last_version_list_path = None
        cls.last_analysis_version_list_path = None
        cls.last_version_create_path = None
        cls.last_weight_list_path = None
        cls.last_weight_create_path = None
        cls.last_weight_edit_path = None
        cls.last_weight_edit_payload = None

    def list_product_versions(self, product_id):
        type(self).last_version_list_path = f"/internal/algorithm/algorithm-version/listByProduct/{product_id}"
        type(self).version_lists += 1
        return {"code": 200, "data": list(self.versions)}

    def list_analysis_versions(self, analysis_id):
        type(self).last_analysis_version_list_path = f"/internal/algorithm/algorithm-version/listByAnalysis/{analysis_id}"
        return {
            "code": 200,
            "data": [
                row for row in self.versions
                if str(row.get("analysisId") or "") == str(analysis_id)
            ],
        }

    def create_algorithm_version(self, payload):
        type(self).last_version_create_path = "/internal/algorithm/algorithm-version/add"
        type(self).version_creates += 1
        type(self).last_version_payload = dict(payload)
        row = {
            "algoVersionId": f"av-{type(self).version_creates}",
            "versionName": payload["versionName"],
        }
        if payload.get("versionNo"):
            row["versionNo"] = payload["versionNo"]
        if payload.get("analysisId"):
            row["analysisId"] = payload["analysisId"]
        type(self).versions.append(row)
        return {"code": 200, "data": {"algoVersionId": row["algoVersionId"]}}

    def list_version_weights(self, algo_version_id):
        type(self).last_weight_list_path = f"/internal/algorithm/algorithm-weight/listByVersion/{algo_version_id}"
        type(self).weight_lists += 1
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

    def products(self, **_filters):
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
        }
        if payload.get("versionNo"):
            row["versionNo"] = payload["versionNo"]
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
        row = {
            "algoVersionId": "ambiguous-version",
            "versionName": payload["versionName"],
        }
        if payload.get("versionNo"):
            row["versionNo"] = payload["versionNo"]
        type(self).versions.append(row)
        raise RuntimeError("connection reset after server commit")


class AnalysisFallbackPublishingClient(FakePublishingClient):
    analysis_versions = []

    @classmethod
    def reset(cls):
        super().reset()
        cls.analysis_versions = []

    def list_analysis_versions(self, analysis_id):
        type(self).last_analysis_version_list_path = f"/internal/algorithm/algorithm-version/listByAnalysis/{analysis_id}"
        return {"code": 0, "data": list(self.analysis_versions)}


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
            "version_no": "20260917120000",
            "training_status": "SUCCEEDED",
            "artifact_verified": True,
            "stored_path": str(model),
            "model_name": model.name,
            "external_analysis_id": "analysis-1",
            "training_lineage": {"base": {"model": "yolo11n.pt"}, "parameters": {"actual": {"imgsz": 800}}},
            "label_schema": [{"class_id": 0, "code": "smoke"}],
            "label_codes": ["smoke"],
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
        "params": {"chip": chip, "input_size": 640},
        "outputs": [{"path": str(output), "available": True}],
    }), encoding="utf-8")
    return output


def _service(
    root: Path,
    memory: MemorySecretStore,
    client_factory=FakePublishingClient,
    artifact_url_probe=lambda _url: None,
):
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
        artifact_url_probe=artifact_url_probe,
    )
    service.save_config(ExternalPublishConfigPayload(
        storage_source_id="default_local",
        public_base_url="https://platform.example",
        target_mappings={
            "original": TargetMapping(compute_platform_id="cp-rk", chip_code="PYTORCH"),
            "rockchip": TargetMapping(compute_platform_id="cp-rk", chip_code="RK3568"),
        },
    ))
    return service


def _version(root: Path, project_id: str = "p1", algorithm_id: str = "a1", version_id: str = "v1"):
    algorithm = next(
        row for row in list_algorithms(_algorithms_file(root, project_id))
        if str(row.get("id") or "") == algorithm_id
    )
    version = next(
        row for row in algorithm.get("versions") or []
        if str(row.get("id") or "") == version_id
    )
    return algorithm, version


def _inject_legacy_version_remote_fields(
    root: Path,
    *,
    version_id: str = "v1",
    external_algo_version_id: str = "",
    external_publish_status: str = "",
) -> None:
    """Simulate pre-owner-migration SQLite rows without using runtime writers."""
    db_path = _project_dir(root, "p1") / "algorithms.sqlite3"
    with sqlite3.connect(db_path) as database:
        database.execute(
            """
            UPDATE algorithm_versions
            SET external_algo_version_id=?, external_publish_status=?
            WHERE id=?
            """,
            (external_algo_version_id, external_publish_status, version_id),
        )


def test_version_publications_are_unique_per_provider(tmp_path: Path):
    _seed_external_algorithm(tmp_path)
    algorithm, version = _version(tmp_path)
    repository = ExternalPublicationRepository(tmp_path)

    changlian = repository.ensure_publication(
        provider=PROVIDER_CHANGLIAN,
        project_id="p1",
        algorithm=algorithm,
        version=version,
    )
    secondary = repository.ensure_publication(
        provider="SECONDARY_PROVIDER",
        project_id="p1",
        algorithm=algorithm,
        version=version,
    )

    assert changlian["provider"] == PROVIDER_CHANGLIAN
    assert secondary["provider"] == "SECONDARY_PROVIDER"
    assert changlian["publication_key"] != secondary["publication_key"]
    with sqlite3.connect(repository.db_path) as database:
        count = database.execute(
            "SELECT COUNT(*) FROM external_version_publications WHERE project_id='p1' AND algorithm_id='a1' AND version_id='v1'"
        ).fetchone()[0]
    assert count == 2


def test_repository_migrates_actual_legacy_schema_with_provider_key_once(tmp_path: Path):
    root = tmp_path / "external_algorithm_publish"
    root.mkdir(parents=True)
    db_path = root / "publications.sqlite3"
    legacy_key = hashlib.sha256(b"p1:a1:v1").hexdigest()[:32]
    with sqlite3.connect(db_path) as database:
        database.executescript(
            """
            CREATE TABLE external_version_publications (
                publication_key TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                algorithm_id TEXT NOT NULL, version_id TEXT NOT NULL,
                external_product_id TEXT NOT NULL, external_analysis_id TEXT NOT NULL DEFAULT '',
                version_name TEXT NOT NULL, external_algo_version_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'PENDING', last_error TEXT NOT NULL DEFAULT '',
                attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, published_at TEXT
            );
            CREATE TABLE external_model_artifacts (
                artifact_id TEXT PRIMARY KEY, publication_key TEXT NOT NULL,
                project_id TEXT NOT NULL, algorithm_id TEXT NOT NULL, version_id TEXT NOT NULL,
                target TEXT NOT NULL, file_name TEXT NOT NULL, source_path TEXT NOT NULL,
                source_sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL,
                compute_platform_id TEXT NOT NULL DEFAULT '', chip_code TEXT NOT NULL DEFAULT '',
                storage_source_id TEXT NOT NULL DEFAULT '', object_key TEXT NOT NULL DEFAULT '',
                public_url TEXT NOT NULL DEFAULT '', upload_status TEXT NOT NULL DEFAULT 'PENDING',
                external_weight_id TEXT NOT NULL DEFAULT '', sync_status TEXT NOT NULL DEFAULT 'PENDING',
                last_error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            """
        )
        database.execute(
            """
            INSERT INTO external_version_publications
            VALUES (?, 'p1', 'a1', 'v1', 'product-1', 'analysis-1', 'V1',
                    'remote-v1', 'PUBLISHED', '', 1, '2026-09-21T00:00:00Z',
                    '2026-09-21T00:00:00Z', '2026-09-21T00:00:00Z')
            """,
            (legacy_key,),
        )
        database.execute(
            """
            INSERT INTO external_model_artifacts
            VALUES ('legacy-a1', ?, 'p1', 'a1', 'v1', 'original', 'best.pt',
                    'C:/models/best.pt', ?, 12, 'cp-rk', 'PYTORCH', 'oss-1',
                    'legacy/key.pt', 'https://models.example/legacy/key.pt', 'UPLOADED',
                    'remote-w1', 'SYNCED', '', '2026-09-21T00:00:00Z', '2026-09-21T00:00:00Z')
            """,
            (legacy_key, "a" * 64),
        )

    first = ExternalPublicationRepository(tmp_path)
    publication = first.publication("p1", "a1", "v1", provider=PROVIDER_CHANGLIAN)
    mapping = first.artifact_publication("legacy-a1", provider=PROVIDER_CHANGLIAN)
    second = ExternalPublicationRepository(tmp_path)

    assert publication["provider"] == PROVIDER_CHANGLIAN
    assert publication["publication_key"] != legacy_key
    assert first.legacy_artifact("legacy-a1")["publication_key"] == publication["publication_key"]
    assert mapping["external_weight_id"] == "remote-w1"
    with sqlite3.connect(second.db_path) as database:
        assert database.execute("SELECT COUNT(*) FROM external_version_publications").fetchone()[0] == 1
        assert database.execute("SELECT COUNT(*) FROM external_artifact_publications").fetchone()[0] == 1


def test_legacy_version_remote_identity_backfills_once(tmp_path: Path):
    _seed_external_algorithm(tmp_path)
    _inject_legacy_version_remote_fields(
        tmp_path,
        external_algo_version_id="legacy-version-501",
        external_publish_status="published",
    )
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)

    first_service = _service(tmp_path, memory)
    first = first_service.publication_status("p1", "a1", "v1")["publication"]
    second_service = _service(tmp_path, memory)
    second = second_service.publication_status("p1", "a1", "v1")["publication"]

    assert first["provider"] == PROVIDER_CHANGLIAN
    assert first["external_algo_version_id"] == "legacy-version-501"
    assert first["status"] == "PUBLISHED"
    assert second["publication_key"] == first["publication_key"]
    with sqlite3.connect(second_service.repository.db_path) as database:
        count = database.execute(
            "SELECT COUNT(*) FROM external_version_publications WHERE provider=? AND project_id='p1' AND algorithm_id='a1' AND version_id='v1'",
            (PROVIDER_CHANGLIAN,),
        ).fetchone()[0]
    assert count == 1


def test_conflicting_legacy_and_publication_version_ids_fail_closed(tmp_path: Path):
    FakePublishingClient.reset()
    _seed_external_algorithm(tmp_path)
    algorithm, version = _version(tmp_path)
    repository = ExternalPublicationRepository(tmp_path)
    publication = repository.ensure_publication(
        provider=PROVIDER_CHANGLIAN,
        project_id="p1",
        algorithm=algorithm,
        version=version,
    )
    repository.patch_publication(
        publication["publication_key"],
        external_algo_version_id="new-owner-version-502",
        status="VERSION_READY",
    )
    _inject_legacy_version_remote_fields(
        tmp_path,
        external_algo_version_id="legacy-version-501",
    )
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    service = _service(tmp_path, memory)

    status = service.publication_status("p1", "a1", "v1")
    assert status["publication"]["status"] == "UNKNOWN"
    assert "MIGRATION_CONFLICT" in status["publication"]["last_error"]
    with pytest.raises(PlatformError) as captured:
        service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert captured.value.code == "EXTERNAL_PUBLICATION_RECONCILIATION_REQUIRED"
    assert FakePublishingClient.version_creates == 0
    assert FakePublishingClient.weight_creates == 0


def test_publish_uses_model_artifact_and_provider_mapping_single_owners(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory)

    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    status = service.publication_status("p1", "a1", "v1")
    _, durable_version = _version(tmp_path)
    artifact = result["artifacts"][0]
    canonical = service.model_assets.repository.get(artifact["artifact_id"])
    mapping = service.repository.artifact_publication(
        artifact["artifact_id"], provider=PROVIDER_CHANGLIAN
    )

    assert canonical is not None
    assert canonical["file_name"] == "best.pt"
    assert canonical["storage_status"] == "UPLOADED"
    assert mapping["external_weight_id"] == "w-1"
    assert mapping["sync_status"] == "SYNCED"
    assert mapping["compute_platform_id"] == "cp-rk"
    assert mapping["remote_chip_code"] == "PYTORCH"
    assert "file_name" not in mapping
    assert "source_path" not in mapping
    assert "object_key" not in mapping
    assert "public_url" not in mapping
    assert "external_algo_version_id" not in durable_version
    assert "external_publish_status" not in durable_version
    assert status["version"]["external_algo_version_id"] == "av-1"
    assert status["version"]["external_publish_status"] == "published"
    with sqlite3.connect(service.repository.db_path) as database:
        legacy_count = database.execute("SELECT COUNT(*) FROM external_model_artifacts").fetchone()[0]
        mapping_columns = {
            row[1] for row in database.execute("PRAGMA table_info(external_artifact_publications)").fetchall()
        }
    assert legacy_count == 0
    assert not {
        "file_name", "source_path", "source_sha256", "size_bytes",
        "storage_source_id", "object_key", "public_url", "upload_status",
    } & mapping_columns


def test_rollback_uses_version_publication_owner(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory)
    service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    algorithm, version = _version(tmp_path)

    assert "external_algo_version_id" not in version
    result = service.delete_version_for_rollback(
        project_id="p1", algorithm=algorithm, version=version,
    )

    assert result["status"] == "deleted"
    assert result["external_algo_version_id"] == "av-1"
    assert FakePublishingClient.removed_version_ids == ["av-1"]


def test_legacy_artifact_backfill_is_idempotent_and_old_store_is_frozen(tmp_path: Path):
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    model_path = _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory)
    algorithm, version = _version(tmp_path)
    publication = service.repository.ensure_publication(
        provider=PROVIDER_CHANGLIAN,
        project_id="p1",
        algorithm=algorithm,
        version=version,
    )
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    artifact_id = "legacy-artifact-1"
    canonical_id = "canonical-artifact-1"
    service.model_assets.repository.upsert({
        "artifact_id": canonical_id,
        "project_id": "p1",
        "algorithm_id": "a1",
        "version_id": "v1",
        "artifact_kind": "original",
        "target": "original",
        "chip_code": "",
        "conversion_job_id": "",
        "file_name": "best.pt",
        "source_path": str(model_path),
        "sha256": digest,
        "size_bytes": model_path.stat().st_size,
        "metadata": {},
    })
    with sqlite3.connect(service.repository.db_path) as database:
        database.execute(
            """
            INSERT INTO external_model_artifacts
            (artifact_id, publication_key, project_id, algorithm_id, version_id, target,
             file_name, source_path, source_sha256, size_bytes, compute_platform_id,
             chip_code, storage_source_id, object_key, public_url, upload_status,
             external_weight_id, sync_status, last_error, created_at, updated_at)
            VALUES (?, ?, 'p1', 'a1', 'v1', 'original', 'best.pt', ?, ?, ?,
                    'cp-rk', 'PYTORCH', 'default_local', 'legacy/key.pt',
                    'https://platform.example/legacy/key.pt', 'UPLOADED',
                    'legacy-weight-701', 'SYNCED', '', '2026-09-21T00:00:00Z', '2026-09-21T00:00:00Z')
            """,
            (artifact_id, publication["publication_key"], str(model_path), digest, model_path.stat().st_size),
        )
    migrated_once = _service(tmp_path, memory)
    migrated_twice = _service(tmp_path, memory)

    canonical = migrated_twice.model_assets.repository.get(canonical_id)
    mapping = migrated_twice.repository.artifact_publication(
        canonical_id, provider=PROVIDER_CHANGLIAN
    )
    assert migrated_twice.model_assets.repository.get(artifact_id) is None
    assert canonical["sha256"] == digest
    assert canonical["object_key"] == "legacy/key.pt"
    assert mapping["external_weight_id"] == "legacy-weight-701"
    with sqlite3.connect(migrated_twice.repository.db_path) as database:
        count = database.execute(
            "SELECT COUNT(*) FROM external_artifact_publications WHERE provider=? AND artifact_id=?",
            (PROVIDER_CHANGLIAN, canonical_id),
        ).fetchone()[0]
        legacy_history = database.execute(
            """
            SELECT active, superseded_by_artifact_id
            FROM external_artifact_publications
            WHERE provider=? AND artifact_id=?
            """,
            (PROVIDER_CHANGLIAN, artifact_id),
        ).fetchone()
    assert count == 1
    assert legacy_history == (0, canonical_id)
    with pytest.raises(PlatformError) as captured:
        migrated_once.repository.upsert_artifact(
            publication["publication_key"],
            {
                "artifact_id": "new-legacy-write", "project_id": "p1", "algorithm_id": "a1",
                "version_id": "v1", "target": "original", "file_name": "best.pt",
                "source_path": str(model_path), "sha256": digest, "size_bytes": model_path.stat().st_size,
            },
            {"compute_platform_id": "cp-rk", "chip_code": "PYTORCH"},
        )
    assert captured.value.code == "LEGACY_EXTERNAL_ARTIFACT_STORE_FROZEN"


def test_conflicting_legacy_and_provider_weight_ids_fail_closed(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory)
    published = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    publication = published["publication"]
    artifact = published["artifacts"][0]
    canonical = service.model_assets.repository.get(artifact["artifact_id"])
    assert canonical is not None
    with sqlite3.connect(service.repository.db_path) as database:
        database.execute(
            """
            INSERT INTO external_model_artifacts
            (artifact_id, publication_key, project_id, algorithm_id, version_id, target,
             file_name, source_path, source_sha256, size_bytes, compute_platform_id,
             chip_code, storage_source_id, object_key, public_url, upload_status,
             external_weight_id, sync_status, last_error, created_at, updated_at)
            VALUES (?, ?, 'p1', 'a1', 'v1', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'UPLOADED',
                    'conflicting-legacy-weight', 'SYNCED', '', ?, ?)
            """,
            (
                artifact["artifact_id"], publication["publication_key"], canonical["target"],
                canonical["file_name"], canonical["source_path"], canonical["sha256"],
                canonical["size_bytes"], artifact["compute_platform_id"], artifact["remote_chip_code"],
                canonical["storage_source_id"], canonical["object_key"], canonical["public_url"],
                "2026-09-21T00:00:00Z", "2026-09-21T00:00:00Z",
            ),
        )

    version_creates = FakePublishingClient.version_creates
    weight_creates = FakePublishingClient.weight_creates
    weight_edits = FakePublishingClient.weight_edits
    restarted = _service(tmp_path, memory)
    mapping = restarted.repository.artifact_publication(
        artifact["artifact_id"], provider=PROVIDER_CHANGLIAN,
    )
    assert mapping["sync_status"] == "UNKNOWN"
    assert "MIGRATION_CONFLICT" in mapping["last_error"]

    with pytest.raises(PlatformError) as captured:
        restarted.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert captured.value.code == "EXTERNAL_ARTIFACT_PUBLICATION_RECONCILIATION_REQUIRED"
    assert FakePublishingClient.version_creates == version_creates
    assert FakePublishingClient.weight_creates == weight_creates
    assert FakePublishingClient.weight_edits == weight_edits


def _seed_same_id_canonical_and_legacy_storage(
    root: Path,
    memory: MemorySecretStore,
    *,
    canonical_storage: dict | None = None,
    legacy_object_key: str = "legacy/models/best.pt",
    legacy_public_url: str = "https://platform.example/legacy/models/best.pt",
) -> tuple[str, str]:
    _configure_external(root, memory)
    model_path = _seed_external_algorithm(root)
    service = _service(root, memory)
    algorithm, version = _version(root)
    publication = service.repository.ensure_publication(
        provider=PROVIDER_CHANGLIAN,
        project_id="p1",
        algorithm=algorithm,
        version=version,
    )
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    artifact_id = "same-id-storage-artifact"
    service.model_assets.repository.upsert({
        "artifact_id": artifact_id,
        "project_id": "p1",
        "algorithm_id": "a1",
        "version_id": "v1",
        "artifact_kind": "original",
        "target": "original",
        "chip_code": "",
        "conversion_job_id": "",
        "file_name": "best.pt",
        "source_path": str(model_path),
        "sha256": digest,
        "size_bytes": model_path.stat().st_size,
        "metadata": {},
    })
    if canonical_storage:
        service.model_assets.repository.patch(artifact_id, **canonical_storage)
    with sqlite3.connect(service.repository.db_path) as database:
        database.execute(
            """
            INSERT INTO external_model_artifacts
            (artifact_id, publication_key, project_id, algorithm_id, version_id, target,
             file_name, source_path, source_sha256, size_bytes, compute_platform_id,
             chip_code, storage_source_id, object_key, public_url, upload_status,
             external_weight_id, sync_status, last_error, created_at, updated_at)
            VALUES (?, ?, 'p1', 'a1', 'v1', 'original', 'best.pt', ?, ?, ?,
                    'cp-rk', 'PYTORCH', 'default_local', ?, ?, 'UPLOADED',
                    '', 'PENDING', '', '2026-09-21T00:00:00Z', '2026-09-21T01:00:00Z')
            """,
            (
                artifact_id,
                publication["publication_key"],
                "D:/moved-working-directory/best.pt",
                digest,
                model_path.stat().st_size,
                legacy_object_key,
                legacy_public_url,
            ),
        )
    return artifact_id, publication["publication_key"]


def test_existing_canonical_artifact_backfills_missing_legacy_storage_truth_idempotently(tmp_path: Path):
    memory = MemorySecretStore()
    artifact_id, publication_key = _seed_same_id_canonical_and_legacy_storage(
        tmp_path, memory,
    )

    migrated_once = _service(tmp_path, memory)
    first = migrated_once.model_assets.repository.get(artifact_id)
    migrated_twice = _service(tmp_path, memory)
    second = migrated_twice.model_assets.repository.get(artifact_id)
    mapping = migrated_twice.repository.artifact_publication(
        artifact_id, provider=PROVIDER_CHANGLIAN,
    )

    assert first["storage_source_id"] == "default_local"
    assert first["object_key"] == "legacy/models/best.pt"
    assert first["public_url"] == "https://platform.example/legacy/models/best.pt"
    assert first["storage_status"] == "UPLOADED"
    assert first["uploaded_at"] == "2026-09-21T01:00:00Z"
    assert second == first
    assert mapping["publication_key"] == publication_key
    assert mapping["sync_status"] != "UNKNOWN"
    with sqlite3.connect(migrated_twice.repository.db_path) as database:
        count = database.execute(
            "SELECT COUNT(*) FROM external_artifact_publications WHERE provider=? AND artifact_id=?",
            (PROVIDER_CHANGLIAN, artifact_id),
        ).fetchone()[0]
    assert count == 1


def test_existing_canonical_artifact_storage_conflict_is_unknown_without_overwrite(tmp_path: Path):
    memory = MemorySecretStore()
    canonical_storage = {
        "storage_source_id": "default_local",
        "object_key": "canonical/models/best.pt",
        "public_url": "https://platform.example/canonical/models/best.pt",
        "storage_status": "UPLOADED",
        "storage_error": "",
        "uploaded_at": "2026-09-21T01:00:00Z",
    }
    artifact_id, _publication_key = _seed_same_id_canonical_and_legacy_storage(
        tmp_path,
        memory,
        canonical_storage=canonical_storage,
        legacy_object_key="legacy/models/best.pt",
        legacy_public_url="https://platform.example/legacy/models/best.pt",
    )

    migrated_once = _service(tmp_path, memory)
    migrated_twice = _service(tmp_path, memory)
    canonical = migrated_twice.model_assets.repository.get(artifact_id)
    mapping = migrated_twice.repository.artifact_publication(
        artifact_id, provider=PROVIDER_CHANGLIAN,
    )

    assert canonical["object_key"] == canonical_storage["object_key"]
    assert canonical["public_url"] == canonical_storage["public_url"]
    assert canonical["storage_status"] == "UPLOADED"
    assert mapping["sync_status"] == "UNKNOWN"
    assert "MIGRATION_CONFLICT" in mapping["last_error"]
    assert "object_key" in mapping["last_error"]
    assert "public_url" in mapping["last_error"]
    assert migrated_once.repository.artifact_publication(
        artifact_id, provider=PROVIDER_CHANGLIAN,
    )["last_error"] == mapping["last_error"]


def test_existing_canonical_artifact_uploaded_at_conflict_is_unknown_without_overwrite(tmp_path: Path):
    memory = MemorySecretStore()
    canonical_storage = {
        "storage_source_id": "default_local",
        "object_key": "legacy/models/best.pt",
        "public_url": "https://platform.example/legacy/models/best.pt",
        "storage_status": "UPLOADED",
        "storage_error": "",
        "uploaded_at": "2026-09-21T02:00:00Z",
    }
    artifact_id, _publication_key = _seed_same_id_canonical_and_legacy_storage(
        tmp_path,
        memory,
        canonical_storage=canonical_storage,
    )

    migrated = _service(tmp_path, memory)
    canonical = migrated.model_assets.repository.get(artifact_id)
    mapping = migrated.repository.artifact_publication(
        artifact_id, provider=PROVIDER_CHANGLIAN,
    )

    assert canonical["uploaded_at"] == canonical_storage["uploaded_at"]
    assert mapping["sync_status"] == "UNKNOWN"
    assert "uploaded_at" in mapping["last_error"]


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
        "version_no": "20260919230000",
        "training_status": "SUCCEEDED",
        "artifact_verified": True,
        "stored_path": str(model),
        "model_name": model.name,
        "external_analysis_id": selected_analysis,
        "training_lineage": {"base": {"model": "yolo11n.pt"}, "parameters": {"actual": {"imgsz": 800}}},
        "label_schema": [{"class_id": 0, "code": "smoke"}],
        "label_codes": ["smoke"],
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
    # Keep the Windows local-provider test root short enough for the canonical
    # full-SHA object key. Production OSS keys are not filesystem paths.
    sources = publish.storage_sources_factory()
    local_source = sources.get("default_local")
    assert local_source is not None
    sources.update("default_local", {
        "config": {**local_source.config, "root": str(tmp_path / "s")},
    })
    publish.model_assets.save_config(ModelArtifactConfigPayload(
        storage_source_id="default_local",
        root_prefix="a",
        auto_upload_enabled=True,
    ))
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
        "https://platform.example/a/projects/"
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
        "https://platform.example/changlian-ai/artifacts/projects/"
    )
    artifact = next(row for row in result["artifacts"] if row["target"] == "rockchip")
    assert artifact["storage_status"] == "UPLOADED"
    assert artifact["sync_status"] == "SYNCED"
    assert artifact["compute_platform_id"] == "cp-rk"
    assert artifact["chip_code"] == "rk3568"
    assert artifact["remote_chip_code"] == "RK3568"
    assert artifact["public_url"].startswith("https://platform.example/changlian-ai/artifacts/projects/")
    uploaded = _project_dir(tmp_path, "p1") / artifact["object_key"]
    assert uploaded.read_bytes() == b"converted-rknn"
    version = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]["versions"][0]
    assert "external_publish_status" not in version
    assert "external_algo_version_id" not in version
    assert result["publication"]["external_algo_version_id"] == "av-1"


def test_recovered_weight_missing_file_path_is_repaired_without_duplicate_create(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    FakePublishingClient.versions = [{
        "algoVersionId": "remote-existing-version",
        "versionName": "20260917120000",
        "versionNo": "20260917120000",
        "analysisId": "analysis-1",
    }]
    FakePublishingClient.weights = [{
        "weightId": "remote-existing-weight",
        "algoVersionId": "remote-existing-version",
        "computePlatformId": "cp-rk",
        "chipCode": "PYTORCH",
        "fileName": "best.pt",
        "filePath": "",
    }]
    service = _service(tmp_path, memory)

    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert result["publication"]["status"] == "PUBLISHED"
    assert result["external_algo_version_id"] == "remote-existing-version"
    assert FakePublishingClient.version_creates == 0
    assert FakePublishingClient.weight_creates == 0
    assert FakePublishingClient.weight_edits == 1
    remote = FakePublishingClient.weights[0]
    assert remote["weightId"] == "remote-existing-weight"
    assert remote["filePath"].startswith(
        "https://platform.example/changlian-ai/artifacts/projects/"
    )
    artifact = result["artifacts"][0]
    assert artifact["external_weight_id"] == "remote-existing-weight"
    assert artifact["sync_status"] == "SYNCED"
    assert artifact["public_url"] == remote["filePath"]


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
            "original": TargetMapping(compute_platform_id="cp-rk", chip_code="PYTORCH"),
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

    sources = service.storage_sources_factory()
    source = sources.get("default_local")
    assert source is not None
    sources.update("default_local", {
        "config": {**source.config, "public_base_url": "https://cdn.example"},
    })
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
        "params": {"chip": "rk3568", "input_size": 640},
        "outputs": [
            {"path": str(intermediate), "available": True},
            {"path": str(final), "available": True},
            {"path": str(manifest), "available": True},
        ],
    }), encoding="utf-8")
    service = _service(tmp_path, memory)
    # Keep the local-provider test path below the legacy Windows path limit;
    # the production OSS object key still uses the canonical full SHA256.
    sources = service.storage_sources_factory()
    local_source = sources.get("default_local")
    assert local_source is not None
    sources.update("default_local", {
        "config": {**local_source.config, "root": str(tmp_path / "s")},
    })

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
    assert {row["chip_code"] for row in artifacts} == {"rk3568", "rk3576"}
    assert {row["remote_chip_code"] for row in artifacts} == {"RK3568", "RK3576"}
    assert len({row["artifact_id"] for row in artifacts}) == 2
    assert len({row["sha256"] for row in artifacts}) == 1


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
        root_prefix="changlian-ai/artifacts/",
        auto_upload_enabled=True,
    ))
    sources = service.storage_sources_factory()
    source = sources.get("default_local")
    assert source is not None
    source_config = dict(source.config)
    source_config.pop("public_base_url", None)
    sources.update("default_local", {"config": source_config})
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


def test_publish_original_and_mapped_conversion_when_other_conversion_lacks_mapping(tmp_path: Path):
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
    assert status["deferred_conversion_count"] == 1
    assert status["ignored_artifact_count"] == 0
    assert status["publish_ready"] is True
    blocked = next(row for row in status["discovered"] if row["publish_mapping_status"] == "blocked")
    assert blocked["target"] == "onnx"

    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert result["publication"]["status"] == "PUBLISHED"
    assert result["external_algo_version_id"]
    assert len(result["deferred_conversions"]) == 1
    assert "onnx" in result["deferred_conversions"][0]
    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.weight_creates == 2
    assert {row["fileName"] for row in FakePublishingClient.weights} == {"best.pt", "model.rknn"}
    algorithm, version = _version(tmp_path)
    assert service.publication_requires_sync("p1", algorithm, version, result["publication"]) is False


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


def test_publish_uses_distinct_durable_version_name_and_number(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    algorithms = list_algorithms(_algorithms_file(tmp_path, "p1"))
    algorithms[0]["versions"][0]["version_name"] = "正式版本 V1"
    algorithms[0]["versions"][0]["version_no"] = "2026.09.21-001"
    save_algorithms(_algorithms_file(tmp_path, "p1"), algorithms)
    service = _service(tmp_path, memory)

    service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert FakePublishingClient.last_version_payload == {
        "versionName": "正式版本 V1",
        "versionNo": "2026.09.21-001",
        "analysisId": "analysis-1",
    }


def test_publish_allows_empty_version_no_and_omits_it_from_remote_payload(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    algorithms = list_algorithms(_algorithms_file(tmp_path, "p1"))
    algorithms[0]["versions"][0]["version_no"] = ""
    save_algorithms(_algorithms_file(tmp_path, "p1"), algorithms)
    service = _service(tmp_path, memory)

    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert result["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.last_version_payload["versionName"] == "20260917120000"
    assert FakePublishingClient.last_version_payload["analysisId"] == "analysis-1"
    assert "versionNo" not in FakePublishingClient.last_version_payload


def test_empty_local_version_no_recovers_unique_name_and_analysis_without_duplicate(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    algorithms = list_algorithms(_algorithms_file(tmp_path, "p1"))
    algorithms[0]["versions"][0]["version_no"] = ""
    save_algorithms(_algorithms_file(tmp_path, "p1"), algorithms)
    FakePublishingClient.versions = [{
        "algoVersionId": "remote-existing",
        "versionName": "20260917120000",
        "versionNo": "remote-sequence-42",
        "analysisId": "analysis-1",
    }]
    service = _service(tmp_path, memory)

    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert result["external_algo_version_id"] == "remote-existing"
    assert FakePublishingClient.version_creates == 0
    assert FakePublishingClient.weight_creates == 1


def test_empty_local_version_no_fails_closed_when_name_and_analysis_are_not_unique(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    algorithms = list_algorithms(_algorithms_file(tmp_path, "p1"))
    algorithms[0]["versions"][0]["version_no"] = ""
    save_algorithms(_algorithms_file(tmp_path, "p1"), algorithms)
    FakePublishingClient.versions = [
        {
            "algoVersionId": remote_id,
            "versionName": "20260917120000",
            "versionNo": remote_no,
            "analysisId": "analysis-1",
        }
        for remote_id, remote_no in (("remote-a", "1"), ("remote-b", "2"))
    ]
    service = _service(tmp_path, memory)

    with pytest.raises(PlatformError) as error:
        service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert error.value.code == "EXTERNAL_VERSION_RECOVERY_AMBIGUOUS"
    assert FakePublishingClient.version_creates == 0
    assert FakePublishingClient.weight_creates == 0


def test_version_recovery_uses_full_identity_then_falls_back_to_analysis(tmp_path: Path):
    AnalysisFallbackPublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    AnalysisFallbackPublishingClient.versions = [{
        "algoVersionId": "wrong-version-number",
        "versionName": "20260917120000",
        "versionNo": "different-number",
        "analysisId": "analysis-1",
    }]
    AnalysisFallbackPublishingClient.analysis_versions = [{
        "algoVersionId": "full-identity-version",
        "versionName": "20260917120000",
        "versionNo": "20260917120000",
        "analysisId": "analysis-1",
    }]
    service = _service(tmp_path, memory, client_factory=AnalysisFallbackPublishingClient)

    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert result["external_algo_version_id"] == "full-identity-version"
    assert AnalysisFallbackPublishingClient.version_creates == 0
    assert AnalysisFallbackPublishingClient.last_analysis_version_list_path.endswith("/analysis-1")


def test_version_recovery_deduplicates_same_remote_id_across_product_and_analysis_lists(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    FakePublishingClient.versions = [{
        "algoVersionId": "same-remote-version",
        "versionName": "20260917120000",
        "versionNo": "20260917120000",
        "analysisId": "analysis-1",
    }]
    service = _service(tmp_path, memory)

    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert result["external_algo_version_id"] == "same-remote-version"
    assert FakePublishingClient.version_creates == 0
    assert FakePublishingClient.last_version_list_path.endswith("/product-1")
    assert FakePublishingClient.last_analysis_version_list_path.endswith("/analysis-1")


def test_version_recovery_with_multiple_full_identity_matches_fails_unknown_without_post(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    FakePublishingClient.versions = [
        {
            "algoVersionId": remote_id,
            "versionName": "20260917120000",
            "versionNo": "20260917120000",
            "analysisId": "analysis-1",
        }
        for remote_id in ("duplicate-a", "duplicate-b")
    ]
    service = _service(tmp_path, memory)

    with pytest.raises(PlatformError) as error:
        service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert error.value.code == "EXTERNAL_VERSION_RECOVERY_AMBIGUOUS"
    assert FakePublishingClient.version_creates == 0
    assert FakePublishingClient.weight_creates == 0
    publication = service.repository.publication("p1", "a1", "v1")
    assert publication["status"] == "UNKNOWN"


def test_version_recovery_with_incomplete_identity_fails_unknown_without_post(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    FakePublishingClient.versions = [{
        "algoVersionId": "missing-version-number",
        "versionName": "20260917120000",
        "analysisId": "analysis-1",
    }]
    service = _service(tmp_path, memory)

    with pytest.raises(PlatformError) as error:
        service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert error.value.code == "EXTERNAL_VERSION_RECOVERY_AMBIGUOUS"
    assert FakePublishingClient.version_creates == 0
    assert FakePublishingClient.weight_creates == 0


def test_weight_recovery_rejects_same_identity_with_different_returned_file_path(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory)
    algorithm, version = service._algorithm_version("p1", "a1", "v1")
    publication = service.repository.ensure_publication(project_id="p1", algorithm=algorithm, version=version)
    discovered = service.discover_artifacts("p1", algorithm, version)[0]
    canonical = service.model_assets.repository.upsert({
        **discovered,
        "artifact_kind": "original",
        "conversion_job_id": "",
        "metadata": discovered["weight_metadata"],
    })
    canonical = service.model_assets.repository.patch(
        canonical["artifact_id"],
        public_url="https://models.example/current.pt",
        storage_status="UPLOADED",
    )
    mapping = service.repository.ensure_artifact_publication(
        publication["publication_key"], canonical,
        {"compute_platform_id": "cp-rk", "chip_code": "PYTORCH"},
        provider=PROVIDER_CHANGLIAN,
    )
    artifact = {**canonical, **mapping}
    FakePublishingClient.weights = [{
        "weightId": "same-name-wrong-url",
        "algoVersionId": "remote-v1",
        "computePlatformId": "cp-rk",
        "chipCode": "PYTORCH",
        "fileName": artifact["file_name"],
        "filePath": "https://models.example/other.pt",
    }]

    with pytest.raises(PlatformError) as error:
        service._sync_weight(artifact, "remote-v1", FakePublishingClient())

    assert error.value.code == "EXTERNAL_WEIGHT_RECOVERY_AMBIGUOUS"
    assert FakePublishingClient.weight_creates == 0
    stored = service.repository.artifact_publication(
        artifact["artifact_id"], provider=PROVIDER_CHANGLIAN,
    )
    assert stored["sync_status"] == "UNKNOWN"


def test_weight_recovery_never_downgrades_when_remote_chip_code_is_empty(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory)
    algorithm, version = service._algorithm_version("p1", "a1", "v1")
    publication = service.repository.ensure_publication(project_id="p1", algorithm=algorithm, version=version)
    discovered = service.discover_artifacts("p1", algorithm, version)[0]
    canonical = service.model_assets.repository.upsert({
        **discovered,
        "artifact_kind": "original",
        "conversion_job_id": "",
        "metadata": discovered["weight_metadata"],
    })
    canonical = service.model_assets.repository.patch(
        canonical["artifact_id"],
        public_url="https://models.example/current.pt",
        storage_status="UPLOADED",
    )
    mapping = service.repository.ensure_artifact_publication(
        publication["publication_key"], canonical,
        {"compute_platform_id": "cp-rk", "chip_code": "PYTORCH"},
        provider=PROVIDER_CHANGLIAN,
    )
    artifact = {**canonical, **mapping}
    FakePublishingClient.weights = [{
        "weightId": "missing-chip",
        "algoVersionId": "remote-v1",
        "computePlatformId": "cp-rk",
        "chipCode": "",
        "fileName": artifact["file_name"],
        "filePath": artifact["public_url"],
    }]

    with pytest.raises(PlatformError) as error:
        service._sync_weight(artifact, "remote-v1", FakePublishingClient())

    assert error.value.code == "EXTERNAL_WEIGHT_RECOVERY_AMBIGUOUS"
    assert FakePublishingClient.weight_creates == 0


def test_original_weight_allows_empty_chip_code(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory)
    service.save_config(ExternalPublishConfigPayload(
        storage_source_id="default_local",
        public_base_url="https://platform.example",
        target_mappings={
            "original": TargetMapping(compute_platform_id="cp-rk", chip_code=""),
            "rockchip": TargetMapping(compute_platform_id="cp-rk", chip_code="RK3568"),
        },
    ))

    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert result["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.weight_creates == 1
    assert FakePublishingClient.last_weight_payload["fileName"] == "best.pt"
    assert FakePublishingClient.last_weight_payload["filePath"].startswith("https://platform.example/")
    assert "chipCode" not in FakePublishingClient.last_weight_payload


def test_rockchip_missing_chip_is_deferred_until_new_chip_bound_artifact_arrives(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    _seed_conversion(tmp_path, target="rockchip", chip="", content=b"rk-without-chip")
    service = _service(tmp_path, memory)
    # Even a configured provider chip must not invent canonical identity for a
    # conversion artifact whose own job metadata omitted chip/soc_version.
    service.save_config(ExternalPublishConfigPayload(
        target_mappings={
            "original": TargetMapping(compute_platform_id="cp-rk", chip_code=""),
            "rockchip": TargetMapping(compute_platform_id="cp-rk", chip_code="RK3568"),
        },
    ))

    first = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert first["conversion_failures"] == []
    assert first["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.weight_creates == 1
    assert first["deferred_conversions"]
    assert "RKNN 产物缺少芯片身份" in first["deferred_conversions"][0]
    assert all(row["target"] != "rockchip" for row in first["artifacts"])
    algorithm, version = _version(tmp_path)
    assert service.publication_requires_sync(
        "p1", algorithm, version, first["publication"],
    ) is False

    # A new, correctly identified conversion is a new artifact identity and
    # automatically becomes appendable to the already-published remote Version.
    _seed_conversion(
        tmp_path,
        job_id="convert-rk3568-fixed",
        target="rockchip",
        chip="rk3568",
        content=b"rk-with-chip",
    )
    algorithm, version = _version(tmp_path)
    publication = service.repository.publication("p1", "a1", "v1")
    assert publication["status"] == "PUBLISHED"
    assert service.publication_requires_sync(
        "p1", algorithm, version, publication,
    ) is True

    second = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    assert second["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.weight_creates == 2
    rknn = next(row for row in FakePublishingClient.weights if row["fileName"].endswith(".rknn"))
    assert rknn["chipCode"] == "RK3568"


def test_legacy_contract_failed_publication_is_rearmed_once_without_losing_attempt_audit(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory)
    algorithm, version = _version(tmp_path)
    publication = service.repository.ensure_publication(
        project_id="p1", algorithm=algorithm, version=version,
    )
    service.repository.patch_publication(
        publication["publication_key"],
        status="FAILED",
        attempts=1152,
        last_error="新畅联权重发布字段不完整",
    )

    reopened = ExternalPublicationRepository(tmp_path)
    repaired = reopened.publication("p1", "a1", "v1")

    assert repaired["status"] == "PENDING"
    assert repaired["last_error"] == ""
    assert repaired["attempts"] == 1152


def test_blocked_config_does_not_auto_retry_until_publish_config_changes(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory)
    service.save_config(ExternalPublishConfigPayload(
        target_mappings={
            "original": TargetMapping(compute_platform_id="", chip_code=""),
        },
    ))

    with pytest.raises(PlatformError) as blocked:
        service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    assert blocked.value.code == "ORIGINAL_MODEL_MAPPING_INCOMPLETE"
    publication = service.repository.publication("p1", "a1", "v1")
    assert publication["status"] == "BLOCKED_CONFIG"
    attempts = publication["attempts"]
    assert service.repository.auto_retry_due(publication) is False

    skipped = service.publish(
        project_id="p1", algorithm_id="a1", version_id="v1", automatic=True,
    )
    assert skipped["skipped"] is True
    assert service.repository.publication("p1", "a1", "v1")["attempts"] == attempts

    service.save_config(ExternalPublishConfigPayload(
        target_mappings={
            "original": TargetMapping(compute_platform_id="cp-rk", chip_code=""),
        },
    ))
    reactivated = service.repository.publication("p1", "a1", "v1")
    assert reactivated["status"] == "PENDING"
    assert service.repository.auto_retry_due(reactivated) is True


def test_auto_publish_request_only_marks_external_version_when_enabled(tmp_path: Path, monkeypatch):
    # Drain any signal left by a prior request in the same pytest process.
    wait_for_external_publish_owner(0)
    import platform_core.external_publish_request as request_module
    emitted = []
    signal = request_module._EXTERNAL_PUBLISH_WAKE_EVENT.set
    def record_signal():
        emitted.append(True)
        signal()
    monkeypatch.setattr(request_module._EXTERNAL_PUBLISH_WAKE_EVENT, 'set', record_signal)
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
    assert "external_publish_status" not in version
    # The real background owner may already have consumed the single-consumer
    # signal. Observe emission, preserving the actual Event.set call.
    assert emitted == [True]
    wait_for_external_publish_owner(0)
    assert wait_for_external_publish_owner(0) is False



def test_conversion_publish_request_marks_blocked_by_hardware_version(tmp_path: Path):
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory, auto_publish=True)
    _seed_external_algorithm(tmp_path)

    marked = request_external_auto_publish_for_conversion_if_enabled(
        data_dir=tmp_path,
        project_id="p1",
        conversion_job={
            "status": "blocked_by_hardware",
            "source_trace": {"algorithm_id": "a1", "version_id": "v1"},
        },
        now="2026-09-24T10:00:00Z",
    )

    assert marked is True
    version = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]["versions"][0]
    assert version["external_publish_requested_at"] == "2026-09-24T10:00:00Z"


def test_conversion_publish_request_rejects_blocked_by_environment(tmp_path: Path):
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory, auto_publish=True)
    _seed_external_algorithm(tmp_path)

    marked = request_external_auto_publish_for_conversion_if_enabled(
        data_dir=tmp_path,
        project_id="p1",
        conversion_job={
            "status": "blocked_by_environment",
            "source_id": "version::a1::v1",
        },
        now="2026-09-24T10:01:00Z",
    )

    assert marked is False
    version = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]["versions"][0]
    assert "external_publish_requested_at" not in version


def test_publish_owner_stitches_training_request_and_late_rknn_weight(tmp_path: Path):
    """One existing owner must bridge training publication and late conversion publication."""
    FakePublishingClient.reset()
    wait_for_external_publish_owner(0)
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory, auto_publish=True)
    _seed_external_algorithm(tmp_path)
    (tmp_path / "projects.json").write_text(
        json.dumps([{"id": "p1", "name": "项目1"}]),
        encoding="utf-8",
    )
    service = _service(tmp_path, memory)

    training_requested = request_external_auto_publish_if_enabled(
        data_dir=tmp_path,
        algorithms_path=_algorithms_file(tmp_path, "p1"),
        algorithm_id="a1",
        version_id="v1",
        now="2026-09-28T12:10:00Z",
    )
    assert training_requested is True
    first = service.run_auto_publish_once()
    assert first["published"] == 1
    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.weight_creates == 1
    assert FakePublishingClient.weights[0]["fileName"] == "best.pt"

    _seed_conversion(
        tmp_path,
        job_id="convert-rk3568-after-training",
        target="rockchip",
        chip="rk3568",
        content=b"late-rk3568-model",
    )
    conversion_requested = request_external_auto_publish_for_conversion_if_enabled(
        data_dir=tmp_path,
        project_id="p1",
        conversion_job={
            "status": "done",
            "source_trace": {"algorithm_id": "a1", "version_id": "v1"},
        },
        now="2026-09-28T12:11:00Z",
    )
    assert conversion_requested is True

    second = service.run_auto_publish_once()
    assert second["published"] == 1
    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.weight_creates == 2
    rknn = next(
        row for row in FakePublishingClient.weights
        if str(row.get("fileName") or "").endswith(".rknn")
    )
    assert rknn["chipCode"] == "RK3568"
    assert rknn["algoVersionId"] == FakePublishingClient.weights[0]["algoVersionId"]

    algorithm = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]
    publication = service.repository.publication("p1", "a1", "v1")
    assert publication["status"] == "PUBLISHED"
    assert service.publication_requires_sync(
        "p1", algorithm, algorithm["versions"][0], publication,
    ) is False


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


def test_rollback_repairs_pre_v3_durable_training_version_number_before_remote_recovery(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory)

    algorithms_path = _algorithms_file(tmp_path, "p1")
    # Simulate a version written by the pre-v3 durable Training Task owner:
    # timestamp version_name + training_job_id, but no durable version_no.
    from platform_core.algorithm_sql_store import AlgorithmSqlStore
    store = AlgorithmSqlStore(algorithms_path)
    store.ensure_ready()
    with sqlite3.connect(store.db_path) as connection:
        payload_raw = connection.execute(
            "SELECT payload_json FROM algorithm_versions WHERE id='v1'"
        ).fetchone()[0]
        payload = json.loads(payload_raw)
        payload.pop("version_no", None)
        payload["task_id"] = "train-durable-old"
        connection.execute(
            """
            UPDATE algorithm_versions
            SET version_no=NULL, training_job_id=?, payload_json=?
            WHERE id='v1'
            """,
            ("train-durable-old", json.dumps(payload, ensure_ascii=False)),
        )
        connection.execute(
            "UPDATE algorithm_store_meta SET value='2' WHERE key='schema_version'"
        )
        connection.commit()

    FakePublishingClient.versions = [{
        "algoVersionId": "remote-version-recovered",
        "versionName": "20260917120000",
        "versionNo": "20260917120000",
        "analysisId": "analysis-1",
        "productId": "product-1",
    }]

    algorithm = list_algorithms(algorithms_path)[0]
    version = algorithm["versions"][0]
    assert version["version_no"] == version["version_name"]

    result = service.delete_version_for_rollback(
        project_id="p1",
        algorithm=algorithm,
        version=version,
    )

    assert result["status"] == "deleted"
    assert result["external_algo_version_id"] == "remote-version-recovered"
    assert FakePublishingClient.removed_version_ids == ["remote-version-recovered"]


def test_rollback_with_empty_version_no_recovers_unique_name_and_analysis(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    algorithms = list_algorithms(_algorithms_file(tmp_path, "p1"))
    algorithms[0]["versions"][0]["version_no"] = ""
    save_algorithms(_algorithms_file(tmp_path, "p1"), algorithms)
    FakePublishingClient.versions = [{
        "algoVersionId": "remote-version-no-number",
        "versionName": "20260917120000",
        "versionNo": "server-side-number",
        "analysisId": "analysis-1",
    }]
    service = _service(tmp_path, memory)
    algorithm = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]
    version = algorithm["versions"][0]

    result = service.delete_version_for_rollback(
        project_id="p1",
        algorithm=algorithm,
        version=version,
    )

    assert result["status"] == "deleted"
    assert result["external_algo_version_id"] == "remote-version-no-number"
    assert FakePublishingClient.removed_version_ids == ["remote-version-no-number"]


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


def test_blocked_by_hardware_rknn_is_still_appended_as_conversion_weight(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    service = _service(tmp_path, memory)

    first = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    assert first["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.weight_creates == 1

    output = _seed_conversion(
        tmp_path,
        job_id="convert-rknn-await-board",
        target="rockchip",
        chip="rk3568",
    )
    job_path = output.parents[1] / "job.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job.update({
        "status": "blocked_by_hardware",
        "conversion_status": "converted",
        "hardware_verified": False,
        "validation_status": "converted_unverified",
    })
    job_path.write_text(json.dumps(job), encoding="utf-8")

    algorithm = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]
    version = algorithm["versions"][0]
    publication = service.repository.publication("p1", "a1", "v1")
    assert service.publication_requires_sync("p1", algorithm, version, publication) is True

    second = service.publish(
        project_id="p1",
        algorithm_id="a1",
        version_id="v1",
        automatic=True,
    )

    assert second["publication"]["status"] == "PUBLISHED"
    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.weight_creates == 2
    remote = next(
        row for row in FakePublishingClient.weights
        if row["fileName"] == output.name
    )
    assert remote["chipCode"] == "RK3568"


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
        root_prefix="changlian-ai/artifacts/",
        auto_upload_enabled=True,
    ))
    sources = service.storage_sources_factory()
    source = sources.get("default_local")
    assert source is not None
    sources.update("default_local", {
        "config": {**source.config, "public_base_url": "https://oss.example.com"},
    })

    assert service.auto_publish_ready() is True


def test_publish_probes_actual_artifact_urls_before_remote_version(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    _seed_conversion(tmp_path)
    probed: list[str] = []

    def reject(url: str) -> None:
        probed.append(url)
        raise PlatformError(
            "MODEL_ARTIFACT_PUBLIC_URL_UNREACHABLE",
            "算法产物长期访问地址不可达",
            url,
            "修复外网地址后重试。",
            409,
        )

    service = _service(tmp_path, memory, artifact_url_probe=reject)

    with pytest.raises(PlatformError) as captured:
        service.publish(project_id="p1", algorithm_id="a1", version_id="v1")

    assert captured.value.code == "MODEL_ARTIFACT_PUBLIC_URL_UNREACHABLE"
    assert probed and probed[0].startswith(
        "https://platform.example/changlian-ai/artifacts/projects/p1/"
    )
    assert FakePublishingClient.version_creates == 0
    assert FakePublishingClient.weight_creates == 0
    publication = service.repository.publication("p1", "a1", "v1")
    assert publication is not None
    assert publication["status"] == "FAILED"


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
    assert "external_publish_status" not in version
    publication = service.repository.publication("p1", "a1", "v1")
    assert publication["status"] == "PUBLISHED"


def test_auto_publish_remote_reconcile_recreates_missing_weight_without_duplicate_version(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    (tmp_path / "projects.json").write_text(
        json.dumps([{"id": "p1", "name": "项目1"}]),
        encoding="utf-8",
    )
    service = _service(tmp_path, memory)

    first = service.run_auto_publish_once()
    assert first["published"] == 1
    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.weight_creates == 1

    publication = service.repository.publication("p1", "a1", "v1")
    service.repository.patch_publication(
        publication["publication_key"],
        remote_checked_at="2026-09-01T00:00:00Z",
        remote_check_error="",
    )
    FakePublishingClient.weights = []
    before_lists = FakePublishingClient.weight_lists

    repaired = service.run_auto_publish_once()

    assert repaired["remote_reconciled"] == 1
    assert repaired["remote_drifted"] >= 1
    assert repaired["published"] == 1
    assert FakePublishingClient.version_creates == 1
    assert FakePublishingClient.weight_creates == 2
    assert len(FakePublishingClient.weights) == 1
    assert FakePublishingClient.weight_lists >= before_lists + 2

    lists_after_repair = FakePublishingClient.weight_lists
    immediate = service.run_auto_publish_once()
    assert immediate["remote_reconciled"] == 0
    assert FakePublishingClient.weight_lists == lists_after_repair
    assert FakePublishingClient.weight_creates == 2


def test_auto_publish_remote_reconcile_recreates_missing_version_and_weights(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    (tmp_path / "projects.json").write_text(
        json.dumps([{"id": "p1", "name": "项目1"}]),
        encoding="utf-8",
    )
    service = _service(tmp_path, memory)

    first = service.run_auto_publish_once()
    assert first["published"] == 1
    old_version_id = FakePublishingClient.versions[0]["algoVersionId"]
    old_weight_id = FakePublishingClient.weights[0]["weightId"]

    publication = service.repository.publication("p1", "a1", "v1")
    service.repository.patch_publication(
        publication["publication_key"],
        remote_checked_at="2026-09-01T00:00:00Z",
        remote_check_error="",
    )
    FakePublishingClient.versions = []
    FakePublishingClient.weights = []

    repaired = service.run_auto_publish_once()

    assert repaired["remote_reconciled"] == 1
    assert repaired["remote_drifted"] >= 1
    assert repaired["published"] == 1
    assert FakePublishingClient.version_creates == 2
    assert FakePublishingClient.weight_creates == 2
    assert FakePublishingClient.versions[0]["algoVersionId"] != old_version_id
    assert FakePublishingClient.weights[0]["weightId"] != old_weight_id
    publication = service.repository.publication("p1", "a1", "v1")
    assert publication["status"] == "PUBLISHED"
    assert publication["external_algo_version_id"] == FakePublishingClient.versions[0]["algoVersionId"]


def test_remote_weight_reconcile_ambiguity_marks_publication_unknown_without_guessing(tmp_path: Path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    (tmp_path / "projects.json").write_text(
        json.dumps([{"id": "p1", "name": "项目1"}]),
        encoding="utf-8",
    )
    service = _service(tmp_path, memory)

    first = service.run_auto_publish_once()
    assert first["published"] == 1
    assert FakePublishingClient.weight_creates == 1
    canonical_remote = dict(FakePublishingClient.weights[0])
    publication = service.repository.publication("p1", "a1", "v1")
    service.repository.patch_publication(
        publication["publication_key"],
        remote_checked_at="2026-09-01T00:00:00Z",
        remote_check_error="",
    )
    FakePublishingClient.weights = [
        {**canonical_remote, "weightId": "ambiguous-weight-a"},
        {**canonical_remote, "weightId": "ambiguous-weight-b"},
    ]
    creates_before = FakePublishingClient.weight_creates
    edits_before = FakePublishingClient.weight_edits

    reconciled = service.run_auto_publish_once()

    assert reconciled["remote_reconciled"] == 1
    assert reconciled["published"] == 0
    assert FakePublishingClient.weight_creates == creates_before
    assert FakePublishingClient.weight_edits == edits_before
    publication = service.repository.publication("p1", "a1", "v1")
    assert publication["status"] == "UNKNOWN"
    assert "REMOTE_WEIGHT_RECONCILIATION_AMBIGUOUS" in publication["last_error"]
    mapping = service.repository.artifact_publications(publication["publication_key"])[0]
    assert mapping["sync_status"] == "UNKNOWN"
    assert mapping["external_weight_id"] == canonical_remote["weightId"]

    repeated = service.run_auto_publish_once()
    assert repeated["published"] == 0
    assert FakePublishingClient.weight_creates == creates_before
    assert FakePublishingClient.weight_edits == edits_before


def test_remote_reconcile_due_uses_long_success_and_short_failure_windows(tmp_path: Path):
    repository = ExternalPublicationRepository(tmp_path)
    now = datetime(2026, 10, 5, 6, 0, tzinfo=timezone.utc)
    base = {
        "status": "PUBLISHED",
        "external_algo_version_id": "av-1",
        "remote_checked_at": (now - timedelta(hours=1)).isoformat(),
        "remote_check_error": "",
    }
    assert repository.remote_reconcile_due(base, now=now) is False

    failed = {
        **base,
        "remote_checked_at": (now - timedelta(minutes=16)).isoformat(),
        "remote_check_error": "temporary timeout",
    }
    assert repository.remote_reconcile_due(failed, now=now) is True

    stale = {
        **base,
        "remote_checked_at": (now - timedelta(hours=7)).isoformat(),
    }
    assert repository.remote_reconcile_due(stale, now=now) is True


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
        "params": {"chip": "rk3576", "input_size": 640},
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
        "params": {"chip": "rk3576", "input_size": 640},
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
        "params": {"chip": "rk3576", "input_size": 640},
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
    algorithm, version = _version(tmp_path)
    assert service.publication_requires_sync(
        "p1", algorithm, version, result["publication"],
    ) is False


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


def _seed_complete_weight_version(root):
    _seed_external_algorithm(root)
    rows = list_algorithms(_algorithms_file(root, 'p1'))
    rows[0]['versions'][0].update({
        'training_lineage': {'base': {'model': 'yolo11s.pt'}, 'parameters': {'actual': {'imgsz': 800}}},
        'label_schema': [{'class_id': 1, 'code': 'fire'}, {'class_id': 0, 'code': 'smoke'}],
        'label_codes': ['smoke', 'fire'],
    })
    save_algorithms(_algorithms_file(root, 'p1'), rows)


def test_synced_legacy_weight_backfills_by_edit_once_when_list_omits_metadata(tmp_path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_complete_weight_version(tmp_path)
    service = _service(tmp_path, memory)
    first = service.publish(project_id='p1', algorithm_id='a1', version_id='v1')
    artifact = first['artifacts'][0]
    # Simulate an old registration: base identity is durable, extended fields
    # and the new acknowledgement receipt are absent, not guessed from lists.
    service.repository.patch_artifact_publication(artifact['artifact_id'], synced_payload_json='{}')
    extended = {'imageWidth', 'imageHeight', 'yoloVersion', 'fileSize', 'fileSha256', 'tags'}
    for key in extended:
        FakePublishingClient.weights[0].pop(key, None)
    algorithm, version = _version(tmp_path)
    assert service.publication_requires_sync('p1', algorithm, version, first['publication'])
    repaired = service.publish(project_id='p1', algorithm_id='a1', version_id='v1')
    assert FakePublishingClient.weight_edits == 1
    assert FakePublishingClient.weight_creates == FakePublishingClient.version_creates == 1
    assert FakePublishingClient.last_weight_edit_payload['weightId'] == artifact['external_weight_id']
    assert FakePublishingClient.last_weight_edit_payload['tags'] == ['smoke', 'fire']
    for key in extended:
        FakePublishingClient.weights[0].pop(key, None)
    assert not service.publication_requires_sync('p1', algorithm, version, repaired['publication'])
    assert not service.reconcile_published_remote(project_id='p1', algorithm_id='a1', version_id='v1', client=FakePublishingClient(), remote_versions=FakePublishingClient.versions)['drifted']
    service.publish(project_id='p1', algorithm_id='a1', version_id='v1')
    assert FakePublishingClient.weight_edits == 1


def test_synced_weight_metadata_change_rearms_existing_mapping(tmp_path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_complete_weight_version(tmp_path)
    service = _service(tmp_path, memory)
    first = service.publish(project_id='p1', algorithm_id='a1', version_id='v1')
    service.repository.patch_artifact_publication(first['artifacts'][0]['artifact_id'], synced_payload_json='{}')
    service.publish(project_id='p1', algorithm_id='a1', version_id='v1')
    assert FakePublishingClient.weight_edits == 0, 'full remote proof avoids an unnecessary edit'
    rows = list_algorithms(_algorithms_file(tmp_path, 'p1'))
    rows[0]['versions'][0]['training_lineage']['parameters']['actual']['imgsz'] = 960
    save_algorithms(_algorithms_file(tmp_path, 'p1'), rows)
    algorithm, version = _version(tmp_path)
    assert service.publication_requires_sync('p1', algorithm, version, first['publication'])
    service.publish(project_id='p1', algorithm_id='a1', version_id='v1')
    assert FakePublishingClient.last_weight_edit_payload['imageWidth'] == 960
    assert FakePublishingClient.weight_creates == 1


def test_metadata_edit_timeout_requires_full_remote_proof_and_never_blindly_retries(tmp_path, monkeypatch):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_complete_weight_version(tmp_path)
    service = _service(tmp_path, memory)
    first = service.publish(project_id='p1', algorithm_id='a1', version_id='v1')
    artifact = first['artifacts'][0]
    service.repository.patch_artifact_publication(artifact['artifact_id'], synced_payload_json='{}')
    FakePublishingClient.weights[0].pop('tags')
    calls = []
    edit = FakePublishingClient.edit_weight
    def timeout(_self, payload):
        calls.append(payload)
        raise TimeoutError('isolated timeout before metadata commit')
    monkeypatch.setattr(FakePublishingClient, 'edit_weight', timeout)
    for _ in range(2):
        with pytest.raises(PlatformError) as captured:
            service.publish(project_id='p1', algorithm_id='a1', version_id='v1')
        assert captured.value.code == 'EXTERNAL_WEIGHT_EDIT_UNKNOWN'
    assert len(calls) == 1
    assert service.repository.artifact_publication(artifact['artifact_id'])['sync_status'] == 'UNKNOWN'
    assert FakePublishingClient.weight_creates == 1
    # Complete the delayed remote operation through the same isolated client.
    edit(FakePublishingClient(), calls[0])
    recovered = service.publish(project_id='p1', algorithm_id='a1', version_id='v1')
    assert recovered['artifacts'][0]['sync_status'] == 'SYNCED'
    assert len(calls) == 1


def test_core_only_weight_registers_without_optional_metadata_or_empty_tags():
    FakePublishingClient.reset()
    payload = ExternalAlgorithmPublishService._weight_payload({
        'target': 'original', 'compute_platform_id': 'cp', 'file_name': 'best.pt',
        'public_url': 'https://isolated.example/best.pt', 'metadata': {},
    }, 'remote-v1')
    assert payload == {'algoVersionId':'remote-v1','computePlatformId':'cp',
                       'fileName':'best.pt','filePath':'https://isolated.example/best.pt'}
    assert FakePublishingClient().create_weight(payload)['data']['weightId'] == 'w-1'
    assert 'tags' not in FakePublishingClient.weights[0]


@pytest.mark.parametrize('missing', ['yolo', 'tags'])
def test_missing_optional_model_facts_stay_synced_and_never_clear_remote_tags(tmp_path, missing):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_complete_weight_version(tmp_path)
    rows = list_algorithms(_algorithms_file(tmp_path, 'p1'))
    version = rows[0]['versions'][0]
    if missing == 'yolo':
        version.pop('training_lineage')
    else:
        version.pop('label_schema')
        version.pop('label_codes')
    save_algorithms(_algorithms_file(tmp_path, 'p1'), rows)
    (_project_dir(tmp_path, 'p1') / 'meta.json').write_text(json.dumps({'labels':['helmet']}))
    service = _service(tmp_path, memory)
    result = service.publish(project_id='p1', algorithm_id='a1', version_id='v1')
    field = 'yoloVersion' if missing == 'yolo' else 'tags'
    assert result['publication']['status'] == 'PUBLISHED'
    assert result['artifacts'][0]['sync_status'] == 'SYNCED'
    assert field not in FakePublishingClient.last_weight_payload
    service.publish(project_id='p1', algorithm_id='a1', version_id='v1')
    assert FakePublishingClient.weight_creates == 1 and FakePublishingClient.weight_edits == 0
    if missing == 'tags':
        FakePublishingClient.weights[0]['tags'] = ['remote-existing']
        version['training_lineage']['parameters']['actual']['imgsz'] = 960
        save_algorithms(_algorithms_file(tmp_path, 'p1'), rows)
        service.publish(project_id='p1', algorithm_id='a1', version_id='v1')
        assert 'tags' not in FakePublishingClient.last_weight_edit_payload
        assert FakePublishingClient.weights[0]['tags'] == ['remote-existing']
    else:
        assert FakePublishingClient.last_weight_payload['tags'] == ['smoke','fire']


def test_read_only_recovery_failure_does_not_poison_first_weight_creation(tmp_path, monkeypatch):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_complete_weight_version(tmp_path)
    service = _service(tmp_path, memory)
    lists = FakePublishingClient.list_version_weights
    def unavailable(*_):
        raise ConnectionError('isolated read-only query outage')
    monkeypatch.setattr(FakePublishingClient, 'list_version_weights', unavailable)
    with pytest.raises(PlatformError):
        service.publish(project_id='p1', algorithm_id='a1', version_id='v1')
    assert FakePublishingClient.weight_creates == 0
    assert service.repository.artifact_publications(service.repository.publication('p1','a1','v1')['publication_key'])[0]['sync_status'] == 'PENDING'
    monkeypatch.setattr(FakePublishingClient, 'list_version_weights', lists)
    result = service.publish(project_id='p1', algorithm_id='a1', version_id='v1')
    assert result['publication']['status'] == 'PUBLISHED'
    assert FakePublishingClient.weight_creates == FakePublishingClient.version_creates == 1


def test_rectangular_original_input_retains_height_width_order():
    facts = ExternalAlgorithmPublishService._weight_model_metadata({
        'training_lineage': {'parameters': {'actual': {'imgsz': [384, 640]}}},
    })
    assert facts['image_width'] == 640 and facts['image_height'] == 384


def test_unknown_add_waits_for_unique_recovery_instead_of_recreating(tmp_path, monkeypatch):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_complete_weight_version(tmp_path)
    service = _service(tmp_path, memory)
    create = FakePublishingClient.create_weight
    def timeout_after_commit(client, payload):
        create(client, payload)
        raise TimeoutError('isolated lost acknowledgement')
    monkeypatch.setattr(FakePublishingClient, 'create_weight', timeout_after_commit)
    monkeypatch.setattr(FakePublishingClient, 'list_version_weights', lambda *_: {'code': 200, 'data': []})
    for _ in range(2):
        with pytest.raises(PlatformError):
            service.publish(project_id='p1', algorithm_id='a1', version_id='v1')
    assert FakePublishingClient.weight_creates == 1
    monkeypatch.setattr(FakePublishingClient, 'list_version_weights', lambda *_: {'code': 200, 'data': FakePublishingClient.weights})
    recovered = service.publish(project_id='p1', algorithm_id='a1', version_id='v1')
    assert recovered['artifacts'][0]['external_weight_id'] == FakePublishingClient.weights[0]['weightId']
    assert FakePublishingClient.weight_creates == FakePublishingClient.version_creates == 1


@pytest.mark.parametrize('chip,scale', [('rk3568','n'), ('rk3576','s')])
def test_late_rectangular_conversion_metadata_is_complete_without_changing_conversion_status(tmp_path, chip, scale):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_complete_weight_version(tmp_path)
    rows = list_algorithms(_algorithms_file(tmp_path, 'p1'))
    rows[0]['versions'][0]['training_lineage']['base']['model'] = f'yolo11{scale}.pt'
    save_algorithms(_algorithms_file(tmp_path, 'p1'), rows)
    service = _service(tmp_path, memory)
    first = service.publish(project_id='p1', algorithm_id='a1', version_id='v1')
    assert first['artifacts'][0]['metadata']['image_width'] == 800
    output = _seed_conversion(tmp_path, chip=chip, content=b'actual-rknn-bytes-unequal-to-pt')
    path = _project_dir(tmp_path, 'p1') / 'deployment/jobs/convert-1/job.json'
    job = json.loads(path.read_text())
    job.update(status='blocked_by_hardware', hardware_verified=False)
    job['params'].pop('input_size')
    path.write_text(json.dumps(job))
    incomplete = service.publish(project_id='p1', algorithm_id='a1', version_id='v1')
    assert incomplete['publication']['status'] == 'PUBLISHED'
    assert 'imageWidth' not in FakePublishingClient.last_weight_payload
    assert 'imageHeight' not in FakePublishingClient.last_weight_payload
    assert FakePublishingClient.weight_creates == 2
    status = service.publication_status('p1', 'a1', 'v1')
    rknn = next(row for row in status['artifacts'] if row['target'] == 'rockchip')
    assert rknn['sync_status'] == 'SYNCED'
    assert 'imageWidth' in rknn['metadata_note']
    job['params'].update(input_width=640, input_height=384)
    path.write_text(json.dumps(job))
    complete = service.publish(project_id='p1', algorithm_id='a1', version_id='v1')
    payload = {key: value for key, value in FakePublishingClient.last_weight_edit_payload.items() if key != 'weightId'}
    assert set(payload) == {'algoVersionId','computePlatformId','chipCode','fileName','filePath','imageWidth','imageHeight','yoloVersion','fileSize','fileSha256','tags'}
    assert (payload['imageWidth'], payload['imageHeight']) == (640, 384)
    assert payload['fileSize'] == output.stat().st_size != first['artifacts'][0]['size_bytes']
    assert payload['fileSha256'] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert payload['yoloVersion'] == f'YOLOv11{scale}' and payload['tags'] == ['smoke','fire']
    assert payload['chipCode'] == chip.upper()
    assert complete['publication']['status'] == 'PUBLISHED'
    assert FakePublishingClient.version_creates == 1 and FakePublishingClient.weight_creates == 2
    assert json.loads(path.read_text())['status'] == 'blocked_by_hardware'
    assert not json.loads(path.read_text())['hardware_verified']


def test_remote_metadata_drift_is_detected_after_model_asset_rediscovery(tmp_path):
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_complete_weight_version(tmp_path)
    service = _service(tmp_path, memory)
    first = service.publish(project_id='p1', algorithm_id='a1', version_id='v1')
    asset = service.model_assets.repository.get(first['artifacts'][0]['artifact_id'])
    service.model_assets.repository.upsert({**asset, 'metadata': {'chip_code': ''}})
    FakePublishingClient.weights[0]['tags'] = ['wrong-project-label']
    result = service.reconcile_published_remote(project_id='p1', algorithm_id='a1', version_id='v1',
        client=FakePublishingClient(), remote_versions=FakePublishingClient.versions)
    assert result['drifted'] == 1
    assert FakePublishingClient.weight_edits == 0


def test_weight_status_api_projects_missing_facts_without_remote_writes(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import platform_core.external_algorithm_publish as publish_module
    FakePublishingClient.reset()
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    rows = list_algorithms(_algorithms_file(tmp_path, 'p1'))
    rows[0]['versions'][0].pop('training_lineage')
    save_algorithms(_algorithms_file(tmp_path, 'p1'), rows)
    service = _service(tmp_path, memory)
    api = FastAPI()
    # This test owns its one isolated service; disable only router background
    # startup while wiring the real route, before starting TestClient's threads.
    with monkeypatch.context() as patch:
        patch.setattr(publish_module, 'ExternalAlgorithmPublishService', lambda **_: service)
        patch.setattr(publish_module.threading.Thread, 'start', lambda _self: None)
        router = publish_module.external_algorithm_publish_router(data_dir=tmp_path,
            get_project=lambda pid: {'id': pid}, project_dir=lambda pid: _project_dir(tmp_path, pid),
            algorithms_file=lambda pid: _algorithms_file(tmp_path, pid), external_secret_store_factory=lambda: memory,
            storage_sources_factory=service.storage_sources_factory, storage_credentials_factory=service.storage_credentials_factory)
    api.include_router(router)
    with TestClient(api) as client:
        response = client.get('/api/v64/external-publish/projects/p1/algorithms/a1/versions/v1')
    assert response.status_code == 200
    status = response.json()
    assert status['publish_ready']
    assert 'yoloVersion' in status['artifacts'][0]['metadata_note']
    assert FakePublishingClient.weight_creates == FakePublishingClient.weight_edits == 0


def test_weight_extended_metadata_uses_actual_training_and_conversion_input(tmp_path):
    model = _seed_external_algorithm(tmp_path)
    algorithm = list_algorithms(_algorithms_file(tmp_path, "p1"))[0]
    version = algorithm["versions"][0]
    version["training_lineage"] = {
        "base": {"model": "yolo11n.pt"},
        "parameters": {"actual": {"imgsz": 800}},
    }
    version["label_schema"] = [
        {"class_id": 0, "code": "smoke"},
        {"class_id": 1, "code": "fire"},
    ]
    version["label_codes"] = ["smoke", "fire"]
    version["tags"] = ["unrelated-ui-tag"]
    output = _seed_conversion(tmp_path, target="rockchip", job_id="convert-size-640")
    job_path = _project_dir(tmp_path, "p1") / "deployment/jobs/convert-size-640/job.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job["params"]["input_size"] = 640
    job_path.write_text(json.dumps(job), encoding="utf-8")
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    service = _service(tmp_path, memory)
    discovered = service.discover_artifacts("p1", algorithm, version)
    original = next(row for row in discovered if row["target"] == "original")
    converted = next(row for row in discovered if row["target"] == "rockchip")
    assert original["weight_metadata"] == {
        "image_width": 800, "image_height": 800,
        "yolo_version": "YOLOv11n", "tags": ["smoke", "fire"],
    }
    assert converted["weight_metadata"] == {
        "image_width": 640, "image_height": 640,
        "yolo_version": "YOLOv11n", "tags": ["smoke", "fire"],
    }
    for artifact in (original, converted):
        payload = service._weight_artifact_payload({
            **artifact, "compute_platform_id": "91",
            "remote_chip_code": artifact["chip_code"] if artifact["target"] == "rockchip" else "",
            "public_url": f"https://models.example/{artifact['file_name']}",
            "metadata": artifact["weight_metadata"],
        })
        assert payload["fileSize"] == artifact["size_bytes"]
        assert payload["fileSha256"] == artifact["sha256"]
        assert payload["yoloVersion"] == "YOLOv11n"
        assert payload["tags"] == ["smoke", "fire"]
    assert original["source_path"] == str(model.resolve())
    assert converted["source_path"] == str(output.resolve())


def test_weight_extended_metadata_never_invents_unknown_values():
    metadata = ExternalAlgorithmPublishService._weight_model_metadata({"id": "legacy"})
    assert metadata == {}
    payload = ExternalAlgorithmPublishService._weight_artifact_payload({
            "target": "original", "compute_platform_id": "91", "file_name": "best.pt",
            "public_url": "https://models.example/best.pt",
            "sha256": "f" * 64, "size_bytes": 32, "metadata": {},
        })
    assert payload['fileSize'] == 32 and payload['fileSha256'] == 'f' * 64
    assert not set(payload).intersection({'imageWidth','imageHeight','yoloVersion','tags'})
    assert "tags" not in ExternalAlgorithmPublishService._weight_model_metadata({"tags": []})
    assert "yolo_version" not in ExternalAlgorithmPublishService._weight_model_metadata({
        "yolo_version": "v11",
    })


def test_weight_tags_use_frozen_training_classes_and_not_project_metadata():
    version = {
        "label_schema": [
            {"class_id": 1, "code": "fire"},
            {"class_id": 0, "code": "smoke"},
        ],
        "label_codes": ["smoke", "fire"],
        "tags": ["generic", "wrong-user-tag"],
        "training_lineage": {"base": {"model": "/models/yolo11n.pt"}},
    }
    values = ExternalAlgorithmPublishService._weight_model_metadata(version)
    assert values["tags"] == ["smoke", "fire"]
    assert values["yolo_version"] == "YOLOv11n"
    assert ExternalAlgorithmPublishService._frozen_weight_labels({
        **version, "label_codes": ["smoke", "helmet"],
    }) is None
    assert "tags" not in ExternalAlgorithmPublishService._weight_model_metadata({
        "tags": ["not-model-label"],
    })


def test_weight_yolo_architecture_follows_version_lineage_for_best_pt_iterations():
    initial = {
        "id": "v1", "training_lineage": {"base": {"model": "yolo11s.pt"}},
    }
    second = {
        "id": "v2", "base_version_id": "v1",
        "training_lineage": {"base": {"model": "best.pt", "version_id": "v1"}},
    }
    third = {
        "id": "v3", "base_version_id": "v2",
        "training_lineage": {"base": {"model": "best.pt", "version_id": "v2"}},
    }
    algorithm = {"versions": [initial, second, third]}
    assert ExternalAlgorithmPublishService._yolo_architecture(third, algorithm) == "YOLOv11s"
    assert ExternalAlgorithmPublishService._yolo_architecture(second, algorithm) == "YOLOv11s"
    assert ExternalAlgorithmPublishService._yolo_architecture(third) == ""
    assert ExternalAlgorithmPublishService._yolo_architecture({
        "id": "v1", "base_version_id": "v1",
        "training_lineage": {"base": {"model": "best.pt"}},
    }, algorithm) == ""
    assert ExternalAlgorithmPublishService._yolo_architecture({
        "training_lineage": {"base": {"model": "yolov8m.pt"}},
    }) == "YOLOv8m"


def test_weight_labels_recover_only_hash_verified_training_snapshot(tmp_path: Path):
    _seed_external_algorithm(tmp_path)
    algorithm, version = _version(tmp_path)
    version.pop('label_schema', None)
    version.pop('label_codes', None)
    signed = {
        "label_schema": [{"class_id": 0, "code": "smoke"}, {"class_id": 1, "code": "fire"}],
        "dataset_revision_id": "b" * 64,
    }
    digest = hashlib.sha256(
        json.dumps(signed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    version["snapshot_id"] = digest
    version["dataset_revision_id"] = "b" * 64
    version["training_lineage"] = {"task_id": "task-verified", "snapshot_id": digest}
    path = tmp_path / "task_runtime" / "artifacts" / "task-verified" / "snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"snapshot_id": digest, "created_at": "2026-10-19", **signed}), encoding="utf-8")
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    service = _service(tmp_path, memory)
    assert service.discover_artifacts("p1", algorithm, version)[0]["weight_metadata"]["tags"] == ["smoke", "fire"]
    path.write_text(json.dumps({"snapshot_id": digest, "label_schema": [{"class_id": 0, "code": "dog"}], "dataset_revision_id": "b" * 64}), encoding="utf-8")
    assert "tags" not in service.discover_artifacts("p1", algorithm, version)[0]["weight_metadata"]
    version["snapshot_id"] = "f" * 64
    assert "tags" not in service.discover_artifacts("p1", algorithm, version)[0]["weight_metadata"]


def test_weight_schema_rejects_invalid_class_id_mappings():
    frozen = ExternalAlgorithmPublishService._frozen_weight_labels
    assert frozen({"label_schema": [{"class_id": 0, "code": "smoke"}, {"class_id": 0, "code": "fire"}]}) is None
    assert frozen({"label_schema": [{"class_id": 0, "code": "smoke"}, {"class_id": 2, "code": "fire"}]}) is None
    assert frozen({"label_schema": [{"class_id": 1, "code": "fire"}, {"class_id": 0, "code": "smoke"}]}) == ["smoke", "fire"]
    assert frozen({'label_schema': [{'class_id': 0, 'code': 'smoke'}, {'class_id': 1, 'code': 'fire'}],
                   'label_codes': ['fire', 'smoke']}) is None


@pytest.mark.parametrize('target', ['original', 'rockchip'])
def test_upload_refuses_modified_source_with_unchanged_file_size(tmp_path: Path, target):
    model = _seed_external_algorithm(tmp_path)
    algorithm, version = _version(tmp_path)
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    service = _service(tmp_path, memory)
    if target == 'rockchip':
        model = _seed_conversion(tmp_path)
    artifact = next(row for row in service.discover_artifacts("p1", algorithm, version) if row['target'] == target)
    content = model.read_bytes()
    model.write_bytes(content[:-1] + bytes([content[-1] ^ 1]))
    assert model.stat().st_size == artifact["size_bytes"]
    with pytest.raises(PlatformError) as captured:
        service._upload_artifact(artifact, algorithm, version)
    assert captured.value.code == "MODEL_ARTIFACT_SOURCE_IDENTITY_CHANGED"


def _hierarchical_compute_cache(root: Path):
    external = ExternalPlatformRepository(root)
    cached = external.cache()
    cached["compute_platforms"] = [
        {"computePlatformId": "cp-rk", "computePlatformName": "瑞芯微", "parentId": 0, "delFlag": 0},
        {"computePlatformId": "rk-edge", "computePlatformName": "边缘通用环境", "parentId": "cp-rk", "delFlag": 0},
        {"computePlatformId": "rk-3568", "computePlatformName": "客户自定义 RK 边缘分类", "parentId": "cp-rk", "delFlag": 0},
        {"computePlatformId": "rk-3576", "computePlatformName": "ARM 芯片档位", "parentId": "cp-rk", "delFlag": 0},
        {"computePlatformId": "cp-onnx", "computePlatformName": "ONNX 通用", "parentId": 0, "delFlag": 0},
    ]
    external.save_cache(cached)


def test_child_compute_platform_mapping_uses_actual_rknn_chip_not_remote_name(tmp_path: Path):
    _seed_external_algorithm(tmp_path)
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _hierarchical_compute_cache(tmp_path)
    service = _service(tmp_path, memory)
    service.save_config(ExternalPublishConfigPayload(target_mappings={
        "original": TargetMapping(compute_platform_id="cp-onnx"),
        "rockchip": TargetMapping(
            compute_platform_id="cp-rk",
            chip_mappings={"rk-3568": "rk-edge", "RK3576": "rk-3576"},
        ),
    }))
    by_chip = lambda chip: service._artifact_mapping_state({"target": "rockchip", "chip_code": chip})
    first = by_chip("rk3568")
    assert first["status"] == "mapped"
    assert first["mapping"]["compute_platform_id"] == "rk-edge"
    assert by_chip("RK3576")["mapping"]["compute_platform_id"] == "rk-3576"
    assert by_chip("rk3578")["code"] == "EXTERNAL_COMPUTE_CHIP_MAPPING_REQUIRED"
    assert by_chip("")["code"] == "MODEL_ARTIFACT_CHIP_REQUIRED"
    assert service._artifact_mapping_state({"target": "original"})["mapping"]["compute_platform_id"] == "cp-onnx"


def test_hierarchical_root_without_chip_binding_never_publishes_as_chip(tmp_path: Path):
    _seed_external_algorithm(tmp_path)
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _hierarchical_compute_cache(tmp_path)
    service = _service(tmp_path, memory)
    blocked = service._artifact_mapping_state({"target": "rockchip", "chip_code": "rk3568"})
    assert blocked["status"] == "blocked"
    assert blocked["code"] == "EXTERNAL_COMPUTE_CHIP_MAPPING_REQUIRED"


def test_mapping_config_rejects_wrong_parent_deleted_child_and_duplicate_chip_keys(tmp_path: Path):
    _seed_external_algorithm(tmp_path)
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _hierarchical_compute_cache(tmp_path)
    service = _service(tmp_path, memory)
    for mappings in (
        {"RK3568": "cp-onnx"},
        {"RK3568": "rk-edge", "rk-3568": "rk-3568"},
    ):
        with pytest.raises(PlatformError):
            service.save_config(ExternalPublishConfigPayload(target_mappings={
                "rockchip": TargetMapping(compute_platform_id="cp-rk", chip_mappings=mappings),
            }))
    external = ExternalPlatformRepository(tmp_path)
    cached = external.cache()
    next(row for row in cached["compute_platforms"] if row["computePlatformId"] == "rk-edge")["delFlag"] = 1
    external.save_cache(cached)
    with pytest.raises(PlatformError) as captured:
        service.save_config(ExternalPublishConfigPayload(target_mappings={
            "rockchip": TargetMapping(compute_platform_id="cp-rk", chip_mappings={"RK3568": "rk-edge"}),
        }))
    assert captured.value.code == "EXTERNAL_COMPUTE_CHILD_MAPPING_INVALID"


def test_existing_remote_weight_id_cannot_silently_move_to_new_chip_node(tmp_path: Path):
    repo = ExternalPublicationRepository(tmp_path)
    publication = {"publication_key": "pub-mapping", "project_id": "p1", "algorithm_id": "a1", "version_id": "v1"}
    artifact = {
        "artifact_id": "artifact-chip", "project_id": "p1", "algorithm_id": "a1",
        "version_id": "v1", "target": "rockchip", "chip_code": "rk3568",
    }
    # The real repository owner retains the current external weight mapping.
    with sqlite3.connect(repo.db_path) as db:
        db.execute(
            "INSERT INTO external_version_publications (publication_key, project_id, algorithm_id, version_id, external_product_id, version_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (publication["publication_key"], "p1", "a1", "v1", "product-1", "v1", "2026-10-19T00:00:00Z", "2026-10-19T00:00:00Z"),
        )
        db.execute(
            "INSERT INTO external_artifact_publications (mapping_id, provider, artifact_id, publication_key, compute_platform_id, remote_chip_code, sync_status, external_weight_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("owned-chip", PROVIDER_CHANGLIAN, artifact["artifact_id"],
             publication["publication_key"], "rk-edge", "RK3568", "SYNCED", "weight-701",
             "2026-10-19T00:00:00Z", "2026-10-19T00:00:00Z"),
        )
    with pytest.raises(PlatformError) as captured:
        repo.ensure_artifact_publication(publication["publication_key"], artifact, {
            "compute_platform_id": "rk-3576", "chip_mappings": {"RK3568": "rk-3576"},
        })
    assert captured.value.code == "EXTERNAL_WEIGHT_PLATFORM_REMAP_REVIEW_REQUIRED"
    assert repo.artifact_publication("artifact-chip")["compute_platform_id"] == "rk-edge"


def test_direct_child_selected_without_explicit_chip_binding_is_not_chip_identity(tmp_path: Path):
    _seed_external_algorithm(tmp_path)
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _hierarchical_compute_cache(tmp_path)
    service = _service(tmp_path, memory)
    # An old direct-category selection cannot be treated as RK3576 just
    # because the class has a name resembling a hardware model.
    service.save_config(ExternalPublishConfigPayload(target_mappings={
        "rockchip": TargetMapping(compute_platform_id="rk-3568", chip_code="RK3568"),
    }))
    result = service._artifact_mapping_state({"target": "rockchip", "chip_code": "RK3576"})
    assert result["status"] == "blocked"
    assert result["code"] == "EXTERNAL_COMPUTE_CHIP_MAPPING_REQUIRED"


# Exercise the real requests JSON encoder; only the network transport is fake.
def _tags_wire_service(root, memory):
    import requests
    from urllib.parse import urlsplit
    from platform_core.external_algorithm_publish import PublishingChangLianClient

    backend_type = type("TagsWireBackend", (FakePublishingClient,), {})
    backend_type.reset()
    backend = backend_type()
    writes = []

    class IsolatedAdapter(requests.adapters.BaseAdapter):
        def send(self, request, **kwargs):
            assert urlsplit(request.url).hostname == "changlian.example"
            path = urlsplit(request.url).path
            body = json.loads(request.body) if request.body else None
            if path.endswith("/internal/auth/test-sign"):
                result = {"code": 200, "data": {"timestamp": "100", "nonce": "abc", "signature": "sig"}}
            elif path.endswith("/internal/auth/token"):
                result = {"code": 200, "data": {"accessToken": "isolated-token", "expiresIn": 3600}}
            else:
                assert request.headers["Authorization"] == "Bearer isolated-token"
                if request.method == "POST":
                    assert request.headers["Content-Type"] == "application/json"
                    writes.append((path, body))
                if "/algorithm-version/listByProduct/" in path:
                    result = backend.list_product_versions(path.rsplit("/", 1)[1])
                elif "/algorithm-version/listByAnalysis/" in path:
                    result = backend.list_analysis_versions(path.rsplit("/", 1)[1])
                elif path.endswith("/algorithm-version/add"):
                    result = backend.create_algorithm_version(body)
                elif "/algorithm-weight/listByVersion/" in path:
                    version_id = path.rsplit("/", 1)[1]
                    result = {"code": 200, "data": [row for row in backend.weights if row["algoVersionId"] == version_id]}
                elif path.endswith("/algorithm-weight/add"):
                    result = backend.create_weight(body)
                elif path.endswith("/algorithm-weight/edit"):
                    result = backend.edit_weight(body)
                else:
                    raise AssertionError(path)
            response = requests.Response()
            response.status_code = 200
            response._content = json.dumps(result).encode("utf-8")
            response.request = request
            return response

        def close(self):
            pass

    session = requests.Session()
    session.trust_env = False
    adapter = IsolatedAdapter()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    service = _service(root, memory, client_factory=lambda **kwargs: PublishingChangLianClient(session=session, **kwargs))
    config = service.repository.config()
    config["target_mappings"]["onnx"] = {"compute_platform_id": "cp-onnx", "chip_code": ""}
    service.save_config(ExternalPublishConfigPayload(**config))
    return service, backend_type, writes


def _tags_frozen_version(root, codes, *, version_id="v1", previous_id=None):
    from platform_core.algorithms import attach_version_if_current
    from platform_core.snapshots import build_snapshot

    path = _algorithms_file(root, "p1")
    rows = list_algorithms(path)
    template = dict(rows[0]["versions"][0])
    model = _project_dir(root, "p1") / "algorithm_versions" / "a1" / version_id / "best.pt"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(("trained-" + version_id).encode())
    version = {**template, "id": version_id, "task_id": "train-" + version_id,
               "stored_path": str(model), "model_name": "best.pt", "base_version_id": previous_id,
               "version_name": "model-" + version_id, "version_no": "model-" + version_id}
    version.pop("label_schema", None)
    version.pop("label_codes", None)
    if codes is not None:
        # Same canonical Snapshot/schema and conditional version writer used by training.
        snapshot = build_snapshot([], [], [], list(reversed([
            {"class_id": index, "code": code} for index, code in enumerate(codes)
        ])), seed=19)
        version.update(label_schema=snapshot["label_schema"],
                       label_codes=[row["code"] for row in snapshot["label_schema"]],
                       snapshot_id=snapshot["snapshot_id"])
    if previous_id is None:
        rows[0]["versions"] = []
        rows[0]["current_version_id"] = ""
        save_algorithms(path, rows)
    attach_version_if_current(path, "a1", version, expected_current_version_id=previous_id)
    return version


@pytest.mark.parametrize("codes", [["smoke"], ["smoke", "fire"], ["helmet", "fire", "smoke", "vest"], None])
def test_tags_wire_training_and_completed_onnx_rknn_keep_frozen_classes(tmp_path, codes, monkeypatch):
    from types import SimpleNamespace
    from platform_core.deployment.conversion_tasks import _finalize_conversion_job
    from platform_core.task_runtime import TaskStatus
    from platform_core import external_publish_request as request_module

    emitted = []
    signal = request_module._EXTERNAL_PUBLISH_WAKE_EVENT.set
    def record_signal():
        emitted.append(True)
        signal()
    monkeypatch.setattr(request_module._EXTERNAL_PUBLISH_WAKE_EVENT, "set", record_signal)

    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    _tags_frozen_version(tmp_path, codes)
    (tmp_path / "projects.json").write_text(json.dumps([{"id": "p1", "labels": [{"code": "current-only"}]}]))
    service, backend, writes = _tags_wire_service(tmp_path, memory)
    assert request_external_auto_publish_if_enabled(data_dir=tmp_path, algorithms_path=_algorithms_file(tmp_path, "p1"),
                                                   algorithm_id="a1", version_id="v1", now="2026-10-20T04:00:00Z")
    assert len(emitted) == 1
    assert service.run_auto_publish_once()["published"] == 1
    for index, (target, chip) in enumerate([("onnx", ""), ("rockchip", "rk3568"), ("rockchip", "rk3576")]):
        job_id = f"wire-convert-{index}"
        output = _seed_conversion(tmp_path, target=target, chip=chip, job_id=job_id,
                                  content=(target + chip).encode())
        job_file = output.parents[1] / "job.json"
        job = json.loads(job_file.read_text())
        context = SimpleNamespace(task=SimpleNamespace(task_id=job_id, project_id="p1"),
                                  artifacts=SimpleNamespace(atomic_write_json=lambda *args: None),
                                  assert_current_execution=lambda: None, heartbeat=lambda **kwargs: None)
        status, _ = _finalize_conversion_job(context, job_file, job, recovered_from_completed_work=False, data_dir=tmp_path)
        assert status is (TaskStatus.SUCCEEDED if target == "onnx" else TaskStatus.BLOCKED_BY_HARDWARE)
        assert len(emitted) == index + 2
        assert _version(tmp_path)[1]["external_publish_requested_at"]
        assert service.run_auto_publish_once()["published"] == 1
    weights = [body for path, body in writes if path.endswith("/algorithm-weight/add")]
    assert len(weights) == 4 and backend.version_creates == 1
    assert {row["fileName"] for row in weights} == {"best.pt", "model.onnx", "model.rknn"}
    assert len({row["algoVersionId"] for row in weights}) == 1
    assert {row["chipCode"] for row in weights if row["fileName"] == "model.rknn"} == {"RK3568", "RK3576"}
    for row in weights:
        if codes is None:
            assert "tags" not in row
        else:
            assert type(row["tags"]) is list and row["tags"] == codes
            assert all(type(code) is str for code in row["tags"])
        assert row["fileSize"] > 0 and len(row["fileSha256"]) == 64
        assert row["imageWidth"] == row["imageHeight"] == (800 if row["fileName"] == "best.pt" else 640)
    assert service.repository.publication("p1", "a1", "v1")["status"] == "PUBLISHED"
    before = len(writes)
    service.run_auto_publish_once()
    service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    assert len(writes) == before and backend.weight_edits == 0


def test_tags_wire_old_weight_backfills_same_id_and_unknown_never_clears(tmp_path, monkeypatch):
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    _tags_frozen_version(tmp_path, None)
    service, backend, writes = _tags_wire_service(tmp_path, memory)
    first = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    artifact_id = first["artifacts"][0]["artifact_id"]
    weight_id = backend.weights[0]["weightId"]
    uploaded_at = first["artifacts"][0]["uploaded_at"]
    assert "tags" not in backend.weights[0]
    service.repository.patch_artifact_publication(artifact_id, synced_payload_json="{}")
    def unexpected_upload(*args, **kwargs):
        raise AssertionError("metadata edit must reuse the uploaded file")
    monkeypatch.setattr(service.model_assets, "ensure_uploaded", unexpected_upload)
    rows = list_algorithms(_algorithms_file(tmp_path, "p1"))
    version = rows[0]["versions"][0]
    version.update(label_schema=[{"class_id": 1, "code": "fire"}, {"class_id": 0, "code": "smoke"}],
                   label_codes=["smoke", "fire"])
    save_algorithms(_algorithms_file(tmp_path, "p1"), rows)
    assert service.publication_requires_sync("p1", rows[0], version, first["publication"])
    second = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    edits = [body for path, body in writes if path.endswith("/algorithm-weight/edit")]
    assert len(edits) == 1 and edits[0]["tags"] == ["smoke", "fire"]
    assert edits[0]["weightId"] == weight_id and edits[0]["algoVersionId"] == backend.versions[0]["algoVersionId"]
    assert second["artifacts"][0]["uploaded_at"] == uploaded_at
    assert second["artifacts"][0]["artifact_id"] == artifact_id
    service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    assert backend.weight_creates == backend.version_creates == backend.weight_edits == 1
    version.pop("label_schema")
    version.pop("label_codes")
    version["training_lineage"]["parameters"]["actual"]["imgsz"] = 960
    save_algorithms(_algorithms_file(tmp_path, "p1"), rows)
    final = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    edits = [body for path, body in writes if path.endswith("/algorithm-weight/edit")]
    assert len(edits) == 2 and "tags" not in edits[-1]
    assert backend.weights[0]["tags"] == ["smoke", "fire"]
    assert final["artifacts"][0]["sync_status"] == "SYNCED"


def test_tags_wire_model_iterations_keep_each_versions_own_classes(tmp_path):
    memory = MemorySecretStore()
    _configure_external(tmp_path, memory)
    _seed_external_algorithm(tmp_path)
    _tags_frozen_version(tmp_path, ["smoke", "fire"])
    service, backend, writes = _tags_wire_service(tmp_path, memory)
    service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    _tags_frozen_version(tmp_path, ["fire", "helmet", "smoke"], version_id="v2", previous_id="v1")
    service.publish(project_id="p1", algorithm_id="a1", version_id="v2")
    weights = [body for path, body in writes if path.endswith("/algorithm-weight/add")]
    assert [row["tags"] for row in weights] == [["smoke", "fire"], ["fire", "helmet", "smoke"]]
    assert len({row["algoVersionId"] for row in weights}) == 2
    service.publish(project_id="p1", algorithm_id="a1", version_id="v1")
    assert backend.version_creates == backend.weight_creates == 2 and backend.weight_edits == 0


@pytest.mark.parametrize("chip", ["", "RK3568", "bm1690"])
def test_sophon_weight_cannot_use_missing_or_other_vendor_chip(chip):
    with pytest.raises(PlatformError):
        ExternalAlgorithmPublishService._weight_artifact_payload({"target":"sophon","remote_chip_code":chip,
            "compute_platform_id":"cp-sophon","file_name":"model.bmodel","public_url":"https://models.example/model.bmodel"})


def test_sophon_bmodels_share_version_and_frozen_tags_but_keep_each_chip_identity(tmp_path):
    memory=MemorySecretStore();_configure_external(tmp_path,memory);_seed_external_algorithm(tmp_path)
    _tags_frozen_version(tmp_path,["smoke","fire"])
    service,backend,writes=_tags_wire_service(tmp_path,memory)
    # Keep this local test provider below Windows path limits; OSS keys are unchanged.
    sources=service.storage_sources_factory()
    local=sources.get("default_local")
    sources.update("default_local", {"config":{**local.config,"root":str(tmp_path/"s")}})
    service.model_assets.save_config(ModelArtifactConfigPayload(storage_source_id="default_local", root_prefix="a", auto_upload_enabled=True))
    cache=service.external_repository.cache()
    cache["compute_platforms"] += [{"computePlatformId":"cp-sophon","computePlatformName":"算能"},
        {"computePlatformId":"cp-bm1684x","computePlatformName":"BM1684X","parentId":"cp-sophon"},
        {"computePlatformId":"cp-bm1688","computePlatformName":"BM1688","parentId":"cp-sophon"}]
    service.external_repository.save_cache(cache)
    config=service.repository.config();config["target_mappings"]["sophon"]={"compute_platform_id":"cp-sophon",
        "chip_mappings":{"BM1684X":"cp-bm1684x","BM1688":"cp-bm1688"},"enabled":True}
    service.save_config(ExternalPublishConfigPayload(**config))
    for chip in ("bm1684x","bm1688"):
        _seed_conversion(tmp_path,target="sophon",chip=chip,job_id="convert-"+chip,content=b"isolated-same-bmodel-bytes")
    result=service.publish(project_id="p1",algorithm_id="a1",version_id="v1")
    assert result["publication"]["status"] == "PUBLISHED", result
    weights=[body for path,body in writes if path.endswith("/algorithm-weight/add")]
    assert len(weights)==3 and backend.version_creates==1
    bmodels=[row for row in weights if row["fileName"].endswith(".bmodel")]
    assert {row["chipCode"] for row in bmodels} == {"BM1684X","BM1688"}
    assert {row["computePlatformId"] for row in bmodels} == {"cp-bm1684x","cp-bm1688"}
    for row in bmodels:
        assert row["tags"] == ["smoke","fire"] and type(row["tags"]) is list
        assert row["fileSize"] == len(b"isolated-same-bmodel-bytes")
        assert row["fileSha256"] == hashlib.sha256(b"isolated-same-bmodel-bytes").hexdigest()
        assert row["imageWidth"] == row["imageHeight"] == 640
    assert len({row["algoVersionId"] for row in weights})==1
    service.publish(project_id="p1",algorithm_id="a1",version_id="v1")
    assert backend.weight_creates == 3 and backend.weight_edits == 0
    # An old BMODEL receipt must use the same Weight ID for tags backfill.
    existing=next(row for row in result["artifacts"] if row.get("remote_chip_code")=="BM1688")
    old_id=existing["external_weight_id"]
    service.repository.patch_artifact_publication(existing["artifact_id"],synced_payload_json="{}")
    next(row for row in backend.weights if row["weightId"]==old_id).pop("tags")
    service.publish(project_id="p1",algorithm_id="a1",version_id="v1")
    edits=[body for path,body in writes if path.endswith("/algorithm-weight/edit")]
    assert len(edits)==1 and edits[0]["weightId"]==old_id and edits[0]["tags"]==["smoke","fire"]
    service.publish(project_id="p1",algorithm_id="a1",version_id="v1")
    assert backend.weight_creates==3 and backend.weight_edits==1 and backend.version_creates==1


HISTORICAL_TAGS_CASES = [
    ("ext_chang_lian_43b94d739f1bf25b","f4dfedadcce7","2110796556046307328","original",["fire"],True),
    ("ext_chang_lian_43b94d739f1bf25b","f4dfedadcce7","2110966591775707136","rockchip",["fire"],True),
    ("ext_chang_lian_72d63086777561b7","4ef40723d87e","2108753027757379584","original",["fire1","smoke1"],True),
    ("ext_chang_lian_72d63086777561b7","4ef40723d87e","2108823477988495360","rockchip",["fire1","smoke1"],True),
    ("ext_chang_lian_92e659f3e8a7f3bd","3ea046f276b0","2109230402605551616","original",["person"],True),
    ("ext_chang_lian_92e659f3e8a7f3bd","3ea046f276b0","2109232532909330432","rockchip",["person"],True),
    ("ext_chang_lian_aa52b57d1ecbe054","a0e1f035909b","2110401842730110976","original",["tcckongdi","tcccar"],True),
] + [("control-a"+str(i),"control-v"+str(i),"isolated-control-"+str(i),"original",
      [["fire"],["Employee_is_Sleeping"],["No_helmet","helmet"],["Car"]][i%4],False) for i in range(10)]


@pytest.mark.parametrize("aid,vid,wid,target,codes,missing",HISTORICAL_TAGS_CASES,ids=["historical-"+str(i) for i in range(17)])
def test_historical_17_weights_restore_local_tags_and_edit_only_seven_same_ids(tmp_path,monkeypatch,aid,vid,wid,target,codes,missing):
    memory=MemorySecretStore();_configure_external(tmp_path,memory);_seed_external_algorithm(tmp_path,version_id=vid)
    (tmp_path / "projects.json").write_text(json.dumps([{"id":"p1"}]), encoding="utf-8")
    rows=list_algorithms(_algorithms_file(tmp_path,"p1"));rows[0]["id"]=aid
    version=rows[0]["versions"][0];version.update(label_codes=codes,
        label_schema=list(reversed([{"class_id":i,"code":c} for i,c in enumerate(codes)])))
    save_algorithms(_algorithms_file(tmp_path,"p1"),rows)
    if target=="rockchip":_seed_conversion(tmp_path,version_id=vid,algorithm_id=aid)
    service,backend,writes=_tags_wire_service(tmp_path,memory)
    sources=service.storage_sources_factory();source=sources.get("default_local")
    sources.update("default_local",{"config":{**source.config,"root":str(tmp_path/"s")}})
    service.model_assets.save_config(ModelArtifactConfigPayload(storage_source_id="default_local",root_prefix="a",auto_upload_enabled=True))
    first=service.publish(project_id="p1",algorithm_id=aid,version_id=vid)
    selected=next(a for a in first["artifacts"] if a["target"]==target)
    old_id=selected["external_weight_id"]
    remote=next(w for w in backend.weights if w["weightId"]==old_id);remote["weightId"]=wid
    receipt=json.loads(selected["synced_payload_json"])
    if missing: receipt.pop("tags",None);remote.pop("tags",None)
    service.repository.patch_artifact_publication(selected["artifact_id"],external_weight_id=wid,synced_payload_json=json.dumps(receipt))
    # Isolated historical database fixture only: reproduce the supplied empty metadata.
    with sqlite3.connect(service.model_assets.repository.db_path) as db:
        db.execute("UPDATE model_artifacts SET metadata_json='{}'")
    service.repository.patch_publication(first["publication"]["publication_key"],status="PARTIAL" if missing and vid!="a0e1f035909b" else "PUBLISHED", updated_at="2000-01-01T00:00:00Z")
    identity={k:selected[k] for k in ("artifact_id","sha256","object_key","public_url","compute_platform_id","remote_chip_code","uploaded_at")}
    before=len(writes);before_versions=backend.version_creates;before_weights=backend.weight_creates
    monkeypatch.setattr(service.model_assets,"ensure_uploaded",lambda *a,**kw:pytest.fail("metadata repair must not upload"))
    from scripts.audit_weight_metadata import audit
    report=audit(tmp_path,"p1")
    audited=next(r for r in report['artifacts'] if r['artifact_id']==selected['artifact_id'])
    assert audited['local_state']=='LOCAL_REPAIR_REQUIRED' and audited['frozen_tags']==codes
    assert audited['external_action']==('EDIT_CANDIDATE_REQUIRES_REMOTE_IDENTITY' if missing else 'NO_AUTOMATIC_WRITE')
    local=service.model_assets.register_version_metadata("p1",aid,vid)
    assert all(a["metadata"]["tags"]==codes for a in local)
    # Exercise the existing Owner, including PUBLISHED and PARTIAL versions.
    summary=service.run_auto_publish_once()
    assert summary["checked"]==1 and summary["failed"]==0, summary
    after=service._artifact_projection(selected["artifact_id"])
    assert {k:after[k] for k in identity}==identity
    assert after["external_weight_id"]==wid and after["metadata"]["tags"]==codes
    edits=[body for path,body in writes[before:] if path.endswith("/algorithm-weight/edit")]
    assert len(edits)==int(missing)
    if edits:
        assert str(edits[0]["weightId"])==wid and edits[0]["tags"]==codes
        assert edits[0]["filePath"]==identity["public_url"]
    assert backend.version_creates==before_versions and backend.weight_creates==before_weights
    count=len(writes);service.run_auto_publish_once()
    assert len(writes)==count


def test_synced_tags_backfill_requires_unique_remote_identity_before_edit(tmp_path):
    FakePublishingClient.reset();memory=MemorySecretStore();_configure_external(tmp_path,memory);_seed_complete_weight_version(tmp_path)
    service=_service(tmp_path,memory);first=service.publish(project_id="p1",algorithm_id="a1",version_id="v1")
    artifact=first["artifacts"][0]
    receipt=json.loads(artifact["synced_payload_json"]);receipt.pop("tags")
    service.repository.patch_artifact_publication(artifact["artifact_id"],synced_payload_json=json.dumps(receipt))
    FakePublishingClient.weights[0].pop("tags")
    FakePublishingClient.weights.append({**FakePublishingClient.weights[0],"weightId":"ambiguous-id"})
    with pytest.raises(PlatformError,match="唯一|确认"):
        service.publish(project_id="p1",algorithm_id="a1",version_id="v1")
    assert FakePublishingClient.weight_edits==0 and FakePublishingClient.weight_creates==1


def test_ensure_publication_does_not_reset_partial_retry_clock(tmp_path):
    repo=ExternalPublicationRepository(tmp_path)
    algorithm={"id":"a1","external_product_id":"product-1"};version={"id":"v1","version_name":"v1"}
    publication=repo.ensure_publication(project_id="p1",algorithm=algorithm,version=version)
    repo.patch_publication(publication["publication_key"],status="PARTIAL",updated_at="2000-01-01T00:00:00Z")
    refreshed=repo.ensure_publication(project_id="p1",algorithm=algorithm,version=version)
    assert refreshed["updated_at"]=="2000-01-01T00:00:00Z"
    assert repo.auto_retry_due(refreshed) is True


def test_label_conflict_preserves_local_tags_without_repeated_external_edit(tmp_path):
    FakePublishingClient.reset();memory=MemorySecretStore();_configure_external(tmp_path,memory);_seed_complete_weight_version(tmp_path)
    service=_service(tmp_path,memory);first=service.publish(project_id='p1',algorithm_id='a1',version_id='v1')
    rows=list_algorithms(_algorithms_file(tmp_path,'p1'));version=rows[0]['versions'][0]
    version.update(label_codes=['wrong-project'],label_schema=[{'class_id':0,'code':'wrong-project'}])
    save_algorithms(_algorithms_file(tmp_path,'p1'),rows)
    service.model_assets.register_version_metadata('p1','a1','v1')
    stored=service.model_assets.repository.get(first['artifacts'][0]['artifact_id'])
    assert stored['metadata']['tags']==['smoke','fire'] and stored['metadata']['label_validation_status']=='CONFLICT'
    service.publish(project_id='p1',algorithm_id='a1',version_id='v1')
    assert FakePublishingClient.weight_edits==0
    assert service.publication_requires_sync('p1',rows[0],version,first['publication']) is False
    status=service.publication_status('p1','a1','v1')['artifacts'][0]
    assert status['local_tags']==['smoke','fire'] and status['prepared_tags'] is None
    assert status['metadata_sync_status']=='CONFLICT'


def test_publication_status_reads_local_metadata_without_any_external_publication(tmp_path):
    memory=MemorySecretStore();_configure_external(tmp_path,memory);_seed_complete_weight_version(tmp_path)
    service=_service(tmp_path,memory)
    local=service.model_assets.register_version_metadata('p1','a1','v1')
    assert local[0]['metadata']['tags']==['smoke','fire']
    assert service.repository.publication('p1','a1','v1') is None
    status=service.publication_status('p1','a1','v1')['artifacts'][0]
    assert status['local_tags']==['smoke','fire']
    assert status['prepared_tags']==['smoke','fire'] and status['confirmed_tags'] is None
    assert status['remote_registered'] is False and status['remote_tags_status']=='NOT_VERIFIED'


def test_tags_readback_evidence_is_distinct_from_confirmed_receipt(tmp_path):
    FakePublishingClient.reset();memory=MemorySecretStore();_configure_external(tmp_path,memory);_seed_complete_weight_version(tmp_path)
    service=_service(tmp_path,memory);service.publish(project_id='p1',algorithm_id='a1',version_id='v1')
    FakePublishingClient.weights[0].pop('tags')
    service.reconcile_published_remote(project_id='p1',algorithm_id='a1',version_id='v1',client=FakePublishingClient(),remote_versions=FakePublishingClient.versions)
    row=service.publication_status('p1','a1','v1')['artifacts'][0]
    assert row['confirmed_tags']==['smoke','fire'] and row['remote_tags'] is None
    assert row['remote_tags_status']=='NOT_RETURNED' and row['metadata_sync_status']=='SYNCED'
    FakePublishingClient.weights[0]['tags']=['wrong']
    service.reconcile_published_remote(project_id='p1',algorithm_id='a1',version_id='v1',client=FakePublishingClient(),remote_versions=FakePublishingClient.versions)
    row=service.publication_status('p1','a1','v1')['artifacts'][0]
    assert row['remote_tags']==['wrong'] and row['remote_tags_status']=='READ_BACK'
    assert row['confirmed_tags']==['smoke','fire'] and row['metadata_sync_status']=='PENDING'

def test_external_chip_bindings_read_the_local_catalog_without_changing_saved_mappings(tmp_path):
    from tests.unit.test_dynamic_conversion_catalog import catalog
    memory=MemorySecretStore()
    _configure_external(tmp_path,memory)
    service=_service(tmp_path,memory)
    original=service.repository.config()
    assert service._local_chip_dictionary()=={}
    service.model_assets.repository.save_conversion_catalog(catalog(),expected_revision=0)
    assert service._local_chip_dictionary()=={"sophon":["BM1684","BM1688"]}
    assert service.repository.config()==original
