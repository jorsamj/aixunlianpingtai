from __future__ import annotations

import hashlib
import json

import pytest

from platform_core.annotation_schema import (
    CANONICAL_ANNOTATION_SCHEMA_VERSION,
    CanonicalAnnotationSchemaError,
    build_canonical_annotation_evidence,
    canonical_annotation_source_digest,
    canonical_class_catalog_digest,
    validate_canonical_annotation_evidence,
)


def _source(digest: str):
    return {
        "size_bytes": 12,
        "etag": "etag-1",
        "sha256": digest,
    }


@pytest.mark.parametrize("source_format", ["yolo", "coco", "voc"])
def test_canonical_evidence_v1_preserves_legacy_digest_semantics(
    source_format,
):
    classes = [
        {"class_id": 7, "name": "smoke"},
        {"class_id": 2, "name": "fire"},
    ]
    boxes = [{
        "line_number": 1,
        "class_id": 7,
        "cx": 0.5,
        "cy": 0.4,
        "w": 0.2,
        "h": 0.25,
        "clipped": False,
    }]
    class_digest = hashlib.sha256(json.dumps(
        sorted(classes, key=lambda item: item["class_id"]),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    legacy_payload = {
        "schema_version": 1,
        "source_format": source_format,
        "object_key": "images/train/a.jpg",
        "split": "train",
        "annotation_status": "annotated",
        "label_key": "labels/train/a.txt",
        "label_object": _source("a" * 64),
        "dataset_key": "data.yaml",
        "dataset_object": _source("b" * 64),
        "class_catalog_digest": class_digest,
        "boxes": boxes,
    }
    legacy_digest = hashlib.sha256(json.dumps(
        legacy_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()

    evidence = build_canonical_annotation_evidence(
        source_format=source_format,
        object_key=legacy_payload["object_key"],
        split="train",
        annotation_status="annotated",
        label_key=legacy_payload["label_key"],
        label_object=legacy_payload["label_object"],
        dataset_key=legacy_payload["dataset_key"],
        dataset_object=legacy_payload["dataset_object"],
        classes=classes,
        boxes=boxes,
    )

    assert evidence["schema_version"] == CANONICAL_ANNOTATION_SCHEMA_VERSION
    assert evidence["class_catalog_digest"] == class_digest
    assert evidence["source_digest"] == legacy_digest
    assert canonical_annotation_source_digest(evidence) == legacy_digest
    assert validate_canonical_annotation_evidence(evidence) == evidence


def test_canonical_class_catalog_is_order_independent():
    left = canonical_class_catalog_digest([
        {"class_id": 7, "name": "smoke"},
        {"class_id": 2, "name": "fire"},
    ])
    right = canonical_class_catalog_digest([
        {"class_id": 2, "name": "fire"},
        {"class_id": 7, "name": "smoke"},
    ])
    assert left == right


def test_canonical_evidence_rejects_digest_tampering():
    evidence = build_canonical_annotation_evidence(
        source_format="yolo",
        object_key="images/a.jpg",
        split="train",
        annotation_status="confirmed_empty",
        label_key="labels/a.txt",
        label_object=_source("a" * 64),
        dataset_key="data.yaml",
        dataset_object=_source("b" * 64),
        classes=[{"class_id": 0, "name": "smoke"}],
        boxes=[],
    )
    evidence["split"] = "val"
    with pytest.raises(
        CanonicalAnnotationSchemaError,
        match="source_digest",
    ):
        validate_canonical_annotation_evidence(evidence)


@pytest.mark.parametrize("source_format", ["yolo", "coco", "voc"])
def test_canonical_evidence_rejects_invalid_normalized_box(source_format):
    with pytest.raises(
        CanonicalAnnotationSchemaError,
        match="normalized detection constraints",
    ):
        build_canonical_annotation_evidence(
            source_format=source_format,
            object_key="images/a.jpg",
            split="train",
            annotation_status="annotated",
            label_key="labels/a.txt",
            label_object=_source("a" * 64),
            dataset_key="data.yaml",
            dataset_object=_source("b" * 64),
            classes=[{"class_id": 0, "name": "smoke"}],
            boxes=[{
                "line_number": 1,
                "class_id": 0,
                "cx": 1.2,
                "cy": 0.5,
                "w": 0.2,
                "h": 0.2,
                "clipped": False,
            }],
        )
