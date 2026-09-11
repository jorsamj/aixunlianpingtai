import pytest

from platform_core.snapshots import build_snapshot
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
