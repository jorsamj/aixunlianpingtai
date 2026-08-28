from platform_core.quality import compute_quality


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
