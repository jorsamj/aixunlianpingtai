"""Authoritative training-label aggregation and immutable task snapshots."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .annotation_repository import AnnotationRepository
from .annotations import annotation_scope_covers, legal_negative_for_labels
from .material_repository import MaterialRepository


def _unique(values: Sequence[object] | None) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in (values or ()) if str(value).strip()))


def _digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _schema_by_id(label_schema: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for item in label_schema:
        label_id = str(item.get("label_id") or "").strip()
        if label_id and item.get("active", True) is not False and str(item.get("status") or "active") == "active":
            result[label_id] = dict(item)
    return result


def aggregate_training_labels(
    project_path: str | Path,
    train_image_ids: Sequence[object],
    test_image_ids: Sequence[object],
    label_schema: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate only labels evidenced by the exact selected images and their GT scopes."""
    train_ids, test_ids = _unique(train_image_ids), _unique(test_image_ids)
    overlap = sorted(set(train_ids) & set(test_ids))
    if overlap:
        raise ValueError(f"训练素材与独立试验素材不能重复: {', '.join(overlap[:5])}")
    selected_ids = _unique([*train_ids, *test_ids])
    if not selected_ids:
        raise ValueError("请选择本次训练素材")
    project = Path(project_path)
    materials = MaterialRepository(project)
    rows = []
    for offset in range(0, len(selected_ids), 500):
        rows.extend(materials.get_many(selected_ids[offset:offset + 500]))
    found = {str(row.get("id") or "") for row in rows}
    missing = [image_id for image_id in selected_ids if image_id not in found]
    if missing:
        raise ValueError(f"所选素材不存在: {', '.join(missing[:5])}")

    annotations = AnnotationRepository(project).get_many(selected_ids)
    schema = _schema_by_id(label_schema)
    related = set()
    for annotation in annotations:
        related.update(str(value) for value in (annotation.get("annotation_scope") or ()) if str(value) in schema)
        related.update(
            str(box.get("label_id")) for box in (annotation.get("boxes") or ())
            if str(box.get("label_id") or "") in schema
        )

    counters = {
        label_id: {
            "positive_images": 0, "boxes": 0, "scope_covered_images": 0,
            "legal_negative_images": 0, "gt_incomplete_images": 0,
        }
        for label_id in related
    }
    for annotation in annotations:
        boxes = list(annotation.get("boxes") or ())
        state = str(annotation.get("annotation_state") or "unannotated")
        scope = list(annotation.get("annotation_scope") or ())
        box_counts = {}
        for box in boxes:
            label_id = str(box.get("label_id") or "")
            if label_id in counters:
                box_counts[label_id] = box_counts.get(label_id, 0) + 1
        for label_id, stats in counters.items():
            count = box_counts.get(label_id, 0)
            if count:
                stats["positive_images"] += 1
                stats["boxes"] += count
            covered = annotation_scope_covers(scope, [label_id])
            if covered:
                stats["scope_covered_images"] += 1
            else:
                stats["gt_incomplete_images"] += 1
            if legal_negative_for_labels(boxes, state, scope, [label_id]):
                stats["legal_negative_images"] += 1

    labels = []
    for label_id in sorted(related, key=lambda value: (int(schema[value].get("class_id", 10**9)), value)):
        labels.append({**schema[label_id], **counters[label_id]})
    selection = {
        "schema_version": 1,
        "train_image_ids": train_ids,
        "test_image_ids": test_ids,
    }
    return {
        "selection_manifest": {**selection, "selection_hash": _digest(selection)},
        "selected_image_count": len(selected_ids),
        "available_training_labels": labels,
    }


def freeze_training_labels(report: Mapping[str, Any], training_label_ids: Sequence[object]) -> dict[str, Any]:
    selected = _unique(training_label_ids)
    if not selected:
        raise ValueError("请至少选择一个本次训练标签")
    available = {
        str(item.get("label_id") or ""): dict(item)
        for item in (report.get("available_training_labels") or ())
        if item.get("label_id")
    }
    missing = [label_id for label_id in selected if label_id not in available]
    if missing:
        raise ValueError(f"训练标签不属于本次所选素材: {', '.join(missing[:5])}")
    snapshot = []
    for yolo_class_id, label_id in enumerate(selected):
        item = available[label_id]
        snapshot.append({
            "label_id": label_id,
            "code": str(item.get("code") or ""),
            "display_name": str(item.get("display_name") or item.get("name") or item.get("code") or ""),
            "platform_class_id": item.get("class_id"),
            "class_id": yolo_class_id,
            "yolo_class_id": yolo_class_id,
        })
    frozen = {"schema_version": 1, "labels": snapshot}
    return {**frozen, "schema_hash": _digest(frozen)}


def verify_frozen_training_contract(payload: Mapping[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """Reject payload drift before a Worker builds any training artifact."""
    train_ids = _unique(payload.get("train_image_ids"))
    test_ids = _unique(payload.get("test_image_ids"))
    selection = payload.get("selection_manifest")
    if not isinstance(selection, Mapping):
        raise ValueError("训练素材冻结清单缺失")
    expected_selection = {
        "schema_version": 1,
        "train_image_ids": train_ids,
        "test_image_ids": test_ids,
    }
    if list(selection.get("train_image_ids") or ()) != train_ids or list(
        selection.get("test_image_ids") or ()
    ) != test_ids or str(selection.get("selection_hash") or "") != _digest(expected_selection):
        raise ValueError("训练素材冻结清单与任务 image_id 不一致")

    label_ids = _unique(payload.get("training_label_ids"))
    frozen = payload.get("training_label_schema_snapshot")
    labels = list(frozen.get("labels") or ()) if isinstance(frozen, Mapping) else []
    if not label_ids or [str(item.get("label_id") or "") for item in labels] != label_ids:
        raise ValueError("训练标签冻结快照缺失或与 training_label_ids 不一致")
    frozen_body = {"schema_version": int(frozen.get("schema_version") or 1), "labels": labels}
    if str(frozen.get("schema_hash") or "") != _digest(frozen_body):
        raise ValueError("训练标签冻结快照校验失败")
    return label_ids, labels
