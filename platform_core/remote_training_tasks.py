"""Durable control-plane preparation for portable remote TRAINING tasks."""
from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from typing import Any, Mapping

from .algorithms import choose_algorithm_iteration_base, list_algorithms
from .material_repository import MaterialRepository
from .model_artifacts import ModelArtifactService
from .remote_training_transport import (
    RemoteTrainingTransportError,
    create_training_bundle_archive,
    stage_training_bundle_object,
)
from .resource_discovery import OFFICIAL_DOWNLOADABLE_MODELS
from .secrets import KeyringSecretStore, SecretCredentialStore
from .storage import StorageManager, StorageProviderFactory, StorageType
from .storage.source_repository import StorageSourceRepository
from .task_runtime import TaskKind, TaskStatus
from .training_bundle_cache import TrainingBundleCache
from .training_splits import SplitMode, SplitRequest, build_split_manifest
from .training_tasks import (
    _indexed_content_identity_ready,
    _label_schema,
    _selected_project_images,
    materialize_portable_dataset,
)
from .snapshots import build_snapshot


class RemoteTrainingPreparationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        target_status: TaskStatus = TaskStatus.BLOCKED_BY_ENVIRONMENT,
    ):
        self.code = str(code)
        self.target_status = target_status
        super().__init__(str(message))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_segment(value: object, fallback: str) -> str:
    text = "".join(
        char if char.isalnum() or char in "._-" else "-"
        for char in str(value or "")
    ).strip("-._")
    return (text or fallback)[:120]


def _portable_params(payload: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "epochs", "imgsz", "batch", "patience", "workers", "optimizer",
        "lr0", "lrf", "weight_decay", "close_mosaic", "mosaic", "cache",
        "freeze", "momentum", "warmup_epochs", "save_period", "seed",
        "multi_scale", "hsv_h", "hsv_s", "hsv_v", "degrees", "translate",
        "scale", "shear", "perspective", "flipud", "fliplr", "mixup",
        "val_max_samples", "eval_interval", "eval_metric",
        "continue_threshold", "stop_threshold", "single_cls", "pretrained",
        "rect", "amp", "cos_lr", "deterministic", "auto_supplement",
        "ai_intervention_enabled", "supplement_count", "resource_strategy",
    )
    result = {}
    for key in keys:
        if key not in payload:
            continue
        value = payload[key]
        if value is None or isinstance(value, (str, int, float, bool)):
            result[key] = value
    return result


class RemoteTrainingPrepareHandler:
    def __init__(
        self,
        data_dir: str | Path,
        *,
        sources=None,
        credentials=None,
        provider_factory=None,
        model_artifacts=None,
    ):
        self.data_dir = Path(data_dir).resolve()
        self.sources = sources or StorageSourceRepository(
            self.data_dir / "storage" / "storage_sources.sqlite3"
        )
        self.credentials = credentials or SecretCredentialStore(KeyringSecretStore())
        self.provider_factory = provider_factory
        self.model_artifacts = model_artifacts or ModelArtifactService(
            data_dir=self.data_dir,
            project_dir=lambda project_id: self.data_dir / "projects" / str(project_id),
            algorithms_file=lambda project_id: (
                self.data_dir / "projects" / str(project_id) / "algorithms.json"
            ),
            storage_sources_factory=lambda: self.sources,
            storage_credentials_factory=lambda: self.credentials,
        )

    def _target(self, context, training_task_id: str):
        target = context.repository.get(training_task_id)
        if target is None:
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_TASK_MISSING",
                "target training task does not exist",
                target_status=TaskStatus.FAILED,
            )
        if target.kind is not TaskKind.TRAINING:
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_TASK_KIND_INVALID",
                "preparation target is not a TRAINING task",
                target_status=TaskStatus.FAILED,
            )
        if target.status is TaskStatus.CANCELLED:
            raise InterruptedError("target training task was cancelled during input preparation")
        if target.status is not TaskStatus.QUEUED:
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_TASK_NOT_QUEUED",
                f"target training task is no longer queued: {target.status.value}",
                target_status=TaskStatus.FAILED,
            )
        return target

    def _storage(self, project_id: str):
        config = self.model_artifacts.repository.config()
        source_id = str(config.get("storage_source_id") or "").strip()
        if not source_id:
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_STORAGE_REQUIRED",
                "remote training requires a configured object storage source",
            )
        source = self.sources.get(source_id)
        if source is None or not source.enabled:
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_STORAGE_UNAVAILABLE",
                "configured remote training storage source is unavailable",
            )
        try:
            storage_type = StorageType.parse(source.type)
        except ValueError as error:
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_STORAGE_INVALID",
                "configured remote training storage type is invalid",
            ) from error
        if storage_type not in {StorageType.OSS, StorageType.S3}:
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_STORAGE_NOT_PORTABLE",
                "remote training requires OSS/S3/MinIO object storage; local storage is not portable",
            )
        secret = self.credentials.get(source.secret_ref) if source.secret_ref else {}
        if self.provider_factory is not None:
            provider = self.provider_factory(str(project_id), source, secret or {})
        else:
            provider = StorageProviderFactory(
                data_dir=self.data_dir,
                project_dir=self.data_dir / "projects" / str(project_id),
                credentials={source.id: secret or {}},
            ).create(source)
        return source, provider

    def _heartbeat(self, context, progress: float, stage: str, current_item: str) -> None:
        context.heartbeat(progress=progress, stage=stage, current_item=current_item)

    def _prepare_bundle(self, context, training_task, payload: Mapping[str, Any]):
        project = self.data_dir / "projects" / training_task.project_id
        if not (project / "meta.json").is_file():
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_PROJECT_MISSING",
                "training project does not exist",
                target_status=TaskStatus.FAILED,
            )
        train_image_ids = tuple(payload.get("train_image_ids") or ())
        test_image_ids = tuple(payload.get("test_image_ids") or ())
        if not train_image_ids:
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_INPUT_EMPTY",
                "remote training has no selected training images",
                target_status=TaskStatus.FAILED,
            )
        if payload.get("train_dataset_ids") or payload.get("test_dataset_ids"):
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_LEGACY_DATASET_FIELDS",
                "remote training only accepts explicit train_image_ids/test_image_ids",
                target_status=TaskStatus.FAILED,
            )

        materials = MaterialRepository(project)
        images = _selected_project_images(
            materials,
            project,
            (*train_image_ids, *test_image_ids),
        )
        split_request = SplitRequest(
            mode=SplitMode(str(payload.get("split_mode"))),
            train_image_ids=train_image_ids,
            test_image_ids=test_image_ids,
            experiment_percent=payload.get("experiment_percent"),
            validation_percent=float(payload.get("validation_percent") or 20),
        )
        schema = _label_schema(project)
        seed = int(payload.get("seed") or 0)
        cache = TrainingBundleCache(self.data_dir, training_task.project_id)
        split_manifest = None
        snapshot = None
        cache_entry = None

        self._heartbeat(context, 5, "locking_snapshot", "锁定远程训练数据快照")
        if _indexed_content_identity_ready(images):
            split_manifest = build_split_manifest(images, split_request, seed=seed)
            snapshot = build_snapshot(images, split_manifest, schema)
            cache_entry = cache.resolve(str(snapshot["snapshot_id"]))

        target_work = context.artifacts.artifact_path(training_task.task_id, "work")
        if cache_entry is not None:
            self._heartbeat(context, 20, "materializing_bundle", "复用已验证训练数据缓存")
            bundle, cache_stats = cache.restore(cache_entry, target_work)
            context.artifacts.atomic_write_json(
                training_task.task_id,
                "bundle-cache.json",
                {
                    "cache_hit": True,
                    "snapshot_id": snapshot["snapshot_id"],
                    "source_validation": "verified_snapshot_cache",
                    **cache_stats,
                },
            )
        else:
            self._heartbeat(context, 10, "materializing_sources", "读取并校验训练素材")
            storage = StorageManager(
                data_dir=self.data_dir,
                project_id=training_task.project_id,
                materials=materials,
                credentials=self.credentials,
            )
            materialized: dict[str, Path] = {}
            total = len(images)
            for index, row in enumerate(images, start=1):
                target = self._target(context, training_task.task_id)
                if target.status is not TaskStatus.QUEUED:
                    raise InterruptedError("target training task left queue during preparation")
                resolved = storage.materialize(row)
                row["content_sha256"] = resolved.content_sha256
                row["size_bytes"] = resolved.size_bytes
                materialized[str(row.get("id"))] = Path(resolved.path).resolve()
                if index == 1 or index == total or index % max(1, total // 50) == 0:
                    self._heartbeat(
                        context,
                        10 + (30 * index / max(1, total)),
                        "materializing_sources",
                        f"校验训练素材 {index}/{total}",
                    )
            split_manifest = build_split_manifest(images, split_request, seed=seed)
            snapshot = build_snapshot(images, split_manifest, schema)
            self._heartbeat(context, 42, "materializing_bundle", "生成 portable 训练数据")
            bundle = materialize_portable_dataset(
                target_work,
                snapshot,
                images,
                lambda row: materialized[str(row.get("id"))],
                progress=lambda completed, total, _item: self._heartbeat(
                    context,
                    42 + (28 * completed / max(1, total)),
                    "materializing_bundle",
                    f"生成训练数据 {completed}/{total}",
                ) if (
                    completed == 1
                    or completed == total
                    or completed % max(1, total // 50) == 0
                ) else None,
            )
            context.artifacts.atomic_write_json(
                training_task.task_id,
                "bundle-cache.json",
                {
                    "cache_hit": False,
                    "snapshot_id": snapshot["snapshot_id"],
                    "source_validation": "materialized_from_source",
                },
            )

        if split_manifest is None or snapshot is None:
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_SNAPSHOT_FAILED",
                "training snapshot preparation produced no durable snapshot",
                target_status=TaskStatus.FAILED,
            )
        context.artifacts.atomic_write_json(
            training_task.task_id,
            "snapshot.json",
            snapshot,
        )
        return bundle, snapshot, split_manifest, images

    def _stage_direct_model(
        self,
        *,
        provider,
        source_id: str,
        project_id: str,
        task_id: str,
        model_path: Path,
    ) -> dict[str, Any]:
        resolved = model_path.expanduser().resolve()
        if not resolved.is_file() or resolved.stat().st_size <= 0:
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_BASE_MODEL_MISSING",
                "training base model file does not exist",
                target_status=TaskStatus.FAILED,
            )
        if resolved.suffix.lower() != ".pt":
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_BASE_MODEL_INVALID",
                "Ultralytics remote training requires a .pt base model",
                target_status=TaskStatus.FAILED,
            )
        digest = _sha256(resolved)
        object_key = (
            f"training-input-models/{_safe_segment(project_id, 'project')}/"
            f"{_safe_segment(task_id, 'task')}/{digest[:16]}-{_safe_segment(resolved.name, 'model.pt')}"
        )
        if provider.exists(object_key):
            metadata = provider.stat(object_key)
        else:
            metadata = provider.upload(
                object_key,
                resolved,
                content_type="application/octet-stream",
                metadata={
                    "sha256": digest,
                    "purpose": "remote-training-base-model",
                },
            )
        if (
            int(metadata.size_bytes) != int(resolved.stat().st_size)
            or str(metadata.sha256 or "").strip().lower() != digest
        ):
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_BASE_MODEL_UPLOAD_INVALID",
                "remote training base model object failed size/SHA256 verification",
            )
        return {
            "type": "object",
            "storage_source_id": str(source_id),
            "object_key": object_key,
            "file_name": resolved.name,
            "content_type": mimetypes.guess_type(resolved.name)[0] or "application/octet-stream",
            "sha256": digest,
            "size_bytes": int(resolved.stat().st_size),
        }

    def _prepare_base_model(
        self,
        *,
        provider,
        source_id: str,
        project_id: str,
        task_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        algorithms = list_algorithms(
            self.data_dir / "projects" / project_id / "algorithms.json"
        )
        algorithm = next(
            (
                item
                for item in algorithms
                if str(item.get("id") or "") == str(payload.get("algorithm_asset_id") or "")
            ),
            None,
        )
        if algorithm is None:
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_ALGORITHM_MISSING",
                "training algorithm no longer exists",
                target_status=TaskStatus.FAILED,
            )
        mother = str(payload.get("model") or "").strip()
        versions = list(algorithm.get("versions") or [])
        base = choose_algorithm_iteration_base(
            algorithm,
            mother,
            "ultralytics",
            strict_latest=bool(versions),
            artifact_validator=lambda path: path.is_file() and path.stat().st_size > 0,
        )
        base_path = str(base.get("base_model_path") or mother).strip()

        if not versions:
            canonical = next(
                (
                    name
                    for name in OFFICIAL_DOWNLOADABLE_MODELS
                    if str(name).casefold() == base_path.casefold()
                ),
                None,
            )
            if canonical is not None and "/" not in base_path and "\\" not in base_path:
                return {
                    "type": "official",
                    "reference": canonical,
                    "base_selection_reason": str(base.get("base_selection_reason") or "mother_model"),
                }
            return {
                **self._stage_direct_model(
                    provider=provider,
                    source_id=source_id,
                    project_id=project_id,
                    task_id=task_id,
                    model_path=Path(base_path),
                ),
                "base_selection_reason": str(base.get("base_selection_reason") or "mother_model"),
            }

        version_id = str(base.get("base_version_id") or "")
        version = next(
            (item for item in versions if str(item.get("id") or "") == version_id),
            None,
        )
        if version is None:
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_BASE_VERSION_MISSING",
                "latest training base version cannot be resolved",
                target_status=TaskStatus.FAILED,
            )
        resolved_base = Path(base_path).expanduser().resolve()
        candidates = self.model_artifacts.discover_version_artifacts(
            project_id,
            algorithm,
            version,
        )
        candidate = next(
            (
                item
                for item in candidates
                if str(item.get("target") or "") == "original"
                and Path(str(item.get("source_path") or "")).expanduser().resolve() == resolved_base
            ),
            None,
        )
        if candidate is None:
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_BASE_ARTIFACT_MISSING",
                "latest algorithm version has no verifiable original model artifact",
                target_status=TaskStatus.FAILED,
            )
        row = self.model_artifacts.ensure_uploaded(candidate)
        if (
            str(row.get("storage_status") or "").upper() != "UPLOADED"
            or str(row.get("storage_source_id") or "") != source_id
            or not str(row.get("object_key") or "")
        ):
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_BASE_ARTIFACT_UPLOAD_FAILED",
                str(row.get("storage_error") or "latest base model is not uploaded to remote storage"),
            )
        metadata = provider.stat(str(row["object_key"]))
        digest = str(row.get("sha256") or "").strip().lower()
        if (
            int(metadata.size_bytes) != int(row.get("size_bytes") or 0)
            or not str(metadata.sha256 or "").strip()
            or str(metadata.sha256).strip().lower() != digest
        ):
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_BASE_ARTIFACT_UNVERIFIED",
                "latest base model object is missing matching size/SHA256 evidence",
            )
        return {
            "type": "object",
            "artifact_id": str(row.get("artifact_id") or ""),
            "storage_source_id": source_id,
            "object_key": str(row["object_key"]),
            "file_name": str(row["file_name"]),
            "content_type": mimetypes.guess_type(str(row["file_name"]))[0]
            or "application/octet-stream",
            "sha256": digest,
            "size_bytes": int(row["size_bytes"]),
            "base_version_id": version_id,
            "base_version_name": str(base.get("base_version_name") or ""),
            "base_selection_reason": str(base.get("base_selection_reason") or ""),
        }

    def run(self, context):
        prep_payload = context.artifacts.read_json(
            context.task.task_id,
            context.task.payload_ref,
            default={},
        )
        if not isinstance(prep_payload, dict):
            raise ValueError("remote training preparation payload is invalid")
        training_task_id = str(prep_payload.get("training_task_id") or "").strip()
        if not training_task_id:
            raise ValueError("remote training preparation has no target task id")

        try:
            target = self._target(context, training_task_id)
            payload = context.artifacts.read_json(
                training_task_id,
                target.payload_ref,
                default={},
            )
            if not isinstance(payload, dict):
                raise RemoteTrainingPreparationError(
                    "REMOTE_TRAINING_PAYLOAD_INVALID",
                    "target training payload is invalid",
                    target_status=TaskStatus.FAILED,
                )
            if str(payload.get("target") or "").strip().lower() != "remote":
                raise RemoteTrainingPreparationError(
                    "REMOTE_TRAINING_TARGET_INVALID",
                    "preparation target is not configured for remote training",
                    target_status=TaskStatus.FAILED,
                )
            if str(payload.get("framework") or "ultralytics").strip().lower() != "ultralytics":
                raise RemoteTrainingPreparationError(
                    "REMOTE_TRAINING_FRAMEWORK_UNSUPPORTED",
                    "remote Agent training currently supports Ultralytics only",
                )
            existing = payload.get("remote_execution")
            if (
                isinstance(existing, Mapping)
                and int(existing.get("version") or 0) == 1
                and str(existing.get("task_kind") or "") == "TRAINING"
                and str(existing.get("transport") or "") == "object-storage-v1"
            ):
                result = {
                    "training_task_id": training_task_id,
                    "status": "already_ready",
                    "snapshot_id": str(
                        ((existing.get("training") or {}).get("snapshot_id"))
                        if isinstance(existing.get("training"), Mapping)
                        else ""
                    ),
                }
                context.artifacts.atomic_write_json(
                    context.task.task_id,
                    "result.json",
                    result,
                )
                return TaskStatus.SUCCEEDED, "result.json"

            source, provider = self._storage(target.project_id)
            bundle, snapshot, split_manifest, images = self._prepare_bundle(
                context,
                target,
                payload,
            )
            self._target(context, training_task_id)
            self._heartbeat(context, 72, "archiving_bundle", "归档 portable 训练数据")
            archive = create_training_bundle_archive(
                bundle,
                context.artifacts.artifact_path(
                    training_task_id,
                    "remote-training/training-bundle.zip",
                ),
            )
            self._heartbeat(context, 78, "uploading_bundle", "上传训练数据到对象存储")
            bundle_ref = stage_training_bundle_object(
                project_id=target.project_id,
                archive=archive,
                source_id=source.id,
                provider=provider,
            )
            self._heartbeat(context, 88, "preparing_base_model", "准备训练基础模型")
            model_ref = self._prepare_base_model(
                provider=provider,
                source_id=source.id,
                project_id=target.project_id,
                task_id=training_task_id,
                payload=payload,
            )
            self._target(context, training_task_id)

            remote_execution = {
                "version": 1,
                "task_kind": "TRAINING",
                "transport": "object-storage-v1",
                "training": {
                    "schema_version": 1,
                    "framework": "ultralytics",
                    "snapshot_id": str(snapshot.get("snapshot_id") or ""),
                    "bundle": bundle_ref,
                    "model": model_ref,
                    "params": _portable_params(payload),
                    "counts": dict(getattr(split_manifest, "counts", {}) or {}),
                    "selected_image_count": len(images),
                },
            }
            updated_payload = {
                **payload,
                "remote_input_state": "READY",
                "remote_prepare_task_id": context.task.task_id,
                "remote_execution": remote_execution,
            }
            context.artifacts.atomic_write_json(
                training_task_id,
                target.payload_ref,
                updated_payload,
            )
            result = {
                "training_task_id": training_task_id,
                "status": "ready",
                "snapshot_id": remote_execution["training"]["snapshot_id"],
                "bundle": bundle_ref,
                "model": model_ref,
            }
            context.artifacts.atomic_write_json(
                context.task.task_id,
                "result.json",
                result,
            )
            self._heartbeat(context, 100, "ready", "远程训练输入已就绪")
            return TaskStatus.SUCCEEDED, "result.json"
        except InterruptedError:
            raise
        except RemoteTrainingPreparationError as error:
            current = context.repository.get(training_task_id) if training_task_id else None
            if current is not None and current.status is TaskStatus.QUEUED:
                context.repository.fail_queued_precondition(
                    training_task_id,
                    f"{error.code}: {error}",
                    status=error.target_status,
                    stage="remote_input_preparation_failed",
                )
            raise
        except (RemoteTrainingTransportError, Exception) as error:
            current = context.repository.get(training_task_id) if training_task_id else None
            if current is not None and current.status is TaskStatus.QUEUED:
                context.repository.fail_queued_precondition(
                    training_task_id,
                    f"REMOTE_TRAINING_PREPARATION_FAILED: {error}",
                    status=TaskStatus.FAILED,
                    stage="remote_input_preparation_failed",
                )
            raise


def worker_registration(data_dir: Path):
    return {
        "handlers": {
            TaskKind.TRAINING_PREPARE: RemoteTrainingPrepareHandler(data_dir),
        },
        "capabilities": {"training.prepare"},
    }


__all__ = [
    "RemoteTrainingPreparationError",
    "RemoteTrainingPrepareHandler",
    "worker_registration",
]
