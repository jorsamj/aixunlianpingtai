from platform_core.snapshots import build_snapshot


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
