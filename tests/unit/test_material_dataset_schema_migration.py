from __future__ import annotations

import sqlite3

from platform_core import material_repository_batch as material_batch_module
from platform_core.material_repository import MaterialRepository


def test_schema_6_database_gains_dataset_index_once_and_keeps_data(tmp_path):
    project = tmp_path / "project"
    repository = MaterialRepository(project)
    repository.upsert_many([
        {"id": "old-default", "filename": "old.jpg", "object_key": "old.jpg",
         "dataset_id": "default", "split": "unassigned"},
        {"id": "old-other", "filename": "other.jpg", "object_key": "other.jpg",
         "dataset_id": "other", "split": "test"},
    ])
    before = {row["id"]: row for row in repository.read().rows}

    with sqlite3.connect(repository.path) as database:
        database.execute("DROP INDEX ix_materials_dataset")
        database.execute("PRAGMA user_version=6")
        database.commit()

    read_only = MaterialRepository.open_readonly(project)
    assert read_only.get("old-default")["dataset_id"] == "default"

    # Simulate a fresh process opening the schema-6 file; the in-process
    # repository-ready cache must not hide the migration.
    material_batch_module._MATERIAL_INIT_READY.discard(repository.path.resolve())
    migrated = MaterialRepository(project)
    with sqlite3.connect(migrated.path) as database:
        assert database.execute("PRAGMA user_version").fetchone()[0] == 8
        index = database.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='ix_materials_dataset'"
        ).fetchone()
        assert index and "dataset_id" in index[0]
        plan = " | ".join(
            str(row[-1]) for row in database.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM materials "
                "WHERE COALESCE(CAST(json_extract(payload_json, '$.dataset_id') AS TEXT), 'default') = ?",
                ("other",),
            ).fetchall()
        )
        assert "ix_materials_dataset" in plan, plan

    after = {row["id"]: row for row in migrated.read().rows}
    assert after == before
    # A second open must be a no-op and must not lose the index/version.
    MaterialRepository(project)
    with sqlite3.connect(migrated.path) as database:
        assert database.execute("PRAGMA user_version").fetchone()[0] == 8
        assert database.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='ix_materials_dataset'"
        ).fetchone()
