from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from platform_core.material_repository import MaterialRepository
from platform_core.secrets import MemorySecretStore, SecretCredentialStore
from platform_core.storage import (
    LocalStorageProvider,
    MaterialCache,
    ObjectMetadata,
    StorageError,
    StorageManager,
    StorageSourceRepository,
    StorageType,
)


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def test_manager_materializes_legacy_local_row_and_persists_hash(tmp_path):
    data = tmp_path / "data"
    project = data / "projects" / "p1"
    (project / "uploads").mkdir(parents=True)
    content = b"legacy-file"
    (project / "uploads" / "legacy.jpg").write_bytes(content)
    materials = MaterialRepository(project)
    materials.upsert({"id": "legacy", "filename": "legacy.jpg", "stored_name": "legacy.jpg", "labels": []})
    sources = StorageSourceRepository(data / "storage" / "sources.sqlite3")
    manager = StorageManager(data_dir=data, project_id="p1", materials=materials, sources=sources)

    resolved = manager.materialize("legacy")

    assert resolved.path == (project / "uploads" / "legacy.jpg").resolve()
    assert resolved.cache_hit is True
    persisted = materials.get("legacy")
    assert persisted["content_sha256"] == sha(content)
    assert persisted["size_bytes"] == len(content)


def test_manager_uses_content_cache_for_external_source(tmp_path):
    data = tmp_path / "data"
    project = data / "projects" / "p1"
    materials = MaterialRepository(project)
    content = b"external-image"
    materials.upsert({
        "id": "remote-1", "filename": "remote.jpg", "storage_source_id": "remote-a",
        "storage_type": "remote", "object_key": "folder/remote.jpg",
        "content_sha256": sha(content), "size_bytes": len(content), "labels": [],
    })
    sources = StorageSourceRepository(data / "storage" / "sources.sqlite3")
    source = sources.create({"id": "remote-a", "name": "remote", "type": "remote", "config": {"base_url": "http://127.0.0.1"}})
    remote_root = tmp_path / "remote"
    remote_root.mkdir()
    provider = LocalStorageProvider(source.id, remote_root)
    provider.storage_type = StorageType.REMOTE
    provider.upload("folder/remote.jpg", Path(project).parent / "missing" if False else __import__("io").BytesIO(content))
    manager = StorageManager(
        data_dir=data, project_id="p1", materials=materials, sources=sources,
        provider_resolver=lambda _source, _credentials: provider,
    )

    first = manager.materialize("remote-1")
    second = manager.materialize("remote-1")
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert first.path.read_bytes() == content
    assert data / "cache" / "materials" in first.path.parents


def test_manager_fails_for_missing_or_disabled_source(tmp_path):
    data = tmp_path / "data"
    materials = MaterialRepository(data / "projects" / "p1")
    materials.upsert({"id": "x", "filename": "x.jpg", "storage_source_id": "gone", "storage_type": "remote", "object_key": "x.jpg"})
    sources = StorageSourceRepository(data / "storage" / "sources.sqlite3")
    manager = StorageManager(data_dir=data, project_id="p1", materials=materials, sources=sources)
    with pytest.raises(StorageError) as missing:
        manager.materialize("x")
    assert missing.value.code == "STORAGE_SOURCE_NOT_FOUND"


def test_manager_resolves_compound_credentials_without_exposing_them(tmp_path):
    data = tmp_path / "data"
    materials = MaterialRepository(data / "projects" / "p1")
    sources = StorageSourceRepository(data / "storage" / "sources.sqlite3")
    source = sources.create({"id": "s3-a", "name": "S3", "type": "s3", "config": {"bucket": "images"}, "secret_ref": "xjalgo:storage-source:s3-a"})
    backend = MemorySecretStore()
    secrets = SecretCredentialStore(backend)
    secrets.set(source.secret_ref, {"access_key_id": "id", "secret_access_key": "top-secret"})
    captured = {}

    def resolver(value, credentials):
        captured.update(credentials)
        raise StorageError(code="STOP", message="stop")

    manager = StorageManager(data_dir=data, project_id="p1", materials=materials, sources=sources, credentials=secrets, provider_resolver=resolver)
    with pytest.raises(StorageError, match="stop"):
        manager.provider_for("s3-a")
    assert captured == {"access_key_id": "id", "secret_access_key": "top-secret"}
