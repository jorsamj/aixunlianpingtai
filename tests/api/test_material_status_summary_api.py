from __future__ import annotations

import app as app_module
from platform_core.material_repository import MaterialRepository


def test_material_status_summary_is_a_read_only_endpoint_with_source_specific_badges(tmp_path, monkeypatch):
    repository = MaterialRepository(tmp_path / "project")
    repository.upsert_many([
        {"id": "local-1", "filename": "local.jpg", "processing_status": "pending_decision"},
        {"id": "remote-1", "filename": "remote.jpg", "storage_source_id": "oss-x",
         "object_key": "materials/remote.jpg",
         "processing_status": "processed", "annotated": True},
    ])
    seen = []
    monkeypatch.setattr(app_module, "get_project", lambda pid: seen.append(pid))
    monkeypatch.setattr(app_module, "material_store", lambda pid: repository)

    route = next(route for route in app_module.app.routes
                 if getattr(route, "path", "") == "/api/v61/projects/{project_id}/materials/status-counts")
    assert route.methods == {"GET"}
    before = repository.current_revision()
    result = app_module.material_status_counts_v61("project-1", storage_source_id=["oss-x"])
    assert result["total"] == 2
    assert result["unprocessed"] == 0
    assert result["processed"] == 1
    assert result["annotated"] == 1
    assert result["revision"] == before == repository.current_revision()
    assert seen == ["project-1"]
