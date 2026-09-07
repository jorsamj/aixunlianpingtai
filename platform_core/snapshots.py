import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .annotations import atomic_write_json
from .training_splits import SplitManifest


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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
            or image.get("processing_status") == "processed"
            or image.get("cleaned_at")
            or image.get("clean_skipped")
        )
        if not processed:
            raise ValueError(f"训练素材 {image_id} 仍是未处理状态")
        boxes = list(image.get("boxes") or [])
        annotation_hash = str(image.get("annotation_hash") or hashlib.sha256(_canonical(boxes).encode("utf-8")).hexdigest())
        for box in boxes:
            label = str(box.get("label") or "").strip()
            if label:
                label_counts[label] = label_counts.get(label, 0) + 1
        records.append({
            "image_id": image_id,
            "annotation_hash": annotation_hash,
            "box_count": len(boxes),
            "labels": sorted({str(box.get("label") or "").strip() for box in boxes if str(box.get("label") or "").strip()}),
        })
    stable_schema = sorted(
        [dict(item) for item in label_schema if item.get("code")],
        key=lambda item: (int(item.get("class_id", 10**9)), str(item.get("code"))),
    )
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
    by_id = {str(image.get("id")): image for image in images if image.get("id") is not None}
    records: list[dict[str, Any]] = []
    label_counts: dict[str, int] = {}
    for role in ("train", "validation", "test"):
        for image_id in manifest.ids[role]:
            image = by_id.get(image_id)
            if image is None:
                raise ValueError(f"训练素材 {image_id} 不存在")
            if not bool(
                image.get("annotated")
                or image.get("processing_status") == "processed"
                or image.get("cleaned_at")
                or image.get("clean_skipped")
            ):
                raise ValueError(f"训练素材 {image_id} 仍是未处理状态")
            actual_hash = str(image.get("content_sha256") or "").strip()
            if actual_hash != manifest.content_hashes.get(image_id, ""):
                raise ValueError(f"训练素材 {image_id} content hash 已变化")
            boxes = list(image.get("boxes") or [])
            annotation_hash = str(
                image.get("annotation_hash")
                or hashlib.sha256(_canonical(boxes).encode("utf-8")).hexdigest()
            )
            labels = sorted(
                {str(box.get("label") or "").strip() for box in boxes if str(box.get("label") or "").strip()}
            )
            for box in boxes:
                label = str(box.get("label") or "").strip()
                if label:
                    label_counts[label] = label_counts.get(label, 0) + 1
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
                    "annotation_hash": annotation_hash,
                    "stored_name": str(image.get("stored_name") or ""),
                    "box_count": len(boxes),
                    "labels": labels,
                }
            )
    stable_schema = sorted(
        [dict(item) for item in label_schema if item.get("code")],
        key=lambda item: (int(item.get("class_id", 10**9)), str(item.get("code"))),
    )
    ids = {role: list(manifest.ids[role]) for role in ("train", "validation", "test")}
    payload = {
        "schema_version": 2,
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
