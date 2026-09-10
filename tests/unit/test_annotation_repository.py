import json

import pytest

from platform_core.annotation_repository import AnnotationRepository


def _write_schema(project_path):
    (project_path / "meta.json").write_text(
        json.dumps(
            {
                "labels": ["fire", "smoke"],
                "label_meta": [
                    {"code": "fire", "label_id": "lbl_fire", "status": "active"},
                    {"code": "smoke", "label_id": "lbl_smoke", "status": "active"},
                ],
            }
        ),
        encoding="utf-8",
    )


def test_empty_boxes_default_to_unannotated(tmp_path):
    repository = AnnotationRepository(tmp_path)

    saved = repository.upsert("image-a", [])

    assert saved["annotation_state"] == "unannotated"
    assert saved["annotation_scope"] == []


def test_confirmed_empty_requires_explicit_state_and_scope(tmp_path):
    repository = AnnotationRepository(tmp_path)

    saved = repository.upsert(
        "image-b",
        [],
        annotation_state="confirmed_empty",
        annotation_scope=["lbl_fire"],
    )

    assert saved["annotation_state"] == "confirmed_empty"
    assert saved["annotation_scope"] == ["lbl_fire"]
    assert saved["confirmed_empty_scope"] == ["lbl_fire"]


def test_stable_label_id_overrides_stale_code_and_class_projection(tmp_path):
    _write_schema(tmp_path)
    repository = AnnotationRepository(tmp_path)

    saved = repository.upsert(
        "image-c",
        [
            {
                "id": "box-1",
                "label_id": "lbl_fire",
                "label": "smoke",
                "class_id": 1,
                "x1": 1,
                "y1": 2,
                "x2": 30,
                "y2": 40,
            }
        ],
        annotation_state="annotated",
        annotation_scope=["lbl_fire"],
    )

    assert saved["boxes"][0]["label_id"] == "lbl_fire"
    assert saved["boxes"][0]["label"] == "fire"
    assert saved["boxes"][0]["class_id"] == 0
    assert saved["annotation_scope"] == ["lbl_fire"]


def test_legacy_code_is_upgraded_to_stable_label_id_on_write(tmp_path):
    _write_schema(tmp_path)
    repository = AnnotationRepository(tmp_path)

    saved = repository.upsert(
        "image-d",
        [
            {
                "id": "box-1",
                "label": "smoke",
                "class_id": 0,
                "x1": 1,
                "y1": 2,
                "x2": 30,
                "y2": 40,
            }
        ],
        annotation_state="annotated",
        annotation_scope=["lbl_smoke"],
    )

    assert saved["boxes"][0]["label_id"] == "lbl_smoke"
    assert saved["boxes"][0]["label"] == "smoke"
    assert saved["boxes"][0]["class_id"] == 1


def test_unknown_stable_label_id_is_rejected_when_project_schema_exists(tmp_path):
    _write_schema(tmp_path)
    repository = AnnotationRepository(tmp_path)

    with pytest.raises(ValueError, match="unknown stable label_id"):
        repository.upsert(
            "image-e",
            [
                {
                    "label_id": "lbl_unknown",
                    "label": "fire",
                    "x1": 1,
                    "y1": 2,
                    "x2": 30,
                    "y2": 40,
                }
            ],
            annotation_state="annotated",
            annotation_scope=["lbl_fire"],
        )


def test_unknown_annotation_scope_is_rejected_when_project_schema_exists(tmp_path):
    _write_schema(tmp_path)
    repository = AnnotationRepository(tmp_path)

    with pytest.raises(ValueError, match="annotation scope references unknown"):
        repository.upsert(
            "image-f",
            [],
            annotation_state="confirmed_empty",
            annotation_scope=["lbl_unknown"],
        )
