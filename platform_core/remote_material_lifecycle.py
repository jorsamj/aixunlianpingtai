"""Lifecycle governance for temporary Remote MATERIAL_IMPORT staging objects.

Only exact task-owned object references are eligible. The implementation never
lists/deletes by prefix and never touches formal target material object keys.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from filelock import FileLock, Timeout

from .task_runtime import TaskKind, TaskStatus


REMOTE_MATERIAL_CLEANUP_REF = "remote-material/staging-cleanup.json"
REMOTE_MATERIAL_GC_STATE_REF = "remote-material-gc-state.json"
REMOTE_MATERIAL_STAGING_RETENTION_SECONDS = max(
    3600,
    int(os.environ.get("MC_REMOTE_MATERIAL_STAGING_RETENTION_SECONDS", 7 * 24 * 3600)),
)
_TERMINAL = {
    TaskStatus.SUCCEEDED,
    TaskStatus.PARTIAL_SUCCESS,
    TaskStatus.CANCELLED,
    TaskStatus.FAILED,
    TaskStatus.BLOCKED_BY_ENVIRONMENT,
    TaskStatus.BLOCKED_BY_HARDWARE,
}


def _utc(value: datetime | str | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _iso(value: datetime | str | None = None) -> str:
    return _utc(value).isoformat()


def _safe_segment(value: object, fallback: str) -> str:
    text = "".join(
        char if char.isalnum() or char in "._-" else "-"
        for char in str(value or "").strip()
    ).strip("-._")
    return (text or fallback)[:120]


def _owned_prefix(project_id: str, task_id: str) -> str:
    return (
        f"remote-execution/{_safe_segment(project_id, 'project')}/"
        f"{_safe_segment(task_id, 'task')}/"
    )


def _normalized_ref(
    *,
    task,
    value: Mapping[str, Any],
    role: str,
    sha256: object,
    size_bytes: object,
) -> dict[str, Any]:
    source_id = str(value.get("storage_source_id") or "").strip()
    object_key = str(value.get("object_key") or "").strip().replace("\\", "/")
    digest = str(sha256 or "").strip().lower()
    try:
        size = int(size_bytes)
    except (TypeError, ValueError) as error:
        raise ValueError("staging object size evidence is invalid") from error
    prefix = _owned_prefix(str(task.project_id), str(task.task_id))
    path = PurePosixPath(object_key)
    if (
        not source_id
        or not object_key
        or path.is_absolute()
        or ".." in path.parts
        or not object_key.startswith(prefix)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
        or size <= 0
    ):
        raise ValueError("staging object reference is not task-owned or lacks evidence")
    return {
        "role": str(role),
        "storage_source_id": source_id,
        "object_key": object_key,
        "sha256": digest,
        "size_bytes": size,
        "status": "PENDING",
        "last_error": "",
        "last_attempt_at": None,
        "deleted_at": None,
    }


def material_staging_refs(
    task,
    payload: Mapping[str, Any],
    *,
    confirmed: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
    artifacts=None,
) -> list[dict[str, Any]]:
    if task.kind is not TaskKind.MATERIAL_IMPORT:
        return []
    remote = payload.get("remote_execution")
    if not isinstance(remote, Mapping):
        return []
    material = remote.get("material_import")
    if (
        not isinstance(material, Mapping)
        or int(remote.get("version") or 0) != 1
        or str(remote.get("task_kind") or "") != "MATERIAL_IMPORT"
        or str(remote.get("transport") or "") != "object-storage-v1"
    ):
        return []
    result: list[dict[str, Any]] = []
    input_ref = material.get("input")
    if isinstance(input_ref, Mapping):
        result.append(
            _normalized_ref(
                task=task,
                value=input_ref,
                role="input",
                sha256=input_ref.get("sha256"),
                size_bytes=input_ref.get("size_bytes"),
            )
        )

    output_ref = None
    output_sha = None
    output_size = None
    if isinstance(confirmed, Mapping):
        confirmed_result = confirmed.get("result")
        if isinstance(confirmed_result, Mapping):
            output_ref = confirmed_result.get("output_storage")
            output_sha = confirmed_result.get("output_sha256")
            output_size = confirmed_result.get("output_size_bytes")
    if isinstance(evidence, Mapping):
        output_sha = output_sha or evidence.get("sha256")
        output_size = output_size or evidence.get("size_bytes")

    if not isinstance(output_ref, Mapping) and artifacts is not None:
        # A failed/cancelled generation can have prepared an immutable result
        # object without reaching confirm. Recover the exact generation-owned
        # storage_ref from the durable upload state rather than deriving keys.
        for generation in range(1, max(0, int(getattr(task, "attempt", 0))) + 1):
            state = artifacts.read_json(
                str(task.task_id),
                f"remote-results/{generation}/upload.json",
                default={},
            )
            if not isinstance(state, Mapping):
                continue
            storage_ref = state.get("storage_ref")
            if not isinstance(storage_ref, Mapping):
                continue
            try:
                candidate = _normalized_ref(
                    task=task,
                    value=storage_ref,
                    role=f"review:generation-{generation}",
                    sha256=state.get("sha256"),
                    size_bytes=state.get("size_bytes"),
                )
            except ValueError:
                continue
            if not any(row["object_key"] == candidate["object_key"] for row in result):
                result.append(candidate)
    elif isinstance(output_ref, Mapping):
        result.append(
            _normalized_ref(
                task=task,
                value=output_ref,
                role="review",
                sha256=output_sha,
                size_bytes=output_size,
            )
        )
    return result


class RemoteMaterialStagingGCReporter:
    """Throttled observer attached to the existing storage Worker heartbeat."""

    def __init__(
        self,
        repository,
        artifacts,
        data_dir: str | Path,
        *,
        interval_seconds: int = 300,
        retention_seconds: int = REMOTE_MATERIAL_STAGING_RETENTION_SECONDS,
    ) -> None:
        from .secrets import KeyringSecretStore, SecretCredentialStore
        from .storage import StorageProviderFactory, StorageSourceRepository

        self.data_dir = Path(data_dir).resolve()
        self.sources = StorageSourceRepository(
            self.data_dir / "storage" / "storage_sources.sqlite3"
        )
        self.credentials = SecretCredentialStore(KeyringSecretStore())
        self.provider_factory = StorageProviderFactory
        self.interval_seconds = max(30, int(interval_seconds))
        self._next_run = 0.0

        def resolver(project_id: str, ref: Mapping[str, Any]):
            source_id = str(ref.get("storage_source_id") or "").strip()
            source = self.sources.get(source_id)
            if source is None or not source.enabled:
                raise RuntimeError(f"storage source unavailable for staging cleanup: {source_id}")
            secret = (
                self.credentials.get(source.secret_ref) or {}
                if source.secret_ref
                else {}
            )
            return self.provider_factory(
                data_dir=self.data_dir,
                project_dir=self.data_dir / "projects" / str(project_id),
                credentials={source.id: secret},
            ).create(source)

        self.lifecycle = RemoteMaterialStagingLifecycle(
            repository,
            artifacts,
            resolver,
            data_dir=self.data_dir,
            retention_seconds=retention_seconds,
        )

    def report(self) -> dict[str, Any]:
        now = time.monotonic()
        if now < self._next_run:
            return {"skipped": True}
        self._next_run = now + self.interval_seconds
        try:
            return self.lifecycle.maintain()
        except Exception as error:
            # Maintenance is observational/background work. Provider or secret
            # outages must not kill the Worker heartbeat/task scheduler.
            return {"error": str(error)[:1000]}


class RemoteMaterialStagingLifecycle:
    """Exact-ref, idempotent cleanup for remote material staging objects."""

    def __init__(
        self,
        repository,
        artifacts,
        provider_resolver: Callable[[str, Mapping[str, Any]], object],
        *,
        data_dir: str | Path | None = None,
        retention_seconds: int = REMOTE_MATERIAL_STAGING_RETENTION_SECONDS,
        scan_limit: int = 100,
    ) -> None:
        self.repository = repository
        self.artifacts = artifacts
        self.provider_resolver = provider_resolver
        self.retention_seconds = max(3600, int(retention_seconds))
        self.scan_limit = max(1, min(100, int(scan_limit)))
        if data_dir is not None:
            base = Path(data_dir)
            self.state_path = base / "task_runtime" / REMOTE_MATERIAL_GC_STATE_REF
        elif repository is not None:
            self.state_path = Path(repository.path).parent / REMOTE_MATERIAL_GC_STATE_REF
        else:
            self.state_path = Path(artifacts.root).parent / REMOTE_MATERIAL_GC_STATE_REF
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def _ledger_path(self, task_id: str) -> Path:
        return self.artifacts.artifact_path(str(task_id), REMOTE_MATERIAL_CLEANUP_REF)

    def _read_ledger(self, task_id: str) -> dict[str, Any]:
        value = self.artifacts.read_json(
            str(task_id), REMOTE_MATERIAL_CLEANUP_REF, default={}
        )
        return dict(value) if isinstance(value, Mapping) else {}

    def _write_ledger(self, task_id: str, value: Mapping[str, Any]) -> None:
        self.artifacts.atomic_write_json(
            str(task_id), REMOTE_MATERIAL_CLEANUP_REF, dict(value)
        )

    @staticmethod
    def _merge_objects(
        existing: list[Mapping[str, Any]],
        discovered: list[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        by_identity: dict[tuple[str, str], dict[str, Any]] = {}
        for item in [*existing, *discovered]:
            if not isinstance(item, Mapping):
                continue
            identity = (
                str(item.get("storage_source_id") or ""),
                str(item.get("object_key") or ""),
            )
            if not all(identity):
                continue
            current = by_identity.get(identity)
            if current is None:
                by_identity[identity] = dict(item)
                continue
            # Preserve terminal cleanup state while refreshing immutable evidence.
            for key in ("role", "sha256", "size_bytes"):
                if item.get(key) not in (None, ""):
                    current[key] = item[key]
        return list(by_identity.values())

    def record_confirmed(
        self,
        task,
        payload: Mapping[str, Any],
        evidence: Mapping[str, Any],
        confirmed: Mapping[str, Any],
        *,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        refs = material_staging_refs(
            task,
            payload,
            confirmed=confirmed,
            evidence=evidence,
            artifacts=self.artifacts,
        )
        current = self._read_ledger(str(task.task_id))
        ledger = {
            "schema_version": 1,
            "task_id": str(task.task_id),
            "project_id": str(task.project_id),
            "reason": "server_confirmed_review",
            "eligible_after": _iso(now),
            "objects": self._merge_objects(
                list(current.get("objects") or []),
                refs,
            ),
            "updated_at": _iso(now),
        }
        self._write_ledger(str(task.task_id), ledger)
        return self.cleanup_task(task, now=now, force=True)

    def _terminal_eligible_after(self, task) -> str:
        finished = getattr(task, "finished_at", None) or getattr(task, "updated_at", None)
        return _iso(_utc(finished) + timedelta(seconds=self.retention_seconds))

    def _build_terminal_ledger(self, task, *, now=None) -> dict[str, Any] | None:
        if self.repository is None:
            return None
        if task.kind is not TaskKind.MATERIAL_IMPORT or task.status not in _TERMINAL:
            return None
        payload = self.artifacts.read_json(
            str(task.task_id), str(task.payload_ref), default={}
        )
        if not isinstance(payload, Mapping):
            return None
        refs = material_staging_refs(
            task,
            payload,
            artifacts=self.artifacts,
        )
        if not refs:
            return None
        current = self._read_ledger(str(task.task_id))
        ledger = {
            "schema_version": 1,
            "task_id": str(task.task_id),
            "project_id": str(task.project_id),
            "reason": str(current.get("reason") or "terminal_retention_expired"),
            "eligible_after": str(
                current.get("eligible_after") or self._terminal_eligible_after(task)
            ),
            "objects": self._merge_objects(
                list(current.get("objects") or []),
                refs,
            ),
            "updated_at": _iso(now),
        }
        self._write_ledger(str(task.task_id), ledger)
        return ledger

    def cleanup_task(
        self,
        task,
        *,
        now: datetime | str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        now_dt = _utc(now)
        lock = FileLock(str(self._ledger_path(str(task.task_id))) + ".lock", timeout=0)
        try:
            lock.acquire()
        except Timeout:
            return {"task_id": str(task.task_id), "status": "BUSY", "deleted": 0}
        try:
            ledger = self._read_ledger(str(task.task_id))
            if not ledger:
                ledger = self._build_terminal_ledger(task, now=now_dt) or {}
            if not ledger:
                return {"task_id": str(task.task_id), "status": "NO_OBJECTS", "deleted": 0}
            eligible_after = _utc(ledger.get("eligible_after") or now_dt)
            if not force and now_dt < eligible_after:
                return {
                    "task_id": str(task.task_id),
                    "status": "RETAINED",
                    "deleted": 0,
                    "eligible_after": eligible_after.isoformat(),
                }
            objects = [dict(row) for row in list(ledger.get("objects") or [])]
            deleted = conflicts = pending = 0
            for item in objects:
                if item.get("status") in {"DELETED", "ABSENT"}:
                    continue
                item["last_attempt_at"] = now_dt.isoformat()
                try:
                    # Re-validate ownership even for a previously written ledger.
                    safe = _normalized_ref(
                        task=task,
                        value=item,
                        role=str(item.get("role") or "staging"),
                        sha256=item.get("sha256"),
                        size_bytes=item.get("size_bytes"),
                    )
                    provider = self.provider_resolver(str(task.project_id), safe)
                    key = safe["object_key"]
                    if not provider.exists(key):
                        item.update(status="ABSENT", last_error="", deleted_at=now_dt.isoformat())
                        deleted += 1
                        continue
                    meta = provider.stat(key)
                    actual_sha = str(getattr(meta, "sha256", "") or "").strip().lower()
                    if (
                        int(getattr(meta, "size_bytes", 0) or 0) != int(safe["size_bytes"])
                        or not actual_sha
                        or actual_sha != safe["sha256"]
                    ):
                        item.update(
                            status="CONFLICT",
                            last_error="object size/SHA256 no longer matches task-owned staging evidence",
                        )
                        conflicts += 1
                        continue
                    provider.delete(key)
                    item.update(status="DELETED", last_error="", deleted_at=now_dt.isoformat())
                    deleted += 1
                except Exception as error:
                    item.update(status="PENDING", last_error=str(error)[:1000])
                    pending += 1
            ledger["objects"] = objects
            ledger["updated_at"] = now_dt.isoformat()
            ledger["complete"] = all(
                row.get("status") in {"DELETED", "ABSENT"} for row in objects
            )
            ledger["conflicts"] = sum(row.get("status") == "CONFLICT" for row in objects)
            ledger["pending"] = sum(row.get("status") == "PENDING" for row in objects)
            self._write_ledger(str(task.task_id), ledger)
            return {
                "task_id": str(task.task_id),
                "status": "COMPLETE" if ledger["complete"] else "INCOMPLETE",
                "deleted": deleted,
                "conflicts": conflicts,
                "pending": pending,
            }
        finally:
            try:
                lock.release()
            except Exception:
                pass

    def _read_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return dict(value) if isinstance(value, Mapping) else {}

    def _write_state(self, value: Mapping[str, Any]) -> None:
        temporary = self.state_path.with_name(f".{self.state_path.name}.tmp")
        temporary.write_text(
            json.dumps(dict(value), ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, self.state_path)

    def maintain(self, *, now: datetime | str | None = None) -> dict[str, Any]:
        if self.repository is None:
            raise RuntimeError("remote material staging maintenance requires TaskRepository")
        now_dt = _utc(now)
        state = self._read_state()
        cursor = state.get("cursor")
        statuses = [TaskStatus.AWAITING_CONFIRMATION, *_TERMINAL]
        page = self.repository.list(
            kinds=(TaskKind.MATERIAL_IMPORT,),
            statuses=statuses,
            limit=self.scan_limit,
            cursor=str(cursor) if cursor else None,
        )
        visited = complete = retained = incomplete = 0
        for task in page.items:
            visited += 1
            ledger = self._read_ledger(str(task.task_id))
            if task.status is TaskStatus.AWAITING_CONFIRMATION:
                # Safe immediate retry only when server-confirm already wrote a
                # cleanup ledger. Never infer early deletion from status alone.
                if not ledger:
                    continue
                outcome = self.cleanup_task(task, now=now_dt)
            else:
                if not ledger:
                    self._build_terminal_ledger(task, now=now_dt)
                outcome = self.cleanup_task(task, now=now_dt)
            status = outcome.get("status")
            complete += int(status == "COMPLETE")
            retained += int(status == "RETAINED")
            incomplete += int(status in {"INCOMPLETE", "BUSY"})
        next_cursor = page.next_cursor
        self._write_state({
            "schema_version": 1,
            "cursor": next_cursor,
            "last_run_at": now_dt.isoformat(),
            "last_visited": visited,
            "last_complete": complete,
            "last_retained": retained,
            "last_incomplete": incomplete,
        })
        return {
            "visited": visited,
            "complete": complete,
            "retained": retained,
            "incomplete": incomplete,
            "next_cursor": next_cursor,
        }


__all__ = [
    "REMOTE_MATERIAL_CLEANUP_REF",
    "REMOTE_MATERIAL_GC_STATE_REF",
    "REMOTE_MATERIAL_STAGING_RETENTION_SECONDS",
    "RemoteMaterialStagingGCReporter",
    "RemoteMaterialStagingLifecycle",
    "material_staging_refs",
]
