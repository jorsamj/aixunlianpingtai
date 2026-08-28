from typing import Any, Mapping


def initial_processing_status(has_valid_boxes: bool) -> str:
    return "processed" if has_valid_boxes else "unprocessed"


def mark_ready(material: Mapping[str, Any], decided_at: str) -> dict:
    updated = dict(material)
    updated.update(
        {
            "processing_status": "processed",
            "clean_skipped": True,
            "clean_decision": "skipped",
            "clean_decision_at": decided_at,
            "updated_at": decided_at,
        }
    )
    return updated

