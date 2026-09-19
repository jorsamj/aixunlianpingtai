import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .annotations import atomic_write_json
from .annotation_schema import CANONICAL_ANNOTATION_SCHEMA_VERSION, CANONICAL_SOURCE_FORMATS
from .training_splits import SplitManifest


TRAINING_INPUT_POLICY = "ultralytics_jpeg_repair_v1"
DATASET_REVISION_SCHEMA_VERSION = 1


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_schema(label_schema: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [dict(item) for item in label_schema if item.get("code")],
        key=lambda item: (int(item.get("class_id", 10**9)), str(item.get("code"))),
    )




def _sha256_hex(value: object, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError(f"{field} 必须是 SHA256")
    return text


def _external_annotation_provenance(
    image: Mapping[str, Any],
    *,
    annotation_hash: str,
) -> dict[str, Any] | None:
    value = image.get("external_annotation")
    if value in (None, {}):
        return None
    if not isinstance(value, Mapping):
        raise ValueError("external_annotation 必须是对象")
    try:
        schema_version = int(value.get("schema_version") or 0)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("external_annotation.schema_version 无效") from error
    if schema_version != CANONICAL_ANNOTATION_SCHEMA_VERSION:
        raise ValueError("external_annotation schema 版本不受支持")
    source_format = str(value.get("source_format") or "").strip().lower()
    if source_format not in CANONICAL_SOURCE_FORMATS:
        raise ValueError("external_annotation source_format 不受支持")
    source_digest = _sha256_hex(
        value.get("source_digest"),
        "external_annotation.source_digest",
    )
    synced_hash = str(value.get("synced_annotation_hash") or "").strip().lower()
    if synced_hash:
        synced_hash = _sha256_hex(
            synced_hash,
            "external_annotation.synced_annotation_hash",
        )
    return {
        "schema_version": schema_version,
        "source_format": source_format,
        "source_digest": source_digest,
        "annotation_status": str(value.get("annotation_status") or ""),
        "split": str(value.get("split") or ""),
        "label_key": str(value.get("label_key") or "") or None,
        "dataset_key": str(value.get("dataset_key") or "") or None,
        "synced_annotation_hash": synced_hash,
        "platform_annotation_hash": str(annotation_hash or ""),
        "needs_review": bool(image.get("external_annotation_needs_review")),
        "review_reason": str(image.get("external_annotation_review_reason") or ""),
    }


def _dataset_revision_payload(
    records: Sequence[Mapping[str, Any]],
    label_schema: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    fields = (
        "image_id",
        "dataset_id",
        "source_type",
        "source_ref",
        "group_id",
        "content_sha256",
        "storage_source_id",
        "storage_type",
        "object_key",
        "annotation_state",
        "annotation_scope",
        "annotation_hash",
        "negative_origin",
        "source_annotation_state",
        "source_labels",
        "box_count",
        "labels",
        "external_annotation",
    )
    images = [
        {field: record.get(field) for field in fields}
        for record in sorted(records, key=lambda row: str(row.get("image_id") or ""))
    ]
    return {
        "schema_version": DATASET_REVISION_SCHEMA_VERSION,
        "canonical_annotation_schema_version": CANONICAL_ANNOTATION_SCHEMA_VERSION,
        "label_schema": _stable_schema(label_schema),
        "images": images,
    }


def _dataset_revision_id(
    records: Sequence[Mapping[str, Any]],
    label_schema: Sequence[Mapping[str, Any]],
) -> str:
    payload = _dataset_revision_payload(records, label_schema)
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def ensure_dataset_revision(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Return snapshot truth with a deterministic Dataset Revision identity.

    Snapshot V3 producers already carry dataset_revision_id. Legacy V1/V2
    portable fixtures may not; they are upgraded deterministically without
    changing their historical snapshot_id.
    """
    value = dict(snapshot)
    records = list(value.get("images") or [])
    label_schema = list(value.get("label_schema") or [])
    expected = _dataset_revision_id(records, label_schema)
    actual = str(value.get("dataset_revision_id") or "").strip().lower()
    if actual and actual != expected:
        raise ValueError("Snapshot dataset_revision_id 与冻结数据 truth 不一致")
    value["dataset_revision_schema_version"] = DATASET_REVISION_SCHEMA_VERSION
    value["canonical_annotation_schema_version"] = CANONICAL_ANNOTATION_SCHEMA_VERSION
    value["dataset_revision_id"] = expected
    return value


def dataset_revision_document(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    normalized = ensure_dataset_revision(snapshot)
    records = list(normalized.get("images") or [])
    label_schema = list(normalized.get("label_schema") or [])
    payload = _dataset_revision_payload(records, label_schema)
    return {
        "dataset_revision_id": str(normalized["dataset_revision_id"]),
        "created_at": str(normalized.get("created_at") or datetime.now(timezone.utc).isoformat()),
        **payload,
    }


def _annotation_state(image: Mapping[str, Any], boxes: Sequence[Mapping[str, Any]]) -> str:
    return str(image.get("annotation_state") or ("annotated" if boxes else "unannotated"))


def _annotation_scope(
    image: Mapping[str, Any],
    boxes: Sequence[Mapping[str, Any]],
) -> list[str]:
    raw = image.get("annotation_scope") or []
    if isinstance(raw, str):
        raw = [raw]
    scope = sorted({str(value).strip() for value in raw if str(value).strip()})
    state = _annotation_state(image, boxes)
    if state == "annotated" and not scope:
        scope = sorted({
            str(box.get("label") or box.get("code") or "").strip()
            for box in boxes
            if str(box.get("label") or box.get("code") or "").strip()
        })
    if state == "confirmed_empty" and not scope:
        scope = ["*"]
    if state == "unannotated":
        scope = []
    return scope


def _lock_scope_to_schema(
    image_id: str,
    state: str,
    raw_scope: Sequence[str],
    boxes: Sequence[Mapping[str, Any]],
    schema_codes: set[str],
) -> list[str]:
    labels = {
        str(box.get("label") or box.get("code") or "").strip()
        for box in boxes
        if str(box.get("label") or box.get("code") or "").strip()
    }
    unknown_labels = sorted(labels - schema_codes)
    if unknown_labels:
        raise ValueError(
            f"训练素材 {image_id} 的标注标签不在本次锁定标签结构中: "
            + ", ".join(unknown_labels[:5])
        )
    if state != "confirmed_empty":
        return sorted({str(value).strip() for value in raw_scope if str(value).strip()})

    # A YOLO empty label file means that *none* of the locked classes is present.
    # Partial negative scopes cannot be represented by an empty detection target;
    # using them would silently teach unverified classes as background.
    normalized = {str(value).strip() for value in raw_scope if str(value).strip()}
    if "*" in normalized:
        return sorted(schema_codes)
    missing = sorted(schema_codes - normalized)
    if missing:
        raise ValueError(
            f"负样本 {image_id} 未确认本次算法的全部标签: "
            + ", ".join(missing[:5])
        )
    return sorted(schema_codes)


def _annotation_hash(
    image: Mapping[str, Any],
    boxes: Sequence[Mapping[str, Any]],
    state: str,
    scope: Sequence[str],
) -> str:
    stored = str(image.get("annotation_hash") or "").strip()
    if stored:
        return stored
    payload = {
        "annotation_state": state,
        "annotation_scope": list(scope),
        "boxes": list(boxes),
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def build_snapshot(
    images: Sequence[Mapping[str, Any]],
    train_image_ids: Sequence[str] | SplitManifest,
    val_image_ids: Sequence[str] | Sequence[Mapping[str, Any]],
    label_schema: Sequence[Mapping[str, Any]] | None = None,
    seed: int | None = None,
) -> dict:
    if isinstance(train_image_ids, SplitManifest):
        if label_schema is not None:
            raise TypeError("V2 snapshot 的标签结构应作为第三个参数传入")
        return _build_snapshot_v2(images, train_image_ids, val_image_ids)  # type: ignore[arg-type]
    if label_schema is None or seed is None:
        raise TypeError("旧版 snapshot 需要 label_schema 和 seed")
    stable_schema = _stable_schema(label_schema)
    schema_codes = {str(item["code"]) for item in stable_schema}
    by_id = {str(image.get("id")): image for image in images if image.get("id") is not None}
    train_ids = sorted({str(image_id) for image_id in train_image_ids})
    val_ids = sorted({str(image_id) for image_id in val_image_ids})
    selected_ids = train_ids + [image_id for image_id in val_ids if image_id not in set(train_ids)]
    records = []
    label_counts: dict[str, int] = {}
    for image_id in selected_ids:
        image = by_id.get(image_id)
        if image is None:
            raise ValueError(f"训练素材 {image_id} 不存在")
        processed = bool(
            image.get("annotated")
            or image.get("annotation_state") in {"annotated", "confirmed_empty"}
            or image.get("processing_status") == "processed"
            or image.get("cleaned_at")
            or image.get("clean_skipped")
        )
        if not processed:
            raise ValueError(f"训练素材 {image_id} 仍是未处理状态")
        boxes = list(image.get("boxes") or [])
        state = _annotation_state(image, boxes)
        raw_scope = _annotation_scope(image, boxes)
        scope = _lock_scope_to_schema(image_id, state, raw_scope, boxes, schema_codes)
        annotation_hash = _annotation_hash(image, boxes, state, raw_scope)
        for box in boxes:
            label = str(box.get("label") or "").strip()
            if label:
                label_counts[label] = label_counts.get(label, 0) + 1
        records.append({
            "image_id": image_id,
            "annotation_state": state,
            "annotation_scope": scope,
            "annotation_hash": annotation_hash,
            "negative_origin": str(image.get("negative_origin") or ""),
            "source_annotation_state": str(image.get("source_annotation_state") or ""),
            "source_labels": sorted({str(value) for value in (image.get("source_labels") or []) if str(value)}),
            "box_count": len(boxes),
            "labels": sorted({
                str(box.get("label") or "").strip()
                for box in boxes
                if str(box.get("label") or "").strip()
            }),
        })
    payload = {
        "seed": int(seed),
        "training_input_policy": TRAINING_INPUT_POLICY,
        "train_image_ids": train_ids,
        "val_image_ids": val_ids,
        "label_schema": stable_schema,
        "label_counts": dict(sorted(label_counts.items())),
        "images": records,
    }
    snapshot_id = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    return {
        "snapshot_id": snapshot_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }


def _build_snapshot_v2(
    images: Sequence[Mapping[str, Any]],
    manifest: SplitManifest,
    label_schema: Sequence[Mapping[str, Any]],
) -> dict:
    stable_schema = _stable_schema(label_schema)
    schema_codes = {str(item["code"]) for item in stable_schema}
    by_id = {str(image.get("id")): image for image in images if image.get("id") is not None}
    records: list[dict[str, Any]] = []
    label_counts: dict[str, int] = {}
    negative_scope_counts: dict[str, int] = {}
    negative_origin_counts: dict[str, int] = {}
    for role in ("train", "validation", "test"):
        for image_id in manifest.ids[role]:
            image = by_id.get(image_id)
            if image is None:
                raise ValueError(f"训练素材 {image_id} 不存在")
            if not bool(
                image.get("annotated")
                or image.get("annotation_state") in {"annotated", "confirmed_empty"}
                or image.get("processing_status") == "processed"
                or image.get("cleaned_at")
                or image.get("clean_skipped")
            ):
                raise ValueError(f"训练素材 {image_id} 仍是未处理状态")
            actual_hash = str(image.get("content_sha256") or "").strip()
            if actual_hash != manifest.content_hashes.get(image_id, ""):
                raise ValueError(f"训练素材 {image_id} content hash 已变化")
            boxes = list(image.get("boxes") or [])
            state = _annotation_state(image, boxes)
            raw_scope = _annotation_scope(image, boxes)
            scope = _lock_scope_to_schema(image_id, state, raw_scope, boxes, schema_codes)
            annotation_hash = _annotation_hash(image, boxes, state, raw_scope)
            labels = sorted(
                {
                    str(box.get("label") or "").strip()
                    for box in boxes
                    if str(box.get("label") or "").strip()
                }
            )
            for box in boxes:
                label = str(box.get("label") or "").strip()
                if label:
                    label_counts[label] = label_counts.get(label, 0) + 1
            if state == "confirmed_empty":
                origin = str(image.get("negative_origin") or "explicit_confirmed_empty")
                negative_origin_counts[origin] = negative_origin_counts.get(origin, 0) + 1
                for label in scope:
                    negative_scope_counts[label] = negative_scope_counts.get(label, 0) + 1
            records.append(
                {
                    "image_id": image_id,
                    "role": role,
                    "dataset_id": str(image.get("dataset_id") or ""),
                    "source_type": str(image.get("source_type") or "upload"),
                    "source_ref": str(image.get("video_task_id") or image.get("source_ref") or ""),
                    "group_id": manifest.groups.get(image_id, image_id),
                    "content_sha256": actual_hash,
                    "storage_source_id": str(image.get("storage_source_id") or "default_local"),
                    "storage_type": str(image.get("storage_type") or "local"),
                    "object_key": str(image.get("object_key") or ""),
                    "annotation_state": state,
                    "annotation_scope": scope,
                    "annotation_hash": annotation_hash,
                    "negative_origin": str(image.get("negative_origin") or ""),
                    "source_annotation_state": str(image.get("source_annotation_state") or ""),
                    "source_labels": sorted({str(value) for value in (image.get("source_labels") or []) if str(value)}),
                    "stored_name": str(image.get("stored_name") or ""),
                    "box_count": len(boxes),
                    "labels": labels,
                    "external_annotation": _external_annotation_provenance(
                        image,
                        annotation_hash=annotation_hash,
                    ),
                }
            )
    ids = {role: list(manifest.ids[role]) for role in ("train", "validation", "test")}
    duplicate_groups = {
        content_hash: list(image_ids)
        for content_hash, image_ids in sorted((manifest.duplicate_groups or {}).items())
    }
    dataset_revision_id = _dataset_revision_id(records, stable_schema)
    payload = {
        "schema_version": 3,
        "dataset_revision_schema_version": DATASET_REVISION_SCHEMA_VERSION,
        "canonical_annotation_schema_version": CANONICAL_ANNOTATION_SCHEMA_VERSION,
        "dataset_revision_id": dataset_revision_id,
        "training_input_policy": TRAINING_INPUT_POLICY,
        "mode": manifest.mode.value,
        "test_seed": manifest.test_seed,
        "validation_seed": manifest.validation_seed,
        "requested": manifest.requested,
        "actual_ratios": manifest.actual_ratios,
        "counts": manifest.counts,
        "ids": ids,
        "train_image_ids": ids["train"],
        "val_image_ids": ids["validation"],
        "test_image_ids": ids["test"],
        "excluded_duplicate_ids": list(manifest.excluded_duplicate_ids),
        "duplicate_groups": duplicate_groups,
        "label_schema": stable_schema,
        "label_counts": dict(sorted(label_counts.items())),
        "negative_scope_counts": dict(sorted(negative_scope_counts.items())),
        "negative_origin_counts": dict(sorted(negative_origin_counts.items())),
        "images": records,
    }
    snapshot_id = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    return {
        "snapshot_id": snapshot_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }


def persist_snapshot(directory: Path, snapshot: Mapping[str, Any]) -> Path:
    snapshot_id = str(snapshot.get("snapshot_id") or "")
    if not snapshot_id:
        raise ValueError("snapshot_id 不能为空")
    path = directory / f"{snapshot_id}.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        comparable_existing = {key: value for key, value in existing.items() if key != "created_at"}
        comparable_new = {key: value for key, value in snapshot.items() if key != "created_at"}
        if comparable_existing != comparable_new:
            raise ValueError(f"Snapshot {snapshot_id} 已存在但内容不一致")
        return path
    atomic_write_json(path, dict(snapshot))
    return path



def persist_dataset_revision(directory: Path, snapshot: Mapping[str, Any]) -> Path:
    revision = dataset_revision_document(snapshot)
    revision_id = str(revision["dataset_revision_id"])
    path = directory / f"{revision_id}.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        comparable_existing = {key: value for key, value in existing.items() if key != "created_at"}
        comparable_new = {key: value for key, value in revision.items() if key != "created_at"}
        if comparable_existing != comparable_new:
            raise ValueError(f"Dataset Revision {revision_id} 已存在但内容不一致")
        return path
    atomic_write_json(path, revision)
    return path
