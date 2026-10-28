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
            if float(self.experiment_percent) + float(self.validation_percent) >= 100:
                raise ValueError("experiment_percent 与 validation_percent 之和必须小于 100，保留训练集")


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
    "near_duplicate_group_id",
    "sequence_group_id",
)


def _processed(row: Mapping[str, Any]) -> bool:
    """Training eligibility is formal annotation truth, never cleaning state."""
    state = str(row.get("annotation_state") or "").strip().lower()
    if state:
        return state in {"annotated", "confirmed_empty"}
    # Legacy callers may not carry annotation_state yet. Keep only the old
    # explicit annotation flag; processing/cleaning metadata is not Ground Truth.
    return bool(row.get("annotated"))


def _identity(row: Mapping[str, Any]) -> str:
    for key in ("stored_name", "stored_path", "path"):
        value = str(row.get(key) or "").strip()
        if value:
            return PurePath(value.replace("\\", "/")).as_posix().casefold()
    return ""


def _relation_tokens(row: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    tokens: list[tuple[str, str]] = []
    # Originals and derivatives share one identity namespace. A child must join
    # its original even when only the child carries provenance fields.
    image_id = str(row.get('id') or row.get('image_id') or '').strip()
    if image_id:
        tokens.append(('image_id', image_id))
    for field in ('source_root_id', 'derived_from_image_id'):
        value = row.get(field)
        if value is None or value == '':
            continue
        if not isinstance(value, str) or value.strip() in {'.','..'} or any(char in value for char in ('/','\\',':')):
            raise ValueError('training derivative source identity must be a project image id')
        tokens.append(('image_id', value.strip()))
    content_hash = str(row.get("content_sha256") or "").strip().lower()
    if content_hash:
        tokens.append(("content_sha256", content_hash))
    identity = _identity(row)
    if identity:
        tokens.append(("file_identity", identity))
    for field in _COMPONENT_RELATION_FIELDS:
        value = str(row.get(field) or "").strip()
        if value:
            tokens.append((field, value))

    explicit_camera_session = str(
        row.get("camera_session_id") or row.get("capture_session_id") or ""
    ).strip()
    if explicit_camera_session:
        tokens.append(("camera_session", explicit_camera_session))
    else:
        camera_id = str(row.get("camera_id") or "").strip()
        session_id = str(row.get("session_id") or "").strip()
        if camera_id and session_id:
            tokens.append(("camera_session", f"{camera_id}\x1f{session_id}"))
    return tuple(tokens)


def _canonical_box(box: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    label = str(box.get("label") or box.get("code") or "").strip()
    if label:
        result["label"] = label
    elif box.get("class_id") is not None:
        try:
            result["class_id"] = int(box["class_id"])
        except (TypeError, ValueError):
            result["class_id"] = str(box["class_id"])
    for key in ("x1", "y1", "x2", "y2", "cx", "cy", "w", "h"):
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
    boxes = list(row.get("boxes") or [])
    state = str(
        row.get("annotation_state")
        or ("annotated" if boxes else "unannotated")
    )
    if state == "annotated" and not scope:
        scope = tuple(sorted({
            str(box.get("label") or box.get("code") or "").strip()
            for box in boxes
            if str(box.get("label") or box.get("code") or "").strip()
        }))
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


def training_annotation_digest(row: Mapping[str, Any]) -> str:
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


def analyze_training_duplicates(
    rows: Sequence[Mapping[str, Any]],
    train_image_ids: Sequence[str],
    test_image_ids: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Describe original GT duplicates without choosing which annotation is correct.

    The full membership stays server-side. Callers must page the member projection
    rather than sending these groups to the browser. Leakage always sorts first.
    """
    train, test = set(train_image_ids), set(test_image_ids)
    selected = train | test
    by_hash: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        if str(row.get("id") or "") not in selected:
            continue
        sha = str(row.get("content_sha256") or "").strip().lower()
        if sha:
            by_hash.setdefault(sha, []).append(row)
    groups = []
    for sha, members in by_hash.items():
        if len(members) < 2:
            continue
        ids = tuple(str(row.get("id") or "") for row in members)
        dimensions: dict[str, set[str]] = {key: set() for key in (
            "annotation_state", "annotation_scope", "labels", "box_count", "coordinates",
        )}
        digests = set()
        for row in members:
            boxes = [_canonical_box(box) for box in row.get("boxes") or []]
            dimensions["annotation_state"].add(str(row.get("annotation_state") or ("annotated" if boxes else "unannotated")))
            dimensions["annotation_scope"].add(json.dumps(_annotation_scope(row)))
            dimensions["labels"].add(json.dumps(sorted({str(box.get("label") or box.get("class_id") or "") for box in boxes})))
            dimensions["box_count"].add(str(len(boxes)))
            coordinates = [json.dumps({key: value for key, value in box.items()
                if key not in {"label", "class_id"}}, sort_keys=True, separators=(",", ":")) for box in boxes]
            dimensions["coordinates"].add(json.dumps(sorted(coordinates)))
            digests.add(training_annotation_digest(row))
        conflicts = [key for key, values in dimensions.items() if len(values) > 1]
        leakage = bool(train.intersection(ids) and test.intersection(ids))
        groups.append({
            "content_sha256": sha,
            "image_ids": ids,
            "issue_type": ("content_hash_leakage" if leakage else
                           "duplicate_annotation_conflict" if len(digests) > 1 else
                           "duplicate_identical"),
            "conflict_types": (["cross_role"] if leakage else []) + conflicts,
            "ground_truth_conflict": len(digests) > 1,
        })
    return sorted(groups, key=lambda group: (group["issue_type"] != "content_hash_leakage", group["content_sha256"]))


def assert_training_duplicate_safety(rows, train_image_ids, test_image_ids=()) -> None:
    for group in analyze_training_duplicates(rows, train_image_ids, test_image_ids):
        if group["issue_type"] == "duplicate_identical":
            continue
        if group["issue_type"] == "content_hash_leakage":
            raise ValueError(f"content hash leakage: {group['content_sha256']} 同时被显式选择为训练素材和独立试验素材")
        raise ValueError(
            "duplicate_annotation_conflict: "
            f"content_sha256={group['content_sha256']} 的重复素材标注不一致: "
            + ", ".join(group["image_ids"][:5])
        )


def _deduplicate_selected(
    rows: Sequence[Mapping[str, Any]],
    request: SplitRequest,
) -> tuple[list[Mapping[str, Any]], tuple[str, ...], dict[str, tuple[str, ...]]]:
    assert_training_duplicate_safety(rows, request.train_image_ids, request.test_image_ids)
    by_hash: dict[str, list[Mapping[str, Any]]] = {}
    without_hash: list[Mapping[str, Any]] = []
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

        ids = tuple(str(row.get("id") or "") for row in ordered)
        duplicate_groups[content_hash] = ids
        # The shared analyzer above has already rejected differing original GT
        # and any cross-role SHA; only equivalent same-role samples reach here.
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
        for token in _relation_tokens(row):
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


def exclude_reserved_test_components(
    images: Sequence[Mapping[str, Any]],
    train_image_ids: Sequence[str],
    test_image_ids: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Remove training candidates connected to a reserved independent test cohort.

    This reuses the same component relation truth as the split leakage guard so
    fixed-benchmark identities stay server-private while exact images, duplicate
    content, video/group siblings and other coupled samples cannot enter train/val.
    Callers may expose counts, but should not expose the excluded identities.
    """
    train_ids = tuple(dict.fromkeys(
        str(value).strip() for value in train_image_ids if str(value).strip()
    ))
    test_ids = tuple(dict.fromkeys(
        str(value).strip() for value in test_image_ids if str(value).strip()
    ))
    if not train_ids or not test_ids:
        return train_ids, ()

    wanted = set(train_ids) | set(test_ids)
    rows = [
        row for row in images
        if str(row.get("id") or "").strip() in wanted
    ]
    component_keys = _component_keys(rows)
    reserved_components = {
        component_keys[image_id]
        for image_id in test_ids
        if image_id in component_keys
    }
    test_id_set = set(test_ids)
    excluded = tuple(
        image_id for image_id in train_ids
        if image_id in test_id_set
        or component_keys.get(image_id) in reserved_components
    )
    excluded_set = set(excluded)
    return (
        tuple(image_id for image_id in train_ids if image_id not in excluded_set),
        excluded,
    )


def _row_label_codes(row: Mapping[str, Any]) -> set[str]:
    return {
        str(box.get("label") or box.get("code") or "").strip()
        for box in (row.get("boxes") or [])
        if isinstance(box, Mapping)
        and str(box.get("label") or box.get("code") or "").strip()
    }


def _reserve_required_train_components(
    rows: Sequence[Mapping[str, Any]],
    component_keys: Mapping[str, str],
    required_labels: Sequence[str],
    seed: int,
) -> set[str]:
    required = tuple(dict.fromkeys(
        str(value).strip() for value in required_labels if str(value).strip()
    ))
    if not required:
        return set()

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    group_labels: dict[str, set[str]] = {}
    for row in rows:
        image_id = str(row.get("id") or "")
        key = component_keys[image_id]
        grouped.setdefault(key, []).append(row)
        group_labels.setdefault(key, set()).update(_row_label_codes(row))

    available = set().union(*(group_labels.values())) if group_labels else set()
    missing = [label for label in required if label not in available]
    if missing:
        raise ValueError(
            "本次新增训练标签在训练候选中没有正样本: "
            + ", ".join(missing[:20])
        )

    order = sorted(grouped)
    random.Random(int(seed)).shuffle(order)
    rank = {key: index for index, key in enumerate(order)}
    needed = set(required)
    reserved: set[str] = set()
    while needed:
        candidates = [
            key for key in order
            if key not in reserved and group_labels.get(key, set()) & needed
        ]
        if not candidates:
            raise ValueError(
                "无法为本次新增训练标签保留训练正样本: "
                + ", ".join(sorted(needed)[:20])
            )
        chosen = min(
            candidates,
            key=lambda key: (
                -len(group_labels.get(key, set()) & needed),
                len(grouped[key]),
                rank[key],
            ),
        )
        reserved.add(chosen)
        needed.difference_update(group_labels.get(chosen, set()))
    return reserved


def _select_grouped(
    rows: Sequence[Mapping[str, Any]],
    component_keys: Mapping[str, str],
    percent: float,
    seed: int,
    *,
    min_remaining_groups: int = 1,
    reserved_component_keys: Sequence[str] = (),
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        image_id = str(row.get("id") or "")
        grouped.setdefault(component_keys[image_id], []).append(row)
    if len(grouped) <= int(min_remaining_groups):
        raise ValueError("按不可拆分数据组件分组后组数不足，无法避免数据泄漏")
    keys = sorted(grouped)
    random.Random(int(seed)).shuffle(keys)
    reserved = {
        str(key) for key in reserved_component_keys
        if str(key) in grouped
    }
    selectable_keys = [key for key in keys if key not in reserved]
    if not selectable_keys:
        raise ValueError("保留新增标签训练正样本后，没有可用于验证/试验划分的数据组件")
    sizes = [len(grouped[key]) for key in selectable_keys]
    target = max(1, min(len(rows) - 1, round(len(rows) * float(percent) / 100)))

    # Exact subset-sum with O(number_of_rows) Python-side state.
    #
    # The previous implementation stored the complete selected-index tuple for
    # every reachable total. With thousands of singleton components that means
    # sum(1..N) tuple entries and can consume quadratic memory before training
    # even starts. A Python integer is an efficient reachability bitset; each
    # total is discovered at most once, while predecessor arrays reconstruct the
    # exact same first-reached subset semantics as the old DP.
    max_total = len(rows) - 1
    reachable = 1  # bit 0
    mask = (1 << (max_total + 1)) - 1
    parent_total = [-1] * (max_total + 1)
    parent_group = [-1] * (max_total + 1)
    selected_counts = [-1] * (max_total + 1)
    selected_counts[0] = 0

    for index, size in enumerate(sizes):
        shifted = (reachable << size) & mask
        newly_reachable = shifted & ~reachable
        pending = newly_reachable
        while pending:
            bit = pending & -pending
            total = bit.bit_length() - 1
            previous = total - size
            parent_total[total] = previous
            parent_group[total] = index
            selected_counts[total] = selected_counts[previous] + 1
            pending ^= bit
        reachable |= shifted

    max_selected_groups = len(grouped) - int(min_remaining_groups)
    allowed_totals = [
        total
        for total in range(1, max_total + 1)
        if ((reachable >> total) & 1)
        and 0 < selected_counts[total] <= max_selected_groups
    ]
    if not allowed_totals:
        raise ValueError("所选不可拆分数据组件不足以划分训练、验证和试验数据")
    selected_total = min(
        allowed_totals,
        key=lambda total: (abs(total - target), total > target, total),
    )

    selected_indexes: set[int] = set()
    cursor = selected_total
    while cursor:
        index = parent_group[cursor]
        previous = parent_total[cursor]
        if index < 0 or previous < 0 or previous >= cursor:
            raise RuntimeError("split subset predecessor chain is invalid")
        selected_indexes.add(index)
        cursor = previous
    selected_keys = {selectable_keys[index] for index in selected_indexes}
    selected = [
        row for row in rows
        if component_keys[str(row.get("id") or "")] in selected_keys
    ]
    remaining = [
        row for row in rows
        if component_keys[str(row.get("id") or "")] not in selected_keys
    ]
    return remaining, selected



def _select_grouped_stratified(
    rows: Sequence[Mapping[str, Any]],
    component_keys: Mapping[str, str],
    percent: float,
    seed: int,
    *,
    min_remaining_groups: int = 1,
    min_future_positive_groups: int = 1,
    reserved_component_keys: Sequence[str] = (),
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Deterministic multilabel holdout at indivisible component granularity.

    Keep at least one positive component per label for training, and during
    test selection keep two where available for later train/validation.
    Prefer multi-class (and confirmed-empty) coverage before matching image
    quotas; never split a correlated component to improve percentages.
    Work scales with groups * labels, not a subset-sum over all combinations.
    """
    negative_label = "\x00confirmed_empty"
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    label_images: dict[str, dict[str, int]] = {}
    for row in rows:
        key = component_keys[str(row.get("id") or "")]
        grouped.setdefault(key, []).append(row)
        labels = _row_label_codes(row)
        if not labels and str(row.get("annotation_state") or "").strip().lower() == "confirmed_empty":
            labels = {negative_label}
        counts = label_images.setdefault(key, {})
        for label in labels:
            counts[label] = counts.get(label, 0) + 1
    if len(grouped) <= int(min_remaining_groups):
        raise ValueError("按不可拆分数据组件分组后组数不足，无法避免数据泄漏")

    keys = sorted(grouped)
    random.Random(int(seed)).shuffle(keys)
    rank = {key: index for index, key in enumerate(keys)}
    reserved = set(reserved_component_keys) & set(grouped)
    sizes = {key: len(grouped[key]) for key in keys}
    by_label: dict[str, list[str]] = {}
    support: dict[str, int] = {}
    total_label_images: dict[str, int] = {}
    for key in keys:
        for label, count in label_images.get(key, {}).items():
            by_label.setdefault(label, []).append(key)
            support[label] = support.get(label, 0) + 1
            total_label_images[label] = total_label_images.get(label, 0) + count

    # A rare class observed in only one independent group stays in training.
    # Test can take a class only when >= 3 independent groups exist; validation
    # can take it when >= 2 remain. Fixed independent Test is handled outside.
    keep = {
        label: min(count, int(min_future_positive_groups))
        for label, count in support.items()
    }
    selected_keys: set[str] = set()
    selected_image_count = 0
    selected_label_images: dict[str, int] = {}
    remaining_support = dict(support)
    max_selected_groups = len(grouped) - int(min_remaining_groups)
    target = max(1, min(len(rows) - 1, round(len(rows) * float(percent) / 100)))

    def eligible(key: str, *, fit: bool = False) -> bool:
        if key in selected_keys or key in reserved or len(selected_keys) >= max_selected_groups:
            return False
        if selected_image_count + sizes[key] >= len(rows):
            return False
        if fit and selected_image_count + sizes[key] > target:
            return False
        return all(
            remaining_support[label] > keep[label]
            for label in label_images.get(key, {})
        )

    def take(key: str) -> None:
        nonlocal selected_image_count
        selected_keys.add(key)
        selected_image_count += sizes[key]
        for label, count in label_images.get(key, {}).items():
            remaining_support[label] -= 1
            selected_label_images[label] = selected_label_images.get(label, 0) + count

    # Cover rarer classes first; one mixed-label component can cover several.
    for label in sorted(support, key=lambda item: (support[item], item)):
        if selected_label_images.get(label, 0) or selected_image_count >= target:
            continue
        candidates = (key for key in by_label[label] if eligible(key))
        best = min(
            candidates,
            key=lambda key: (
                max(0, selected_image_count + sizes[key] - target),
                sizes[key],
                -len(label_images[key]),
                rank[key],
            ),
            default=None,
        )
        if best is not None:
            take(best)

    # Deficit-driven pass balances positive image counts, not only presence.
    desired = {
        label: max(1, round(count * float(percent) / 100))
        for label, count in total_label_images.items()
    }
    positions = {label: 0 for label in by_label}
    exhausted: set[str] = set()
    while selected_image_count < target:
        pending = [
            label for label in by_label
            if label not in exhausted
            and selected_label_images.get(label, 0) < desired[label]
        ]
        if not pending:
            break
        label = max(
            pending,
            key=lambda item: (
                (desired[item] - selected_label_images.get(item, 0)) / desired[item],
                -support[item],
                item,
            ),
        )
        candidates = by_label[label]
        chosen = None
        while positions[label] < len(candidates):
            key = candidates[positions[label]]
            positions[label] += 1
            if eligible(key, fit=True):
                chosen = key
                break
        if chosen is None:
            exhausted.add(label)
        else:
            take(chosen)

    # Complete the requested image quota with unlabeled/other components.
    # A single final closest-overshoot choice is optional; isolation wins.
    if selected_image_count < target:
        for key in keys:
            if selected_image_count >= target:
                break
            if eligible(key, fit=True):
                take(key)
    if selected_image_count < target:
        best = min(
            (key for key in keys if eligible(key)),
            key=lambda key: (
                abs(selected_image_count + sizes[key] - target),
                sizes[key],
                rank[key],
            ),
            default=None,
        )
        if best is not None and abs(selected_image_count + sizes[best] - target) < target - selected_image_count:
            take(best)

    if not selected_keys:
        raise ValueError(
            "无法在保留训练类别正样本、来源关联组及剩余集合的前提下划分留出集；"
            "请补充独立来源素材或调整数据划分比例"
        )
    return (
        [row for row in rows if component_keys[str(row.get("id") or "")] not in selected_keys],
        [row for row in rows if component_keys[str(row.get("id") or "")] in selected_keys],
    )


def _assert_no_leakage(role_rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    owners: dict[tuple[str, str], str] = {}
    for role, rows in role_rows.items():
        for row in rows:
            for relation_type, value in _relation_tokens(row):
                token = (relation_type, value)
                previous = owners.setdefault(token, role)
                if previous != role:
                    label = relation_type.replace("_", " ")
                    raise ValueError(
                        f"{label} leakage: {value} 同时出现在 {previous} 和 {role}"
                    )


def build_split_manifest(
    images: Sequence[Mapping[str, Any]],
    request: SplitRequest,
    *,
    seed: int,
    required_train_labels: Sequence[str] = (),
    split_strategy: str = "legacy_v1",
    forbidden_test_image_ids: Sequence[str] = (),
) -> SplitManifest:
    if split_strategy not in {"legacy_v1", "multilabel_grouped_v2"}:
        raise ValueError("unknown training split strategy")
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
    required_labels = tuple(dict.fromkeys(
        str(value).strip()
        for value in required_train_labels
        if str(value).strip()
    ))
    reserved_train_components = _reserve_required_train_components(
        train_pool, component_keys, required_labels, int(seed),
    )
    history_test_components = {component_keys[item] for item in forbidden_test_image_ids if item in component_keys}
    if request.mode == SplitMode.INDEPENDENT_TEST_SET and any(
        component_keys[str(row['id'])] in history_test_components for row in independent_test_rows
    ):
        raise ValueError('TRAINING_TEST_HISTORY_EXPOSURE: parent model has seen selected Test materials')
    test_seed = int(seed)
    digest = hashlib.sha256(f"validation:{seed}".encode("utf-8")).digest()
    validation_seed = int.from_bytes(digest[:8], "big")

    selector = _select_grouped_stratified if split_strategy == "multilabel_grouped_v2" else _select_grouped

    if request.mode == SplitMode.INDEPENDENT_TEST_SET:
        test_rows = independent_test_rows
        train_rows, validation_rows = selector(
            train_pool,
            component_keys,
            request.validation_percent,
            validation_seed,
            reserved_component_keys=reserved_train_components,
        )
        test_source = "independent_materials"
    else:
        after_test, test_rows = selector(
            train_pool,
            component_keys,
            float(request.experiment_percent or 0),
            test_seed,
            min_remaining_groups=2,
            **({"min_future_positive_groups": 2} if split_strategy == "multilabel_grouped_v2" else {}),
            reserved_component_keys=set(reserved_train_components) | history_test_components,
        )
        # Percentages are measured against the complete frozen pool.
        # The test holdout is frozen first, so rebase the validation target
        # onto the remaining pool without weakening the leakage guard.
        validation_of_remaining = float(request.validation_percent) * 100.0 / (100.0 - float(request.experiment_percent))
        train_rows, validation_rows = selector(
            after_test,
            component_keys,
            validation_of_remaining,
            validation_seed,
            reserved_component_keys=reserved_train_components,
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
        **({"split_strategy": split_strategy} if split_strategy == "multilabel_grouped_v2" else {}),
        **({'forbidden_test_image_ids': sorted(set(forbidden_test_image_ids))} if forbidden_test_image_ids else {}),
        **(
            {
                "required_train_labels": list(required_labels),
                "reserved_train_component_count": len(reserved_train_components),
            }
            if required_labels else {}
        ),
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
