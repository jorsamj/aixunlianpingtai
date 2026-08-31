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


def test_unprocessed_selected_image_is_rejected():
    images = [{"id": "raw", "processing_status": "unprocessed", "labels": []}]

    try:
        build_snapshot(images, ["raw"], [], [{"code": "fire"}], seed=1)
    except ValueError as error:
        assert "未处理" in str(error)
    else:
        raise AssertionError("unprocessed training material must not enter a snapshot")


def test_v2_snapshot_contains_three_roles_provenance_and_content_hash():
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
            train_dataset_ids=("pool",),
            experiment_percent=20,
            validation_percent=20,
        ),
        seed=11,
    )
    first = build_snapshot(images, manifest, [{"code": "fire", "class_id": 0}])
    second = build_snapshot(images, manifest, [{"code": "fire", "class_id": 0}])
    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["schema_version"] == 2
    assert set(first["ids"]) == {"train", "validation", "test"}
    assert first["counts"] == manifest.counts
    assert all(row["content_sha256"] for row in first["images"])
    assert all(row["role"] in {"train", "validation", "test"} for row in first["images"])

    changed = [dict(image) for image in images]
    changed[0]["content_sha256"] = "changed"
    with pytest.raises(ValueError, match="content hash"):
        build_snapshot(changed, manifest, [{"code": "fire", "class_id": 0}])
