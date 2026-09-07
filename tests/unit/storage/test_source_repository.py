from __future__ import annotations

import sqlite3

import pytest

from platform_core.storage import StorageSourceRepository


def test_repository_uses_wal_and_seeds_one_default_local_source(tmp_path):
    repository = StorageSourceRepository(tmp_path / "storage.sqlite3")
    assert repository.journal_mode() == "wal"
    sources = repository.list()
    assert len(sources) == 1
    assert sources[0].id == "default_local"
    assert sources[0].type == "local"
    assert sources[0].is_default is True
    assert sources[0].enabled is True


def test_storage_source_crud_preserves_single_default(tmp_path):
    repository = StorageSourceRepository(tmp_path / "storage.sqlite3")
    created = repository.create({
        "id": "minio_a", "name": "内网 MinIO", "type": "s3",
        "config": {"endpoint": "http://127.0.0.1:9000", "bucket": "materials", "prefix": "incoming", "region": "us-east-1", "use_ssl": False},
        "secret_ref": "xjalgo:storage-source:minio_a", "enabled": True,
    })
    assert created.name == "内网 MinIO"
    assert created.config["bucket"] == "materials"
    updated = repository.update("minio_a", {"name": "生产 MinIO", "enabled": False})
    assert updated.name == "生产 MinIO"
    assert updated.enabled is False
    repository.update("minio_a", {"enabled": True})
    selected = repository.set_default("minio_a")
    assert selected.is_default is True
    assert repository.get("default_local").is_default is False
    assert sum(item.is_default for item in repository.list()) == 1
    repository.set_default("default_local")
    assert repository.delete("minio_a") is True
    assert repository.get("minio_a") is None


def test_default_local_cannot_be_deleted_or_disabled(tmp_path):
    repository = StorageSourceRepository(tmp_path / "storage.sqlite3")
    with pytest.raises(ValueError, match="default local"):
        repository.delete("default_local")
    with pytest.raises(ValueError, match="default local"):
        repository.update("default_local", {"enabled": False})


def test_referenced_source_cannot_be_deleted(tmp_path):
    repository = StorageSourceRepository(
        tmp_path / "storage.sqlite3",
        reference_counter=lambda source_id: 3 if source_id == "remote_a" else 0,
    )
    repository.create({"id": "remote_a", "name": "素材服务器 A", "type": "remote", "config": {"base_url": "http://127.0.0.1:9020", "namespace": "main"}})
    with pytest.raises(ValueError, match="3 materials"):
        repository.delete("remote_a")


def test_health_result_is_persisted_without_credentials(tmp_path):
    database_path = tmp_path / "storage.sqlite3"
    repository = StorageSourceRepository(database_path)
    repository.create({
        "id": "oss_a", "name": "杭州 OSS", "type": "oss",
        "config": {"endpoint": "oss-cn-hangzhou.aliyuncs.com", "bucket": "training"},
        "secret_ref": "xjalgo:storage-source:oss_a",
    })
    source = repository.record_health("oss_a", ok=False, message="AccessKey secret=should-not-be-saved")
    assert source.health_status == "UNAVAILABLE"
    assert "should-not-be-saved" not in source.health_message
    assert "[REDACTED]" in source.health_message
    assert "should-not-be-saved" not in database_path.read_bytes().decode("utf-8", "ignore")


def test_sensitive_config_keys_are_rejected(tmp_path):
    repository = StorageSourceRepository(tmp_path / "storage.sqlite3")
    with pytest.raises(ValueError, match="sensitive"):
        repository.create({"id": "bad", "name": "bad", "type": "s3", "config": {"bucket": "x", "secret_access_key": "plaintext"}})


def test_public_record_only_exposes_secret_configuration_state(tmp_path):
    repository = StorageSourceRepository(tmp_path / "storage.sqlite3")
    source = repository.create({
        "id": "s3_a", "name": "S3", "type": "s3",
        "config": {"endpoint": "https://s3.example.com", "bucket": "images"},
        "secret_ref": "xjalgo:storage-source:s3_a",
    })
    public = source.to_public_dict(secret_configured=True, secret_masked="abc****wxyz")
    assert public["secret_ref"] == "xjalgo:storage-source:s3_a"
    assert public["secret_configured"] is True
    assert public["secret_masked"] == "abc****wxyz"
    assert "secret" not in public["config"]


def test_database_constraints_reject_duplicate_names(tmp_path):
    repository = StorageSourceRepository(tmp_path / "storage.sqlite3")
    repository.create({"id": "a", "name": "same", "type": "local", "config": {"root": "a"}})
    with pytest.raises(sqlite3.IntegrityError):
        repository.create({"id": "b", "name": "same", "type": "local", "config": {"root": "b"}})
