import json

from starlette.responses import Response

import app as app_module


def test_material_list_is_pre_serialized_without_changing_json(monkeypatch):
    rows = [
        {
            "id": "image-1",
            "filename": "测试图片.jpg",
            "box_count": 1,
            "labels": ["helmet"],
            "annotation_preview": [{"label": "helmet", "x1": 1, "y1": 2}],
            "size_bytes": 12,
            "split": "train",
            "processing_status": "processed",
            "annotation_summary_at": "2026-08-30T00:00:00Z",
        }
    ]
    monkeypatch.setattr(app_module, "get_project", lambda _project_id: {"id": "project-1"})
    monkeypatch.setattr(app_module, "load_images", lambda _project_id: rows)

    response = app_module.list_images("project-1")

    assert isinstance(response, Response)
    assert response.media_type == "application/json"
    assert json.loads(response.body) == rows


def test_bootstrap_snapshot_is_pre_serialized_without_changing_json(monkeypatch):
    snapshot = {"project": {"id": "project-1"}, "images": [{"id": "image-1"}]}
    monkeypatch.setattr(app_module, "_V53_BOOTSTRAP_STATUS", {"status": "ready"})
    monkeypatch.setattr(app_module, "_V53_BOOTSTRAP_SNAPSHOT", snapshot)
    monkeypatch.setattr(app_module, "read_json", lambda *_args, **_kwargs: [{"id": "project-1"}])
    monkeypatch.setattr(app_module, "_v53_project_counts", lambda _project: {"images": 1})
    monkeypatch.setattr(app_module, "_v53_choose_project", lambda projects, _preferred: projects[0])

    response = app_module.v53_bootstrap_snapshot("")

    assert isinstance(response, Response)
    payload = json.loads(response.body)
    assert payload["ok"] is True
    assert payload["bootstrap"] == {"status": "ready"}
    assert payload["project"] == snapshot["project"]
    assert payload["images"] == snapshot["images"]
