from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path, PureWindowsPath
from typing import Any, Callable

from .payload_publications import (
    DEFAULT_MAX_PAYLOAD_BYTES, VERSION_REF, EVIDENCE_REF, PayloadPublicationError, PayloadPublicationIdentity,
    PayloadVersionStore, PreparedPayloadPublication, VerifiedPayload, is_reserved_path,
)


class ArtifactStore:
    def __init__(self, root: str | Path, *, max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
                 max_receipt_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._payload_versions = PayloadVersionStore(self.root, max_payload_bytes, max_receipt_bytes)

    @property
    def payload_reader(self):
        """Evidence reads confer no Task mutation or execution authority."""
        return self._payload_versions

    def prepare_payload_publication(
        self, identity: PayloadPublicationIdentity, payload: Any, *, activation: dict | None = None,
        _before_publish: Callable[[], None] = lambda: None,
    ) -> PreparedPayloadPublication:
        """Prepare immutable files only; this does not publish a Task reference."""
        return self._payload_versions.prepare_payload_publication(
            identity, payload, activation=activation, before_publish=_before_publish)

    def read_payload_version(self, task_id: str, payload_ref: str) -> VerifiedPayload:
        return self._payload_versions.read_payload_version(task_id, payload_ref)

    def write_evidence_json(self, task_id, value, *, _before_publish=lambda: None):
        return self._payload_versions.write_evidence_json(task_id, value, before_publish=_before_publish)

    def write_execution_anchor(self, task_id, attempt, value, *, _before_publish=lambda: None):
        return self._payload_versions.write_execution_anchor(task_id, attempt, value, before_publish=_before_publish)

    def read_execution_anchor(self, task_id, attempt):
        return self._payload_versions.read_execution_anchor(task_id, attempt)

    def read_payload_publication_receipt(
        self, task_id: str, operation_id: str, *, identity: PayloadPublicationIdentity | None = None,
    ) -> PreparedPayloadPublication:
        return self._payload_versions.read_payload_publication_receipt(task_id, operation_id, identity=identity)

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
        if self.root not in task_root.parents:
            raise ValueError("task artifact root escaped")
        resolved = (task_root / candidate).resolve()
        if resolved != task_root and task_root not in resolved.parents:
            raise ValueError("relative task artifact path required")
        if is_reserved_path(candidate.parts) or is_reserved_path(resolved.relative_to(self.root).parts):
            raise ValueError("PAYLOAD_RESERVED_NAMESPACE: use controlled Payload interfaces")
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
        if VERSION_REF.fullmatch(str(relative_path)):
            return self.read_payload_version(task_id, relative_path).data
        if EVIDENCE_REF.fullmatch(str(relative_path)):
            return self._payload_versions.read_evidence_json(task_id, relative_path)
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

    def retention_required(self, task_id):
        lexical=self.root/self._validate_task_id(task_id)
        if lexical.is_symlink() or getattr(lexical,'is_junction',lambda:False)():
            raise ValueError('task artifact root link is unsafe for deletion')
        task_root=self.artifact_path(task_id,'.')
        return any(parent.is_dir() and any(is_reserved_path((child.name,)) for child in parent.iterdir())
                   for parent in (task_root,task_root/'scenario'))

    def delete_task(self, task_id: str) -> bool:
        safe_task_id = self._validate_task_id(task_id)
        lexical=self.root/safe_task_id
        if lexical.is_symlink() or getattr(lexical,'is_junction',lambda:False)():
            raise ValueError('task artifact root link is unsafe for deletion')
        task_root = (self.root / safe_task_id).resolve()
        if task_root.parent != self.root:
            raise ValueError("task artifact root escaped")
        if task_root.is_symlink():
            task_root.unlink(missing_ok=True)
            return True
        if not task_root.exists():
            return False
        # Check all protected roots BEFORE deleting anything. Legacy tasks with
        # no P1 namespace retain their existing deletion behavior.
        for parent in (task_root, task_root / "scenario"):
            if parent.is_dir() and any(is_reserved_path((child.name,)) for child in parent.iterdir()):
                raise PayloadPublicationError("ARTIFACT_RETENTION_REQUIRED", "immutable Payload artifacts retained; no P1 GC")
        shutil.rmtree(task_root)
        return True
