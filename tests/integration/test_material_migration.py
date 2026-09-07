from __future__ import annotations

import hashlib
import json

from platform_core.material_repository import MaterialRepository


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_legacy_json_is_imported_once_without_moving_or_modifying_files(tmp_path):
    project = tmp_path / "project"
    uploads = project / "uploads"
    uploads.mkdir(parents=True)
    image_path = uploads / "abc.jpg"
    image_path.write_bytes(b"real-existing-image-bytes")
    legacy = project / "images.json"
    legacy.write_text(json.dumps([{
        "id": "abc", "filename": "原图.jpg", "stored_name": "abc.jpg",
        "width": 12, "height": 8, "labels": ["fire"], "processing_status": "processed",
    }], ensure_ascii=False), encoding="utf-8")
    json_hash = digest(legacy)
    image_hash = digest(image_path)

    first = MaterialRepository(project)
    row = first.get("abc")
    assert row["storage_source_id"] == "default_local"
    assert row["storage_type"] == "local"
    assert row["object_key"] == "uploads/abc.jpg"
    assert digest(legacy) == json_hash
    assert digest(image_path) == image_hash
    assert image_path.is_file()

    second = MaterialRepository(project)
    assert second.count() == 1
    assert digest(legacy) == json_hash


def test_empty_sqlite_repository_can_accept_new_remote_index_without_legacy_json(tmp_path):
    repository = MaterialRepository(tmp_path / "project")
    repository.upsert({
        "id": "remote-1", "filename": "outside.jpg", "storage_source_id": "oss-a",
        "storage_type": "oss", "object_key": "existing/outside.jpg", "labels": [],
        "size_bytes": 123, "content_sha256": "a" * 64,
    })
    assert repository.get("remote-1")["object_key"] == "existing/outside.jpg"
    assert not (tmp_path / "project" / "uploads" / "outside.jpg").exists()
    assert not (tmp_path / "project" / "images.json").exists()
