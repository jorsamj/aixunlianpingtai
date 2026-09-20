import hashlib
import sqlite3
import json
from pathlib import Path

import pytest

from platform_core.errors import PlatformError
from platform_core.algorithms import save_algorithms
from platform_core.model_artifacts import ModelArtifactConfigPayload, ModelArtifactService
from platform_core.secrets import MemorySecretStore, SecretCredentialStore
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
    service.save_config(ModelArtifactConfigPayload(
        storage_source_id="default_local",
        object_prefix="models-central",
        public_base_url="https://models.example.com",
        auto_upload_enabled=True,
    ))
    return service


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
        assert row["object_key"].startswith("models-central/p1/local-a1/v1/")
        assert row["public_url"].startswith("https://models.example.com/models-central/p1/local-a1/v1/")


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


def test_public_url_includes_storage_source_prefix_and_is_persisted(tmp_path: Path):
    _seed(tmp_path)
    service = _service(tmp_path)
    sources = service.storage_sources_factory()
    source = sources.get("default_local")
    assert source is not None

    # Local source has no provider prefix, so the configured delivery domain is
    # joined directly with the immutable object key.
    service.run_auto_upload_once()
    row = next(item for item in service.repository.list(project_id="p1") if item["target"] == "original")
    assert row["public_url"] == service.public_url(row)
    assert row["public_url"].startswith("https://models.example.com/models-central/")


def test_model_storage_always_keeps_auto_upload_enabled(tmp_path: Path):
    service = _service(tmp_path)

    saved = service.save_config(ModelArtifactConfigPayload(
        storage_source_id="default_local",
        object_prefix="model-assets",
        public_base_url="https://models.example.com",
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


def test_storage_test_verifies_long_term_delivery_url(tmp_path: Path, monkeypatch):
    service = _service(tmp_path)
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return type("Response", (), {"status_code": 206})()

    monkeypatch.setattr("platform_core.model_artifacts.requests.get", fake_get)

    result = service.test_storage("default_local", "https://models.example.com")

    assert result["ok"] is True
    assert result["public_url_checked"] is True
    assert result["public_url_reachable"] is True
    assert calls
    assert calls[0][0].startswith("https://models.example.com/model-assets-healthcheck/")
    assert calls[0][1]["headers"]["Range"] == "bytes=0-0"
    assert calls[0][1]["allow_redirects"] is False


def test_storage_test_rejects_unreadable_delivery_url(tmp_path: Path, monkeypatch):
    service = _service(tmp_path)

    monkeypatch.setattr(
        "platform_core.model_artifacts.requests.get",
        lambda *_args, **_kwargs: type("Response", (), {"status_code": 403})(),
    )

    with pytest.raises(PlatformError) as blocked:
        service.test_storage("default_local", "https://private.example.com")

    assert blocked.value.code == "MODEL_ARTIFACT_PUBLIC_URL_UNREACHABLE"
