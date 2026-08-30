import app as app_module


def test_label_schema_uses_material_summaries_without_opening_annotation_files(monkeypatch):
    project = {
        "id": "project-1",
        "labels": ["fire", "smoke"],
        "label_meta": [
            {"display_name": "明火", "status": "active"},
            {"display_name": "烟雾", "status": "active"},
        ],
    }
    rows = [
        {"id": "one", "labels": ["fire"], "label_counts": {"fire": 2}},
        {"id": "two", "labels": ["fire", "smoke"], "label_counts": {"fire": 1, "smoke": 3}},
    ]
    monkeypatch.setattr(app_module, "get_project", lambda _project_id: project)
    monkeypatch.setattr(app_module, "load_images", lambda _project_id: rows)
    monkeypatch.setattr(
        app_module,
        "read_annotation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not scan annotation files")),
    )

    result = app_module.v54_label_schema("project-1")

    assert [(item["code"], item["usage_images"], item["usage_boxes"]) for item in result["items"]] == [
        ("fire", 2, 3),
        ("smoke", 1, 3),
    ]
