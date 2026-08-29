from platform_core.materials import (
    initial_processing_status,
    mark_ready,
    processing_status_group,
)


def test_imported_annotation_is_processed():
    assert initial_processing_status(has_valid_boxes=True) == "processed"


def test_raw_upload_is_pending_decision():
    assert initial_processing_status(has_valid_boxes=False) == "pending_decision"


def test_pending_decision_and_legacy_unprocessed_share_unprocessed_group():
    assert processing_status_group("pending_decision") == "unprocessed"
    assert processing_status_group("unprocessed") == "unprocessed"
    assert processing_status_group("processed") == "processed"


def test_mark_ready_records_explicit_decision():
    result = mark_ready(
        {"id": "i1", "processing_status": "unprocessed"},
        "2026-08-28T10:00:00",
    )
    assert result["processing_status"] == "processed"
    assert result["clean_skipped"] is True
    assert result["clean_decision"] == "skipped"
    assert result["clean_decision_at"] == "2026-08-28T10:00:00"
