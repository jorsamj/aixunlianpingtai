"""Portable object-storage transport for remote task execution.

Durable task payloads keep only object references and content evidence. Signed
GET/PUT URLs are minted just-in-time when an authenticated Agent starts an
execution and are never persisted into scheduler assignment truth.
"""
from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path
from typing import Any, Callable, Mapping

from .algorithms import list_algorithms
from .model_artifacts import ModelArtifactService
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
        if metadata.sha256 and str(metadata.sha256).lower() != expected_sha:
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

    def resolve_execution_payload(
        self,
        task,
        payload: Mapping[str, Any],
        assignment: Mapping[str, Any],
    ) -> dict[str, Any]:
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
