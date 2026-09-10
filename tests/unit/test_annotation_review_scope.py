import sys
import types
from dataclasses import replace
from pathlib import Path

from platform_core.annotation_task_service import _freeze_review_scope, _stable_scope_for_codes
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord


class ScopeContext:
    def __init__(self, tmp_path: Path):
        self.artifacts = ArtifactStore(tmp_path)
        self.task = replace(
            TaskRecord.new(
                "scope-task", "project-1", TaskKind.AI_ANNOTATION,
                "request.json", "vision:model-1",
            )
        )


def _fake_app(monkeypatch):
    fake = types.ModuleType("app")
    fake.get_project = lambda _project_id: {"id": "project-1"}
    fake.project_label_items = lambda _project: [
        {"code": "fire", "label_id": "lbl-fire", "status": "active"},
        {"code": "smoke", "label_id": "lbl-smoke", "status": "active"},
        {"code": "disabled", "label_id": "lbl-disabled", "status": "disabled"},
    ]
    monkeypatch.setitem(sys.modules, "app", fake)


def test_stable_scope_resolves_active_project_label_ids(monkeypatch):
    _fake_app(monkeypatch)
    assert _stable_scope_for_codes("project-1", ["fire", "smoke"]) == ["lbl-fire", "lbl-smoke"]


def test_freeze_review_scope_upgrades_legacy_catalog_without_label_ids(tmp_path, monkeypatch):
    _fake_app(monkeypatch)
    context = ScopeContext(tmp_path)

    label_ids = _freeze_review_scope(context, {
        "labels": ["fire", "smoke"],
        "label_catalog": [
            {"code": "fire", "class_id": 0},
            {"code": "smoke", "class_id": 1},
        ],
    })

    assert label_ids == ["lbl-fire", "lbl-smoke"]
    assert context.artifacts.read_json("scope-task", "review-scope.json") == {
        "schema_version": 1,
        "labels": ["fire", "smoke"],
        "label_ids": ["lbl-fire", "lbl-smoke"],
    }
