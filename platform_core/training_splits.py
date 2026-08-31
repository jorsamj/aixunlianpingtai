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
    train_dataset_ids: tuple[str, ...]
    test_dataset_ids: tuple[str, ...] = ()
    experiment_percent: float | None = None
    validation_percent: float = 20

    def __post_init__(self) -> None:
        mode = SplitMode(self.mode)
        train_ids = tuple(dict.fromkeys(str(value).strip() for value in self.train_dataset_ids if str(value).strip()))
        test_ids = tuple(dict.fromkeys(str(value).strip() for value in self.test_dataset_ids if str(value).strip()))
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "train_dataset_ids", train_ids)
        object.__setattr__(self, "test_dataset_ids", test_ids)
        if not train_ids:
            raise ValueError("train_dataset_ids 不能为空")
        if not 0 < float(self.validation_percent) < 100:
            raise ValueError("validation_percent 必须大于 0 且小于 100")
        if mode == SplitMode.INDEPENDENT_TEST_SET:
            if not test_ids:
                raise ValueError("test_dataset_ids 不能为空")
            if set(train_ids) & set(test_ids):
                raise ValueError("训练数据集与独立试验数据集不能重复")
            if self.experiment_percent is not None:
                raise ValueError("独立试验集模式不能设置 experiment_percent")
        else:
            if test_ids:
                raise ValueError("随机抽取模式不能设置 test_dataset_ids")
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


def _group_key(row: Mapping[str, Any]) -> str:
    image_id = str(row.get("id") or "").strip()
    for key in ("group_id", "video_task_id", "source_group_id"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return image_id


def _processed(row: Mapping[str, Any]) -> bool:
    return bool(
        row.get("annotated")
        or row.get("processing_status") == "processed"
        or row.get("cleaned_at")
        or row.get("clean_skipped")
    )


def _select_grouped(rows: Sequence[Mapping[str, Any]], percent: float, seed: int) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_group_key(row), []).append(row)
    if len(grouped) < 2:
        raise ValueError("按来源分组后不足两个组，无法避免数据泄漏")
    keys = sorted(grouped)
    random.Random(int(seed)).shuffle(keys)
    sizes = [len(grouped[key]) for key in keys]
    target = max(1, min(len(rows) - 1, round(len(rows) * float(percent) / 100)))

    # Exact subset-sum where possible. Seeded key order makes ties deterministic.
    choices: dict[int, tuple[int, ...]] = {0: ()}
    for index, size in enumerate(sizes):
        for total, selected in list(choices.items())[::-1]:
            candidate = total + size
            if candidate < len(rows) and candidate not in choices:
                choices[candidate] = (*selected, index)
    selected_total = min(
        (total for total in choices if total > 0),
        key=lambda total: (abs(total - target), total > target, total),
    )
    selected_keys = {keys[index] for index in choices[selected_total]}
    selected = [row for row in rows if _group_key(row) in selected_keys]
    remaining = [row for row in rows if _group_key(row) not in selected_keys]
    return remaining, selected


def _identity(row: Mapping[str, Any]) -> str:
    for key in ("stored_name", "stored_path", "path"):
        value = str(row.get(key) or "").strip()
        if value:
            return PurePath(value.replace("\\", "/")).as_posix().casefold()
    return ""


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
) -> SplitManifest:
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in images:
        image_id = str(row.get("id") or "").strip()
        if not image_id:
            raise ValueError("素材缺少 id")
        if image_id in by_id:
            raise ValueError(f"素材 id 重复: {image_id}")
        by_id[image_id] = row

    train_datasets = set(request.train_dataset_ids)
    train_pool = [row for row in by_id.values() if str(row.get("dataset_id") or "") in train_datasets]
    if not train_pool:
        raise ValueError("训练数据集没有可用素材")

    test_seed = int(seed)
    digest = hashlib.sha256(f"validation:{seed}".encode("utf-8")).digest()
    validation_seed = int.from_bytes(digest[:8], "big")
    if request.mode == SplitMode.INDEPENDENT_TEST_SET:
        test_datasets = set(request.test_dataset_ids)
        test_rows = [row for row in by_id.values() if str(row.get("dataset_id") or "") in test_datasets]
        if not test_rows:
            raise ValueError("独立试验数据集没有可用素材")
        train_rows, validation_rows = _select_grouped(
            train_pool, request.validation_percent, validation_seed
        )
        test_source = "independent_dataset"
    else:
        after_test, test_rows = _select_grouped(
            train_pool, float(request.experiment_percent or 0), test_seed
        )
        train_rows, validation_rows = _select_grouped(
            after_test, request.validation_percent, validation_seed
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
        "train_dataset_ids": list(request.train_dataset_ids),
        "test_dataset_ids": list(request.test_dataset_ids),
        "experiment_percent": request.experiment_percent,
        "validation_percent": request.validation_percent,
    }
    actual_ratios = {
        role: round(len(value) * 100 / total, 6) for role, value in ids.items()
    }
    selected_rows = [row for rows in roles.values() for row in rows]
    groups = {str(row.get("id")): _group_key(row) for row in selected_rows}
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
        test_seed=test_seed,
        validation_seed=validation_seed,
    )

