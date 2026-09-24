import pytest

import app as app_module
from platform_core.material_repository import MaterialRepository


def _material(image_id, label_counts):
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
    }


def test_material_repository_aggregates_existing_label_usage(tmp_path):
    repository = MaterialRepository(tmp_path / "project")
    repository.upsert_many([
        _material("m1", {"smoke": 2}),
        _material("m2", {"smoke": 1, "fire": 4}),
        _material("m3", {}),
    ])

    assert repository.label_usage() == {
        "fire": {"images": 1, "boxes": 4},
        "smoke": {"images": 2, "boxes": 3},
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
