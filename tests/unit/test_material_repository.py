from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from platform_core.material_repository import MaterialRepository


def material(image_id: str, *, source: str = "default_local", labels=(), status="processed"):
    return {
        "id": image_id,
        "filename": f"{image_id}.jpg",
        "stored_name": f"{image_id}.jpg",
        "storage_source_id": source,
        "storage_type": "local" if source == "default_local" else "s3",
        "object_key": f"uploads/{image_id}.jpg" if source == "default_local" else f"materials/{image_id}.jpg",
        "width": 640,
        "height": 480,
        "processing_status": status,
        "labels": list(labels),
        "box_count": len(labels),
        "created_at": f"2026-09-07T00:00:{int(image_id[-1], 16):02d}+00:00",
    }


def test_crud_and_revision_use_sqlite_rows(tmp_path):
    repository = MaterialRepository(tmp_path)
    assert repository.journal_mode() == "wal"
    assert repository.read().rows == []

    first = repository.upsert(material("image-1", labels=("fire",)))
    assert first["id"] == "image-1"
    before = repository.read().revision
    repository.patch({"image-1": {"processing_status": "cleaning", "labels": ["fire", "smoke"]}})
    assert repository.get("image-1")["processing_status"] == "cleaning"
    assert repository.get("image-1")["labels"] == ["fire", "smoke"]
    assert repository.read().revision > before

    removed = repository.remove(["image-1"])
    assert [row["id"] for row in removed] == ["image-1"]
    assert repository.count() == 0


def test_paginated_filters_and_multi_label_or(tmp_path):
    repository = MaterialRepository(tmp_path)
    repository.upsert_many([
        material("image-1", source="default_local", labels=("fire",)),
        material("image-2", source="oss-a", labels=("smoke",)),
        material("image-3", source="oss-a", labels=("helmet",), status="pending_decision"),
        material("image-4", source="s3-a", labels=("person",)),
    ])

    first = repository.list_page(limit=2)
    assert len(first.items) == 2
    assert first.next_cursor
    second = repository.list_page(limit=2, cursor=first.next_cursor)
    assert {row["id"] for row in first.items + second.items} == {
        "image-1", "image-2", "image-3", "image-4"
    }

    by_source = repository.list_page(storage_source_ids=["oss-a"], limit=20)
    assert {row["id"] for row in by_source.items} == {"image-2", "image-3"}
    by_status = repository.list_page(processing_status="pending_decision", limit=20)
    assert [row["id"] for row in by_status.items] == ["image-3"]
    by_name = repository.list_page(query="IMAGE-4", limit=20)
    assert [row["id"] for row in by_name.items] == ["image-4"]

    any_label = repository.list_page(labels=["fire", "smoke"], limit=20)
    assert {row["id"] for row in any_label.items} == {"image-1", "image-2"}
    assert repository.count(labels=["fire", "smoke"]) == 2


def test_reference_count_and_id_only_page(tmp_path):
    repository = MaterialRepository(tmp_path)
    repository.upsert_many([
        material("image-1", source="oss-a", labels=("fire",)),
        material("image-2", source="oss-a", labels=("smoke",)),
        material("image-3", source="s3-a", labels=("fire",)),
    ])
    assert repository.reference_count("oss-a") == 2
    page = repository.list_ids(labels=["fire"], limit=10)
    assert set(page.items) == {"image-1", "image-3"}


def test_legacy_external_rows_get_collision_safe_working_name(tmp_path):
    repository = MaterialRepository(tmp_path)
    legacy = {
        "id": "remote-legacy-1",
        "filename": "camera.jpg",
        "stored_name": "",
        "storage_source_id": "oss-a",
        "storage_type": "oss",
        "object_key": "archive/2026/camera.jpg",
        "content_sha256": "a" * 64,
        "labels": [],
    }
    persisted = repository.upsert(legacy)
    assert persisted["stored_name"] == "remote-legacy-1.jpg"
    assert repository.get("remote-legacy-1")["stored_name"] == "remote-legacy-1.jpg"
    assert repository.get("remote-legacy-1")["object_key"] == "archive/2026/camera.jpg"

    # Simulate a row persisted by an older build where payload_json still had stored_name="".
    with repository._connect() as database:
        payload = dict(legacy)
        database.execute(
            "UPDATE materials SET payload_json = ? WHERE id = ?",
            (__import__("json").dumps(payload), "remote-legacy-1"),
        )
    recovered = repository.get("remote-legacy-1")
    assert recovered["stored_name"] == "remote-legacy-1.jpg"
    assert recovered["object_key"] == "archive/2026/camera.jpg"


def test_concurrent_readers_observe_committed_batches(tmp_path):
    repository = MaterialRepository(tmp_path)

    def write_batch(batch: int):
        repository.upsert_many([material(f"batch-{batch}-{index}") for index in range(5)])

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write_batch, range(8)))
    with ThreadPoolExecutor(max_workers=8) as pool:
        counts = list(pool.map(lambda _index: repository.count(), range(16)))
    assert counts == [40] * 16


def test_compatibility_mutate_remains_atomic(tmp_path):
    repository = MaterialRepository(tmp_path)
    repository.upsert_many([material("image-1"), material("image-2")])

    changed = repository.mutate(
        lambda rows: [row.update({"processing_status": "processed"}) or row["id"] for row in rows]
    )

    assert changed == ["image-1", "image-2"]
    assert repository.count(processing_status="processed") == 2
