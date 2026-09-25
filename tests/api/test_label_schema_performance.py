import pytest

import app as app_module
from platform_core.material_repository import MaterialRepository


def _material(image_id, label_counts, annotation_scope=None):
    scope = list(annotation_scope or [])
    return {
        "id": image_id,
        "filename": f"{image_id}.jpg",
        "stored_name": f"{image_id}.jpg",
        "object_key": f"uploads/{image_id}.jpg",
        "processing_status": "processed",
        "box_count": sum(label_counts.values()),
        "annotated": bool(label_counts),
        "labels": list(label_counts),
        "label_counts": label_counts,
        "annotation_scope": scope,
        "annotation_state": "confirmed_empty" if scope and not label_counts else ("annotated" if label_counts else "unannotated"),
    }


def test_material_repository_aggregates_existing_label_usage(tmp_path):
    repository = MaterialRepository(tmp_path / "project")
    repository.upsert_many([
        _material("m1", {"smoke": 2}),
        _material("m2", {"smoke": 1, "fire": 4}, ["smoke", "fire"]),
        _material("m3", {}),
    ])

    assert repository.label_usage() == {
        "fire": {"images": 1, "boxes": 4},
        "smoke": {"images": 2, "boxes": 3},
    }
    # Positive annotation scope is not a negative-sample reference and must not
    # be double-counted by the dedicated confirmed-empty scope index.
    assert repository.label_reference_usage() == {
        "fire": {"positive_images": 1, "scope_images": 0, "affected_images": 1},
        "smoke": {"positive_images": 2, "scope_images": 0, "affected_images": 2},
    }
    repository.upsert_many([
        _material("n1", {}, ["smoke"]),
        _material("n2", {}, ["smoke", "fire"]),
    ])
    assert repository.label_reference_usage() == {
        "fire": {"positive_images": 1, "scope_images": 1, "affected_images": 2},
        "smoke": {"positive_images": 2, "scope_images": 2, "affected_images": 4},
    }


def test_label_schema_get_uses_existing_material_index_without_annotation_io(tmp_path, monkeypatch):
    repository = MaterialRepository(tmp_path / "project")
    repository.upsert_many([
        _material("m1", {"smoke": 2}),
        _material("m2", {"smoke": 1}),
    ])
    project = {
        "id": "p1",
        "labels": ["smoke"],
        "label_meta": [{"display_name": "烟雾", "enabled": True}],
    }
    monkeypatch.setattr(app_module, "get_project", lambda _project_id: project)
    monkeypatch.setattr(app_module, "material_store", lambda _project_id: repository)
    monkeypatch.setattr(
        app_module,
        "load_images",
        lambda *_args, **_kwargs: pytest.fail("ordinary label schema GET scanned all materials"),
    )
    monkeypatch.setattr(
        app_module,
        "read_annotation",
        lambda *_args, **_kwargs: pytest.fail("ordinary label schema GET read annotations"),
    )

    result = app_module.v54_label_schema("p1")

    smoke = next(item for item in result["items"] if item["code"] == "smoke")
    assert smoke["usage_images"] == 2
    assert smoke["usage_boxes"] == 3
    assert smoke["scope_images"] == 0
    assert smoke["affected_images"] == 2
