import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .annotations import atomic_write_json
from .training_splits import SplitManifest


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_schema(label_schema: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [dict(item) for item in label_schema if item.get("code")],
        key=lambda item: (int(item.get("class_id", 10**9)), str(item.get("code"))),
    )


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
            "box_count": len(boxes),
            "labels": sorted({
                str(box.get("label") or "").strip()
                for box in boxes
                if str(box.get("label") or "").strip()
            }),
        })
    payload = {
        "seed": int(seed),
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
                    "stored_name": str(image.get("stored_name") or ""),
                    "box_count": len(boxes),
                    "labels": labels,
                }
            )
    ids = {role: list(manifest.ids[role]) for role in ("train", "validation", "test")}
    duplicate_groups = {
        content_hash: list(image_ids)
        for content_hash, image_ids in sorted((manifest.duplicate_groups or {}).items())
    }
    payload = {
        "schema_version": 3,
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
