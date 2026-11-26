"""Bounded stored-name lookup used by business-file resolution.

The hot path used to hydrate every project material for one name. These tests
pin the schema/index upgrade, the exact uniqueness semantics the caller relies
on, the bounded legacy completion query and limit clamping.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import app
from platform_core import material_repository_batch as material_batch_module
import platform_core.material_repository as material_repository_module
from platform_core.material_repository import (
    MaterialRepository,
    _LEGACY_STORED_NAME_SCAN_LIMIT,
)

INDEX_NAME = "ix_materials_stored_name"


def material(
    image_id: str, stored_name: str, *, created_at: str,
    object_key: str | None = None,
) -> dict:
    return {
        "id": image_id,
        "filename": stored_name,
        "stored_name": stored_name,
        "storage_source_id": "default_local",
        "storage_type": "local",
        "object_key": object_key or f"uploads/{stored_name}",
        "created_at": created_at,
    }


def index_names(path) -> set[str]:
    with sqlite3.connect(path) as database:
        return {
            str(row[0])
            for row in database.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }


def user_version(path) -> int:
    with sqlite3.connect(path) as database:
        return int(database.execute("PRAGMA user_version").fetchone()[0])


def insert_legacy_row(
    repository: MaterialRepository, image_id: str, *,
    object_key: str, created_at: str,
) -> None:
    """Insert a pre-normalization payload that has no stored_name field."""
    payload = {
        "id": image_id,
        "filename": object_key.rsplit("/", 1)[-1],
        "object_key": object_key,
        "created_at": created_at,
    }
    with sqlite3.connect(repository.path) as database:
        database.execute(
            "INSERT INTO materials("
            "id, filename, storage_source_id, storage_type, object_key, "
            "created_at, updated_at, payload_json) "
            "VALUES (?, ?, 'default_local', 'local', ?, ?, '', ?)",
            (image_id, payload["filename"], object_key, created_at,
             json.dumps(payload, ensure_ascii=False)),
        )


def test_current_schema_creates_the_stored_name_index(tmp_path):
    repository = MaterialRepository(tmp_path)
    assert material_repository_module._SCHEMA_VERSION == 8
    assert user_version(repository.path) == 8
    assert INDEX_NAME in index_names(repository.path)
    with closing(repository._connect()) as database:
        assert repository._required_objects_present(database) is True


def test_v7_database_falls_through_the_fast_path_and_gets_the_index(tmp_path):
    repository = MaterialRepository(tmp_path)
    with sqlite3.connect(repository.path) as database:
        database.execute(f"DROP INDEX {INDEX_NAME}")
        database.execute("PRAGMA user_version=7")
        database.commit()
    assert user_version(repository.path) == 7
    assert INDEX_NAME not in index_names(repository.path)

    probe = object.__new__(MaterialRepository)
    probe.path = repository.path
    # A v7 database is not mistaken for the current schema by the readiness
    # probe, so reopening runs initialization and builds the index.
    assert probe._read_schema_version_fast() == 7

    # Simulate a fresh process: the in-process constructor cache must not hide
    # the upgrade of the same file.
    material_batch_module._MATERIAL_INIT_READY.discard(repository.path.resolve())
    MaterialRepository(tmp_path)
    assert user_version(repository.path) == 8
    assert INDEX_NAME in index_names(repository.path)


def test_v8_database_missing_the_index_is_repaired_by_reinitialization(tmp_path):
    repository = MaterialRepository(tmp_path)
    with sqlite3.connect(repository.path) as database:
        database.execute(f"DROP INDEX {INDEX_NAME}")
        database.execute("PRAGMA user_version=8")
        database.commit()
    probe = object.__new__(MaterialRepository)
    probe.path = repository.path
    # The readiness probe must not accept a v8 database that lost the index.
    assert probe._read_schema_version_fast() is None

    material_batch_module._MATERIAL_INIT_READY.discard(repository.path.resolve())
    MaterialRepository(tmp_path)
    assert INDEX_NAME in index_names(repository.path)


def test_primary_lookup_uses_the_stored_name_index(tmp_path):
    repository = MaterialRepository(tmp_path)
    repository.upsert(
        material("m-1", "indexed.jpg", created_at="2026-01-01T00:00:00+00:00")
    )
    with closing(repository._connect()) as database:
        plan = database.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM materials "
            "WHERE json_extract(payload_json, '$.stored_name') = ? "
            "ORDER BY created_at, id LIMIT ?",
            ("indexed.jpg", 2),
        ).fetchall()
    assert any(INDEX_NAME in str(row[-1]) for row in plan)


def test_lookup_never_hydrates_the_catalog(tmp_path, monkeypatch):
    repository = MaterialRepository(tmp_path)
    for index in range(3):
        repository.upsert(
            material(
                f"m-{index}", f"img-{index}.jpg",
                created_at=f"2026-01-01T00:00:0{index}+00:00",
            )
        )

    def forbidden_read():
        raise AssertionError("stored-name lookup must not hydrate the catalog")

    monkeypatch.setattr(repository, "read", forbidden_read)
    assert [row["id"] for row in repository.find_by_stored_name("img-1.jpg")] == ["m-1"]
    assert repository.find_by_stored_name("absent.jpg") == []


def test_duplicate_stored_names_stay_ambiguous_for_the_caller(tmp_path, monkeypatch):
    repository = MaterialRepository(tmp_path)
    repository.upsert_many([
        material("m-1", "dup.jpg", created_at="2026-01-01T00:00:01+00:00"),
        material("m-2", "dup.jpg", created_at="2026-01-01T00:00:02+00:00"),
        material("m-3", "single.jpg", created_at="2026-01-01T00:00:03+00:00"),
    ])
    assert [
        row["id"] for row in repository.find_by_stored_name("dup.jpg")
    ] == ["m-1", "m-2"]
    assert [
        row["id"] for row in repository.find_by_stored_name("single.jpg")
    ] == ["m-3"]

    monkeypatch.setattr(app, "material_store", lambda project_id: repository)

    # 2+ matches must still produce None, exactly one match resolves, none -> None.
    assert app._business_material_by_name("project-a", "dup.jpg") is None
    resolved = app._business_material_by_name("project-a", "single.jpg")
    assert resolved is not None and resolved["id"] == "m-3"
    assert repository.find_by_stored_name("unknown.jpg") == []
    assert app._business_material_by_name("project-a", "unknown.jpg") is None


def test_legacy_payload_without_stored_name_is_found_through_the_fallback(tmp_path):
    repository = MaterialRepository(tmp_path)
    insert_legacy_row(
        repository, "legacy-1",
        object_key="uploads/legacy-name.jpg",
        created_at="2026-01-02T00:00:00+00:00",
    )
    rows = repository.find_by_stored_name("legacy-name.jpg")
    assert [row["id"] for row in rows] == ["legacy-1"]
    # The derived payload name is exposed exactly like _row_payload already did.
    assert rows[0]["stored_name"] == "legacy-name.jpg"


def test_legacy_fallback_decodes_at_most_the_documented_cap(tmp_path, monkeypatch):
    repository = MaterialRepository(tmp_path)
    base = datetime(2026, 2, 1, tzinfo=timezone.utc)
    total = _LEGACY_STORED_NAME_SCAN_LIMIT + 3
    for index in range(total):
        insert_legacy_row(
            repository, f"legacy-{index:04d}",
            object_key=f"uploads/legacy-{index:04d}.jpg",
            created_at=(base + timedelta(seconds=index)).isoformat(),
        )

    decoded: list[str] = []
    original = MaterialRepository._row_payload

    def counting(row):
        decoded.append(str(row["id"]))
        return original(row)

    monkeypatch.setattr(repository, "_row_payload", counting)
    # The legacy row that sorts beyond the cap is never decoded: a miss returns
    # fewer rows (here none) instead of scanning every payload.
    assert repository.find_by_stored_name(f"legacy-{total - 1:04d}.jpg") == []
    assert total > _LEGACY_STORED_NAME_SCAN_LIMIT
    assert len(decoded) == _LEGACY_STORED_NAME_SCAN_LIMIT


def test_limit_is_clamped_to_one_through_fifty(tmp_path):
    repository = MaterialRepository(tmp_path)
    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    repository.upsert_many([
        material(
            f"m-{index:03d}", "shared.jpg",
            created_at=(base + timedelta(seconds=index)).isoformat(),
            object_key=f"uploads/shared-{index:03d}.jpg",
        )
        for index in range(55)
    ])
    assert len(repository.find_by_stored_name("shared.jpg")) == 2
    assert [
        row["id"] for row in repository.find_by_stored_name("shared.jpg", limit=0)
    ] == ["m-000"]
    assert len(repository.find_by_stored_name("shared.jpg", limit=-10)) == 1
    widened = repository.find_by_stored_name("shared.jpg", limit=10_000)
    assert len(widened) == 50
    assert [row["id"] for row in widened] == [
        f"m-{index:03d}" for index in range(50)
    ]
    assert repository.find_by_stored_name("") == []
