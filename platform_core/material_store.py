"""Process-local, atomic storage for the material index."""

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar

from .annotations import atomic_write_json


_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[Path, threading.RLock] = {}
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

    def read(self) -> MaterialSnapshot:
        with self._lock:
            return MaterialSnapshot(
                revision=read_revision(self.revision_path),
                rows=read_rows(self.path),
            )

    def mutate(self, fn: Callable[[list[dict[str, Any]]], _Result]) -> _Result:
        with self._lock:
            rows = read_rows(self.path)
            result = fn(rows)
            atomic_write_json(self.path, rows)
            write_revision(self.revision_path, read_revision(self.revision_path) + 1)
            return result

    def upsert(self, record: Mapping[str, Any]) -> dict[str, Any]:
        incoming = dict(record)
        image_id = incoming.get("id")

        def apply(rows: list[dict[str, Any]]) -> dict[str, Any]:
            for row in rows:
                if row.get("id") == image_id:
                    row.update(incoming)
                    return dict(row)
            rows.append(incoming)
            return dict(incoming)

        return self.mutate(apply)

    def patch(self, patches: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
        def apply(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            changed = []
            for row in rows:
                patch = patches.get(str(row.get("id")))
                if patch is not None:
                    row.update(patch)
                    changed.append(dict(row))
            return changed

        return self.mutate(apply)

    def remove(self, image_ids: set[str]) -> list[dict[str, Any]]:
        ids = {str(image_id) for image_id in image_ids}

        def apply(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            removed = [dict(row) for row in rows if str(row.get("id")) in ids]
            rows[:] = [row for row in rows if str(row.get("id")) not in ids]
            return removed

        return self.mutate(apply)
