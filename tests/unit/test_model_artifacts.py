import hashlib
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
        "params": {"chip": "rk3588"},
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
    service.save_config(ModelArtifactConfigPayload(storage_source_id="", object_prefix="model-assets", auto_upload_enabled=True))
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
