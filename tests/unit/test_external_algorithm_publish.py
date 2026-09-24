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
    _remote_id,
    DEFAULT_PUBLISH_CONFIG,
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
        "params": {"chip": "rk3568"},
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
        "metadata": {},
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
        "metadata": {},
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
    assert "external_publish_status" not in version


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
