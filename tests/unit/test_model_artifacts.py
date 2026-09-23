import hashlib
import sqlite3
import json
from io import BytesIO
from pathlib import Path

import pytest

from platform_core.errors import PlatformError
from platform_core.algorithms import save_algorithms
from platform_core.model_artifacts import (
    ARTIFACT_OSS_SOURCE_ID,
    ArtifactOSSConfigPayload,
    ModelArtifactConfigPayload,
    ModelArtifactService,
    build_artifact_object_key,
    build_public_url,
)
from platform_core.secrets import MemorySecretStore, SecretCredentialStore
from platform_core.storage.models import ObjectMetadata, StorageHealth
from platform_core.storage.source_repository import StorageSourceRepository


def _project_dir(root: Path, project_id: str) -> Path:
    path = root / "projects" / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _algorithms_file(root: Path, project_id: str) -> Path:
    return _project_dir(root, project_id) / "algorithms.json"


def _service(root: Path):
    memory = MemorySecretStore()
    sources = StorageSourceRepository(root / "storage" / "storage_sources.sqlite3")
    credentials = SecretCredentialStore(memory)
    service = ModelArtifactService(
        data_dir=root,
        project_dir=lambda pid: _project_dir(root, pid),
        algorithms_file=lambda pid: _algorithms_file(root, pid),
        storage_sources_factory=lambda: sources,
        storage_credentials_factory=lambda: credentials,
    )
    sources.update("default_local", {
        "config": {
            "prefix": "materials-only",
            "public_base_url": "https://models.example.com",
        },
    })
    service.save_config(ModelArtifactConfigPayload(
        storage_source_id="default_local",
        root_prefix="changlian-ai/artifacts/",
        auto_upload_enabled=True,
    ))
    return service




def test_artifact_oss_config_is_standalone_from_material_storage(tmp_path: Path):
    service = _service(tmp_path)

    result = service.save_artifact_oss_config(ArtifactOSSConfigPayload(
        endpoint="https://oss-cn-hangzhou.aliyuncs.com",
        bucket="new24hlink",
        access_key_id="LTAI-artifact",
        access_key_secret="artifact-secret",
        public_base_url="https://new24hlink.oss-cn-hangzhou.aliyuncs.com",
        root_prefix="changlian-ai/artifacts",
    ))

    assert result["config"]["storage_source_id"] == ARTIFACT_OSS_SOURCE_ID
    assert result["artifact_storage"]["dedicated"] is True
    assert result["artifact_storage"]["endpoint"] == "https://oss-cn-hangzhou.aliyuncs.com"
    assert result["artifact_storage"]["bucket"] == "new24hlink"
    assert result["artifact_storage"]["credential_configured"] is True
    source = service.storage_sources_factory().get(ARTIFACT_OSS_SOURCE_ID)
    assert source is not None
    assert source.type == "oss"
    assert source.config["usage"] == "model_artifact"
    assert source.config["prefix"] == ""
    assert source.config["public_base_url"] == "https://new24hlink.oss-cn-hangzhou.aliyuncs.com"
    credentials = service.storage_credentials_factory().get(source.secret_ref)
    assert credentials == {
        "access_key_id": "LTAI-artifact",
        "access_key_secret": "artifact-secret",
    }


def test_artifact_oss_bucket_domain_is_normalized_to_service_endpoint(tmp_path: Path):
    service = _service(tmp_path)

    result = service.save_artifact_oss_config(ArtifactOSSConfigPayload(
        endpoint="new24hlink.oss-cn-hangzhou.aliyuncs.com",
        bucket="new24hlink",
        access_key_id="LTAI-artifact",
        access_key_secret="artifact-secret",
        public_base_url="https://new24hlink.oss-cn-hangzhou.aliyuncs.com",
        root_prefix="changlian-ai/artifacts",
    ))

    assert result["artifact_storage"]["endpoint"] == "https://oss-cn-hangzhou.aliyuncs.com"
    source = service.storage_sources_factory().get(ARTIFACT_OSS_SOURCE_ID)
    assert source is not None
    assert source.config["endpoint"] == "https://oss-cn-hangzhou.aliyuncs.com"


def test_artifact_oss_endpoint_without_scheme_defaults_to_https(tmp_path: Path):
    service = _service(tmp_path)

    result = service.save_artifact_oss_config(ArtifactOSSConfigPayload(
        endpoint="oss-cn-hangzhou.aliyuncs.com",
        bucket="new24hlink",
        access_key_id="LTAI-artifact",
        access_key_secret="artifact-secret",
        root_prefix="changlian-ai/artifacts",
    ))

    assert result["artifact_storage"]["endpoint"] == "https://oss-cn-hangzhou.aliyuncs.com"


def test_artifact_oss_config_blank_credentials_preserve_existing_secret(tmp_path: Path):
    service = _service(tmp_path)
    service.save_artifact_oss_config(ArtifactOSSConfigPayload(
        endpoint="https://oss-cn-hangzhou.aliyuncs.com",
        bucket="new24hlink",
        access_key_id="LTAI-artifact",
        access_key_secret="artifact-secret",
        public_base_url="https://new24hlink.oss-cn-hangzhou.aliyuncs.com",
        root_prefix="changlian-ai/artifacts",
    ))

    result = service.save_artifact_oss_config(ArtifactOSSConfigPayload(
        endpoint="https://oss-cn-hangzhou.aliyuncs.com",
        bucket="new24hlink",
        public_base_url="https://models.example.com",
        root_prefix="changlian-ai/artifacts-v2",
    ))

    source = service.storage_sources_factory().get(ARTIFACT_OSS_SOURCE_ID)
    assert source is not None
    assert service.storage_credentials_factory().get(source.secret_ref) == {
        "access_key_id": "LTAI-artifact",
        "access_key_secret": "artifact-secret",
    }
    assert result["config"]["root_prefix"] == "changlian-ai/artifacts-v2"
    assert result["artifact_storage"]["public_base_url"] == "https://models.example.com"


def test_artifact_oss_first_save_requires_own_credentials_without_legacy_oss(tmp_path: Path):
    service = _service(tmp_path)

    with pytest.raises(PlatformError) as blocked:
        service.save_artifact_oss_config(ArtifactOSSConfigPayload(
            endpoint="https://oss-cn-hangzhou.aliyuncs.com",
            bucket="new24hlink",
            root_prefix="changlian-ai/artifacts",
        ))

    assert blocked.value.code == "MODEL_ARTIFACT_OSS_CREDENTIAL_REQUIRED"
    assert service.storage_sources_factory().get(ARTIFACT_OSS_SOURCE_ID) is None


def _seed(root: Path):
    project = _project_dir(root, "p1")
    model = project / "algorithm_versions" / "local-a1" / "v1" / "best.pt"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"best-model")
    save_algorithms(_algorithms_file(root, "p1"), [{
        "id": "local-a1",
        "name": "本平台自建算法",
        "versions": [{
            "id": "v1",
            "version_name": "20260917150000",
            "training_status": "SUCCEEDED",
            "artifact_verified": True,
            "stored_path": str(model),
            "best_path": str(model),
            "model_name": "best.pt",
        }],
        "current_version_id": "v1",
    }])
    conversion = project / "deployment" / "jobs" / "convert-1"
    output = conversion / "artifacts" / "model.rknn"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"rknn-model")
    (conversion / "job.json").write_text(json.dumps({
        "id": "convert-1",
        "status": "done",
        "target": "rockchip",
        "source_id": "version::local-a1::v1",
        "source_meta": {"algorithm_id": "local-a1", "version_id": "v1"},
        "params": {"chip": "rk3568"},
        "outputs": [{"path": str(output), "available": True}],
    }), encoding="utf-8")
    (root / "projects.json").write_text(json.dumps([{"id": "p1", "name": "项目1"}]), encoding="utf-8")
    return model, output


@pytest.mark.parametrize(
    ("target", "chip_code", "expected_directory"),
    [
        ("original", "", "training"),
        ("onnx", "", "onnx"),
        ("rockchip", "rk3568", "rknn/rk3568"),
        ("rockchip", "RK3578", "rknn/rk3578"),
        ("report", "", "reports"),
    ],
)
def test_artifact_object_key_builder_uses_one_canonical_root_prefix(
    target: str,
    chip_code: str,
    expected_directory: str,
):
    key = build_artifact_object_key(
        root_prefix="changlian-ai/artifacts/",
        project_id="project-1",
        algorithm_id="algorithm-1",
        version_id="version-1",
        target=target,
        chip_code=chip_code,
        sha256="a" * 64,
        file_name="model.rknn" if target == "rockchip" else "best.pt",
    )

    assert key.startswith(
        "changlian-ai/artifacts/projects/project-1/algorithms/algorithm-1/versions/version-1/"
    )
    assert f"/{expected_directory}/" in f"/{key}/"
    assert key.count("changlian-ai/artifacts") == 1
    assert f"/{'a' * 64}-" in key
    assert key.endswith(("-model.rknn", "-best.pt"))


@pytest.mark.parametrize(
    ("field", "project_id", "algorithm_id", "version_id"),
    [
        ("project_id", "", "algorithm-1", "version-1"),
        ("algorithm_id", "project-1", "", "version-1"),
        ("version_id", "project-1", "algorithm-1", ""),
    ],
)
def test_artifact_object_key_rejects_empty_stable_identity(
    field: str,
    project_id: str,
    algorithm_id: str,
    version_id: str,
):
    with pytest.raises(PlatformError) as blocked:
        build_artifact_object_key(
            root_prefix="changlian-ai/artifacts/",
            project_id=project_id,
            algorithm_id=algorithm_id,
            version_id=version_id,
            target="original",
            sha256="a" * 64,
            file_name="best.pt",
        )

    assert blocked.value.code == "MODEL_ARTIFACT_IDENTITY_REQUIRED"
    assert field in blocked.value.detail


@pytest.mark.parametrize(
    "digest",
    ["", "a" * 16, "a" * 63, "a" * 65, "g" * 64, "not-a-sha256"],
)
def test_artifact_object_key_requires_full_hex_sha256(digest: str):
    with pytest.raises(PlatformError) as blocked:
        build_artifact_object_key(
            root_prefix="changlian-ai/artifacts/",
            project_id="project-1",
            algorithm_id="algorithm-1",
            version_id="version-1",
            target="original",
            sha256=digest,
            file_name="best.pt",
        )

    assert blocked.value.code == "MODEL_ARTIFACT_HASH_INVALID"


def test_public_url_joins_storage_source_base_with_final_object_key_exactly_once():
    key = (
        "changlian-ai/artifacts/projects/p1/algorithms/a1/versions/v1/"
        "training/aaaaaaaaaaaaaaaa-best.pt"
    )

    url = build_public_url(
        "https://company-models.oss-cn-hangzhou.aliyuncs.com/",
        key,
    )

    assert url == (
        "https://company-models.oss-cn-hangzhou.aliyuncs.com/"
        "changlian-ai/artifacts/projects/p1/algorithms/a1/versions/v1/"
        "training/aaaaaaaaaaaaaaaa-best.pt"
    )
    assert url.count("changlian-ai/artifacts") == 1


def test_auto_upload_archives_original_and_conversion_for_local_algorithm(tmp_path: Path):
    model, output = _seed(tmp_path)
    service = _service(tmp_path)

    result = service.run_auto_upload_once()

    assert result["versions"] == 1
    assert result["discovered"] == 2
    assert result["uploaded"] == 2
    assert result["failed"] == 0
    rows = service.repository.list(project_id="p1", algorithm_id="local-a1", version_id="v1")
    assert {row["target"] for row in rows} == {"original", "rockchip"}
    assert all(row["storage_status"] == "UPLOADED" for row in rows)
    for row in rows:
        stored = _project_dir(tmp_path, "p1") / row["object_key"]
        assert stored.is_file()
        expected = model.read_bytes() if row["target"] == "original" else output.read_bytes()
        assert stored.read_bytes() == expected
        assert row["object_key"].startswith(
            "changlian-ai/artifacts/projects/p1/algorithms/local-a1/versions/v1/"
        )
        assert row["public_url"].startswith(
            "https://models.example.com/changlian-ai/artifacts/projects/p1/"
        )
        assert "materials-only" not in row["object_key"]
        assert "materials-only" not in row["public_url"]


def test_same_sha_rockchip_artifacts_remain_distinct_by_chip(tmp_path: Path):
    _model, first_output = _seed(tmp_path)
    shared = b"same-rknn-bytes-different-chip"
    first_output.write_bytes(shared)
    project = _project_dir(tmp_path, "p1")
    conversion = project / "deployment" / "jobs" / "convert-rk3576"
    second_output = conversion / "artifacts" / "model.rknn"
    second_output.parent.mkdir(parents=True, exist_ok=True)
    second_output.write_bytes(shared)
    (conversion / "job.json").write_text(json.dumps({
        "id": "convert-rk3576",
        "status": "done",
        "target": "rockchip",
        "source_id": "version::local-a1::v1",
        "source_meta": {"algorithm_id": "local-a1", "version_id": "v1"},
        "params": {"chip": "rk3576"},
        "outputs": [{"path": str(second_output), "available": True}],
    }), encoding="utf-8")
    service = _service(tmp_path)

    result = service.run_auto_upload_once()

    assert result["discovered"] == 3
    rockchip = [
        row for row in service.repository.list(
            project_id="p1", algorithm_id="local-a1", version_id="v1"
        )
        if row["target"] == "rockchip"
    ]
    assert len(rockchip) == 2
    assert {row["chip_code"] for row in rockchip} == {"rk3568", "rk3576"}
    assert len({row["artifact_id"] for row in rockchip}) == 2
    assert len({row["object_key"] for row in rockchip}) == 2
    assert all(
        f"/{row['chip_code']}/" in f"/{row['object_key']}/"
        for row in rockchip
    )


def test_repository_migrates_legacy_identity_index_to_chip_scope(tmp_path: Path):
    root = tmp_path / "model_artifacts"
    root.mkdir(parents=True, exist_ok=True)
    database_path = root / "artifacts.sqlite3"
    with sqlite3.connect(database_path) as database:
        database.executescript("""
        CREATE TABLE model_artifacts (
            artifact_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            algorithm_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            artifact_kind TEXT NOT NULL,
            target TEXT NOT NULL,
            conversion_job_id TEXT NOT NULL DEFAULT '',
            file_name TEXT NOT NULL,
            source_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            storage_source_id TEXT NOT NULL DEFAULT '',
            object_key TEXT NOT NULL DEFAULT '',
            storage_status TEXT NOT NULL DEFAULT 'PENDING',
            storage_error TEXT NOT NULL DEFAULT '',
            uploaded_at TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX ux_model_artifacts_identity
        ON model_artifacts(project_id, algorithm_id, version_id, target, sha256);
        """)
        database.execute(
            """
            INSERT INTO model_artifacts (
                artifact_id, project_id, algorithm_id, version_id, artifact_kind,
                target, conversion_job_id, file_name, source_path, sha256,
                size_bytes, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-rk3568", "p1", "a1", "v1", "conversion", "rockchip",
                "convert-old", "model.rknn", "/old/model.rknn", "a" * 64, 100,
                json.dumps({"chip_code": "rk3568"}), "2026-09-19T00:00:00Z",
                "2026-09-19T00:00:00Z",
            ),
        )

    from platform_core.model_artifacts import ModelArtifactRepository
    repository = ModelArtifactRepository(tmp_path)

    legacy = repository.get("legacy-rk3568")
    assert legacy["chip_code"] == "rk3568"
    assert legacy["public_url"] == ""
    inserted = repository.upsert({
        "artifact_id": "new-rk3576",
        "project_id": "p1",
        "algorithm_id": "a1",
        "version_id": "v1",
        "artifact_kind": "conversion",
        "target": "rockchip",
        "chip_code": "rk3576",
        "conversion_job_id": "convert-new",
        "file_name": "model.rknn",
        "source_path": "/new/model.rknn",
        "sha256": "a" * 64,
        "size_bytes": 100,
        "metadata": {"chip_code": "rk3576"},
    })
    assert inserted["artifact_id"] == "new-rk3576"
    assert {
        row["chip_code"]
        for row in repository.list(project_id="p1", algorithm_id="a1", version_id="v1")
    } == {"rk3568", "rk3576"}


def test_auto_upload_is_idempotent_and_keeps_one_index_per_content(tmp_path: Path):
    _seed(tmp_path)
    service = _service(tmp_path)

    first = service.run_auto_upload_once()
    second = service.run_auto_upload_once()

    assert first["uploaded"] == 2
    assert second["uploaded"] == 2
    rows = service.repository.list(project_id="p1")
    assert len(rows) == 2
    assert service.repository.summary(project_id="p1") == {"total": 2, "uploaded": 2, "failed": 0, "pending": 0}


def test_missing_storage_config_keeps_artifact_pending_instead_of_failing_training_truth(tmp_path: Path):
    _seed(tmp_path)
    service = _service(tmp_path)
    service.save_config(ModelArtifactConfigPayload(storage_source_id="", object_prefix="model-assets", public_base_url="", auto_upload_enabled=True))
    algorithm = __import__("platform_core.algorithms", fromlist=["list_algorithms"]).list_algorithms(_algorithms_file(tmp_path, "p1"))[0]

    summary = service.ingest_version("p1", algorithm, algorithm["versions"][0])

    assert summary["pending"] == 2
    rows = service.repository.list(project_id="p1")
    assert all(row["storage_status"] == "PENDING" for row in rows)
    assert all("尚未配置" in row["storage_error"] for row in rows)



def test_register_verified_remote_artifact_restats_object_before_marking_uploaded(tmp_path: Path):
    service = _service(tmp_path)
    project = _project_dir(tmp_path, "p1")
    object_key = "models-central/p1/local-a1/remote-v1/best/best.pt"
    stored = project / object_key
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes(b"remote-agent-model")
    digest = hashlib.sha256(stored.read_bytes()).hexdigest()

    row = service.register_verified_remote_artifact(
        project_id="p1",
        algorithm_id="local-a1",
        version_id="remote-v1",
        target="best",
        file_name="best.pt",
        sha256=digest,
        size_bytes=stored.stat().st_size,
        storage_source_id="default_local",
        object_key=object_key,
        source_path="",
        metadata={"remote_training": True, "execution_generation": 3},
    )

    assert row["storage_status"] == "UPLOADED"
    assert row["storage_source_id"] == "default_local"
    assert row["object_key"] == object_key
    assert row["sha256"] == digest
    assert row["size_bytes"] == len(b"remote-agent-model")
    assert row["metadata"]["remote_training"] is True


def test_register_verified_remote_artifact_rejects_object_content_mismatch(tmp_path: Path):
    service = _service(tmp_path)
    project = _project_dir(tmp_path, "p1")
    object_key = "models-central/p1/local-a1/remote-v2/best/best.pt"
    stored = project / object_key
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes(b"actual-object")

    with pytest.raises(PlatformError) as mismatch:
        service.register_verified_remote_artifact(
            project_id="p1",
            algorithm_id="local-a1",
            version_id="remote-v2",
            target="best",
            file_name="best.pt",
            sha256=hashlib.sha256(b"different-object").hexdigest(),
            size_bytes=stored.stat().st_size,
            storage_source_id="default_local",
            object_key=object_key,
        )

    assert mismatch.value.code == "MODEL_REMOTE_ARTIFACT_EVIDENCE_MISMATCH"
    assert service.repository.list(
        project_id="p1",
        algorithm_id="local-a1",
        version_id="remote-v2",
    ) == []


def test_public_url_uses_storage_source_base_without_provider_prefix_and_is_persisted(tmp_path: Path):
    _seed(tmp_path)
    service = _service(tmp_path)
    sources = service.storage_sources_factory()
    source = sources.get("default_local")
    assert source is not None

    service.run_auto_upload_once()
    row = next(item for item in service.repository.list(project_id="p1") if item["target"] == "original")
    assert row["public_url"] == service.public_url(row)
    assert row["public_url"].startswith("https://models.example.com/changlian-ai/artifacts/")
    assert "materials-only" not in row["public_url"]


def test_artifact_binding_persists_only_storage_source_and_root_prefix(tmp_path: Path):
    service = _service(tmp_path)

    config = service.repository.config()
    stored = json.loads(service.repository.config_path.read_text(encoding="utf-8"))

    assert config["storage_source_id"] == "default_local"
    assert config["root_prefix"] == "changlian-ai/artifacts"
    assert stored["root_prefix"] == "changlian-ai/artifacts"
    assert "object_prefix" not in stored
    assert "public_base_url" not in stored


def test_artifact_provider_does_not_apply_material_prefix_to_final_object_key(tmp_path: Path, monkeypatch):
    service = _service(tmp_path)
    captured = {}

    def capture_source(_factory, source):
        captured["prefix"] = source.config.get("prefix")
        return object()

    monkeypatch.setattr(
        "platform_core.model_artifacts.StorageProviderFactory.create",
        capture_source,
    )

    service._provider("p1", "default_local")

    assert captured["prefix"] == ""
    original = service.storage_sources_factory().get("default_local")
    assert original is not None
    assert original.config["prefix"] == "materials-only"


def test_model_storage_always_keeps_auto_upload_enabled(tmp_path: Path):
    service = _service(tmp_path)

    saved = service.save_config(ModelArtifactConfigPayload(
        storage_source_id="default_local",
        root_prefix="changlian-ai/artifacts",
        auto_upload_enabled=False,
    ))

    assert saved["auto_upload_enabled"] is True
    assert service.repository.config()["auto_upload_enabled"] is True


def test_auto_upload_discovers_durable_remote_conversion_root(tmp_path: Path):
    _seed(tmp_path)
    service = _service(tmp_path)
    project = _project_dir(tmp_path, "p1")
    remote_job = project / "deploy" / "jobs" / "remote-convert-1"
    output = remote_job / "artifacts" / "model_rk3576.rknn"
    manifest = remote_job / "artifacts" / "manifest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"durable-remote-rknn")
    manifest.write_text('{"status":"converted"}', encoding="utf-8")
    (remote_job / "job.json").write_text(json.dumps({
        "id": "remote-convert-1",
        "status": "done",
        "target": "rockchip",
        "source_trace": {"algorithm_id": "local-a1", "version_id": "v1"},
        "params": {"chip": "rk3576"},
        "outputs": [
            {"path": str(output), "available": True},
            {"path": str(manifest), "available": True},
        ],
    }), encoding="utf-8")

    result = service.run_auto_upload_once()

    assert result["failed"] == 0
    rows = service.repository.list(project_id="p1", algorithm_id="local-a1", version_id="v1")
    durable_rows = [row for row in rows if row["conversion_job_id"] == "remote-convert-1"]
    assert len(durable_rows) == 1
    durable = durable_rows[0]
    assert durable["file_name"] == "model_rk3576.rknn"
    assert durable["target"] == "rockchip"
    assert durable["chip_code"] == "rk3576"
    assert durable["storage_status"] == "UPLOADED"


def test_auto_upload_prefers_durable_remote_conversion_when_job_id_exists_in_both_roots(tmp_path: Path):
    _seed(tmp_path)
    service = _service(tmp_path)
    project = _project_dir(tmp_path, "p1")
    job_id = "remote-collision-1"

    legacy_job = project / "deployment" / "jobs" / job_id
    legacy_job.mkdir(parents=True, exist_ok=True)
    (legacy_job / "job.json").write_text(json.dumps({
        "id": job_id,
        "status": "queued",
        "target": "rockchip",
        "source_trace": {"algorithm_id": "local-a1", "version_id": "v1"},
        "params": {"chip": "rk3576"},
        "outputs": [],
    }), encoding="utf-8")

    remote_job = project / "deploy" / "jobs" / job_id
    output = remote_job / "artifacts" / "model_rk3576.rknn"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"durable-remote-rknn-collision")
    (remote_job / "job.json").write_text(json.dumps({
        "id": job_id,
        "status": "done",
        "target": "rockchip",
        "source_trace": {"algorithm_id": "local-a1", "version_id": "v1"},
        "params": {"chip": "rk3576"},
        "outputs": [{"path": str(output), "available": True}],
    }), encoding="utf-8")

    result = service.run_auto_upload_once()

    assert result["failed"] == 0
    rows = service.repository.list(project_id="p1", algorithm_id="local-a1", version_id="v1")
    durable_rows = [row for row in rows if row["conversion_job_id"] == job_id]
    assert len(durable_rows) == 1
    assert durable_rows[0]["file_name"] == "model_rk3576.rknn"
    assert durable_rows[0]["storage_status"] == "UPLOADED"

def test_storage_test_verifies_long_term_delivery_url(tmp_path: Path, monkeypatch):
    service = _service(tmp_path)
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return type("Response", (), {"status_code": 206})()

    monkeypatch.setattr("platform_core.model_artifacts.requests.get", fake_get)

    result = service.test_storage("default_local")

    assert result["ok"] is True
    assert result["public_url_checked"] is True
    assert result["public_url_reachable"] is True
    assert calls
    assert calls[0][0].startswith(
        "https://models.example.com/changlian-ai/artifacts/.changlian-health-check/"
    )
    assert calls[0][1]["headers"]["Range"] == "bytes=0-0"
    assert calls[0][1]["allow_redirects"] is False


class RecordingHealthProvider:
    def __init__(self, *, fail_delete: bool = False):
        self.fail_delete = fail_delete
        self.operations = []
        self.payload = b""
        self.deleted = False

    def health_check(self):
        self.operations.append("health")
        return StorageHealth.available("bucket ready")

    def upload(self, _key, source, **_kwargs):
        self.operations.append("put")
        self.payload = Path(source).read_bytes()
        return ObjectMetadata(key=_key, size_bytes=len(self.payload))

    def stat(self, key):
        self.operations.append("stat")
        return ObjectMetadata(key=key, size_bytes=len(self.payload))

    def open_reader(self, _key):
        self.operations.append("read")
        return BytesIO(self.payload)

    def delete(self, _key):
        self.operations.append("delete")
        if self.fail_delete:
            raise RuntimeError("delete denied")
        self.deleted = True

    def exists(self, _key):
        self.operations.append("exists")
        return not self.deleted


def test_storage_test_runs_put_stat_read_delete_and_public_url_probe(tmp_path: Path, monkeypatch):
    service = _service(tmp_path)
    provider = RecordingHealthProvider()
    monkeypatch.setattr(service, "_provider", lambda *_args: provider)
    monkeypatch.setattr(
        "platform_core.model_artifacts.requests.get",
        lambda *_args, **_kwargs: type("Response", (), {"status_code": 206})(),
    )

    result = service.test_storage("default_local")

    assert provider.operations == ["health", "put", "stat", "read", "delete", "exists"]
    assert result["stages"] == {
        "authenticated": True,
        "written": True,
        "stat_checked": True,
        "read_checked": True,
        "deleted": True,
        "public_url_checked": True,
    }


def test_storage_test_fails_when_health_object_delete_fails(tmp_path: Path, monkeypatch):
    service = _service(tmp_path)
    provider = RecordingHealthProvider(fail_delete=True)
    monkeypatch.setattr(service, "_provider", lambda *_args: provider)
    monkeypatch.setattr(
        "platform_core.model_artifacts.requests.get",
        lambda *_args, **_kwargs: type("Response", (), {"status_code": 206})(),
    )

    with pytest.raises(PlatformError) as blocked:
        service.test_storage("default_local")

    assert blocked.value.code == "MODEL_STORAGE_HEALTH_DELETE_FAILED"


def test_storage_test_rejects_unreadable_delivery_url(tmp_path: Path, monkeypatch):
    service = _service(tmp_path)
    service.storage_sources_factory().update("default_local", {
        "config": {
            "prefix": "materials-only",
            "public_base_url": "https://private.example.com",
        },
    })

    monkeypatch.setattr(
        "platform_core.model_artifacts.requests.get",
        lambda *_args, **_kwargs: type("Response", (), {"status_code": 403})(),
    )

    with pytest.raises(PlatformError) as blocked:
        service.test_storage("default_local")

    assert blocked.value.code == "MODEL_ARTIFACT_PUBLIC_URL_UNREACHABLE"


def _configure_artifact_oss(service: ModelArtifactService, *, public_base_url: str = "") -> str:
    source_id = "artifact_oss"
    service.storage_sources_factory().create({
        "id": source_id,
        "name": "算法产物 OSS",
        "type": "oss",
        "enabled": True,
        "config": {
            "endpoint": "https://oss-cn-hangzhou.aliyuncs.com",
            "bucket": "new24hlink",
            "prefix": "materials-only",
            "public_base_url": public_base_url,
        },
    })
    service.save_config(ModelArtifactConfigPayload(
        storage_source_id=source_id,
        root_prefix="changlian-ai/artifacts/",
        auto_upload_enabled=True,
    ))
    return source_id


class ArtifactCapabilityProvider:
    def __init__(self, *, bucket_info_ok: bool = True, fail_stage: str = ""):
        self.bucket_info_ok = bucket_info_ok
        self.fail_stage = fail_stage
        self.operations = []
        self.payload = b""
        self.deleted = False

    def health_check(self):
        self.operations.append("health")
        if self.bucket_info_ok:
            return StorageHealth.available("bucket ready")
        return StorageHealth.unavailable(
            "AccessDenied: status=403, eventName=GetBucketInfo"
        )

    def upload(self, key, source, **_kwargs):
        self.operations.append("put")
        if self.fail_stage == "put":
            raise RuntimeError("status: 403 AccessDenied: PutObject denied")
        self.payload = Path(source).read_bytes()
        self.deleted = False
        return ObjectMetadata(key=key, size_bytes=len(self.payload))

    def stat(self, key):
        self.operations.append("stat")
        if self.fail_stage == "stat":
            raise RuntimeError("403 AccessDenied: HeadObject denied")
        return ObjectMetadata(key=key, size_bytes=len(self.payload))

    def open_reader(self, _key):
        self.operations.append("read")
        if self.fail_stage == "get":
            raise RuntimeError("403 AccessDenied: GetObject denied")
        return BytesIO(self.payload)

    def delete(self, _key):
        self.operations.append("delete")
        if self.fail_stage == "delete":
            raise RuntimeError("403 AccessDenied: DeleteObject denied")
        self.deleted = True

    def exists(self, _key):
        self.operations.append("exists")
        return not self.deleted




def test_artifact_storage_treats_non_accessdenied_bucket_metadata_failure_as_diagnostic(
    tmp_path: Path,
    monkeypatch,
):
    service = _service(tmp_path)
    source_id = _configure_artifact_oss(service)
    provider = ArtifactCapabilityProvider()

    def metadata_probe_failed():
        return StorageHealth.unavailable("GetBucketInfo diagnostic unavailable: request rejected")

    provider.health_check = metadata_probe_failed
    monkeypatch.setattr(service, "_provider", lambda *_args: provider)

    result = service.test_artifact_storage(source_id)

    assert result["ok"] is True
    assert result["bucket_info_checked"] is False
    assert result["stages"]["bucket_info_checked"] is False
    assert "仅作为诊断" in result["warning"]
    assert provider.operations == ["put", "stat", "read", "delete", "exists"]


def test_artifact_storage_metadata_failure_does_not_hide_put_failure(
    tmp_path: Path,
    monkeypatch,
):
    service = _service(tmp_path)
    source_id = _configure_artifact_oss(service)
    provider = ArtifactCapabilityProvider(fail_stage="put")

    def metadata_probe_failed():
        return StorageHealth.unavailable("GetBucketInfo diagnostic unavailable: request rejected")

    provider.health_check = metadata_probe_failed
    monkeypatch.setattr(service, "_provider", lambda *_args: provider)

    with pytest.raises(PlatformError) as blocked:
        service.test_artifact_storage(source_id)

    assert blocked.value.code == "MODEL_STORAGE_OBJECT_WRITE_FAILED"
    assert "写入失败（PUT）" in blocked.value.message
def test_artifact_storage_allows_bucket_info_access_denied_after_object_roundtrip(
    tmp_path: Path,
    monkeypatch,
):
    service = _service(tmp_path)
    source_id = _configure_artifact_oss(
        service,
        public_base_url="https://new24hlink.oss-cn-hangzhou.aliyuncs.com",
    )
    provider = ArtifactCapabilityProvider(bucket_info_ok=False)
    monkeypatch.setattr(service, "_provider", lambda *_args: provider)
    monkeypatch.setattr(
        "platform_core.model_artifacts.requests.get",
        lambda *_args, **_kwargs: type("Response", (), {"status_code": 206})(),
    )

    result = service.test_artifact_storage(source_id)

    assert result["ok"] is True
    assert result["health"] == "AVAILABLE"
    assert result["bucket_info_checked"] is False
    assert result["stages"]["bucket_info_checked"] is False
    assert "Bucket 元信息查询无权限" in result["warning"]
    assert "不影响算法产物存储" in result["message"]
    assert result["public_url_checked"] is True
    assert result["public_url_reachable"] is True
    assert result["probe_object_key"].startswith(
        "changlian-ai/artifacts/.changlian-health-check/"
    )
    assert provider.operations == ["health", "put", "stat", "read", "delete", "exists"]


def test_artifact_storage_put_403_reports_write_permission(tmp_path: Path, monkeypatch):
    service = _service(tmp_path)
    source_id = _configure_artifact_oss(service)
    provider = ArtifactCapabilityProvider(fail_stage="put")
    monkeypatch.setattr(service, "_provider", lambda *_args: provider)

    with pytest.raises(PlatformError) as blocked:
        service.test_artifact_storage(source_id)

    assert blocked.value.code == "MODEL_STORAGE_OBJECT_WRITE_FAILED"
    assert "写入失败（PUT）" in blocked.value.message


def test_artifact_storage_get_403_reports_read_permission(tmp_path: Path, monkeypatch):
    service = _service(tmp_path)
    source_id = _configure_artifact_oss(service)
    provider = ArtifactCapabilityProvider(fail_stage="get")
    monkeypatch.setattr(service, "_provider", lambda *_args: provider)

    with pytest.raises(PlatformError) as blocked:
        service.test_artifact_storage(source_id)

    assert blocked.value.code == "MODEL_STORAGE_OBJECT_READ_FAILED"
    assert "读取失败（GET）" in blocked.value.message
    assert provider.operations[-2:] == ["delete", "exists"]


def test_artifact_storage_stat_403_reports_read_permission(tmp_path: Path, monkeypatch):
    service = _service(tmp_path)
    source_id = _configure_artifact_oss(service)
    provider = ArtifactCapabilityProvider(fail_stage="stat")
    monkeypatch.setattr(service, "_provider", lambda *_args: provider)

    with pytest.raises(PlatformError) as blocked:
        service.test_artifact_storage(source_id)

    assert blocked.value.code == "MODEL_STORAGE_OBJECT_STAT_FAILED"
    assert "读取权限不足（STAT）" in blocked.value.message
    assert provider.operations[-2:] == ["delete", "exists"]


def test_artifact_storage_nested_post_put_stat_403_is_read_failure_and_cleans_up(
    tmp_path: Path,
    monkeypatch,
):
    service = _service(tmp_path)
    source_id = _configure_artifact_oss(service)
    provider = ArtifactCapabilityProvider()

    def upload_with_nested_stat_error(key, source, **_kwargs):
        provider.operations.extend(["put", "stat"])
        provider.payload = Path(source).read_bytes()
        provider.deleted = False
        raise RuntimeError("upload: stat: status: 403 AccessDenied: HeadObject denied")

    provider.upload = upload_with_nested_stat_error
    monkeypatch.setattr(service, "_provider", lambda *_args: provider)

    with pytest.raises(PlatformError) as blocked:
        service.test_artifact_storage(source_id)

    assert blocked.value.code == "MODEL_STORAGE_OBJECT_STAT_FAILED"
    assert provider.operations == ["health", "put", "stat", "delete", "exists"]


def test_artifact_storage_delete_403_reports_delete_permission(tmp_path: Path, monkeypatch):
    service = _service(tmp_path)
    source_id = _configure_artifact_oss(service)
    provider = ArtifactCapabilityProvider(fail_stage="delete")
    monkeypatch.setattr(service, "_provider", lambda *_args: provider)

    with pytest.raises(PlatformError) as blocked:
        service.test_artifact_storage(source_id)

    assert blocked.value.code == "MODEL_STORAGE_OBJECT_DELETE_FAILED"
    assert "删除失败（DELETE）" in blocked.value.message


def test_artifact_storage_public_url_403_fails_changlian_filepath(
    tmp_path: Path,
    monkeypatch,
):
    service = _service(tmp_path)
    source_id = _configure_artifact_oss(
        service,
        public_base_url="https://new24hlink.oss-cn-hangzhou.aliyuncs.com",
    )
    provider = ArtifactCapabilityProvider()
    monkeypatch.setattr(service, "_provider", lambda *_args: provider)
    monkeypatch.setattr(
        "platform_core.model_artifacts.requests.get",
        lambda *_args, **_kwargs: type("Response", (), {"status_code": 403})(),
    )

    with pytest.raises(PlatformError) as blocked:
        service.test_artifact_storage(source_id)

    assert blocked.value.code == "MODEL_ARTIFACT_PUBLIC_URL_UNREACHABLE"
    assert blocked.value.message == "新畅联 filePath 不可访问"
    assert provider.operations[-2:] == ["delete", "exists"]


def test_artifact_storage_full_bucket_and_object_permissions_pass(
    tmp_path: Path,
    monkeypatch,
):
    service = _service(tmp_path)
    source_id = _configure_artifact_oss(
        service,
        public_base_url="https://new24hlink.oss-cn-hangzhou.aliyuncs.com",
    )
    provider = ArtifactCapabilityProvider()
    monkeypatch.setattr(service, "_provider", lambda *_args: provider)
    monkeypatch.setattr(
        "platform_core.model_artifacts.requests.get",
        lambda *_args, **_kwargs: type("Response", (), {"status_code": 206})(),
    )

    result = service.test_artifact_storage(source_id)

    assert result["ok"] is True
    assert result["bucket_info_checked"] is True
    assert result["warning"] == ""
    assert result["public_url_checked"] is True
    assert result["public_url_reachable"] is True
    assert provider.operations == ["health", "put", "stat", "read", "delete", "exists"]


def test_generic_storage_health_contract_still_blocks_bucket_metadata_access_denied(
    tmp_path: Path,
    monkeypatch,
):
    service = _service(tmp_path)
    source_id = _configure_artifact_oss(service)
    provider = ArtifactCapabilityProvider(bucket_info_ok=False)
    monkeypatch.setattr(service, "_provider", lambda *_args: provider)

    with pytest.raises(PlatformError) as blocked:
        service.test_storage(source_id)

    assert blocked.value.code == "MODEL_STORAGE_HEALTH_AUTH_FAILED"
    assert provider.operations == ["health"]
