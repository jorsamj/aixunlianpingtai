from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath
from typing import Any, Mapping, Sequence


class SplitMode(str, Enum):
    INDEPENDENT_TEST_SET = "independent_test_set"
    RANDOM_TEST_FROM_TRAINING_POOL = "random_test_from_training_pool"


@dataclass(frozen=True)
class SplitRequest:
    mode: SplitMode
    train_image_ids: tuple[str, ...]
    test_image_ids: tuple[str, ...] = ()
    experiment_percent: float | None = None
    validation_percent: float = 20

    def __post_init__(self) -> None:
        mode = SplitMode(self.mode)
        train_ids = tuple(dict.fromkeys(str(value).strip() for value in self.train_image_ids if str(value).strip()))
        test_ids = tuple(dict.fromkeys(str(value).strip() for value in self.test_image_ids if str(value).strip()))
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "train_image_ids", train_ids)
        object.__setattr__(self, "test_image_ids", test_ids)
        if not train_ids:
            raise ValueError("train_image_ids 不能为空")
        if not 0 < float(self.validation_percent) < 100:
            raise ValueError("validation_percent 必须大于 0 且小于 100")
        if mode == SplitMode.INDEPENDENT_TEST_SET:
            if not test_ids:
                raise ValueError("test_image_ids 不能为空")
            if set(train_ids) & set(test_ids):
                raise ValueError("训练素材与独立试验素材不能重复")
            if self.experiment_percent is not None:
                raise ValueError("独立试验集模式不能设置 experiment_percent")
        else:
            if test_ids:
                raise ValueError("随机抽取模式不能设置 test_image_ids")
            if self.experiment_percent is None or not 0 < float(self.experiment_percent) < 100:
                raise ValueError("experiment_percent 必须大于 0 且小于 100")


@dataclass(frozen=True)
class SplitManifest:
    mode: SplitMode
    ids: dict[str, tuple[str, ...]]
    counts: dict[str, int]
    requested: dict[str, Any]
    actual_ratios: dict[str, float]
    groups: dict[str, str]
    content_hashes: dict[str, str]
    test_seed: int
    validation_seed: int
    excluded_duplicate_ids: tuple[str, ...] = ()
    duplicate_groups: dict[str, tuple[str, ...]] | None = None


_COMPONENT_RELATION_FIELDS = (
    "group_id",
    "video_task_id",
    "source_group_id",
    "camera_id",
    "session_id",
)


def _processed(row: Mapping[str, Any]) -> bool:
    return bool(
        row.get("annotation_state") in {"annotated", "confirmed_empty"}
        or row.get("annotated")
        or row.get("processing_status") == "processed"
        or row.get("cleaned_at")
        or row.get("clean_skipped")
    )


def _identity(row: Mapping[str, Any]) -> str:
    for key in ("stored_name", "stored_path", "path"):
        value = str(row.get(key) or "").strip()
        if value:
            return PurePath(value.replace("\\", "/")).as_posix().casefold()
    return ""


def _canonical_box(box: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    label = str(box.get("label") or box.get("code") or "").strip()
    if label:
        result["label"] = label
    if box.get("class_id") is not None:
        try:
            result["class_id"] = int(box["class_id"])
        except (TypeError, ValueError):
            result["class_id"] = str(box["class_id"])
    for key in ("x1", "y1", "x2", "y2"):
        if box.get(key) is not None:
            try:
                result[key] = round(float(box[key]), 6)
            except (TypeError, ValueError):
                result[key] = str(box[key])
    return result


def _annotation_scope(row: Mapping[str, Any]) -> tuple[str, ...]:
    raw = row.get("annotation_scope") or ()
    if isinstance(raw, str):
        raw = (raw,)
    scope = tuple(sorted({str(value).strip() for value in raw if str(value).strip()}))
    state = str(
        row.get("annotation_state")
        or ("annotated" if list(row.get("boxes") or []) else "unannotated")
    )
    if state == "confirmed_empty" and not scope:
        return ("*",)
    return scope


def _valid_annotation(row: Mapping[str, Any]) -> bool:
    boxes = list(row.get("boxes") or [])
    state = str(
        row.get("annotation_state")
        or ("annotated" if boxes else "unannotated")
    )
    if state == "annotated":
        return bool(boxes)
    if state == "confirmed_empty":
        return not boxes and bool(_annotation_scope(row))
    return False


def _annotation_digest(row: Mapping[str, Any]) -> str:
    boxes = sorted(
        (_canonical_box(box) for box in (row.get("boxes") or [])),
        key=lambda box: json.dumps(box, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )
    state = str(row.get("annotation_state") or ("annotated" if boxes else "unannotated"))
    payload = {
        "annotation_state": state,
        "annotation_scope": list(_annotation_scope(row)),
        "boxes": boxes,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _deduplicate_selected(
    rows: Sequence[Mapping[str, Any]],
    request: SplitRequest,
) -> tuple[list[Mapping[str, Any]], tuple[str, ...], dict[str, tuple[str, ...]]]:
    by_hash: dict[str, list[Mapping[str, Any]]] = {}
    without_hash: list[Mapping[str, Any]] = []
    train_ids = set(request.train_image_ids)
    test_ids = set(request.test_image_ids)
    for row in rows:
        content_hash = str(row.get("content_sha256") or "").strip().lower()
        if content_hash:
            by_hash.setdefault(content_hash, []).append(row)
        else:
            without_hash.append(row)

    canonical_rows: list[Mapping[str, Any]] = list(without_hash)
    excluded: list[str] = []
    duplicate_groups: dict[str, tuple[str, ...]] = {}
    request_order = {
        image_id: index
        for index, image_id in enumerate((*request.train_image_ids, *request.test_image_ids))
    }

    for content_hash, group in by_hash.items():
        ordered = sorted(
            group,
            key=lambda row: (
                request_order.get(str(row.get("id") or ""), 10**12),
                str(row.get("id") or ""),
            ),
        )
        if len(ordered) == 1:
            canonical_rows.append(ordered[0])
            continue

        digests = {_annotation_digest(row) for row in ordered}
        ids = tuple(str(row.get("id") or "") for row in ordered)
        duplicate_groups[content_hash] = ids
        if len(digests) != 1:
            raise ValueError(
                "duplicate_annotation_conflict: "
                f"content_sha256={content_hash} 的重复素材标注不一致: {', '.join(ids[:5])}"
            )

        if request.mode is SplitMode.INDEPENDENT_TEST_SET:
            has_train = any(image_id in train_ids for image_id in ids)
            has_test = any(image_id in test_ids for image_id in ids)
            if has_train and has_test:
                raise ValueError(
                    f"content hash leakage: {content_hash} 同时被显式选择为训练素材和独立试验素材"
                )

        canonical_rows.append(ordered[0])
        excluded.extend(ids[1:])

    canonical_rows.sort(
        key=lambda row: request_order.get(str(row.get("id") or ""), 10**12)
    )
    return canonical_rows, tuple(sorted(excluded)), dict(sorted(duplicate_groups.items()))


def _component_keys(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    parent: dict[str, str] = {}
    rank: dict[str, int] = {}
    token_owner: dict[tuple[str, str], str] = {}

    def find(image_id: str) -> str:
        root = image_id
        while parent[root] != root:
            root = parent[root]
        while parent[image_id] != image_id:
            next_id = parent[image_id]
            parent[image_id] = root
            image_id = next_id
        return root

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return
        if rank[left_root] < rank[right_root]:
            left_root, right_root = right_root, left_root
        parent[right_root] = left_root
        if rank[left_root] == rank[right_root]:
            rank[left_root] += 1

    for row in rows:
        image_id = str(row.get("id") or "").strip()
        parent[image_id] = image_id
        rank[image_id] = 0

    for row in rows:
        image_id = str(row.get("id") or "").strip()
        relations: list[tuple[str, str]] = []
        content_hash = str(row.get("content_sha256") or "").strip().lower()
        if content_hash:
            relations.append(("content_sha256", content_hash))
        identity = _identity(row)
        if identity:
            relations.append(("file_identity", identity))
        for field in _COMPONENT_RELATION_FIELDS:
            value = str(row.get(field) or "").strip()
            if value:
                relations.append((field, value))
        for token in relations:
            owner = token_owner.setdefault(token, image_id)
            union(owner, image_id)

    members: dict[str, list[str]] = {}
    for image_id in parent:
        members.setdefault(find(image_id), []).append(image_id)

    result: dict[str, str] = {}
    for image_ids in members.values():
        stable_members = tuple(sorted(image_ids))
        digest = hashlib.sha256("\n".join(stable_members).encode("utf-8")).hexdigest()[:16]
        component_id = f"component:{digest}"
        for image_id in stable_members:
            result[image_id] = component_id
    return result


def _select_grouped(
    rows: Sequence[Mapping[str, Any]],
    component_keys: Mapping[str, str],
    percent: float,
    seed: int,
    *,
    min_remaining_groups: int = 1,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        image_id = str(row.get("id") or "")
        grouped.setdefault(component_keys[image_id], []).append(row)
    if len(grouped) <= int(min_remaining_groups):
        raise ValueError("按不可拆分数据组件分组后组数不足，无法避免数据泄漏")
    keys = sorted(grouped)
    random.Random(int(seed)).shuffle(keys)
    sizes = [len(grouped[key]) for key in keys]
    target = max(1, min(len(rows) - 1, round(len(rows) * float(percent) / 100)))

    choices: dict[int, tuple[int, ...]] = {0: ()}
    for index, size in enumerate(sizes):
        for total, selected in list(choices.items())[::-1]:
            candidate = total + size
            if candidate < len(rows) and candidate not in choices:
                choices[candidate] = (*selected, index)
    allowed_totals = [
        total for total, selected in choices.items()
        if total > 0 and len(grouped) - len(selected) >= int(min_remaining_groups)
    ]
    if not allowed_totals:
        raise ValueError("所选不可拆分数据组件不足以划分训练、验证和试验数据")
    selected_total = min(
        allowed_totals,
        key=lambda total: (abs(total - target), total > target, total),
    )
    selected_keys = {keys[index] for index in choices[selected_total]}
    selected = [
        row for row in rows
        if component_keys[str(row.get("id") or "")] in selected_keys
    ]
    remaining = [
        row for row in rows
        if component_keys[str(row.get("id") or "")] not in selected_keys
    ]
    return remaining, selected


def _assert_no_leakage(role_rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    checks: list[tuple[str, Any]] = [
        ("content hash", lambda row: str(row.get("content_sha256") or "").strip().lower()),
        ("file identity", _identity),
    ]
    checks.extend(
        (field.replace("_", " "), lambda row, field=field: str(row.get(field) or "").strip())
        for field in _COMPONENT_RELATION_FIELDS
    )
    for label, getter in checks:
        owners: dict[str, str] = {}
        for role, rows in role_rows.items():
            for row in rows:
                value = getter(row)
                if not value:
                    continue
                previous = owners.setdefault(value, role)
                if previous != role:
                    raise ValueError(f"{label} leakage: {value} 同时出现在 {previous} 和 {role}")


def build_split_manifest(
    images: Sequence[Mapping[str, Any]],
    request: SplitRequest,
    *,
    seed: int,
) -> SplitManifest:
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in images:
        image_id = str(row.get("id") or "").strip()
        if not image_id:
            raise ValueError("素材缺少 id")
        if image_id in by_id:
            raise ValueError(f"素材 id 重复: {image_id}")
        by_id[image_id] = row

    requested_ids = set(request.train_image_ids) | set(request.test_image_ids)
    missing_ids = sorted(requested_ids - set(by_id))
    if missing_ids:
        raise ValueError(f"所选素材不存在: {', '.join(missing_ids[:5])}")

    selected_rows = [
        by_id[image_id]
        for image_id in (*request.train_image_ids, *request.test_image_ids)
    ]
    canonical_rows, excluded_duplicate_ids, duplicate_groups = _deduplicate_selected(
        selected_rows, request
    )
    canonical_by_id = {str(row.get("id")): row for row in canonical_rows}
    train_pool = [
        canonical_by_id[image_id]
        for image_id in request.train_image_ids
        if image_id in canonical_by_id
    ]
    independent_test_rows = [
        canonical_by_id[image_id]
        for image_id in request.test_image_ids
        if image_id in canonical_by_id
    ]

    invalid_annotation_ids = sorted(
        str(row.get("id"))
        for row in [*train_pool, *independent_test_rows]
        if not _valid_annotation(row)
    )
    if invalid_annotation_ids:
        raise ValueError(
            "所选素材没有有效正式标注或确认负样本: "
            f"{', '.join(invalid_annotation_ids[:5])}"
        )

    component_keys = _component_keys(canonical_rows)
    test_seed = int(seed)
    digest = hashlib.sha256(f"validation:{seed}".encode("utf-8")).digest()
    validation_seed = int.from_bytes(digest[:8], "big")

    if request.mode == SplitMode.INDEPENDENT_TEST_SET:
        test_rows = independent_test_rows
        train_rows, validation_rows = _select_grouped(
            train_pool, component_keys, request.validation_percent, validation_seed
        )
        test_source = "independent_materials"
    else:
        after_test, test_rows = _select_grouped(
            train_pool,
            component_keys,
            float(request.experiment_percent or 0),
            test_seed,
            min_remaining_groups=2,
        )
        train_rows, validation_rows = _select_grouped(
            after_test, component_keys, request.validation_percent, validation_seed
        )
        test_source = "random_from_training_pool"

    roles = {"train": train_rows, "validation": validation_rows, "test": test_rows}
    for role, rows in roles.items():
        if not rows:
            raise ValueError(f"{role} 集为空")
        pending = [str(row.get("id")) for row in rows if not _processed(row)]
        if pending:
            raise ValueError(f"{role} 集包含未处理素材: {', '.join(pending[:5])}")
    _assert_no_leakage(roles)

    ids = {
        role: tuple(sorted(str(row.get("id")) for row in rows))
        for role, rows in roles.items()
    }
    total = sum(len(value) for value in ids.values())
    counts = {role: len(value) for role, value in ids.items()}
    counts["total"] = total
    requested = {
        "test_source": test_source,
        "train_image_ids": list(request.train_image_ids),
        "test_image_ids": list(request.test_image_ids),
        "experiment_percent": request.experiment_percent,
        "validation_percent": request.validation_percent,
        "excluded_duplicate_ids": list(excluded_duplicate_ids),
        "duplicate_group_count": len(duplicate_groups),
    }
    actual_ratios = {
        role: round(len(value) * 100 / total, 6) for role, value in ids.items()
    }
    selected_role_rows = [row for rows in roles.values() for row in rows]
    groups = {
        str(row.get("id")): component_keys[str(row.get("id"))]
        for row in selected_role_rows
    }
    hashes = {
        str(row.get("id")): str(row.get("content_sha256") or "").strip()
        for row in selected_role_rows
    }
    return SplitManifest(
        mode=request.mode,
        ids=ids,
        counts=counts,
        requested=requested,
        actual_ratios=actual_ratios,
        groups=groups,
        content_hashes=hashes,
        test_seed=test_seed,
        validation_seed=validation_seed,
        excluded_duplicate_ids=excluded_duplicate_ids,
        duplicate_groups=duplicate_groups,
    )
