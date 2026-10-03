"""Canonical external detection-annotation evidence contract.

Source-format parsers remain responsible for YOLO/COCO/VOC discovery and
parsing. This module owns only the versioned, deterministic evidence shape
consumed by rescan/delta logic.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Iterable, Mapping

CANONICAL_ANNOTATION_SCHEMA_VERSION = 1
CANONICAL_SOURCE_FORMATS = frozenset({"yolo", "coco", "voc"})
CANONICAL_ANNOTATION_STATUSES = frozenset(
    {"annotated", "confirmed_empty", "unannotated", "invalid"}
)


class CanonicalAnnotationSchemaError(ValueError):
    pass


def _sha256_hex(value: object, *, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise CanonicalAnnotationSchemaError(
            f"{field} must be a lowercase SHA256 hex digest"
        )
    return text


def _source_object(value: object, *, field: str) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise CanonicalAnnotationSchemaError(f"{field} must be an object or null")
    try:
        size_bytes = int(value.get("size_bytes") or 0)
    except (TypeError, ValueError, OverflowError) as error:
        raise CanonicalAnnotationSchemaError(
            f"{field}.size_bytes is invalid"
        ) from error
    if size_bytes < 0:
        raise CanonicalAnnotationSchemaError(
            f"{field}.size_bytes must be nonnegative"
        )
    return {
        "size_bytes": size_bytes,
        "etag": str(value.get("etag") or ""),
        "sha256": _sha256_hex(value.get("sha256"), field=f"{field}.sha256"),
    }


def canonical_class_catalog_digest(
    classes: Iterable[Mapping[str, object]],
) -> str:
    normalized = []
    seen = set()
    for item in classes:
        if not isinstance(item, Mapping):
            raise CanonicalAnnotationSchemaError(
                "class catalog entry must be an object"
            )
        try:
            class_id = int(item.get("class_id"))
        except (TypeError, ValueError, OverflowError) as error:
            raise CanonicalAnnotationSchemaError("class_id is invalid") from error
        name = str(item.get("name") or "").strip()
        if class_id < 0 or class_id in seen or not name:
            raise CanonicalAnnotationSchemaError(
                "class catalog is invalid or ambiguous"
            )
        seen.add(class_id)
        normalized.append({"class_id": class_id, "name": name})
    normalized.sort(key=lambda item: item["class_id"])
    return hashlib.sha256(json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _box(value: Mapping[str, object]) -> dict:
    if not isinstance(value, Mapping):
        raise CanonicalAnnotationSchemaError("annotation box must be an object")
    try:
        line_number = int(value.get("line_number"))
        class_id = int(value.get("class_id"))
        cx = float(value.get("cx"))
        cy = float(value.get("cy"))
        width = float(value.get("w"))
        height = float(value.get("h"))
    except (TypeError, ValueError, OverflowError) as error:
        raise CanonicalAnnotationSchemaError(
            "annotation box contains invalid values"
        ) from error
    if (
        line_number <= 0
        or class_id < 0
        or not all(math.isfinite(item) for item in (cx, cy, width, height))
        or not (0.0 <= cx <= 1.0)
        or not (0.0 <= cy <= 1.0)
        or not (0.0 < width <= 1.0)
        or not (0.0 < height <= 1.0)
    ):
        raise CanonicalAnnotationSchemaError(
            "annotation box violates normalized detection constraints"
        )
    return {
        "line_number": line_number,
        "class_id": class_id,
        "cx": cx,
        "cy": cy,
        "w": width,
        "h": height,
        "clipped": bool(value.get("clipped")),
    }


def _payload(value: Mapping[str, object]) -> dict:
    if not isinstance(value, Mapping):
        raise CanonicalAnnotationSchemaError(
            "annotation evidence must be an object"
        )
    try:
        schema_version = int(value.get("schema_version"))
    except (TypeError, ValueError, OverflowError) as error:
        raise CanonicalAnnotationSchemaError(
            "schema_version is invalid"
        ) from error
    if schema_version != CANONICAL_ANNOTATION_SCHEMA_VERSION:
        raise CanonicalAnnotationSchemaError(
            "unsupported annotation schema version"
        )

    source_format = str(value.get("source_format") or "").strip().lower()
    if source_format not in CANONICAL_SOURCE_FORMATS:
        raise CanonicalAnnotationSchemaError(
            "unsupported annotation source format"
        )

    object_key = str(value.get("object_key") or "").strip()
    if not object_key or "\x00" in object_key:
        raise CanonicalAnnotationSchemaError("object_key is required")

    annotation_status = str(value.get("annotation_status") or "").strip()
    if annotation_status not in CANONICAL_ANNOTATION_STATUSES:
        raise CanonicalAnnotationSchemaError(
            "annotation_status is invalid"
        )

    label_key = str(value.get("label_key") or "").strip() or None
    dataset_key = str(value.get("dataset_key") or "").strip() or None
    label_object = _source_object(value.get("label_object"), field="label_object")
    dataset_object = _source_object(
        value.get("dataset_object"), field="dataset_object"
    )
    if label_key and label_object is None:
        raise CanonicalAnnotationSchemaError(
            "label_key requires label_object identity"
        )
    if dataset_key and dataset_object is None:
        raise CanonicalAnnotationSchemaError(
            "dataset_key requires dataset_object identity"
        )

    boxes = [_box(item) for item in list(value.get("boxes") or [])]
    line_numbers = [item["line_number"] for item in boxes]
    if len(line_numbers) != len(set(line_numbers)):
        raise CanonicalAnnotationSchemaError(
            "annotation box line numbers must be unique"
        )

    return {
        "schema_version": CANONICAL_ANNOTATION_SCHEMA_VERSION,
        "source_format": source_format,
        "object_key": object_key,
        "split": str(value.get("split") or ""),
        "annotation_status": annotation_status,
        "label_key": label_key,
        "label_object": label_object,
        "dataset_key": dataset_key,
        "dataset_object": dataset_object,
        "class_catalog_digest": _sha256_hex(
            value.get("class_catalog_digest"),
            field="class_catalog_digest",
        ),
        "boxes": boxes,
    }


def canonical_annotation_source_digest(
    value: Mapping[str, object],
) -> str:
    payload = _payload(value)
    return hashlib.sha256(json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def build_canonical_annotation_evidence(
    *,
    source_format: str,
    object_key: str,
    split: str,
    annotation_status: str,
    label_key: str | None,
    label_object: Mapping[str, object] | None,
    dataset_key: str | None,
    dataset_object: Mapping[str, object] | None,
    classes: Iterable[Mapping[str, object]],
    boxes: Iterable[Mapping[str, object]],
) -> dict:
    payload = _payload({
        "schema_version": CANONICAL_ANNOTATION_SCHEMA_VERSION,
        "source_format": source_format,
        "object_key": object_key,
        "split": split,
        "annotation_status": annotation_status,
        "label_key": label_key,
        "label_object": label_object,
        "dataset_key": dataset_key,
        "dataset_object": dataset_object,
        "class_catalog_digest": canonical_class_catalog_digest(classes),
        "boxes": list(boxes),
    })
    digest = hashlib.sha256(json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return {
        **payload,
        "source_digest": digest,
        "box_count": len(payload["boxes"]),
    }


def validate_canonical_annotation_evidence(
    value: Mapping[str, object],
) -> dict:
    payload = _payload(value)
    try:
        box_count = int(value.get("box_count"))
    except (TypeError, ValueError, OverflowError) as error:
        raise CanonicalAnnotationSchemaError("box_count is invalid") from error
    if box_count != len(payload["boxes"]):
        raise CanonicalAnnotationSchemaError(
            "box_count does not match boxes"
        )

    expected = hashlib.sha256(json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()
    actual = _sha256_hex(value.get("source_digest"), field="source_digest")
    if actual != expected:
        raise CanonicalAnnotationSchemaError(
            "source_digest does not match canonical evidence"
        )
    return {
        **payload,
        "source_digest": actual,
        "box_count": box_count,
    }
