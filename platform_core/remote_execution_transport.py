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
from pathlib import Path
from typing import Any, Callable, Mapping

from .algorithms import attach_version, list_algorithms, resolve_current_version_id
from filelock import FileLock, Timeout

from .model_artifacts import ModelArtifactService
from .remote_training_results import (
    RemoteTrainingResultError,
    verify_training_result_archive,
)
from .resource_discovery import OFFICIAL_DOWNLOADABLE_MODELS
from .storage import StorageProviderFactory, StorageType


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
    ):
        self.data_dir = Path(data_dir)
        self.project_dir = project_dir
        self.algorithms_file = algorithms_file
        self.storage_sources_factory = storage_sources_factory
        self.storage_credentials_factory = storage_credentials_factory
        self.provider_factory = provider_factory
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
        if (
            int(training.get("schema_version") or 0) != 1
            or str(training.get("framework") or "") != "ultralytics"
            or not str(training.get("snapshot_id") or "").strip()
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_EXECUTION_CONTRACT_INVALID",
                "portable remote training payload identity is invalid",
                422,
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
        prefix = str(config.get("object_prefix") or "model-assets").strip().strip("/") or "model-assets"
        role = str(model["role"])
        digest = str(model["sha256"])
        file_name = Path(str(model["file_name"])).name
        object_key = "/".join([
            prefix,
            _safe_segment(task.project_id, "project"),
            _safe_segment(algorithm_id, "algorithm"),
            _safe_segment(version_id, "version"),
            _safe_segment(role, "model"),
            f"{digest[:16]}-{_safe_segment(file_name, role + '.pt')}",
        ])
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
        if str(getattr(task.kind, "value", task.kind)) == "TRAINING":
            return self._prepare_training_result_upload(task, payload, evidence)
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
        if str(getattr(task.kind, "value", task.kind)) == "TRAINING":
            return self._confirm_training_result_upload(task, payload, evidence)
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

        return {
            "result_ref": "result.json",
            "result": {
                "task_id": str(task.task_id),
                "project_id": str(task.project_id),
                "remote_execution": True,
                "transport": "object-storage-v1",
                "framework": str(deployment.get("framework") or "ultralytics"),
                "runtime_format": str(deployment.get("runtime_format") or ""),
                "confidence": max(0.0, min(1.0, float(deployment.get("confidence") or 0.25))),
                "output_storage": storage_ref,
                "output_size_bytes": expected_size,
                "output_sha256": expected_sha,
                "runtime_log_ref": str(getattr(task, "log_ref", "") or ""),
                "recovered_from_completed_work": False,
            },
        }

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
            return {
                "algorithm_id": algorithm_id,
                "version_id": version_id,
                "version_name": str(existing_version.get("version_name") or ""),
                "model_artifacts_committed": True,
            }

        verified_models = result.get("verified_models")
        if not isinstance(verified_models, list) or not verified_models:
            raise RemoteExecutionTransportError(
                "REMOTE_TRAINING_MODEL_MISSING",
                "verified training result contains no deliverable model",
                409,
            )
        committed_models: list[dict[str, Any]] = []
        best_path = ""
        last_path = ""
        for index, item in enumerate(verified_models):
            if not isinstance(item, Mapping):
                raise RemoteExecutionTransportError(
                    "REMOTE_TRAINING_MODEL_INVALID",
                    "verified training model metadata is invalid",
                    422,
                )
            ref = str(item.get("ref") or "").strip().replace("\\", "/")
            if not ref.startswith("models/") or ".." in ref.split("/"):
                raise RemoteExecutionTransportError(
                    "REMOTE_TRAINING_MODEL_INVALID",
                    "verified training model reference is unsafe",
                    422,
                )
            source = (extracted / Path(*ref.split("/"))).resolve()
            if extracted not in source.parents or not source.is_file():
                raise RemoteExecutionTransportError(
                    "REMOTE_TRAINING_MODEL_MISSING",
                    "verified training model is missing from staged result",
                    409,
                )
            expected_sha = _normalized_sha256(
                item.get("sha256"),
                "training.model.sha256",
            )
            expected_size = _positive_int(
                item.get("size_bytes"),
                "training.model.size_bytes",
            )
            if int(source.stat().st_size) != expected_size or _sha256(source) != expected_sha:
                raise RemoteExecutionTransportError(
                    "REMOTE_TRAINING_MODEL_EVIDENCE_MISMATCH",
                    "staged training model changed after result verification",
                    409,
                )
            role = str(item.get("role") or "model").strip().lower()
            suffix = source.suffix.lower() or ".pt"
            destination = (
                models_root
                / f"remote_{_safe_segment(task.task_id, 'task')}_g{generation}_{role}_{expected_sha[:12]}{suffix}"
            ).resolve()
            if models_root not in destination.parents:
                raise RemoteExecutionTransportError(
                    "REMOTE_TRAINING_MODEL_DESTINATION_INVALID",
                    "training model destination escaped project model directory",
                    500,
                )
            if destination.exists():
                if (
                    not destination.is_file()
                    or int(destination.stat().st_size) != expected_size
                    or _sha256(destination) != expected_sha
                ):
                    raise RemoteExecutionTransportError(
                        "REMOTE_TRAINING_MODEL_CONFLICT",
                        "existing committed model path has different content",
                        409,
                    )
            else:
                temporary = destination.with_name(f".{destination.name}.{version_id}.tmp")
                temporary.unlink(missing_ok=True)
                try:
                    shutil.copy2(source, temporary)
                    if (
                        int(temporary.stat().st_size) != expected_size
                        or _sha256(temporary) != expected_sha
                    ):
                        raise RemoteExecutionTransportError(
                            "REMOTE_TRAINING_MODEL_COPY_FAILED",
                            "copied training model failed size/SHA256 verification",
                            500,
                        )
                    temporary.replace(destination)
                finally:
                    temporary.unlink(missing_ok=True)
            committed_models.append({
                "role": role,
                "path": str(destination),
                "sha256": expected_sha,
                "size_bytes": expected_size,
            })
            if role == "best":
                best_path = str(destination)
            elif role == "last":
                last_path = str(destination)

        primary = best_path or last_path or str(committed_models[0]["path"])
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
        version = {
            "id": version_id,
            "version_name": version_name,
            "stored_path": primary,
            "best_path": best_path,
            "last_path": last_path,
            "model_name": Path(primary).name,
            "verified_models": committed_models,
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
            "snapshot_id": str(training.get("snapshot_id") or ""),
            "result_ref": f"remote-results/{generation}/result.json",
            "task_id": str(task.task_id),
            "job_id": str(task.task_id),
            "execution_generation": generation,
            "created_at": finished_at,
            "finished_at": finished_at,
        }

        # Upload/register the verified models in the unified model-asset store
        # before exposing the algorithm version. A retry is safe because both
        # the version id and model content identity are deterministic.
        artifact_summary = self.model_artifacts.ingest_version(
            str(task.project_id),
            algorithm,
            version,
        )
        if (
            int(artifact_summary.get("discovered") or 0) <= 0
            or int(artifact_summary.get("failed") or 0) > 0
            or int(artifact_summary.get("pending") or 0) > 0
        ):
            raise RemoteExecutionTransportError(
                "REMOTE_TRAINING_MODEL_ASSET_COMMIT_FAILED",
                "verified remote training models were not fully committed to model asset storage",
                409,
            )

        attach_version(
            self.algorithms_file(str(task.project_id)),
            algorithm_id,
            version,
        )
        return {
            "algorithm_id": algorithm_id,
            "version_id": version_id,
            "version_name": version_name,
            "model_artifacts_committed": True,
            "model_artifact_summary": {
                "discovered": int(artifact_summary.get("discovered") or 0),
                "uploaded": int(artifact_summary.get("uploaded") or 0),
                "failed": int(artifact_summary.get("failed") or 0),
                "pending": int(artifact_summary.get("pending") or 0),
            },
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
        return {}

    def resolve_execution_payload(
        self,
        task,
        payload: Mapping[str, Any],
        assignment: Mapping[str, Any],
    ) -> dict[str, Any]:
        if str(getattr(task.kind, "value", task.kind)) == "TRAINING":
            return self._resolve_training_execution_payload(task, payload, assignment)
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

        return {
            "schema_version": 1,
            "task_kind": "DEPLOYMENT_TEST",
            "transport": "object-storage-v1",
            "framework": str(deployment.get("framework") or "ultralytics"),
            "runtime_format": str(deployment.get("runtime_format") or ""),
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


__all__ = [
    "REMOTE_TRANSFER_TTL_SECONDS",
    "RemoteExecutionTransportError",
    "RemoteExecutionTransportService",
]
