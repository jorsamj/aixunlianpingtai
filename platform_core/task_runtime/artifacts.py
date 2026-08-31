from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path, PureWindowsPath
from typing import Any


class ArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_task_id(task_id: str) -> str:
        value = str(task_id)
        windows = PureWindowsPath(value)
        if (
            not value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
            or windows.drive
            or windows.root
        ):
            raise ValueError("task id must be one safe path component")
        return value

    def artifact_path(self, task_id: str, relative_path: str) -> Path:
        safe_task_id = self._validate_task_id(task_id)
        raw = str(relative_path)
        candidate = Path(raw)
        windows = PureWindowsPath(raw)
        if (
            not raw
            or "\\" in raw
            or candidate.is_absolute()
            or windows.is_absolute()
            or windows.drive
            or windows.root
            or ".." in candidate.parts
            or ".." in windows.parts
        ):
            raise ValueError("relative task artifact path required")

        task_root = (self.root / safe_task_id).resolve()
        resolved = (task_root / candidate).resolve()
        if resolved != task_root and task_root not in resolved.parents:
            raise ValueError("relative task artifact path required")
        return resolved

    def atomic_write_json(self, task_id: str, relative_path: str, value: Any) -> None:
        path = self.artifact_path(task_id, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                json.dump(value, stream, ensure_ascii=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)

    def read_json(self, task_id: str, relative_path: str, default: Any = None) -> Any:
        path = self.artifact_path(task_id, relative_path)
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def append_log(self, task_id: str, relative_path: str, text: str) -> None:
        path = self.artifact_path(task_id, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="") as stream:
            stream.write(str(text))
            stream.flush()
