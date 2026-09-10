"""Authoritative training preflight shared by the HTTP preview and Worker gate."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .annotations import annotation_scope_covers


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _issue(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **details}


class PreflightBlocked(ValueError):
    def __init__(self, report: Mapping[str, Any]):
        blockers = list(report.get("blockers") or ())
        first = blockers[0] if blockers else {"code": "PREFLIGHT_BLOCKED", "message": "训练预检未通过"}
        self.code = str(first.get("code") or "PREFLIGHT_BLOCKED")
        self.report = dict(report)
        super().__init__(f"{self.code}: {first.get('message')}")


def _projected_count(values: Sequence[object], percent: float) -> int:
    total = len(tuple(dict.fromkeys(str(value) for value in values if str(value))))
    if total <= 1 or percent <= 0:
        return 0
    return max(1, min(total - 1, round(total * percent / 100)))


def _split_request_values(split_request: Any) -> tuple[str, tuple[object, ...], tuple[object, ...], Any, float]:
    if hasattr(split_request, "mode"):
        mode = getattr(split_request, "mode")
        return (
            str(getattr(mode, "value", mode)),
            tuple(getattr(split_request, "train_image_ids", ()) or ()),
            tuple(getattr(split_request, "test_image_ids", ()) or ()),
            getattr(split_request, "experiment_percent", None),
            float(getattr(split_request, "validation_percent", 20) or 20),
        )
    return (
        str(split_request.get("mode") or ""),
        tuple(split_request.get("train_image_ids") or ()),
        tuple(split_request.get("test_image_ids") or ()),
        split_request.get("experiment_percent"),
        float(split_request.get("validation_percent") or 20),
    )


def preview_preflight(
    label_report: Mapping[str, Any],
    frozen_labels: Mapping[str, Any],
    split_request: Any,
) -> dict[str, Any]:
    """Cheap, non-mutating preview based on the exact server-side selection."""
    mode, train_ids, test_ids, experiment_percent, validation_percent = _split_request_values(split_request)
    selected = [dict(row) for row in (frozen_labels.get("labels") or ())]
    available = {
        str(row.get("label_id") or ""): dict(row)
        for row in (label_report.get("available_training_labels") or ())
    }
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    for row in selected:
        label_id = str(row.get("label_id") or "")
        stats = available.get(label_id, {})
        positive = int(stats.get("positive_images") or 0)
        labels.append({
            "label_id": label_id,
            "code": row.get("code"),
            "display_name": row.get("display_name"),
            "positive_images": positive,
            "boxes": int(stats.get("boxes") or 0),
            "legal_negative_images": int(stats.get("legal_negative_images") or 0),
            "gt_incomplete_images": int(stats.get("gt_incomplete_images") or 0),
        })
        if positive <= 0:
            blockers.append(_issue(
                "TRAINING_LABEL_NO_POSITIVE_SAMPLE",
                f"训练标签 {row.get('display_name') or row.get('code') or label_id} 没有有效正样本",
                label_id=label_id,
            ))

    train_pool = len(tuple(dict.fromkeys(train_ids)))
    if mode == "independent_test_set":
        test_count = len(tuple(dict.fromkeys(test_ids)))
        validation_count = _projected_count(train_ids, validation_percent)
        train_count = max(0, train_pool - validation_count)
    else:
        test_count = _projected_count(train_ids, float(experiment_percent or 0))
        remaining = max(0, train_pool - test_count)
        validation_count = _projected_count(range(remaining), validation_percent)
        train_count = max(0, remaining - validation_count)
    counts = {"train": train_count, "validation": validation_count, "test": test_count, "total": train_count + validation_count + test_count}
    for role in ("train", "validation", "test"):
        if counts[role] <= 0:
            blockers.append(_issue("EMPTY_SPLIT", f"预计 {role} 集为空", role=role))
    incomplete = sum(int(row.get("gt_incomplete_images") or 0) for row in labels)
    if incomplete:
        warnings.append(_issue(
            "GROUND_TRUTH_INCOMPLETE_MAY_BE_EXCLUDED",
            "部分素材对本次训练标签的 Ground Truth 不完整，Worker 固化划分时会排除并给出准确数量",
            label_incomplete_count=incomplete,
        ))
    return {
        "schema_version": 1,
        "status": "PASSED" if not blockers else "BLOCKED",
        "ok": not blockers,
        "stage": "preview",
        "generated_at": _now(),
        "selected_image_count": int(label_report.get("selected_image_count") or 0),
        "counts": counts,
        "counts_are_projected": True,
        "labels": labels,
        "yolo_mapping": [
            {"class_id": int(row.get("yolo_class_id", -1)), "label_id": row.get("label_id"), "name": row.get("code")}
            for row in selected
        ],
        "blockers": blockers,
        "warnings": warnings,
    }


def _nearest_existing(path: Path) -> Path:
    current = path.resolve()
    while not current.exists() and current.parent != current:
        current = current.parent
    return current


def _bundle_contract(manifest_path: Path, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        roles = list(manifest.get("materialized_roles") or ())
        if roles != ["train", "validation"]:
            blockers.append(_issue("TEST_DATA_LEAKAGE", "训练工作区只能物化 Train/Validation", materialized_roles=roles))
        yaml_ref = str(manifest.get("data_yaml_ref") or "")
        data_yaml = (manifest_path.parent / Path(yaml_ref)).resolve()
        if not data_yaml.is_relative_to(manifest_path.parent.resolve()) or not data_yaml.is_file():
            blockers.append(_issue("TRAINING_YAML_MISSING", "训练 data.yaml 不存在或越过任务工作区"))
            return manifest
        data = yaml.safe_load(data_yaml.read_text(encoding="utf-8")) or {}
        if "test" in data:
            blockers.append(_issue("TEST_DATA_LEAKAGE", "训练 data.yaml 禁止包含 Test 路径"))
        return manifest
    except Exception as error:
        blockers.append(_issue("TRAINING_BUNDLE_INVALID", f"训练工作区清单无效：{error}"))
        return {}


def authoritative_preflight(
    snapshot: Mapping[str, Any],
    images: Sequence[Mapping[str, Any]],
    payload: Mapping[str, Any],
    *,
    bundle_manifest_path: str | Path,
    device_evidence: Mapping[str, Any] | None = None,
    resource_context: Mapping[str, Any] | None = None,
    workspace: str | Path | None = None,
) -> dict[str, Any]:
    """Final Worker-side gate immediately before the trainer is launched."""
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    schema = [dict(row) for row in (snapshot.get("label_schema") or ())]
    selected_ids = [str(row.get("label_id") or "") for row in schema]
    codes = [str(row.get("code") or "") for row in schema]
    yolo_ids = [int(row.get("yolo_class_id", row.get("class_id", -1))) for row in schema]
    if (
        not selected_ids
        or any(not value for value in selected_ids)
        or len(set(selected_ids)) != len(selected_ids)
        or any(not value for value in codes)
        or len(set(codes)) != len(codes)
        or yolo_ids != list(range(len(schema)))
    ):
        blockers.append(_issue("INVALID_YOLO_LABEL_SCHEMA", "冻结标签必须使用唯一 label_id/code 和从 0 开始的连续 YOLO class id"))

    label_counts = {str(key): int(value or 0) for key, value in (snapshot.get("label_counts") or {}).items()}
    for row in schema:
        label_id = str(row.get("label_id") or "")
        if label_counts.get(label_id, 0) <= 0:
            blockers.append(_issue(
                "TRAINING_LABEL_NO_POSITIVE_SAMPLE",
                f"训练标签 {row.get('display_name') or row.get('code') or label_id} 没有有效正样本",
                label_id=label_id,
            ))

    ids = {
        role: [str(value) for value in (snapshot.get("ids") or {}).get(role, ())]
        for role in ("train", "validation", "test")
    }
    id_owner: dict[str, str] = {}
    for role, values in ids.items():
        if not values:
            blockers.append(_issue("EMPTY_SPLIT", f"{role} 集为空", role=role))
        for image_id in values:
            previous = id_owner.setdefault(image_id, role)
            if previous != role:
                blockers.append(_issue("SPLIT_IMAGE_LEAKAGE", f"素材 {image_id} 同时出现在 {previous} 和 {role}", image_id=image_id))

    locked = {str(row.get("image_id") or ""): dict(row) for row in (snapshot.get("images") or ())}
    hash_owner: dict[str, str] = {}
    for role, values in ids.items():
        for image_id in values:
            digest = str((locked.get(image_id) or {}).get("content_sha256") or "")
            if not digest:
                blockers.append(_issue("SNAPSHOT_SHA_MISSING", f"素材 {image_id} 缺少冻结 SHA256", image_id=image_id))
                continue
            previous = hash_owner.setdefault(digest, role)
            if previous != role:
                blockers.append(_issue("SPLIT_CONTENT_LEAKAGE", f"同一内容同时出现在 {previous} 和 {role}", image_id=image_id, sha256=digest))

    by_id = {str(row.get("id") or ""): row for row in images}
    split_stats = {
        role: {"annotated": 0, "confirmed_empty": 0, "unannotated": 0, "positive_images": 0, "legal_negative_images": 0}
        for role in ("train", "validation", "test")
    }
    label_stats = {
        label_id: {
            role: {"positive_images": 0, "boxes": 0, "legal_negative_images": 0}
            for role in ("train", "validation", "test")
        }
        for label_id in selected_ids
    }
    for role, values in ids.items():
        for image_id in values:
            row = by_id.get(image_id)
            frozen = locked.get(image_id)
            if row is None or frozen is None:
                blockers.append(_issue("MATERIAL_MISSING", f"素材 {image_id} 不存在", image_id=image_id))
                continue
            expected_sha = str(frozen.get("content_sha256") or "")
            current_sha = str(row.get("content_sha256") or "")
            if current_sha and expected_sha and current_sha != expected_sha:
                blockers.append(_issue("MATERIAL_SHA_CHANGED", f"素材 {image_id} SHA256 已变化", image_id=image_id))
            expected_annotation = str(frozen.get("annotation_hash") or "")
            current_annotation = str(row.get("annotation_hash") or "")
            if expected_annotation and current_annotation != expected_annotation:
                blockers.append(_issue("ANNOTATION_CHANGED", f"素材 {image_id} 标注在快照后发生变化", image_id=image_id))
            state = str(row.get("annotation_state") or "unannotated")
            split_stats[role][state if state in {"annotated", "confirmed_empty"} else "unannotated"] += 1
            if state not in {"annotated", "confirmed_empty"}:
                blockers.append(_issue("ANNOTATION_STATE_INVALID", f"{role} 集素材 {image_id} 没有确认 Ground Truth", image_id=image_id, state=state))
            scope_complete = annotation_scope_covers(row.get("annotation_scope"), selected_ids)
            if not scope_complete:
                blockers.append(_issue(
                    "ANNOTATION_SCOPE_INCOMPLETE",
                    f"{role} 集素材 {image_id} 对本次训练标签的 Ground Truth 不完整",
                    image_id=image_id,
                    role=role,
                ))
            selected_boxes = [
                box for box in (row.get("boxes") or ())
                if str(box.get("label_id") or "") in label_stats
            ]
            if selected_boxes:
                split_stats[role]["positive_images"] += 1
            elif scope_complete and state in {"annotated", "confirmed_empty"}:
                split_stats[role]["legal_negative_images"] += 1
            for label_id in selected_ids:
                boxes = [box for box in selected_boxes if str(box.get("label_id") or "") == label_id]
                if boxes:
                    label_stats[label_id][role]["positive_images"] += 1
                    label_stats[label_id][role]["boxes"] += len(boxes)
                elif scope_complete and state in {"annotated", "confirmed_empty"}:
                    label_stats[label_id][role]["legal_negative_images"] += 1

    for row in schema:
        label_id = str(row.get("label_id") or "")
        if int(label_stats.get(label_id, {}).get("train", {}).get("boxes") or 0) <= 0:
            blockers.append(_issue(
                "TRAINING_LABEL_NO_TRAIN_POSITIVE",
                f"训练标签 {row.get('display_name') or row.get('code') or label_id} 在 Train 中没有有效正样本",
                label_id=label_id,
            ))

    bundle = _bundle_contract(Path(bundle_manifest_path).resolve(), blockers)
    requested_device = str(payload.get("requested_device") or payload.get("device") or "auto")
    assigned_device = str(payload.get("assigned_device") or payload.get("device") or "")
    evidence = dict(device_evidence or {})
    if assigned_device.startswith("cuda:") and evidence.get("cuda_available") is not True:
        blockers.append(_issue("CUDA_UNAVAILABLE", f"已分配 {assigned_device}，但训练环境 CUDA 不可用"))

    resources = dict(resource_context or {})
    required_disk = max(512 * 1024 * 1024, int(resources.get("dataset_bytes") or 0) // 10)
    disk = None
    if workspace is not None:
        usage = shutil.disk_usage(_nearest_existing(Path(workspace)))
        disk = {"free_bytes": int(usage.free), "required_bytes": required_disk}
        if usage.free < required_disk:
            blockers.append(_issue("DISK_SPACE_INSUFFICIENT", "训练工作区磁盘空间不足", **disk))
    try:
        import psutil  # type: ignore

        memory = psutil.virtual_memory()
        memory_info = {"total_bytes": int(memory.total), "available_bytes": int(memory.available)}
    except Exception as error:
        memory_info = {"total_bytes": None, "available_bytes": None, "error": str(error)}
        warnings.append(_issue("HOST_MEMORY_UNKNOWN", "无法读取主机内存状态"))
    if memory_info.get("available_bytes") and int(memory_info["available_bytes"]) < 1024 * 1024 * 1024:
        blockers.append(_issue("HOST_RAM_INSUFFICIENT", "可用主机内存不足 1GB", available_bytes=memory_info["available_bytes"]))
    shm = None
    shm_path = Path("/dev/shm")
    if shm_path.is_dir():
        usage = shutil.disk_usage(shm_path)
        shm = {"free_bytes": int(usage.free)}
        if int(payload.get("workers") or 0) > 0 and usage.free < 256 * 1024 * 1024:
            blockers.append(_issue("SHM_INSUFFICIENT", "/dev/shm 空间不足，无法安全启动多进程 DataLoader", **shm))

    report = {
        "schema_version": 1,
        "status": "PASSED" if not blockers else "BLOCKED",
        "ok": not blockers,
        "stage": "authoritative",
        "generated_at": _now(),
        "snapshot_id": snapshot.get("snapshot_id"),
        "counts": dict(snapshot.get("counts") or {}),
        "labels": schema,
        "label_counts": label_counts,
        "label_split_stats": label_stats,
        "split_stats": split_stats,
        "excluded_images": dict(snapshot.get("excluded_images") or {}),
        "yolo_mapping": [
            {"class_id": yolo_id, "label_id": row.get("label_id"), "name": row.get("code")}
            for row, yolo_id in zip(schema, yolo_ids)
        ],
        "requested_device": requested_device,
        "assigned_device": assigned_device,
        "resources": {"disk": disk, "memory": memory_info, "shm": shm, "gpu": evidence, "context": resources},
        "bundle": {"manifest": str(Path(bundle_manifest_path).resolve()), "materialized_roles": bundle.get("materialized_roles")},
        "blockers": blockers,
        "warnings": warnings,
    }
    return report


def require_preflight(report: Mapping[str, Any]) -> None:
    if report.get("ok") is not True:
        raise PreflightBlocked(report)
