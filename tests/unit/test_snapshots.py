import pytest

from platform_core.snapshots import (
    build_snapshot,
    dataset_revision_document,
    ensure_dataset_revision,
    persist_dataset_revision,
)
from platform_core.training_splits import SplitMode, SplitRequest, build_split_manifest


def test_snapshot_contains_only_processed_images_and_is_deterministic():
    images = [
        {"id": "b", "processing_status": "processed", "labels": ["smoke"], "boxes": [{"label": "smoke"}]},
        {"id": "a", "processing_status": "processed", "labels": ["fire"], "boxes": [{"label": "fire"}]},
        {"id": "c", "processing_status": "unprocessed", "labels": [], "boxes": []},
    ]

    first = build_snapshot(images, ["a"], ["b"], [{"code": "fire"}, {"code": "smoke"}], seed=42)
    second = build_snapshot(images, ["a"], ["b"], [{"code": "fire"}, {"code": "smoke"}], seed=42)

    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["train_image_ids"] == ["a"]
    assert first["val_image_ids"] == ["b"]
    assert first["label_counts"] == {"fire": 1, "smoke": 1}
    assert first["images"][0]["annotation_state"] == "annotated"
    assert first["images"][0]["annotation_scope"] == ["fire"]


def test_unprocessed_selected_image_is_rejected():
    images = [{"id": "raw", "processing_status": "unprocessed", "labels": []}]

    try:
        build_snapshot(images, ["raw"], [], [{"code": "fire"}], seed=1)
    except ValueError as error:
        assert "未处理" in str(error)
    else:
        raise AssertionError("unprocessed training material must not enter a snapshot")


def test_v3_snapshot_contains_three_roles_provenance_content_hash_and_annotation_contract():
    images = []
    for index in range(6):
        images.append(
            {
                "id": str(index),
                "dataset_id": "pool",
                "processing_status": "processed",
                "stored_name": f"{index}.jpg",
                "source_type": "video_frame" if index < 2 else "upload",
                "video_task_id": "video-1" if index < 2 else "",
                "group_id": "video-1" if index < 2 else f"g{index}",
                "content_sha256": f"hash-{index}",
                "boxes": [{"label": "fire", "x1": 1, "y1": 1, "x2": 2, "y2": 2}],
            }
        )
    manifest = build_split_manifest(
        images,
        SplitRequest(
            mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
            train_image_ids=tuple(str(index) for index in range(6)),
            experiment_percent=20,
            validation_percent=20,
        ),
        seed=11,
    )
    first = build_snapshot(images, manifest, [{"code": "fire", "class_id": 0}])
    second = build_snapshot(images, manifest, [{"code": "fire", "class_id": 0}])
    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["schema_version"] == 3
    assert first["training_input_policy"] == "ultralytics_jpeg_repair_v1"
    assert set(first["ids"]) == {"train", "validation", "test"}
    assert first["counts"] == manifest.counts
    assert all(row["content_sha256"] for row in first["images"])
    assert all(row["role"] in {"train", "validation", "test"} for row in first["images"])
    assert all(row["annotation_state"] == "annotated" for row in first["images"])
    assert all(row["annotation_scope"] == ["fire"] for row in first["images"])

    changed = [dict(image) for image in images]
    changed[0]["content_sha256"] = "changed"
    with pytest.raises(ValueError, match="content hash"):
        build_snapshot(changed, manifest, [{"code": "fire", "class_id": 0}])


def test_confirmed_empty_scope_is_locked_in_snapshot():
    images = []
    for index in range(6):
        row = {
            "id": str(index),
            "dataset_id": "pool",
            "processing_status": "processed",
            "stored_name": f"{index}.jpg",
            "group_id": f"g{index}",
            "content_sha256": f"hash-{index}",
            "annotated": True,
            "annotation_state": "annotated",
            "annotation_scope": ["fire"],
            "boxes": [{"label": "fire", "x1": 1, "y1": 1, "x2": 2, "y2": 2}],
        }
        images.append(row)
    images[-1].update(
        annotation_state="confirmed_empty",
        annotation_scope=["fire"],
        boxes=[],
    )

    manifest = build_split_manifest(
        images,
        SplitRequest(
            mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
            train_image_ids=tuple(str(index) for index in range(6)),
            experiment_percent=20,
            validation_percent=20,
        ),
        seed=17,
    )
    snapshot = build_snapshot(images, manifest, [{"code": "fire", "class_id": 0}])
    negative = next(row for row in snapshot["images"] if row["image_id"] == "5")

    assert negative["annotation_state"] == "confirmed_empty"
    assert negative["annotation_scope"] == ["fire"]
    assert negative["box_count"] == 0
    assert snapshot["negative_scope_counts"] == {"fire": 1}


def test_snapshot_records_canonical_duplicate_exclusions():
    images = []
    for image_id, content_hash in (
        ("a", "same"),
        ("b", "same"),
        ("c", "hc"),
        ("d", "hd"),
        ("e", "he"),
        ("f", "hf"),
        ("g", "hg"),
    ):
        images.append(
            {
                "id": image_id,
                "dataset_id": "pool",
                "processing_status": "processed",
                "stored_name": f"{image_id}.jpg",
                "group_id": f"g-{image_id}",
                "content_sha256": content_hash,
                "annotated": True,
                "annotation_state": "annotated",
                "annotation_scope": ["fire"],
                "boxes": [{"label": "fire", "x1": 1, "y1": 1, "x2": 2, "y2": 2}],
            }
        )

    manifest = build_split_manifest(
        images,
        SplitRequest(
            mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
            train_image_ids=tuple(row["id"] for row in images),
            experiment_percent=20,
            validation_percent=20,
        ),
        seed=21,
    )
    snapshot = build_snapshot(images, manifest, [{"code": "fire", "class_id": 0}])

    assert snapshot["excluded_duplicate_ids"] == ["b"]
    assert snapshot["duplicate_groups"] == {"same": ["a", "b"]}
    assert snapshot["counts"]["total"] == 6


def _revision_images():
    images = []
    for index in range(8):
        annotation_hash = f"{index + 20:064x}"
        row = {
            "id": str(index),
            "dataset_id": "pool",
            "processing_status": "processed",
            "stored_name": f"{index}.jpg",
            "group_id": f"group-{index}",
            "content_sha256": f"{index + 1:064x}",
            "size_bytes": 100 + index,
            "storage_source_id": "s3-main",
            "storage_type": "s3",
            "object_key": f"images/{index}.jpg",
            "annotated": True,
            "annotation_state": "annotated",
            "annotation_scope": ["fire"],
            "annotation_hash": annotation_hash,
            "boxes": [{"label": "fire", "x1": 1, "y1": 1, "x2": 2, "y2": 2}],
        }
        if index == 0:
            row["external_annotation"] = {
                "schema_version": 1,
                "source_format": "yolo",
                "source_digest": "a" * 64,
                "annotation_status": "annotated",
                "split": "train",
                "label_key": "labels/0.txt",
                "dataset_key": "data.yaml",
                "synced_annotation_hash": annotation_hash,
            }
        images.append(row)
    return images


def test_dataset_revision_is_split_independent_but_snapshot_is_not():
    images = _revision_images()
    request = SplitRequest(
        mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
        train_image_ids=tuple(row["id"] for row in images),
        experiment_percent=25,
        validation_percent=25,
    )
    first_manifest = build_split_manifest(images, request, seed=11)
    second_manifest = build_split_manifest(images, request, seed=19)
    first = build_snapshot(images, first_manifest, [{"code": "fire", "class_id": 0}])
    second = build_snapshot(images, second_manifest, [{"code": "fire", "class_id": 0}])

    assert first["dataset_revision_schema_version"] == 1
    assert first["canonical_annotation_schema_version"] == 1
    assert first["dataset_revision_id"] == second["dataset_revision_id"]
    assert first["snapshot_id"] != second["snapshot_id"]
    provenance = next(
        row["external_annotation"]
        for row in first["images"]
        if row["image_id"] == "0"
    )
    assert provenance["source_format"] == "yolo"
    assert provenance["source_digest"] == "a" * 64
    assert provenance["platform_annotation_hash"] == f"{20:064x}"


def test_dataset_revision_changes_with_platform_or_external_annotation_truth():
    images = _revision_images()
    request = SplitRequest(
        mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
        train_image_ids=tuple(row["id"] for row in images),
        experiment_percent=25,
        validation_percent=25,
    )
    manifest = build_split_manifest(images, request, seed=7)
    original = build_snapshot(images, manifest, [{"code": "fire", "class_id": 0}])

    changed_external = [dict(row) for row in images]
    changed_external[0]["external_annotation"] = {
        **dict(images[0]["external_annotation"]),
        "source_digest": "b" * 64,
    }
    external_snapshot = build_snapshot(
        changed_external,
        manifest,
        [{"code": "fire", "class_id": 0}],
    )
    assert external_snapshot["dataset_revision_id"] != original["dataset_revision_id"]

    changed_platform = [dict(row) for row in images]
    changed_platform[1]["annotation_hash"] = "f" * 64
    platform_snapshot = build_snapshot(
        changed_platform,
        manifest,
        [{"code": "fire", "class_id": 0}],
    )
    assert platform_snapshot["dataset_revision_id"] != original["dataset_revision_id"]


def test_dataset_revision_document_and_persistence_are_immutable(tmp_path):
    images = _revision_images()
    manifest = build_split_manifest(
        images,
        SplitRequest(
            mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
            train_image_ids=tuple(row["id"] for row in images),
            experiment_percent=25,
            validation_percent=25,
        ),
        seed=13,
    )
    snapshot = build_snapshot(images, manifest, [{"code": "fire", "class_id": 0}])
    revision = dataset_revision_document(snapshot)
    path = persist_dataset_revision(tmp_path / "dataset_revisions", snapshot)

    assert revision["dataset_revision_id"] == snapshot["dataset_revision_id"]
    assert path.name == f"{snapshot['dataset_revision_id']}.json"
    assert persist_dataset_revision(tmp_path / "dataset_revisions", snapshot) == path

    tampered = dict(snapshot)
    tampered["dataset_revision_id"] = "0" * 64
    with pytest.raises(ValueError, match="dataset_revision_id"):
        dataset_revision_document(tampered)


def test_legacy_snapshot_gets_deterministic_revision_without_changing_snapshot_id():
    legacy = {
        "schema_version": 2,
        "snapshot_id": "legacy-snapshot",
        "label_schema": [],
        "images": [{"image_id": "a", "annotation_hash": "x"}],
    }
    first = ensure_dataset_revision(legacy)
    second = ensure_dataset_revision(legacy)

    assert first["snapshot_id"] == "legacy-snapshot"
    assert first["dataset_revision_id"] == second["dataset_revision_id"]
    assert len(first["dataset_revision_id"]) == 64
