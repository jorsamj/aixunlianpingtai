"""Process-local, atomic storage for the material index."""

import json
import threading
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, TypeVar

from filelock import FileLock

from .annotations import atomic_write_json


_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[Path, threading.RLock] = {}
_CACHE_GUARD = threading.RLock()
_ROW_CACHE: dict[Path, tuple[tuple[int, int] | None, list[dict[str, Any]]]] = {}
_Result = TypeVar("_Result")


def _lock_for(path: Path) -> threading.RLock:
    resolved_path = path.resolve()
    with _LOCKS_GUARD:
        lock = _LOCKS.get(resolved_path)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[resolved_path] = lock
        return lock


def read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("images.json 必须是数组")
    return [dict(row) for row in rows]


def _file_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _cached_rows_shared(path: Path) -> list[dict[str, Any]]:
    resolved_path = path.resolve()
    signature = _file_signature(path)
    with _CACHE_GUARD:
        cached = _ROW_CACHE.get(resolved_path)
        if cached is not None and cached[0] == signature:
            return cached[1]

    rows = read_rows(path)
    signature = _file_signature(path)
    with _CACHE_GUARD:
        cached_rows = deepcopy(rows)
        _ROW_CACHE[resolved_path] = (signature, cached_rows)
    return cached_rows


def _cached_rows(path: Path) -> list[dict[str, Any]]:
    return deepcopy(_cached_rows_shared(path))


def _store_cached_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    with _CACHE_GUARD:
        _ROW_CACHE[path.resolve()] = (_file_signature(path), deepcopy(rows))


def read_revision(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def write_revision(path: Path, value: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(str(int(value)), encoding="utf-8")
    temp.replace(path)


@dataclass(frozen=True)
class MaterialSnapshot:
    revision: int
    rows: list[dict[str, Any]]


class MaterialStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.revision_path = self.path.with_suffix(".revision")
        self._lock = _lock_for(self.path)
        self._file_lock = FileLock(str(self.path.resolve()) + ".lock", timeout=30)

    def read(self) -> MaterialSnapshot:
        with self._lock:
            with self._file_lock:
                return MaterialSnapshot(
                    revision=read_revision(self.revision_path),
                    rows=_cached_rows(self.path),
                )

    def count(self) -> int:
        with self._lock:
            with self._file_lock:
                return len(_cached_rows_shared(self.path))

    def mutate(self, fn: Callable[[list[dict[str, Any]]], _Result]) -> _Result:
        with self._lock:
            with self._file_lock:
                rows = _cached_rows(self.path)
                result = fn(rows)
                atomic_write_json(self.path, rows)
                write_revision(self.revision_path, read_revision(self.revision_path) + 1)
                _store_cached_rows(self.path, rows)
                return result

    def upsert(self, record: Mapping[str, Any]) -> dict[str, Any]:
        incoming = dict(record)
        image_id = str(incoming.get("id"))

        def apply(rows: list[dict[str, Any]]) -> dict[str, Any]:
            for row in rows:
                if str(row.get("id")) == image_id:
                    row.update(incoming)
                    return dict(row)
            rows.append(incoming)
            return dict(incoming)

        return self.mutate(apply)

    def upsert_many(
        self,
        records: Iterable[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        incoming = [dict(record) for record in records]
        for record in incoming:
            if not str(record.get("id") or "").strip():
                raise ValueError("素材 id 不能为空")

        def apply(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            positions = {str(row.get("id")): index for index, row in enumerate(rows)}
            persisted = []
            for record in incoming:
                image_id = str(record["id"])
                position = positions.get(image_id)
                if position is None:
                    rows.append(dict(record))
                    positions[image_id] = len(rows) - 1
                    persisted.append(dict(record))
                else:
                    rows[position].update(record)
                    persisted.append(dict(rows[position]))
            return persisted

        return self.mutate(apply)

    def patch(self, patches: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
        normalized_patches = {
            str(image_id): dict(patch)
            for image_id, patch in patches.items()
        }

        def apply(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            changed = []
            for row in rows:
                patch = normalized_patches.get(str(row.get("id")))
                if patch is not None:
                    row.update(patch)
                    changed.append(dict(row))
            return changed

        return self.mutate(apply)

    def remove(self, image_ids: Iterable[str]) -> list[dict[str, Any]]:
        ids = {str(image_id) for image_id in image_ids}

        def apply(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            removed = [dict(row) for row in rows if str(row.get("id")) in ids]
            rows[:] = [row for row in rows if str(row.get("id")) not in ids]
            return removed

        return self.mutate(apply)
