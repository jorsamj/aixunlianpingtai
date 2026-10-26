import json
from pathlib import Path
import sqlite3

import pytest

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
from platform_core.storage.source_repository import StorageSourceRepository


def snapshot(path):
    with sqlite3.connect(path) as db:
        return {name: db.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
            for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}, db.execute("PRAGMA user_version").fetchone()[0]


def test_readonly_material_owner_preserves_genuine_schema5(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    path = project / "materials.sqlite3"
    ddl = Path(__file__).parents[1] / "fixtures/material_repository_schema5.sql"
    with sqlite3.connect(path) as db:
        db.executescript(ddl.read_text(encoding="utf-8"))
        MaterialRepository._write_row(db, {"id": "old", "filename": "old.png", "_dataset_delete_claim": {"token": "keep"}})
    (project / "images.json").write_text(json.dumps([{"id": "must-not-import", "filename": "shadow.png"}]))
    before = snapshot(path)
    owner = MaterialRepository.open_readonly(project)
    assert owner.get("old")["_dataset_delete_claim"] == {"token": "keep"}
    assert owner.get("must-not-import") is None
    with owner._connect() as db:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("DELETE FROM materials")
    assert snapshot(path) == before
    assert before[1] == 5


def test_readonly_annotation_and_storage_owners_do_not_initialize_or_write(tmp_path):
    project = tmp_path / "project"
    annotations = AnnotationRepository(project)
    sources = StorageSourceRepository(tmp_path / "storage.sqlite3")
    before_gt, before_sources = snapshot(annotations.path), snapshot(sources.path)
    read_gt = AnnotationRepository.open_readonly(project)
    read_sources = StorageSourceRepository.open_readonly(sources.path)
    assert read_gt.get("missing")["annotation_state"] == "unannotated"
    assert read_sources.get("default_local").id == "default_local"
    for owner, table in ((read_gt, "annotations"), (read_sources, "storage_sources")):
        with owner._connect() as db:
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                db.execute(f"DELETE FROM {table}")
    assert snapshot(annotations.path) == before_gt
    assert snapshot(sources.path) == before_sources


@pytest.mark.parametrize("owner", [MaterialRepository, AnnotationRepository, StorageSourceRepository])
def test_readonly_missing_registry_never_creates_directories(tmp_path, owner):
    with pytest.raises(sqlite3.OperationalError):
        owner.open_readonly(tmp_path / "missing/path")
    assert not list(tmp_path.iterdir())


def test_analysis_cache_reads_never_reclaim_unrelated_shared_files(tmp_path):
    import hashlib
    import os
    from platform_core.storage.cache import MaterialCache
    from platform_core.storage.models import ObjectMetadata

    class Provider:
        source_id = "fixture"
        def materialize_to_local(self, key, destination):
            Path(destination).write_bytes(b"new")
            return ObjectMetadata(key=key, size_bytes=3)

    cache = MaterialCache(tmp_path/"cache", max_bytes=1, ttl_seconds=1, recent_access_grace_seconds=0, allow_maintenance=False)
    old = cache.path_for(hashlib.sha256(b"old").hexdigest(), ".jpg")
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_bytes(b"old")
    os.utime(old, (1, 1))
    downloaded = cache.materialize(Provider(), "new.jpg", expected_sha256=hashlib.sha256(b"new").hexdigest(), suffix=".jpg")
    assert downloaded.path.read_bytes() == b"new"
    assert old.read_bytes() == b"old"
