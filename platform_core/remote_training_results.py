"""Portable generation-scoped result bundle for remote TRAINING executions."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


TRAINING_RESULT_SCHEMA_VERSION = 1
TRAINING_RESULT_MAX_MEMBERS = 128
TRAINING_RESULT_MAX_UNCOMPRESSED_BYTES = 16 * 1024 * 1024 * 1024
SUCCESSFUL_TRAINING_OUTCOMES = frozenset({
    "completed",
    "target_reached",
    "early_stopping",
    "needs_optimization",
})


class RemoteTrainingResultError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409):
        self.code = str(code)
        self.status_code = int(status_code)
        super().__init__(str(message))


@dataclass(frozen=True)
class TrainingResultArchive:
    path: Path
    sha256: str
    size_bytes: int
    uncompressed_size_bytes: int
    member_count: int
    task_id: str
    execution_generation: int
    snapshot_id: str
    models: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class VerifiedTrainingResult:
    root: Path
    manifest: dict[str, Any]
    models: tuple[dict[str, Any], ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member_name(value: object) -> str:
    raw = str(value or "")
    if not raw or "\\" in raw or "\x00" in raw:
        raise RemoteTrainingResultError(
            "TRAINING_RESULT_ARCHIVE_UNSAFE",
            "training result archive contains an unsafe member name",
            422,
        )
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise RemoteTrainingResultError(
            "TRAINING_RESULT_ARCHIVE_UNSAFE",
            "training result archive member escapes the result root",
            422,
        )
    normalized = path.as_posix().strip("/")
    if not normalized:
        raise RemoteTrainingResultError(
            "TRAINING_RESULT_ARCHIVE_UNSAFE",
            "training result archive contains an empty member name",
            422,
        )
    return normalized


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (int(info.external_attr) >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _sanitize_json(value: object, *, depth: int = 0) -> Any:
    if depth > 8:
        raise RemoteTrainingResultError(
            "TRAINING_RESULT_METADATA_INVALID",
            "training result metadata nesting is too deep",
            422,
        )
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and len(value) > 100_000:
            raise RemoteTrainingResultError(
                "TRAINING_RESULT_METADATA_INVALID",
                "training result metadata string is too large",
                422,
            )
        return value
    if isinstance(value, Mapping):
        if len(value) > 1000:
            raise RemoteTrainingResultError(
                "TRAINING_RESULT_METADATA_INVALID",
                "training result metadata object is too large",
                422,
            )
        return {
            str(key)[:200]: _sanitize_json(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        if len(value) > 10_000:
            raise RemoteTrainingResultError(
                "TRAINING_RESULT_METADATA_INVALID",
                "training result metadata list is too large",
                422,
            )
        return [_sanitize_json(item, depth=depth + 1) for item in value]
    return str(value)[:2000]


def _verified_model_paths(
    job: Mapping[str, Any],
    *,
    models_root: Path,
) -> list[tuple[str, Path]]:
    if str(job.get("status") or "").strip().lower() != "done":
        raise RemoteTrainingResultError(
            "TRAINING_RESULT_JOB_INCOMPLETE",
            "training job did not finish successfully",
            409,
        )
    if job.get("artifact_verified") is not True:
        raise RemoteTrainingResultError(
            "TRAINING_RESULT_ARTIFACT_UNVERIFIED",
            "training job did not verify its model artifacts",
            409,
        )
    outcome = str(job.get("training_outcome") or "").strip().lower()
    if outcome not in SUCCESSFUL_TRAINING_OUTCOMES:
        raise RemoteTrainingResultError(
            "TRAINING_RESULT_OUTCOME_INVALID",
            f"training outcome is not publishable: {outcome or '<missing>'}",
            409,
        )

    verified = []
    for raw in job.get("verified_models") or ():
        if isinstance(raw, Mapping):
            raw = raw.get("path") or raw.get("stored_path") or raw.get("source")
        text = str(raw or "").strip()
        if not text:
            continue
        path = Path(text).expanduser().resolve()
        try:
            path.relative_to(models_root)
        except ValueError as error:
            raise RemoteTrainingResultError(
                "TRAINING_RESULT_MODEL_OUTSIDE_WORKSPACE",
                "verified training model is outside the Agent task workspace",
                409,
            ) from error
        if not path.is_file() or path.stat().st_size <= 0:
            raise RemoteTrainingResultError(
                "TRAINING_RESULT_MODEL_MISSING",
                "verified training model is missing or empty",
                409,
            )
        verified.append(path)
    if not verified:
        raise RemoteTrainingResultError(
            "TRAINING_RESULT_MODEL_MISSING",
            "training job has no verified model",
            409,
        )

    best = str(job.get("best_path") or "").strip()
    last = str(job.get("last_path") or "").strip()
    best_path = Path(best).expanduser().resolve() if best else None
    last_path = Path(last).expanduser().resolve() if last else None
    roles: list[tuple[str, Path]] = []
    seen: set[tuple[str, str]] = set()
    for path in verified:
        role = "model"
        if best_path is not None and path == best_path:
            role = "best"
        elif last_path is not None and path == last_path:
            role = "last"
        identity = (role, str(path))
        if identity not in seen:
            roles.append((role, path))
            seen.add(identity)
    if not any(role in {"best", "last"} for role, _path in roles):
        raise RemoteTrainingResultError(
            "TRAINING_RESULT_PRIMARY_MODEL_MISSING",
            "verified training result has no best/last model",
            409,
        )
    return roles


def create_training_result_archive(
    *,
    project_dir: str | Path,
    job: Mapping[str, Any],
    task_id: str,
    execution_generation: int,
    snapshot_id: str,
    destination: str | Path,
    include_model_bytes: bool = True,
) -> TrainingResultArchive:
    project = Path(project_dir).expanduser().resolve()
    models_root = (project / "models").resolve()
    models_root.mkdir(parents=True, exist_ok=True)
    model_paths = _verified_model_paths(job, models_root=models_root)

    task_value = str(task_id or "").strip()
    snapshot_value = str(snapshot_id or "").strip()
    generation = int(execution_generation)
    if not task_value or not snapshot_value or generation <= 0:
        raise RemoteTrainingResultError(
            "TRAINING_RESULT_IDENTITY_INVALID",
            "training result task/generation/snapshot identity is incomplete",
            422,
        )

    models: list[dict[str, Any]] = []
    archive_members: list[tuple[str, Path]] = []
    used_names: set[str] = set()
    for index, (role, path) in enumerate(model_paths, start=1):
        digest = _sha256(path)
        suffix = path.suffix.lower() or ".pt"
        base = f"{role}-{digest[:16]}{suffix}"
        name = base
        counter = 1
        while name in used_names:
            counter += 1
            name = f"{role}-{digest[:16]}-{counter}{suffix}"
        used_names.add(name)
        ref = f"models/{name}"
        models.append({
            "role": role,
            "ref": ref,
            "file_name": name,
            "sha256": digest,
            "size_bytes": int(path.stat().st_size),
        })
        if include_model_bytes:
            archive_members.append((ref, path))

    training_report = _sanitize_json(job.get("training_report") or {})
    completion = {
        key: _sanitize_json(job.get(key))
        for key in (
            "training_outcome",
            "completion_reason",
            "early_stopping_reason",
            "early_stopping_patience",
            "best_epoch",
            "completed_epochs",
            "requested_epochs",
            "runtime_stop_policy",
            "quality_gate",
            "actual_device",
            "assigned_device",
            "requested_device",
            "actual_train_params",
            "device_evidence",
            "device_validation",
            "finished_at",
        )
        if job.get(key) is not None
    }
    manifest = {
        "schema_version": TRAINING_RESULT_SCHEMA_VERSION,
        "task_id": task_value,
        "execution_generation": generation,
        "snapshot_id": snapshot_value,
        "framework": "ultralytics",
        "artifact_verified": True,
        "training_outcome": str(job.get("training_outcome") or ""),
        "model_transport": "embedded-v1" if include_model_bytes else "separate-object-v1",
        "completion": completion,
        "training_report": training_report,
        "models": models,
    }
    manifest_bytes = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    total_uncompressed = len(manifest_bytes) + (
        sum(int(item["size_bytes"]) for item in models)
        if include_model_bytes
        else 0
    )
    member_count = 1 + (len(models) if include_model_bytes else 0)
    if (
        member_count > TRAINING_RESULT_MAX_MEMBERS
        or total_uncompressed > TRAINING_RESULT_MAX_UNCOMPRESSED_BYTES
    ):
        raise RemoteTrainingResultError(
            "TRAINING_RESULT_ARCHIVE_TOO_LARGE",
            "training result archive exceeds supported limits",
            413,
        )

    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_STORED,
            allowZip64=True,
        ) as archive:
            archive.writestr("manifest.json", manifest_bytes)
            for ref, path in archive_members:
                archive.write(path, arcname=_safe_member_name(ref))
        if temporary.stat().st_size <= 0:
            raise RemoteTrainingResultError(
                "TRAINING_RESULT_ARCHIVE_EMPTY",
                "training result archive is empty",
                409,
            )
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)

    return TrainingResultArchive(
        path=target,
        sha256=_sha256(target),
        size_bytes=int(target.stat().st_size),
        uncompressed_size_bytes=total_uncompressed,
        member_count=member_count,
        task_id=task_value,
        execution_generation=generation,
        snapshot_id=snapshot_value,
        models=tuple(dict(item) for item in models),
    )


def verify_training_result_archive(
    archive: str | Path,
    destination: str | Path,
    *,
    expected_sha256: str,
    expected_size_bytes: int,
    expected_task_id: str,
    expected_execution_generation: int,
    expected_snapshot_id: str,
    allow_separate_model_objects: bool = False,
) -> VerifiedTrainingResult:
    source = Path(archive).expanduser().resolve()
    digest = str(expected_sha256 or "").strip().lower()
    size = int(expected_size_bytes)
    if (
        len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
        or size <= 0
        or not source.is_file()
        or int(source.stat().st_size) != size
        or _sha256(source) != digest
    ):
        raise RemoteTrainingResultError(
            "TRAINING_RESULT_ARCHIVE_EVIDENCE_MISMATCH",
            "training result archive does not match generation evidence",
            409,
        )

    target = Path(destination).expanduser().resolve()
    if target.exists() or target.is_symlink():
        shutil.rmtree(target, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(
        dir=target.parent,
        prefix=f".{target.name}.extract.",
    )).resolve()
    try:
        seen: set[str] = set()
        total = 0
        files = 0
        with zipfile.ZipFile(source, "r") as archive_file:
            infos = archive_file.infolist()
            if not infos or len(infos) > TRAINING_RESULT_MAX_MEMBERS:
                raise RemoteTrainingResultError(
                    "TRAINING_RESULT_MEMBER_COUNT_INVALID",
                    "training result archive member count is invalid",
                    422,
                )
            for info in infos:
                name = _safe_member_name(info.filename)
                if name in seen:
                    raise RemoteTrainingResultError(
                        "TRAINING_RESULT_DUPLICATE_MEMBER",
                        "training result archive contains duplicate members",
                        422,
                    )
                seen.add(name)
                if _is_zip_symlink(info):
                    raise RemoteTrainingResultError(
                        "TRAINING_RESULT_LINK_FORBIDDEN",
                        "training result archive contains a symbolic link",
                        422,
                    )
                if info.is_dir():
                    continue
                files += 1
                total += int(info.file_size)
                if total > TRAINING_RESULT_MAX_UNCOMPRESSED_BYTES:
                    raise RemoteTrainingResultError(
                        "TRAINING_RESULT_ARCHIVE_TOO_LARGE",
                        "training result archive expands beyond supported limits",
                        413,
                    )
                output = (temporary / Path(*PurePosixPath(name).parts)).resolve()
                if temporary not in output.parents:
                    raise RemoteTrainingResultError(
                        "TRAINING_RESULT_ARCHIVE_UNSAFE",
                        "training result archive escaped extraction root",
                        422,
                    )
                output.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with archive_file.open(info, "r") as input_stream, output.open("xb") as output_stream:
                    for chunk in iter(lambda: input_stream.read(1024 * 1024), b""):
                        written += len(chunk)
                        if total - int(info.file_size) + written > TRAINING_RESULT_MAX_UNCOMPRESSED_BYTES:
                            raise RemoteTrainingResultError(
                                "TRAINING_RESULT_ARCHIVE_TOO_LARGE",
                                "training result archive expanded beyond supported limits",
                                413,
                            )
                        output_stream.write(chunk)
                if written != int(info.file_size):
                    raise RemoteTrainingResultError(
                        "TRAINING_RESULT_MEMBER_SIZE_MISMATCH",
                        "training result member size does not match ZIP metadata",
                        409,
                    )
        manifest_path = temporary / "manifest.json"
        if not manifest_path.is_file():
            raise RemoteTrainingResultError(
                "TRAINING_RESULT_MANIFEST_MISSING",
                "training result manifest is missing",
                422,
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RemoteTrainingResultError(
                "TRAINING_RESULT_MANIFEST_INVALID",
                "training result manifest is invalid JSON",
                422,
            ) from error
        if not isinstance(manifest, dict):
            raise RemoteTrainingResultError(
                "TRAINING_RESULT_MANIFEST_INVALID",
                "training result manifest must be an object",
                422,
            )
        if (
            int(manifest.get("schema_version") or 0) != TRAINING_RESULT_SCHEMA_VERSION
            or str(manifest.get("task_id") or "") != str(expected_task_id)
            or int(manifest.get("execution_generation") or 0) != int(expected_execution_generation)
            or str(manifest.get("snapshot_id") or "") != str(expected_snapshot_id)
            or str(manifest.get("framework") or "") != "ultralytics"
            or manifest.get("artifact_verified") is not True
            or str(manifest.get("training_outcome") or "") not in SUCCESSFUL_TRAINING_OUTCOMES
        ):
            raise RemoteTrainingResultError(
                "TRAINING_RESULT_IDENTITY_MISMATCH",
                "training result manifest does not match durable task identity",
                409,
            )
        model_transport = str(manifest.get("model_transport") or "embedded-v1")
        if model_transport not in {"embedded-v1", "separate-object-v1"}:
            raise RemoteTrainingResultError(
                "TRAINING_RESULT_MODEL_TRANSPORT_INVALID",
                "training result model transport is unsupported",
                422,
            )
        if model_transport == "separate-object-v1" and not allow_separate_model_objects:
            raise RemoteTrainingResultError(
                "TRAINING_RESULT_MODEL_TRANSPORT_INVALID",
                "training result references separate model objects but verifier did not allow them",
                409,
            )
        raw_models = manifest.get("models")
        if not isinstance(raw_models, list) or not raw_models:
            raise RemoteTrainingResultError(
                "TRAINING_RESULT_MODEL_MISSING",
                "training result manifest has no verified models",
                409,
            )
        verified_models: list[dict[str, Any]] = []
        primary = False
        allowed_refs = {"manifest.json"}
        for item in raw_models:
            if not isinstance(item, Mapping):
                raise RemoteTrainingResultError(
                    "TRAINING_RESULT_MODEL_INVALID",
                    "training result model entry is invalid",
                    422,
                )
            ref = _safe_member_name(item.get("ref"))
            if not ref.startswith("models/"):
                raise RemoteTrainingResultError(
                    "TRAINING_RESULT_MODEL_INVALID",
                    "training result model reference is outside models/",
                    422,
                )
            path = (temporary / Path(*PurePosixPath(ref).parts)).resolve()
            expected_model_sha = str(item.get("sha256") or "").strip().lower()
            try:
                expected_model_size = int(item.get("size_bytes") or 0)
            except (TypeError, ValueError) as error:
                raise RemoteTrainingResultError(
                    "TRAINING_RESULT_MODEL_EVIDENCE_MISMATCH",
                    "training result model size evidence is invalid",
                    409,
                ) from error
            if (
                len(expected_model_sha) != 64
                or any(ch not in "0123456789abcdef" for ch in expected_model_sha)
                or expected_model_size <= 0
            ):
                raise RemoteTrainingResultError(
                    "TRAINING_RESULT_MODEL_EVIDENCE_MISMATCH",
                    "training result model evidence is incomplete",
                    409,
                )
            if model_transport == "embedded-v1":
                if temporary not in path.parents or not path.is_file():
                    raise RemoteTrainingResultError(
                        "TRAINING_RESULT_MODEL_MISSING",
                        "training result model file is missing",
                        409,
                    )
                if (
                    int(path.stat().st_size) != expected_model_size
                    or _sha256(path) != expected_model_sha
                ):
                    raise RemoteTrainingResultError(
                        "TRAINING_RESULT_MODEL_EVIDENCE_MISMATCH",
                        "training result model content does not match manifest evidence",
                        409,
                    )
            role = str(item.get("role") or "model")
            if role in {"best", "last"}:
                primary = True
            if model_transport == "embedded-v1":
                allowed_refs.add(ref)
            verified_models.append({
                "role": role,
                "ref": ref,
                "file_name": Path(ref).name,
                "sha256": expected_model_sha,
                "size_bytes": expected_model_size,
            })
        if not primary:
            raise RemoteTrainingResultError(
                "TRAINING_RESULT_PRIMARY_MODEL_MISSING",
                "training result has no best/last model",
                409,
            )
        actual_files = {
            path.relative_to(temporary).as_posix()
            for path in temporary.rglob("*")
            if path.is_file()
        }
        if actual_files != allowed_refs:
            raise RemoteTrainingResultError(
                "TRAINING_RESULT_UNDECLARED_MEMBER",
                "training result archive contains undeclared files",
                422,
            )
        os.replace(temporary, target)
        temporary = None  # type: ignore[assignment]
        return VerifiedTrainingResult(
            root=target,
            manifest=dict(manifest),
            models=tuple(verified_models),
        )
    except zipfile.BadZipFile as error:
        raise RemoteTrainingResultError(
            "TRAINING_RESULT_ARCHIVE_INVALID",
            "training result archive is not a valid ZIP",
            422,
        ) from error
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)


__all__ = [
    "RemoteTrainingResultError",
    "SUCCESSFUL_TRAINING_OUTCOMES",
    "TRAINING_RESULT_MAX_MEMBERS",
    "TRAINING_RESULT_MAX_UNCOMPRESSED_BYTES",
    "TRAINING_RESULT_SCHEMA_VERSION",
    "TrainingResultArchive",
    "VerifiedTrainingResult",
    "create_training_result_archive",
    "verify_training_result_archive",
]
