"""Lifecycle governance for temporary task-owned remote execution objects.

Only exact remote-execution/{project}/{task}/... references are eligible for
ordinary staging cleanup. Remote-training final-key models are eligible only
from durable task evidence while their deterministic algorithm version is still
unattached. Referenced canonical ModelArtifact objects, shared remote-training
bundles, and formal material object keys are protected.

The historical remote-material ledger/state paths remain unchanged so existing
cleanup journals stay recoverable while this single owner also governs
conversion, training-result, cleaning-result, and provisional training delivery
cleanup.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from filelock import FileLock, Timeout

from .algorithms import list_algorithms
from .model_artifacts import (
    ModelArtifactRepository,
    SUCCESSFUL_CONVERSION_STATUSES,
    build_artifact_object_key,
    model_delivery_version_fence,
)
from .task_runtime import TaskKind, TaskStatus


REMOTE_MATERIAL_CLEANUP_REF = "remote-material/staging-cleanup.json"
REMOTE_MATERIAL_GC_STATE_REF = "remote-material-gc-state.json"
REMOTE_MATERIAL_STAGING_RETENTION_SECONDS = max(
    3600,
    int(os.environ.get("MC_REMOTE_MATERIAL_STAGING_RETENTION_SECONDS", 7 * 24 * 3600)),
)
REMOTE_EXECUTION_CLEANUP_REF = REMOTE_MATERIAL_CLEANUP_REF
REMOTE_EXECUTION_GC_STATE_REF = REMOTE_MATERIAL_GC_STATE_REF
REMOTE_EXECUTION_STAGING_RETENTION_SECONDS = REMOTE_MATERIAL_STAGING_RETENTION_SECONDS
_STAGING_TASK_KINDS = (
    TaskKind.MATERIAL_IMPORT,
    TaskKind.MATERIAL_BATCH,
    TaskKind.MODEL_CONVERSION,
    TaskKind.TRAINING,
    TaskKind.DEPLOYMENT_TEST,
)
_TERMINAL = {
    TaskStatus.SUCCEEDED,
    TaskStatus.PARTIAL_SUCCESS,
    TaskStatus.CANCELLED,
    TaskStatus.FAILED,
    TaskStatus.BLOCKED_BY_ENVIRONMENT,
    TaskStatus.BLOCKED_BY_HARDWARE,
}
_CONVERSION_ORPHAN_TERMINAL = {
    TaskStatus.CANCELLED,
    TaskStatus.FAILED,
    TaskStatus.BLOCKED_BY_ENVIRONMENT,
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


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _append_unique_ref(
    result: list[dict[str, Any]],
    candidate: Mapping[str, Any],
) -> None:
    identity = (
        str(candidate.get("storage_source_id") or ""),
        str(candidate.get("object_key") or ""),
    )
    for existing in result:
        if (
            str(existing.get("storage_source_id") or ""),
            str(existing.get("object_key") or ""),
        ) == identity:
            return
    result.append(dict(candidate))


def remote_execution_staging_refs(
    task,
    payload: Mapping[str, Any],
    *,
    confirmed: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
    artifacts=None,
) -> list[dict[str, Any]]:
    """Return exact task-owned temporary refs; never canonical/shared objects."""
    if task.kind not in _STAGING_TASK_KINDS:
        return []
    remote = payload.get("remote_execution")
    if (
        not isinstance(remote, Mapping)
        or int(remote.get("version") or 0) != 1
        or str(remote.get("task_kind") or "") != task.kind.value
        or str(remote.get("transport") or "") != "object-storage-v1"
    ):
        return []

    result: list[dict[str, Any]] = []
    if task.kind is TaskKind.MATERIAL_IMPORT:
        material = remote.get("material_import")
        if not isinstance(material, Mapping):
            return []
        input_ref = material.get("input")
        if isinstance(input_ref, Mapping):
            _append_unique_ref(
                result,
                _normalized_ref(
                    task=task,
                    value=input_ref,
                    role="input",
                    sha256=input_ref.get("sha256"),
                    size_bytes=input_ref.get("size_bytes"),
                ),
            )
    elif task.kind is TaskKind.DEPLOYMENT_TEST:
        deployment = remote.get("deployment")
        board = deployment.get("board") if isinstance(deployment, Mapping) else None
        if (
            not isinstance(deployment, Mapping)
            or str(deployment.get("runtime_format") or "").strip().lower() != "rknn"
            or not isinstance(board, Mapping)
            or not str(board.get("conversion_job_id") or "").strip()
        ):
            # Generic remote deployment tests may reference canonical ModelArtifact
            # objects outside the task prefix. Keep them outside this board-only
            # GC scope until their own result/local-copy lifecycle is proven.
            return []
        # Board validation stages redundant transport copies of the already-local
        # RKNN artifact plus the one-shot validation image. The result output is
        # different: hardware_verification.result_output_storage is durable
        # report truth, so it must stay outside GC until a canonical copy exists.
        for role, field in (("board-model", "model"), ("board-input", "input")):
            staged = deployment.get(field)
            if not isinstance(staged, Mapping):
                continue
            _append_unique_ref(
                result,
                _normalized_ref(
                    task=task,
                    value=staged,
                    role=role,
                    sha256=staged.get("sha256"),
                    size_bytes=staged.get("size_bytes"),
                ),
            )
        return result
    else:
        section_name = {
            TaskKind.MODEL_CONVERSION: "conversion",
            TaskKind.TRAINING: "training",
            TaskKind.MATERIAL_BATCH: "cleaning",
        }[task.kind]
        if not isinstance(remote.get(section_name), Mapping):
            return []

    # Recover all exact generation uploads so a later successful retry also
    # retires stale output from earlier failed generations.
    if artifacts is not None:
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
                    role=f"result:generation-{generation}",
                    sha256=state.get("sha256"),
                    size_bytes=state.get("size_bytes"),
                )
            except ValueError:
                continue
            _append_unique_ref(result, candidate)

    if isinstance(confirmed, Mapping):
        confirmed_result = confirmed.get("result")
        if isinstance(confirmed_result, Mapping):
            output_ref = confirmed_result.get("output_storage")
            output_sha = confirmed_result.get("output_sha256")
            output_size = confirmed_result.get("output_size_bytes")
            if isinstance(evidence, Mapping):
                output_sha = output_sha or evidence.get("sha256")
                output_size = output_size or evidence.get("size_bytes")
            if isinstance(output_ref, Mapping):
                _append_unique_ref(
                    result,
                    _normalized_ref(
                        task=task,
                        value=output_ref,
                        role=(
                            "review"
                            if task.kind is TaskKind.MATERIAL_IMPORT
                            else "confirmed-result"
                        ),
                        sha256=output_sha,
                        size_bytes=output_size,
                    ),
                )
    return result


def material_staging_refs(
    task,
    payload: Mapping[str, Any],
    *,
    confirmed: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
    artifacts=None,
) -> list[dict[str, Any]]:
    """Compatibility wrapper for the original MATERIAL_IMPORT contract."""
    if task.kind is not TaskKind.MATERIAL_IMPORT:
        return []
    return remote_execution_staging_refs(
        task,
        payload,
        confirmed=confirmed,
        evidence=evidence,
        artifacts=artifacts,
    )


def _conversion_local_artifact_path(
    data_dir: Path,
    *,
    project_id: str,
    task_id: str,
    file_name: str,
) -> Path:
    return (
        data_dir
        / "projects"
        / str(project_id)
        / "deploy"
        / "jobs"
        / str(task_id)
        / "artifacts"
        / Path(str(file_name)).name
    ).resolve()


def remote_conversion_local_orphan_refs(
    task,
    payload: Mapping[str, Any],
    *,
    artifacts,
    data_dir: str | Path,
) -> list[dict[str, Any]]:
    """Recover exact local conversion copies left before durable job finalization."""
    if (
        task.kind is not TaskKind.MODEL_CONVERSION
        or task.status not in _CONVERSION_ORPHAN_TERMINAL
    ):
        return []
    remote = payload.get("remote_execution")
    conversion = remote.get("conversion") if isinstance(remote, Mapping) else None
    source_trace = conversion.get("source_trace") if isinstance(conversion, Mapping) else None
    if (
        not isinstance(conversion, Mapping)
        or int(remote.get("version") or 0) != 1
        or str(remote.get("task_kind") or "") != "MODEL_CONVERSION"
        or str(remote.get("transport") or "") != "object-storage-v1"
        or not isinstance(source_trace, Mapping)
    ):
        return []
    algorithm_id = str(source_trace.get("algorithm_id") or "").strip()
    version_id = str(source_trace.get("version_id") or "").strip()
    target = str(conversion.get("target") or "").strip().lower()
    params = conversion.get("params")
    params = params if isinstance(params, Mapping) else {}
    chip_code = str(params.get("chip") or "").strip().lower() if target == "rockchip" else ""
    if not algorithm_id or not version_id or target not in {"onnx", "rockchip"}:
        return []

    base = Path(data_dir).resolve()
    job_dir = (
        base / "projects" / str(task.project_id) / "deploy" / "jobs" / str(task.task_id)
    ).resolve()
    job_file = job_dir / "job.json"
    if job_file.is_file():
        try:
            job = json.loads(job_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            job = {}
        if (
            isinstance(job, Mapping)
            and str(job.get("status") or "").strip().lower()
            in SUCCESSFUL_CONVERSION_STATUSES
        ):
            # A crash may happen after job.json became durable but before the
            # Task Runtime terminal update. That local artifact is deliverable.
            return []

    expected_suffix = ".onnx" if target == "onnx" else ".rknn"
    result: list[dict[str, Any]] = []
    for generation in range(1, max(0, int(getattr(task, "attempt", 0))) + 1):
        state = artifacts.read_json(
            str(task.task_id),
            f"remote-results/{generation}/upload.json",
            default={},
        )
        if (
            not isinstance(state, Mapping)
            or int(state.get("execution_generation") or 0) != generation
        ):
            continue
        storage_ref = state.get("storage_ref")
        if not isinstance(storage_ref, Mapping):
            continue
        file_name = str(storage_ref.get("file_name") or "").strip()
        digest = str(state.get("sha256") or "").strip().lower()
        try:
            size = int(state.get("size_bytes") or 0)
        except (TypeError, ValueError):
            continue
        if (
            not file_name
            or Path(file_name).name != file_name
            or Path(file_name).suffix.lower() != expected_suffix
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or size <= 0
        ):
            continue
        local_path = _conversion_local_artifact_path(
            base,
            project_id=str(task.project_id),
            task_id=str(task.task_id),
            file_name=file_name,
        )
        artifacts_root = (job_dir / "artifacts").resolve()
        if artifacts_root not in local_path.parents:
            continue
        result.append({
            "scope": "conversion-local-staging",
            "role": f"local-result:generation-{generation}",
            "algorithm_id": algorithm_id,
            "version_id": version_id,
            "conversion_job_id": str(task.task_id),
            "execution_generation": generation,
            "target": target,
            "chip_code": chip_code,
            "file_name": file_name,
            "local_path": str(local_path),
            "sha256": digest,
            "size_bytes": size,
            "status": "PENDING",
            "last_error": "",
            "last_attempt_at": None,
            "deleted_at": None,
        })
    return result


def _training_delivery_version_id(task_id: str, generation: int, snapshot_id: str) -> str:
    return "rt" + hashlib.sha256(
        f"{task_id}:{int(generation)}:{snapshot_id}".encode("utf-8")
    ).hexdigest()[:10]


def _training_delivery_local_path(
    data_dir: Path,
    *,
    project_id: str,
    task_id: str,
    generation: int,
    role: str,
    sha256: str,
    file_name: str,
) -> Path:
    suffix = Path(str(file_name or "model.pt")).suffix.lower() or ".pt"
    return (
        data_dir
        / "projects"
        / str(project_id)
        / "models"
        / (
            f"remote_{_safe_segment(task_id, 'task')}_g{int(generation)}_"
            f"{role}_{sha256[:12]}{suffix}"
        )
    ).resolve()


def _normalize_training_delivery_ref(
    task,
    payload: Mapping[str, Any],
    state: Mapping[str, Any],
    model: Mapping[str, Any],
    *,
    generation: int,
    primary_role: str,
    data_dir: Path,
) -> dict[str, Any]:
    remote = payload.get("remote_execution")
    training = remote.get("training") if isinstance(remote, Mapping) else None
    if (
        task.kind is not TaskKind.TRAINING
        or not isinstance(training, Mapping)
        or int(remote.get("version") or 0) != 1
        or str(remote.get("task_kind") or "") != "TRAINING"
        or str(remote.get("transport") or "") != "object-storage-v1"
    ):
        raise ValueError("training delivery cleanup requires the portable training contract")
    algorithm_id = str(payload.get("algorithm_asset_id") or "").strip()
    snapshot_id = str(training.get("snapshot_id") or "").strip()
    version_id = str(state.get("version_id") or "").strip()
    expected_version_id = _training_delivery_version_id(
        str(task.task_id), generation, snapshot_id,
    )
    role = str(model.get("role") or "").strip().lower()
    digest = str(model.get("sha256") or "").strip().lower()
    file_name = str(model.get("file_name") or "").strip()
    storage_ref = model.get("storage_ref")
    try:
        size = int(model.get("size_bytes") or 0)
    except (TypeError, ValueError) as error:
        raise ValueError("training delivery size evidence is invalid") from error
    if (
        not algorithm_id
        or not snapshot_id
        or version_id != expected_version_id
        or role not in {"best", "last"}
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
        or size <= 0
        or not file_name
        or Path(file_name).name != file_name
        or Path(file_name).suffix.lower() != ".pt"
        or not isinstance(storage_ref, Mapping)
    ):
        raise ValueError("training delivery identity evidence is invalid")
    source_id = str(storage_ref.get("storage_source_id") or "").strip()
    object_key = str(storage_ref.get("object_key") or "").strip().replace("\\", "/")
    path = PurePosixPath(object_key)
    canonical = build_artifact_object_key(
        root_prefix="gc-root",
        project_id=str(task.project_id),
        algorithm_id=algorithm_id,
        version_id=version_id,
        target="training",
        sha256=digest,
        file_name=file_name,
    )
    canonical_suffix = canonical.split("/", 1)[1]
    expected_prepare_id = hashlib.sha256(
        f"{task.project_id}:{algorithm_id}:{version_id}:{role}:{digest}".encode("utf-8")
    ).hexdigest()[:32]
    if (
        not source_id
        or not object_key
        or path.is_absolute()
        or ".." in path.parts
        or not object_key.endswith("/" + canonical_suffix)
        or str(model.get("artifact_id") or "").strip() != expected_prepare_id
    ):
        raise ValueError("training delivery object is not the deterministic task artifact")
    local_path = ""
    if role == primary_role:
        local_path = str(
            _training_delivery_local_path(
                data_dir,
                project_id=str(task.project_id),
                task_id=str(task.task_id),
                generation=generation,
                role=role,
                sha256=digest,
                file_name=file_name,
            )
        )
    return {
        "scope": "provisional-training-delivery",
        "role": role,
        "algorithm_id": algorithm_id,
        "version_id": version_id,
        "execution_generation": int(generation),
        "artifact_id": expected_prepare_id,
        "file_name": file_name,
        "storage_source_id": source_id,
        "object_key": object_key,
        "sha256": digest,
        "size_bytes": size,
        "local_path": local_path,
        "status": "PENDING",
        "last_error": "",
        "last_attempt_at": None,
        "deleted_at": None,
    }


def remote_training_delivery_orphan_refs(
    task,
    payload: Mapping[str, Any],
    *,
    artifacts,
    data_dir: str | Path,
) -> list[dict[str, Any]]:
    """Recover exact final-key model uploads that never became an algorithm version."""
    if task.kind is not TaskKind.TRAINING:
        return []
    base = Path(data_dir).resolve()
    result: list[dict[str, Any]] = []
    for generation in range(1, max(0, int(getattr(task, "attempt", 0))) + 1):
        state = artifacts.read_json(
            str(task.task_id),
            f"remote-results/{generation}/training-models.json",
            default={},
        )
        if (
            not isinstance(state, Mapping)
            or int(state.get("execution_generation") or 0) != generation
            or not str(state.get("version_id") or "").strip()
            or not isinstance(state.get("models"), list)
        ):
            continue
        models = [item for item in state.get("models") or [] if isinstance(item, Mapping)]
        roles = [str(item.get("role") or "").strip().lower() for item in models]
        if not models or len(set(roles)) != len(roles) or not set(roles).issubset({"best", "last"}):
            continue
        primary_role = "best" if "best" in roles else "last"
        generation_refs: list[dict[str, Any]] = []
        try:
            for model in models:
                generation_refs.append(
                    _normalize_training_delivery_ref(
                        task,
                        payload,
                        state,
                        model,
                        generation=generation,
                        primary_role=primary_role,
                        data_dir=base,
                    )
                )
        except Exception:
            # Malformed legacy evidence is fail-safe: skip this generation
            # without blocking cleanup of unrelated terminal tasks.
            continue
        result.extend(generation_refs)
    return result


class RemoteExecutionStagingGCReporter:
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

        self.lifecycle = RemoteExecutionStagingLifecycle(
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


class RemoteExecutionStagingLifecycle:
    """Exact-ref, idempotent cleanup for task-owned remote execution staging."""

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
        self.data_dir = Path(data_dir).resolve() if data_dir is not None else None
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
        by_identity: dict[tuple[str, ...], dict[str, Any]] = {}
        for item in [*existing, *discovered]:
            if not isinstance(item, Mapping):
                continue
            if str(item.get("scope") or "") == "conversion-local-staging":
                identity = (
                    "local",
                    str(item.get("local_path") or ""),
                    str(item.get("sha256") or ""),
                )
            else:
                identity = (
                    "remote",
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
            for key in (
                "scope", "role", "sha256", "size_bytes", "algorithm_id",
                "version_id", "execution_generation", "artifact_id",
                "file_name", "local_path", "conversion_job_id",
                "target", "chip_code",
            ):
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
        cleanup_now: bool = False,
    ) -> dict[str, Any]:
        refs = remote_execution_staging_refs(
            task,
            payload,
            confirmed=confirmed,
            evidence=evidence,
            artifacts=self.artifacts,
        )
        if not refs:
            return {
                "task_id": str(task.task_id),
                "status": "NO_OBJECTS",
                "deleted": 0,
            }
        current = self._read_ledger(str(task.task_id))
        ledger = {
            "schema_version": 1,
            "task_id": str(task.task_id),
            "project_id": str(task.project_id),
            "reason": "server_confirmed_remote_result",
            "eligible_after": _iso(now),
            "objects": self._merge_objects(
                list(current.get("objects") or []),
                refs,
            ),
            "updated_at": _iso(now),
        }
        self._write_ledger(str(task.task_id), ledger)
        if cleanup_now:
            return self.cleanup_task(task, now=now, force=True)
        return {
            "task_id": str(task.task_id),
            "status": "RECORDED",
            "deleted": 0,
            "eligible_after": ledger["eligible_after"],
        }

    def _terminal_eligible_after(self, task) -> str:
        finished = getattr(task, "finished_at", None) or getattr(task, "updated_at", None)
        return _iso(_utc(finished) + timedelta(seconds=self.retention_seconds))

    def _build_terminal_ledger(self, task, *, now=None) -> dict[str, Any] | None:
        if self.repository is None:
            return None
        if task.kind not in _STAGING_TASK_KINDS or task.status not in _TERMINAL:
            return None
        payload = self.artifacts.read_json(
            str(task.task_id), str(task.payload_ref), default={}
        )
        if not isinstance(payload, Mapping):
            return None
        refs = remote_execution_staging_refs(
            task,
            payload,
            artifacts=self.artifacts,
        )
        if task.kind is TaskKind.TRAINING and self.data_dir is not None:
            refs.extend(
                remote_training_delivery_orphan_refs(
                    task,
                    payload,
                    artifacts=self.artifacts,
                    data_dir=self.data_dir,
                )
            )
        if task.kind is TaskKind.MODEL_CONVERSION and self.data_dir is not None:
            refs.extend(
                remote_conversion_local_orphan_refs(
                    task,
                    payload,
                    artifacts=self.artifacts,
                    data_dir=self.data_dir,
                )
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

    def _algorithm_version_exists(
        self,
        project_id: str,
        algorithm_id: str,
        version_id: str,
    ) -> bool:
        if self.data_dir is None:
            raise RuntimeError("training delivery cleanup requires data_dir")
        algorithms = list_algorithms(
            self.data_dir / "projects" / str(project_id) / "algorithms.json"
        )
        algorithm = next(
            (
                row for row in algorithms
                if str(row.get("id") or "") == str(algorithm_id)
            ),
            None,
        )
        if algorithm is None:
            return False
        # Provisional remote-training delivery identity is generation-scoped:
        # _normalize_training_delivery_ref() already proves version_id equals
        # hash(task_id, generation, snapshot_id). A later retry generation may
        # legitimately attach another version with the same durable task_id.
        # Protect only the exact deterministic version or older generation
        # artifacts become permanent false-positive references.
        return any(
            isinstance(row, Mapping)
            and str(row.get("id") or "") == str(version_id)
            for row in (algorithm.get("versions") or [])
        )

    def _cleanup_training_delivery_group(
        self,
        task,
        payload: Mapping[str, Any],
        objects: list[dict[str, Any]],
        indices: list[int],
        now_dt: datetime,
    ) -> dict[str, int]:
        if self.data_dir is None:
            for index in indices:
                objects[index].update(
                    status="PENDING",
                    last_error="training delivery cleanup requires data_dir",
                    last_attempt_at=now_dt.isoformat(),
                )
            return {"deleted": 0, "conflicts": 0, "pending": len(indices)}
        sample = objects[indices[0]]
        algorithm_id = str(sample.get("algorithm_id") or "")
        version_id = str(sample.get("version_id") or "")
        try:
            with model_delivery_version_fence(
                self.data_dir,
                str(task.project_id),
                algorithm_id,
                version_id,
            ):
                if self._algorithm_version_exists(
                    str(task.project_id),
                    algorithm_id,
                    version_id,
                ):
                    for index in indices:
                        objects[index].update(
                            status="PROTECTED",
                            last_error="",
                            last_attempt_at=now_dt.isoformat(),
                        )
                    return {"deleted": 0, "conflicts": 0, "pending": 0}

                primary_roles = {
                    str(objects[index].get("role") or "")
                    for index in indices
                    if str(objects[index].get("local_path") or "")
                }
                if len(primary_roles) > 1:
                    raise ValueError("training delivery has multiple local primary models")
                primary_role = next(iter(primary_roles), "")
                validated: list[tuple[int, dict[str, Any]]] = []
                for index in indices:
                    item = objects[index]
                    safe = _normalize_training_delivery_ref(
                        task,
                        payload,
                        {"version_id": str(item.get("version_id") or "")},
                        {
                            "role": item.get("role"),
                            "file_name": item.get("file_name"),
                            "sha256": item.get("sha256"),
                            "size_bytes": item.get("size_bytes"),
                            "artifact_id": item.get("artifact_id"),
                            "storage_ref": {
                                "storage_source_id": item.get("storage_source_id"),
                                "object_key": item.get("object_key"),
                            },
                        },
                        generation=int(item.get("execution_generation") or 0),
                        primary_role=primary_role,
                        data_dir=self.data_dir,
                    )
                    if str(item.get("local_path") or "") != str(safe.get("local_path") or ""):
                        raise ValueError("training delivery local path evidence changed")
                    validated.append((index, safe))

                expected = {
                    (str(safe["role"]), str(safe["sha256"])): safe
                    for _, safe in validated
                }
                artifact_repository = ModelArtifactRepository(self.data_dir)
                rows = artifact_repository.list(
                    project_id=str(task.project_id),
                    algorithm_id=algorithm_id,
                    version_id=version_id,
                    limit=100,
                )
                for row in rows:
                    metadata = row.get("metadata")
                    safe = expected.get((
                        str(row.get("target") or "").strip().lower(),
                        str(row.get("sha256") or "").strip().lower(),
                    ))
                    if (
                        safe is None
                        or not isinstance(metadata, Mapping)
                        or metadata.get("remote_training") is not True
                        or str(metadata.get("task_id") or "") != str(task.task_id)
                        or int(row.get("size_bytes") or 0) != int(safe["size_bytes"])
                        or str(row.get("storage_source_id") or "") not in {
                            "", str(safe["storage_source_id"]),
                        }
                        or str(row.get("object_key") or "") not in {
                            "", str(safe["object_key"]),
                        }
                    ):
                        raise ValueError(
                            "canonical ModelArtifact row is not owned by this provisional training delivery"
                        )

                providers: dict[int, object] = {}
                existing_remote: set[int] = set()
                for index, safe in validated:
                    item = objects[index]
                    item["last_attempt_at"] = now_dt.isoformat()
                    if item.get("status") in {"DELETED", "ABSENT"}:
                        continue
                    provider = self.provider_resolver(str(task.project_id), safe)
                    providers[index] = provider
                    key = str(safe["object_key"])
                    if not provider.exists(key):
                        item.update(
                            status="ABSENT",
                            last_error="",
                            deleted_at=now_dt.isoformat(),
                        )
                        continue
                    meta = provider.stat(key)
                    actual_sha = str(getattr(meta, "sha256", "") or "").strip().lower()
                    if (
                        int(getattr(meta, "size_bytes", 0) or 0) != int(safe["size_bytes"])
                        or not actual_sha
                        or actual_sha != str(safe["sha256"])
                    ):
                        raise ValueError(
                            "provisional training model size/SHA256 no longer matches durable evidence"
                        )
                    existing_remote.add(index)

                for _index, safe in validated:
                    local_path = str(safe.get("local_path") or "")
                    if not local_path:
                        continue
                    candidate = Path(local_path)
                    if candidate.exists() and (
                        not candidate.is_file()
                        or int(candidate.stat().st_size) != int(safe["size_bytes"])
                        or _sha256_path(candidate) != str(safe["sha256"])
                    ):
                        raise ValueError(
                            "provisional local training model no longer matches durable evidence"
                        )

                deleted = 0
                for index, safe in validated:
                    if index not in existing_remote:
                        continue
                    try:
                        providers[index].delete(str(safe["object_key"]))
                        objects[index].update(
                            status="DELETED",
                            last_error="",
                            deleted_at=now_dt.isoformat(),
                        )
                        deleted += 1
                    except Exception as error:
                        objects[index].update(status="PENDING", last_error=str(error)[:1000])
                        return {"deleted": deleted, "conflicts": 0, "pending": 1}

                for index, safe in validated:
                    local_path = str(safe.get("local_path") or "")
                    if not local_path:
                        continue
                    candidate = Path(local_path)
                    if candidate.exists():
                        try:
                            candidate.unlink()
                        except OSError as error:
                            objects[index].update(
                                status="PENDING",
                                last_error=str(error)[:1000],
                            )
                            return {"deleted": deleted, "conflicts": 0, "pending": 1}

                try:
                    artifact_repository.delete_version(
                        str(task.project_id), algorithm_id, version_id,
                    )
                except Exception as error:
                    for index, _safe in validated:
                        objects[index].update(
                            status="PENDING",
                            last_error=str(error)[:1000],
                        )
                    return {"deleted": deleted, "conflicts": 0, "pending": 1}
                return {"deleted": deleted, "conflicts": 0, "pending": 0}
        except ValueError as error:
            for index in indices:
                objects[index].update(
                    status="CONFLICT",
                    last_error=str(error)[:1000],
                    last_attempt_at=now_dt.isoformat(),
                )
            return {"deleted": 0, "conflicts": len(indices), "pending": 0}
        except Exception as error:
            for index in indices:
                objects[index].update(
                    status="PENDING",
                    last_error=str(error)[:1000],
                    last_attempt_at=now_dt.isoformat(),
                )
            return {"deleted": 0, "conflicts": 0, "pending": len(indices)}

    def _cleanup_conversion_local_group(
        self,
        task,
        payload: Mapping[str, Any],
        objects: list[dict[str, Any]],
        indices: list[int],
        now_dt: datetime,
    ) -> dict[str, int]:
        if self.data_dir is None:
            for index in indices:
                objects[index].update(
                    status="PENDING",
                    last_error="conversion local cleanup requires data_dir",
                    last_attempt_at=now_dt.isoformat(),
                )
            return {"deleted": 0, "conflicts": 0, "pending": len(indices)}

        # A retry can move the durable task to a deliverable terminal state
        # after an earlier failure ledger was created. Never delete in that case.
        if task.status not in _CONVERSION_ORPHAN_TERMINAL:
            for index in indices:
                objects[index].update(
                    status="PROTECTED",
                    last_error="",
                    last_attempt_at=now_dt.isoformat(),
                )
            return {"deleted": 0, "conflicts": 0, "pending": 0}

        sample = objects[indices[0]]
        local_path = Path(str(sample.get("local_path") or "")).resolve()
        project_id = str(task.project_id)
        task_id = str(task.task_id)
        expected_root = (
            self.data_dir / "projects" / project_id
            / "deploy" / "jobs" / task_id / "artifacts"
        ).resolve()
        if expected_root not in local_path.parents:
            for index in indices:
                objects[index].update(
                    status="CONFLICT",
                    last_error="conversion local staging path escaped task artifact root",
                    last_attempt_at=now_dt.isoformat(),
                )
            return {"deleted": 0, "conflicts": len(indices), "pending": 0}

        job_file = expected_root.parent / "job.json"
        if job_file.is_file():
            try:
                job = json.loads(job_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                job = {}
            if (
                isinstance(job, Mapping)
                and str(job.get("status") or "").strip().lower()
                in SUCCESSFUL_CONVERSION_STATUSES
            ):
                for index in indices:
                    objects[index].update(
                        status="PROTECTED",
                        last_error="",
                        last_attempt_at=now_dt.isoformat(),
                    )
                return {"deleted": 0, "conflicts": 0, "pending": 0}

        artifact_repository = ModelArtifactRepository(self.data_dir)
        if artifact_repository.list_by_conversion_job(project_id, task_id):
            for index in indices:
                objects[index].update(
                    status="PROTECTED",
                    last_error="",
                    last_attempt_at=now_dt.isoformat(),
                )
            return {"deleted": 0, "conflicts": 0, "pending": 0}

        if not local_path.exists():
            for index in indices:
                objects[index].update(
                    status="ABSENT",
                    last_error="",
                    deleted_at=now_dt.isoformat(),
                    last_attempt_at=now_dt.isoformat(),
                )
            return {"deleted": 0, "conflicts": 0, "pending": 0}
        if local_path.is_symlink() or not local_path.is_file():
            for index in indices:
                objects[index].update(
                    status="CONFLICT",
                    last_error="conversion local staging is not a regular task-owned file",
                    last_attempt_at=now_dt.isoformat(),
                )
            return {"deleted": 0, "conflicts": len(indices), "pending": 0}

        actual_size = int(local_path.stat().st_size)
        actual_sha = _sha256_path(local_path)
        matching = [
            index for index in indices
            if int(objects[index].get("size_bytes") or 0) == actual_size
            and str(objects[index].get("sha256") or "").strip().lower() == actual_sha
        ]
        if not matching:
            for index in indices:
                objects[index].update(
                    status="CONFLICT",
                    last_error="conversion local staging size/SHA256 does not match durable generation evidence",
                    last_attempt_at=now_dt.isoformat(),
                )
            return {"deleted": 0, "conflicts": len(indices), "pending": 0}

        for index in matching:
            item = objects[index]
            canonical = artifact_repository.find_identity(
                project_id,
                str(item.get("algorithm_id") or ""),
                str(item.get("version_id") or ""),
                str(item.get("target") or ""),
                str(item.get("chip_code") or ""),
                actual_sha,
            )
            if canonical is not None:
                for protected_index in indices:
                    objects[protected_index].update(
                        status="PROTECTED",
                        last_error="",
                        last_attempt_at=now_dt.isoformat(),
                    )
                return {"deleted": 0, "conflicts": 0, "pending": 0}

        try:
            local_path.unlink()
        except OSError as error:
            for index in indices:
                objects[index].update(
                    status="PENDING",
                    last_error=str(error)[:1000],
                    last_attempt_at=now_dt.isoformat(),
                )
            return {"deleted": 0, "conflicts": 0, "pending": len(indices)}

        for index in indices:
            objects[index].update(
                status="DELETED" if index in matching else "ABSENT",
                last_error="",
                deleted_at=now_dt.isoformat(),
                last_attempt_at=now_dt.isoformat(),
            )
        return {"deleted": 1, "conflicts": 0, "pending": 0}

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
            payload = self.artifacts.read_json(
                str(task.task_id), str(task.payload_ref), default={}
            )
            payload = payload if isinstance(payload, Mapping) else {}
            conversion_local_groups: dict[str, list[int]] = {}
            training_groups: dict[tuple[str, str], list[int]] = {}
            for index, item in enumerate(objects):
                scope = str(item.get("scope") or "")
                if scope == "conversion-local-staging":
                    conversion_local_groups.setdefault(
                        str(item.get("local_path") or ""), []
                    ).append(index)
                    continue
                if scope != "provisional-training-delivery":
                    continue
                training_groups.setdefault((
                    str(item.get("algorithm_id") or ""),
                    str(item.get("version_id") or ""),
                ), []).append(index)
            for indices in conversion_local_groups.values():
                outcome = self._cleanup_conversion_local_group(
                    task, payload, objects, indices, now_dt,
                )
                deleted += int(outcome.get("deleted") or 0)
                conflicts += int(outcome.get("conflicts") or 0)
                pending += int(outcome.get("pending") or 0)
            for indices in training_groups.values():
                outcome = self._cleanup_training_delivery_group(
                    task, payload, objects, indices, now_dt,
                )
                deleted += int(outcome.get("deleted") or 0)
                conflicts += int(outcome.get("conflicts") or 0)
                pending += int(outcome.get("pending") or 0)

            for item in objects:
                if str(item.get("scope") or "") in {
                    "provisional-training-delivery",
                    "conversion-local-staging",
                }:
                    continue
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
                row.get("status") in {"DELETED", "ABSENT", "PROTECTED"}
                for row in objects
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
            raise RuntimeError("remote execution staging maintenance requires TaskRepository")
        now_dt = _utc(now)
        state = self._read_state()
        cursor = state.get("cursor")
        statuses = [TaskStatus.AWAITING_CONFIRMATION, *_TERMINAL]
        page = self.repository.list(
            kinds=_STAGING_TASK_KINDS,
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


# Compatibility aliases: there is still exactly one lifecycle/reporter owner.
RemoteMaterialStagingGCReporter = RemoteExecutionStagingGCReporter
RemoteMaterialStagingLifecycle = RemoteExecutionStagingLifecycle

__all__ = [
    "REMOTE_EXECUTION_CLEANUP_REF",
    "REMOTE_EXECUTION_GC_STATE_REF",
    "REMOTE_EXECUTION_STAGING_RETENTION_SECONDS",
    "REMOTE_MATERIAL_CLEANUP_REF",
    "REMOTE_MATERIAL_GC_STATE_REF",
    "REMOTE_MATERIAL_STAGING_RETENTION_SECONDS",
    "RemoteExecutionStagingGCReporter",
    "RemoteExecutionStagingLifecycle",
    "RemoteMaterialStagingGCReporter",
    "RemoteMaterialStagingLifecycle",
    "material_staging_refs",
    "remote_conversion_local_orphan_refs",
    "remote_execution_staging_refs",
    "remote_training_delivery_orphan_refs",
]
