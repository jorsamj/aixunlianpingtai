"""Atomic, process-local persistence for upload decision batches."""

import copy
import json
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence, TypeVar

from .annotations import atomic_write_json


_BATCH_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_DECISIONS = {"pending", "clean", "ready"}
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[Path, threading.RLock] = {}
_Result = TypeVar("_Result")


def _validate_batch_id(batch_id: str) -> str:
    if not isinstance(batch_id, str) or not _BATCH_ID_PATTERN.fullmatch(batch_id):
        raise ValueError("上传批次 ID 无效")
    return batch_id


def _lock_for(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _LOCKS_GUARD:
        lock = _LOCKS.get(resolved)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[resolved] = lock
        return lock


def _validated_batch(value: Any, expected_id: str | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("上传批次 JSON 必须是对象")
    batch = copy.deepcopy(dict(value))
    batch_id = _validate_batch_id(batch.get("id"))
    if expected_id is not None and batch_id != expected_id:
        raise ValueError("上传批次 ID 与文件名不一致")
    if not isinstance(batch.get("created_at"), str):
        raise ValueError("上传批次 created_at 必须是字符串")
    raw_items = batch.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("上传批次 items 必须是数组")
    items = []
    seen = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            raise ValueError("上传批次 items 元素必须是对象")
        item = copy.deepcopy(dict(raw_item))
        image_id = item.get("image_id")
        decision = item.get("decision")
        if not isinstance(image_id, str) or not image_id:
            raise ValueError("上传批次 image_id 必须是非空字符串")
        if image_id in seen:
            raise ValueError("上传批次 image_id 不能重复")
        if decision not in _DECISIONS:
            raise ValueError("上传批次 decision 无效")
        seen.add(image_id)
        items.append(item)
    batch["items"] = items
    if "clean_task_id" in batch and batch["clean_task_id"] is not None:
        if not isinstance(batch["clean_task_id"], str) or not batch["clean_task_id"]:
            raise ValueError("上传批次 clean_task_id 必须是非空字符串")
    if "clean_task_image_ids" in batch:
        clean_task_image_ids = batch["clean_task_image_ids"]
        if not isinstance(clean_task_image_ids, list) or any(
            not isinstance(image_id, str) or image_id not in seen
            for image_id in clean_task_image_ids
        ):
            raise ValueError("上传批次 clean_task_image_ids 无效")
        batch["clean_task_image_ids"] = list(dict.fromkeys(clean_task_image_ids))
    return batch


def create_upload_batch(
    directory: Path,
    batch_id: str,
    image_ids: Sequence[str],
    created_at: str,
) -> dict[str, Any]:
    batch_id = _validate_batch_id(batch_id)
    value = {
        "id": batch_id,
        "created_at": str(created_at),
        "items": [
            {"image_id": str(image_id), "decision": "pending"}
            for image_id in image_ids
        ],
    }
    value = _validated_batch(value, batch_id)
    atomic_write_json(Path(directory) / f"{batch_id}.json", value)
    return value


def apply_decisions(
    batch: Mapping[str, Any],
    clean_ids: set[str],
    ready_ids: set[str],
) -> dict[str, Any]:
    updated = _validated_batch(batch)
    clean = {str(image_id) for image_id in clean_ids}
    ready = {str(image_id) for image_id in ready_ids}
    if clean & ready:
        raise ValueError("同一张图片不能同时选择清洗和无需清洗")
    members = {item["image_id"] for item in updated["items"]}
    unknown = (clean | ready) - members
    if unknown:
        raise ValueError(f"图片不属于该上传批次：{', '.join(sorted(unknown))}")
    for item in updated["items"]:
        image_id = item["image_id"]
        if image_id in clean:
            item["decision"] = "clean"
        elif image_id in ready:
            item["decision"] = "ready"
    return updated


class UploadBatchStore:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def _path(self, batch_id: str) -> Path:
        return self.directory / f"{_validate_batch_id(batch_id)}.json"

    @contextmanager
    def locked(self, batch_id: str) -> Iterator[None]:
        path = self._path(batch_id)
        with _lock_for(path):
            yield

    def _read_unlocked(self, batch_id: str) -> dict[str, Any]:
        path = self._path(batch_id)
        if not path.is_file():
            raise FileNotFoundError(path)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("上传批次 JSON 无效") from error
        return _validated_batch(value, batch_id)

    def _write_unlocked(self, batch_id: str, value: Mapping[str, Any]) -> dict[str, Any]:
        validated = _validated_batch(value, _validate_batch_id(batch_id))
        atomic_write_json(self._path(batch_id), validated)
        return validated

    def create(
        self,
        batch_id: str,
        image_ids: Sequence[str],
        created_at: str,
    ) -> dict[str, Any]:
        with self.locked(batch_id):
            return create_upload_batch(
                self.directory,
                batch_id,
                image_ids,
                created_at,
            )

    def read(self, batch_id: str) -> dict[str, Any]:
        with self.locked(batch_id):
            return self._read_unlocked(batch_id)

    def mutate(
        self,
        batch_id: str,
        fn: Callable[[dict[str, Any]], tuple[Mapping[str, Any], _Result]],
    ) -> _Result:
        with self.locked(batch_id):
            batch = self._read_unlocked(batch_id)
            updated, result = fn(batch)
            self._write_unlocked(batch_id, updated)
            return result

    def update_decisions(
        self,
        batch_id: str,
        clean_ids: set[str],
        ready_ids: set[str],
    ) -> dict[str, Any]:
        def update(batch: dict[str, Any]):
            updated = apply_decisions(batch, clean_ids, ready_ids)
            return updated, updated

        return self.mutate(batch_id, update)
