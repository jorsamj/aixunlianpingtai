"""W10/M13-A negative-sample training closed loop, isolated on real SQLite.

Every test builds real MaterialRepository / AnnotationRepository / NegativePool
databases under ``tmp_path`` (or uses the session-isolated app DATA_DIR for the
formal review API) and drives the existing prepare -> freeze -> materialize and
synchronous-create paths. Core repositories are never mocked.

M13-A closes two reachability/consistency gaps:

* the first-training pure-negative refusal is proven on the *real* prepare
  worker and the *real* synchronous create request (no ``freeze_training_inputs``
  nor ``assert_material_input_admission`` monkeypatch). Only one minimal unit test
  keeps the typed-error -> preparation-evidence mapping injecting a typed error.
* an explicitly submitted formal negative (``confirmed_empty``) must prove that
  it belongs to the declared target algorithm, through algorithm-tier
  ``NegativePool`` membership or an algorithm-context task negative receipt.
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
from platform_core.negative_pool import NegativePool
import platform_core.remote_training_tasks as remote_training_tasks_module
from platform_core.remote_training_tasks import (
    RemoteTrainingPreparationError,
    RemoteTrainingPrepareHandler,
)
from platform_core.task_runtime import (
    ArtifactStore,
    Scheduler,
    TaskKind,
    TaskRecord,
    TaskRepository,
    TaskStatus,
)
from platform_core.training_material_picker_api import training_material_picker_router
import platform_core.training_tasks as training_tasks
from platform_core.training_splits import SplitMode, SplitRequest

ALGORITHM_ID = "algorithm-w10"
TARGET_TASK_ID = "train_w10_target"
PREP_TASK_ID = "trainprep_train_w10_target"
FIRE_BOX = {"label": "fire", "class_id": 0, "x1": 5, "y1": 5, "x2": 40, "y2": 40}
FIRST_TRAINING_POSITIVE_MESSAGE = (
    "训练集没有任何正样本标注框；confirmed_empty 可作为负样本，但不能单独训练检测模型"
)
# The earlier label-contract gate (the first real gate reached by a request that
# selects only confirmed_empty material) keeps its own Chinese reason.
FIRST_TRAINING_CONTRACT_POSITIVE_MESSAGE = (
    "首次训练的所有已选素材都没有正样本标注框"
    "；confirmed_empty 只能作为负样本，不能单独训练检测模型"
)


def _write_image(path: Path, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (64, 64), color).save(path, format="JPEG")


def _build_project(
    data_dir: Path,
    *,
    project_id: str = "p1",
    labels: tuple[str, ...] = ("fire",),
    count: int = 5,
) -> str:
    """Real project directory with uploaded JPEG bytes and repository sources."""
    project = Path(data_dir) / "projects" / project_id
    (project / "uploads").mkdir(parents=True)
    (project / "models").mkdir()
    (project / "jobs").mkdir()
    (project / "models" / "yolo11n.pt").write_bytes(b"preinstalled-w10-weight" * 128)
    (project / "meta.json").write_text(json.dumps({
        "id": project_id,
        "labels": list(labels),
        "label_meta": [
            {"code": code, "class_id": index}
            for index, code in enumerate(labels)
        ],
    }, ensure_ascii=False), encoding="utf-8")
    rows = []
    for index in range(count):
        image_id = f"image-{index}"
        path = project / "uploads" / f"{image_id}.jpg"
        _write_image(path, (20 * index, 40, 90))
        rows.append({
            "id": image_id,
            "dataset_id": "default",
            "stored_name": path.name,
            "filename": path.name,
            "storage_source_id": "default_local",
            "storage_type": "local",
            "object_key": f"uploads/{path.name}",
            "width": 64,
            "height": 64,
            "size_bytes": path.stat().st_size,
            "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "processing_status": "processed",
            "annotated": True,
            "group_id": image_id,
        })
    (project / "images.json").write_text(json.dumps(rows), encoding="utf-8")
    (project / "algorithms.json").write_text(json.dumps([
        {"id": ALGORITHM_ID, "name": "W10 negative loop", "versions": []},
    ]), encoding="utf-8")
    return project_id


def _project_path(data_dir: Path, project_id: str = "p1") -> Path:
    return Path(data_dir) / "projects" / project_id


def _set_annotation(
    project: Path,
    image_id: str,
    *,
    boxes: list[dict] | None = None,
    state: str = "annotated",
    scope: list[str] | None = None,
) -> dict:
    return AnnotationRepository(project).upsert(
        image_id,
        [dict(box) for box in (boxes or [])],
        annotation_state=state,
        annotation_scope=list(scope or []),
    )


def _paint_fire_gt(project: Path, image_ids: list[str] | tuple[str, ...]) -> None:
    for image_id in image_ids:
        _set_annotation(project, image_id, boxes=[FIRE_BOX], scope=["fire"])


def _add_to_algorithm_pool(
    project: Path, image_ids: list[str] | tuple[str, ...],
    algorithm_id: str = ALGORITHM_ID,
) -> None:
    NegativePool(MaterialRepository(project)).members(
        list(image_ids), algorithm_id=algorithm_id,
    )


def _confirm_algorithm_negative_receipts(
    project: Path, image_ids: list[str] | tuple[str, ...],
    labels: tuple[str, ...] = ("fire",),
    *,
    algorithm_id: str = ALGORITHM_ID,
) -> list[str]:
    """Issue the existing algorithm-context task negative receipts (real owner)."""
    from platform_core.training_label_tasks import (
        task_negative_context,
        task_negative_identity,
    )

    contract = {
        "algorithm_id": algorithm_id,
        "effective_label_codes": list(labels),
    }
    rows = training_tasks._selected_project_images(
        MaterialRepository(project), project, list(image_ids),
    )
    return AnnotationRepository(project).confirm_task_negatives(
        task_negative_context(contract),
        [task_negative_identity(row, contract) for row in rows],
        {"actor_id": "w10-m13a"},
    )


def _runtime(
    data_dir: Path,
    project_id: str,
    *,
    train_ids: tuple[str, ...],
    test_ids: tuple[str, ...] = (),
) -> tuple[TaskRepository, ArtifactStore, str]:
    """Minimal real task runtime: one TRAINING target plus its PREPARE child."""
    runtime = Path(data_dir) / "task_runtime"
    repository = TaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")
    project = _project_path(data_dir, project_id)
    payload = {
        "schema_version": 3,
        "framework": "ultralytics",
        "target": "remote",
        "remote_input_state": "PREPARING",
        "remote_prepare_task_id": PREP_TASK_ID,
        "algorithm_asset_id": ALGORITHM_ID,
        "model": str(project / "models" / "yolo11n.pt"),
        "split_mode": "independent_test_set",
        "train_image_ids": list(train_ids),
        "test_image_ids": list(test_ids),
        "validation_percent": 25,
        "experiment_percent": None,
        "epochs": 3,
        "imgsz": 640,
        "batch": 4,
        "resource_strategy": "auto",
        "resource_profile": "performance",
        "gpu_policy": "exclusive",
        "precision": "fp16",
        "time": 2.5,
        "requested_device": "auto",
        "device": "auto",
    }
    artifacts.atomic_write_json(TARGET_TASK_ID, "payload.json", payload)
    repository.create(TaskRecord.new(
        TARGET_TASK_ID,
        project_id,
        TaskKind.TRAINING,
        "payload.json",
        "training:remote:scheduler",
        required_capabilities=("training.ultralytics",),
    ))
    artifacts.atomic_write_json(PREP_TASK_ID, "payload.json", {
        "schema_version": 1,
        "training_task_id": TARGET_TASK_ID,
        "project_id": project_id,
    })
    repository.create(TaskRecord.new(
        PREP_TASK_ID,
        project_id,
        TaskKind.TRAINING_PREPARE,
        "payload.json",
        f"training-prepare:{project_id}",
        required_capabilities=("training.prepare",),
    ))
    return repository, artifacts, TARGET_TASK_ID


def _freeze_through_prepare(
    data_dir: Path,
    project_id: str = "p1",
    *,
    train_ids: tuple[str, ...],
    test_ids: tuple[str, ...] = (),
    updates: dict | None = None,
) -> tuple[dict, dict, ArtifactStore, TaskRepository, str]:
    """Real prepare handler freeze (the same phase exercised by the integration suite)."""
    repository, artifacts, target_id = _runtime(
        data_dir, project_id, train_ids=train_ids, test_ids=test_ids,
    )
    payload = artifacts.read_json(target_id, repository.get(target_id).payload_ref)
    payload.update(schema_version=4, training_input_state="PREPARING", train_labels=["fire"])
    payload.update(updates or {})
    artifacts.atomic_write_json(target_id, "payload.json", payload)
    handler = RemoteTrainingPrepareHandler(data_dir)
    context = SimpleNamespace(
        artifacts=artifacts,
        repository=repository,
        run_owned=lambda operation: operation(),
    )
    updated = handler._freeze_request_contract(context, repository.get(target_id), payload)
    frozen = artifacts.read_json(target_id, updated["input_freeze_ref"])
    return updated, frozen, artifacts, repository, target_id


def _picker_client(data_dir: Path, project_id: str = "p1") -> TestClient:
    algorithm = {"id": ALGORITHM_ID, "versions": []}
    app = FastAPI()
    app.include_router(training_material_picker_router(
        lambda candidate: {"id": candidate} if candidate == project_id else None,
        lambda: data_dir,
        algorithm_provider=lambda _pid, algorithm_id: (
            algorithm if str(algorithm_id) == ALGORITHM_ID else None
        ),
        actor_provider=lambda _request, _project_id: {"actor_id": "w10-tester"},
    ))
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Project pool vs algorithm pool in training selection
# ---------------------------------------------------------------------------


def test_algorithm_pool_scope_gates_negative_filters_and_selection_union(tmp_path):
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir, count=5)
    project = _project_path(data_dir, project_id)
    _paint_fire_gt(project, ["image-0", "image-1", "image-2", "image-3", "image-4"])
    repository = MaterialRepository(project)
    pool = NegativePool(repository)
    category = pool.category(name="反光")["id"]
    # image-0 and image-1 are project-pool members; only image-1 is associated
    # with the target algorithm.
    pool.members(["image-0", "image-1"], category_ids=[category])
    pool.members(["image-1"], algorithm_id=ALGORITHM_ID)
    assert pool.candidate_ids([category]) == ["image-0", "image-1"]
    assert pool.candidate_ids([category], algorithm_id=ALGORITHM_ID) == ["image-1"]

    client = _picker_client(data_dir, project_id)
    endpoint = f"/api/v62/projects/{project_id}/training-materials"

    legacy = client.get(endpoint, params=[
        ("negative_pool_only", "true"), ("negative_category_id", category),
    ])
    assert legacy.status_code == 200, legacy.text
    assert {row["id"] for row in legacy.json()["items"]} == {"image-0", "image-1"}

    scoped = client.get(endpoint, params=[
        ("negative_pool_only", "true"), ("negative_category_id", category),
        ("algorithm_asset_id", ALGORITHM_ID),
    ])
    assert scoped.status_code == 200, scoped.text
    assert {row["id"] for row in scoped.json()["items"]} == {"image-1"}

    bulk = client.post(endpoint + "/bulk-selection", json={
        "negative_pool_only": True,
        "negative_category_ids": [category],
        "algorithm_asset_id": ALGORITHM_ID,
        "history_policy": "include_history",
    })
    assert bulk.status_code == 200, bulk.text
    assert set(bulk.json()["items"]) == {"image-1"}

    union_endpoint = endpoint + "/selection-union"
    common = {
        "algorithm_asset_id": ALGORITHM_ID,
        "role": "train",
        "positive_ids": ["image-2"],
    }
    rejected = client.post(union_endpoint, json={**common, "negative_ids": ["image-0"]})
    assert rejected.status_code == 422, rejected.text
    assert "负样本" in rejected.json()["detail"]
    accepted = client.post(union_endpoint, json={**common, "negative_ids": ["image-1"]})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["count"] == 2


# ---------------------------------------------------------------------------
# 2. Human negative confirmation -> formal GT -> counts -> idempotency
# ---------------------------------------------------------------------------


def test_human_negative_confirmation_writes_formal_gt_and_training_counts(client, monkeypatch):
    import app as platform_app

    project = client.post("/api/projects", json={
        "name": "w10-negative-" + uuid.uuid4().hex[:8],
        "labels": [{"code": "fire", "class_id": 0}, {"code": "smoke", "class_id": 1}],
    }).json()
    project_id = project["id"]
    uploaded = []
    for name, color in (("positive", "red"), ("negative", "blue"), ("pending", "green")):
        stream = io.BytesIO()
        Image.new("RGB", (96, 80), color).save(stream, format="PNG")
        image = client.post(
            f"/api/projects/{project_id}/images",
            files=[("files", (f"{name}.png", stream.getvalue(), "image/png"))],
            data={"dataset_id": "default"},
        ).json()["uploaded"][0]
        uploaded.append(image)
    platform_app.material_store(project_id).patch({
        image["id"]: {"processing_status": "processed"} for image in uploaded
    })
    positive, negative, pending = uploaded
    current = client.get(
        f"/api/projects/{project_id}/annotations/{positive['id']}"
    ).json()
    saved = client.post(
        f"/api/projects/{project_id}/annotations/{positive['id']}",
        json={
            "boxes": [dict(FIRE_BOX)],
            "annotation_state": "annotated",
            "expected_version": current["annotation"]["version"],
            "source_content_sha256": positive["content_sha256"],
            "reviewed_label_codes": ["fire"],
        },
    )
    assert saved.status_code == 200, saved.text

    monkeypatch.setattr(
        platform_app, "list_algorithms_internal",
        lambda _project_id: [{"id": "algorithm-w10", "versions": []}],
    )
    before = client.get(
        f"/api/projects/{project_id}/annotations/{negative['id']}"
    ).json()["annotation"]
    review = client.post(
        f"/api/v62/projects/{project_id}/training-materials/review-negative",
        json={
            "algorithm_asset_id": "algorithm-w10",
            "train_labels": ["fire"],
            "model": "yolo11n.pt",
            "confirmed": True,
            "items": [{
                "image_id": negative["id"],
                "expected_version": before["version"],
                "source_content_sha256": negative["content_sha256"],
            }],
        },
    )
    assert review.status_code == 200, review.text
    assert review.json()["succeeded"] == [negative["id"]]
    formal = client.get(
        f"/api/projects/{project_id}/annotations/{negative['id']}"
    ).json()["annotation"]
    assert formal["annotation_state"] == "confirmed_empty"
    assert formal["boxes"] == []
    assert formal["annotation_scope"] == ["fire"]
    evidence = platform_app._v50_annotation_repository(project_id).negative_review_evidence(
        negative["id"], before["version"], "isolated-test", ["fire"],
        negative["content_sha256"],
    )
    assert evidence and evidence["annotation_version"] == formal["version"]
    assert evidence["reviewed_at"]

    selection = [positive["id"], negative["id"], pending["id"]]
    base = {
        "algorithm_asset_id": "algorithm-w10",
        "train_labels": ["fire"],
        "model": "yolo11n.pt",
        "train_image_ids": selection,
    }
    preview = client.post(
        f"/api/v62/projects/{project_id}/training-materials/negative-preview",
        json=base,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["counts"] == {
        "positive": 1, "confirmed_negative": 1,
        "pending_negative": 1, "pending_review": 0,
    }
    assert preview.json()["pending_count"] == 1

    confirm_url = f"/api/v62/projects/{project_id}/training-materials/confirm-negatives"
    confirmed = client.post(confirm_url, json={
        **base, "confirmed": True, "proof_digest": preview.json()["proof_digest"],
    })
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["confirmed_count"] == 1
    version_after_first = client.get(
        f"/api/projects/{project_id}/annotations/{negative['id']}"
    ).json()["annotation"]["version"]

    again = client.post(
        f"/api/v62/projects/{project_id}/training-materials/negative-preview", json=base,
    )
    assert again.status_code == 200, again.text
    assert again.json()["counts"]["pending_negative"] == 0
    repeated = client.post(confirm_url, json={
        **base, "confirmed": True, "proof_digest": again.json()["proof_digest"],
    })
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["confirmed_count"] == 0
    version_after_second = client.get(
        f"/api/projects/{project_id}/annotations/{negative['id']}"
    ).json()["annotation"]["version"]
    assert version_after_second == version_after_first


# ---------------------------------------------------------------------------
# 3. Duplicate membership never inflates either pool tier
# ---------------------------------------------------------------------------


def test_negative_pool_membership_is_deduplicated_in_both_tiers(tmp_path):
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir, count=3)
    pool = NegativePool(MaterialRepository(_project_path(data_dir, project_id)))
    category = pool.category(name="反光")["id"]

    first = pool.members(["image-0"], category_ids=[category], report_counts=True)
    assert first == {"affected": 1, "added": 1, "already_present": 0}
    second = pool.members(["image-0"], category_ids=[category], report_counts=True)
    assert second == {"affected": 1, "added": 0, "already_present": 1}

    algorithm_first = pool.members(
        ["image-0"], algorithm_id=ALGORITHM_ID, report_counts=True,
    )
    assert algorithm_first == {"affected": 1, "added": 1, "already_present": 0}
    algorithm_second = pool.members(
        ["image-0"], algorithm_id=ALGORITHM_ID, report_counts=True,
    )
    assert algorithm_second == {"affected": 1, "added": 0, "already_present": 1}

    duplicated_ids = pool.members(
        ["image-1", "image-1"], category_ids=[category], report_counts=True,
    )
    assert duplicated_ids["affected"] == 1

    assert pool.candidate_ids([category]) == ["image-0", "image-1"]
    assert pool.candidate_ids([category], algorithm_id=ALGORITHM_ID) == ["image-0"]
    assert pool.query(category_ids=[category])["total"] == 2


# ---------------------------------------------------------------------------
# 4. Legal negative enters the real frozen snapshot/materialized dataset
# ---------------------------------------------------------------------------


def test_confirmed_empty_negative_enters_frozen_snapshot_and_materialized_dataset(tmp_path):
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir, count=5)
    project = _project_path(data_dir, project_id)
    for image_id in ("image-0", "image-2", "image-3"):
        _set_annotation(project, image_id, boxes=[FIRE_BOX], scope=["fire"])
    _set_annotation(project, "image-1", state="confirmed_empty", scope=["fire"])
    _set_annotation(project, "image-4", boxes=[FIRE_BOX], scope=["fire"])
    # M13-A: the explicit formal negative proves target-algorithm ownership via
    # the existing algorithm-tier negative pool; GT and roles stay unchanged.
    _add_to_algorithm_pool(project, ["image-1"])
    repository = MaterialRepository(project)
    source_bytes = {
        row["id"]: (project / "uploads" / row["stored_name"]).read_bytes()
        for row in repository.get_many(
            ["image-0", "image-1", "image-2", "image-3", "image-4"]
        )
    }

    _, frozen, _, _, _ = _freeze_through_prepare(
        data_dir, project_id,
        train_ids=("image-0", "image-1", "image-2", "image-3"),
        test_ids=("image-4",),
    )
    split = frozen["split"]
    rows, schema, manifest, snapshot = training_tasks.resolve_training_input_freeze(
        frozen,
        SplitRequest(
            mode=SplitMode(split["mode"]),
            train_image_ids=tuple(split["train_image_ids"]),
            test_image_ids=tuple(split["test_image_ids"]),
            validation_percent=split["validation_percent"],
            experiment_percent=split["experiment_percent"],
        ),
        seed=split["seed"],
    )
    assert [item["code"] for item in schema] == ["fire"]
    frozen_negative = next(
        item for item in frozen["images"] if item["id"] == "image-1"
    )
    assert frozen_negative["annotation_state"] == "confirmed_empty"
    assert frozen_negative["boxes"] == []
    snapshot_by_id = {item["image_id"]: item for item in snapshot["images"]}
    negative = snapshot_by_id["image-1"]
    assert negative["annotation_state"] == "confirmed_empty"
    assert negative["box_count"] == 0
    assert negative["annotation_scope"] == ["fire"]
    assert snapshot["negative_scope_counts"] == {"fire": 1}
    assert snapshot["negative_origin_counts"] == {"explicit_confirmed_empty": 1}
    assert all(item["image_id"] != "image-1" or item["role"] != "test"
               for item in snapshot["images"])

    output = training_tasks.materialize_portable_dataset(
        tmp_path / "materialized",
        snapshot,
        rows,
        lambda row: project / "uploads" / row["stored_name"],
        safety_reserve_bytes=0,
    )
    role = negative["role"]
    assert (output / f"dataset/labels/{role}/image-1.txt").read_text() == ""
    assert (output / f"dataset/images/{role}/image-1.jpg").read_bytes() == source_bytes["image-1"]
    exported = yaml.safe_load((output / "dataset/data.yaml").read_text())
    assert exported["names"] == {0: "fire"}


# ---------------------------------------------------------------------------
# 5. First-training pure negative rejected with code; base iteration allowed
# ---------------------------------------------------------------------------


def _negative_only_project(tmp_path: Path, *, count: int = 4) -> tuple[Path, str]:
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir, count=count)
    project = _project_path(data_dir, project_id)
    for index in range(count):
        _set_annotation(project, f"image-{index}", state="confirmed_empty", scope=["fire"])
    return project, project_id


def test_first_training_pure_negative_is_rejected_with_machine_readable_code(tmp_path):
    project, _ = _negative_only_project(tmp_path)
    split = SplitRequest(
        mode=SplitMode.INDEPENDENT_TEST_SET,
        train_image_ids=("image-0", "image-1", "image-2"),
        test_image_ids=("image-3",),
        validation_percent=50,
    )
    with pytest.raises(training_tasks.TrainingAdmissionError) as captured:
        training_tasks.freeze_training_inputs(project, split, seed=7)
    assert captured.value.code == "TRAINING_FIRST_TRAINING_REQUIRES_POSITIVE"
    assert FIRST_TRAINING_POSITIVE_MESSAGE in str(captured.value)
    # The exception type stays a ValueError for every existing caller.
    assert isinstance(captured.value, ValueError)


def test_negative_only_iteration_with_base_version_is_allowed(tmp_path):
    project, _project_id = _negative_only_project(tmp_path)
    split = SplitRequest(
        mode=SplitMode.INDEPENDENT_TEST_SET,
        train_image_ids=("image-0", "image-1", "image-2"),
        test_image_ids=("image-3",),
        validation_percent=50,
    )
    # Positive fire evidence belongs to the independent test image only; the
    # continuation is intentionally trained from the inherited checkpoint.
    _set_annotation(project, "image-3", boxes=[FIRE_BOX], scope=["fire"])
    # M13-A: the explicit negatives prove target-algorithm ownership through the
    # existing algorithm-tier pool, preserving the legal continuation path.
    _add_to_algorithm_pool(project, ["image-0", "image-1", "image-2"])
    contract = {
        "schema_version": 1,
        "strict_target_negative_scope": True,
        "training_projection_policy": training_tasks.TRAINING_PROJECTION_POLICY_V3,
        "algorithm_id": ALGORITHM_ID,
        "effective_label_codes": ["fire"],
        "effective_label_schema": [{"code": "fire", "class_id": 0,
                                    "canonical_project_class_id": 0}],
        "requested_new_label_codes": [],
        "base_training_mode": "previous_weights_init",
        "base_version_id": "v1",
        "base_version_name": "v1",
    }
    resolution = training_tasks.resolve_training_selection(project, split)
    from platform_core.training_label_tasks import project_training_rows
    projected = project_training_rows(list(resolution.effective_images), contract)
    frozen = training_tasks.freeze_training_inputs(
        project,
        split,
        seed=11,
        selection_resolution=resolution,
        effective_images=projected,
        label_schema_override=contract["effective_label_schema"],
        label_contract=contract,
    )
    quality = frozen["input_quality"]
    assert quality["role_box_counts"]["train"] == 0
    assert frozen["selection"]["selected_train_count"] == 3
    snapshot_negatives = [
        item for item in frozen["images"] if item["annotation_state"] == "confirmed_empty"
    ]
    assert len(snapshot_negatives) == 3
    assert any("纯负样本继续训练" in warning for warning in quality["warnings"])


def test_negative_only_iteration_with_new_label_is_forbidden_by_split_quality():
    """The base-version pure-negative rule keeps its typed split-quality code."""
    images = [
        {"id": "negative-1", "boxes": []},
        {"id": "validation-fire", "boxes": [{"label": "fire"}]},
        {"id": "test-1", "boxes": []},
    ]
    manifest = SimpleNamespace(ids={
        "train": ("negative-1",),
        "validation": ("validation-fire",),
        "test": ("test-1",),
    })
    contract = {
        "base_training_mode": "previous_weights_init",
        "base_version_id": "v1",
        "effective_label_codes": ["fire", "smoke"],
        "requested_new_label_codes": ["smoke"],
    }
    with pytest.raises(training_tasks.TrainingAdmissionError) as captured:
        training_tasks._training_split_quality(
            images,
            manifest,
            [{"code": "fire", "class_id": 0}, {"code": "smoke", "class_id": 1}],
            label_contract=contract,
        )
    assert captured.value.code == "TRAINING_NEGATIVE_ONLY_NEW_LABEL_FORBIDDEN"
    assert "纯负样本继续训练" in str(captured.value)


def _run_prepare_worker(
    data_dir: Path,
    project_id: str,
    *,
    train_ids: tuple[str, ...],
    test_ids: tuple[str, ...] = (),
    updates: dict | None = None,
) -> tuple[TaskRepository, ArtifactStore, str]:
    """Run the real TRAINING_PREPARE worker; return its durable failure evidence."""
    repository, artifacts, target_id = _runtime(
        data_dir, project_id, train_ids=train_ids, test_ids=test_ids,
    )
    payload = artifacts.read_json(target_id, repository.get(target_id).payload_ref)
    payload.update(schema_version=4, training_input_state="PREPARING")
    payload.update(updates or {})
    artifacts.atomic_write_json(target_id, "payload.json", payload)
    scheduler = Scheduler(
        repository,
        artifacts,
        "w10-m13a-preparer",
        {TaskKind.TRAINING_PREPARE: RemoteTrainingPrepareHandler(data_dir)},
        {"training.prepare"},
    )
    assert scheduler.run_once() is True
    return repository, artifacts, target_id


def test_real_prepare_first_training_pure_negative_returns_typed_code(tmp_path):
    """The full worker path (no freeze monkeypatch) yields the typed evidence."""
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir, count=4)
    project = _project_path(data_dir, project_id)
    for index in range(4):
        _set_annotation(project, f"image-{index}", state="confirmed_empty", scope=["fire"])
    repository, artifacts, target_id = _run_prepare_worker(
        data_dir, project_id,
        train_ids=("image-0", "image-1", "image-2"), test_ids=("image-3",),
    )
    target = repository.get(target_id)
    assert target is not None and target.status is TaskStatus.FAILED
    evidence = artifacts.read_json(target_id, "input-preparation-error.json", default={})
    assert evidence["code"] == "TRAINING_FIRST_TRAINING_REQUIRES_POSITIVE"
    assert evidence["input_freeze_created"] is False
    assert evidence["task_id"] == target_id
    assert not artifacts.artifact_path(target_id, "input-freeze.json").exists()


def test_real_prepare_first_training_with_positive_evidence_but_no_label_stays_plain_error(tmp_path):
    """Positive evidence exists: omitting labels remains an ordinary user error."""
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir, count=4)
    project = _project_path(data_dir, project_id)
    _paint_fire_gt(project, ["image-0", "image-1", "image-2"])
    _set_annotation(project, "image-3", state="confirmed_empty", scope=["fire"])
    repository, artifacts, target_id = _runtime(
        data_dir, project_id,
        train_ids=("image-0", "image-1", "image-2"), test_ids=("image-3",),
    )
    payload = artifacts.read_json(target_id, repository.get(target_id).payload_ref)
    payload.update(schema_version=4, training_input_state="PREPARING")
    artifacts.atomic_write_json(target_id, "payload.json", payload)
    handler = RemoteTrainingPrepareHandler(data_dir)
    context = SimpleNamespace(
        artifacts=artifacts, repository=repository, run_owned=lambda operation: operation(),
    )
    with pytest.raises(ValueError) as captured:
        handler._freeze_request_contract(context, repository.get(target_id), payload)
    assert not isinstance(captured.value, training_tasks.TrainingAdmissionError)
    assert "首次训练必须" in str(captured.value)
    assert not artifacts.artifact_path(target_id, "input-freeze.json").exists()


def test_prepare_maps_typed_admission_code_into_failure_evidence(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir, count=5)
    project = _project_path(data_dir, project_id)
    _paint_fire_gt(project, ["image-0", "image-1", "image-2", "image-3", "image-4"])

    def reject_freeze(*_args, **_kwargs):
        raise training_tasks.TrainingAdmissionError(
            "TRAINING_FIRST_TRAINING_REQUIRES_POSITIVE",
            FIRST_TRAINING_POSITIVE_MESSAGE,
        )

    monkeypatch.setattr(
        remote_training_tasks_module, "freeze_training_inputs", reject_freeze,
    )
    repository, artifacts, target_id = _runtime(
        data_dir, project_id,
        train_ids=("image-0", "image-1", "image-2", "image-3"),
        test_ids=("image-4",),
    )
    payload = artifacts.read_json(target_id, repository.get(target_id).payload_ref)
    payload.update(schema_version=4, training_input_state="PREPARING", train_labels=["fire"])
    artifacts.atomic_write_json(target_id, "payload.json", payload)
    scheduler = Scheduler(
        repository,
        artifacts,
        "w10-preparer",
        {TaskKind.TRAINING_PREPARE: RemoteTrainingPrepareHandler(data_dir)},
        {"training.prepare"},
    )
    assert scheduler.run_once() is True
    target = repository.get(target_id)
    assert target is not None and target.status is TaskStatus.FAILED
    evidence = artifacts.read_json(target_id, "input-preparation-error.json", default={})
    assert evidence["code"] == "TRAINING_FIRST_TRAINING_REQUIRES_POSITIVE"
    assert evidence["input_freeze_created"] is False
    assert evidence["task_id"] == target_id
    assert not artifacts.artifact_path(target_id, "input-freeze.json").exists()


# ---------------------------------------------------------------------------
# 6. Pending/unannotated material never reaches the frozen snapshot
# ---------------------------------------------------------------------------


def test_unannotated_material_is_excluded_from_freeze_with_readable_evidence(tmp_path):
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir, count=6)
    project = _project_path(data_dir, project_id)
    for image_id in ("image-0", "image-1", "image-2", "image-3", "image-4"):
        _set_annotation(project, image_id, boxes=[FIRE_BOX], scope=["fire"])
    _set_annotation(project, "image-5", state="unannotated", scope=[])
    # The direct freeze owner (the same one the prepare worker calls) preserves
    # the task intent but never converts an unannotated image into GT/negative.
    split = SplitRequest(
        mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
        train_image_ids=(
            "image-0", "image-1", "image-2", "image-3", "image-4", "image-5",
        ),
        experiment_percent=20,
        validation_percent=20,
    )
    frozen = training_tasks.freeze_training_inputs(project, split, seed=3)
    assert frozen["selection"]["pending_annotation_image_ids"] == ["image-5"]
    assert frozen["selection"]["pending_annotation_count"] == 1
    assert frozen["selection"]["selected_train_count"] == 6
    assert frozen["selection"]["effective_train_count"] == 5
    assert all(item["id"] != "image-5" for item in frozen["images"])
    assert sum(
        frozen["input_quality"]["class_coverage"][
            "role_confirmed_negative_image_counts"
        ].values()
    ) == 0
    # The real prepare admission rejects the same selection *before* a freeze is
    # published, with an existing machine code and per-image missing scope.
    repository, artifacts, target_id = _runtime(
        data_dir, project_id,
        train_ids=("image-0", "image-1", "image-2", "image-3", "image-4", "image-5"),
    )
    payload = artifacts.read_json(target_id, repository.get(target_id).payload_ref)
    payload.update(schema_version=4, training_input_state="PREPARING",
                   train_labels=["fire"], split_mode="random_test_from_training_pool",
                   experiment_percent=20, validation_percent=20)
    artifacts.atomic_write_json(target_id, "payload.json", payload)
    handler = RemoteTrainingPrepareHandler(data_dir)
    context = SimpleNamespace(
        artifacts=artifacts,
        repository=repository,
        run_owned=lambda operation: operation(),
    )
    with pytest.raises(RemoteTrainingPreparationError) as captured:
        handler._freeze_request_contract(context, repository.get(target_id), payload)
    assert captured.value.code == "TRAINING_MATERIAL_SCOPE_INCOMPATIBLE"
    evidence = artifacts.read_json(target_id, "input-preparation-error.json", default={})
    assert evidence["code"] == "TRAINING_MATERIAL_SCOPE_INCOMPATIBLE"
    assert evidence["input_freeze_created"] is False
    manifest = artifacts.read_json(target_id, "input-compatibility/manifest.json")
    assert manifest["issue_counts"].get("missing_annotation") == 1
    assert not artifacts.artifact_path(target_id, "input-freeze.json").exists()


def test_annotation_needs_review_material_blocks_freeze_with_existing_issue_code(tmp_path):
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir, count=3)
    project = _project_path(data_dir, project_id)
    _paint_fire_gt(project, ["image-0", "image-1", "image-2"])
    MaterialRepository(project).patch({
        "image-1": {
            "annotation_needs_review": True,
            "annotation_review_reason": "W10_TEST_STALE_REVIEW",
        },
    })
    repository, artifacts, target_id = _runtime(
        data_dir, project_id, train_ids=("image-0", "image-1"), test_ids=("image-2",),
    )
    payload = artifacts.read_json(target_id, repository.get(target_id).payload_ref)
    payload.update(schema_version=4, training_input_state="PREPARING", train_labels=["fire"])
    artifacts.atomic_write_json(target_id, "payload.json", payload)
    handler = RemoteTrainingPrepareHandler(data_dir)
    context = SimpleNamespace(
        artifacts=artifacts,
        repository=repository,
        run_owned=lambda operation: operation(),
    )
    with pytest.raises(RemoteTrainingPreparationError) as captured:
        handler._freeze_request_contract(context, repository.get(target_id), payload)
    assert captured.value.code == "TRAINING_MATERIAL_SCOPE_INCOMPATIBLE"
    evidence = artifacts.read_json(target_id, "input-preparation-error.json", default={})
    assert evidence["code"] == "TRAINING_MATERIAL_SCOPE_INCOMPATIBLE"
    manifest = artifacts.read_json(target_id, "input-compatibility/manifest.json")
    assert manifest["issue_counts"].get("stale_ground_truth") == 1
    assert not artifacts.artifact_path(target_id, "input-freeze.json").exists()


# ---------------------------------------------------------------------------
# 7. Negative scope labels never pollute the frozen class mapping
# ---------------------------------------------------------------------------


def test_negative_scope_extra_labels_do_not_pollute_frozen_class_mapping(tmp_path):
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir, count=4, labels=("fire", "smoke"))
    project = _project_path(data_dir, project_id)
    _set_annotation(project, "image-0", boxes=[FIRE_BOX], scope=["fire"])
    _set_annotation(project, "image-1", boxes=[FIRE_BOX], scope=["fire"])
    # The project-level negative scope contains smoke, but the training task's
    # effective schema only asks for fire.
    _set_annotation(project, "image-2", state="confirmed_empty", scope=["fire", "smoke"])
    _set_annotation(project, "image-3", boxes=[FIRE_BOX], scope=["fire"])
    # M13-A: the explicit negative owns target-algorithm attribution through the
    # existing algorithm pool; its scope still must not pollute the class map.
    _add_to_algorithm_pool(project, ["image-2"])
    _, frozen, _, _, _ = _freeze_through_prepare(
        data_dir, project_id,
        train_ids=("image-0", "image-1", "image-2"),
        test_ids=("image-3",),
    )
    assert [item["code"] for item in frozen["label_schema"]] == ["fire"]
    split = frozen["split"]
    rows, schema, _manifest, snapshot = training_tasks.resolve_training_input_freeze(
        frozen,
        SplitRequest(
            mode=SplitMode(split["mode"]),
            train_image_ids=tuple(split["train_image_ids"]),
            test_image_ids=tuple(split["test_image_ids"]),
            validation_percent=split["validation_percent"],
            experiment_percent=split["experiment_percent"],
        ),
        seed=split["seed"],
    )
    negative = next(item for item in snapshot["images"] if item["image_id"] == "image-2")
    assert negative["annotation_state"] == "confirmed_empty"
    assert negative["annotation_scope"] == ["fire"]
    assert snapshot["negative_scope_counts"] == {"fire": 1}
    assert [item["code"] for item in schema] == ["fire"]
    output = training_tasks.materialize_portable_dataset(
        tmp_path / "materialized-extra-labels",
        snapshot,
        rows,
        lambda row: project / "uploads" / row["stored_name"],
        safety_reserve_bytes=0,
    )
    exported = yaml.safe_load((output / "dataset/data.yaml").read_text())
    assert exported["names"] == {0: "fire"}


# ---------------------------------------------------------------------------
# 8. Real synchronous create exposes the typed admission code (409 unchanged)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _preinstalled_mother_model():
    """Same isolated preloaded .pt contract used by the existing training API suite."""
    import app as platform_app

    target = platform_app.DATA_DIR / "models" / "yolo11n.pt"
    target.parent.mkdir(parents=True, exist_ok=True)
    previous = target.read_bytes() if target.is_file() else None
    target.write_bytes(b"preinstalled-w10-test-mother" * 128)
    try:
        yield
    finally:
        if previous is None:
            target.unlink(missing_ok=True)
        else:
            target.write_bytes(previous)


def _training_ready_image(client, project_id: str, name: str, color: str) -> dict:
    stream = io.BytesIO()
    Image.new("RGB", (128, 128), color).save(stream, format="JPEG")
    image = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", (name, stream.getvalue(), "image/jpeg"))],
        data={"dataset_id": "default"},
    ).json()["uploaded"][0]
    annotation = client.get(
        f"/api/projects/{project_id}/annotations/{image['id']}"
    ).json()
    saved = client.post(
        f"/api/projects/{project_id}/annotations/{image['id']}",
        json={
            "boxes": [{"class_id": 0, "label": "fire", "x1": 10, "y1": 10,
                       "x2": 80, "y2": 80}],
            "expected_version": annotation["annotation"]["version"],
            "source_content_sha256": annotation["image"]["content_sha256"],
            "reviewed_label_codes": ["fire"],
        },
    )
    assert saved.status_code == 200, saved.text
    import app as platform_app
    platform_app.material_store(project_id).patch({
        image["id"]: {"processing_status": "processed"},
    })
    return image


def _training_negative_image(client, project_id: str, name: str, color: str) -> dict:
    stream = io.BytesIO()
    Image.new("RGB", (128, 128), color).save(stream, format="JPEG")
    image = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", (name, stream.getvalue(), "image/jpeg"))],
        data={"dataset_id": "default"},
    ).json()["uploaded"][0]
    annotation = client.get(
        f"/api/projects/{project_id}/annotations/{image['id']}"
    ).json()
    saved = client.post(
        f"/api/projects/{project_id}/annotations/{image['id']}",
        json={
            "boxes": [],
            "annotation_state": "confirmed_empty",
            "expected_version": annotation["annotation"]["version"],
            "source_content_sha256": annotation["image"]["content_sha256"],
            "reviewed_label_codes": ["fire"],
        },
    )
    assert saved.status_code == 200, saved.text
    import app as platform_app
    platform_app.material_store(project_id).patch({
        image["id"]: {"processing_status": "processed"},
    })
    return image


def _assert_no_training_task_leak(platform_app, project_id, task_id):
    repository = platform_app.shared_task_repository()
    assert repository.get(task_id) is None
    assert repository.get("trainprep_" + task_id) is None
    assert not (platform_app.project_dir(project_id) / "jobs" / task_id).exists()


def test_real_synchronous_create_first_training_pure_negative_returns_typed_code(client):
    """A real request with only confirmed_empty GT gets the earliest typed code."""
    import app as platform_app

    project = client.post("/api/projects", json={
        "name": "w10-sync-negative-" + uuid.uuid4().hex[:8],
        "labels": [{"code": "fire", "class_id": 0}],
    }).json()
    project_id = project["id"]
    negatives = [
        _training_negative_image(client, project_id, f"sync-neg-{index}.jpg", color)
        for index, color in enumerate(("red", "blue", "green"))
    ]
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "W10 sync negative admission", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    task_id = "train_" + hashlib.sha256(project_id.encode()).hexdigest()[:24]
    request = {
        "task_id": task_id,
        "framework": "ultralytics",
        "algorithm_asset_id": algorithm["id"],
        "model": "yolo11n.pt",
        "split_mode": "random_test_from_training_pool",
        "train_image_ids": [image["id"] for image in negatives],
        "test_image_ids": [],
        "experiment_percent": 20,
        "validation_percent": 20,
    }
    response = client.post(f"/api/v12/projects/{project_id}/train/start", json=request)
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["code"] == "TRAINING_FIRST_TRAINING_REQUIRES_POSITIVE"
    assert FIRST_TRAINING_CONTRACT_POSITIVE_MESSAGE in body["message"]
    assert body["message"] in body["detail"]
    _assert_no_training_task_leak(platform_app, project_id, task_id)


def test_real_synchronous_create_with_positive_evidence_but_no_label_stays_plain_error(client):
    """Positive evidence exists: the real request keeps the ordinary 409 detail."""
    import app as platform_app

    project = client.post("/api/projects", json={
        "name": "w10-sync-positive-" + uuid.uuid4().hex[:8],
        "labels": [{"code": "fire", "class_id": 0}],
    }).json()
    project_id = project["id"]
    positives = [
        _training_ready_image(client, project_id, f"sync-pos-{index}.jpg", color)
        for index, color in enumerate(("red", "blue", "green"))
    ]
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "W10 sync positive no label", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    task_id = "train_" + hashlib.sha256(project_id.encode()).hexdigest()[:24]
    request = {
        "task_id": task_id,
        "framework": "ultralytics",
        "algorithm_asset_id": algorithm["id"],
        "model": "yolo11n.pt",
        "split_mode": "random_test_from_training_pool",
        "train_image_ids": [image["id"] for image in positives],
        "test_image_ids": [],
        "experiment_percent": 20,
        "validation_percent": 20,
    }
    response = client.post(f"/api/v12/projects/{project_id}/train/start", json=request)
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["code"] != "TRAINING_FIRST_TRAINING_REQUIRES_POSITIVE"
    assert body["code"] == "CONFLICT"
    assert "首次训练必须" in body["message"]
    _assert_no_training_task_leak(platform_app, project_id, task_id)


# ---------------------------------------------------------------------------
# 9. Explicit formal negatives must prove target-algorithm ownership (M13-A)
# ---------------------------------------------------------------------------


def _attribution_project(
    tmp_path: Path, *, count: int = 5,
) -> tuple[Path, str, str]:
    """Positive train/test GT plus one explicit confirmed_empty negative."""
    data_dir = tmp_path / "data"
    project_id = _build_project(data_dir, count=count)
    project = _project_path(data_dir, project_id)
    _paint_fire_gt(project, ["image-0", "image-1", "image-2"])
    _set_annotation(project, "image-3", state="confirmed_empty", scope=["fire"])
    _set_annotation(project, "image-4", boxes=[FIRE_BOX], scope=["fire"])
    return project, project_id, data_dir


def test_prepare_rejects_project_pool_negative_without_algorithm_attribution(tmp_path):
    project, project_id, data_dir = _attribution_project(tmp_path)
    category = NegativePool(MaterialRepository(project)).category(name="反光")["id"]
    NegativePool(MaterialRepository(project)).members(
        ["image-3"], category_ids=[category],
    )
    repository, artifacts, target_id = _run_prepare_worker(
        data_dir, project_id,
        train_ids=("image-0", "image-1", "image-2", "image-3"),
        test_ids=("image-4",),
        updates={"train_labels": ["fire"]},
    )
    target = repository.get(target_id)
    assert target is not None and target.status is TaskStatus.FAILED
    evidence = artifacts.read_json(target_id, "input-preparation-error.json", default={})
    assert evidence["code"] == "TRAINING_NEGATIVE_ALGORITHM_ATTRIBUTION_MISSING"
    assert evidence["input_freeze_created"] is False
    assert not artifacts.artifact_path(target_id, "input-freeze.json").exists()


def test_prepare_allows_algorithm_pool_negative_and_freezes_correct_snapshot(tmp_path):
    project, project_id, data_dir = _attribution_project(tmp_path)
    _add_to_algorithm_pool(project, ["image-3"])
    _updated, frozen, _artifacts, _repository, _target_id = _freeze_through_prepare(
        data_dir, project_id,
        train_ids=("image-0", "image-1", "image-2", "image-3"),
        test_ids=("image-4",),
    )
    assert frozen["label_contract"]["algorithm_id"] == ALGORITHM_ID
    assert [item["code"] for item in frozen["label_schema"]] == ["fire"]
    split = frozen["split"]
    _rows, schema, _manifest, snapshot = training_tasks.resolve_training_input_freeze(
        frozen,
        SplitRequest(
            mode=SplitMode(split["mode"]),
            train_image_ids=tuple(split["train_image_ids"]),
            test_image_ids=tuple(split["test_image_ids"]),
            validation_percent=split["validation_percent"],
            experiment_percent=split["experiment_percent"],
        ),
        seed=split["seed"],
    )
    assert [item["code"] for item in schema] == ["fire"]
    frozen_negative = next(
        item for item in frozen["images"] if item["id"] == "image-3"
    )
    assert frozen_negative["annotation_state"] == "confirmed_empty"
    assert frozen_negative["boxes"] == []
    assert frozen_negative["annotation_scope"] == ["fire"]
    negative = next(item for item in snapshot["images"] if item["image_id"] == "image-3")
    assert negative["role"] == "train"
    assert negative["annotation_state"] == "confirmed_empty"
    assert negative["box_count"] == 0
    assert negative["annotation_scope"] == ["fire"]
    assert snapshot["negative_origin_counts"] == {"explicit_confirmed_empty": 1}


def test_prepare_allows_algorithm_context_negative_receipt_and_freezes_snapshot(tmp_path):
    project, project_id, data_dir = _attribution_project(tmp_path)
    receipt_ids = _confirm_algorithm_negative_receipts(project, ["image-3"])
    assert receipt_ids
    _updated, frozen, _artifacts, _repository, _target_id = _freeze_through_prepare(
        data_dir, project_id,
        train_ids=("image-0", "image-1", "image-2", "image-3"),
        test_ids=("image-4",),
    )
    contract = frozen["label_contract"]
    assert contract["algorithm_id"] == ALGORITHM_ID
    assert contract["training_projection_policy"] == (
        training_tasks.TRAINING_PROJECTION_POLICY_V4
    )
    receipt_images = {
        str(item.get("image_id") or "")
        for item in contract.get("task_negative_confirmations") or []
    }
    assert "image-3" in receipt_images
    split = frozen["split"]
    _rows, _schema, _manifest, snapshot = training_tasks.resolve_training_input_freeze(
        frozen,
        SplitRequest(
            mode=SplitMode(split["mode"]),
            train_image_ids=tuple(split["train_image_ids"]),
            test_image_ids=tuple(split["test_image_ids"]),
            validation_percent=split["validation_percent"],
            experiment_percent=split["experiment_percent"],
        ),
        seed=split["seed"],
    )
    negative = next(item for item in snapshot["images"] if item["image_id"] == "image-3")
    assert negative["role"] == "train"
    assert negative["annotation_state"] == "confirmed_empty"
    assert negative["box_count"] == 0
    assert frozen["images"][3]["annotation_state"] == "confirmed_empty"


def test_prepare_rejects_negative_receipt_from_another_algorithm_context(tmp_path):
    project, project_id, data_dir = _attribution_project(tmp_path)
    assert _confirm_algorithm_negative_receipts(
        project, ["image-3"], algorithm_id="algorithm-other",
    )
    repository, artifacts, target_id = _run_prepare_worker(
        data_dir, project_id,
        train_ids=("image-0", "image-1", "image-2", "image-3"),
        test_ids=("image-4",),
        updates={"train_labels": ["fire"]},
    )
    target = repository.get(target_id)
    assert target is not None and target.status is TaskStatus.FAILED
    evidence = artifacts.read_json(target_id, "input-preparation-error.json", default={})
    assert evidence["code"] == "TRAINING_NEGATIVE_ALGORITHM_ATTRIBUTION_MISSING"
    assert evidence["input_freeze_created"] is False
    assert not artifacts.artifact_path(target_id, "input-freeze.json").exists()


def test_freeze_without_declared_algorithm_keeps_unattributed_negative_allowed(tmp_path):
    """Historical/ordinary contract without algorithm_id keeps the old behaviour."""
    project, project_id, data_dir = _attribution_project(tmp_path)
    split = SplitRequest(
        mode=SplitMode.INDEPENDENT_TEST_SET,
        train_image_ids=("image-0", "image-1", "image-2", "image-3"),
        test_image_ids=("image-4",),
        validation_percent=25,
    )
    contract = {
        "schema_version": 1,
        "strict_target_negative_scope": True,
        "training_projection_policy": training_tasks.TRAINING_PROJECTION_POLICY_V3,
        "effective_label_codes": ["fire"],
        "effective_label_schema": [{"code": "fire", "class_id": 0,
                                    "canonical_project_class_id": 0}],
        "requested_new_label_codes": [],
        "base_training_mode": "mother_model_init",
    }
    resolution = training_tasks.resolve_training_selection(
        project, split, label_contract=contract,
    )
    from platform_core.training_label_tasks import project_training_rows
    projected = project_training_rows(list(resolution.effective_images), contract)
    frozen = training_tasks.freeze_training_inputs(
        project,
        split,
        seed=5,
        selection_resolution=resolution,
        effective_images=projected,
        label_schema_override=contract["effective_label_schema"],
        label_contract=contract,
    )
    frozen_negative = next(
        item for item in frozen["images"] if item["id"] == "image-3"
    )
    assert frozen_negative["annotation_state"] == "confirmed_empty"
    assert frozen_negative["annotation_scope"] == ["fire"]
    assert "algorithm_id" not in (frozen.get("label_contract") or {}) or not frozen[
        "label_contract"
    ].get("algorithm_id")


def test_picker_selection_union_accepts_algorithm_context_receipt_for_negative(tmp_path):
    project, project_id, data_dir = _attribution_project(tmp_path, count=5)
    category = NegativePool(MaterialRepository(project)).category(name="反光")["id"]
    NegativePool(MaterialRepository(project)).members(
        ["image-3"], category_ids=[category],
    )
    assert _confirm_algorithm_negative_receipts(project, ["image-3"])
    client = _picker_client(data_dir, project_id)
    payload = {
        "algorithm_asset_id": ALGORITHM_ID,
        "role": "train",
        "positive_ids": ["image-0", "image-1"],
        "negative_ids": ["image-3"],
        "train_labels": ["fire"],
        "model": "yolo11n.pt",
    }
    response = client.post(
        f"/api/v62/projects/{project_id}/training-materials/selection-union",
        json=payload,
    )
    assert response.status_code == 200, response.text
    assert response.json()["count"] == 3
    from platform_core.training_selection_reference import (
        read_selection,
        selection_context,
    )
    frozen_ids = set(read_selection(
        data_dir,
        response.json()["selection_ref"],
        selection_context(data_dir, project_id, payload),
    ))
    assert frozen_ids == {"image-0", "image-1", "image-3"}


def test_picker_union_explicit_ids_frozen_selection_and_worker_contract_agree(tmp_path):
    project, project_id, data_dir = _attribution_project(tmp_path)
    _add_to_algorithm_pool(project, ["image-3"])
    client = _picker_client(data_dir, project_id)
    picker_payload = {
        "algorithm_asset_id": ALGORITHM_ID,
        "role": "train",
        "positive_ids": ["image-0", "image-1"],
        "negative_ids": ["image-3"],
        "train_labels": ["fire"],
        "model": "yolo11n.pt",
    }
    union = client.post(
        f"/api/v62/projects/{project_id}/training-materials/selection-union",
        json=picker_payload,
    )
    assert union.status_code == 200, union.text
    from platform_core.training_selection_reference import (
        read_selection,
        selection_context,
    )
    picker_ids = set(read_selection(
        data_dir,
        union.json()["selection_ref"],
        selection_context(data_dir, project_id, picker_payload),
    ))
    explicit_ids = {"image-0", "image-1", "image-3"}
    assert picker_ids == explicit_ids

    updated, frozen, _artifacts, _repository, _target_id = _freeze_through_prepare(
        data_dir, project_id,
        train_ids=("image-0", "image-1", "image-3"),
        test_ids=("image-4",),
    )
    assert set(updated["selected_train_image_ids"]) == explicit_ids
    assert set(updated["train_image_ids"]) == explicit_ids
    assert updated["input_freeze_id"] == frozen["input_freeze_id"]
    assert updated["snapshot_id"] == frozen["snapshot_id"]
    assert set(frozen["selection"]["selected_train_image_ids"]) == explicit_ids
    assert updated["selection_counts"]["selected_train_count"] == 3
    split = frozen["split"]
    _rows, _schema, _manifest, snapshot = training_tasks.resolve_training_input_freeze(
        frozen,
        SplitRequest(
            mode=SplitMode(split["mode"]),
            train_image_ids=tuple(split["train_image_ids"]),
            test_image_ids=tuple(split["test_image_ids"]),
            validation_percent=split["validation_percent"],
            experiment_percent=split["experiment_percent"],
        ),
        seed=split["seed"],
    )
    roles = {item["image_id"]: item["role"] for item in snapshot["images"]}
    assert roles["image-3"] == "train"
    negative = next(item for item in snapshot["images"] if item["image_id"] == "image-3")
    assert negative["annotation_state"] == "confirmed_empty"
    assert negative["box_count"] == 0
    assert set(roles) == explicit_ids | {"image-4"}
