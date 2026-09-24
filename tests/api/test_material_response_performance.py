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
    monkeypatch.setattr(
        app_module,
        "_v53_project_counts",
        lambda _project: (_ for _ in ()).throw(AssertionError("cached snapshot must not recalculate project counts")),
    )
    monkeypatch.setattr(app_module, "_v53_choose_project", lambda projects, _preferred: projects[0])

    response = app_module.v53_bootstrap_snapshot("")

    assert isinstance(response, Response)
    payload = json.loads(response.body)
    assert payload["ok"] is True
    assert payload["bootstrap"] == {"status": "ready"}
    assert payload["project"] == snapshot["project"]
    assert payload["images"] == snapshot["images"]


def test_refreshed_bootstrap_counts_each_project_once_and_replaces_cache(monkeypatch):
    projects = [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]
    calls = []
    monkeypatch.setattr(app_module, "_V53_BOOTSTRAP_STATUS", {"status": "ready"})
    monkeypatch.setattr(app_module, "_V53_BOOTSTRAP_SNAPSHOT", {"project": {"id": "p1"}})
    monkeypatch.setattr(app_module, "read_json", lambda *_args, **_kwargs: projects)
    monkeypatch.setattr(
        app_module,
        "_v53_project_counts",
        lambda project: calls.append(project["id"]) or {
            "images": 1, "algorithms": 2, "versions": 3, "jobs": 4,
        },
    )
    monkeypatch.setattr(
        app_module,
        "_v53_build_snapshot",
        lambda project_id: {"project": {"id": project_id}, "generated_at": "fresh"},
    )

    response = app_module.v53_bootstrap_snapshot("p2", refresh=True)
    payload = json.loads(response.body)

    assert calls == ["p1", "p2", "p3"]
    assert payload["project"]["id"] == "p2"
    assert [row["bootstrap_counts"]["jobs"] for row in payload["projects"]] == [4, 4, 4]
    assert app_module._V53_BOOTSTRAP_SNAPSHOT["project"]["id"] == "p2"
