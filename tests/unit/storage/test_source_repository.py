from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading
import time

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



def test_existing_wal_connection_does_not_reapply_journal_mode(monkeypatch, tmp_path):
    class Cursor:
        def __init__(self, value=None):
            self.value = value

        def fetchone(self):
            return [self.value]

        def fetchall(self):
            # Schema initialization will see the current revision column.
            return [{"name": "runtime_revision"}]

    class FakeDatabase:
        def __init__(self):
            self.row_factory = None
            self.calls = []

        def execute(self, statement, *_args):
            self.calls.append(statement)
            if statement == "PRAGMA journal_mode":
                return Cursor("wal")
            if statement == "PRAGMA journal_mode=WAL":
                raise AssertionError("WAL mode must not be reapplied when already active")
            return Cursor(None)

    fake = FakeDatabase()
    import platform_core.storage.source_repository as source_repository_module
    monkeypatch.setattr(source_repository_module.sqlite3, "connect", lambda *_args, **_kwargs: fake)
    repository = object.__new__(StorageSourceRepository)
    repository.path = tmp_path / "storage.sqlite3"

    connected = repository._connect()

    assert connected is fake
    assert fake.calls[:2] == ["PRAGMA busy_timeout=5000", "PRAGMA journal_mode"]
    assert "PRAGMA journal_mode=WAL" not in fake.calls
    assert fake.calls[-1] == "PRAGMA foreign_keys=ON"


def test_non_wal_connection_sets_busy_timeout_before_switching_mode(monkeypatch, tmp_path):
    class Cursor:
        def __init__(self, value=None):
            self.value = value

        def fetchone(self):
            return [self.value]

        def fetchall(self):
            # Schema initialization will see the current revision column.
            return [{"name": "runtime_revision"}]

    class FakeDatabase:
        def __init__(self):
            self.row_factory = None
            self.calls = []

        def execute(self, statement, *_args):
            self.calls.append(statement)
            if statement == "PRAGMA journal_mode":
                return Cursor("delete")
            return Cursor(None)

    fake = FakeDatabase()
    import platform_core.storage.source_repository as source_repository_module
    monkeypatch.setattr(source_repository_module.sqlite3, "connect", lambda *_args, **_kwargs: fake)
    repository = object.__new__(StorageSourceRepository)
    repository.path = tmp_path / "storage.sqlite3"

    repository._connect()

    assert fake.calls[:3] == [
        "PRAGMA busy_timeout=5000",
        "PRAGMA journal_mode",
        "PRAGMA journal_mode=WAL",
    ]


def test_concurrent_first_initialization_serializes_wal_transition(monkeypatch, tmp_path):
    class Cursor:
        def __init__(self, value=None):
            self.value = value

        def fetchone(self):
            return [self.value]

        def fetchall(self):
            # Schema initialization will see the current revision column.
            return [{"name": "runtime_revision"}]

    transition = threading.Lock()

    class FakeDatabase:
        def __init__(self):
            self.row_factory = None

        def execute(self, statement, *_args):
            if statement == "PRAGMA journal_mode":
                return Cursor("delete")
            if statement == "PRAGMA journal_mode=WAL":
                if not transition.acquire(blocking=False):
                    raise sqlite3.OperationalError("database is locked")
                try:
                    time.sleep(0.02)
                finally:
                    transition.release()
            return Cursor(None)

        def executescript(self, _script):
            return None

        def close(self):
            return None

    import platform_core.storage.source_repository as source_repository_module
    monkeypatch.setattr(
        source_repository_module.sqlite3,
        "connect",
        lambda *_args, **_kwargs: FakeDatabase(),
    )
    workers = 8
    start = threading.Barrier(workers)
    database_path = tmp_path / "storage.sqlite3"

    def initialize(_index):
        start.wait()
        StorageSourceRepository(database_path)

    errors = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in [pool.submit(initialize, index) for index in range(workers)]:
            try:
                future.result()
            except Exception as error:
                errors.append(error)

    assert errors == []


def test_runtime_revision_monotonic_for_config_changes_but_not_cosmetic_edits(tmp_path):
    repository = StorageSourceRepository(tmp_path / "storage.sqlite3")
    source = repository.create({
        "id": "revision_guard", "name": "guard", "type": "local",
        "config": {"root": "A"}, "enabled": True,
    })
    first = source.runtime_revision
    rename = repository.update(source.id, {"name": "new-display-name"})
    assert rename.runtime_revision == first
    other = repository.update(source.id, {"config": {"root": "B"}})
    assert other.runtime_revision == first + 1
    restored = repository.update(source.id, {"config": {"root": "A"}})
    assert restored.runtime_revision == first + 2
    assert restored.config == source.config
    disabled = repository.update(source.id, {"enabled": False})
    assert disabled.runtime_revision == first + 3
    with_secret = repository.update(source.id, {"secret_ref": "new-version"})
    assert with_secret.runtime_revision == first + 4
    repository.record_health(source.id, ok=True, message="ok")
    assert repository.get(source.id).runtime_revision == first + 4


def test_legacy_storage_source_schema_migrates_revision_without_losing_records(tmp_path):
    db_path = tmp_path / "storage.sqlite3"
    with sqlite3.connect(db_path) as database:
        database.execute("""
            CREATE TABLE storage_sources (
                id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL, config_json TEXT NOT NULL DEFAULT '{}',
                secret_ref TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1, is_default INTEGER NOT NULL DEFAULT 0,
                health_status TEXT NOT NULL DEFAULT 'UNKNOWN',
                health_message TEXT NOT NULL DEFAULT '',
                last_checked_at TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
        database.execute(
            "INSERT INTO storage_sources "
            "(id,name,type,config_json,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?)",
            ("legacy_local", "legacy", "local", '{"root":"old"}', "old", "old"),
        )
    migrated = StorageSourceRepository(db_path)
    assert migrated.get("legacy_local").config == {"root": "old"}
    assert migrated.get("legacy_local").runtime_revision == 1
    changed = migrated.update("legacy_local", {"config": {"root": "new"}})
    assert changed.runtime_revision == 2
    assert StorageSourceRepository(db_path).get("legacy_local").runtime_revision == 2
