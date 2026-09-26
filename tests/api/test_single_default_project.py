import json

import pytest
from fastapi import HTTPException

import app as app_module


CANONICAL_ID = "f1fb1e6fa373"


def _configure_single_project_data(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    projects_file = data_dir / "projects.json"
    data_dir.mkdir(parents=True)
    projects_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(app_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(app_module, "PROJECTS_FILE", projects_file)
    monkeypatch.setattr(app_module, "ALLOW_MULTIPLE_PROJECTS_FOR_TESTS", False)
    return data_dir, projects_file


def test_existing_default_project_rejects_second_creation(monkeypatch, tmp_path):
    _data_dir, projects_file = _configure_single_project_data(monkeypatch, tmp_path)

    first = app_module.create_project(app_module.ProjectCreate(name="ignored"))
    assert first["id"] == CANONICAL_ID
    assert first["name"] == "默认空间"

    with pytest.raises(HTTPException) as error:
        app_module.create_project(app_module.ProjectCreate(name="第二个空间"))

    assert error.value.status_code == 409
    assert [row["id"] for row in json.loads(projects_file.read_text(encoding="utf-8"))] == [CANONICAL_ID]


def test_runtime_project_list_and_preference_always_use_canonical(monkeypatch, tmp_path):
    _data_dir, projects_file = _configure_single_project_data(monkeypatch, tmp_path)
    canonical = {"id": CANONICAL_ID, "name": "默认空间", "labels": []}
    accidental = {"id": "182cac36f20d", "name": "默认空间", "labels": []}
    projects_file.write_text(
        json.dumps([canonical, accidental], ensure_ascii=False),
        encoding="utf-8",
    )

    assert app_module.list_projects() == [canonical]
    assert app_module._v53_choose_project([canonical, accidental], accidental["id"])["id"] == CANONICAL_ID


def test_default_project_cannot_be_deleted_or_renamed(monkeypatch, tmp_path):
    _configure_single_project_data(monkeypatch, tmp_path)
    app_module.create_project(app_module.ProjectCreate(name="默认空间"))

    with pytest.raises(HTTPException) as delete_error:
        app_module.delete_project(CANONICAL_ID)
    assert delete_error.value.status_code == 409

    with pytest.raises(HTTPException) as rename_error:
        app_module.update_project(CANONICAL_ID, app_module.ProjectUpdate(name="其他空间"))
    assert rename_error.value.status_code == 409
