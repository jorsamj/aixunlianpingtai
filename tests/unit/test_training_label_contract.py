from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from PIL import Image

from platform_core.annotation_repository import AnnotationRepository
from platform_core.training_label_tasks import (
    _LABEL_CONTRACT,
    _persist_version_contract,
    _scoped_selected_project_images,
    inherited_training_label_preview,
    project_training_rows,
    resolve_training_label_contract,
    selected_material_label_codes,
    training_material_scope_issue,
)
from platform_core.training_splits import SplitMode, SplitRequest, build_split_manifest
from platform_core.training_tasks import (
    TrainingSelectionResolution,
    TRAINING_PROJECTION_POLICY_V1,
    _apply_training_projection,
    freeze_training_inputs,
    materialize_portable_dataset,
    resolve_frozen_training_base,
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


def _seed_historical_annotation(project: Path, image_id: str, labels) -> None:
    """Seed pre-governance GT so fail-closed preflight can audit old bad data."""
    directory = project / "annotations"
    directory.mkdir(parents=True, exist_ok=True)
    boxes = [_box(label) for label in labels]
    (directory / f"{image_id}.json").write_text(
        json.dumps({
            "image_id": image_id,
            "annotation_state": "annotated",
            "annotation_scope": list(labels),
            "boxes": boxes,
        }),
        encoding="utf-8",
    )


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
    assert contract["requested_new_label_codes"] == ["smoke", "fire"]
    assert contract["inherited_label_codes"] == []
    assert contract["effective_label_codes"] == ["smoke", "fire"]
    assert [item["class_id"] for item in contract["effective_label_schema"]] == [0, 1]
    assert contract["mother_model_labels_inherited"] is False
    assert "person" not in contract["effective_label_codes"]
    assert "helmet" not in contract["effective_label_codes"]


def test_training_class_ids_are_dense_while_canonical_ids_remain_stable(tmp_path: Path):
    data_dir, project = _project(tmp_path)
    meta = json.loads((project / "meta.json").read_text(encoding="utf-8"))
    for row in meta["label_meta"]:
        if row["code"] == "fire":
            row["class_id"] = 1
        elif row["code"] == "smoke":
            row["class_id"] = 7
    (project / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    annotations = AnnotationRepository(project)
    annotations.upsert("a", [_box("fire"), _box("smoke")], annotation_state="annotated")

    contract = resolve_training_label_contract(
        data_dir,
        project,
        {
            "model": "yolo11n.pt",
            "train_image_ids": ["a"],
            "train_labels": ["fire", "smoke"],
        },
        {"id": "alg", "versions": []},
    )

    schema = contract["effective_label_schema"]
    assert [item["class_id"] for item in schema] == [0, 1]
    assert [item["canonical_project_class_id"] for item in schema] == [1, 7]


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


def test_confirmed_empty_scope_cannot_introduce_a_new_training_class(tmp_path: Path):
    data_dir, project = _project(tmp_path)
    annotations = AnnotationRepository(project)
    annotations.upsert("positive", [_box("fire")], annotation_state="annotated")
    annotations.upsert(
        "negative",
        [],
        annotation_state="confirmed_empty",
        annotation_scope=["helmet"],
    )

    with pytest.raises(ValueError, match="不在已选素材"):
        resolve_training_label_contract(
            data_dir,
            project,
            {
                "model": "yolo11n.pt",
                "train_image_ids": ["positive", "negative"],
                "train_labels": ["helmet"],
            },
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


def test_requested_new_label_cannot_be_sourced_only_from_test_set(tmp_path: Path):
    data_dir, project = _project(tmp_path)
    annotations = AnnotationRepository(project)
    annotations.upsert("train", [_box("fire")], annotation_state="annotated")
    annotations.upsert("test", [_box("person")], annotation_state="annotated")
    with pytest.raises(ValueError, match="不在已选素材"):
        resolve_training_label_contract(
            data_dir,
            project,
            {
                "model": "yolo11n.pt",
                "train_image_ids": ["train"],
                "test_image_ids": ["test"],
                "train_labels": ["person"],
            },
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
    assert contract["requested_new_label_codes"] == ["cigarette"]
    assert contract["effective_label_codes"] == ["fire", "smoke", "cigarette"]
    assert [item["class_id"] for item in contract["effective_label_schema"]] == [0, 1, 2]
    assert contract["base_version_id"] == "v1"
    assert contract["label_schema_changed"] is True
    assert contract["label_schema_change_reasons"] == ["added_labels"]
    assert contract["base_training_mode"] == "previous_weights_init"
    assert contract["strict_resume"] is False
    assert contract["optimizer_state_resumed"] is False
    assert contract["base_model_contract_schema_version"] == 1
    assert contract["base_model_reference"] == str(model.resolve())
    assert contract["base_model_size_bytes"] == model.stat().st_size
    assert contract["base_model_sha256"] == hashlib.sha256(model.read_bytes()).hexdigest()
    frozen_base = resolve_frozen_training_base({
        "framework": "ultralytics",
        "label_contract": contract,
    })
    assert frozen_base["base_version_id"] == "v1"
    assert frozen_base["base_model_path"] == str(model.resolve())


def test_input_freeze_identity_changes_when_frozen_base_model_changes(tmp_path: Path):
    _data_dir, project = _project(tmp_path)
    images = tuple(
        {
            "id": f"image-{index}",
            "dataset_id": "pool",
            "filename": f"image-{index}.jpg",
            "stored_name": f"image-{index}.jpg",
            "content_sha256": hashlib.sha256(f"image-{index}".encode()).hexdigest(),
            "size_bytes": 100 + index,
            "width": 100,
            "height": 100,
            "processing_status": "processed",
            "annotation_state": "annotated",
            "annotation_scope": ["fire"],
            "annotated": True,
            "group_id": f"group-{index}",
            "boxes": [_box("fire")],
        }
        for index in range(5)
    )
    split = SplitRequest(
        mode=SplitMode.INDEPENDENT_TEST_SET,
        train_image_ids=tuple(row["id"] for row in images[:4]),
        test_image_ids=(images[4]["id"],),
        experiment_percent=None,
        validation_percent=25,
    )
    resolution = TrainingSelectionResolution(
        requested_split=split,
        effective_split=split,
        effective_images=images,
        selected_train_image_ids=split.train_image_ids,
        pending_annotation_image_ids=(),
    )
    schema = [{"code": "fire", "class_id": 0, "canonical_project_class_id": 0}]
    common = {
        "base_model_contract_schema_version": 1,
        "framework": "ultralytics",
        "base_training_mode": "previous_weights_init",
        "base_version_id": "v1",
        "base_model_reference": "/frozen/v1.pt",
        "base_model_size_bytes": 123,
    }
    first = freeze_training_inputs(
        project,
        split,
        seed=7,
        selection_resolution=resolution,
        effective_images=images,
        label_schema_override=schema,
        label_contract={**common, "base_model_sha256": "a" * 64},
    )
    second = freeze_training_inputs(
        project,
        split,
        seed=7,
        selection_resolution=resolution,
        effective_images=images,
        label_schema_override=schema,
        label_contract={**common, "base_model_sha256": "b" * 64},
    )

    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["dataset_revision_id"] == second["dataset_revision_id"]
    assert first["input_freeze_id"] != second["input_freeze_id"]


def test_input_freeze_reserves_new_label_positive_in_train_split(tmp_path: Path):
    _data_dir, project = _project(tmp_path)
    images = tuple(
        {
            "id": f"image-{index}",
            "dataset_id": "pool",
            "filename": f"image-{index}.jpg",
            "stored_name": f"image-{index}.jpg",
            "content_sha256": hashlib.sha256(f"rare-{index}".encode()).hexdigest(),
            "size_bytes": 100 + index,
            "width": 100,
            "height": 100,
            "processing_status": "processed",
            "annotation_state": "annotated",
            "annotation_scope": ["fire", "smoke"],
            "annotated": True,
            "group_id": f"group-{index}",
            "boxes": [_box("smoke" if index == 0 else "fire")],
        }
        for index in range(12)
    )
    split = SplitRequest(
        mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
        train_image_ids=tuple(row["id"] for row in images),
        experiment_percent=25,
        validation_percent=25,
    )
    seed = next(
        candidate
        for candidate in range(100)
        if "image-0" not in build_split_manifest(
            images, split, seed=candidate,
        ).ids["train"]
    )
    resolution = TrainingSelectionResolution(
        requested_split=split,
        effective_split=split,
        effective_images=images,
        selected_train_image_ids=split.train_image_ids,
        pending_annotation_image_ids=(),
    )
    schema = [
        {"code": "fire", "class_id": 0, "canonical_project_class_id": 0},
        {"code": "smoke", "class_id": 1, "canonical_project_class_id": 1},
    ]

    frozen = freeze_training_inputs(
        project,
        split,
        seed=seed,
        selection_resolution=resolution,
        effective_images=images,
        label_schema_override=schema,
        label_contract={
            "effective_label_schema": schema,
            "requested_new_label_codes": ["smoke"],
        },
    )

    assert frozen["input_quality"]["role_label_counts"]["train"]["smoke"] == 1
    assert frozen["input_quality"]["active_labels_without_train_positive"] == []


def test_version_contract_backfill_preserves_full_frozen_base_lineage(tmp_path: Path):
    _data_dir, project = _project(tmp_path)
    (project / "algorithms.json").write_text(
        json.dumps([{
            "id": "alg",
            "versions": [{
                "id": "v1",
                "task_id": "task-1",
                "label_contract": {
                    "base_model_contract_schema_version": 1,
                    "base_model_reference": "/frozen/original.pt",
                    "base_model_sha256": "a" * 64,
                    "base_model_size_bytes": 123,
                },
            }],
        }]),
        encoding="utf-8",
    )
    contract = {
        "algorithm_id": "alg",
        "project_path": str(project),
        "schema_version": 1,
        "effective_label_schema": [
            {"code": "fire", "class_id": 0, "canonical_project_class_id": 0}
        ],
        "effective_label_codes": ["fire"],
        "base_model_contract_schema_version": 1,
        "base_model_reference": "/frozen/original.pt",
        "base_model_sha256": "a" * 64,
        "base_model_size_bytes": 123,
        "base_training_mode": "previous_weights_init",
        "base_version_id": "v0",
        "strict_resume": False,
        "optimizer_state_resumed": False,
    }

    _persist_version_contract(project, "task-1", contract)

    from platform_core.algorithms import list_algorithms

    version = list_algorithms(project / "algorithms.json")[0]["versions"][0]
    persisted = version["label_contract"]
    assert persisted["base_model_contract_schema_version"] == 1
    assert persisted["base_model_reference"] == "/frozen/original.pt"
    assert persisted["base_model_sha256"] == "a" * 64
    assert persisted["base_model_size_bytes"] == 123
    assert persisted["base_version_id"] == "v0"
    assert "project_path" not in persisted


def test_frozen_iteration_base_fails_closed_if_checkpoint_changes(tmp_path: Path):
    data_dir, project = _project(tmp_path)
    AnnotationRepository(project).upsert("a", [_box("fire")], annotation_state="annotated")
    model = project / "previous.pt"
    model.write_bytes(b"original-model")
    algorithm = {
        "id": "alg",
        "versions": [{
            "id": "v1",
            "version_name": "20260910010101",
            "stored_path": str(model),
            "training_status": "SUCCEEDED",
            "artifact_verified": True,
            "trainable": True,
            "framework": "ultralytics",
            "label_schema": [{"code": "fire", "class_id": 0}],
        }],
    }
    contract = resolve_training_label_contract(
        data_dir,
        project,
        {
            "framework": "ultralytics",
            "model": "yolo11n.pt",
            "train_image_ids": ["a"],
            "train_labels": [],
        },
        algorithm,
    )
    model.write_bytes(b"changed-model")

    with pytest.raises(ValueError, match="size changed|SHA256 changed"):
        resolve_frozen_training_base({
            "framework": "ultralytics",
            "label_contract": contract,
        })


def test_first_training_base_mode_stays_mother_model_reference(tmp_path: Path):
    data_dir, project = _project(tmp_path)
    AnnotationRepository(project).upsert("a", [_box("fire")], annotation_state="annotated")
    contract = resolve_training_label_contract(
        data_dir,
        project,
        {
            "framework": "ultralytics",
            "model": "yolo11n.pt",
            "train_image_ids": ["a"],
            "train_labels": ["fire"],
        },
        {"id": "alg", "versions": []},
    )
    assert contract["base_training_mode"] == "mother_model_init"
    assert contract["base_version_id"] == ""
    assert contract["base_model_reference"] == "yolo11n.pt"
    frozen_base = resolve_frozen_training_base({
        "framework": "ultralytics",
        "label_contract": contract,
    })
    assert frozen_base["base_version_id"] is None
    assert frozen_base["base_model_path"] == "yolo11n.pt"


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
    assert contract["requested_new_label_codes"] == []
    assert contract["label_schema_changed"] is False
    assert contract["dropped_inherited_label_codes"] == []


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


def test_selected_material_codes_include_explicit_and_default_negative_scopes(tmp_path: Path):
    _, project = _project(tmp_path)
    annotations = AnnotationRepository(project)
    annotations.upsert(
        "a",
        [],
        annotation_state="confirmed_empty",
        annotation_scope=["fire", "smoke"],
    )
    default_negative = annotations.upsert(
        "b",
        [],
        annotation_state="confirmed_empty",
    )
    assert default_negative["annotation_scope"] == [
        "cigarette",
        "fire",
        "helmet",
        "person",
        "smoke",
    ]
    assert selected_material_label_codes(
        project, {"train_image_ids": ["a", "b"]}
    ) == ["fire", "smoke", "person", "helmet", "cigarette"]


@pytest.mark.parametrize("selected_codes", [
    ["smoke", "fire"],  # Unreviewed class beside a retained positive.
    ["fire"],           # Removing the only box must not invent a negative.
])
def test_projection_rejects_unreviewed_class_in_task_schema(selected_codes):
    rows = [{
        "id": "image-a", "annotation_state": "annotated",
        "annotation_scope": ["smoke"], "boxes": [_box("smoke")],
    }]
    contract = {"effective_label_codes": selected_codes}
    with pytest.raises(ValueError, match="标注审核范围未覆盖"):
        project_training_rows(rows, contract)

    # A single-class task may legitimately use the reviewed smoke positive.
    positive = project_training_rows(rows, {"effective_label_codes": ["smoke"]})
    assert positive[0]["annotation_state"] == "annotated"
    assert positive[0]["annotation_scope"] == ["smoke"]

    # Explicit review of both classes permits the existing redaction contract.
    rows[0]["annotation_scope"] = ["smoke", "fire"]
    projected = project_training_rows(rows, {"effective_label_codes": ["fire"]})
    assert projected[0]["annotation_state"] == "confirmed_empty"
    assert projected[0]["annotation_scope"] == ["fire"]
    assert projected[0]["negative_origin"] == "redacted_unselected_labels"


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
    assert rows[0]["source_annotation_state"] == "annotated"
    assert rows[0]["source_labels"] == ["fire", "person"]
    assert "negative_origin" not in rows[0]
    assert [box["label"] for box in rows[0]["training_excluded_boxes"]] == ["person"]
    assert rows[0]["training_projection_policy"] == "redact_excluded_objects_v2_preserve_selected"
    assert len(rows[0]["training_projection_digest"]) == 64
    assert "annotation_hash" not in rows[0]


def test_projection_turns_only_unselected_labels_into_task_negative_without_mutating_source(tmp_path: Path):
    _, project = _project(tmp_path)
    annotations = AnnotationRepository(project)
    annotations.upsert(
        "a", [_box("person")], annotation_state="annotated",
        annotation_scope=["fire", "person"],
    )

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
        rows = _scoped_selected_project_images(Materials(), project, ["a"])
    finally:
        _LABEL_CONTRACT.reset(token)

    projected = rows[0]
    assert projected["annotation_state"] == "confirmed_empty"
    assert projected["annotated"] is True
    assert projected["boxes"] == []
    assert projected["annotation_scope"] == ["fire"]
    assert projected["negative_origin"] == "redacted_unselected_labels"
    assert projected["source_annotation_state"] == "annotated"
    assert projected["source_labels"] == ["person"]
    assert [box["label"] for box in projected["training_excluded_boxes"]] == ["person"]
    assert projected["training_projection_policy"] == "redact_excluded_objects_v2_preserve_selected"
    assert len(projected["training_projection_digest"]) == 64

    # Source Ground Truth identity is immutable provenance. Re-projecting an
    # already task-local row must not reinterpret the synthetic negative as
    # the original annotation truth.
    source = annotations.get("a")
    assert projected["source_annotation_hash"] == source["content_digest"]
    reprojected = project_training_rows([projected], contract)[0]
    assert reprojected["annotation_state"] == "confirmed_empty"
    assert reprojected["source_annotation_state"] == "annotated"
    assert reprojected["source_annotation_hash"] == source["content_digest"]
    assert reprojected["source_labels"] == ["person"]

    # The task projection must never rewrite material-library Ground Truth.
    assert source["annotation_state"] == "annotated"
    assert [box["label"] for box in source["boxes"]] == ["person"]


def test_portable_data_yaml_contains_only_effective_task_schema(tmp_path: Path):
    _, project = _project(tmp_path)
    AnnotationRepository(project).upsert(
        "a",
        [_box("fire"), _box("smoke"), _box("person")],
        annotation_state="annotated",
    )
    image_file = tmp_path / "source.jpg"
    Image.new("RGB", (100, 100), (220, 220, 220)).save(image_file, format="JPEG")
    content_hash = hashlib.sha256(image_file.read_bytes()).hexdigest()

    class Materials:
        def get_many(self, _ids):
            return [{
                "id": "a",
                "filename": "source.jpg",
                "width": 100,
                "height": 100,
            }]

    contract = {
        "project_path": str(project.resolve()),
        "effective_label_codes": ["fire", "smoke"],
        "effective_label_schema": [
            {"code": "fire", "class_id": 0},
            {"code": "smoke", "class_id": 1},
        ],
    }
    token = _LABEL_CONTRACT.set(contract)
    try:
        rows = _scoped_selected_project_images(Materials(), project, ["a"])
    finally:
        _LABEL_CONTRACT.reset(token)
    rows[0]["content_sha256"] = content_hash
    snapshot = {
        "snapshot_id": "task-schema-only",
        "label_schema": contract["effective_label_schema"],
        "ids": {"train": ["a"], "validation": [], "test": []},
        "images": [{"image_id": "a", "content_sha256": content_hash}],
    }
    bundle = materialize_portable_dataset(
        tmp_path / "work",
        snapshot,
        rows,
        lambda _row: image_file,
        safety_reserve_bytes=0,
    )
    data = yaml.safe_load((bundle / "dataset" / "data.yaml").read_text(encoding="utf-8"))
    assert data["names"] == {0: "fire", 1: "smoke"}
    label_lines = (bundle / "dataset" / "labels" / "train" / "a.txt").read_text(encoding="utf-8").splitlines()
    assert {line.split()[0] for line in label_lines} == {"0", "1"}
    assert all("person" not in line for line in label_lines)


def test_task_filtered_negative_materializes_as_empty_yolo_label(tmp_path: Path):
    _, project = _project(tmp_path)
    AnnotationRepository(project).upsert(
        "a", [_box("person")], annotation_state="annotated",
        annotation_scope=["fire", "person"],
    )
    image_file = tmp_path / "task-negative.jpg"
    source_image = Image.new("RGB", (100, 100), (220, 220, 220))
    source_image.paste((0, 0, 0), (1, 1, 21, 21))
    source_image.save(image_file, format="JPEG")
    content_hash = hashlib.sha256(image_file.read_bytes()).hexdigest()

    class Materials:
        def get_many(self, _ids):
            return [{
                "id": "a", "filename": image_file.name, "width": 100, "height": 100
            }]

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
    rows[0]["content_sha256"] = content_hash
    snapshot = {
        "snapshot_id": "filtered-negative",
        "label_schema": contract["effective_label_schema"],
        "ids": {"train": ["a"], "validation": [], "test": []},
        "images": [{"image_id": "a", "content_sha256": content_hash}],
    }
    bundle = materialize_portable_dataset(
        tmp_path / "work-negative", snapshot, rows, lambda _row: image_file, safety_reserve_bytes=0
    )
    label = bundle / "dataset" / "labels" / "train" / "a.txt"
    assert label.is_file()
    assert label.read_text(encoding="utf-8") == ""
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    record = manifest["splits"]["train"][0]
    assert record["training_projection_policy"] == "redact_excluded_objects_v2_preserve_selected"
    assert record["redacted_object_count"] == 1
    assert record["content_sha256"] != content_hash
    with Image.open(bundle / "dataset" / "images" / "train" / "a.jpg") as projected_image:
        r, g, b = projected_image.convert("RGB").getpixel((10, 10))
    assert min(r, g, b) > 150



def test_redaction_v2_preserves_selected_positive_pixels_inside_excluded_box(tmp_path: Path):
    _, project = _project(tmp_path)
    annotations = AnnotationRepository(project)
    annotations.upsert(
        "a",
        [
            {"label": "person", "x1": 1, "y1": 1, "x2": 60, "y2": 60},
            {"label": "fire", "x1": 20, "y1": 20, "x2": 35, "y2": 35},
        ],
        annotation_state="annotated",
    )
    image_file = tmp_path / "overlap.png"
    source = Image.new("RGB", (100, 100), (230, 230, 230))
    source.paste((0, 0, 0), (1, 1, 60, 60))
    source.paste((240, 20, 20), (20, 20, 35, 35))
    source.save(image_file, format="PNG")
    content_hash = hashlib.sha256(image_file.read_bytes()).hexdigest()

    class Materials:
        def get_many(self, _ids):
            return [{"id": "a", "filename": image_file.name, "width": 100, "height": 100}]

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
    rows[0]["content_sha256"] = content_hash
    assert rows[0]["training_projection_policy"] == "redact_excluded_objects_v2_preserve_selected"

    bundle = materialize_portable_dataset(
        tmp_path / "work-overlap",
        {
            "snapshot_id": "overlap-redaction-v2",
            "label_schema": contract["effective_label_schema"],
            "ids": {"train": ["a"], "validation": [], "test": []},
            "images": [{"image_id": "a", "content_sha256": content_hash}],
        },
        rows,
        lambda _row: image_file,
        safety_reserve_bytes=0,
    )

    with Image.open(bundle / "dataset" / "images" / "train" / "a.png") as projected:
        rgb = projected.convert("RGB")
        outside_selected = rgb.getpixel((10, 10))
        selected_target = rgb.getpixel((25, 25))

    assert min(outside_selected) > 150
    assert selected_target[0] > 180
    assert selected_target[1] < 80
    assert selected_target[2] < 80
    label_lines = (
        bundle / "dataset" / "labels" / "train" / "a.txt"
    ).read_text(encoding="utf-8").splitlines()
    assert len(label_lines) == 1
    assert label_lines[0].startswith("0 ")


def test_legacy_v1_redaction_remains_replayable_without_v2_pixel_restore(tmp_path: Path):
    image_file = tmp_path / "legacy-v1.png"
    source = Image.new("RGB", (100, 100), (230, 230, 230))
    source.paste((0, 0, 0), (1, 1, 60, 60))
    source.paste((240, 20, 20), (20, 20, 35, 35))
    source.save(image_file, format="PNG")

    identity = _apply_training_projection(
        image_file,
        {
            "id": "legacy",
            "boxes": [{"label": "fire", "x1": 20, "y1": 20, "x2": 35, "y2": 35}],
            "training_excluded_boxes": [
                {"label": "person", "x1": 1, "y1": 1, "x2": 60, "y2": 60}
            ],
            "training_projection_policy": TRAINING_PROJECTION_POLICY_V1,
            "training_projection_digest": "a" * 64,
        },
        "train",
        {},
    )

    assert identity["training_projection_policy"] == TRAINING_PROJECTION_POLICY_V1
    with Image.open(image_file) as projected:
        r, g, b = projected.convert("RGB").getpixel((25, 25))
    assert min(r, g, b) > 150

def test_training_preflight_rejects_dangling_material_label(tmp_path: Path):
    data_dir, project = _project(tmp_path)
    _seed_historical_annotation(project, "a", ["external_only"])
    with pytest.raises(ValueError, match="未映射、已删除或已停用"):
        resolve_training_label_contract(
            data_dir,
            project,
            {"model": "yolo11n.pt", "train_image_ids": ["a"], "train_labels": ["fire"]},
            {"id": "alg", "versions": []},
        )


def test_training_preflight_rejects_temp_class_even_if_catalog_contains_it(tmp_path: Path):
    data_dir, project = _project(tmp_path)
    meta = json.loads((project / "meta.json").read_text(encoding="utf-8"))
    meta["label_meta"].append(
        {"code": "class_0", "display_name_zh": "临时类", "class_id": 5, "active": True}
    )
    (project / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    AnnotationRepository(project).upsert(
        "a", [_box("class_0")], annotation_state="annotated"
    )
    with pytest.raises(ValueError, match="临时/未知标签"):
        selected_material_label_codes(project, {"train_image_ids": ["a"]})


def test_iteration_collapses_merged_previous_labels_into_current_canonical_target(tmp_path: Path):
    data_dir, project = _project(tmp_path)
    meta = json.loads((project / "meta.json").read_text(encoding="utf-8"))
    for row in meta["label_meta"]:
        if row["code"] == "smoke":
            row["status"] = "merged"
            row["merged_into"] = "fire"
    (project / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    AnnotationRepository(project).upsert(
        "a", [_box("fire")], annotation_state="annotated"
    )
    model = project / "previous.pt"
    model.write_bytes(b"model")
    previous_schema = [
        {"code": "fire", "class_id": 0},
        {"code": "smoke", "class_id": 1},
    ]
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
            "label_schema": previous_schema,
        }],
    }
    contract = resolve_training_label_contract(
        data_dir,
        project,
        {"model": "yolo11n.pt", "train_image_ids": ["a"], "train_labels": []},
        algorithm,
    )
    assert contract["inherited_label_codes"] == ["fire", "smoke"]
    assert contract["retained_inherited_label_codes"] == ["fire"]
    assert contract["merged_inherited_label_codes"] == {"smoke": "fire"}
    assert contract["dropped_inherited_label_codes"] == ["smoke"]
    assert contract["effective_label_codes"] == ["fire"]
    assert [row["class_id"] for row in contract["effective_label_schema"]] == [0]
    assert contract["label_schema_changed"] is True
    assert contract["label_schema_change_reasons"] == ["merged_labels"]
    assert contract["base_training_mode"] == "previous_weights_init"
    assert contract["strict_resume"] is False
    assert algorithm["versions"][0]["label_schema"] == previous_schema


def test_inherited_training_label_preview_returns_only_current_canonical_labels(tmp_path: Path):
    data_dir, project = _project(tmp_path)
    meta = json.loads((project / "meta.json").read_text(encoding="utf-8"))
    for row in meta["label_meta"]:
        if row["code"] == "smoke":
            row["status"] = "merged"
            row["merged_into"] = "fire"
    (project / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    previous_schema = [
        {"code": "fire", "class_id": 0},
        {"code": "smoke", "class_id": 1},
    ]
    algorithm = {
        "id": "alg",
        "current_version_id": "v1",
        "versions": [{
            "id": "v1",
            "version_name": "20260910010101",
            "label_schema": previous_schema,
        }],
    }

    preview = inherited_training_label_preview(
        data_dir,
        project,
        algorithm,
        "v1",
    )

    assert preview == {
        "has_previous_version": True,
        "base_version_id": "v1",
        "base_version_name": "20260910010101",
        "labels": [{"code": "fire", "display_name": "明火"}],
    }
    serialized = json.dumps(preview, ensure_ascii=False)
    assert "smoke" not in serialized
    assert "merged_into" not in serialized
    assert "inherited_from_codes" not in serialized


def test_inherited_training_label_preview_is_empty_for_first_training(tmp_path: Path):
    data_dir, project = _project(tmp_path)
    preview = inherited_training_label_preview(
        data_dir,
        project,
        {"id": "alg", "versions": []},
    )
    assert preview == {
        "has_previous_version": False,
        "base_version_id": "",
        "base_version_name": "",
        "labels": [],
    }


def test_iteration_rejects_inactive_previous_label_without_merge_target(tmp_path: Path):
    data_dir, project = _project(tmp_path)
    meta = json.loads((project / "meta.json").read_text(encoding="utf-8"))
    for row in meta["label_meta"]:
        if row["code"] == "smoke":
            row["active"] = False
            row["status"] = "inactive"
    (project / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    AnnotationRepository(project).upsert(
        "a", [_box("fire")], annotation_state="annotated"
    )
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
            "label_schema": [
                {"code": "fire", "class_id": 0},
                {"code": "smoke", "class_id": 1},
            ],
        }],
    }
    with pytest.raises(ValueError, match="已停用且没有明确 merged_into"):
        resolve_training_label_contract(
            data_dir,
            project,
            {"model": "yolo11n.pt", "train_image_ids": ["a"], "train_labels": []},
            algorithm,
        )


def test_scoped_projection_reuses_frozen_rows_without_second_annotation_io(tmp_path: Path, monkeypatch):
    _, project = _project(tmp_path)
    total = 20_000
    frozen_rows = [
        {
            "id": f"image-{index:05d}",
            "width": 100,
            "height": 100,
            "annotation_state": "annotated",
            "annotation_scope": ["fire", "person"],
            "annotation_hash": f"digest-{index}",
            "boxes": [_box("fire"), _box("person")],
        }
        for index in range(total)
    ]
    monkeypatch.setattr(
        "platform_core.training_label_tasks._ORIGINAL_SELECTED_PROJECT_IMAGES",
        lambda _materials, _project, _ids: frozen_rows,
    )

    class ForbiddenSecondRepository:
        def __init__(self, *_args, **_kwargs):
            pytest.fail("training label projection must reuse already-frozen annotation rows")

    monkeypatch.setattr(
        "platform_core.training_label_tasks.AnnotationRepository",
        ForbiddenSecondRepository,
    )
    contract = {
        "project_path": str(project.resolve()),
        "effective_label_codes": ["fire"],
        "effective_label_schema": [{"code": "fire", "class_id": 0}],
    }
    token = _LABEL_CONTRACT.set(contract)
    try:
        projected = _scoped_selected_project_images(object(), project, [row["id"] for row in frozen_rows])
    finally:
        _LABEL_CONTRACT.reset(token)

    assert len(projected) == total
    assert projected[0]["source_labels"] == ["fire", "person"]
    assert projected[-1]["boxes"][0]["label"] == "fire"
    assert all("annotation_hash" not in row for row in projected)


def test_scope_issue_returns_every_missing_effective_label():
    issue = training_material_scope_issue(
        {
            "id": "partial",
            "annotation_state": "annotated",
            "annotation_scope": ["helmet"],
            "boxes": [{"label": "helmet", "class_id": 0}],
        },
        {"effective_label_codes": ["helmet", "cigarette", "person"]},
    )

    assert issue == {
        "image_id": "partial",
        "issue_type": "partial_review_scope",
        "annotation_state": "annotated",
        "annotation_scope": ["helmet"],
        "required_label_codes": ["helmet", "cigarette", "person"],
        "missing_label_codes": ["cigarette", "person"],
    }


def test_scope_issue_accepts_explicitly_complete_scope():
    assert training_material_scope_issue(
        {
            "id": "complete",
            "annotation_state": "confirmed_empty",
            "annotation_scope": ["helmet", "person"],
            "boxes": [],
        },
        {"effective_label_codes": ["helmet", "person"]},
    ) is None


def test_scope_issue_treats_legacy_positive_labels_as_minimum_review_evidence():
    issue = training_material_scope_issue(
        {
            "id": "legacy",
            "annotation_state": "annotated",
            "annotation_scope": [],
            "boxes": [{"label": "helmet", "class_id": 0}],
        },
        {"effective_label_codes": ["helmet", "person"]},
    )

    assert issue["missing_label_codes"] == ["person"]


def test_scope_issue_reports_missing_formal_annotation():
    issue = training_material_scope_issue(
        {
            "id": "pending",
            "annotation_state": "unannotated",
            "annotation_scope": [],
            "boxes": [],
        },
        {"effective_label_codes": ["helmet"]},
    )

    assert issue["issue_type"] == "missing_annotation"
    assert issue["missing_label_codes"] == ["helmet"]
