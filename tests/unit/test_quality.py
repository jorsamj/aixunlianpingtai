from platform_core.quality import compute_quality


def test_frozen_distribution_uses_snapshot_labels_and_does_not_invent_missing_image_counts():
    from platform_core.quality import frozen_data_quality
    snapshot={"snapshot_id":"frozen","label_counts":{"helmet":2},"images":[
        {"image_id":"a","role":"train","annotation_state":"annotated","labels":["helmet"],"content_sha256":"same"},
        {"image_id":"b","role":"test","annotation_state":"confirmed_empty","labels":[],"content_sha256":"same"}]}
    result=frozen_data_quality(snapshot)
    assert result["classes"] == [{"label":"helmet","image_count":1,"box_count":2}]
    assert result["duplicate_count"] == 1
    assert result["annotation_states"]["confirmed_empty"] == 1
    assert result["object_size_distribution"] is None
    snapshot["images"]=[{"image_id":"a"}]
    assert frozen_data_quality(snapshot)["classes"][0]["image_count"] is None


def test_quality_reports_label_imbalance_and_low_resolution():
    rows = [
        {"id": "a", "width": 1280, "height": 720, "boxes": [{"label": "fire"}, {"label": "fire"}]},
        {"id": "b", "width": 320, "height": 240, "boxes": [{"label": "smoke"}]},
    ]

    result = compute_quality(rows, min_width=640, min_height=480)

    assert result["label_counts"] == {"fire": 2, "smoke": 1}
    assert result["low_resolution"] == 1
    assert len(result["radar"]) == 6
    assert any("smoke" in item for item in result["suggestions"])
    assert sum(result["weights"].values()) == 1.0
