from __future__ import annotations

import json
from pathlib import Path

import pytest

from platform_core.annotation_repository import AnnotationRepository
from platform_core.training_label_tasks import (
    _LABEL_CONTRACT,
    _scoped_selected_project_images,
    resolve_training_label_contract,
    selected_material_label_codes,
)


def _project(tmp_path: Path) -> tuple[Path, Path]:
    data_dir = tmp_path / "data"
    project = data_dir / "projects" / "p1"
    project.mkdir(parents=True)
    (project / "meta.json").write_text(
        json.dumps(
            {
                "label_meta": [
                    {"code": "fire", "display_name_zh": "明火", "class_id": 0, "active": True},
                    {"code": "smoke", "display_name_zh": "烟雾", "class_id": 1, "active": True},
                    {"code": "person", "display_name_zh": "人员", "class_id": 2, "active": True},
                    {"code": "helmet", "display_name_zh": "安全帽", "class_id": 3, "active": True},
                    {"code": "cigarette", "display_name_zh": "香烟", "class_id": 4, "active": True},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return data_dir, project


def _box(label: str) -> dict:
    return {"label": label, "x1": 1, "y1": 1, "x2": 20, "y2": 20}


def test_first_training_uses_only_user_selected_material_labels(tmp_path: Path):
    data_dir, project = _project(tmp_path)
    annotations = AnnotationRepository(project)
    annotations.upsert("a", [_box("fire"), _box("person")], annotation_state="annotated")
    annotations.upsert("b", [_box("smoke")], annotation_state="annotated")

    payload = {
        "model": "yolo11n.pt",  # Mother model may internally know COCO; contract must ignore it.
        "train_image_ids": ["a", "b"],
        "train_labels": ["smoke", "fire"],
    }
    algorithm = {"id": "alg", "versions": []}

    contract = resolve_training_label_contract(data_dir, project, payload, algorithm)

    assert contract["available_material_label_codes"] == ["fire", "smoke", "person"]
    assert contract["requested_label_codes"] == ["smoke", "fire"]
    assert contract["inherited_label_codes"] == []
    assert contract["effective_label_codes"] == ["smoke", "fire"]
    assert [item["class_id"] for item in contract["effective_label_schema"]] == [0, 1]
    assert contract["mother_model_labels_inherited"] is False
    assert "person" not in contract["effective_label_codes"]
    assert "helmet" not in contract["effective_label_codes"]


def test_first_training_requires_explicit_label_choice(tmp_path: Path):
    data_dir, project = _project(tmp_path)
    AnnotationRepository(project).upsert("a", [_box("fire")], annotation_state="annotated")
    with pytest.raises(ValueError, match="首次训练必须"):
        resolve_training_label_contract(
            data_dir,
            project,
            {"model": "yolo11n.pt", "train_image_ids": ["a"], "train_labels": []},
            {"id": "alg", "versions": []},
        )


def test_requested_label_must_exist_in_selected_materials(tmp_path: Path):
    data_dir, project = _project(tmp_path)
    AnnotationRepository(project).upsert("a", [_box("fire")], annotation_state="annotated")
    with pytest.raises(ValueError, match="不在已选素材"):
        resolve_training_label_contract(
            data_dir,
            project,
            {"model": "yolo11n.pt", "train_image_ids": ["a"], "train_labels": ["helmet"]},
            {"id": "alg", "versions": []},
        )


def test_iteration_inherits_previous_schema_and_appends_new_label(tmp_path: Path):
    data_dir, project = _project(tmp_path)
    AnnotationRepository(project).upsert("a", [_box("cigarette")], annotation_state="annotated")
    model = project / "previous.pt"
    model.write_bytes(b"model")
    algorithm = {
        "id": "alg",
        "versions": [
            {
                "id": "v1",
                "version_name": "20260910010101",
                "created_at": "2026-09-10T01:01:01+00:00",
                "stored_path": str(model),
                "training_status": "SUCCEEDED",
                "artifact_verified": True,
                "trainable": True,
                "framework": "ultralytics",
                "label_schema": [
                    {"code": "fire", "class_id": 0},
                    {"code": "smoke", "class_id": 1},
                ],
            }
        ],
    }
    contract = resolve_training_label_contract(
        data_dir,
        project,
        {"model": "yolo11n.pt", "train_image_ids": ["a"], "train_labels": ["cigarette"]},
        algorithm,
    )
    assert contract["inherited_label_codes"] == ["fire", "smoke"]
    assert contract["effective_label_codes"] == ["fire", "smoke", "cigarette"]
    assert [item["class_id"] for item in contract["effective_label_schema"]] == [0, 1, 2]
    assert contract["base_version_id"] == "v1"


def test_iteration_can_continue_with_inherited_labels_without_adding_new_labels(tmp_path: Path):
    data_dir, project = _project(tmp_path)
    AnnotationRepository(project).upsert("a", [_box("fire")], annotation_state="annotated")
    model = project / "previous.pt"
    model.write_bytes(b"model")
    algorithm = {
        "id": "alg",
        "versions": [{
            "id": "v1",
            "created_at": "2026-09-10T01:01:01+00:00",
            "stored_path": str(model),
            "training_status": "SUCCEEDED",
            "artifact_verified": True,
            "trainable": True,
            "framework": "ultralytics",
            "label_schema": [{"code": "fire", "class_id": 0}, {"code": "smoke", "class_id": 1}],
        }],
    }
    contract = resolve_training_label_contract(
        data_dir,
        project,
        {"model": "yolo11n.pt", "train_image_ids": ["a"], "train_labels": []},
        algorithm,
    )
    assert contract["effective_label_codes"] == ["fire", "smoke"]


def test_legacy_iteration_recovers_schema_from_previous_snapshot(tmp_path: Path):
    data_dir, project = _project(tmp_path)
    AnnotationRepository(project).upsert("a", [_box("cigarette")], annotation_state="annotated")
    model = project / "previous.pt"
    model.write_bytes(b"model")
    snapshot = data_dir / "task_runtime" / "artifacts" / "old-task" / "snapshot.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(
        json.dumps({"label_schema": [{"code": "fire", "class_id": 0}, {"code": "smoke", "class_id": 1}]}),
        encoding="utf-8",
    )
    algorithm = {
        "id": "alg",
        "versions": [{
            "id": "v1",
            "task_id": "old-task",
            "created_at": "2026-09-10T01:01:01+00:00",
            "stored_path": str(model),
            "training_status": "SUCCEEDED",
            "artifact_verified": True,
            "trainable": True,
            "framework": "ultralytics",
        }],
    }
    contract = resolve_training_label_contract(
        data_dir,
        project,
        {"model": "yolo11n.pt", "train_image_ids": ["a"], "train_labels": ["cigarette"]},
        algorithm,
    )
    assert contract["effective_label_codes"] == ["fire", "smoke", "cigarette"]


def test_selected_material_codes_include_scoped_negatives_but_not_legacy_star(tmp_path: Path):
    _, project = _project(tmp_path)
    annotations = AnnotationRepository(project)
    annotations.upsert("a", [], annotation_state="confirmed_empty", annotation_scope=["fire", "smoke"])
    annotations.upsert("b", [], annotation_state="confirmed_empty")
    assert selected_material_label_codes(project, {"train_image_ids": ["a", "b"]}) == ["fire", "smoke"]


def test_projection_drops_unselected_boxes_without_creating_fake_negative(tmp_path: Path):
    _, project = _project(tmp_path)
    annotations = AnnotationRepository(project)
    annotations.upsert("a", [_box("fire"), _box("person")], annotation_state="annotated")

    class Materials:
        def get_many(self, _ids):
            return [{"id": "a", "width": 100, "height": 100, "annotation_hash": "full-hash"}]

    contract = {
        "project_path": str(project.resolve()),
        "effective_label_codes": ["fire"],
        "effective_label_schema": [{"code": "fire", "class_id": 0}],
    }
    token = _LABEL_CONTRACT.set(contract)
    try:
        rows = _scoped_selected_project_images(Materials(), project, ["a"])
    finally:
        _LABEL_CONTRACT.reset(token)
    assert [box["label"] for box in rows[0]["boxes"]] == ["fire"]
    assert rows[0]["annotation_scope"] == ["fire"]
    assert "annotation_hash" not in rows[0]


def test_projection_rejects_positive_material_with_only_unselected_labels(tmp_path: Path):
    _, project = _project(tmp_path)
    AnnotationRepository(project).upsert("a", [_box("person")], annotation_state="annotated")

    class Materials:
        def get_many(self, _ids):
            return [{"id": "a", "width": 100, "height": 100}]

    contract = {
        "project_path": str(project.resolve()),
        "effective_label_codes": ["fire"],
        "effective_label_schema": [{"code": "fire", "class_id": 0}],
    }
    token = _LABEL_CONTRACT.set(contract)
    try:
        with pytest.raises(ValueError, match="不能通过过滤其他标签制造负样本"):
            _scoped_selected_project_images(Materials(), project, ["a"])
    finally:
        _LABEL_CONTRACT.reset(token)
