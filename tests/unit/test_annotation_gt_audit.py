from platform_core.annotation_gt_audit import audit_gt_commit


TASK = "task-a"
JOURNAL = {"image_id": "image-a", "box_count": 2}
CANDIDATE = {"accepted": True, "boxes": [{"id": "box-1"}, {"id": "box-2"}]}


def _gt(*boxes, version=5, digest=""):
    return {
        "annotation_state": "annotated" if boxes else "confirmed_empty",
        "boxes": list(boxes), "version": version, "content_digest": digest,
    }


def _box(box_id, source=TASK):
    return {"candidate_id": box_id, "source_task_id": source}


def test_audit_requires_matching_task_and_candidate_provenance():
    retained = audit_gt_commit(TASK, JOURNAL, CANDIDATE, _gt(_box("box-1"), _box("box-2")))
    assert retained["state"] == "retained"
    assert retained["retained_task_boxes"] == 2
    partial = audit_gt_commit(TASK, JOURNAL, CANDIDATE, _gt(_box("box-1"), _box("box-2", "task-b")))
    assert partial["state"] == "partially_retained"
    missing = audit_gt_commit(TASK, JOURNAL, CANDIDATE, _gt(_box("box-1", "task-b")))
    assert missing["state"] == "not_retained"


def test_audit_does_not_invent_negative_or_legacy_snapshot_proof():
    negative = {"accepted": True, "boxes": []}
    current = _gt(version=3)
    assert audit_gt_commit(TASK, JOURNAL, negative, current)["state"] == "unverifiable"
    assert audit_gt_commit(TASK, JOURNAL, negative, None)["state"] == "not_retained"
    assert audit_gt_commit(TASK, JOURNAL, None, _gt(_box("any")))["state"] == "retained_unquantified"


def test_audit_future_snapshot_proves_same_revision_and_detects_changed_negative():
    journal = {
        **JOURNAL,
        "gt_write_performed": True,
        "gt_snapshot_version": 3,
        "gt_snapshot_digest": "a" * 64,
    }
    negative = {"accepted": True, "boxes": []}
    same = audit_gt_commit(TASK, journal, negative, _gt(version=3, digest="a" * 64))
    assert same["state"] == "same_revision" and same["snapshot_available"] is True
    changed = audit_gt_commit(TASK, journal, negative, _gt(version=4, digest="b" * 64))
    assert changed["state"] == "revision_changed_unverifiable"
    not_written = audit_gt_commit(TASK, {**journal, "gt_write_performed": False}, negative, _gt(version=3, digest="a" * 64))
    assert not_written["state"] == "unverifiable"
