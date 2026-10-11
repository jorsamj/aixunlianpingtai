from __future__ import annotations

import pytest

from platform_core.material_repository import MaterialRepository


def material(index: int) -> dict:
    image_id = f"image-{index:05d}"
    return {
        "id": image_id,
        "filename": f"{image_id}.jpg",
        "stored_name": f"{image_id}.jpg",
        "storage_source_id": "default_local",
        "storage_type": "local",
        "object_key": f"uploads/{image_id}.jpg",
        "processing_status": "processed",
        "labels": [],
        "created_at": f"2026-09-08T00:{index // 60:02d}:{index % 60:02d}+00:00",
    }


def test_get_many_supports_more_than_sqlite_parameter_limit(tmp_path):
    repository = MaterialRepository(tmp_path)
    rows = [material(index) for index in range(2200)]
    repository.upsert_many(rows)

    ids = [row["id"] for row in rows]
    fetched = repository.get_many(ids)

    assert [row["id"] for row in fetched] == ids


def test_remove_supports_large_id_sets_and_preserves_request_order(tmp_path):
    repository = MaterialRepository(tmp_path)
    rows = [material(index) for index in range(1800)]
    repository.upsert_many(rows)
    ids = [row["id"] for row in reversed(rows)]

    removed = repository.remove(ids)

    assert [row["id"] for row in removed] == ids
    assert repository.count() == 0


def test_legacy_mutate_chunks_large_deletions(tmp_path):
    repository = MaterialRepository(tmp_path)
    rows = [material(index) for index in range(1300)]
    repository.upsert_many(rows)

    deleted = repository.mutate(
        lambda current: current.__setitem__(slice(None), current[1200:]) or 1200
    )

    assert deleted == 1200
    assert repository.count() == 100


def test_cleaning_projection_fields_are_batch_mutable_but_unknown_fields_still_fail(tmp_path):
    repository = MaterialRepository(tmp_path)
    row = material(1)
    repository.upsert(row)

    changed = repository.patch_many(
        [row["id"]],
        {
            "processing_status": "processed",
            "cleaned_at": "2026-09-26T12:00:00Z",
            "clean_skipped": True,
            "clean_decision": "skipped",
            "clean_decision_at": "2026-09-26T12:00:00Z",
            "clean_task_id": "clean-task-1",
        },
    )

    assert changed == 1
    saved = repository.get(row["id"])
    assert saved["clean_task_id"] == "clean-task-1"
    assert saved["clean_skipped"] is True
    assert saved["clean_decision"] == "skipped"

    with pytest.raises(ValueError, match="material fields are not mutable"):
        repository.patch_many([row["id"]], {"unexpected_projection_field": True})
