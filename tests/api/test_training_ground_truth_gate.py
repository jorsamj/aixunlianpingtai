import pytest

from platform_core.snapshots import build_snapshot
from platform_core.training_splits import SplitManifest, SplitMode, _processed


CONTENT_SHA = "a" * 64


def _manifest(image_id: str) -> SplitManifest:
    return SplitManifest(
        mode=SplitMode.INDEPENDENT_TEST_SET,
        ids={"train": (image_id,), "validation": (), "test": ()},
        counts={"train": 1, "validation": 0, "test": 0, "total": 1},
        requested={},
        actual_ratios={},
        groups={image_id: image_id},
        content_hashes={image_id: CONTENT_SHA},
        test_seed=0,
        validation_seed=0,
    )


def test_cleaned_unannotated_material_is_not_training_ground_truth():
    row = {
        "id": "cleaned-unannotated",
        "annotation_state": "unannotated",
        "annotated": False,
        "boxes": [],
        "processing_status": "processed",
        "cleaned_at": "2026-09-28T00:00:00Z",
        "clean_skipped": True,
        "content_sha256": CONTENT_SHA,
    }

    assert _processed(row) is False
    with pytest.raises(ValueError, match="正式标注 Ground Truth"):
        build_snapshot(
            [row],
            _manifest(row["id"]),
            [{"code": "smoke", "class_id": 0}],
        )


def test_confirmed_empty_remains_an_explicit_training_negative():
    row = {
        "id": "confirmed-empty",
        "annotation_state": "confirmed_empty",
        "annotation_scope": ["*"],
        "annotated": True,
        "boxes": [],
        "processing_status": "processed",
        "content_sha256": CONTENT_SHA,
    }

    assert _processed(row) is True
    snapshot = build_snapshot(
        [row],
        _manifest(row["id"]),
        [{"code": "smoke", "class_id": 0}],
    )

    frozen = snapshot["images"][0]
    assert frozen["annotation_state"] == "confirmed_empty"
    assert frozen["annotation_scope"] == ["smoke"]
    assert frozen["box_count"] == 0


def test_training_label_schema_compacts_active_classes_without_losing_canonical_id(tmp_path):
    import json

    from platform_core.training_tasks import _label_schema

    (tmp_path / "meta.json").write_text(
        json.dumps(
            {
                "label_meta": [
                    {"code": "retired", "status": "inactive", "class_id": 0},
                    {"code": "smoke", "status": "active", "class_id": 1},
                    {"code": "fire", "status": "active", "class_id": 7},
                ]
            }
        ),
        encoding="utf-8",
    )

    schema = _label_schema(tmp_path)

    assert [row["code"] for row in schema] == ["smoke", "fire"]
    assert [row["class_id"] for row in schema] == [0, 1]
    assert [row["canonical_project_class_id"] for row in schema] == [1, 7]
