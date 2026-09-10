from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath
from typing import Any, Mapping, Sequence

from .annotations import annotation_scope_covers


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
    exclusions: dict[str, str]
    test_seed: int
    validation_seed: int


def _group_key(row: Mapping[str, Any]) -> str:
    image_id = str(row.get("id") or "").strip()
    for key in ("group_id", "video_task_id", "source_group_id"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return image_id


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


def _selected_gt_fingerprint(
    row: Mapping[str, Any],
    selected_labels: Sequence[str],
) -> str:
    """Canonical selected-label GT semantics for duplicate-content checks.

    Box IDs and provenance are intentionally ignored. Unrelated classes are
    ignored when this task has an explicit selected-label schema.
    """
    selected = set(str(value) for value in selected_labels if str(value))
    boxes = []
    for raw in row.get("boxes") or ():
        box = dict(raw)
        label_id = str(box.get("label_id") or "").strip()
        if selected and label_id not in selected:
            continue
        label_key = label_id or str(box.get("label") or box.get("class_id") or "").strip()
        if not label_key:
            continue
        if all(key in box for key in ("x1", "y1", "x2", "y2")):
            geometry = {
                "x1": float(box["x1"]),
                "y1": float(box["y1"]),
                "x2": float(box["x2"]),
                "y2": float(box["y2"]),
            }
        else:
            geometry = {
                "cx": float(box.get("cx", 0)),
                "cy": float(box.get("cy", 0)),
                "w": float(box.get("w", 0)),
                "h": float(box.get("h", 0)),
            }
        boxes.append({"label": label_key, **geometry})
    boxes.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    return hashlib.sha256(
        json.dumps(boxes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_duplicate_annotations(
    rows: Sequence[Mapping[str, Any]],
    selected_labels: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    """Reject exact-content duplicates whose selected-label GT disagrees."""
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        digest = str(row.get("content_sha256") or "").strip()
        if digest:
            grouped.setdefault(digest, []).append(row)

    duplicates: dict[str, tuple[str, ...]] = {}
    for digest, members in grouped.items():
        if len(members) <= 1:
            continue
        ids = tuple(sorted(str(row.get("id") or "") for row in members))
        fingerprints = {_selected_gt_fingerprint(row, selected_labels) for row in members}
        if len(fingerprints) > 1:
            raise ValueError(
                "duplicate annotation conflict: "
                f"{digest} 的重复素材在本次训练标签下 Ground Truth 不一致：{', '.join(ids[:8])}"
            )
        duplicates[digest] = ids
    return duplicates


def _build_leakage_components(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    """Build transitive leakage components before any random split assignment."""
    indexed = [row for row in rows if str(row.get("id") or "").strip()]
    parents = list(range(len(indexed)))
    ranks = [0] * len(indexed)

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return
        if ranks[left_root] < ranks[right_root]:
            left_root, right_root = right_root, left_root
        parents[right_root] = left_root
        if ranks[left_root] == ranks[right_root]:
            ranks[left_root] += 1

    owners: dict[tuple[str, str], int] = {}
    for index, row in enumerate(indexed):
        identities = (
            ("content", str(row.get("content_sha256") or "").strip()),
            ("group", _group_key(row)),
            ("file", _identity(row)),
        )
        for namespace, value in identities:
            if not value:
                continue
            key = (namespace, value)
            previous = owners.setdefault(key, index)
            if previous != index:
                union(previous, index)

    members: dict[int, list[str]] = {}
    for index, row in enumerate(indexed):
        members.setdefault(find(index), []).append(str(row.get("id")))
    component_name = {
        root: "component:" + min(image_ids)
        for root, image_ids in members.items()
    }
    return {
        str(row.get("id")): component_name[find(index)]
        for index, row in enumerate(indexed)
    }


def _assert_requested_component_separation(
    train_rows: Sequence[Mapping[str, Any]],
    test_rows: Sequence[Mapping[str, Any]],
    components: Mapping[str, str],
) -> None:
    train_hashes = {
        str(row.get("content_sha256") or "").strip()
        for row in train_rows
        if str(row.get("content_sha256") or "").strip()
    }
    test_hashes = {
        str(row.get("content_sha256") or "").strip()
        for row in test_rows
        if str(row.get("content_sha256") or "").strip()
    }
    shared_hashes = sorted(train_hashes & test_hashes)
    if shared_hashes:
        raise ValueError(
            f"content hash leakage: {shared_hashes[0]} 同时出现在请求的 train 和 test"
        )

    train_components = {
        components.get(str(row.get("id") or ""), "")
        for row in train_rows
    }
    test_components = {
        components.get(str(row.get("id") or ""), "")
        for row in test_rows
    }
    overlap = sorted(value for value in train_components & test_components if value)
    if overlap:
        raise ValueError(
            "leakage component conflict: 独立 Train/Test 请求包含同一来源组或文件身份，"
            f"首个冲突组件 {overlap[0]}"
        )


def _dedupe_exact_content(
    rows: Sequence[Mapping[str, Any]],
    exclusions: dict[str, str],
) -> tuple[list[Mapping[str, Any]], int]:
    """Keep one canonical material record per exact SHA after GT is validated."""
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    without_hash: list[Mapping[str, Any]] = []
    for row in rows:
        digest = str(row.get("content_sha256") or "").strip()
        if digest:
            grouped.setdefault(digest, []).append(row)
        else:
            without_hash.append(row)

    kept = list(without_hash)
    removed = 0
    for members in grouped.values():
        ordered = sorted(members, key=lambda row: str(row.get("id") or ""))
        canonical = ordered[0]
        kept.append(canonical)
        canonical_id = str(canonical.get("id") or "")
        for duplicate in ordered[1:]:
            duplicate_id = str(duplicate.get("id") or "")
            exclusions[duplicate_id] = f"exact_duplicate_of:{canonical_id}"
            removed += 1
    return kept, removed


def _select_grouped(
    rows: Sequence[Mapping[str, Any]],
    percent: float,
    seed: int,
    *,
    min_remaining_groups: int = 1,
    group_ids: Mapping[str, str] | None = None,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Select whole leakage components in bounded memory.

    The previous exact subset-sum DP stored a tuple for many reachable image
    counts and becomes quadratic or worse when tens of thousands of singleton
    components are selected.  This deterministic seeded greedy selector is
    O(number_of_groups + number_of_rows) and keeps split ratios close to the
    requested target without ever splitting a leakage component.
    """
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        image_id = str(row.get("id") or "")
        key = (group_ids or {}).get(image_id) or _group_key(row)
        grouped.setdefault(key, []).append(row)
    minimum_remaining = max(1, int(min_remaining_groups))
    if len(grouped) <= minimum_remaining:
        raise ValueError("按泄漏组件分组后不足两个组，无法避免数据泄漏")

    keys = sorted(grouped)
    random.Random(int(seed)).shuffle(keys)
    target = max(1, min(len(rows) - 1, round(len(rows) * float(percent) / 100)))
    selectable_groups = len(keys) - minimum_remaining
    selected_keys: set[str] = set()
    selected_total = 0

    for key in keys[:selectable_groups]:
        size = len(grouped[key])
        before_distance = abs(target - selected_total)
        after_distance = abs(target - (selected_total + size))
        # Always select at least one group.  Afterwards stop once taking the
        # next whole component would move farther away from the target and we
        # have already reached/passed the target.
        if selected_keys and selected_total >= target and after_distance >= before_distance:
            break
        if selected_keys and selected_total < target and after_distance > before_distance:
            # Oversized component: keeping the current selection is a closer
            # ratio.  Continue scanning later components rather than ending so
            # a smaller component can still improve the target.
            continue
        selected_keys.add(key)
        selected_total += size
        if selected_total == target:
            break

    if not selected_keys:
        # Deterministically choose the smallest available component when every
        # candidate overshoots a tiny requested split.
        fallback = min(keys[:selectable_groups], key=lambda key: (len(grouped[key]), key))
        selected_keys.add(fallback)

    selected = [
        row for row in rows
        if ((group_ids or {}).get(str(row.get("id") or "")) or _group_key(row)) in selected_keys
    ]
    remaining = [
        row for row in rows
        if ((group_ids or {}).get(str(row.get("id") or "")) or _group_key(row)) not in selected_keys
    ]
    if not selected or not remaining:
        raise ValueError("所选泄漏组件不足以划分训练、验证和试验数据")
    return remaining, selected


def _assert_no_leakage(role_rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    for field, label, getter in (
        ("content_sha256", "content hash", lambda row: str(row.get("content_sha256") or "").strip()),
        ("group", "source group", _group_key),
        ("file", "file identity", _identity),
    ):
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
    training_label_ids: Sequence[object] | None = None,
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
    selected_labels = tuple(dict.fromkeys(
        str(value).strip() for value in (training_label_ids or ()) if str(value).strip()
    ))
    exclusions: dict[str, str] = {}

    def eligible(row: Mapping[str, Any]) -> bool:
        image_id = str(row.get("id") or "")
        if not selected_labels:
            if list(row.get("boxes") or []):
                return True
            exclusions[image_id] = "no_effective_annotation"
            return False
        state = str(row.get("annotation_state") or "unannotated")
        if state not in {"annotated", "confirmed_empty"}:
            exclusions[image_id] = "unannotated"
            return False
        if not annotation_scope_covers(row.get("annotation_scope"), selected_labels):
            exclusions[image_id] = "annotation_scope_incomplete_for_selected_labels"
            return False
        return True

    requested_train_rows = [
        by_id[image_id] for image_id in request.train_image_ids
        if eligible(by_id[image_id])
    ]
    if not requested_train_rows:
        raise ValueError("所选训练素材在本次训练标签作用域下无可用 Ground Truth")

    requested_test_rows = (
        [
            by_id[image_id] for image_id in request.test_image_ids
            if eligible(by_id[image_id])
        ]
        if request.mode == SplitMode.INDEPENDENT_TEST_SET
        else []
    )
    if request.mode == SplitMode.INDEPENDENT_TEST_SET and not requested_test_rows:
        raise ValueError("独立试验素材在本次训练标签作用域下无可用 Ground Truth")

    integrity_rows = [*requested_train_rows, *requested_test_rows]
    duplicate_groups = _validate_duplicate_annotations(integrity_rows, selected_labels)
    components = _build_leakage_components(integrity_rows)
    if request.mode == SplitMode.INDEPENDENT_TEST_SET:
        _assert_requested_component_separation(
            requested_train_rows, requested_test_rows, components
        )

    train_pool, deduped_train = _dedupe_exact_content(requested_train_rows, exclusions)
    deduped_test = 0
    test_rows: list[Mapping[str, Any]] = []
    if request.mode == SplitMode.INDEPENDENT_TEST_SET:
        test_rows, deduped_test = _dedupe_exact_content(requested_test_rows, exclusions)

    test_seed = int(seed)
    digest = hashlib.sha256(f"validation:{seed}".encode("utf-8")).digest()
    validation_seed = int.from_bytes(digest[:8], "big")
    if request.mode == SplitMode.INDEPENDENT_TEST_SET:
        train_rows, validation_rows = _select_grouped(
            train_pool,
            request.validation_percent,
            validation_seed,
            group_ids=components,
        )
        test_source = "independent_materials"
    else:
        after_test, test_rows = _select_grouped(
            train_pool,
            float(request.experiment_percent or 0),
            test_seed,
            min_remaining_groups=2,
            group_ids=components,
        )
        train_rows, validation_rows = _select_grouped(
            after_test,
            request.validation_percent,
            validation_seed,
            group_ids=components,
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
        "training_label_ids": list(selected_labels),
        "excluded_image_count": len(exclusions),
        "duplicate_content_group_count": len(duplicate_groups),
        "deduplicated_image_count": deduped_train + deduped_test,
    }
    actual_ratios = {
        role: round(len(value) * 100 / total, 6) for role, value in ids.items()
    }
    selected_rows = [row for rows in roles.values() for row in rows]
    groups = {
        str(row.get("id")): components.get(str(row.get("id")), _group_key(row))
        for row in selected_rows
    }
    hashes = {
        str(row.get("id")): str(row.get("content_sha256") or "").strip()
        for row in selected_rows
    }
    return SplitManifest(
        mode=request.mode,
        ids=ids,
        counts=counts,
        requested=requested,
        actual_ratios=actual_ratios,
        groups=groups,
        content_hashes=hashes,
        exclusions=dict(sorted(exclusions.items())),
        test_seed=test_seed,
        validation_seed=validation_seed,
    )
