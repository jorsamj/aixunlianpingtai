from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image

from platform_core.annotation_repository import AnnotationRepository
from platform_core.snapshots import build_snapshot
from platform_core.training_splits import SplitManifest, SplitMode
from platform_core.training_tasks import materialize_portable_dataset


def _manifest(image_id: str, content_hash: str) -> SplitManifest:
    return SplitManifest(
        mode=SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
        ids={"train": (image_id,), "validation": (), "test": ()},
        counts={"train": 1, "validation": 0, "test": 0, "total": 1},
        requested={},
        actual_ratios={"train": 1.0, "validation": 0.0, "test": 0.0},
        groups={image_id: "component:test"},
        content_hashes={image_id: content_hash},
        test_seed=1,
        validation_seed=2,
    )


def test_confirmed_empty_without_explicit_scope_persists_active_project_labels(tmp_path: Path):
    (tmp_path / "meta.json").write_text(
        """{
          "labels": ["fire", "smoke", "helmet"],
          "label_meta": [
            {"status": "active"},
            {"status": "active"},
            {"status": "inactive"}
          ]
        }""",
        encoding="utf-8",
    )
    repository = AnnotationRepository(tmp_path)

    saved = repository.upsert(
        "negative-1",
        [],
        annotation_state="confirmed_empty",
    )

    assert saved["annotation_state"] == "confirmed_empty"
    assert saved["annotation_scope"] == ["fire", "smoke"]


def test_snapshot_expands_legacy_global_negative_to_locked_schema():
    row = {
        "id": "negative-1",
        "content_sha256": "hash-negative",
        "stored_name": "negative-1.jpg",
        "annotation_state": "confirmed_empty",
        "annotation_scope": ["*"],
        "annotated": True,
        "processing_status": "processed",
        "boxes": [],
    }
    schema = [
        {"code": "fire", "class_id": 0},
        {"code": "smoke", "class_id": 1},
    ]

    snapshot = build_snapshot(
        [row],
        _manifest("negative-1", "hash-negative"),
        schema,
    )

    locked = snapshot["images"][0]
    assert locked["annotation_state"] == "confirmed_empty"
    assert locked["annotation_scope"] == ["fire", "smoke"]
    assert snapshot["negative_scope_counts"] == {"fire": 1, "smoke": 1}


def test_partial_negative_scope_is_rejected_for_multiclass_yolo_snapshot():
    row = {
        "id": "negative-partial",
        "content_sha256": "hash-partial",
        "stored_name": "negative-partial.jpg",
        "annotation_state": "confirmed_empty",
        "annotation_scope": ["fire"],
        "annotated": True,
        "processing_status": "processed",
        "boxes": [],
    }
    schema = [
        {"code": "fire", "class_id": 0},
        {"code": "smoke", "class_id": 1},
    ]

    with pytest.raises(ValueError, match="未确认本次算法的全部标签"):
        build_snapshot(
            [row],
            _manifest("negative-partial", "hash-partial"),
            schema,
        )


def test_annotation_label_outside_locked_schema_is_rejected_early():
    row = {
        "id": "positive-wrong-label",
        "content_sha256": "hash-positive",
        "stored_name": "positive-wrong-label.jpg",
        "annotation_state": "annotated",
        "annotation_scope": ["helmet"],
        "annotated": True,
        "processing_status": "processed",
        "boxes": [
            {"label": "helmet", "x1": 1, "y1": 1, "x2": 5, "y2": 5}
        ],
    }

    with pytest.raises(ValueError, match="不在本次锁定标签结构"):
        build_snapshot(
            [row],
            _manifest("positive-wrong-label", "hash-positive"),
            [{"code": "fire", "class_id": 0}],
        )


def test_confirmed_empty_materializes_as_real_empty_yolo_label_file(tmp_path: Path):
    source = tmp_path / "source.jpg"
    Image.new("RGB", (32, 24), (20, 20, 20)).save(source, format="JPEG")
    content_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    row = {
        "id": "negative-yolo",
        "filename": source.name,
        "stored_name": source.name,
        "width": 32,
        "height": 24,
        "content_sha256": content_hash,
        "boxes": [],
        "annotation_state": "confirmed_empty",
        "annotation_scope": ["fire"],
    }
    snapshot = {
        "schema_version": 3,
        "snapshot_id": "negative-snapshot",
        "ids": {"train": ["negative-yolo"], "validation": [], "test": []},
        "label_schema": [{"code": "fire", "class_id": 0}],
        "images": [
            {
                "image_id": "negative-yolo",
                "role": "train",
                "content_sha256": content_hash,
                "annotation_state": "confirmed_empty",
                "annotation_scope": ["fire"],
            }
        ],
    }

    bundle = materialize_portable_dataset(
        tmp_path / "task",
        snapshot,
        [row],
        lambda _row: source,
        safety_reserve_bytes=0,
    )

    label = bundle / "dataset" / "labels" / "train" / "negative-yolo.txt"
    assert label.is_file()
    assert label.read_text(encoding="utf-8") == ""
