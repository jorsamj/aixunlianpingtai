"""Durable upload receipts with cross-process request ownership."""

import asyncio
import copy
import json
import re
import threading
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Iterator, Mapping, Sequence, TypeVar

from filelock import FileLock, Timeout

from .annotations import atomic_write_json


_BATCH_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_DECISIONS = {"pending", "clean", "ready"}
_UPLOAD_REQUEST_STATUSES = {"PROCESSING", "SUCCEEDED", "FAILED"}
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[Path, threading.RLock] = {}
_Result = TypeVar("_Result")


class UploadRequestBusy(RuntimeError):
    """Another worker holds the same upload request ID."""



def _validate_batch_id(batch_id: str) -> str:
    if not isinstance(batch_id, str) or not _BATCH_ID_PATTERN.fullmatch(batch_id):
        raise ValueError("上传批次 ID 无效")
    return batch_id


def _normalize_upload_request_manifest(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("上传请求 manifest 必须是数组")
    rows: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise ValueError("上传请求 manifest 元素必须是对象")
        name = str(raw.get("name") or "").strip()
        if not name:
            raise ValueError("上传请求 manifest 文件名不能为空")
        try:
            size = int(raw.get("size") or 0)
        except (TypeError, ValueError) as error:
            raise ValueError("上传请求 manifest 文件大小无效") from error
        if size < 0:
            raise ValueError("上传请求 manifest 文件大小无效")
        row = {"name": name, "size": size, "content_type": str(raw.get("content_type") or "")}
        # Legacy receipts without SHA remain readable, but cannot silently
        # match new content-bound requests. All new API receipts carry SHA256.
        if "sha256" in raw:
            content_hash = str(raw["sha256"] or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", content_hash):
                raise ValueError("上传请求 manifest 内容 SHA256 无效")
            row["sha256"] = content_hash
        rows.append(row)
    return rows


def _normalize_upload_failures(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("上传失败记录必须是数组")
    rows: list[dict[str, str]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise ValueError("上传失败记录元素必须是对象")
        rows.append({"name": str(raw.get("name") or "文件"), "reason": str(raw.get("reason") or "处理失败")})
    return rows


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
    if "upload_request_status" in batch:
        status = str(batch.get("upload_request_status") or "").strip().upper()
        if status not in _UPLOAD_REQUEST_STATUSES:
            raise ValueError("上传请求状态无效")
        batch["upload_request_status"] = status
        batch["upload_request_manifest"] = _normalize_upload_request_manifest(batch.get("upload_request_manifest"))
        batch["upload_failed"] = _normalize_upload_failures(batch.get("upload_failed"))
        if "upload_dataset_id" in batch:
            batch["upload_dataset_id"] = str(batch.get("upload_dataset_id") or "default")
        if "upload_storage_source_id" in batch:
            batch["upload_storage_source_id"] = str(batch.get("upload_storage_source_id") or "default_local")
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
        # First upload in a fresh project must be able to acquire both the
        # cross-process receipt lock and the request claim BEFORE the first
        # receipt JSON is written.
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, batch_id: str) -> Path:
        return self.directory / f"{_validate_batch_id(batch_id)}.json"

    @contextmanager
    def locked(self, batch_id: str) -> Iterator[None]:
        path = self._path(batch_id)
        # Keep the local RLock for nested mutations; serialize across workers.
        with _lock_for(path):
            with FileLock(str(path) + ".store.lock", timeout=30):
                yield

    @asynccontextmanager
    async def claim_upload_request(self, batch_id: str) -> AsyncIterator[None]:
        """Hold the same request ID across all awaits and the receipt commit.

        Acquisition is off-loop. Keep the lease proxy alive until release:
        discarding the proxy would otherwise release the OS lock.
        """
        path = self._path(batch_id)
        lock = FileLock(str(path) + ".request.lock", thread_local=False)
        try:
            lease = await asyncio.to_thread(lock.acquire, timeout=0)
        except Timeout as error:
            raise UploadRequestBusy("该上传请求正在另一工作进程执行") from error
        try:
            yield
        finally:
            await asyncio.to_thread(lock.release)
            del lease

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

    def begin_upload_request(
        self, batch_id: str, *, created_at: str,
        manifest: Sequence[Mapping[str, Any]], dataset_id: str, storage_source_id: str,
    ) -> tuple[dict[str, Any], bool]:
        """Create the durable idempotency receipt before material writes begin."""
        batch_id = _validate_batch_id(batch_id)
        normalized_manifest = _normalize_upload_request_manifest(list(manifest))
        expected_dataset = str(dataset_id or "default")
        expected_source = str(storage_source_id or "default_local")
        with self.locked(batch_id):
            path = self._path(batch_id)
            if path.is_file():
                current = self._read_unlocked(batch_id)
                if (
                    current.get("upload_request_manifest") != normalized_manifest
                    or str(current.get("upload_dataset_id") or "default") != expected_dataset
                    or str(current.get("upload_storage_source_id") or "default_local") != expected_source
                ):
                    raise ValueError("上传请求 ID 已用于不同文件或保存位置")
                return current, False
            value = {
                "id": batch_id, "created_at": str(created_at), "updated_at": str(created_at),
                "items": [], "upload_request_status": "PROCESSING",
                "upload_request_manifest": normalized_manifest, "upload_failed": [],
                "upload_dataset_id": expected_dataset, "upload_storage_source_id": expected_source,
            }
            return self._write_unlocked(batch_id, value), True

    def prepare_upload_request(
        self, batch_id: str, image_ids: Sequence[str], *,
        failed: Sequence[Mapping[str, Any]], prepared_at: str,
    ) -> dict[str, Any]:
        """Persist intended image identities before any Material DB commit."""
        ids = [str(image_id) for image_id in image_ids if str(image_id)]
        if len(set(ids)) != len(ids):
            raise ValueError("上传准备阶段存在重复素材 ID")
        with self.locked(batch_id):
            batch = self._read_unlocked(batch_id)
            if batch.get("upload_request_status") != "PROCESSING":
                raise ValueError("上传请求不处于准备状态")
            if "upload_prepared_image_ids" in batch:
                raise ValueError("上传请求已经准备，不能重复执行提交")
            batch["upload_prepared_image_ids"] = ids
            batch["upload_failed"] = _normalize_upload_failures(list(failed))
            batch["upload_prepared_at"] = str(prepared_at)
            batch["updated_at"] = str(prepared_at)
            return self._write_unlocked(batch_id, batch)

    def complete_upload_request(
        self, batch_id: str, image_ids: Sequence[str], *,
        failed: Sequence[Mapping[str, Any]], finished_at: str,
        elapsed_seconds: float, material_total: int,
    ) -> dict[str, Any]:
        batch_id = _validate_batch_id(batch_id)
        with self.locked(batch_id):
            batch = self._read_unlocked(batch_id)
            status = str(batch.get("upload_request_status") or "").upper()
            if status == "SUCCEEDED":
                return batch
            if status != "PROCESSING":
                raise ValueError("上传请求不处于可完成状态")
            completed_ids = [str(image_id) for image_id in image_ids if str(image_id)]
            if (
                "upload_prepared_image_ids" in batch
                and batch["upload_prepared_image_ids"] != completed_ids
            ):
                raise ValueError("上传完成 ID 与准备阶段不一致")
            batch["items"] = [{"image_id": image_id, "decision": "pending"} for image_id in completed_ids]
            batch["upload_request_status"] = "SUCCEEDED"
            batch["upload_failed"] = _normalize_upload_failures(list(failed))
            batch["upload_elapsed_seconds"] = round(max(0.0, float(elapsed_seconds)), 2)
            batch["upload_material_total"] = max(0, int(material_total))
            batch["finished_at"] = str(finished_at)
            batch["updated_at"] = str(finished_at)
            batch.pop("upload_request_error", None)
            return self._write_unlocked(batch_id, batch)

    def fail_upload_request(self, batch_id: str, *, error: str, failed_at: str) -> dict[str, Any]:
        batch_id = _validate_batch_id(batch_id)
        with self.locked(batch_id):
            batch = self._read_unlocked(batch_id)
            if str(batch.get("upload_request_status") or "").upper() == "SUCCEEDED":
                return batch
            batch["upload_request_status"] = "FAILED"
            batch["upload_request_error"] = str(error or "上传请求失败")
            batch["failed_at"] = str(failed_at)
            batch["updated_at"] = str(failed_at)
            return self._write_unlocked(batch_id, batch)

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
