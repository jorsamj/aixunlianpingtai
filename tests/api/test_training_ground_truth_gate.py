import pytest

from platform_core.snapshots import build_snapshot, is_training_ground_truth
from platform_core.training_splits import SplitManifest, SplitMode, _processed


CONTENT_SHA = "a" * 64


def _manifest(image_id: str) -> SplitManifest:
    return SplitManifest(
        mode=SplitMode.INDEPENDENT_TEST_SET,
        ids={"train": (image_id,), "validation": (), "test": ()},
        counts={"train": 1, "validation": 0, "test": 0, "total": 1},
        requested={},
        actual_ratios={},
        groups={image_id: image_id},
        content_hashes={image_id: CONTENT_SHA},
        test_seed=0,
        validation_seed=0,
    )


def test_cleaned_unannotated_material_is_not_training_ground_truth():
    row = {
        "id": "cleaned-unannotated",
        "annotation_state": "unannotated",
        "annotated": False,
        "boxes": [],
        "processing_status": "processed",
        "cleaned_at": "2026-09-28T00:00:00Z",
        "clean_skipped": True,
        "content_sha256": CONTENT_SHA,
    }

    assert _processed(row) is False
    with pytest.raises(ValueError, match="正式标注 Ground Truth"):
        build_snapshot(
            [row],
            _manifest(row["id"]),
            [{"code": "smoke", "class_id": 0}],
        )


def test_confirmed_empty_remains_an_explicit_training_negative():
    row = {
        "id": "confirmed-empty",
        "annotation_state": "confirmed_empty",
        "annotation_scope": ["*"],
        "annotated": True,
        "boxes": [],
        "processing_status": "processed",
        "content_sha256": CONTENT_SHA,
    }

    assert _processed(row) is True
    snapshot = build_snapshot(
        [row],
        _manifest(row["id"]),
        [{"code": "smoke", "class_id": 0}],
    )

    frozen = snapshot["images"][0]
    assert frozen["annotation_state"] == "confirmed_empty"
    assert frozen["annotation_scope"] == ["smoke"]
    assert frozen["box_count"] == 0


def test_training_label_schema_compacts_active_classes_without_losing_canonical_id(tmp_path):
    import json

    from platform_core.training_tasks import _label_schema

    (tmp_path / "meta.json").write_text(
        json.dumps(
            {
                "label_meta": [
                    {"code": "retired", "status": "inactive", "class_id": 0},
                    {"code": "smoke", "status": "active", "class_id": 1},
                    {"code": "fire", "status": "active", "class_id": 7},
                ]
            }
        ),
        encoding="utf-8",
    )

    schema = _label_schema(tmp_path)

    assert [row["code"] for row in schema] == ["smoke", "fire"]
    assert [row["class_id"] for row in schema] == [0, 1]
    assert [row["canonical_project_class_id"] for row in schema] == [1, 7]


@pytest.mark.parametrize(
    ("state", "boxes", "eligible"),
    [
        ("annotated", [{"label": "smoke"}], True),
        ("confirmed_empty", [], True),
        ("unannotated", [], False),
        ("annotated", [], False),
        ("confirmed_empty", [{"label": "smoke"}], False),
    ],
)
def test_training_ground_truth_eligibility_is_explicit(state, boxes, eligible):
    assert is_training_ground_truth(state, boxes) is eligible


def test_legacy_include_empty_cannot_reenable_unannotated_training_source():
    import inspect
    import app as app_module

    source = inspect.getsource(app_module.dataset_items_by_split)
    assert "is_training_ground_truth" in source
    assert "not include_empty" not in source

    source = inspect.getsource(app_module.build_yolo_dataset_v44)
    assert source.count("is_training_ground_truth") >= 2
    assert "not payload.include_empty" not in source


def test_selected_training_material_reads_are_bounded(monkeypatch, tmp_path):
    import platform_core.training_tasks as training_tasks

    image_ids = [f"image-{index}" for index in range(1001)]

    class Materials:
        def __init__(self):
            self.calls = []

        def get_many(self, ids):
            ids = tuple(ids)
            assert len(ids) <= 500
            self.calls.append(len(ids))
            return [
                {
                    "id": image_id,
                    "content_sha256": "a" * 64,
                    "size_bytes": 1,
                    "width": 10,
                    "height": 10,
                }
                for image_id in ids
            ]

    class Annotations:
        def __init__(self, _project):
            pass

        def get_many(self, ids):
            assert len(ids) <= 500
            return {
                image_id: {
                    "annotation_state": "confirmed_empty",
                    "annotation_scope": ["smoke"],
                    "content_digest": "b" * 64,
                    "boxes": [],
                }
                for image_id in ids
            }

    materials = Materials()
    monkeypatch.setattr(training_tasks, "AnnotationRepository", Annotations)

    selected = training_tasks._selected_project_images(
        materials,
        tmp_path,
        image_ids,
    )

    assert len(selected) == 1001
    assert materials.calls == [500, 500, 1]


def _freeze_rows(image_ids):
    rows = []
    for index, image_id in enumerate(image_ids, start=1):
        rows.append(
            {
                "id": image_id,
                "dataset_id": "default",
                "filename": f"{image_id}.jpg",
                "stored_name": f"{image_id}.jpg",
                "storage_source_id": "default_local",
                "storage_type": "local",
                "object_key": f"uploads/{image_id}.jpg",
                "content_sha256": f"{index:064x}",
                "size_bytes": 100 + index,
                "width": 640,
                "height": 480,
                "group_id": f"group-{image_id}",
                "annotation_state": "annotated",
                "annotation_scope": ["smoke"],
                "annotation_hash": f"{index + 100:064x}",
                "annotated": True,
                "boxes": [
                    {
                        "label": "smoke",
                        "class_id": 0,
                        "x1": 10,
                        "y1": 10,
                        "x2": 100,
                        "y2": 100,
                    }
                ],
            }
        )
    return rows


def test_training_input_freeze_survives_later_gt_and_label_changes(monkeypatch, tmp_path):
    import platform_core.training_tasks as training_tasks
    from platform_core.training_splits import SplitRequest

    train_ids = ("train-1", "train-2", "train-3", "train-4")
    test_ids = ("test-1",)
    rows = _freeze_rows((*train_ids, *test_ids))
    live_schema = [
        {
            "code": "smoke",
            "class_id": 0,
            "canonical_project_class_id": 4,
            "status": "active",
        }
    ]

    monkeypatch.setattr(training_tasks, "MaterialRepository", lambda _project: object())
    monkeypatch.setattr(
        training_tasks,
        "_selected_project_images",
        lambda _materials, _project, image_ids: [
            dict(next(row for row in rows if row["id"] == image_id))
            for image_id in image_ids
        ],
    )
    monkeypatch.setattr(training_tasks, "_label_schema", lambda _project: [dict(x) for x in live_schema])

    split = SplitRequest(
        mode=SplitMode.INDEPENDENT_TEST_SET,
        train_image_ids=train_ids,
        test_image_ids=test_ids,
        validation_percent=25,
    )
    frozen = training_tasks.freeze_training_inputs(tmp_path, split, seed=17)
    frozen_snapshot_id = frozen["snapshot_id"]
    frozen_revision_id = frozen["dataset_revision_id"]
    frozen_id = frozen["input_freeze_id"]

    # Simulate edits made after the user clicked "create training".
    rows[0]["boxes"][0]["label"] = "fire"
    rows[0]["annotation_scope"] = ["fire"]
    live_schema[0]["code"] = "fire"

    images, schema, _manifest, snapshot = training_tasks.resolve_training_input_freeze(
        frozen,
        split,
        seed=17,
    )

    assert frozen["input_freeze_id"] == frozen_id
    assert snapshot["snapshot_id"] == frozen_snapshot_id
    assert snapshot["dataset_revision_id"] == frozen_revision_id
    assert schema[0]["code"] == "smoke"
    assert images[0]["boxes"][0]["label"] == "smoke"


def test_training_input_freeze_rejects_tampering(monkeypatch, tmp_path):
    import copy
    import platform_core.training_tasks as training_tasks
    from platform_core.training_splits import SplitRequest

    train_ids = ("train-1", "train-2", "train-3", "train-4")
    test_ids = ("test-1",)
    rows = _freeze_rows((*train_ids, *test_ids))
    monkeypatch.setattr(training_tasks, "MaterialRepository", lambda _project: object())
    monkeypatch.setattr(
        training_tasks,
        "_selected_project_images",
        lambda _materials, _project, image_ids: [
            dict(next(row for row in rows if row["id"] == image_id))
            for image_id in image_ids
        ],
    )
    monkeypatch.setattr(
        training_tasks,
        "_label_schema",
        lambda _project: [
            {
                "code": "smoke",
                "class_id": 0,
                "canonical_project_class_id": 4,
                "status": "active",
            }
        ],
    )
    split = SplitRequest(
        mode=SplitMode.INDEPENDENT_TEST_SET,
        train_image_ids=train_ids,
        test_image_ids=test_ids,
        validation_percent=25,
    )
    frozen = training_tasks.freeze_training_inputs(tmp_path, split, seed=17)
    tampered = copy.deepcopy(frozen)
    tampered["images"][0]["boxes"][0]["label"] = "fire"

    with pytest.raises(ValueError, match="freeze digest mismatch"):
        training_tasks.resolve_training_input_freeze(tampered, split, seed=17)


def test_training_input_freeze_requires_indexed_content_identity(monkeypatch, tmp_path):
    import platform_core.training_tasks as training_tasks
    from platform_core.training_splits import SplitRequest

    train_ids = ("train-1", "train-2", "train-3", "train-4")
    test_ids = ("test-1",)
    rows = _freeze_rows((*train_ids, *test_ids))
    rows[2]["content_sha256"] = ""
    monkeypatch.setattr(training_tasks, "MaterialRepository", lambda _project: object())
    monkeypatch.setattr(
        training_tasks,
        "_selected_project_images",
        lambda _materials, _project, image_ids: [
            dict(next(row for row in rows if row["id"] == image_id))
            for image_id in image_ids
        ],
    )
    monkeypatch.setattr(
        training_tasks,
        "_label_schema",
        lambda _project: [{"code": "smoke", "class_id": 0, "status": "active"}],
    )
    split = SplitRequest(
        mode=SplitMode.INDEPENDENT_TEST_SET,
        train_image_ids=train_ids,
        test_image_ids=test_ids,
        validation_percent=25,
    )

    with pytest.raises(ValueError, match="缺少可冻结的 SHA256"):
        training_tasks.freeze_training_inputs(tmp_path, split, seed=17)


def test_training_input_freeze_rejects_all_negative_detection_training(monkeypatch, tmp_path):
    import platform_core.training_tasks as training_tasks
    from platform_core.training_splits import SplitRequest

    train_ids = ("train-1", "train-2", "train-3", "train-4")
    test_ids = ("test-1",)
    rows = _freeze_rows((*train_ids, *test_ids))
    for row in rows:
        row["annotation_state"] = "confirmed_empty"
        row["annotation_scope"] = ["smoke"]
        row["boxes"] = []

    monkeypatch.setattr(training_tasks, "MaterialRepository", lambda _project: object())
    monkeypatch.setattr(
        training_tasks,
        "_selected_project_images",
        lambda _materials, _project, image_ids: [
            dict(next(row for row in rows if row["id"] == image_id))
            for image_id in image_ids
        ],
    )
    monkeypatch.setattr(
        training_tasks,
        "_label_schema",
        lambda _project: [{"code": "smoke", "class_id": 0, "status": "active"}],
    )
    split = SplitRequest(
        mode=SplitMode.INDEPENDENT_TEST_SET,
        train_image_ids=train_ids,
        test_image_ids=test_ids,
        validation_percent=25,
    )

    with pytest.raises(ValueError, match="训练集没有任何正样本"):
        training_tasks.freeze_training_inputs(tmp_path, split, seed=17)


def _selection_row(image_id, *, annotated=True, index=0):
    if annotated:
        return {
            "id": image_id,
            "processing_status": "processed",
            "content_sha256": f"{index + 1:064x}",
            "size_bytes": 100 + index,
            "stored_name": f"{image_id}.jpg",
            "group_id": f"group-{image_id}",
            "annotation_state": "annotated",
            "annotation_scope": ["smoke"],
            "annotation_hash": "b" * 64,
            "annotated": True,
            "boxes": [{
                "label": "smoke",
                "class_id": 0,
                "x1": 1, "y1": 1, "x2": 8, "y2": 8,
            }],
        }
    return {
        "id": image_id,
        "processing_status": "processed",
        "cleaned_at": "2026-09-28T00:00:00Z",
        "content_sha256": f"{index + 1:064x}",
        "size_bytes": 100 + index,
        "stored_name": f"{image_id}.jpg",
        "group_id": f"group-{image_id}",
        "annotation_state": "unannotated",
        "annotation_scope": [],
        "annotation_hash": "",
        "annotated": False,
        "boxes": [],
    }


def test_cleaned_unannotated_selection_is_preserved_but_excluded_from_snapshot(monkeypatch, tmp_path):
    import platform_core.training_tasks as training_tasks
    from platform_core.training_splits import SplitMode, SplitRequest

    rows = [
        *[_selection_row(f"gt-{index}", index=index) for index in range(6)],
        _selection_row("pending-1", annotated=False, index=10),
    ]
    by_id = {row["id"]: row for row in rows}

    def selected_images(_materials, _project, image_ids):
        return [dict(by_id[image_id]) for image_id in image_ids]

    monkeypatch.setattr(training_tasks, "_selected_project_images", selected_images)
    monkeypatch.setattr(
        training_tasks,
        "_label_schema",
        lambda _project: [{"code": "smoke", "class_id": 0, "canonical_project_class_id": 7}],
    )

    requested = SplitRequest(
        mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
        train_image_ids=tuple(row["id"] for row in rows),
        experiment_percent=20,
        validation_percent=20,
    )
    resolution = training_tasks.resolve_training_selection(tmp_path, requested)

    assert resolution.selected_train_image_ids[-1] == "pending-1"
    assert resolution.pending_annotation_image_ids == ("pending-1",)
    assert "pending-1" not in resolution.effective_split.train_image_ids

    frozen = training_tasks.freeze_training_inputs(
        tmp_path,
        requested,
        seed=42,
        selection_resolution=resolution,
    )

    assert frozen["selection"]["selected_train_count"] == 7
    assert frozen["selection"]["effective_train_count"] == 6
    assert frozen["selection"]["pending_annotation_count"] == 1
    assert frozen["selection"]["pending_annotation_image_ids"] == ["pending-1"]
    assert "pending-1" not in frozen["split"]["train_image_ids"]
    assert "pending-1" not in {row["id"] for row in frozen["images"]}


def test_cleaned_unannotated_independent_test_material_is_rejected(monkeypatch, tmp_path):
    import platform_core.training_tasks as training_tasks
    from platform_core.training_splits import SplitMode, SplitRequest

    rows = [
        _selection_row("train-a", index=0),
        _selection_row("train-b", index=1),
        _selection_row("test-pending", annotated=False, index=2),
    ]
    by_id = {row["id"]: row for row in rows}
    monkeypatch.setattr(
        training_tasks,
        "_selected_project_images",
        lambda _materials, _project, image_ids: [dict(by_id[image_id]) for image_id in image_ids],
    )
    requested = SplitRequest(
        mode=SplitMode.INDEPENDENT_TEST_SET,
        train_image_ids=("train-a", "train-b"),
        test_image_ids=("test-pending",),
        experiment_percent=None,
        validation_percent=20,
    )

    with pytest.raises(ValueError, match="独立试验素材必须具备正式 Ground Truth"):
        training_tasks.resolve_training_selection(tmp_path, requested)


def test_all_pending_training_selection_fails_before_queue(monkeypatch, tmp_path):
    import platform_core.training_tasks as training_tasks
    from platform_core.training_splits import SplitMode, SplitRequest

    rows = [
        _selection_row("pending-a", annotated=False, index=0),
        _selection_row("pending-b", annotated=False, index=1),
    ]
    by_id = {row["id"]: row for row in rows}
    monkeypatch.setattr(
        training_tasks,
        "_selected_project_images",
        lambda _materials, _project, image_ids: [dict(by_id[image_id]) for image_id in image_ids],
    )
    requested = SplitRequest(
        mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
        train_image_ids=("pending-a", "pending-b"),
        experiment_percent=20,
        validation_percent=20,
    )

    with pytest.raises(ValueError, match="本轮没有任何正式标注素材"):
        training_tasks.resolve_training_selection(tmp_path, requested)
