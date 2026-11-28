"""Read-only, per-page comparison of AI commit journals with canonical formal GT.

This is deliberately not a second GT store or a claim about the whole task:
only an explicitly requested bounded page is inspected. Historical journals
may lack a formal revision identity; such negatives cannot be proved current.
"""

from __future__ import annotations

import re
from typing import Any

from .annotation_task_service import _candidate_id


def audit_gt_commit(
    task_id: str,
    journal: dict[str, Any],
    candidate: dict[str, Any] | None,
    formal: dict[str, Any] | None,
) -> dict[str, Any]:
    image_id = str(journal["image_id"])
    formal_absent = not formal or (
        int(formal.get("version") or 0) == 0
        and str(formal.get("annotation_state") or "") == "unannotated"
        and not formal.get("boxes")
    )
    formal = formal or {}
    current_boxes = list(formal.get("boxes") or [])
    owned_ids = {
        str(box.get("candidate_id") or "")
        for box in current_boxes
        if str(box.get("source_task_id") or "") == task_id
        and str(box.get("candidate_id") or "")
    }
    expected_ids = {
        _candidate_id(image_id, box)
        for box in (candidate or {}).get("boxes") or []
    } if candidate and candidate.get("accepted") is True else set()
    matched = len(owned_ids & expected_ids)
    current_version = int(formal.get("version") or 0)
    expected_version = journal.get("gt_snapshot_version")
    expected_digest = str(journal.get("gt_snapshot_digest") or "")
    snapshot_valid = (
        journal.get("gt_write_performed") is True
        and type(expected_version) is int and expected_version > 0
        and bool(re.fullmatch(r"[0-9a-f]{64}", expected_digest))
    )
    same_revision = (
        snapshot_valid and current_version == expected_version
        and str(formal.get("content_digest") or "") == expected_digest
    )
    if same_revision:
        state = "same_revision"
    elif expected_ids and matched == len(expected_ids):
        state = "retained"
    elif expected_ids and matched:
        state = "partially_retained"
    elif expected_ids or formal_absent:
        state = "not_retained"
    elif owned_ids:
        state = "retained_unquantified"
    elif snapshot_valid:
        state = "revision_changed_unverifiable"
    else:
        state = "unverifiable"
    return {
        "image_id": image_id,
        "state": state,
        "journal_box_count": int(journal.get("box_count") or 0),
        "expected_task_boxes": len(expected_ids) if candidate and candidate.get("accepted") is True else None,
        "retained_task_boxes": matched if expected_ids else len(owned_ids),
        "current_gt_version": current_version,
        "snapshot_available": snapshot_valid,
    }
