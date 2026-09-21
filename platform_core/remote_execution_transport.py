"""Portable object-storage transport for remote task execution.

Durable task payloads keep only object references and content evidence. Signed
GET/PUT URLs are minted just-in-time when an authenticated Agent starts an
execution and are never persisted into scheduler assignment truth.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from .algorithms import attach_version, list_algorithms, resolve_current_version_id, update_algorithm_version
from filelock import FileLock, Timeout

from .material_repository import MaterialRepository
from .model_artifacts import ModelArtifactService, build_artifact_object_key
from .remote_training_results import (
    RemoteTrainingResultError,
    verify_training_result_archive,
)
from .remote_material_import import (
    RemoteMaterialImportError,
    commit_material_review_archive,
)
from .remote_cleaning import (
    MAX_REMOTE_CLEAN_ITEMS,
    RemoteCleaningError,
    commit_remote_cleaning_review,
)
from .remote_material_lifecycle import RemoteMaterialStagingLifecycle
from .storage.zip_import import safe_member_path
from .resource_discovery import OFFICIAL_DOWNLOADABLE_MODELS
from .storage import StorageProviderFactory, StorageType
from .training_lineage import build_training_lineage
from .training_evaluation import build_evaluation_benchmark_scope, build_evaluation_truth


REMOTE_TRANSFER_TTL_SECONDS = 900
_REMOTE_PREFIX = "remote-execution"
_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")


class RemoteExecutionTransportError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409):
        self.code = str(code)
        self.status_code = int(status_code)
        super().__init__(str(message))


def _safe_segment(value: object, fallback: str) -> str:
    text = _SAFE_SEGMENT.sub("-", str(value or "").strip()).strip("-._")
    return (text or fallback)[:120]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_sha256(value: object, field: str = "sha256") -> str:
    normalized = str(value or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise RemoteExecutionTransportError(
            "REMOTE_RESULT_EVIDENCE_INVALID",
            f"{field} must be a 64-character lowercase/uppercase hexadecimal SHA256",
            422,
        )
    return normalized


def _positive_int(value: object, field: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise RemoteExecutionTransportError(
            "REMOTE_OBJECT_CONTRACT_INVALID",
            f"{field} must be a positive integer",
            422,
        ) from error
    if result <= 0:
        raise RemoteExecutionTransportError(
            "REMOTE_OBJECT_CONTRACT_INVALID",
            f"{field} must be a positive integer",
            422,
        )
    return result


class RemoteExecutionTransportService:
    def __init__(
        self,
        *,
        data_dir: str | Path,
        project_dir: Callable[[str], Path],
        algorithms_file: Callable[[str], Path],
        storage_sources_factory,
        storage_credentials_factory,
        provider_factory: Callable[[str, object, Mapping[str, str]], object] | None = None,
        model_artifacts: ModelArtifactService | None = None,
        task_artifacts=None,
    ):
        self.data_dir = Path(data_dir)
        self.project_dir = project_dir
        self.algorithms_file = algorithms_file
        self.storage_sources_factory = storage_sources_factory
        self.storage_credentials_factory = storage_credentials_factory
        self.provider_factory = provider_factory
        self.task_artifacts = task_artifacts
        self.model_artifacts = model_artifacts or ModelArtifactService(
            data_dir=self.data_dir,
            project_dir=self.project_dir,
            algorithms_file=self.algorithms_file,
            storage_sources_factory=self.storage_sources_factory,
            storage_credentials_factory=self.storage_credentials_factory,
        )

    def _configured_source(self):
        config = self.model_artifacts.repository.config()
        source_id = str(config.get("storage_source_id") or "").strip()
        if not source_id:
            return None
        source = self.storage_sources_factory().get(source_id)
        if source is None or not source.enabled:
            return None
        try:
            storage_type = StorageType.parse(source.type)
        except ValueError:
            return None
        # A portable deployment needs both signed download and signed upload.
        # Current OSS/S3 providers implement those contracts. Local storage and
        # generic remote_server storage are deliberately not treated as shared
        # filesystems or silently upgraded into remote execution.
        if storage_type not in {StorageType.OSS, StorageType.S3}:
            return None
        return source

    def _provider(self, project_id: str, source):
        secret: Mapping[str, str] = {}
        if source.secret_ref:
            secret = self.storage_credentials_factory().get(source.secret_ref) or {}
        if self.provider_factory is not None:
            return self.provider_factory(str(project_id), source, secret)
        return StorageProviderFactory(
            data_dir=self.data_dir,
            project_dir=self.project_dir(str(project_id)),
            credentials={source.id: secret},
        ).create(source)

    @staticmethod
    def _object_ref(
        *,
        source_id: str,
        object_key: str,
        file_name: str,
        size_bytes: int,
        sha256: str,
        content_type: str,
    ) -> dict[str, Any]:
        return {
            "storage_source_id": str(source_id),
            "object_key": str(object_key),
            "file_name": Path(str(file_name)).name,
            "size_bytes": int(size_bytes),
            "sha256": str(sha256).lower(),
            "content_type": str(content_type or "application/octet-stream"),
        }

    def _portable_model(
        self,
        *,
        project_id: str,
        source,
        model_path: str,
        model_reference: str,
        model_reference_type: str,
        algorithm_id: str,
        version_id: str,
    ) -> dict[str, Any] | None:
        if str(model_reference_type or "") == "official_downloadable":
            reference = str(model_reference or "").strip()
            if not reference or Path(reference).is_absolute() or "/" in reference or "\\" in reference:
                return None
            return {"type": "official", "reference": reference}

        if not str(algorithm_id or "").strip() or not str(version_id or "").strip():
            return None
        resolved_model = Path(str(model_path or "")).expanduser()
        try:
            resolved_model = resolved_model.resolve()
        except (OSError, RuntimeError):
            return None
        if not resolved_model.is_file() or resolved_model.stat().st_size <= 0:
            return None

        algorithm = next(
            (
                item
                for item in list_algorithms(self.algorithms_file(str(project_id)))
                if str(item.get("id") or "") == str(algorithm_id)
            ),
            None,
        )
        if algorithm is None:
            return None
        version = next(
            (
                item
                for item in (algorithm.get("versions") or [])
                if isinstance(item, Mapping)
                and str(item.get("id") or "") == str(version_id)
            ),
            None,
        )
        if version is None:
            return None

        discovered = self.model_artifacts.discover_version_artifacts(
            str(project_id),
            algorithm,
            version,
        )
        candidate = None
        for item in discovered:
            if str(item.get("target") or "") != "original":
                continue
            try:
                candidate_path = Path(str(item.get("source_path") or "")).expanduser().resolve()
            except (OSError, RuntimeError):
                continue
            if candidate_path == resolved_model:
                candidate = item
                break
        if candidate is None:
            return None

        row = self.model_artifacts.ensure_uploaded(candidate)
        if (
            str(row.get("storage_status") or "").upper() != "UPLOADED"
            or str(row.get("storage_source_id") or "") != str(source.id)
            or not str(row.get("object_key") or "").strip()
        ):
            return None
        return {
            "type": "object",
            **self._object_ref(
                source_id=str(row["storage_source_id"]),
                object_key=str(row["object_key"]),
                file_name=str(row["file_name"]),
                size_bytes=_positive_int(row.get("size_bytes"), "model.size_bytes"),
                sha256=str(row.get("sha256") or ""),
                content_type=mimetypes.guess_type(str(row["file_name"]))[0]
                or "application/octet-stream",
            ),
            "artifact_id": str(row.get("artifact_id") or ""),
        }

    def stage_deployment_test(
        self,
        *,
        project_id: str,
        task_id: str,
        input_path: str | Path,
        model_path: str,
        model_reference: str,
        model_reference_type: str,
        algorithm_id: str,
        version_id: str,
        framework: str,
        runtime_format: str,
        confidence: float,
    ) -> dict[str, Any] | None:
        """Stage durable remote references; return None when no portable backend exists."""
        source = self._configured_source()
        if source is None:
            return None
        model = self._portable_model(
            project_id=str(project_id),
            source=source,
            model_path=model_path,
            model_reference=model_reference,
            model_reference_type=model_reference_type,
            algorithm_id=algorithm_id,
            version_id=version_id,
        )
        if model is None:
            return None

        source_path = Path(input_path).expanduser().resolve()
        if not source_path.is_file() or source_path.stat().st_size <= 0:
            raise RemoteExecutionTransportError(
                "REMOTE_INPUT_NOT_FOUND",
                "deployment test input image is missing",
                409,
            )
        input_sha = _sha256(source_path)
        input_type = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
        safe_project = _safe_segment(project_id, "project")
        safe_task = _safe_segment(task_id, "task")
        input_key = "/".join(
            (
                _REMOTE_PREFIX,
                safe_project,
                safe_task,
                "input",
                f"{input_sha[:16]}-{_safe_segment(source_path.name, 'input.bin')}",
            )
        )
        output_key = "/".join(
            (
                _REMOTE_PREFIX,
                safe_project,
                safe_task,
                "output",
                "result.jpg",
            )
        )
        provider = self._provider(str(project_id), source)

        if provider.exists(input_key):
            meta = provider.stat(input_key)
            if int(meta.size_bytes) != source_path.stat().st_size:
                raise RemoteExecutionTransportError(
                    "REMOTE_INPUT_CONFLICT",
                    "staged deployment input exists with different size",
                    409,
                )
            if meta.sha256 and str(meta.sha256).lower() != input_sha:
                raise RemoteExecutionTransportError(
                    "REMOTE_INPUT_CONFLICT",
                    "staged deployment input exists with different sha256",
                    409,
                )
        else:
            meta = provider.upload(
                input_key,
                source_path,
                content_type=input_type,
                metadata={"sha256": input_sha, "purpose": "deployment-test-input"},
            )
        if int(meta.size_bytes) != source_path.stat().st_size:
            raise RemoteExecutionTransportError(
                "REMOTE_INPUT_UPLOAD_INVALID",
                "staged deployment input size verification failed",
                502,
            )
        if meta.sha256 and str(meta.sha256).lower() != input_sha:
            raise RemoteExecutionTransportError(
                "REMOTE_INPUT_UPLOAD_INVALID",
                "staged deployment input sha256 verification failed",
                502,
            )

        return {
            "version": 1,
            "task_kind": "DEPLOYMENT_TEST",
            "transport": "object-storage-v1",
            "deployment": {
                "framework": str(framework or "ultralytics"),
                "runtime_format": str(runtime_format or "").lower(),
                "confidence": max(0.0, min(1.0, float(confidence))),
                "input": self._object_ref(
                    source_id=str(source.id),
                    object_key=input_key,
                    file_name=source_path.name,
                    size_bytes=source_path.stat().st_size,
                    sha256=input_sha,
                    content_type=input_type,
                ),
                "model": model,
                "output": {
                    "storage_source_id": str(source.id),
                    "object_key": output_key,
                    "file_name": "result.jpg",
                    "content_type": "image/jpeg",
                },
            },
        }

    def stage_rknn_board_validation(
        self,
        *,
        project_id: str,
        task_id: str,
        conversion_job_id: str,
        model_path: str | Path,
        input_path: str | Path,
        chip: str,
        input_size: int,
    ) -> dict[str, Any]:
        source = self._configured_source()
        if source is None:
            raise RemoteExecutionTransportError(
                "REMOTE_RKNN_BOARD_STORAGE_REQUIRED",
                "RKNN board verification requires configured OSS/S3/MinIO object storage",
                409,
            )
        chip = str(chip or "").strip().lower()
        if chip not in {"rk3568", "rk3576"}:
            raise RemoteExecutionTransportError(
                "REMOTE_RKNN_BOARD_CHIP_INVALID",
                "RKNN board verification supports rk3568 or rk3576",
                422,
            )
        try:
            input_size = int(input_size)
        except (TypeError, ValueError) as error:
            raise RemoteExecutionTransportError(
                "REMOTE_RKNN_BOARD_INPUT_SIZE_INVALID",
                "RKNN board input_size must be an integer",
                422,
            ) from error
        if input_size < 32 or input_size > 4096:
            raise RemoteExecutionTransportError(
                "REMOTE_RKNN_BOARD_INPUT_SIZE_INVALID",
                "RKNN board input_size is out of range",
                422,
            )
        model = Path(model_path).expanduser().resolve()
        image = Path(input_path).expanduser().resolve()
        if model.suffix.lower() != ".rknn" or not model.is_file() or model.stat().st_size <= 0:
            raise RemoteExecutionTransportError(
                "REMOTE_RKNN_BOARD_MODEL_INVALID",
                "board verification source must be a non-empty .rknn artifact",
                422,
            )
        if not image.is_file() or image.stat().st_size <= 0:
            raise RemoteExecutionTransportError(
                "REMOTE_RKNN_BOARD_INPUT_INVALID",
                "board verification input image is missing or empty",
                422,
            )
        provider = self._provider(str(project_id), source)
        safe_project = _safe_segment(project_id, "project")
        safe_task = _safe_segment(task_id, "task")

        def stage(path: Path, purpose: str, content_type: str) -> dict[str, Any]:
            digest = _sha256(path)
            key = "/".join((
                _REMOTE_PREFIX,
                safe_project,
                safe_task,
                purpose,
                f"{digest[:16]}-{_safe_segment(path.name, purpose)}",
            ))
            if provider.exists(key):
                metadata = provider.stat(key)
            else:
                metadata = provider.upload(
                    key,
                    path,
                    content_type=content_type,
                    metadata={"sha256": digest, "purpose": purpose},
                )
            actual_sha = str(metadata.sha256 or "").strip().lower()
            if (
                int(metadata.size_bytes) != int(path.stat().st_size)
                or not actual_sha
                or actual_sha != digest
            ):
                raise RemoteExecutionTransportError(
                    "REMOTE_RKNN_BOARD_STAGE_INVALID",
                    f"staged {purpose} object does not match durable size/SHA256 evidence",
                    502,
                )
            return self._object_ref(
                source_id=str(source.id),
                object_key=key,
                file_name=path.name,
                size_bytes=int(path.stat().st_size),
                sha256=digest,
                content_type=content_type,
            )

        model_ref = stage(model, "rknn-board-model", "application/octet-stream")
        input_type = mimetypes.guess_type(image.name)[0] or "application/octet-stream"
        input_ref = stage(image, "rknn-board-input", input_type)
        output_key = "/".join((
            _REMOTE_PREFIX,
            safe_project,
            safe_task,
            "rknn-board-output",
            "result.jpg",
        ))
        return {
            "version": 1,
            "task_kind": "DEPLOYMENT_TEST",
            "transport": "object-storage-v1",
            "deployment": {
                "framework": "rknn",
                "runtime_format": "rknn",
                "confidence": 0.0,
                "input": input_ref,
                "model": {
                    "type": "object",
                    **model_ref,
                },
                "board": {
                    "schema_version": 1,
                    "chip": chip,
                    "input_size": input_size,
                    "conversion_job_id": str(conversion_job_id or "").strip(),
                    "model_sha256": str(model_ref["sha256"]),
                    "model_size_bytes": int(model_ref["size_bytes"]),
                },
                "output": {
                    "storage_source_id": str(source.id),
                    "object_key": output_key,
                    "file_name": "result.jpg",
                    "content_type": "image/jpeg",
                },
            },
        }

    def stage_material_storage_scan(
        self,
        *,
        project_id: str,
        task_id: str,
        storage_source_id: str,
        prefix: str,
        recursive: bool,
        import_format: str = "images",
        dataset_yaml: str = "",
        allow_root: bool = False,
        intent: str = "",
    ) -> dict[str, Any]:
        source = self.storage_sources_factory().get(str(storage_source_id))
        if source is None or not source.enabled:
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_STORAGE_UNAVAILABLE",
                "selected material storage source is unavailable",
                409,
            )
        try:
            storage_type = StorageType.parse(source.type)
        except ValueError as error:
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_STORAGE_INVALID",
                "selected material storage source type is invalid",
                422,
            ) from error
        if storage_type not in {StorageType.OSS, StorageType.S3}:
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_STORAGE_NOT_PORTABLE",
                "Agent storage scan requires OSS/S3/MinIO object storage",
                409,
            )
        normalized_format = str(import_format or "images").strip().lower()
        if normalized_format not in {"images", "yolo", "coco", "voc"}:
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_FORMAT_UNSUPPORTED",
                "Agent storage scan supports images, yolo, coco or voc",
                422,
            )
        normalized_intent = str(intent or "").strip().lower()
        if normalized_intent not in {"", "storage_rescan"}:
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_INTENT_INVALID",
                "unsupported portable material scan intent",
                422,
            )
        if normalized_intent == "storage_rescan" and normalized_format not in {"images", "yolo", "coco", "voc"}:
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_RESCAN_FORMAT_UNSUPPORTED",
                "Remote storage rescan Phase 2C supports image, YOLO, COCO or Pascal VOC reconciliation",
                422,
            )
        raw_prefix = str(prefix or "").strip().replace("\\", "/").strip("/")
        if not raw_prefix and not bool(allow_root):
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_PREFIX_REQUIRED",
                "Agent storage scan requires an explicit object prefix",
                422,
            )
        if raw_prefix:
            try:
                raw_prefix = safe_member_path(raw_prefix).as_posix()
            except Exception as error:
                raise RemoteExecutionTransportError(
                    "REMOTE_MATERIAL_PREFIX_INVALID",
                    "storage scan prefix must be a safe relative object prefix",
                    422,
                ) from error
        yaml_member = str(dataset_yaml or "").strip().replace("\\", "/")
        if yaml_member:
            try:
                yaml_member = safe_member_path(yaml_member).as_posix()
            except Exception as error:
                raise RemoteExecutionTransportError(
                    "REMOTE_MATERIAL_DATASET_YAML_INVALID",
                    "dataset_yaml must be a safe relative object key",
                    422,
                ) from error
        if normalized_format != "yolo" and yaml_member:
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_DATASET_YAML_INVALID",
                "dataset_yaml is only valid for YOLO storage scans",
                422,
            )

        provider = self._provider(str(project_id), source)
        health = provider.health_check()
        if not health.ok:
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_STORAGE_UNAVAILABLE",
                str(health.message or "material storage source health check failed"),
                409,
            )
        safe_project = _safe_segment(project_id, "project")
        safe_task = _safe_segment(task_id, "task")
        output_key = "/".join(
            (
                _REMOTE_PREFIX,
                safe_project,
                safe_task,
                "material-review",
                "review.zip",
            )
        )
        return {
            "version": 1,
            "task_kind": "MATERIAL_IMPORT",
            "transport": "object-storage-v1",
            "material_import": {
                "schema_version": 1,
                "mode": "storage_scan",
                "intent": normalized_intent,
                "import_format": normalized_format,
                "dataset_yaml": yaml_member,
                "source": {
                    "storage_source_id": str(source.id),
                    "storage_type": str(storage_type.value),
                    "prefix": raw_prefix,
                    "recursive": bool(recursive),
                },
                "target": {
                    "storage_source_id": str(source.id),
                    "storage_type": str(storage_type.value),
                    "target_prefix": raw_prefix,
                },
                "output": {
                    "storage_source_id": str(source.id),
                    "object_key": output_key,
                    "file_name": "material-review.zip",
                    "content_type": "application/zip",
                },
            },
        }

    def stage_material_import(
        self,
        *,
        project_id: str,
        task_id: str,
        archive_path: str | Path,
        storage_source_id: str,
        target_prefix: str,
        import_format: str = "images",
        dataset_yaml: str = "",
    ) -> dict[str, Any]:
        normalized_format = str(import_format or "images").strip().lower()
        if normalized_format not in {"images", "yolo", "coco", "voc"}:
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_FORMAT_UNSUPPORTED",
                "portable Agent material import supports images, yolo, coco or voc ZIP review",
                422,
            )
        normalized_yaml = ""
        if str(dataset_yaml or "").strip():
            try:
                normalized_yaml = safe_member_path(str(dataset_yaml).strip()).as_posix()
            except Exception as error:
                raise RemoteExecutionTransportError(
                    "REMOTE_MATERIAL_DATASET_YAML_INVALID",
                    "Agent YOLO dataset_yaml must be a safe ZIP-relative path",
                    422,
                ) from error
        if normalized_format != "yolo" and normalized_yaml:
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_DATASET_YAML_INVALID",
                "dataset_yaml is only valid for YOLO Agent import",
                422,
            )
        prefix = safe_member_path(str(target_prefix or "").strip()).as_posix()
        source_id = str(storage_source_id or "").strip()
        source = self.storage_sources_factory().get(source_id)
        if source is None or not source.enabled:
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_STORAGE_UNAVAILABLE",
                "target material object storage source is unavailable",
                409,
            )
        try:
            storage_type = StorageType.parse(source.type)
        except ValueError as error:
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_STORAGE_INVALID",
                "target material storage type is invalid",
                422,
            ) from error
        if storage_type not in {StorageType.OSS, StorageType.S3}:
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_STORAGE_NOT_PORTABLE",
                "Agent material import requires OSS/S3/MinIO target storage",
                422,
            )
        archive = Path(archive_path).expanduser().resolve()
        if not archive.is_file() or archive.suffix.lower() != ".zip" or archive.stat().st_size <= 0:
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_ARCHIVE_INVALID",
                "material import source must be a non-empty ZIP file",
                422,
            )
        digest = _sha256(archive)
        safe_project = _safe_segment(project_id, "project")
        safe_task = _safe_segment(task_id, "task")
        input_key = "/".join((
            _REMOTE_PREFIX,
            safe_project,
            safe_task,
            "material-input",
            f"{digest[:16]}-{_safe_segment(archive.name, 'materials.zip')}",
        ))
        output_key = "/".join((
            _REMOTE_PREFIX,
            safe_project,
            safe_task,
            "material-review",
            "review.zip",
        ))
        provider = self._provider(str(project_id), source)
        if provider.exists(input_key):
            metadata = provider.stat(input_key)
        else:
            metadata = provider.upload(
                input_key,
                archive,
                content_type="application/zip",
                metadata={"sha256": digest, "purpose": "agent-material-import-input"},
            )
        if (
            int(metadata.size_bytes) != int(archive.stat().st_size)
            or str(metadata.sha256 or "").strip().lower() != digest
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_ARCHIVE_UPLOAD_INVALID",
                "staged material ZIP is missing matching size/SHA256 evidence",
                502,
            )
        return {
            "version": 1,
            "task_kind": "MATERIAL_IMPORT",
            "transport": "object-storage-v1",
            "material_import": {
                "schema_version": 1,
                "mode": "zip_scan",
                "import_format": normalized_format,
                "dataset_yaml": normalized_yaml,
                "target": {
                    "storage_source_id": source_id,
                    "storage_type": storage_type.value,
                    "target_prefix": prefix,
                },
                "input": self._object_ref(
                    source_id=source_id,
                    object_key=input_key,
                    file_name=archive.name,
                    size_bytes=int(archive.stat().st_size),
                    sha256=digest,
                    content_type="application/zip",
                ),
                "output": {
                    "storage_source_id": source_id,
                    "object_key": output_key,
                    "file_name": "material-review.zip",
                    "content_type": "application/zip",
                },
            },
        }

    @staticmethod
    def _portable_conversion_params(target: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        target = str(target or "").strip().lower()
        if target == "rknn":
            target = "rockchip"
        values = dict(params or {})
        if target not in {"onnx", "rockchip"}:
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_TARGET_UNSUPPORTED",
                "portable Agent conversion currently supports ONNX and Rockchip RKNN only",
                409,
            )

        def integer(name: str, default: int, minimum: int, maximum: int) -> int:
            raw = values.get(name)
            if raw in (None, ""):
                result = default
            else:
                try:
                    result = int(raw)
                except (TypeError, ValueError) as error:
                    raise RemoteExecutionTransportError(
                        "REMOTE_CONVERSION_PARAMS_INVALID",
                        f"conversion parameter {name} must be an integer",
                        422,
                    ) from error
            if result < minimum or result > maximum:
                raise RemoteExecutionTransportError(
                    "REMOTE_CONVERSION_PARAMS_INVALID",
                    f"conversion parameter {name} is out of range",
                    422,
                )
            return result

        def boolean(name: str, default: bool = False) -> bool:
            raw = values.get(name)
            if raw is None:
                return default
            if isinstance(raw, bool):
                return raw
            normalized = str(raw).strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_PARAMS_INVALID",
                f"conversion parameter {name} must be boolean",
                422,
            )

        common = {
            "input_size": integer("input_size", 640, 32, 4096),
            "batch": integer("batch", 1, 1, 128),
            "opset": integer("opset", 12, 7, 24),
            "dynamic": boolean("dynamic", False),
            "simplify": boolean("simplify", False),
        }
        if target == "onnx":
            return common

        chip = str(values.get("chip") or "").strip().lower()
        if chip not in {"rk3568", "rk3576"}:
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_PARAMS_INVALID",
                "portable Agent RKNN conversion currently supports rk3568 or rk3576",
                422,
            )
        precision = str(values.get("precision") or "fp16").strip().lower()
        if precision not in {"fp16", "int8"}:
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_PARAMS_INVALID",
                "portable Agent RKNN conversion supports fp16 or int8 precision",
                422,
            )
        if common["dynamic"]:
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_PARAMS_INVALID",
                "portable Agent RKNN conversion requires a static input shape",
                422,
            )
        if common["batch"] != 1:
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_PARAMS_INVALID",
                "portable Agent RKNN conversion currently requires batch=1",
                422,
            )

        def triplet(name: str, default: str) -> str:
            raw = str(values.get(name) or default).strip()
            parts = [part.strip() for part in raw.split(",")]
            if len(parts) != 3:
                raise RemoteExecutionTransportError(
                    "REMOTE_CONVERSION_PARAMS_INVALID",
                    f"conversion parameter {name} must contain three comma-separated numbers",
                    422,
                )
            try:
                numbers = [float(part) for part in parts]
            except ValueError as error:
                raise RemoteExecutionTransportError(
                    "REMOTE_CONVERSION_PARAMS_INVALID",
                    f"conversion parameter {name} must contain numbers",
                    422,
                ) from error
            return ",".join(
                str(int(value)) if value.is_integer() else str(value)
                for value in numbers
            )

        common.update({
            "chip": chip,
            "precision": precision,
            "mean": triplet("mean", "0,0,0"),
            "rknn_std": triplet("rknn_std", "255,255,255"),
        })
        if precision == "int8":
            common["calibration_count"] = integer(
                "calibration_count", 100, 1, 1000
            )
            snapshot = str(values.get("calibration_snapshot") or "").strip().lower()
            if snapshot:
                common["calibration_snapshot"] = _normalized_sha256(
                    snapshot,
                    "conversion.params.calibration_snapshot",
                )
        return common

    def build_rknn_calibration_snapshot(
        self,
        *,
        project_id: str,
        dataset_id: str,
        split: str,
        limit: int,
    ) -> dict[str, Any]:
        try:
            requested = max(1, min(1000, int(limit)))
        except (TypeError, ValueError) as error:
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_CALIBRATION_INVALID",
                "RKNN calibration_count must be an integer",
                422,
            ) from error
        dataset = str(dataset_id or "default").strip() or "default"
        split_name = str(split or "train").strip().lower() or "train"
        if split_name not in {"train", "val", "test", "all"}:
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_CALIBRATION_INVALID",
                "RKNN calibration split must be train, val, test or all",
                422,
            )
        repository = MaterialRepository(self.project_dir(str(project_id)))
        revision = repository.current_revision()
        selected = []
        for material in repository.read().rows:
            if str(material.get("dataset_id") or "default") != dataset:
                continue
            material_split = str(material.get("split") or "train").strip().lower() or "train"
            if split_name != "all" and material_split != split_name:
                continue
            selected.append(material)
            if len(selected) >= requested:
                break
        if not selected:
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_CALIBRATION_EMPTY",
                "RKNN INT8 conversion requires calibration images in the selected dataset/split",
                409,
            )
        items = []
        for material in selected:
            ref = self._portable_clean_material(None, material)
            _source, provider = self._source_provider(str(project_id), ref)
            metadata = provider.stat(str(ref["object_key"]))
            actual_sha = str(metadata.sha256 or "").strip().lower()
            if (
                int(metadata.size_bytes) != int(ref["size_bytes"])
                or not actual_sha
                or actual_sha != str(ref["sha256"])
            ):
                raise RemoteExecutionTransportError(
                    "REMOTE_CONVERSION_CALIBRATION_CHANGED",
                    f"calibration material {ref['image_id']} does not match durable size/SHA256 evidence",
                    409,
                )
            items.append({
                "image_id": str(ref["image_id"]),
                "file_name": str(ref["file_name"]),
                "storage_source_id": str(ref["storage_source_id"]),
                "storage_type": str(ref["storage_type"]),
                "object_key": str(ref["object_key"]),
                "size_bytes": int(ref["size_bytes"]),
                "etag": str(ref.get("etag") or ""),
                "sha256": str(ref["sha256"]),
            })
        digest_payload = {
            "dataset_id": dataset,
            "split": split_name,
            "material_revision": int(revision),
            "items": [
                {
                    "image_id": item["image_id"],
                    "storage_source_id": item["storage_source_id"],
                    "object_key": item["object_key"],
                    "size_bytes": item["size_bytes"],
                    "sha256": item["sha256"],
                }
                for item in items
            ],
        }
        snapshot_id = hashlib.sha256(
            json.dumps(
                digest_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return {
            "schema_version": 1,
            "snapshot_id": snapshot_id,
            "dataset_id": dataset,
            "split": split_name,
            "material_revision": int(revision),
            "requested_count": requested,
            "item_count": len(items),
            "items": items,
        }

    @staticmethod
    def _normalized_rknn_calibration(
        calibration: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if not isinstance(calibration, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_CALIBRATION_REQUIRED",
                "RKNN INT8 conversion requires a frozen portable calibration snapshot",
                422,
            )
        if int(calibration.get("schema_version") or 0) != 1:
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_CALIBRATION_INVALID",
                "RKNN calibration snapshot schema version is invalid",
                422,
            )
        snapshot_id = _normalized_sha256(
            calibration.get("snapshot_id"),
            "conversion.calibration.snapshot_id",
        )
        try:
            item_count = int(calibration.get("item_count") or 0)
            requested_count = int(calibration.get("requested_count") or item_count)
            revision = int(calibration.get("material_revision") or 0)
        except (TypeError, ValueError) as error:
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_CALIBRATION_INVALID",
                "RKNN calibration snapshot counters are invalid",
                422,
            ) from error
        raw_items = calibration.get("items")
        if (
            not isinstance(raw_items, list)
            or item_count <= 0
            or item_count > 1000
            or len(raw_items) != item_count
            or requested_count < item_count
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_CALIBRATION_INVALID",
                "RKNN calibration snapshot item count is invalid",
                422,
            )
        items = []
        seen_ids = set()
        for raw in raw_items:
            if not isinstance(raw, Mapping):
                raise RemoteExecutionTransportError(
                    "REMOTE_CONVERSION_CALIBRATION_INVALID",
                    "RKNN calibration item must be an object reference",
                    422,
                )
            image_id = str(raw.get("image_id") or "").strip()
            source_id = str(raw.get("storage_source_id") or "").strip()
            object_key = str(raw.get("object_key") or "").strip()
            file_name = Path(str(raw.get("file_name") or object_key)).name
            sha256 = _normalized_sha256(
                raw.get("sha256"),
                "conversion.calibration.item.sha256",
            )
            size_bytes = _positive_int(
                raw.get("size_bytes"),
                "conversion.calibration.item.size_bytes",
            )
            if (
                not image_id
                or image_id in seen_ids
                or not source_id
                or not object_key
                or not file_name
            ):
                raise RemoteExecutionTransportError(
                    "REMOTE_CONVERSION_CALIBRATION_INVALID",
                    "RKNN calibration item identity is invalid",
                    422,
                )
            seen_ids.add(image_id)
            items.append({
                "image_id": image_id,
                "file_name": file_name,
                "storage_source_id": source_id,
                "storage_type": str(raw.get("storage_type") or ""),
                "object_key": object_key,
                "size_bytes": size_bytes,
                "etag": str(raw.get("etag") or ""),
                "sha256": sha256,
            })
        return {
            "schema_version": 1,
            "snapshot_id": snapshot_id,
            "dataset_id": str(calibration.get("dataset_id") or "default"),
            "split": str(calibration.get("split") or "train"),
            "material_revision": revision,
            "requested_count": requested_count,
            "item_count": item_count,
            "items": items,
        }

    def stage_model_conversion(
        self,
        *,
        project_id: str,
        task_id: str,
        source_id: str,
        source_path: str | Path,
        algorithm_id: str,
        version_id: str,
        target: str,
        params: Mapping[str, Any] | None,
        calibration_snapshot: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        target = str(target or "").strip().lower()
        if target == "rknn":
            target = "rockchip"
        portable_params = self._portable_conversion_params(target, params)
        calibration = None
        if target == "rockchip" and portable_params.get("precision") == "int8":
            calibration = self._normalized_rknn_calibration(calibration_snapshot)
            portable_params["calibration_count"] = int(calibration["item_count"])
            portable_params["calibration_snapshot"] = str(calibration["snapshot_id"])
        elif calibration_snapshot is not None:
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_CALIBRATION_INVALID",
                "calibration snapshot is only valid for Rockchip INT8 conversion",
                422,
            )
        source = self._configured_source()
        if source is None:
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_STORAGE_REQUIRED",
                "portable model conversion requires configured OSS/S3/MinIO model asset storage",
                409,
            )
        model = self._portable_model(
            project_id=str(project_id),
            source=source,
            model_path=str(source_path),
            model_reference="",
            model_reference_type="",
            algorithm_id=str(algorithm_id),
            version_id=str(version_id),
        )
        if not isinstance(model, Mapping) or str(model.get("type") or "") != "object":
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_SOURCE_NOT_PORTABLE",
                "portable conversion source must be a verified algorithm-version model artifact",
                409,
            )
        # Revalidate server-visible evidence before publishing a durable contract.
        _source, provider = self._source_provider(str(project_id), model)
        metadata = provider.stat(str(model.get("object_key") or ""))
        expected_size = _positive_int(model.get("size_bytes"), "conversion.source.size_bytes")
        expected_sha = _normalized_sha256(model.get("sha256"), "conversion.source.sha256")
        actual_sha = str(metadata.sha256 or "").strip().lower()
        if int(metadata.size_bytes) != expected_size or actual_sha != expected_sha:
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_SOURCE_UNVERIFIED",
                "conversion source model object does not match durable size/SHA256 evidence",
                409,
            )

        safe_project = _safe_segment(project_id, "project")
        safe_task = _safe_segment(task_id, "task")
        output_name = (
            "model.onnx"
            if target == "onnx"
            else f"model_{portable_params['chip']}.rknn"
        )
        output_key = "/".join((
            _REMOTE_PREFIX,
            safe_project,
            safe_task,
            "conversion-output",
            output_name,
        ))
        return {
            "version": 1,
            "task_kind": "MODEL_CONVERSION",
            "transport": "object-storage-v1",
            "conversion": {
                "schema_version": 1,
                "target": target,
                "source": dict(model),
                "source_trace": {
                    "source_id": str(source_id or ""),
                    "algorithm_id": str(algorithm_id or ""),
                    "version_id": str(version_id or ""),
                    "sha256": expected_sha,
                },
                "params": portable_params,
                **({"calibration": calibration} if calibration is not None else {}),
                "output": {
                    "storage_source_id": str(source.id),
                    "object_key": output_key,
                    "file_name": output_name,
                    "content_type": "application/octet-stream",
                },
            },
        }

    @staticmethod
    def _conversion_remote(task, payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        if str(getattr(task.kind, "value", task.kind)) != "MODEL_CONVERSION":
            raise RemoteExecutionTransportError(
                "REMOTE_TASK_KIND_UNSUPPORTED",
                "portable conversion transport requires a MODEL_CONVERSION task",
                409,
            )
        remote = payload.get("remote_execution")
        if not isinstance(remote, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_MISSING",
                "portable conversion contract is missing",
                409,
            )
        if (
            int(remote.get("version") or 0) != 1
            or str(remote.get("task_kind") or "") != "MODEL_CONVERSION"
            or str(remote.get("transport") or "") != "object-storage-v1"
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable conversion contract is invalid",
                422,
            )
        conversion = remote.get("conversion")
        if not isinstance(conversion, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable conversion payload is missing",
                422,
            )
        if int(conversion.get("schema_version") or 0) != 1:
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable conversion schema version is invalid",
                422,
            )
        source_trace = conversion.get("source_trace")
        if (
            not isinstance(source_trace, Mapping)
            or not str(source_trace.get("algorithm_id") or "").strip()
            or not str(source_trace.get("version_id") or "").strip()
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_SOURCE_TRACE_MISSING",
                "portable conversion source lineage requires algorithm_id and version_id",
                422,
            )
        target = str(conversion.get("target") or "").strip().lower()
        # Re-normalize instead of trusting task-supplied nested parameters.
        params = RemoteExecutionTransportService._portable_conversion_params(
            target,
            conversion.get("params") if isinstance(conversion.get("params"), Mapping) else {},
        )
        calibration = conversion.get("calibration")
        if target == "rockchip" and params.get("precision") == "int8":
            normalized = RemoteExecutionTransportService._normalized_rknn_calibration(
                calibration if isinstance(calibration, Mapping) else None
            )
            if (
                str(params.get("calibration_snapshot") or "") != str(normalized["snapshot_id"])
                or int(params.get("calibration_count") or 0) != int(normalized["item_count"])
            ):
                raise RemoteExecutionTransportError(
                    "REMOTE_CONVERSION_CALIBRATION_INVALID",
                    "RKNN calibration snapshot does not match portable conversion parameters",
                    422,
                )
        elif calibration is not None:
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_CALIBRATION_INVALID",
                "unexpected calibration snapshot for non-INT8 conversion",
                422,
            )
        return remote, conversion

    def _resolve_conversion_execution_payload(
        self,
        task,
        payload: Mapping[str, Any],
        assignment: Mapping[str, Any],
    ) -> dict[str, Any]:
        _remote, conversion = self._conversion_remote(task, payload)
        source_ref = conversion.get("source")
        output_ref = conversion.get("output")
        if not isinstance(source_ref, Mapping) or not isinstance(output_ref, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable conversion source/output references are incomplete",
                422,
            )
        if str(source_ref.get("type") or "") != "object":
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_SOURCE_NOT_PORTABLE",
                "portable conversion source must be an object model",
                422,
            )
        target = str(conversion.get("target") or "").strip().lower()
        params = self._portable_conversion_params(
            target,
            conversion.get("params") if isinstance(conversion.get("params"), Mapping) else {},
        )
        expected_suffix = ".onnx" if target == "onnx" else ".rknn"
        output_name = Path(
            str(
                output_ref.get("file_name")
                or ("model.onnx" if target == "onnx" else "model.rknn")
            )
        ).name
        if Path(output_name).suffix.lower() != expected_suffix:
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable conversion output suffix does not match target",
                422,
            )
        trace = conversion.get("source_trace")
        trace = dict(trace) if isinstance(trace, Mapping) else {}
        resolved_calibration = None
        if target == "rockchip" and params.get("precision") == "int8":
            calibration = self._normalized_rknn_calibration(
                conversion.get("calibration")
                if isinstance(conversion.get("calibration"), Mapping)
                else None
            )
            resolved_items = []
            for item in calibration["items"]:
                resolved_items.append({
                    "image_id": str(item["image_id"]),
                    "download": self._download_contract(
                        str(task.project_id),
                        item,
                        require_server_sha256=True,
                    ),
                })
            resolved_calibration = {
                "schema_version": 1,
                "snapshot_id": str(calibration["snapshot_id"]),
                "dataset_id": str(calibration["dataset_id"]),
                "split": str(calibration["split"]),
                "material_revision": int(calibration["material_revision"]),
                "item_count": int(calibration["item_count"]),
                "items": resolved_items,
            }
        return {
            "schema_version": 1,
            "task_kind": "MODEL_CONVERSION",
            "transport": "object-storage-v1",
            "target": target,
            "params": params,
            "source": {
                "type": "object",
                "artifact_id": str(source_ref.get("artifact_id") or ""),
                "download": self._download_contract(
                    str(task.project_id),
                    source_ref,
                    require_server_sha256=True,
                ),
            },
            "source_trace": {
                "source_id": str(trace.get("source_id") or ""),
                "algorithm_id": str(trace.get("algorithm_id") or ""),
                "version_id": str(trace.get("version_id") or ""),
                "sha256": str(trace.get("sha256") or "").strip().lower(),
            },
            **({"calibration": resolved_calibration} if resolved_calibration is not None else {}),
            "output": {
                "type": "object",
                "storage_ref": {
                    "storage_source_id": str(output_ref.get("storage_source_id") or ""),
                    "object_key": str(output_ref.get("object_key") or ""),
                    "file_name": output_name,
                    "content_type": str(output_ref.get("content_type") or "application/octet-stream"),
                },
                "upload_protocol": "prepare-after-local-hash-v1",
            },
        }

    def _source_provider(self, project_id: str, ref: Mapping[str, Any]):
        source_id = str(ref.get("storage_source_id") or "").strip()
        source = self.storage_sources_factory().get(source_id)
        if source is None or not source.enabled:
            raise RemoteExecutionTransportError(
                "REMOTE_STORAGE_SOURCE_UNAVAILABLE",
                f"storage source {source_id or '<empty>'} is unavailable",
                409,
            )
        storage_type = StorageType.parse(source.type)
        if storage_type not in {StorageType.OSS, StorageType.S3}:
            raise RemoteExecutionTransportError(
                "REMOTE_STORAGE_NOT_PORTABLE",
                "remote execution requires OSS/S3-compatible object storage",
                409,
            )
        return source, self._provider(project_id, source)

    def _download_contract(
        self,
        project_id: str,
        ref: Mapping[str, Any],
        *,
        require_server_sha256: bool = False,
    ) -> dict[str, Any]:
        object_key = str(ref.get("object_key") or "").strip()
        expected_size = _positive_int(ref.get("size_bytes"), "object.size_bytes")
        expected_sha = str(ref.get("sha256") or "").strip().lower()
        if not object_key or len(expected_sha) != 64:
            raise RemoteExecutionTransportError(
                "REMOTE_OBJECT_CONTRACT_INVALID",
                "download object reference is incomplete",
                422,
            )
        _source, provider = self._source_provider(project_id, ref)
        metadata = provider.stat(object_key)
        if int(metadata.size_bytes) != expected_size:
            raise RemoteExecutionTransportError(
                "REMOTE_OBJECT_CHANGED",
                "remote object size no longer matches durable task evidence",
                409,
            )
        actual_sha = str(metadata.sha256 or "").strip().lower()
        if require_server_sha256 and not actual_sha:
            raise RemoteExecutionTransportError(
                "REMOTE_OBJECT_HASH_UNVERIFIED",
                "remote object is missing server-visible sha256 metadata",
                409,
            )
        if actual_sha and actual_sha != expected_sha:
            raise RemoteExecutionTransportError(
                "REMOTE_OBJECT_CHANGED",
                "remote object sha256 no longer matches durable task evidence",
                409,
            )
        url = provider.generate_preview_url(
            object_key,
            expires_seconds=REMOTE_TRANSFER_TTL_SECONDS,
        )
        if not url:
            raise RemoteExecutionTransportError(
                "REMOTE_DOWNLOAD_URL_UNAVAILABLE",
                "storage provider cannot mint a signed download URL",
                409,
            )
        return {
            "method": "GET",
            "url": str(url),
            "headers": {},
            "expires_seconds": REMOTE_TRANSFER_TTL_SECONDS,
            "file_name": Path(str(ref.get("file_name") or "input.bin")).name,
            "size_bytes": expected_size,
            "sha256": expected_sha,
            "content_type": str(ref.get("content_type") or "application/octet-stream"),
        }

    def _upload_contract(
        self,
        project_id: str,
        ref: Mapping[str, Any],
        *,
        sha256: str,
        size_bytes: int,
    ) -> dict[str, Any]:
        object_key = str(ref.get("object_key") or "").strip()
        if not object_key:
            raise RemoteExecutionTransportError(
                "REMOTE_OBJECT_CONTRACT_INVALID",
                "output object reference is incomplete",
                422,
            )
        expected_sha = _normalized_sha256(sha256, "result.sha256")
        expected_size = _positive_int(size_bytes, "result.size_bytes")
        _source, provider = self._source_provider(project_id, ref)
        content_type = str(ref.get("content_type") or "application/octet-stream")
        contract_factory = getattr(provider, "generate_upload_contract", None)
        if not callable(contract_factory):
            raise RemoteExecutionTransportError(
                "REMOTE_UPLOAD_URL_UNAVAILABLE",
                "storage provider cannot mint an overwrite-protected upload contract",
                409,
            )
        contract = contract_factory(
            object_key,
            expires_seconds=REMOTE_TRANSFER_TTL_SECONDS,
            content_type=content_type,
            metadata={"sha256": expected_sha},
            size_bytes=expected_size,
        )
        if not isinstance(contract, Mapping) or not str(contract.get("url") or ""):
            raise RemoteExecutionTransportError(
                "REMOTE_UPLOAD_URL_UNAVAILABLE",
                "storage provider returned an invalid upload contract",
                409,
            )
        if contract.get("overwrite_protected") is not True:
            raise RemoteExecutionTransportError(
                "REMOTE_UPLOAD_NOT_PROTECTED",
                "remote result upload must reject overwriting existing objects",
                409,
            )
        headers = {str(key): str(value) for key, value in dict(contract.get("headers") or {}).items()}
        lower_headers = {key.lower(): value for key, value in headers.items()}
        metadata_hashes = [
            value
            for key, value in lower_headers.items()
            if key in {"x-amz-meta-sha256", "x-oss-meta-sha256"}
        ]
        if lower_headers.get("content-length") != str(expected_size) or expected_sha not in metadata_hashes:
            raise RemoteExecutionTransportError(
                "REMOTE_UPLOAD_EVIDENCE_UNBOUND",
                "storage upload contract did not bind result size and sha256 metadata",
                409,
            )
        return {
            "method": str(contract.get("method") or "PUT").upper(),
            "url": str(contract["url"]),
            "headers": headers,
            "expires_seconds": int(contract.get("expires_seconds") or REMOTE_TRANSFER_TTL_SECONDS),
            "overwrite_protected": True,
            "file_name": Path(str(ref.get("file_name") or "result.bin")).name,
            "content_type": content_type,
            "size_bytes": expected_size,
            "sha256": expected_sha,
        }

    @staticmethod
    def _deployment_remote(task, payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        if str(getattr(task.kind, "value", task.kind)) != "DEPLOYMENT_TEST":
            raise RemoteExecutionTransportError(
                "REMOTE_TASK_KIND_UNSUPPORTED",
                "remote object-storage result transport is only implemented for deployment tests",
                409,
            )
        remote = payload.get("remote_execution")
        if not isinstance(remote, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_MISSING",
                "portable remote execution contract is missing",
                409,
            )
        if (
            int(remote.get("version") or 0) != 1
            or str(remote.get("task_kind") or "") != "DEPLOYMENT_TEST"
            or str(remote.get("transport") or "") != "object-storage-v1"
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable deployment contract is invalid",
                422,
            )
        deployment = remote.get("deployment")
        if not isinstance(deployment, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable deployment payload is missing",
                422,
            )
        return remote, deployment

    @staticmethod
    def _material_remote(task, payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        if str(getattr(task.kind, "value", task.kind)) != "MATERIAL_IMPORT":
            raise RemoteExecutionTransportError(
                "REMOTE_TASK_KIND_UNSUPPORTED",
                "portable material import transport requires a MATERIAL_IMPORT task",
                409,
            )
        remote = payload.get("remote_execution")
        if not isinstance(remote, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_MISSING",
                "portable material import contract is missing",
                409,
            )
        if (
            int(remote.get("version") or 0) != 1
            or str(remote.get("task_kind") or "") != "MATERIAL_IMPORT"
            or str(remote.get("transport") or "") != "object-storage-v1"
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable material import contract is invalid",
                422,
            )
        material = remote.get("material_import")
        if not isinstance(material, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable material import payload is missing",
                422,
            )
        target = material.get("target")
        mode = str(material.get("mode") or "")
        intent = str(material.get("intent") or "").strip().lower()
        import_format = str(material.get("import_format") or "")
        allowed_formats = {"images", "yolo", "coco", "voc"}
        if (
            int(material.get("schema_version") or 0) != 1
            or mode not in {"zip_scan", "storage_scan"}
            or intent not in {"", "storage_rescan"}
            or import_format not in allowed_formats
            or not isinstance(target, Mapping)
            or not str(target.get("storage_source_id") or "").strip()
            or not str(target.get("storage_type") or "").strip()
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable material import identity is invalid",
                422,
            )
        target_prefix = str(target.get("target_prefix") or "").strip()
        if intent == "storage_rescan" and (
            mode != "storage_scan" or import_format not in {"images", "yolo", "coco", "voc"}
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "storage_rescan intent requires an image, YOLO, COCO or Pascal VOC storage_scan contract",
                422,
            )
        if mode == "zip_scan" and not target_prefix:
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable ZIP material target prefix is required",
                422,
            )
        if target_prefix:
            safe_member_path(target_prefix)
        if mode == "storage_scan":
            source = material.get("source")
            if (
                not isinstance(source, Mapping)
                or not str(source.get("storage_source_id") or "").strip()
                or not str(source.get("storage_type") or "").strip()
                or str(source.get("storage_source_id") or "") != str(target.get("storage_source_id") or "")
                or str(source.get("storage_type") or "") != str(target.get("storage_type") or "")
            ):
                raise RemoteExecutionTransportError(
                    "REMOTE_EXECUTION_CONTRACT_INVALID",
                    "portable storage_scan source identity is invalid",
                    422,
                )
            source_prefix = str(source.get("prefix") or "").strip()
            if source_prefix:
                safe_member_path(source_prefix)
            if target_prefix != source_prefix:
                raise RemoteExecutionTransportError(
                    "REMOTE_EXECUTION_CONTRACT_INVALID",
                    "storage_scan target prefix must equal its source prefix",
                    422,
                )
        dataset_yaml = str(material.get("dataset_yaml") or "").strip()
        if dataset_yaml:
            safe_member_path(dataset_yaml)
        if import_format != "yolo" and dataset_yaml:
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "dataset_yaml is only valid for YOLO material contracts",
                422,
            )
        return remote, material

    def build_cleaning_remote_contract(self, project_id: str, task_id: str) -> dict[str, Any]:
        source = self._configured_source()
        if source is None:
            raise RemoteExecutionTransportError(
                "REMOTE_CLEANING_STORAGE_REQUIRED",
                "Agent cleaning requires an enabled OSS/S3-compatible unified object storage source",
                409,
            )
        storage_type = StorageType.parse(source.type).value
        output_key = "/".join([
            _REMOTE_PREFIX,
            _safe_segment(project_id, "project"),
            _safe_segment(task_id, "task"),
            "cleaning-review",
            "review.jsonl",
        ])
        return {
            "version": 1,
            "task_kind": "MATERIAL_BATCH",
            "transport": "object-storage-v1",
            "cleaning": {
                "schema_version": 1,
                "selection_protocol": "exact-material-selection-v1",
                "output": {
                    "storage_source_id": str(source.id),
                    "storage_type": storage_type,
                    "object_key": output_key,
                    "file_name": "cleaning-review.jsonl",
                    "content_type": "application/x-ndjson",
                },
            },
        }

    @staticmethod
    def _clean_remote(task, payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        if str(getattr(task.kind, "value", task.kind)) != "MATERIAL_BATCH":
            raise RemoteExecutionTransportError(
                "REMOTE_TASK_KIND_UNSUPPORTED",
                "portable cleaning transport requires a MATERIAL_BATCH task",
                409,
            )
        if str(payload.get("operation") or "").strip().upper() != "CLEAN":
            raise RemoteExecutionTransportError(
                "REMOTE_CLEANING_OPERATION_INVALID",
                "portable MATERIAL_BATCH execution is implemented only for CLEAN",
                422,
            )
        if str(payload.get("execution_mode") or "").strip().lower() != "agent":
            raise RemoteExecutionTransportError(
                "REMOTE_CLEANING_MODE_INVALID",
                "portable cleaning requires execution_mode=agent",
                422,
            )
        remote = payload.get("remote_execution")
        if (
            not isinstance(remote, Mapping)
            or int(remote.get("version") or 0) != 1
            or str(remote.get("task_kind") or "") != "MATERIAL_BATCH"
            or str(remote.get("transport") or "") != "object-storage-v1"
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable cleaning contract is invalid",
                422,
            )
        cleaning = remote.get("cleaning")
        output = cleaning.get("output") if isinstance(cleaning, Mapping) else None
        if (
            not isinstance(cleaning, Mapping)
            or int(cleaning.get("schema_version") or 0) != 1
            or str(cleaning.get("selection_protocol") or "") != "exact-material-selection-v1"
            or not isinstance(output, Mapping)
            or not str(output.get("storage_source_id") or "").strip()
            or not str(output.get("object_key") or "").strip()
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable cleaning payload is incomplete",
                422,
            )
        return remote, cleaning

    @staticmethod
    def _clean_options(payload: Mapping[str, Any]) -> dict[str, Any]:
        from .cleaning import clean_options

        options = clean_options(payload.get("options") or {})
        options.pop("task_name", None)
        return options

    def _clean_selection_database(self, task):
        if self.task_artifacts is None:
            raise RemoteExecutionTransportError(
                "REMOTE_CLEANING_SELECTION_UNAVAILABLE",
                "cleaning task artifacts are unavailable",
                500,
            )
        path = self.task_artifacts.artifact_path(str(task.task_id), "selection.sqlite3")
        if not path.is_file():
            raise RemoteExecutionTransportError(
                "REMOTE_CLEANING_SELECTION_UNAVAILABLE",
                "frozen cleaning selection does not exist",
                409,
            )
        database = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        database.row_factory = sqlite3.Row
        frozen = database.execute(
            "SELECT value FROM meta WHERE key='frozen'"
        ).fetchone()
        if frozen is None:
            database.close()
            raise RemoteExecutionTransportError(
                "REMOTE_CLEANING_SELECTION_UNAVAILABLE",
                "cleaning selection is not frozen",
                409,
            )
        return database

    def _portable_clean_material(self, task, material: Mapping[str, Any]) -> dict[str, Any]:
        image_id = str(material.get("id") or "").strip()
        source_id = str(material.get("storage_source_id") or "").strip()
        object_key = str(material.get("object_key") or "").strip()
        digest = str(material.get("content_sha256") or "").strip().lower()
        try:
            size = int(material.get("size_bytes") or 0)
        except (TypeError, ValueError):
            size = 0
        if (
            not image_id
            or not source_id
            or not object_key
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or size <= 0
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_CLEANING_MATERIAL_EVIDENCE_INVALID",
                f"material {image_id or '<unknown>'} lacks portable object evidence",
                409,
            )
        source = self.storage_sources_factory().get(source_id)
        if source is None or not source.enabled:
            raise RemoteExecutionTransportError(
                "REMOTE_STORAGE_SOURCE_UNAVAILABLE",
                f"storage source {source_id or '<empty>'} is unavailable",
                409,
            )
        try:
            storage_type = StorageType.parse(source.type)
        except ValueError as error:
            raise RemoteExecutionTransportError(
                "REMOTE_STORAGE_NOT_PORTABLE",
                f"material {image_id} storage type is not portable",
                409,
            ) from error
        if storage_type not in {StorageType.OSS, StorageType.S3}:
            raise RemoteExecutionTransportError(
                "REMOTE_STORAGE_NOT_PORTABLE",
                f"material {image_id} is not stored in OSS/S3-compatible object storage",
                409,
            )
        return {
            "image_id": image_id,
            "file_name": Path(str(material.get("filename") or object_key)).name,
            "storage_source_id": source_id,
            "storage_type": storage_type.value,
            "object_key": object_key,
            "size_bytes": size,
            "etag": str(material.get("etag") or ""),
            "sha256": digest,
        }

    def clean_selection_page(
        self,
        task,
        payload: Mapping[str, Any],
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        self._clean_remote(task, payload)
        try:
            page_limit = max(1, min(500, int(limit)))
        except (TypeError, ValueError) as error:
            raise RemoteExecutionTransportError(
                "REMOTE_CLEANING_PAGE_INVALID",
                "cleaning selection page limit is invalid",
                422,
            ) from error
        after = str(cursor or "").strip()
        with closing(self._clean_selection_database(task)) as database:
            if after and database.execute(
                "SELECT 1 FROM selection WHERE image_id=?", (after,)
            ).fetchone() is None:
                raise RemoteExecutionTransportError(
                    "REMOTE_CLEANING_CURSOR_INVALID",
                    "cleaning selection cursor is not a selected image",
                    409,
                )
            total = int(database.execute("SELECT COUNT(*) FROM selection").fetchone()[0])
            if total > MAX_REMOTE_CLEAN_ITEMS:
                raise RemoteExecutionTransportError(
                    "REMOTE_CLEANING_SELECTION_TOO_LARGE",
                    "cleaning selection exceeds 250000 items",
                    413,
                )
            rows = database.execute(
                "SELECT image_id FROM selection WHERE image_id>? ORDER BY image_id LIMIT ?",
                (after, page_limit + 1),
            ).fetchall()
        ids = [str(row["image_id"]) for row in rows]
        has_more = len(ids) > page_limit
        page_ids = ids[:page_limit]
        materials = MaterialRepository(
            self.project_dir(str(task.project_id))
        ).get_many(page_ids)
        if len(materials) != len(page_ids):
            raise RemoteExecutionTransportError(
                "REMOTE_CLEANING_SELECTION_CHANGED",
                "one or more selected materials no longer exist",
                409,
            )
        items = [self._portable_clean_material(task, material) for material in materials]
        return {
            "items": items,
            "next_cursor": page_ids[-1] if has_more and page_ids else None,
            "total": total,
            "selection_protocol": "exact-material-selection-v1",
        }

    def clean_selection_read_contract(
        self,
        task,
        payload: Mapping[str, Any],
        *,
        image_id: str,
    ) -> dict[str, Any]:
        self._clean_remote(task, payload)
        key = str(image_id or "").strip()
        if not key:
            raise RemoteExecutionTransportError(
                "REMOTE_CLEANING_IMAGE_REQUIRED",
                "cleaning image_id is required",
                422,
            )
        with closing(self._clean_selection_database(task)) as database:
            selected = database.execute(
                "SELECT 1 FROM selection WHERE image_id=?", (key,)
            ).fetchone()
        if selected is None:
            raise RemoteExecutionTransportError(
                "REMOTE_CLEANING_IMAGE_NOT_SELECTED",
                "requested cleaning image is outside the frozen selection",
                403,
            )
        material = MaterialRepository(
            self.project_dir(str(task.project_id))
        ).get(key)
        if material is None:
            raise RemoteExecutionTransportError(
                "REMOTE_CLEANING_SELECTION_CHANGED",
                "selected material no longer exists",
                409,
            )
        ref = self._portable_clean_material(task, material)
        return {
            "image_id": key,
            "download": self._download_contract(
                str(task.project_id),
                {
                    "storage_source_id": ref["storage_source_id"],
                    "object_key": ref["object_key"],
                    "file_name": ref["file_name"],
                    "size_bytes": ref["size_bytes"],
                    "sha256": ref["sha256"],
                },
            ),
            "source": ref,
        }

    def _resolve_clean_execution_payload(
        self,
        task,
        payload: Mapping[str, Any],
        assignment: Mapping[str, Any],
    ) -> dict[str, Any]:
        _remote, cleaning = self._clean_remote(task, payload)
        output_ref = cleaning.get("output")
        assert isinstance(output_ref, Mapping)
        return {
            "schema_version": 1,
            "task_kind": "MATERIAL_BATCH",
            "transport": "object-storage-v1",
            "operation": "CLEAN",
            "selection": {
                "protocol": "exact-material-selection-v1",
                "page_size": 100,
            },
            "options": self._clean_options(payload),
            "output": {
                "type": "object",
                "storage_ref": {
                    "storage_source_id": str(output_ref.get("storage_source_id") or ""),
                    "object_key": str(output_ref.get("object_key") or ""),
                    "file_name": Path(str(output_ref.get("file_name") or "cleaning-review.jsonl")).name,
                    "content_type": str(output_ref.get("content_type") or "application/x-ndjson"),
                },
                "upload_protocol": "prepare-after-local-hash-v1",
            },
        }

    def _resolve_material_execution_payload(
        self,
        task,
        payload: Mapping[str, Any],
        assignment: Mapping[str, Any],
    ) -> dict[str, Any]:
        _remote, material = self._material_remote(task, payload)
        mode = str(material.get("mode") or "")
        output_ref = material.get("output")
        target = material.get("target")
        if not isinstance(output_ref, Mapping) or not isinstance(target, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable material output reference is incomplete",
                422,
            )
        target_prefix = str(target.get("target_prefix") or "").strip()
        common = {
            "schema_version": 1,
            "task_kind": "MATERIAL_IMPORT",
            "transport": "object-storage-v1",
            "mode": mode,
            "intent": str(material.get("intent") or ""),
            "import_format": str(material.get("import_format") or "images"),
            "dataset_yaml": str(material.get("dataset_yaml") or ""),
            "target": {
                "storage_source_id": str(target.get("storage_source_id") or ""),
                "storage_type": str(target.get("storage_type") or ""),
                "target_prefix": safe_member_path(target_prefix).as_posix() if target_prefix else "",
            },
            "output": {
                "type": "object",
                "storage_ref": {
                    "storage_source_id": str(output_ref.get("storage_source_id") or ""),
                    "object_key": str(output_ref.get("object_key") or ""),
                    "file_name": Path(str(output_ref.get("file_name") or "material-review.zip")).name,
                    "content_type": "application/zip",
                },
                "upload_protocol": "prepare-after-local-hash-v1",
            },
        }
        if mode == "storage_scan":
            source = self._material_scan_source(material)
            common["source"] = {
                "storage_source_id": str(source.get("storage_source_id") or ""),
                "storage_type": str(source.get("storage_type") or ""),
                "prefix": str(source.get("prefix") or ""),
                "recursive": bool(source.get("recursive", True)),
            }
            return common
        input_ref = material.get("input")
        if not isinstance(input_ref, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable material input reference is incomplete",
                422,
            )
        common["input"] = {
            "type": "object",
            "download": self._download_contract(
                str(task.project_id),
                input_ref,
                require_server_sha256=True,
            ),
        }
        return common

    @staticmethod
    def _training_remote(task, payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        if str(getattr(task.kind, "value", task.kind)) != "TRAINING":
            raise RemoteExecutionTransportError(
                "REMOTE_TASK_KIND_UNSUPPORTED",
                "portable training transport requires a TRAINING task",
                409,
            )
        remote = payload.get("remote_execution")
        if not isinstance(remote, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_MISSING",
                "portable remote training contract is missing",
                409,
            )
        if (
            int(remote.get("version") or 0) != 1
            or str(remote.get("task_kind") or "") != "TRAINING"
            or str(remote.get("transport") or "") != "object-storage-v1"
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable remote training contract is invalid",
                422,
            )
        training = remote.get("training")
        if not isinstance(training, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable remote training payload is missing",
                422,
            )
        training_schema = int(training.get("schema_version") or 0)
        if (
            training_schema not in {1, 2}
            or str(training.get("framework") or "") != "ultralytics"
            or not str(training.get("snapshot_id") or "").strip()
            or (
                training_schema >= 2
                and not str(training.get("dataset_revision_id") or "").strip()
            )
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable remote training payload identity is invalid",
                422,
            )
        if training_schema >= 2:
            _normalized_sha256(
                training.get("dataset_revision_id"),
                "training.dataset_revision_id",
            )
        return remote, training

    @staticmethod
    def _training_result_ref(training: Mapping[str, Any]) -> Mapping[str, Any]:
        result = training.get("result")
        if not isinstance(result, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable remote training result reference is missing",
                422,
            )
        if (
            not str(result.get("storage_source_id") or "").strip()
            or not str(result.get("object_key") or "").strip()
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable remote training result reference is incomplete",
                422,
            )
        return result

    def _resolve_training_execution_payload(
        self,
        task,
        payload: Mapping[str, Any],
        assignment: Mapping[str, Any],
    ) -> dict[str, Any]:
        _remote, training = self._training_remote(task, payload)
        bundle = training.get("bundle")
        model_ref = training.get("model")
        result_ref = self._training_result_ref(training)
        if not isinstance(bundle, Mapping) or not isinstance(model_ref, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable remote training bundle/model references are incomplete",
                422,
            )
        bundle_download = self._download_contract(
            str(task.project_id),
            bundle,
            require_server_sha256=True,
        )
        bundle_download.update({
            "uncompressed_size_bytes": _positive_int(
                bundle.get("uncompressed_size_bytes"),
                "training.bundle.uncompressed_size_bytes",
            ),
            "member_count": _positive_int(
                bundle.get("member_count"),
                "training.bundle.member_count",
            ),
            "snapshot_id": str(training.get("snapshot_id") or ""),
        })

        model_type = str(model_ref.get("type") or "").strip()
        if model_type == "official":
            reference = str(model_ref.get("reference") or "").strip()
            canonical = next(
                (
                    item
                    for item in OFFICIAL_DOWNLOADABLE_MODELS
                    if str(item).casefold() == reference.casefold()
                ),
                None,
            )
            if (
                canonical is None
                or Path(reference).is_absolute()
                or "/" in reference
                or "\\" in reference
            ):
                raise RemoteExecutionTransportError(
                    "REMOTE_MODEL_REFERENCE_INVALID",
                    "remote training official model reference is not allow-listed",
                    422,
                )
            model = {
                "type": "official",
                "reference": str(canonical),
                "base_selection_reason": str(model_ref.get("base_selection_reason") or "mother_model"),
            }
        elif model_type == "object":
            model = {
                "type": "object",
                "download": self._download_contract(
                    str(task.project_id),
                    model_ref,
                    require_server_sha256=True,
                ),
                "artifact_id": str(model_ref.get("artifact_id") or ""),
                "base_version_id": str(model_ref.get("base_version_id") or ""),
                "base_version_name": str(model_ref.get("base_version_name") or ""),
                "base_selection_reason": str(model_ref.get("base_selection_reason") or ""),
            }
        else:
            raise RemoteExecutionTransportError(
                "REMOTE_MODEL_REFERENCE_INVALID",
                "remote training model reference is unsupported",
                422,
            )

        resolved = assignment.get("resolved_execution_config")
        selected_device = ""
        selected_gpu = None
        if isinstance(resolved, Mapping):
            selected_device = str(resolved.get("selected_device") or "")
            selected_gpu = resolved.get("selected_gpu")
        if not selected_device:
            raise RemoteExecutionTransportError(
                "REMOTE_TRAINING_DEVICE_MISSING",
                "remote training assignment has no concrete selected device",
                409,
            )

        params = training.get("params")
        if not isinstance(params, Mapping):
            params = {}
        safe_params = {
            str(key): value
            for key, value in params.items()
            if value is None or isinstance(value, (str, int, float, bool))
        }
        return {
            "schema_version": 1,
            "task_kind": "TRAINING",
            "transport": "object-storage-v1",
            "framework": "ultralytics",
            "algorithm_id": str(payload.get("algorithm_asset_id") or ""),
            "snapshot_id": str(training.get("snapshot_id") or ""),
            "dataset_revision_id": str(training.get("dataset_revision_id") or ""),
            "requested_device": str(payload.get("requested_device") or payload.get("device") or "auto"),
            "selected_device": selected_device,
            "selected_gpu": dict(selected_gpu) if isinstance(selected_gpu, Mapping) else None,
            "bundle": {
                "type": "object",
                "download": bundle_download,
            },
            "model": model,
            "params": safe_params,
            "counts": dict(training.get("counts") or {}) if isinstance(training.get("counts"), Mapping) else {},
            "result": {
                "type": "object",
                "storage_ref": {
                    "storage_source_id": str(result_ref.get("storage_source_id") or ""),
                    "object_key": str(result_ref.get("object_key") or ""),
                    "file_name": Path(str(result_ref.get("file_name") or "training-result.zip")).name,
                    "content_type": str(result_ref.get("content_type") or "application/zip"),
                },
                "upload_protocol": "prepare-after-local-hash-v1",
            },
        }

    def _prepare_training_result_upload(
        self,
        task,
        payload: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        _remote, training = self._training_remote(task, payload)
        output_ref = self._training_result_ref(training)
        expected_sha = _normalized_sha256(evidence.get("sha256"), "result.sha256")
        expected_size = _positive_int(evidence.get("size_bytes"), "result.size_bytes")
        storage_ref = self._execution_output_ref(output_ref, evidence)
        storage_ref["content_type"] = "application/zip"
        storage_ref["file_name"] = "training-result.zip"
        _source, provider = self._source_provider(str(task.project_id), storage_ref)
        object_key = str(storage_ref["object_key"])
        if provider.exists(object_key):
            metadata = provider.stat(object_key)
            actual_sha = str(metadata.sha256 or "").strip().lower()
            if int(metadata.size_bytes) != expected_size or actual_sha != expected_sha:
                raise RemoteExecutionTransportError(
                    "REMOTE_RESULT_OBJECT_CONFLICT",
                    "remote training result object already exists with different or unverifiable evidence",
                    409,
                )
            return {
                "already_uploaded": True,
                "storage_ref": storage_ref,
                "sha256": expected_sha,
                "size_bytes": expected_size,
                "upload": None,
            }
        return {
            "already_uploaded": False,
            "storage_ref": storage_ref,
            "sha256": expected_sha,
            "size_bytes": expected_size,
            "upload": self._upload_contract(
                str(task.project_id),
                storage_ref,
                sha256=expected_sha,
                size_bytes=expected_size,
            ),
        }

    @staticmethod
    def _remote_training_version_id(task_id: str, generation: int, snapshot_id: str) -> str:
        return "rt" + hashlib.sha256(
            f"{task_id}:{int(generation)}:{snapshot_id}".encode("utf-8")
        ).hexdigest()[:10]

    def _normalized_training_model_evidence(self, models: object) -> list[dict[str, Any]]:
        if not isinstance(models, (list, tuple)) or not models or len(models) > 4:
            raise RemoteExecutionTransportError(
                "REMOTE_TRAINING_MODELS_INVALID",
                "remote training model evidence must contain 1-4 model entries",
                422,
            )
        result: list[dict[str, Any]] = []
        seen_roles: set[str] = set()
        for item in models:
            if not isinstance(item, Mapping):
                raise RemoteExecutionTransportError(
                    "REMOTE_TRAINING_MODELS_INVALID",
                    "remote training model evidence entry must be an object",
                    422,
                )
            role = str(item.get("role") or "").strip().lower()
            if role not in {"best", "last"} or role in seen_roles:
                raise RemoteExecutionTransportError(
                    "REMOTE_TRAINING_MODELS_INVALID",
                    "remote training model roles must be unique best/last entries",
                    422,
                )
            seen_roles.add(role)
            digest = _normalized_sha256(
                item.get("sha256"),
                f"training.models.{role}.sha256",
            )
            size = _positive_int(
                item.get("size_bytes"),
                f"training.models.{role}.size_bytes",
            )
            raw_file_name = str(item.get("file_name") or f"{role}.pt")
            file_name = Path(raw_file_name).name
            if (
                not file_name
                or file_name in {".", ".."}
                or "/" in raw_file_name
                or "\\" in raw_file_name
                or Path(file_name).suffix.lower() != ".pt"
            ):
                raise RemoteExecutionTransportError(
                    "REMOTE_TRAINING_MODELS_INVALID",
                    "remote training model file_name must be a .pt basename",
                    422,
                )
            result.append({
                "role": role,
                "file_name": file_name,
                "sha256": digest,
                "size_bytes": size,
            })
        return result

    def _training_model_storage_ref(
        self,
        *,
        task,
        payload: Mapping[str, Any],
        generation: int,
        model: Mapping[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        _remote, training = self._training_remote(task, payload)
        algorithm_id = str(payload.get("algorithm_asset_id") or "").strip()
        if not algorithm_id:
            raise RemoteExecutionTransportError(
                "REMOTE_TRAINING_ALGORITHM_MISSING",
                "remote training payload has no algorithm id",
                422,
            )
        snapshot_id = str(training.get("snapshot_id") or "").strip()
        version_id = self._remote_training_version_id(
            str(task.task_id),
            int(generation),
            snapshot_id,
        )
        config = self.model_artifacts.repository.config()
        source_id = str(config.get("storage_source_id") or "").strip()
        if not source_id:
            raise RemoteExecutionTransportError(
                "REMOTE_TRAINING_MODEL_STORAGE_REQUIRED",
                "unified model artifact storage is not configured",
                409,
            )
        source = self.storage_sources_factory().get(source_id)
        if source is None or not source.enabled:
            raise RemoteExecutionTransportError(
                "REMOTE_TRAINING_MODEL_STORAGE_UNAVAILABLE",
                "unified model artifact storage source is unavailable",
                409,
            )
        try:
            storage_type = StorageType.parse(source.type)
        except ValueError as error:
            raise RemoteExecutionTransportError(
                "REMOTE_TRAINING_MODEL_STORAGE_UNAVAILABLE",
                "unified model artifact storage type is invalid",
                409,
            ) from error
        if storage_type not in {StorageType.OSS, StorageType.S3}:
            raise RemoteExecutionTransportError(
                "REMOTE_TRAINING_MODEL_STORAGE_NOT_PORTABLE",
                "remote training models require OSS/S3/MinIO object storage",
                409,
            )
        role = str(model["role"])
        digest = str(model["sha256"])
        file_name = Path(str(model["file_name"])).name
        object_key = build_artifact_object_key(
            root_prefix=str(config.get("root_prefix") or config.get("object_prefix") or "changlian-ai/artifacts"),
            project_id=task.project_id,
            algorithm_id=algorithm_id,
            version_id=version_id,
            target="training",
            sha256=digest,
            file_name=file_name,
        )
        artifact_id = hashlib.sha256(
            f"{task.project_id}:{algorithm_id}:{version_id}:{role}:{digest}".encode("utf-8")
        ).hexdigest()[:32]
        return version_id, {
            "artifact_id": artifact_id,
            "storage_source_id": source_id,
            "object_key": object_key,
            "file_name": file_name,
            "content_type": "application/octet-stream",
            "role": role,
            "sha256": digest,
            "size_bytes": int(model["size_bytes"]),
        }

    def prepare_training_model_uploads(
        self,
        task,
        payload: Mapping[str, Any],
        *,
        execution_generation: int,
        models: object,
    ) -> dict[str, Any]:
        self._training_remote(task, payload)
        generation = _positive_int(
            execution_generation,
            "training.execution_generation",
        )
        normalized = self._normalized_training_model_evidence(models)
        items = []
        version_id = ""
        for model in normalized:
            version_id, storage_ref = self._training_model_storage_ref(
                task=task,
                payload=payload,
                generation=generation,
                model=model,
            )
            _source, provider = self._source_provider(str(task.project_id), storage_ref)
            object_key = str(storage_ref["object_key"])
            if provider.exists(object_key):
                metadata = provider.stat(object_key)
                actual_sha = str(metadata.sha256 or "").strip().lower()
                if (
                    int(metadata.size_bytes) != int(model["size_bytes"])
                    or actual_sha != str(model["sha256"])
                ):
                    raise RemoteExecutionTransportError(
                        "REMOTE_TRAINING_MODEL_OBJECT_CONFLICT",
                        "remote training model object already exists with different or unverifiable evidence",
                        409,
                    )
                upload = None
                already_uploaded = True
            else:
                upload = self._upload_contract(
                    str(task.project_id),
                    storage_ref,
                    sha256=str(model["sha256"]),
                    size_bytes=int(model["size_bytes"]),
                )
                already_uploaded = False
            items.append({
                **dict(model),
                "artifact_id": str(storage_ref["artifact_id"]),
                "storage_ref": {
                    key: value
                    for key, value in storage_ref.items()
                    if key not in {"artifact_id", "sha256", "size_bytes", "role"}
                },
                "already_uploaded": already_uploaded,
                "upload": upload,
            })
        return {
            "version_id": version_id,
            "execution_generation": generation,
            "items": items,
        }

    def confirm_training_model_uploads(
        self,
        task,
        payload: Mapping[str, Any],
        *,
        execution_generation: int,
        models: object,
    ) -> dict[str, Any]:
        self._training_remote(task, payload)
        generation = _positive_int(
            execution_generation,
            "training.execution_generation",
        )
        normalized = self._normalized_training_model_evidence(models)
        items = []
        version_id = ""
        for model in normalized:
            version_id, storage_ref = self._training_model_storage_ref(
                task=task,
                payload=payload,
                generation=generation,
                model=model,
            )
            _source, provider = self._source_provider(str(task.project_id), storage_ref)
            object_key = str(storage_ref["object_key"])
            if not provider.exists(object_key):
                raise RemoteExecutionTransportError(
                    "REMOTE_TRAINING_MODEL_NOT_UPLOADED",
                    f"remote training {model['role']} model object does not exist",
                    409,
                )
            metadata = provider.stat(object_key)
            actual_sha = str(metadata.sha256 or "").strip().lower()
            if (
                int(metadata.size_bytes) != int(model["size_bytes"])
                or not actual_sha
                or actual_sha != str(model["sha256"])
            ):
                raise RemoteExecutionTransportError(
                    "REMOTE_TRAINING_MODEL_EVIDENCE_MISMATCH",
                    f"remote training {model['role']} model does not match prepared size/SHA256 evidence",
                    409,
                )
            items.append({
                **dict(model),
                "artifact_id": str(storage_ref["artifact_id"]),
                "storage_ref": {
                    key: value
                    for key, value in storage_ref.items()
                    if key not in {"artifact_id", "sha256", "size_bytes", "role"}
                },
            })
        return {
            "version_id": version_id,
            "execution_generation": generation,
            "confirmed": True,
            "items": items,
        }

    def _training_result_stage_root(self, task_id: str, generation: int) -> Path:
        return (
            self.data_dir
            / "task_runtime"
            / "remote-training-results"
            / _safe_segment(task_id, "task")
            / f"generation-{int(generation)}"
        ).resolve()

    def _confirm_training_result_upload(
        self,
        task,
        payload: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        _remote, training = self._training_remote(task, payload)
        output_ref = self._training_result_ref(training)
        expected_sha = _normalized_sha256(evidence.get("sha256"), "result.sha256")
        expected_size = _positive_int(evidence.get("size_bytes"), "result.size_bytes")
        generation = _positive_int(
            evidence.get("execution_generation"),
            "result.execution_generation",
        )
        storage_ref = self._execution_output_ref(output_ref, evidence)
        storage_ref["content_type"] = "application/zip"
        storage_ref["file_name"] = "training-result.zip"
        _source, provider = self._source_provider(str(task.project_id), storage_ref)
        object_key = str(storage_ref["object_key"])
        if not provider.exists(object_key):
            raise RemoteExecutionTransportError(
                "REMOTE_RESULT_NOT_UPLOADED",
                "remote training result object does not exist",
                409,
            )
        metadata = provider.stat(object_key)
        actual_sha = str(metadata.sha256 or "").strip().lower()
        if (
            int(metadata.size_bytes) != expected_size
            or not actual_sha
            or actual_sha != expected_sha
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_RESULT_EVIDENCE_MISMATCH",
                "remote training result object does not match prepared size/SHA256 evidence",
                409,
            )

        stage = self._training_result_stage_root(str(task.task_id), generation)
        stage.parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(stage) + ".lock", timeout=60)
        try:
            with lock:
                archive = stage.parent / f"generation-{generation}.zip"
                extracted = stage / "verified"
                shutil.rmtree(stage, ignore_errors=True)
                stage.mkdir(parents=True, exist_ok=True)
                archive.unlink(missing_ok=True)
                downloaded = provider.download(object_key, archive)
                downloaded_sha = str(downloaded.sha256 or "").strip().lower()
                if (
                    int(downloaded.size_bytes) != expected_size
                    or (downloaded_sha and downloaded_sha != expected_sha)
                ):
                    raise RemoteExecutionTransportError(
                        "REMOTE_RESULT_DOWNLOAD_CHANGED",
                        "downloaded training result no longer matches object evidence",
                        409,
                    )
                try:
                    verified = verify_training_result_archive(
                        archive,
                        extracted,
                        expected_sha256=expected_sha,
                        expected_size_bytes=expected_size,
                        expected_task_id=str(task.task_id),
                        expected_execution_generation=generation,
                        expected_snapshot_id=str(training.get("snapshot_id") or ""),
                        allow_separate_model_objects=True,
                    )
                except RemoteTrainingResultError as error:
                    raise RemoteExecutionTransportError(
                        error.code,
                        str(error),
                        error.status_code,
                    ) from error
                (stage / "verified.json").write_text(
                    json.dumps(
                        {
                            "sha256": expected_sha,
                            "size_bytes": expected_size,
                            "snapshot_id": str(training.get("snapshot_id") or ""),
                            "dataset_revision_id": str(training.get("dataset_revision_id") or ""),
                            "model_count": len(verified.models),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
        except Timeout as error:
            raise RemoteExecutionTransportError(
                "REMOTE_RESULT_VERIFY_BUSY",
                "training result verification is already in progress",
                409,
            ) from error

        manifest = dict(verified.manifest)
        return {
            "result_ref": "result.json",
            "result": {
                "task_id": str(task.task_id),
                "project_id": str(task.project_id),
                "remote_execution": True,
                "transport": "object-storage-v1",
                "framework": "ultralytics",
                "snapshot_id": str(training.get("snapshot_id") or ""),
                "dataset_revision_id": str(training.get("dataset_revision_id") or ""),
                "training_outcome": str(manifest.get("training_outcome") or ""),
                "completion": dict(manifest.get("completion") or {}) if isinstance(manifest.get("completion"), Mapping) else {},
                "training_report": dict(manifest.get("training_report") or {}) if isinstance(manifest.get("training_report"), Mapping) else {},
                "verified_models": [dict(item) for item in verified.models],
                "output_storage": storage_ref,
                "runtime_log_ref": str(getattr(task, "log_ref", "") or ""),
                "recovered_from_completed_work": False,
            },
        }

    @staticmethod
    def _execution_output_ref(
        output_ref: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        generation = _positive_int(
            evidence.get("execution_generation"),
            "result.execution_generation",
        )
        base_key = str(output_ref.get("object_key") or "").strip()
        if not base_key:
            raise RemoteExecutionTransportError(
                "REMOTE_OBJECT_CONTRACT_INVALID",
                "output object reference is incomplete",
                422,
            )
        path = Path(base_key.replace("\\", "/"))
        parent = path.parent.as_posix().strip(".")
        file_name = Path(str(output_ref.get("file_name") or path.name or "result.jpg")).name
        object_key = "/".join(
            part
            for part in (parent, f"generation-{generation}", file_name)
            if part
        )
        return {
            "storage_source_id": str(output_ref.get("storage_source_id") or ""),
            "object_key": object_key,
            "file_name": file_name,
            "content_type": str(output_ref.get("content_type") or "image/jpeg"),
        }

    def prepare_result_upload(
        self,
        task,
        payload: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        kind = str(getattr(task.kind, "value", task.kind))
        if kind == "TRAINING":
            return self._prepare_training_result_upload(task, payload, evidence)
        if kind == "MODEL_CONVERSION":
            _remote, conversion = self._conversion_remote(task, payload)
            output_ref = conversion.get("output")
        elif kind == "MATERIAL_IMPORT":
            _remote, material = self._material_remote(task, payload)
            output_ref = material.get("output")
        elif kind == "MATERIAL_BATCH":
            _remote, cleaning = self._clean_remote(task, payload)
            output_ref = cleaning.get("output")
        else:
            _remote, deployment = self._deployment_remote(task, payload)
            output_ref = deployment.get("output")
        if not isinstance(output_ref, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable deployment output reference is missing",
                422,
            )
        expected_sha = _normalized_sha256(evidence.get("sha256"), "result.sha256")
        expected_size = _positive_int(evidence.get("size_bytes"), "result.size_bytes")
        storage_ref = self._execution_output_ref(output_ref, evidence)
        _source, provider = self._source_provider(str(task.project_id), storage_ref)
        object_key = str(storage_ref["object_key"])
        if provider.exists(object_key):
            metadata = provider.stat(object_key)
            actual_sha = str(metadata.sha256 or "").strip().lower()
            if int(metadata.size_bytes) != expected_size or actual_sha != expected_sha:
                raise RemoteExecutionTransportError(
                    "REMOTE_RESULT_OBJECT_CONFLICT",
                    "remote result object already exists with different or unverifiable content evidence",
                    409,
                )
            return {
                "already_uploaded": True,
                "storage_ref": storage_ref,
                "sha256": expected_sha,
                "size_bytes": expected_size,
                "upload": None,
            }

        return {
            "already_uploaded": False,
            "storage_ref": storage_ref,
            "sha256": expected_sha,
            "size_bytes": expected_size,
            "upload": self._upload_contract(
                str(task.project_id),
                storage_ref,
                sha256=expected_sha,
                size_bytes=expected_size,
            ),
        }

    def confirm_result_upload(
        self,
        task,
        payload: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        kind = str(getattr(task.kind, "value", task.kind))
        if kind == "TRAINING":
            return self._confirm_training_result_upload(task, payload, evidence)
        conversion = None
        material = None
        cleaning = None
        if kind == "MODEL_CONVERSION":
            _remote, conversion = self._conversion_remote(task, payload)
            output_ref = conversion.get("output")
        elif kind == "MATERIAL_IMPORT":
            _remote, material = self._material_remote(task, payload)
            output_ref = material.get("output")
        elif kind == "MATERIAL_BATCH":
            _remote, cleaning = self._clean_remote(task, payload)
            output_ref = cleaning.get("output")
        else:
            _remote, deployment = self._deployment_remote(task, payload)
            output_ref = deployment.get("output")
        if not isinstance(output_ref, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable deployment output reference is missing",
                422,
            )
        expected_sha = _normalized_sha256(evidence.get("sha256"), "result.sha256")
        expected_size = _positive_int(evidence.get("size_bytes"), "result.size_bytes")
        storage_ref = self._execution_output_ref(output_ref, evidence)
        _source, provider = self._source_provider(str(task.project_id), storage_ref)
        object_key = str(storage_ref["object_key"])
        if not provider.exists(object_key):
            raise RemoteExecutionTransportError(
                "REMOTE_RESULT_NOT_UPLOADED",
                "remote result object does not exist",
                409,
            )
        metadata = provider.stat(object_key)
        actual_sha = str(metadata.sha256 or "").strip().lower()
        if int(metadata.size_bytes) != expected_size:
            raise RemoteExecutionTransportError(
                "REMOTE_RESULT_SIZE_MISMATCH",
                "remote result size does not match prepared execution evidence",
                409,
            )
        if not actual_sha:
            raise RemoteExecutionTransportError(
                "REMOTE_RESULT_HASH_UNVERIFIED",
                "remote result object is missing signed sha256 metadata",
                409,
            )
        if actual_sha != expected_sha:
            raise RemoteExecutionTransportError(
                "REMOTE_RESULT_HASH_MISMATCH",
                "remote result sha256 does not match prepared execution evidence",
                409,
            )

        result = {
            "task_id": str(task.task_id),
            "project_id": str(task.project_id),
            "remote_execution": True,
            "transport": "object-storage-v1",
            "output_storage": storage_ref,
            "output_size_bytes": expected_size,
            "output_sha256": expected_sha,
            "runtime_log_ref": str(getattr(task, "log_ref", "") or ""),
            "recovered_from_completed_work": False,
        }
        if kind == "MODEL_CONVERSION" and isinstance(conversion, Mapping):
            result.update({
                "target": str(conversion.get("target") or "onnx"),
                "source_trace": dict(conversion.get("source_trace") or {})
                if isinstance(conversion.get("source_trace"), Mapping)
                else {},
                "params": self._portable_conversion_params(
                    str(conversion.get("target") or ""),
                    conversion.get("params") if isinstance(conversion.get("params"), Mapping) else {},
                ),
                "runtime_verified": str(conversion.get("target") or "") == "onnx",
            })
        elif kind == "MATERIAL_IMPORT" and isinstance(material, Mapping):
            target = material.get("target")
            target = dict(target) if isinstance(target, Mapping) else {}
            result.update({
                "mode": str(material.get("mode") or "zip_scan"),
                "intent": str(material.get("intent") or ""),
                "import_format": str(material.get("import_format") or "images"),
                "dataset_yaml": str(material.get("dataset_yaml") or ""),
                "target": {
                    "storage_source_id": str(target.get("storage_source_id") or ""),
                    "storage_type": str(target.get("storage_type") or ""),
                    "target_prefix": str(target.get("target_prefix") or ""),
                },
                "review_verified": True,
            })
        elif kind == "MATERIAL_BATCH" and isinstance(cleaning, Mapping):
            result.update({
                "operation": "CLEAN",
                "selection_protocol": str(cleaning.get("selection_protocol") or ""),
                "review_verified": True,
            })
        else:
            result.update({
                "framework": str(deployment.get("framework") or "ultralytics"),
                "runtime_format": str(deployment.get("runtime_format") or ""),
                "confidence": max(0.0, min(1.0, float(deployment.get("confidence") or 0.25))),
            })
        return {"result_ref": "result.json", "result": result}

    def _commit_training_result(
        self,
        task,
        payload: Mapping[str, Any],
        evidence: Mapping[str, Any],
        confirmed: Mapping[str, Any],
    ) -> dict[str, Any]:
        _remote, training = self._training_remote(task, payload)
        generation = _positive_int(
            evidence.get("execution_generation"),
            "result.execution_generation",
        )
        result = confirmed.get("result")
        if not isinstance(result, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_RESULT_CONFIRM_INVALID",
                "verified training result metadata is missing",
                500,
            )
        stage = self._training_result_stage_root(str(task.task_id), generation)
        extracted = stage / "verified"
        marker = stage / "verified.json"
        if not marker.is_file() or not extracted.is_dir():
            raise RemoteExecutionTransportError(
                "REMOTE_TRAINING_RESULT_STAGE_MISSING",
                "verified training result staging is missing before commit",
                409,
            )

        project = self.project_dir(str(task.project_id)).resolve()
        models_root = (project / "models").resolve()
        models_root.mkdir(parents=True, exist_ok=True)
        algorithms = list_algorithms(self.algorithms_file(str(task.project_id)))
        algorithm_id = str(payload.get("algorithm_asset_id") or "").strip()
        algorithm = next(
            (row for row in algorithms if str(row.get("id") or "") == algorithm_id),
            None,
        )
        if algorithm is None:
            raise RemoteExecutionTransportError(
                "REMOTE_TRAINING_ALGORITHM_MISSING",
                "training algorithm no longer exists at commit time",
                409,
            )

        model_contract = training.get("model")
        if not isinstance(model_contract, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "training base model contract is missing at commit time",
                422,
            )
        expected_base_id = str(model_contract.get("base_version_id") or "").strip()
        current_base_id = str(resolve_current_version_id(algorithm, framework="ultralytics") or "")
        if expected_base_id:
            if current_base_id != expected_base_id:
                raise RemoteExecutionTransportError(
                    "REMOTE_TRAINING_BASE_VERSION_STALE",
                    "algorithm current version changed while remote training was running",
                    409,
                )
        elif current_base_id:
            raise RemoteExecutionTransportError(
                "REMOTE_TRAINING_BASE_VERSION_STALE",
                "algorithm gained a newer current version while first-run remote training was running",
                409,
            )

        version_id = "rt" + hashlib.sha256(
            f"{task.task_id}:{generation}:{training.get('snapshot_id')}".encode("utf-8")
        ).hexdigest()[:10]
        existing_version = next(
            (
                row
                for row in (algorithm.get("versions") or [])
                if str(row.get("id") or "") == version_id
            ),
            None,
        )
        if existing_version is not None:
            durable_analysis_id = str(payload.get("external_analysis_id") or "").strip()
            if durable_analysis_id and not str(existing_version.get("external_analysis_id") or "").strip():
                existing_version = update_algorithm_version(
                    self.algorithms_file(str(task.project_id)),
                    algorithm_id,
                    version_id,
                    {"external_analysis_id": durable_analysis_id},
                    now=str(getattr(task, "updated_at", "") or datetime.now(timezone.utc).isoformat()),
                )
            return {
                "algorithm_id": algorithm_id,
                "version_id": version_id,
                "version_name": str(existing_version.get("version_name") or ""),
                "model_artifacts_committed": True,
            }

        verified_models = result.get("verified_models")
        training_models = confirmed.get("training_models")
        if (
            not isinstance(verified_models, list)
            or not verified_models
            or not isinstance(training_models, Mapping)
            or str(training_models.get("version_id") or "") != version_id
            or not isinstance(training_models.get("models"), list)
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_TRAINING_MODEL_MISSING",
                "verified training result has no confirmed model artifact uploads",
                409,
            )
        uploaded_models = list(training_models["models"])
        by_role = {
            str(item.get("role") or "").strip().lower(): item
            for item in uploaded_models
            if isinstance(item, Mapping)
        }
        primary_role = "best" if "best" in by_role else "last" if "last" in by_role else ""
        if not primary_role:
            raise RemoteExecutionTransportError(
                "REMOTE_TRAINING_PRIMARY_MODEL_MISSING",
                "confirmed remote training artifacts contain no best/last model",
                409,
            )
        primary_item = by_role[primary_role]
        primary_storage = primary_item.get("storage_ref")
        if not isinstance(primary_storage, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_TRAINING_MODEL_STORAGE_INVALID",
                "primary remote training model storage reference is invalid",
                409,
            )
        primary_sha = _normalized_sha256(
            primary_item.get("sha256"),
            "training.primary.sha256",
        )
        primary_size = _positive_int(
            primary_item.get("size_bytes"),
            "training.primary.size_bytes",
        )
        suffix = Path(str(primary_item.get("file_name") or "model.pt")).suffix.lower() or ".pt"
        primary_path = (
            models_root
            / f"remote_{_safe_segment(task.task_id, 'task')}_g{generation}_{primary_role}_{primary_sha[:12]}{suffix}"
        ).resolve()
        if models_root not in primary_path.parents:
            raise RemoteExecutionTransportError(
                "REMOTE_TRAINING_MODEL_DESTINATION_INVALID",
                "training model destination escaped project model directory",
                500,
            )
        if primary_path.exists():
            if (
                not primary_path.is_file()
                or int(primary_path.stat().st_size) != primary_size
                or _sha256(primary_path) != primary_sha
            ):
                raise RemoteExecutionTransportError(
                    "REMOTE_TRAINING_MODEL_CONFLICT",
                    "existing primary training model path has different content",
                    409,
                )
        else:
            _source, provider = self._source_provider(
                str(task.project_id),
                primary_storage,
            )
            object_key = str(primary_storage.get("object_key") or "")
            temporary = primary_path.with_name(f".{primary_path.name}.{version_id}.tmp")
            temporary.unlink(missing_ok=True)
            try:
                downloaded = provider.download(object_key, temporary)
                downloaded_sha = str(downloaded.sha256 or "").strip().lower()
                if (
                    int(downloaded.size_bytes) != primary_size
                    or (downloaded_sha and downloaded_sha != primary_sha)
                    or int(temporary.stat().st_size) != primary_size
                    or _sha256(temporary) != primary_sha
                ):
                    raise RemoteExecutionTransportError(
                        "REMOTE_TRAINING_PRIMARY_MODEL_DOWNLOAD_CHANGED",
                        "downloaded primary training model failed size/SHA256 verification",
                        409,
                    )
                temporary.replace(primary_path)
            finally:
                temporary.unlink(missing_ok=True)

        committed_models: list[dict[str, Any]] = []
        artifact_rows: list[dict[str, Any]] = []
        for item in uploaded_models:
            if not isinstance(item, Mapping):
                raise RemoteExecutionTransportError(
                    "REMOTE_TRAINING_MODEL_INVALID",
                    "confirmed model artifact metadata is invalid",
                    422,
                )
            role = str(item.get("role") or "").strip().lower()
            digest = _normalized_sha256(
                item.get("sha256"),
                f"training.models.{role}.sha256",
            )
            size = _positive_int(
                item.get("size_bytes"),
                f"training.models.{role}.size_bytes",
            )
            storage_ref = item.get("storage_ref")
            if not isinstance(storage_ref, Mapping):
                raise RemoteExecutionTransportError(
                    "REMOTE_TRAINING_MODEL_STORAGE_INVALID",
                    "confirmed model artifact storage reference is invalid",
                    422,
                )
            local_path = str(primary_path) if role == primary_role else ""
            try:
                artifact_row = self.model_artifacts.register_verified_remote_artifact(
                    project_id=str(task.project_id),
                    algorithm_id=algorithm_id,
                    version_id=version_id,
                    target=role,
                    file_name=str(item.get("file_name") or f"{role}.pt"),
                    sha256=digest,
                    size_bytes=size,
                    storage_source_id=str(storage_ref.get("storage_source_id") or ""),
                    object_key=str(storage_ref.get("object_key") or ""),
                    source_path=local_path,
                    artifact_kind="original",
                    metadata={
                        "remote_training": True,
                        "task_id": str(task.task_id),
                        "execution_generation": generation,
                        "snapshot_id": str(training.get("snapshot_id") or ""),
                        "dataset_revision_id": str(training.get("dataset_revision_id") or ""),
                        "role": role,
                    },
                )
            except Exception as error:
                raise RemoteExecutionTransportError(
                    str(getattr(error, "code", "") or "REMOTE_TRAINING_MODEL_ASSET_COMMIT_FAILED"),
                    str(error),
                    int(getattr(error, "status_code", 409) or 409),
                ) from error
            artifact_rows.append(artifact_row)
            committed_models.append({
                "role": role,
                "path": local_path,
                "sha256": digest,
                "size_bytes": size,
                "artifact_id": str(artifact_row.get("artifact_id") or item.get("artifact_id") or ""),
                "storage_source_id": str(artifact_row.get("storage_source_id") or ""),
                "object_key": str(artifact_row.get("object_key") or ""),
            })

        best_path = str(primary_path) if primary_role == "best" else ""
        last_path = str(primary_path) if primary_role == "last" else ""
        primary = str(primary_path)
        report = result.get("training_report")
        report = dict(report) if isinstance(report, Mapping) else {}
        completion = result.get("completion")
        completion = dict(completion) if isinstance(completion, Mapping) else {}
        test_result = report.get("test_result")
        partial = (
            isinstance(test_result, Mapping)
            and str(test_result.get("status") or "").strip().lower() == "failed"
        )
        finished_at = str(completion.get("finished_at") or "")
        if not finished_at:
            finished_at = str(getattr(task, "updated_at", "") or "")
        version_name = f"remote-g{generation}-{version_id[-6:]}"
        base_model_name = str(model_contract.get("reference") or "")
        if not base_model_name:
            download = model_contract.get("download")
            if isinstance(download, Mapping):
                base_model_name = str(download.get("file_name") or "")
        worker_id = str(getattr(task, "worker_id", "") or "")
        selected_gpu = result.get("selected_gpu")
        selected_gpu = dict(selected_gpu) if isinstance(selected_gpu, Mapping) else {}
        actual_params = report.get("configuration")
        actual_params = dict(actual_params) if isinstance(actual_params, Mapping) else {}
        primary_model = next(
            (item for item in committed_models if str(item.get("role") or "") == primary_role),
            committed_models[0] if committed_models else {},
        )
        snapshot_truth = {}
        dataset_manifest = {}
        if self.task_artifacts is not None:
            snapshot_value = self.task_artifacts.read_json(
                str(task.task_id), "snapshot.json", default={},
            )
            manifest_value = self.task_artifacts.read_json(
                str(task.task_id), "work/bundle/manifest.json", default={},
            )
            snapshot_truth = snapshot_value if isinstance(snapshot_value, dict) else {}
            dataset_manifest = manifest_value if isinstance(manifest_value, dict) else {}
        benchmark_scope = build_evaluation_benchmark_scope(
            snapshot_truth or None,
            dataset_manifest=dataset_manifest or None,
        )
        evaluation = build_evaluation_truth(
            report.get("test_result") if isinstance(report.get("test_result"), Mapping) else {},
            task_id=str(task.task_id),
            snapshot_id=str(training.get("snapshot_id") or ""),
            dataset_revision_id=str(training.get("dataset_revision_id") or ""),
            model_sha256=str(primary_model.get("sha256") or ""),
            finished_at=finished_at,
            benchmark_scope=benchmark_scope,
        )
        training_lineage = build_training_lineage(
            task_id=str(task.task_id),
            snapshot_id=str(training.get("snapshot_id") or ""),
            dataset_revision_id=str(training.get("dataset_revision_id") or ""),
            framework="ultralytics",
            base_version_id=expected_base_id,
            base_version_name=model_contract.get("base_version_name"),
            base_model=base_model_name,
            base_selection_reason=model_contract.get("base_selection_reason"),
            execution={
                "mode": "agent",
                "worker_id": worker_id,
                "execution_generation": generation,
                "requested_device": payload.get("requested_device") or payload.get("device"),
                "assigned_device": result.get("assigned_device") or report.get("assigned_device"),
                "actual_device": result.get("actual_device") or report.get("actual_device"),
                "gpu_id": selected_gpu.get("id"),
                "gpu_uuid": selected_gpu.get("uuid"),
                "gpu_name": selected_gpu.get("name"),
                "gpu_index": selected_gpu.get("index"),
            },
            requested_params=training.get("params") if isinstance(training.get("params"), Mapping) else {},
            actual_params=actual_params,
            iteration_action=payload.get("iteration_action"),
            supplement_provenance=(
                training.get("supplement_provenance")
                if isinstance(training.get("supplement_provenance"), Mapping)
                else payload.get("supplement_provenance")
            ),
            artifacts=[{
                "role": item.get("role"),
                "artifact_id": item.get("artifact_id"),
                "file_name": Path(str(item.get("object_key") or "")).name,
                "sha256": item.get("sha256"),
                "size_bytes": item.get("size_bytes"),
                "storage_source_id": item.get("storage_source_id"),
                "object_key": item.get("object_key"),
                "verified": True,
            } for item in committed_models],
            training_status="PARTIAL_SUCCESS" if partial else "SUCCEEDED",
            training_outcome=result.get("training_outcome"),
            completion_reason=completion.get("completion_reason"),
            finished_at=finished_at,
        )
        version = {
            "id": version_id,
            "version_name": version_name,
            "stored_path": primary,
            "best_path": best_path,
            "last_path": last_path,
            "model_name": Path(primary).name,
            "verified_models": committed_models,
            "model_artifact_ids": [
                str(row.get("artifact_id") or "")
                for row in artifact_rows
                if str(row.get("artifact_id") or "")
            ],
            "training_status": "PARTIAL_SUCCESS" if partial else "SUCCEEDED",
            "training_outcome": str(result.get("training_outcome") or ""),
            "completion_reason": str(completion.get("completion_reason") or ""),
            "base_version_id": expected_base_id or None,
            "base_version_name": str(model_contract.get("base_version_name") or ""),
            "base_selection_reason": str(model_contract.get("base_selection_reason") or ""),
            "metrics": dict(report.get("metrics") or {}) if isinstance(report.get("metrics"), Mapping) else {},
            "artifact_verified": True,
            "trainable": True,
            "framework": "ultralytics",
            "external_analysis_id": str(payload.get("external_analysis_id") or "").strip(),
            "snapshot_id": str(training.get("snapshot_id") or ""),
            "dataset_revision_id": str(training.get("dataset_revision_id") or ""),
            "training_lineage": training_lineage,
            "evaluation": evaluation,
            "result_ref": f"remote-results/{generation}/result.json",
            "task_id": str(task.task_id),
            "job_id": str(task.task_id),
            "execution_generation": generation,
            "created_at": finished_at,
            "finished_at": finished_at,
        }

        attach_version(
            self.algorithms_file(str(task.project_id)),
            algorithm_id,
            version,
        )
        return {
            "algorithm_id": algorithm_id,
            "version_id": version_id,
            "version_name": version_name,
            "snapshot_id": str(training.get("snapshot_id") or ""),
            "dataset_revision_id": str(training.get("dataset_revision_id") or ""),
            "model_artifacts_committed": True,
            "model_artifact_summary": {
                "discovered": len(artifact_rows),
                "uploaded": len(artifact_rows),
                "failed": 0,
                "pending": 0,
            },
        }

    def _commit_conversion_result(
        self,
        task,
        payload: Mapping[str, Any],
        evidence: Mapping[str, Any],
        confirmed: Mapping[str, Any],
    ) -> dict[str, Any]:
        _remote, conversion = self._conversion_remote(task, payload)
        target = str(conversion.get("target") or "").strip().lower()
        params = self._portable_conversion_params(
            target,
            conversion.get("params") if isinstance(conversion.get("params"), Mapping) else {},
        )
        result = confirmed.get("result")
        if not isinstance(result, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_RESULT_CONFIRM_INVALID",
                "verified conversion result metadata is missing",
                500,
            )
        output_storage = result.get("output_storage")
        if not isinstance(output_storage, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_RESULT_CONFIRM_INVALID",
                "verified conversion output storage reference is missing",
                500,
            )
        expected_sha = _normalized_sha256(
            result.get("output_sha256") or evidence.get("sha256"),
            "conversion.output_sha256",
        )
        expected_size = _positive_int(
            result.get("output_size_bytes") or evidence.get("size_bytes"),
            "conversion.output_size_bytes",
        )
        generation = _positive_int(
            evidence.get("execution_generation"),
            "result.execution_generation",
        )
        output_contract = conversion.get("output")
        output_contract = dict(output_contract) if isinstance(output_contract, Mapping) else {}
        expected_suffix = ".onnx" if target == "onnx" else ".rknn"
        default_name = (
            "model.onnx"
            if target == "onnx"
            else f"model_{params.get('chip') or 'rockchip'}.rknn"
        )
        file_name = Path(
            str(
                output_storage.get("file_name")
                or output_contract.get("file_name")
                or default_name
            )
        ).name
        if Path(file_name).suffix.lower() != expected_suffix:
            raise RemoteExecutionTransportError(
                "REMOTE_RESULT_CONFIRM_INVALID",
                "verified conversion output suffix does not match conversion target",
                500,
            )

        project = self.project_dir(str(task.project_id)).resolve()
        job_dir = (project / "deploy" / "jobs" / str(task.task_id)).resolve()
        artifacts = (job_dir / "artifacts").resolve()
        artifacts.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(job_dir / ".remote-conversion-commit.lock"), timeout=30)
        try:
            lock.acquire()
        except Timeout as error:
            raise RemoteExecutionTransportError(
                "REMOTE_CONVERSION_COMMIT_BUSY",
                "remote conversion result commit is busy",
                409,
            ) from error
        try:
            destination = (artifacts / file_name).resolve()
            if artifacts not in destination.parents:
                raise RemoteExecutionTransportError(
                    "REMOTE_CONVERSION_COMMIT_PATH_INVALID",
                    "remote conversion destination escaped artifact root",
                    500,
                )
            if destination.is_symlink():
                raise RemoteExecutionTransportError(
                    "REMOTE_CONVERSION_COMMIT_PATH_INVALID",
                    "remote conversion destination must not be a symlink",
                    409,
                )
            if destination.is_file():
                if (
                    int(destination.stat().st_size) != expected_size
                    or _sha256(destination) != expected_sha
                ):
                    raise RemoteExecutionTransportError(
                        "REMOTE_CONVERSION_COMMIT_CONFLICT",
                        "existing local conversion artifact conflicts with verified remote result",
                        409,
                    )
            else:
                _source, provider = self._source_provider(
                    str(task.project_id),
                    output_storage,
                )
                object_key = str(output_storage.get("object_key") or "").strip()
                if not object_key:
                    raise RemoteExecutionTransportError(
                        "REMOTE_RESULT_CONFIRM_INVALID",
                        "remote conversion object key is missing",
                        500,
                    )
                temporary = artifacts / f".{file_name}.remote.tmp"
                temporary.unlink(missing_ok=True)
                try:
                    provider.download(object_key, temporary)
                    if (
                        not temporary.is_file()
                        or int(temporary.stat().st_size) != expected_size
                        or _sha256(temporary) != expected_sha
                    ):
                        raise RemoteExecutionTransportError(
                            "REMOTE_CONVERSION_COMMIT_VERIFY_FAILED",
                            "downloaded conversion artifact does not match verified remote result evidence",
                            502,
                        )
                    temporary.replace(destination)
                finally:
                    temporary.unlink(missing_ok=True)

            runtime_verified = target == "onnx"
            target_manifest = (
                {"kind": "onnx"}
                if runtime_verified
                else {
                    "kind": "rockchip",
                    "chip": str(params.get("chip") or ""),
                    "precision": str(params.get("precision") or "fp16"),
                }
            )
            manifest = {
                "schema_version": 1,
                "task_id": str(task.task_id),
                "execution_generation": generation,
                "target": target_manifest,
                "status": "runtime_verified" if runtime_verified else "converted_unverified",
                "runtime_verified": runtime_verified,
                "hardware_verified": False,
                "source_trace": dict(conversion.get("source_trace") or {})
                if isinstance(conversion.get("source_trace"), Mapping)
                else {},
                "parameters": params,
                "output": {
                    "file_name": file_name,
                    "size_bytes": expected_size,
                    "sha256": expected_sha,
                    "storage": dict(output_storage),
                },
            }
            manifest_path = artifacts / "manifest.json"
            manifest_tmp = artifacts / ".manifest.json.remote.tmp"
            manifest_tmp.write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            manifest_tmp.replace(manifest_path)

            job_file = job_dir / "job.json"
            try:
                job = json.loads(job_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                job = {}
            if not isinstance(job, dict):
                job = {}
            job.update({
                "id": str(task.task_id),
                "project_id": str(task.project_id),
                "target": target,
                "source_trace": dict(conversion.get("source_trace") or {})
                if isinstance(conversion.get("source_trace"), Mapping)
                else {},
                "status": "done",
                "progress": 100,
                "stage": "转换完成",
                "message": (
                    "Agent ONNX 转换完成并已通过运行时校验"
                    if runtime_verified
                    else "Agent RKNN 转换完成；等待目标板 Runtime 实机验证"
                ),
                "runtime_verified": runtime_verified,
                "hardware_verified": False,
                "validation_status": (
                    "runtime_verified"
                    if runtime_verified
                    else "converted_unverified"
                ),
                "conversion_status": (
                    "runtime_verified"
                    if runtime_verified
                    else "converted"
                ),
                "result_ref": str(confirmed.get("result_ref") or ""),
                "remote_execution": True,
                "remote_execution_generation": generation,
                "outputs": [
                    {
                        "name": file_name,
                        "path": str(destination),
                        "rel": f"artifacts/{file_name}",
                        "size_mb": round(expected_size / 1024 / 1024, 3),
                    },
                    {
                        "name": "manifest.json",
                        "path": str(manifest_path),
                        "rel": "artifacts/manifest.json",
                        "size_mb": round(
                            manifest_path.stat().st_size / 1024 / 1024,
                            3,
                        ),
                    },
                ],
            })
            job_tmp = job_dir / ".job.json.remote.tmp"
            job_tmp.write_text(
                json.dumps(job, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            job_tmp.replace(job_file)
            return {
                "conversion_artifact_committed": True,
                "conversion_artifact_path": str(destination),
                "conversion_artifact_sha256": expected_sha,
                "conversion_artifact_size_bytes": expected_size,
                "target": target,
                "runtime_verified": runtime_verified,
                "hardware_verified": False,
            }
        finally:
            lock.release()

    def _commit_rknn_board_verification_result(
        self,
        task,
        payload: Mapping[str, Any],
        evidence: Mapping[str, Any],
        confirmed: Mapping[str, Any],
    ) -> dict[str, Any]:
        _remote, deployment = self._deployment_remote(task, payload)
        if str(deployment.get("runtime_format") or "").strip().lower() != "rknn":
            return {}
        board = deployment.get("board")
        runtime = confirmed.get("runtime_result")
        if not isinstance(board, Mapping) or not isinstance(runtime, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_RKNN_BOARD_EVIDENCE_INVALID",
                "RKNN board verification is missing contract/runtime evidence",
                409,
            )
        chip = str(board.get("chip") or "").strip().lower()
        conversion_job_id = str(board.get("conversion_job_id") or "").strip()
        if (
            chip not in {"rk3568", "rk3576"}
            or not conversion_job_id
            or runtime.get("ok") is not True
            or str(runtime.get("engine") or "").strip().lower() != "rknn-lite2"
            or str(runtime.get("runtime_format") or "").strip().lower() != "rknn"
            or str(runtime.get("chip") or "").strip().lower() != chip
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_RKNN_BOARD_EVIDENCE_INVALID",
                "RKNN board runtime evidence does not match the requested target",
                409,
            )
        try:
            inference_ms = float(runtime.get("inference_ms"))
            output_count = int(runtime.get("output_count"))
        except (TypeError, ValueError) as error:
            raise RemoteExecutionTransportError(
                "REMOTE_RKNN_BOARD_EVIDENCE_INVALID",
                "RKNN board runtime evidence is incomplete",
                409,
            ) from error
        if inference_ms < 0 or output_count <= 0:
            raise RemoteExecutionTransportError(
                "REMOTE_RKNN_BOARD_EVIDENCE_INVALID",
                "RKNN board inference did not produce valid output evidence",
                409,
            )

        project = self.project_dir(str(task.project_id)).resolve()
        job_dir = (project / "deploy" / "jobs" / conversion_job_id).resolve()
        manifest_path = (job_dir / "artifacts" / "manifest.json").resolve()
        job_path = (job_dir / "job.json").resolve()
        if not manifest_path.is_file() or not job_path.is_file():
            raise RemoteExecutionTransportError(
                "REMOTE_RKNN_BOARD_SOURCE_MISSING",
                "source RKNN conversion job no longer exists",
                409,
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            job = json.loads(job_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RemoteExecutionTransportError(
                "REMOTE_RKNN_BOARD_SOURCE_INVALID",
                "source RKNN conversion metadata is unreadable",
                409,
            ) from error
        target = manifest.get("target") if isinstance(manifest, Mapping) else None
        output = manifest.get("output") if isinstance(manifest, Mapping) else None
        if (
            not isinstance(target, Mapping)
            or str(target.get("kind") or "") != "rockchip"
            or str(target.get("chip") or "").strip().lower() != chip
            or not isinstance(output, Mapping)
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_RKNN_BOARD_SOURCE_INVALID",
                "source conversion manifest does not match the board target",
                409,
            )
        file_name = Path(str(output.get("file_name") or "")).name
        artifact = (job_dir / "artifacts" / file_name).resolve()
        if (
            not file_name
            or artifact.parent != (job_dir / "artifacts").resolve()
            or not artifact.is_file()
            or artifact.suffix.lower() != ".rknn"
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_RKNN_BOARD_SOURCE_MISSING",
                "source RKNN artifact is missing",
                409,
            )
        expected_sha = _normalized_sha256(board.get("model_sha256"), "board.model_sha256")
        try:
            expected_size = int(board.get("model_size_bytes") or 0)
        except (TypeError, ValueError):
            expected_size = 0
        if (
            expected_size <= 0
            or int(artifact.stat().st_size) != expected_size
            or _sha256(artifact) != expected_sha
            or int(output.get("size_bytes") or 0) != expected_size
            or str(output.get("sha256") or "").strip().lower() != expected_sha
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_RKNN_BOARD_SOURCE_CHANGED",
                "source RKNN artifact changed after board validation was staged",
                409,
            )

        generation = _positive_int(
            evidence.get("execution_generation"),
            "result.execution_generation",
        )
        worker_id = str(getattr(task, "worker_id", "") or "").strip()
        if not worker_id.startswith("agent:") or not worker_id.split(":", 1)[1].strip():
            raise RemoteExecutionTransportError(
                "REMOTE_RKNN_BOARD_EVIDENCE_INVALID",
                "RKNN board verification must be committed by an Agent-owned execution",
                409,
            )
        node_id = worker_id.split(":", 1)[1].strip()
        input_ref = deployment.get("input")
        input_ref = dict(input_ref) if isinstance(input_ref, Mapping) else {}
        input_sha = _normalized_sha256(
            input_ref.get("sha256"),
            "board.input.sha256",
        )
        input_size = _positive_int(
            input_ref.get("size_bytes"),
            "board.input.size_bytes",
        )
        verification = {
            "task_id": str(task.task_id),
            "execution_generation": generation,
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "node_id": node_id,
            "chip": chip,
            "engine": "rknn-lite2",
            "rknn_lite_version": str(runtime.get("rknn_lite_version") or ""),
            "model_sha256": expected_sha,
            "model_size_bytes": expected_size,
            "input": {
                "file_name": Path(str(input_ref.get("file_name") or "input")).name,
                "sha256": input_sha,
                "size_bytes": input_size,
            },
            "inference_ms": inference_ms,
            "output_count": output_count,
            "output_shapes": list(runtime.get("output_shapes") or []),
            "result_output_storage": dict(
                (confirmed.get("result") or {}).get("output_storage") or {}
            ),
        }
        lock = FileLock(str(job_dir / ".rknn-hardware-verify.lock"), timeout=30)
        try:
            lock.acquire()
        except Timeout as error:
            raise RemoteExecutionTransportError(
                "REMOTE_RKNN_BOARD_COMMIT_BUSY",
                "RKNN board verification commit is busy",
                409,
            ) from error
        try:
            # Re-read under the lock before publishing the hardware truth.
            latest_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            latest_job = json.loads(job_path.read_text(encoding="utf-8"))
            latest_manifest.update({
                "status": "hardware_verified",
                "runtime_verified": True,
                "hardware_verified": True,
                "validation_status": "hardware_verified",
                "hardware_verification": verification,
            })
            manifest_tmp = manifest_path.with_name(".manifest.json.hardware.tmp")
            manifest_tmp.write_text(
                json.dumps(latest_manifest, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            manifest_tmp.replace(manifest_path)

            latest_job.update({
                "runtime_verified": True,
                "hardware_verified": True,
                "validation_status": "hardware_verified",
                "conversion_status": "hardware_verified",
                "message": f"RKNN 已在 {chip.upper()} 实机完成 Runtime 推理验证",
                "hardware_verification": verification,
            })
            job_tmp = job_path.with_name(".job.json.hardware.tmp")
            job_tmp.write_text(
                json.dumps(latest_job, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            job_tmp.replace(job_path)
        finally:
            lock.release()
        return {
            "rknn_hardware_verified": True,
            "conversion_job_id": conversion_job_id,
            "chip": chip,
            "inference_ms": inference_ms,
            "output_count": output_count,
        }

    def _project_label_items(self, project_id: str) -> list[dict[str, Any]]:
        try:
            meta = json.loads(
                (self.project_dir(str(project_id)) / "meta.json").read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError, TypeError):
            return []
        if not isinstance(meta, Mapping):
            return []
        labels = list(meta.get("labels") or [])
        details = list(meta.get("label_meta") or [])
        result = []
        for index, code in enumerate(labels):
            text = str(code or "").strip()
            if not text:
                continue
            item = dict(details[index]) if index < len(details) and isinstance(details[index], Mapping) else {}
            item["code"] = text
            item.setdefault("display_name", text)
            item.setdefault("status", "active")
            result.append(item)
        return result

    def _commit_material_import_result(
        self,
        task,
        payload: Mapping[str, Any],
        evidence: Mapping[str, Any],
        confirmed: Mapping[str, Any],
    ) -> dict[str, Any]:
        if self.task_artifacts is None:
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_ARTIFACT_STORE_UNAVAILABLE",
                "control-plane task artifact store is not configured",
                500,
            )
        _remote, material = self._material_remote(task, payload)
        target = material.get("target")
        result = confirmed.get("result")
        if not isinstance(target, Mapping) or not isinstance(result, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_RESULT_CONFIRM_INVALID",
                "verified material review metadata is missing",
                500,
            )
        storage_ref = result.get("output_storage")
        if not isinstance(storage_ref, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_RESULT_CONFIRM_INVALID",
                "verified material review object reference is missing",
                500,
            )
        generation = _positive_int(
            evidence.get("execution_generation"),
            "result.execution_generation",
        )
        _source, provider = self._source_provider(str(task.project_id), storage_ref)
        archive_ref = (
            f"remote-material/generation-{generation}/review-source.zip"
        )
        archive_path = self.task_artifacts.artifact_path(
            str(task.task_id),
            archive_ref,
        )
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = archive_path.with_name(f".{archive_path.name}.download")
        temporary.unlink(missing_ok=True)
        try:
            provider.download(str(storage_ref.get("object_key") or ""), temporary)
            if (
                int(temporary.stat().st_size) != int(evidence.get("size_bytes") or 0)
                or _sha256(temporary) != str(evidence.get("sha256") or "").lower()
            ):
                raise RemoteExecutionTransportError(
                    "REMOTE_MATERIAL_REVIEW_CHANGED",
                    "downloaded material review object does not match confirmed evidence",
                    409,
                )
            temporary.replace(archive_path)
        finally:
            temporary.unlink(missing_ok=True)
        try:
            committed = commit_material_review_archive(
                artifacts=self.task_artifacts,
                task_id=str(task.task_id),
                project_id=str(task.project_id),
                execution_generation=generation,
                archive_path=archive_path,
                archive_sha256=str(evidence.get("sha256") or ""),
                archive_size_bytes=int(evidence.get("size_bytes") or 0),
                expected_source_id=str(target.get("storage_source_id") or ""),
                expected_storage_type=str(target.get("storage_type") or ""),
                expected_prefix=str(target.get("target_prefix") or ""),
                expected_mode=str(material.get("mode") or "zip_scan"),
                expected_import_format=str(material.get("import_format") or "images"),
                expected_dataset_yaml=str(material.get("dataset_yaml") or ""),
                expected_intent=str(material.get("intent") or ""),
                platform_labels=self._project_label_items(str(task.project_id)),
            )
        except RemoteMaterialImportError as error:
            raise RemoteExecutionTransportError(
                error.code,
                str(error),
                error.status_code,
            ) from error

        rescan_commit: dict[str, Any] = {}
        if str(payload.get("mode") or "") == "storage_rescan":
            if str(material.get("intent") or "") != "storage_rescan":
                raise RemoteExecutionTransportError(
                    "REMOTE_MATERIAL_RESCAN_CONTRACT_INVALID",
                    "storage_rescan task is missing its portable rescan intent",
                    409,
                )
            from .storage.rescan_tasks import prepare_remote_rescan_review
            try:
                rescan_commit = prepare_remote_rescan_review(
                    data_dir=self.data_dir,
                    artifacts=self.task_artifacts,
                    task_id=str(task.task_id),
                    project_id=str(task.project_id),
                    storage_source_id=str(target.get("storage_source_id") or ""),
                )
            except ValueError as error:
                raise RemoteExecutionTransportError(
                    "REMOTE_MATERIAL_RESCAN_REVIEW_INVALID",
                    str(error),
                    409,
                ) from error

        # The control plane now owns a durable review ZIP + candidate/annotation
        # truth, so the remote input/review objects are no longer required for
        # confirmation or local indexing. Cleanup is deliberately best-effort:
        # a provider outage must not turn a verified import into a failed task.
        cleanup: dict[str, Any]
        try:
            lifecycle = RemoteMaterialStagingLifecycle(
                None,
                self.task_artifacts,
                lambda project_id, ref: self._source_provider(project_id, ref)[1],
            )
            cleanup = lifecycle.record_confirmed(
                task,
                payload,
                evidence,
                confirmed,
            )
        except Exception as error:
            cleanup = {
                "status": "DEFERRED",
                "deleted": 0,
                "error": str(error)[:1000],
            }
        return {
            **dict(committed),
            **rescan_commit,
            "remote_staging_cleanup": cleanup,
        }

    def _commit_cleaning_result(
        self,
        task,
        payload: Mapping[str, Any],
        evidence: Mapping[str, Any],
        confirmed: Mapping[str, Any],
    ) -> dict[str, Any]:
        if self.task_artifacts is None:
            raise RemoteExecutionTransportError(
                "REMOTE_CLEANING_ARTIFACT_STORE_UNAVAILABLE",
                "control-plane task artifact store is not configured",
                500,
            )
        self._clean_remote(task, payload)
        result = confirmed.get("result")
        if not isinstance(result, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_RESULT_CONFIRM_INVALID",
                "verified cleaning review metadata is missing",
                500,
            )
        storage_ref = result.get("output_storage")
        if not isinstance(storage_ref, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_RESULT_CONFIRM_INVALID",
                "verified cleaning review object reference is missing",
                500,
            )
        generation = _positive_int(
            evidence.get("execution_generation"),
            "result.execution_generation",
        )
        _source, provider = self._source_provider(str(task.project_id), storage_ref)
        review_ref = f"remote-cleaning/generation-{generation}/review.jsonl"
        review_path = self.task_artifacts.artifact_path(str(task.task_id), review_ref)
        review_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = review_path.with_name(f".{review_path.name}.download")
        temporary.unlink(missing_ok=True)
        try:
            provider.download(str(storage_ref.get("object_key") or ""), temporary)
            if (
                int(temporary.stat().st_size) != int(evidence.get("size_bytes") or 0)
                or _sha256(temporary) != str(evidence.get("sha256") or "").lower()
            ):
                raise RemoteExecutionTransportError(
                    "REMOTE_CLEANING_REVIEW_CHANGED",
                    "downloaded cleaning review object does not match confirmed evidence",
                    409,
                )
            temporary.replace(review_path)
        finally:
            temporary.unlink(missing_ok=True)
        try:
            committed = commit_remote_cleaning_review(
                artifacts=self.task_artifacts,
                task=task,
                project_path=self.project_dir(str(task.project_id)),
                payload=payload,
                review_path=review_path,
                execution_generation=generation,
                expected_sha256=str(evidence.get("sha256") or ""),
                expected_size_bytes=int(evidence.get("size_bytes") or 0),
            )
        except RemoteCleaningError as error:
            raise RemoteExecutionTransportError(
                error.code,
                str(error),
                error.status_code,
            ) from error
        return {
            **dict(committed),
            "remote_cleaning_review_ref": review_ref,
        }

    def commit_result_publication(
        self,
        task,
        payload: Mapping[str, Any],
        evidence: Mapping[str, Any],
        confirmed: Mapping[str, Any],
    ) -> dict[str, Any]:
        kind = str(getattr(task.kind, "value", task.kind))
        if kind == "TRAINING":
            return self._commit_training_result(task, payload, evidence, confirmed)
        if kind == "MODEL_CONVERSION":
            return self._commit_conversion_result(task, payload, evidence, confirmed)
        if kind == "MATERIAL_IMPORT":
            return self._commit_material_import_result(task, payload, evidence, confirmed)
        if kind == "MATERIAL_BATCH":
            return self._commit_cleaning_result(task, payload, evidence, confirmed)
        if kind == "DEPLOYMENT_TEST":
            return self._commit_rknn_board_verification_result(
                task,
                payload,
                evidence,
                confirmed,
            )
        return {}

    @staticmethod
    def _material_scan_source(material: Mapping[str, Any]) -> Mapping[str, Any]:
        if str(material.get("mode") or "") != "storage_scan":
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_SCAN_UNAVAILABLE",
                "material task is not a brokered storage_scan",
                409,
            )
        source = material.get("source")
        if not isinstance(source, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "storage_scan source contract is missing",
                422,
            )
        return source

    @staticmethod
    def _material_scan_key_allowed(source: Mapping[str, Any], object_key: str) -> bool:
        key = str(object_key or "").replace("\\", "/").lstrip("/")
        prefix = str(source.get("prefix") or "").replace("\\", "/").strip("/")
        if not key or ".." in PurePosixPath(key).parts:
            return False
        if prefix and not (key == prefix or key.startswith(prefix.rstrip("/") + "/")):
            return False
        if not bool(source.get("recursive", True)) and prefix:
            relative = key[len(prefix):].lstrip("/")
            if "/" in relative:
                return False
        return True

    def material_scan_page(
        self,
        task,
        payload: Mapping[str, Any],
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        _remote, material = self._material_remote(task, payload)
        source = self._material_scan_source(material)
        provider_ref = {
            "storage_source_id": str(source.get("storage_source_id") or ""),
        }
        _configured, provider = self._source_provider(str(task.project_id), provider_ref)
        bounded = max(1, min(100, int(limit)))
        page = provider.list_objects(
            str(source.get("prefix") or ""),
            recursive=bool(source.get("recursive", True)),
            cursor=str(cursor) if cursor else None,
            limit=bounded,
        )
        items = []
        for item in page.items:
            key = str(item.key or "")
            if not self._material_scan_key_allowed(source, key):
                raise RemoteExecutionTransportError(
                    "REMOTE_MATERIAL_SCAN_PROVIDER_ESCAPE",
                    "storage provider returned an object outside the task scan scope",
                    409,
                )
            items.append({
                "key": key,
                "size_bytes": max(0, int(item.size_bytes or 0)),
                "etag": str(item.etag or ""),
                "content_type": str(item.content_type or "application/octet-stream"),
                "sha256": str(item.sha256 or "").strip().lower(),
                "last_modified": str(item.last_modified or ""),
            })
        return {
            "items": items,
            "next_cursor": str(page.next_cursor) if page.next_cursor else None,
            "prefix": str(source.get("prefix") or ""),
            "recursive": bool(source.get("recursive", True)),
        }

    def material_scan_read_contract(
        self,
        task,
        payload: Mapping[str, Any],
        *,
        object_key: str,
    ) -> dict[str, Any]:
        _remote, material = self._material_remote(task, payload)
        source = self._material_scan_source(material)
        key = str(object_key or "").replace("\\", "/").lstrip("/")
        if not self._material_scan_key_allowed(source, key):
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_SCAN_KEY_FORBIDDEN",
                "requested object is outside the task storage_scan scope",
                403,
            )
        provider_ref = {
            "storage_source_id": str(source.get("storage_source_id") or ""),
        }
        _configured, provider = self._source_provider(str(task.project_id), provider_ref)
        if not provider.exists(key):
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_SCAN_OBJECT_MISSING",
                "requested storage_scan object does not exist",
                404,
            )
        metadata = provider.stat(key)
        url = provider.generate_preview_url(
            key,
            expires_seconds=REMOTE_TRANSFER_TTL_SECONDS,
        )
        if not url:
            raise RemoteExecutionTransportError(
                "REMOTE_MATERIAL_SCAN_READ_UNAVAILABLE",
                "storage provider cannot mint an object read URL",
                409,
            )
        return {
            "method": "GET",
            "url": str(url),
            "headers": {},
            "expires_seconds": REMOTE_TRANSFER_TTL_SECONDS,
            "key": key,
            "size_bytes": max(0, int(metadata.size_bytes or 0)),
            "etag": str(metadata.etag or ""),
            "content_type": str(metadata.content_type or "application/octet-stream"),
            "sha256": str(metadata.sha256 or "").strip().lower(),
            "last_modified": str(metadata.last_modified or ""),
        }

    def resolve_execution_payload(
        self,
        task,
        payload: Mapping[str, Any],
        assignment: Mapping[str, Any],
    ) -> dict[str, Any]:
        kind = str(getattr(task.kind, "value", task.kind))
        if kind == "TRAINING":
            return self._resolve_training_execution_payload(task, payload, assignment)
        if kind == "MODEL_CONVERSION":
            return self._resolve_conversion_execution_payload(task, payload, assignment)
        if kind == "MATERIAL_IMPORT":
            return self._resolve_material_execution_payload(task, payload, assignment)
        if kind == "MATERIAL_BATCH":
            return self._resolve_clean_execution_payload(task, payload, assignment)
        _remote, deployment = self._deployment_remote(task, payload)
        input_ref = deployment.get("input")
        model_ref = deployment.get("model")
        output_ref = deployment.get("output")
        if not isinstance(input_ref, Mapping) or not isinstance(model_ref, Mapping) or not isinstance(output_ref, Mapping):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable deployment object references are incomplete",
                422,
            )

        model_type = str(model_ref.get("type") or "")
        if model_type == "official":
            reference = str(model_ref.get("reference") or "").strip()
            if not reference or Path(reference).is_absolute() or "/" in reference or "\\" in reference:
                raise RemoteExecutionTransportError(
                    "REMOTE_MODEL_REFERENCE_INVALID",
                    "official model reference is invalid",
                    422,
                )
            model = {"type": "official", "reference": reference}
        elif model_type == "object":
            model = {
                "type": "object",
                "download": self._download_contract(str(task.project_id), model_ref),
                "artifact_id": str(model_ref.get("artifact_id") or ""),
            }
        else:
            raise RemoteExecutionTransportError(
                "REMOTE_MODEL_REFERENCE_INVALID",
                "remote deployment model reference is unsupported",
                422,
            )

        resolved = assignment.get("resolved_execution_config")
        selected_device = ""
        if isinstance(resolved, Mapping):
            selected_device = str(resolved.get("selected_device") or "")

        runtime_format = str(deployment.get("runtime_format") or "").strip().lower()
        framework = str(deployment.get("framework") or "ultralytics").strip().lower()
        board_payload = None
        if runtime_format == "rknn":
            board = deployment.get("board")
            if not isinstance(board, Mapping) or int(board.get("schema_version") or 0) != 1:
                raise RemoteExecutionTransportError(
                    "REMOTE_RKNN_BOARD_CONTRACT_INVALID",
                    "RKNN board verification contract is missing",
                    422,
                )
            chip = str(board.get("chip") or "").strip().lower()
            conversion_job_id = str(board.get("conversion_job_id") or "").strip()
            try:
                input_size = int(board.get("input_size") or 0)
                model_size = int(board.get("model_size_bytes") or 0)
            except (TypeError, ValueError) as error:
                raise RemoteExecutionTransportError(
                    "REMOTE_RKNN_BOARD_CONTRACT_INVALID",
                    "RKNN board numeric evidence is invalid",
                    422,
                ) from error
            model_sha = _normalized_sha256(board.get("model_sha256"), "board.model_sha256")
            if (
                framework != "rknn"
                or chip not in {"rk3568", "rk3576"}
                or not conversion_job_id
                or input_size < 32
                or input_size > 4096
                or model_size <= 0
            ):
                raise RemoteExecutionTransportError(
                    "REMOTE_RKNN_BOARD_CONTRACT_INVALID",
                    "RKNN board verification contract is incomplete",
                    422,
                )
            board_payload = {
                "schema_version": 1,
                "chip": chip,
                "input_size": input_size,
                "conversion_job_id": conversion_job_id,
                "model_sha256": model_sha,
                "model_size_bytes": model_size,
            }

        result = {
            "schema_version": 1,
            "task_kind": "DEPLOYMENT_TEST",
            "transport": "object-storage-v1",
            "framework": framework,
            "runtime_format": runtime_format,
            "confidence": max(0.0, min(1.0, float(deployment.get("confidence") or 0.25))),
            "selected_device": selected_device,
            "input": {
                "type": "object",
                "download": self._download_contract(str(task.project_id), input_ref),
            },
            "model": model,
            "output": {
                "type": "object",
                "storage_ref": {
                    "storage_source_id": str(output_ref.get("storage_source_id") or ""),
                    "object_key": str(output_ref.get("object_key") or ""),
                    "file_name": Path(str(output_ref.get("file_name") or "result.jpg")).name,
                    "content_type": str(output_ref.get("content_type") or "image/jpeg"),
                },
                "upload_protocol": "prepare-after-local-hash-v1",
            },
        }
        if board_payload is not None:
            result["board"] = board_payload
        return result


__all__ = [
    "REMOTE_TRANSFER_TTL_SECONDS",
    "RemoteExecutionTransportError",
    "RemoteExecutionTransportService",
]
