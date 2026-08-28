from platform_core.materials import initial_processing_status, mark_ready


def test_imported_annotation_is_processed():
    assert initial_processing_status(has_valid_boxes=True) == "processed"


def test_raw_upload_is_unprocessed():
    assert initial_processing_status(has_valid_boxes=False) == "unprocessed"


def test_mark_ready_records_explicit_decision():
    result = mark_ready(
        {"id": "i1", "processing_status": "unprocessed"},
        "2026-08-28T10:00:00",
    )
    assert result["processing_status"] == "processed"
    assert result["clean_skipped"] is True

