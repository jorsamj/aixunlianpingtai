"""Durable control-plane preparation for portable remote TRAINING tasks."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from pathlib import Path
from typing import Any, Mapping

from .algorithms import choose_algorithm_iteration_base, list_algorithms, resolve_current_version_id
from .annotations import atomic_write_json
from .annotation_repository import AnnotationRepository
from .external_algorithm_platform import (
    ExternalAlgorithmPlatformService,
    assert_external_algorithm_master_data_current,
    resolve_external_training_analysis,
)
from .errors import PlatformError
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
from .training_label_tasks import project_training_rows, resolve_training_label_contract
from .training_compatibility import (
    evaluate_selection_compatibility,
    persist_compatibility_issues,
)
from .training_resource_policy import auto_admission_evidence
from .training_splits import (
    SplitMode,
    SplitRequest,
    build_split_manifest,
    exclude_reserved_test_components,
)
from .training_tasks import (
    _indexed_content_identity_ready,
    _label_schema,
    _selected_project_images,
    freeze_training_inputs,
    materialize_portable_dataset,
    resolve_frozen_training_base,
    resolve_training_selection,
    resolve_training_input_freeze,
)
from .snapshots import (
    build_snapshot,
    dataset_revision_document,
    persist_dataset_revision,
)


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
        "epochs", "imgsz", "batch", "patience", "early_stopping_enabled", "workers", "optimizer",
        "lr0", "lrf", "weight_decay", "close_mosaic", "mosaic", "cache",
        "freeze", "momentum", "warmup_epochs", "save_period", "seed",
        "multi_scale", "hsv_h", "hsv_s", "hsv_v", "degrees", "translate",
        "scale", "shear", "perspective", "flipud", "fliplr", "mixup",
        "val_max_samples", "eval_interval", "eval_metric",
        "continue_threshold", "stop_threshold", "single_cls", "pretrained",
        "rect", "amp", "cos_lr", "deterministic", "auto_supplement",
        "ai_intervention_enabled", "supplement_count", "resource_strategy",
        "resource_profile", "gpu_policy", "precision", "time",
    )
    result = {}
    for key in keys:
        if key not in payload:
            continue
        value = payload[key]
        if value is None or isinstance(value, (str, int, float, bool)):
            result[key] = value
    result["runtime_stop_policy"] = "target_only"
    return result


class TrainingPrepareHandler:
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

    def _refresh_external_algorithm(self, project_id: str, algorithm: Mapping[str, Any]):
        if (
            str(algorithm.get("source_type") or "").upper() != "EXTERNAL"
            or str(algorithm.get("provider_type") or "").upper() != "CHANG_LIAN"
        ):
            return dict(algorithm)
        service = ExternalAlgorithmPlatformService(
            data_dir=self.data_dir,
            secret_store_factory=KeyringSecretStore,
        )
        try:
            result = service.training_preflight(
                project_id=project_id,
                algorithms_path=self.data_dir / "projects" / project_id / "algorithms.json",
                algorithm_id=str(algorithm.get("id") or ""),
            )
        except PlatformError as error:
            raise RemoteTrainingPreparationError(
                error.code,
                error.message,
                target_status=TaskStatus.FAILED,
            ) from error
        fresh = result.get("algorithm") if isinstance(result, Mapping) else None
        if not isinstance(fresh, Mapping):
            raise RemoteTrainingPreparationError(
                "TRAINING_ALGORITHM_PREFLIGHT_INVALID",
                "external training preflight returned no algorithm truth",
                target_status=TaskStatus.FAILED,
            )
        return dict(fresh)

    def _resolve_benchmark_reuse(
        self,
        project: Path,
        algorithm: Mapping[str, Any],
        payload: Mapping[str, Any],
        split: SplitRequest,
    ):
        requested_version = str(payload.get("benchmark_source_version_id") or "").strip()
        requested_scope = str(payload.get("benchmark_scope_id") or "").strip().lower()
        if not requested_version and not requested_scope:
            return split, None
        if not requested_version or not re.fullmatch(r"[0-9a-f]{64}", requested_scope):
            raise RemoteTrainingPreparationError(
                "TRAINING_BENCHMARK_IDENTITY_INVALID",
                "复用评测基准需要有效的来源版本和 Benchmark Scope",
                target_status=TaskStatus.FAILED,
            )
        if split.test_image_ids:
            raise RemoteTrainingPreparationError(
                "TRAINING_BENCHMARK_TEST_CONFLICT",
                "复用固定评测基准时不能同时提交前端试验素材清单",
                target_status=TaskStatus.FAILED,
            )
        current_version_id = str(resolve_current_version_id(algorithm) or "")
        if current_version_id != requested_version:
            raise RemoteTrainingPreparationError(
                "TRAINING_BENCHMARK_VERSION_CHANGED",
                "算法当前版本已变化，不能继续复用旧版本评测基准",
                target_status=TaskStatus.FAILED,
            )
        version = next(
            (
                row for row in (algorithm.get("versions") or [])
                if str(row.get("id") or row.get("version_id") or "") == current_version_id
            ),
            None,
        )
        evaluation = version.get("evaluation") if isinstance(version, Mapping) else {}
        evaluation = evaluation if isinstance(evaluation, Mapping) else {}
        scope = evaluation.get("benchmark_scope")
        scope = scope if isinstance(scope, Mapping) else {}
        if (
            str(evaluation.get("status") or "").lower() != "succeeded"
            or scope.get("binding_level") != "bundle_verified"
            or str(scope.get("scope_id") or "").lower() != requested_scope
        ):
            raise RemoteTrainingPreparationError(
                "TRAINING_BENCHMARK_SCOPE_CHANGED",
                "已归档 Benchmark Scope 已变化，不能复用",
                target_status=TaskStatus.FAILED,
            )
        snapshot_id = str(evaluation.get("snapshot_id") or version.get("snapshot_id") or "").lower()
        snapshot_path = project / "snapshots" / f"{snapshot_id}.json"
        if not re.fullmatch(r"[0-9a-f]{64}", snapshot_id) or not snapshot_path.is_file():
            raise RemoteTrainingPreparationError(
                "TRAINING_BENCHMARK_SNAPSHOT_MISSING",
                "评测基准对应的训练 Snapshot 已不存在",
                target_status=TaskStatus.FAILED,
            )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        from .training_evaluation import build_evaluation_benchmark_scope
        snapshot_scope = build_evaluation_benchmark_scope(snapshot)
        for key in ("test_image_count", "content_digest", "ground_truth_digest", "label_schema_digest"):
            if str(scope.get(key) or "") != str(snapshot_scope.get(key) or ""):
                raise RemoteTrainingPreparationError(
                    "TRAINING_BENCHMARK_TRUTH_CHANGED",
                    "已归档 Benchmark Scope 与 Snapshot truth 不一致",
                    target_status=TaskStatus.FAILED,
                )
        raw_ids = snapshot.get("test_image_ids")
        if raw_ids is None and isinstance(snapshot.get("ids"), Mapping):
            raw_ids = snapshot["ids"].get("test")
        test_ids = tuple(dict.fromkeys(str(value).strip() for value in (raw_ids or []) if str(value).strip()))
        if not test_ids or len(test_ids) != int(scope.get("test_image_count") or 0):
            raise RemoteTrainingPreparationError(
                "TRAINING_BENCHMARK_SELECTION_INVALID",
                "评测基准试验素材清单不完整",
                target_status=TaskStatus.FAILED,
            )
        materials = MaterialRepository(project)
        material_rows = materials.get_many(test_ids)
        rows_by_id = {str(row.get("id") or ""): row for row in material_rows}
        frozen_by_id = {
            str(row.get("image_id") or ""): row
            for row in (snapshot.get("images") or []) if isinstance(row, Mapping)
        }
        annotations = AnnotationRepository(project).get_many(test_ids)
        for image_id in test_ids:
            material = rows_by_id.get(image_id)
            frozen = frozen_by_id.get(image_id)
            annotation = annotations.get(image_id) or {}
            if material is None or frozen is None:
                raise RemoteTrainingPreparationError(
                    "TRAINING_BENCHMARK_MATERIAL_MISSING",
                    f"评测基准素材 {image_id} 已不存在",
                    target_status=TaskStatus.FAILED,
                )
            annotation_hash = str(annotation.get("content_digest") or material.get("annotation_hash") or "").lower()
            if (
                str(material.get("content_sha256") or "").lower() != str(frozen.get("content_sha256") or "").lower()
                or annotation_hash != str(frozen.get("annotation_hash") or "").lower()
            ):
                raise RemoteTrainingPreparationError(
                    "TRAINING_BENCHMARK_MATERIAL_CHANGED",
                    f"评测基准素材 {image_id} 已变化",
                    target_status=TaskStatus.FAILED,
                )
        selected_count = len(split.train_image_ids)
        all_rows = materials.get_many((*split.train_image_ids, *test_ids))
        train_ids, reserved_ids = exclude_reserved_test_components(all_rows, split.train_image_ids, test_ids)
        if not train_ids:
            raise RemoteTrainingPreparationError(
                "TRAINING_BENCHMARK_TRAINING_EMPTY",
                "所选训练候选全部属于固定评测保留范围",
                target_status=TaskStatus.FAILED,
            )
        effective = SplitRequest(
            mode=SplitMode.INDEPENDENT_TEST_SET,
            train_image_ids=train_ids,
            test_image_ids=test_ids,
            experiment_percent=None,
            validation_percent=split.validation_percent,
        )
        return effective, {
            "source_algorithm_id": str(algorithm.get("id") or ""),
            "source_version_id": current_version_id,
            "scope_id": requested_scope,
            "snapshot_id": snapshot_id,
            "test_image_count": len(test_ids),
            "binding_level": "bundle_verified",
            "selected_training_candidate_count": selected_count,
            "reserved_training_candidate_count": len(reserved_ids),
            "effective_training_candidate_count": len(train_ids),
        }

    def _resolve_supplement_candidate_set(
        self,
        project: Path,
        algorithm: Mapping[str, Any],
        payload: Mapping[str, Any],
        split: SplitRequest,
    ):
        requested_id = str(payload.get("supplement_candidate_set_id") or "").strip().lower()
        current_version_id = str(algorithm.get("current_version_id") or "")
        version = next(
            (row for row in (algorithm.get("versions") or []) if str(row.get("id") or "") == current_version_id),
            None,
        )
        candidate = version.get("supplement_data_candidate_set") if isinstance(version, Mapping) else None
        if not isinstance(candidate, Mapping) or not str(candidate.get("candidate_set_id") or ""):
            if requested_id:
                raise RemoteTrainingPreparationError(
                    "TRAINING_SUPPLEMENT_SET_MISSING",
                    "当前算法版本没有可用的补数据 Candidate Set",
                    target_status=TaskStatus.FAILED,
                )
            return None
        selected_ids = {str(value) for value in (*split.train_image_ids, *split.test_image_ids) if str(value)}
        candidate_ids = {str(value) for value in (candidate.get("material_ids") or []) if str(value)}
        adopted_ids = sorted(selected_ids.intersection(candidate_ids))
        if not adopted_ids:
            if requested_id:
                raise RemoteTrainingPreparationError(
                    "TRAINING_SUPPLEMENT_SELECTION_EMPTY",
                    "本次训练未实际选择 Candidate Set 中的素材",
                    target_status=TaskStatus.FAILED,
                )
            return None
        candidate_id = str(candidate.get("candidate_set_id") or "").strip().lower()
        if requested_id != candidate_id:
            raise RemoteTrainingPreparationError(
                "TRAINING_SUPPLEMENT_SET_CHANGED",
                "训练请求缺少或使用了过期的 Candidate Set",
                target_status=TaskStatus.FAILED,
            )
        materials = MaterialRepository(project)
        by_id = {str(row.get("id") or ""): row for row in materials.get_many(adopted_ids)}
        annotations = AnnotationRepository(project).get_many(adopted_ids)
        truth_rows = []
        for image_id in adopted_ids:
            material = by_id.get(image_id)
            if material is None:
                raise RemoteTrainingPreparationError(
                    "TRAINING_SUPPLEMENT_MATERIAL_MISSING",
                    f"补数据素材 {image_id} 已不存在",
                    target_status=TaskStatus.FAILED,
                )
            annotation = annotations.get(image_id) or {}
            truth_rows.append({
                "id": image_id,
                "content_sha256": str(material.get("content_sha256") or ""),
                "annotation_hash": str(annotation.get("content_digest") or material.get("annotation_hash") or ""),
                "annotation_state": str(annotation.get("annotation_state") or material.get("annotation_state") or "unannotated"),
            })
        from .online_feedback import build_supplement_training_provenance
        build_supplement_training_provenance(candidate, selected_ids, truth_rows)
        return dict(candidate)

    def _freeze_request_contract(self, context, target, payload: Mapping[str, Any]):
        project = self.data_dir / "projects" / target.project_id
        algorithms = list_algorithms(project / "algorithms.json")
        algorithm = next(
            (row for row in algorithms if str(row.get("id") or "") == str(payload.get("algorithm_asset_id") or "")),
            None,
        )
        if algorithm is None:
            raise RemoteTrainingPreparationError(
                "TRAINING_ALGORITHM_MISSING",
                "training algorithm no longer exists",
                target_status=TaskStatus.FAILED,
            )
        algorithm = self._refresh_external_algorithm(target.project_id, algorithm)
        assert_external_algorithm_master_data_current(self.data_dir, algorithm)
        external_analysis_id = resolve_external_training_analysis(
            algorithm, payload.get("external_analysis_id"),
        )
        split = SplitRequest(
            mode=SplitMode(str(payload.get("split_mode"))),
            train_image_ids=tuple(payload.get("train_image_ids") or ()),
            test_image_ids=tuple(payload.get("test_image_ids") or ()),
            experiment_percent=payload.get("experiment_percent"),
            validation_percent=float(payload.get("validation_percent") or 20),
        )
        split, benchmark_reuse = self._resolve_benchmark_reuse(project, algorithm, payload, split)
        selection = resolve_training_selection(project, split)
        effective_split = selection.effective_split
        supplement = self._resolve_supplement_candidate_set(project, algorithm, payload, effective_split)
        label_request = dict(payload)
        label_request.update(
            train_image_ids=list(effective_split.train_image_ids),
            test_image_ids=list(effective_split.test_image_ids),
            selected_image_ids=list(effective_split.train_image_ids),
        )
        label_contract = resolve_training_label_contract(
            self.data_dir, project, label_request, algorithm,
        )
        compatibility = evaluate_selection_compatibility(
            project,
            selection,
            label_contract,
        )
        if compatibility.issues:
            manifest = persist_compatibility_issues(
                context.artifacts,
                target.task_id,
                compatibility,
            )
            raise RemoteTrainingPreparationError(
                "TRAINING_MATERIAL_SCOPE_INCOMPATIBLE",
                "TRAINING_MATERIAL_SCOPE_INCOMPATIBLE: "
                f"{manifest['issue_count']} 张训练素材需要补审或排除",
                target_status=TaskStatus.FAILED,
            )
        projected = project_training_rows(selection.effective_images, label_contract)
        frozen = freeze_training_inputs(
            project,
            split,
            seed=int(payload.get("seed") or 0),
            supplement_candidate_set=supplement,
            selection_resolution=selection,
            effective_images=projected,
            label_schema_override=label_contract["effective_label_schema"],
            label_contract=label_contract,
        )
        context.artifacts.atomic_write_json(target.task_id, "input-freeze.json", frozen)
        truth = selection.truth()
        updated = {
            **payload,
            "schema_version": 4,
            "split_mode": effective_split.mode.value,
            "train_image_ids": list(effective_split.train_image_ids),
            "test_image_ids": list(effective_split.test_image_ids),
            "selected_train_image_ids": list(selection.selected_train_image_ids),
            "pending_annotation_image_ids": list(selection.pending_annotation_image_ids),
            "selection_counts": {
                "selected_train_count": int(truth["selected_train_count"]),
                "effective_train_count": int(truth["effective_train_count"]),
                "pending_annotation_count": int(truth["pending_annotation_count"]),
                "test_count": int(truth["test_count"]),
            },
            "selection_truth": truth,
            "experiment_percent": effective_split.experiment_percent,
            "validation_percent": effective_split.validation_percent,
            "external_analysis_id": external_analysis_id,
            "supplement_candidate_set": supplement,
            "benchmark_reuse": benchmark_reuse,
            "input_freeze_ref": "input-freeze.json",
            "input_freeze_id": frozen["input_freeze_id"],
            "snapshot_id": frozen["snapshot_id"],
            "dataset_revision_id": frozen["dataset_revision_id"],
            "input_quality": frozen["input_quality"],
            "label_contract": frozen.get("label_contract") or {},
            "base_version_id": label_contract.get("base_version_id") or None,
            "base_version_name": label_contract.get("base_version_name") or "",
            "base_training_mode": label_contract.get("base_training_mode") or "",
            "base_model_reference": label_contract.get("base_model_reference") or "",
            "base_model_sha256": label_contract.get("base_model_sha256") or "",
            "base_model_size_bytes": int(label_contract.get("base_model_size_bytes") or 0),
            "base_selection_reason": label_contract.get("base_selection_reason") or "",
        }
        return updated

    def _publish_prepared_job(self, target, payload: Mapping[str, Any]) -> None:
        job_file = (
            self.data_dir / "projects" / target.project_id / "jobs"
            / target.task_id / "job.json"
        )
        try:
            job = json.loads(job_file.read_text(encoding="utf-8")) if job_file.is_file() else {}
        except (OSError, ValueError):
            job = {}
        counts = dict(payload.get("selection_counts") or {})
        job.update({
            "id": target.task_id,
            "task_id": target.task_id,
            "status": "queued",
            "task_stage": "training_input_pending",
            "phase": "training_input_pending",
            "message": "训练输入已核验，正在完成后台准备",
            "asset_algorithm_id": payload.get("asset_algorithm_id") or payload.get("algorithm_asset_id"),
            "algorithm_asset_id": payload.get("algorithm_asset_id") or payload.get("asset_algorithm_id"),
            "asset_algorithm_name": payload.get("asset_algorithm_name") or "已删除算法",
            "selected_train_images": int(counts.get("selected_train_count") or 0),
            "effective_train_images": int(counts.get("effective_train_count") or 0),
            "pending_annotation_images": int(counts.get("pending_annotation_count") or 0),
            "selection_truth": counts,
            "input_freeze_id": payload.get("input_freeze_id"),
            "snapshot_id": payload.get("snapshot_id"),
            "dataset_revision_id": payload.get("dataset_revision_id"),
            "input_quality": payload.get("input_quality"),
            "base_version_id": payload.get("base_version_id"),
            "base_version_name": payload.get("base_version_name") or "",
            "base_training_mode": payload.get("base_training_mode") or "",
            "benchmark_reuse": payload.get("benchmark_reuse"),
            "supplement_candidate_set_id": str(
                ((payload.get("supplement_candidate_set") or {}).get("candidate_set_id"))
                if isinstance(payload.get("supplement_candidate_set"), Mapping)
                else payload.get("supplement_candidate_set_id") or ""
            ),
        })
        atomic_write_json(job_file, job)

    def _resolve_local_resources(
        self,
        context,
        target,
        payload: Mapping[str, Any],
        bundle: Path,
        images,
        split_manifest,
    ):
        """Prepare AUTO admission evidence or resolve non-deferred local resources."""
        from ultralytics import YOLO
        from .gpu_resources import sample_gpus
        from .training_devices import normalize_training_device

        project = self.data_dir / "projects" / target.project_id
        algorithms = list_algorithms(project / "algorithms.json")
        algorithm = next(
            (row for row in algorithms if str(row.get("id") or "") == str(payload.get("algorithm_asset_id") or "")),
            None,
        )
        if algorithm is None:
            raise RemoteTrainingPreparationError(
                "TRAINING_ALGORITHM_MISSING",
                "training algorithm no longer exists",
                target_status=TaskStatus.FAILED,
            )
        base = resolve_frozen_training_base(payload)
        if base is None:
            base = choose_algorithm_iteration_base(
                algorithm,
                str(payload.get("model") or ""),
                str(payload.get("framework") or "ultralytics"),
                strict_latest=bool(algorithm.get("versions")),
                artifact_validator=lambda path: path.is_file() and path.stat().st_size > 0,
            )
        model_path = str(base.get("base_model_path") or payload.get("model") or "").strip()
        requested_device = normalize_training_device(
            payload.get("requested_device", payload.get("device")),
        )
        sampled = [row for row in sample_gpus() if row.get("telemetry_available")]
        strategy = str(payload.get("resource_strategy") or "auto").strip().lower()
        gpu_policy = str(payload.get("gpu_policy") or "auto").strip().lower()
        if (
            requested_device == "auto"
            and strategy == "auto"
            and gpu_policy in {"auto", "exclusive"}
            and sampled
        ):
            model = YOLO(model_path)
            admission = auto_admission_evidence(payload, model)
            admission.update({
                "candidate_gpu_count": len(sampled),
                "candidate_gpu_uuids": [
                    str(row.get("gpu_uuid") or "")
                    for row in sampled
                    if str(row.get("gpu_uuid") or "")
                ],
            })
            context.artifacts.atomic_write_json(
                target.task_id, "resource-admission.json", admission,
            )
            resolution_path = context.artifacts.artifact_path(
                target.task_id, "resolved-resources.json",
            )
            return {
                **payload,
                "resource_resolution_deferred": True,
                "resource_admission_ref": "resource-admission.json",
                "gpu_memory_floor_bytes": int(admission["gpu_memory_floor_bytes"]),
                "estimated_gpu_memory_bytes": None,
                "resource_resolution": str(resolution_path),
                "metrics_db": str(context.artifacts.artifact_path(
                    target.task_id, "training-metrics.sqlite3",
                )),
            }

        import torch
        from .training_metrics import resolve_resources

        resolution_device = requested_device
        selected_gpu = None
        if requested_device == "auto" and sampled:
            # Resolve against the most constrained currently schedulable GPU so
            # the later scheduler assignment cannot make an AUTO plan unsafe.
            selected_gpu = min(sampled, key=lambda row: int(row.get("free_bytes") or 0))
            resolution_device = f"cuda:{int(selected_gpu.get('logical_cuda_index') or 0)}"
        elif requested_device.startswith("cuda:"):
            index = int(requested_device.split(":", 1)[1])
            selected_gpu = next(
                (
                    row for row in sampled
                    if int(row.get("logical_cuda_index") or row.get("physical_index") or -1) == index
                ),
                None,
            )
        if requested_device.startswith("cuda:") and selected_gpu is None:
            raise RemoteTrainingPreparationError(
                "RESOURCE_GPU_TELEMETRY_UNAVAILABLE",
                "指定 GPU 缺少可验证的资源遥测，无法在训练前核验配置",
                target_status=TaskStatus.BLOCKED_BY_HARDWARE,
            )
        if requested_device == "auto" and not sampled:
            resolution_device = "cpu"

        with context.repository._connect() as database:
            reservations = database.execute("SELECT * FROM gpu_reservations").fetchall()
        gpu_uuid = str((selected_gpu or {}).get("gpu_uuid") or "")
        resource_context = {
            "gpu_uuid": gpu_uuid or None,
            "reserved_bytes": None,
            "concurrent_reservations": max(1, len(reservations) + 1),
            "other_reserved_bytes": sum(
                int(row["reserved_bytes"] or 0)
                for row in reservations
                if not gpu_uuid or str(row["gpu_uuid"] or "") == gpu_uuid
            ),
            "dataset_bytes": sum(int(row.get("size_bytes") or 0) for row in images),
            "train_image_count": int(split_manifest.counts.get("train", 0)),
            "decoded_dataset_bytes": (
                sum(
                    max(
                        int(row["width"]) * int(row["height"]),
                        int(payload.get("imgsz") or 640) ** 2,
                    ) * 3
                    for row in images
                )
                if images and all(row.get("width") and row.get("height") for row in images)
                else None
            ),
            "remote_cache_ready": True,
            "resolution_device": resolution_device,
            "resolution_gpu_uuid": gpu_uuid or None,
        }
        request = {
            **payload,
            "data": str(bundle / "manifest.json"),
            "device": resolution_device,
        }
        model = YOLO(model_path)
        resolved = resolve_resources(request, resource_context, model, torch)
        resolution_path = context.artifacts.artifact_path(
            target.task_id, "resolved-resources.json",
        )
        context.artifacts.atomic_write_json(
            target.task_id, "resolved-resources.json", resolved,
        )
        context.artifacts.atomic_write_json(
            target.task_id, "resource-context.json", resource_context,
        )
        return {
            **payload,
            "resource_context": str(context.artifacts.artifact_path(target.task_id, "resource-context.json")),
            "resource_resolution": str(resolution_path),
            "metrics_db": str(context.artifacts.artifact_path(target.task_id, "training-metrics.sqlite3")),
            "resolved_resources": resolved,
            "resolved_batch": int(resolved["resolved_batch"]),
            "resolved_workers": int(resolved["resolved_workers"]),
            "resolved_cache": resolved["resolved_cache"],
            "estimated_gpu_memory_bytes": resolved.get("estimated_gpu_memory_bytes"),
        }

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
        split_request = SplitRequest(
            mode=SplitMode(str(payload.get("split_mode"))),
            train_image_ids=train_image_ids,
            test_image_ids=test_image_ids,
            experiment_percent=payload.get("experiment_percent"),
            validation_percent=float(payload.get("validation_percent") or 20),
        )
        seed = int(payload.get("seed") or 0)
        freeze_ref = str(payload.get("input_freeze_ref") or "").strip()
        self._heartbeat(context, 5, "locking_snapshot", "锁定远程训练数据快照")
        if freeze_ref:
            frozen = context.artifacts.read_json(
                training_task.task_id,
                freeze_ref,
                default={},
            )
            if not isinstance(frozen, Mapping):
                raise RemoteTrainingPreparationError(
                    "REMOTE_TRAINING_INPUT_FREEZE_INVALID",
                    "training input freeze is invalid",
                    target_status=TaskStatus.FAILED,
                )
            try:
                images, schema, split_manifest, snapshot = resolve_training_input_freeze(
                    frozen,
                    split_request,
                    seed=seed,
                    supplement_candidate_set=payload.get("supplement_candidate_set"),
                )
            except (TypeError, ValueError) as error:
                raise RemoteTrainingPreparationError(
                    "REMOTE_TRAINING_INPUT_FREEZE_INVALID",
                    str(error),
                    target_status=TaskStatus.FAILED,
                ) from error
            if str(frozen.get("input_freeze_id") or "") != str(
                payload.get("input_freeze_id") or ""
            ):
                raise RemoteTrainingPreparationError(
                    "REMOTE_TRAINING_INPUT_FREEZE_MISMATCH",
                    "training payload freeze identity mismatch",
                    target_status=TaskStatus.FAILED,
                )
        else:
            # Compatibility only for tasks created before submit-time freezing.
            images = _selected_project_images(
                materials,
                project,
                (*train_image_ids, *test_image_ids),
            )
            schema = _label_schema(project)
            split_manifest = build_split_manifest(images, split_request, seed=seed)
            snapshot = build_snapshot(
                images,
                split_manifest,
                schema,
                supplement_candidate_set=payload.get("supplement_candidate_set"),
            )
        cache = TrainingBundleCache(self.data_dir, training_task.project_id)
        cache.root.mkdir(parents=True, exist_ok=True)
        cache_entry = (
            cache.resolve(str(snapshot["snapshot_id"]))
            if _indexed_content_identity_ready(images)
            else None
        )

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
                frozen_sha256 = str(row.get("content_sha256") or "").strip().lower()
                resolved = storage.materialize(row)
                if str(resolved.content_sha256 or "").strip().lower() != frozen_sha256:
                    raise RemoteTrainingPreparationError(
                        "REMOTE_TRAINING_SOURCE_CHANGED",
                        f"training source content changed after submit: {row.get('id')}",
                        target_status=TaskStatus.FAILED,
                    )
                row["size_bytes"] = resolved.size_bytes
                materialized[str(row.get("id"))] = Path(resolved.path).resolve()
                if index == 1 or index == total or index % max(1, total // 50) == 0:
                    self._heartbeat(
                        context,
                        10 + (30 * index / max(1, total)),
                        "materializing_sources",
                        f"校验训练素材 {index}/{total}",
                    )
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
        revision = dataset_revision_document(snapshot)
        persist_dataset_revision(project / "dataset_revisions", snapshot)
        context.artifacts.atomic_write_json(
            training_task.task_id,
            "snapshot.json",
            snapshot,
        )
        context.artifacts.atomic_write_json(
            training_task.task_id,
            "dataset-revision.json",
            revision,
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
        try:
            base = resolve_frozen_training_base(payload)
        except ValueError as error:
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_BASE_CONTRACT_INVALID",
                str(error),
                target_status=TaskStatus.FAILED,
            ) from error
        if base is None:
            # Compatibility for remote tasks created before submit-time base
            # identity freezing.
            base = choose_algorithm_iteration_base(
                algorithm,
                mother,
                "ultralytics",
                strict_latest=bool(versions),
                artifact_validator=lambda path: path.is_file() and path.stat().st_size > 0,
            )

        base_path = str(base.get("base_model_path") or mother).strip()
        version_id = str(base.get("base_version_id") or "").strip()

        if not version_id:
            # Submission must have frozen a concrete local mother weight.
            # Never send a DOWNLOADABLE name to a remote Agent for implicit GitHub fetching.
            if base_path in OFFICIAL_DOWNLOADABLE_MODELS:
                raise RemoteTrainingPreparationError(
                    "REMOTE_TRAINING_BASE_MODEL_NOT_PREPARED",
                    "请先在训练资源预置 .pt 母模型；远程训练不允许自动下载",
                    target_status=TaskStatus.FAILED,
                )
            staged = self._stage_direct_model(
                provider=provider,
                source_id=source_id,
                project_id=project_id,
                task_id=task_id,
                model_path=Path(base_path),
            )
            frozen_sha = str(base.get("base_model_sha256") or "").strip().lower()
            frozen_size = int(base.get("base_model_size_bytes") or 0)
            if frozen_sha and (
                str(staged.get("sha256") or "").strip().lower() != frozen_sha
                or int(staged.get("size_bytes") or 0) != frozen_size
            ):
                raise RemoteTrainingPreparationError(
                    "REMOTE_TRAINING_BASE_MODEL_CHANGED",
                    "mother model changed after training task creation",
                    target_status=TaskStatus.FAILED,
                )
            return {
                **staged,
                "base_selection_reason": str(base.get("base_selection_reason") or "mother_model"),
                "base_training_mode": str(base.get("base_training_mode") or "mother_model_init"),
            }

        version = next(
            (item for item in versions if str(item.get("id") or "") == version_id),
            None,
        )
        if version is None:
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_BASE_VERSION_MISSING",
                "frozen training base version can no longer be resolved",
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
                "frozen algorithm version has no verifiable original model artifact",
                target_status=TaskStatus.FAILED,
            )
        row = self.model_artifacts.ensure_uploaded(candidate)
        frozen_sha = str(base.get("base_model_sha256") or "").strip().lower()
        frozen_size = int(base.get("base_model_size_bytes") or 0)
        row_sha = str(row.get("sha256") or "").strip().lower()
        row_size = int(row.get("size_bytes") or 0)
        if frozen_sha and (row_sha != frozen_sha or row_size != frozen_size):
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_BASE_ARTIFACT_CHANGED",
                "frozen base model artifact no longer matches submit-time SHA256/size",
                target_status=TaskStatus.FAILED,
            )
        if (
            str(row.get("storage_status") or "").upper() != "UPLOADED"
            or str(row.get("storage_source_id") or "") != source_id
            or not str(row.get("object_key") or "")
        ):
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_BASE_ARTIFACT_UPLOAD_FAILED",
                str(row.get("storage_error") or "frozen base model is not uploaded to remote storage"),
            )
        metadata = provider.stat(str(row["object_key"]))
        digest = row_sha
        if (
            int(metadata.size_bytes) != row_size
            or not str(metadata.sha256 or "").strip()
            or str(metadata.sha256).strip().lower() != digest
        ):
            raise RemoteTrainingPreparationError(
                "REMOTE_TRAINING_BASE_ARTIFACT_UNVERIFIED",
                "frozen base model object is missing matching size/SHA256 evidence",
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
            "size_bytes": row_size,
            "base_version_id": version_id,
            "base_version_name": str(base.get("base_version_name") or ""),
            "base_selection_reason": str(base.get("base_selection_reason") or ""),
            "base_training_mode": str(base.get("base_training_mode") or "previous_weights_init"),
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
            target_mode = str(payload.get("target") or "local").strip().lower()
            if target_mode not in {"local", "remote"}:
                raise RemoteTrainingPreparationError(
                    "TRAINING_TARGET_INVALID",
                    "training target must be local or remote",
                    target_status=TaskStatus.FAILED,
                )
            if str(payload.get("framework") or "ultralytics").strip().lower() != "ultralytics":
                raise RemoteTrainingPreparationError(
                    "TRAINING_FRAMEWORK_UNSUPPORTED",
                    "training preparation currently supports Ultralytics only",
                )
            if (
                str(payload.get("training_input_state") or "").upper() != "READY"
                and int(payload.get("schema_version") or 0) >= 4
            ):
                self._heartbeat(context, 2, "resolving_training_contract", "核验训练素材与标签合同")
                payload = self._freeze_request_contract(context, target, payload)
                context.artifacts.atomic_write_json(
                    training_task_id,
                    target.payload_ref,
                    payload,
                )
                self._publish_prepared_job(target, payload)
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
                    "dataset_revision_id": str(
                        ((existing.get("training") or {}).get("dataset_revision_id"))
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

            bundle, snapshot, split_manifest, images = self._prepare_bundle(
                context,
                target,
                payload,
            )
            prepared_input = {
                "schema_version": 1,
                "training_task_id": training_task_id,
                "snapshot_id": str(snapshot.get("snapshot_id") or ""),
                "dataset_revision_id": str(snapshot.get("dataset_revision_id") or ""),
                "bundle_path": str(bundle),
                "selected_image_count": len(images),
            }
            context.artifacts.atomic_write_json(
                training_task_id,
                "prepared-input.json",
                prepared_input,
            )
            if target_mode == "local":
                self._heartbeat(context, 82, "resolving_resources", "核验 Batch / Workers / Precision")
                payload = self._resolve_local_resources(
                    context,
                    target,
                    payload,
                    bundle,
                    images,
                    split_manifest,
                )
                updated_payload = {
                    **payload,
                    "training_input_state": "READY",
                    "training_prepare_task_id": context.task.task_id,
                    "prepared_input_ref": "prepared-input.json",
                }
                context.artifacts.atomic_write_json(
                    training_task_id,
                    target.payload_ref,
                    updated_payload,
                )
                context.repository.activate_prepared_training(
                    training_task_id,
                    resource_key=str(payload.get("target_resource_key") or "training:auto"),
                    required_capabilities=tuple(
                        payload.get("target_required_capabilities") or ("training.ultralytics",)
                    ),
                )
                result = {**prepared_input, "status": "ready", "target": "local"}
                context.artifacts.atomic_write_json(context.task.task_id, "result.json", result)
                self._heartbeat(context, 100, "ready", "本地训练输入已就绪")
                return TaskStatus.SUCCEEDED, "result.json"

            source, provider = self._storage(target.project_id)
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

            frozen_label_schema = [
                dict(item)
                for item in (snapshot.get("label_schema") or [])
                if isinstance(item, Mapping) and str(item.get("code") or "").strip()
            ]
            frozen_label_codes = [
                str(item.get("code") or "").strip()
                for item in frozen_label_schema
            ]
            freeze_ref = str(payload.get("input_freeze_ref") or "").strip()
            frozen_input = (
                context.artifacts.read_json(
                    training_task_id,
                    freeze_ref,
                    default={},
                )
                if freeze_ref else {}
            )
            frozen_label_contract = (
                dict(frozen_input.get("label_contract") or {})
                if isinstance(frozen_input, Mapping)
                else {}
            )
            if not frozen_label_contract and isinstance(payload.get("label_contract"), Mapping):
                frozen_label_contract = dict(payload.get("label_contract") or {})
            frozen_label_contract.pop("project_path", None)
            contract_codes = [
                str(value or "").strip()
                for value in (frozen_label_contract.get("effective_label_codes") or [])
                if str(value or "").strip()
            ]
            if contract_codes and contract_codes != frozen_label_codes:
                raise RemoteTrainingPreparationError(
                    "REMOTE_TRAINING_LABEL_CONTRACT_MISMATCH",
                    "frozen label contract does not match the durable dataset snapshot",
                    target_status=TaskStatus.FAILED,
                )

            dataset_bytes = sum(int(row.get("size_bytes") or 0) for row in images)
            decoded_dataset_bytes = (
                sum(
                    max(
                        int(row["width"]) * int(row["height"]),
                        int(payload.get("imgsz") or 640) ** 2,
                    ) * 3
                    for row in images
                )
                if images and all(row.get("width") and row.get("height") for row in images)
                else None
            )

            remote_execution = {
                "version": 1,
                "task_kind": "TRAINING",
                "transport": "object-storage-v1",
                "training": {
                    "schema_version": 2,
                    "framework": "ultralytics",
                    "snapshot_id": str(snapshot.get("snapshot_id") or ""),
                    "dataset_revision_id": str(snapshot.get("dataset_revision_id") or ""),
                    "supplement_provenance": snapshot.get("supplement_provenance"),
                    "label_schema": frozen_label_schema,
                    "label_codes": frozen_label_codes,
                    "label_contract": frozen_label_contract,
                    "bundle": bundle_ref,
                    "model": model_ref,
                    "result": {
                        "storage_source_id": str(source.id),
                        "object_key": (
                            f"remote-execution/{_safe_segment(target.project_id, 'project')}/"
                            f"{_safe_segment(training_task_id, 'task')}/training-result.zip"
                        ),
                        "file_name": "training-result.zip",
                        "content_type": "application/zip",
                    },
                    "params": _portable_params(payload),
                    "counts": dict(getattr(split_manifest, "counts", {}) or {}),
                    "selected_image_count": len(images),
                    "dataset_bytes": dataset_bytes,
                    "decoded_dataset_bytes": decoded_dataset_bytes,
                },
            }
            updated_payload = {
                **payload,
                "training_input_state": "READY",
                "remote_input_state": "READY",
                "remote_prepare_task_id": context.task.task_id,
                "supplement_provenance": snapshot.get("supplement_provenance"),
                "remote_execution": remote_execution,
            }
            context.artifacts.atomic_write_json(
                training_task_id,
                target.payload_ref,
                updated_payload,
            )
            context.repository.activate_prepared_training(
                training_task_id,
                resource_key=str(payload.get("target_resource_key") or "training:remote:scheduler"),
                required_capabilities=tuple(
                    payload.get("target_required_capabilities") or ("training.ultralytics",)
                ),
            )
            result = {
                "training_task_id": training_task_id,
                "status": "ready",
                "snapshot_id": remote_execution["training"]["snapshot_id"],
                "dataset_revision_id": remote_execution["training"]["dataset_revision_id"],
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
                    stage="training_input_preparation_failed",
                )
            raise
        except (RemoteTrainingTransportError, Exception) as error:
            current = context.repository.get(training_task_id) if training_task_id else None
            if current is not None and current.status is TaskStatus.QUEUED:
                context.repository.fail_queued_precondition(
                    training_task_id,
                    f"TRAINING_PREPARATION_FAILED: {error}",
                    status=TaskStatus.FAILED,
                    stage="training_input_preparation_failed",
                )
            raise


def worker_registration(data_dir: Path):
    return {
        "handlers": {
            TaskKind.TRAINING_PREPARE: TrainingPrepareHandler(data_dir),
        },
        "capabilities": {"training.prepare"},
    }


__all__ = [
    "RemoteTrainingPreparationError",
    "TrainingPrepareHandler",
    "RemoteTrainingPrepareHandler",
    "worker_registration",
]


# Backward-compatible import name; there is still exactly one handler owner.
RemoteTrainingPrepareHandler = TrainingPrepareHandler
