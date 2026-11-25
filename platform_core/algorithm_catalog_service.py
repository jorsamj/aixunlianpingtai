"""Algorithm catalog and version lifecycle orchestration.

The existing algorithm provider, Task/Artifact/feedback repositories and storage
owners remain authoritative. Dependencies are explicit late-bound accessors;
this module never imports app or copies its mutable lifecycle state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
from .algorithm_catalog_contracts import AlgorithmReq, AlgorithmVersionReq, VersionPatchReq, AlgorithmVersionRollbackReq

import json
import re
import shutil
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from fastapi import HTTPException
from platform_core.algorithms import algorithm_store_revision, delete_algorithm_version, project_current_version, resolve_current_version_id, rollback_algorithm_version, retry_algorithm_version_cleanup, create_algorithm as create_algorithm_asset, delete_algorithm as delete_algorithm_asset, list_algorithms as list_algorithm_assets, update_algorithm as update_algorithm_asset, update_algorithm_version
from platform_core.errors import PlatformError
from platform_core.model_artifacts import ModelArtifactService, model_delivery_version_fence
from platform_core.storage import StorageProviderFactory, StorageType
from platform_core.task_runtime import TaskKind, TaskStatus
from platform_core.external_algorithm_platform import assert_algorithm_mutable
from platform_core.external_algorithm_publish import ExternalAlgorithmPublishService, ExternalPublicationRepository

_ACTIVE_VERSION_REFERENCE_STATUSES = {
    TaskStatus.QUEUED,
    TaskStatus.RUNNING,
    TaskStatus.CANCEL_REQUESTED,
}


@dataclass(frozen=True)
class AlgorithmCatalogDependencies:
    authorize_business_file_project: Callable[..., Any]
    business_file_response: Callable[..., Any]
    algorithms_file: Callable[..., Any]
    artifact_service: Callable[..., Any]
    bootstrap_snapshot: Callable[..., Any]
    catalog: Callable[..., Any]
    conversion_catalog: Callable[..., Any]
    data_dir: Callable[..., Any]
    deploy_root: Callable[..., Any]
    deployment_job_dir: Callable[..., Any]
    feedback_repository: Callable[..., Any]
    get_project: Callable[..., Any]
    job_report: Callable[..., Any]
    list_models: Callable[..., Any]
    now_iso: Callable[..., Any]
    presentation_store: Callable[..., Any]
    project_dir: Callable[..., Any]
    publish_bootstrap_snapshot: Callable[..., Any]
    read_json: Callable[..., Any]
    repository: Callable[..., Any]
    secret_store: Callable[..., Any]
    storage_credentials: Callable[..., Any]
    storage_sources: Callable[..., Any]
    successful_training_counts: Callable[..., Any]
    task_artifacts: Callable[..., Any]
    task_repository: Callable[..., Any]
    training_history: Callable[..., Any]
    version_delivery_quality: Callable[..., Any]
    version_storage_provider: Callable[..., Any]
    write_job_json: Callable[..., Any]
    write_json: Callable[..., Any]


class AlgorithmCatalogService:
    def __init__(self, dependencies: AlgorithmCatalogDependencies):
        self.dependencies = dependencies

    def list_algorithms_internal(self, project_id: str, *, summary_only: bool = False,
                                 algorithm_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fast, read-only algorithm projection. Existing report snapshots are reused."""
        self.dependencies.get_project(project_id)
        if algorithm_id is not None:
            from platform_core.algorithm_sql_store import AlgorithmSqlStore
            selected = self.dependencies.repository(project_id).read_one(str(algorithm_id))
            data = [selected] if selected is not None else []
        else:
            data = (list_algorithm_assets(self.dependencies.algorithms_file(project_id), summary_only=True)
                    if summary_only else list_algorithm_assets(self.dependencies.algorithms_file(project_id)))
        changed = False
        for a in data:
            for k,v0 in {"versions":[],"industry":"","algorithm_type":"","created_at":self.dependencies.now_iso()}.items():
                if k not in a: a[k]=v0; changed=True
            if "updated_at" not in a: a["updated_at"]=a.get("created_at") or self.dependencies.now_iso(); changed=True
            for i,v in enumerate(a.get("versions",[]),start=1):
                if "version_no" not in v: v["version_no"]=i; changed=True
                if "status" not in v: v["status"]="已归属"; changed=True
                if "created_at" not in v: v["created_at"]=self.dependencies.now_iso(); changed=True
                if not v.get("report") and (v.get("job_id") or v.get("stored_path")):
                    try:
                        sp=Path(v.get("stored_path","")) if v.get("stored_path") else None
                        fresh=self.dependencies.job_report(project_id,v.get("job_id",""),sp)
                        if fresh: v["report"]=fresh; v["report_updated_at"]=self.dependencies.now_iso(); changed=True
                    except Exception: pass
                # Historical evaluations keep their persisted decision_id unchanged.
                # Expose ONLY a read-only diagnosis projection from their frozen
                # class metrics so the UI can flag older zero-TP safety classes.
                old_eval = v.get("evaluation")
                if not summary_only and isinstance(old_eval, dict) and old_eval.get("status") == "succeeded":
                    from platform_core.training_evaluation import build_iteration_decision
                    prior_decision = v.get("iteration_decision") or {}
                    projection = build_iteration_decision(
                        old_eval,
                        quality_gate=prior_decision.get("quality_gate") if isinstance(prior_decision, dict) else None,
                    )
                    v["evaluation_class_advisory"] = {
                        "class_diagnostics": projection.get("class_diagnostics") or [],
                        "critical_labels": projection.get("critical_labels") or [],
                        "derived_from_evaluation_id": old_eval.get("evaluation_id") or "",
                        "read_only": True,
                    }
        # A GET must never overwrite a concurrent rollback/current-pointer update.
        # Legacy defaults remain a read projection and are persisted on the next
        # explicit algorithm/version mutation through platform_core.algorithms.
        return [project_current_version(item) for item in data]

    def _iter_active_project_tasks(self, project_id: str):
        repository = self.dependencies.task_repository()
        cursor = None
        while True:
            page = repository.list(
                project_id=project_id,
                kinds=(TaskKind.TRAINING, TaskKind.MODEL_CONVERSION, TaskKind.DEPLOYMENT_TEST, TaskKind.DEPLOYMENT_PREPARE),
                statuses=_ACTIVE_VERSION_REFERENCE_STATUSES,
                limit=100,
                cursor=cursor,
            )
            yield from page.items
            cursor = page.next_cursor
            if not cursor:
                break

    @contextmanager
    def _algorithm_version_reference_fence(self,
        project_id: str,
        algorithm_id: str,
        version_id: str,
        *,
        require_current: bool = False,
    ):
        """Serialize creation of a live version reference against version retirement."""
        algorithm_id = str(algorithm_id or "").strip()
        version_id = str(version_id or "").strip()
        if not algorithm_id or not version_id:
            yield None
            return
        with model_delivery_version_fence(
            self.dependencies.data_dir(), str(project_id), algorithm_id, version_id, timeout=0.0,
        ):
            algorithm = next(
                (
                    row for row in self.dependencies.catalog(str(project_id))
                    if str(row.get("id") or "") == algorithm_id
                ),
                None,
            )
            version = next(
                (
                    row for row in ((algorithm or {}).get("versions") or [])
                    if isinstance(row, Mapping)
                    and str(row.get("id") or "") == version_id
                ),
                None,
            )
            if algorithm is None or version is None:
                raise PlatformError(
                    "ALGORITHM_VERSION_REFERENCE_RETIRED",
                    "算法版本已经退役，不能再创建新的业务引用",
                    f"algorithm={algorithm_id}; version={version_id}",
                    "请刷新算法/版本列表后重新选择当前仍存在的版本。",
                    409,
                )
            if require_current and resolve_current_version_id(algorithm) != version_id:
                raise PlatformError(
                    "ALGORITHM_VERSION_REFERENCE_STALE",
                    "算法当前版本已经变化，不能按旧版本创建训练任务",
                    (
                        f"algorithm={algorithm_id}; expected={version_id}; "
                        f"current={resolve_current_version_id(algorithm) or '-'}"
                    ),
                    "请刷新训练创建页，按新的当前版本重新确认迭代训练。",
                    409,
                )
            yield {"algorithm": dict(algorithm), "version": dict(version)}

    def _deploy_job_version_identity(self, job: Mapping[str, Any]) -> tuple[str, str]:
        for source in (job.get("source_trace"), job.get("source_meta")):
            if not isinstance(source, Mapping):
                continue
            algorithm_id = str(source.get("algorithm_id") or "").strip()
            version_id = str(source.get("version_id") or "").strip()
            if algorithm_id and version_id:
                return algorithm_id, version_id
        source_id = str(job.get("source_id") or "").strip()
        match = re.fullmatch(r"version::([^:]+)::([^:]+)", source_id)
        if match:
            return match.group(1), match.group(2)
        return "", ""

    def _version_model_paths(self, version: Mapping[str, Any]) -> set[Path]:
        paths: set[Path] = set()
        for field in ("stored_path", "best_path", "last_path", "path"):
            raw = str(version.get(field) or "").strip()
            if raw:
                try:
                    paths.add(Path(raw).expanduser().resolve())
                except (OSError, RuntimeError):
                    continue
        return paths

    def _deploy_job_references_version(self, job: Mapping[str, Any], algorithm_id: str, version_id: str) -> bool:
        source = job.get("source_meta") or {}
        trace = job.get("source_trace") or {}
        return bool(
            (str(source.get("algorithm_id") or "") == algorithm_id and str(source.get("version_id") or "") == version_id)
            or (str(trace.get("algorithm_id") or "") == algorithm_id and str(trace.get("version_id") or "") == version_id)
            or str(job.get("source_id") or "") == f"version::{algorithm_id}::{version_id}"
        )

    def _version_cleanup_storage_provider(self,
        project_id: str,
        ref: Mapping[str, Any],
    ):
        source_id = str(ref.get("storage_source_id") or "").strip()
        if not source_id:
            raise RuntimeError("板端验收结果缺少 storage_source_id")
        source = self.dependencies.storage_sources().get(source_id)
        if source is None or not source.enabled:
            raise RuntimeError(f"板端验收结果存储源不可用：{source_id}")
        try:
            storage_type = StorageType.parse(source.type)
        except ValueError as error:
            raise RuntimeError(f"板端验收结果存储类型无效：{source.type}") from error
        if storage_type not in {StorageType.OSS, StorageType.S3}:
            raise RuntimeError(f"板端验收结果不是可移植对象存储：{source_id}")
        secret: Mapping[str, str] = {}
        if source.secret_ref:
            secret = self.dependencies.storage_credentials().get(source.secret_ref) or {}
        return StorageProviderFactory(
            data_dir=self.dependencies.data_dir(),
            project_dir=self.dependencies.project_dir(project_id),
            credentials={source.id: secret},
        ).create(source)

    def _retire_rknn_board_result_output(self,
        project_id: str,
        job_file: Path,
        job: Dict[str, Any],
        *,
        targets: List[str],
        errors: List[str],
    ) -> bool:
        verification = job.get("hardware_verification")
        if not isinstance(verification, Mapping):
            return False
        output_ref = verification.get("result_output_storage")
        if not isinstance(output_ref, Mapping) or not output_ref:
            return False

        try:
            task_id = str(verification.get("task_id") or "").strip()
            generation = int(verification.get("execution_generation") or 0)
            source_id = str(output_ref.get("storage_source_id") or "").strip()
            object_key = str(output_ref.get("object_key") or "").strip().replace("\\", "/")
            if not task_id or generation <= 0 or not source_id or not object_key:
                raise ValueError("板端验收结果对象缺少 task/generation/source/key 身份")

            safe_project = re.sub(r"[^A-Za-z0-9._-]+", "-", str(project_id).strip()).strip("-._")[:120] or "project"
            safe_task = re.sub(r"[^A-Za-z0-9._-]+", "-", task_id).strip("-._")[:120] or "task"
            expected_prefix = (
                f"remote-execution/{safe_project}/{safe_task}/"
                f"rknn-board-output/generation-{generation}/"
            )
            object_path = PurePosixPath(object_key)
            if (
                object_path.is_absolute()
                or ".." in object_path.parts
                or not object_key.startswith(expected_prefix)
            ):
                raise ValueError(
                    f"板端验收结果对象不属于当前 task/generation：{object_key}"
                )

            expected_sha = str(output_ref.get("sha256") or "").strip().lower()
            try:
                expected_size = int(output_ref.get("size_bytes") or 0)
            except (TypeError, ValueError):
                expected_size = 0

            if not re.fullmatch(r"[0-9a-f]{64}", expected_sha) or expected_size <= 0:
                state = self.dependencies.task_artifacts().read_json(
                    task_id,
                    f"remote-results/{generation}/upload.json",
                    default={},
                )
                state_ref = state.get("storage_ref") if isinstance(state, Mapping) else None
                state_generation = int(state.get("execution_generation") or 0) if isinstance(state, Mapping) else 0
                if (
                    not isinstance(state_ref, Mapping)
                    or state_generation != generation
                    or str(state_ref.get("storage_source_id") or "").strip() != source_id
                    or str(state_ref.get("object_key") or "").strip().replace("\\", "/") != object_key
                ):
                    raise ValueError("板端验收结果缺少可恢复的 durable upload evidence")
                expected_sha = str(state.get("sha256") or "").strip().lower()
                try:
                    expected_size = int(state.get("size_bytes") or 0)
                except (TypeError, ValueError):
                    expected_size = 0

            if not re.fullmatch(r"[0-9a-f]{64}", expected_sha) or expected_size <= 0:
                raise ValueError("板端验收结果 size/SHA256 evidence 无效")

            manifest_path = job_file.parent / "artifacts" / "manifest.json"
            manifest = self.dependencies.read_json(manifest_path, {}) if manifest_path.is_file() else {}
            manifest_verification = (
                manifest.get("hardware_verification")
                if isinstance(manifest, Mapping)
                else None
            )
            if isinstance(manifest_verification, Mapping):
                if (
                    str(manifest_verification.get("task_id") or "").strip() != task_id
                    or int(manifest_verification.get("execution_generation") or 0) != generation
                ):
                    raise ValueError("job.json 与 manifest 的板端验收 task/generation 不一致")
                manifest_ref = manifest_verification.get("result_output_storage")
                if isinstance(manifest_ref, Mapping) and manifest_ref:
                    manifest_source = str(manifest_ref.get("storage_source_id") or "").strip()
                    manifest_key = str(manifest_ref.get("object_key") or "").strip().replace("\\", "/")
                    if manifest_source != source_id or manifest_key != object_key:
                        raise ValueError("job.json 与 manifest 的板端验收 result object 不一致")

            provider = self.dependencies.version_storage_provider(project_id, output_ref)
            if provider.exists(object_key):
                metadata = provider.stat(object_key)
                actual_sha = str(getattr(metadata, "sha256", "") or "").strip().lower()
                actual_size = int(getattr(metadata, "size_bytes", 0) or 0)
                if actual_size != expected_size or not actual_sha or actual_sha != expected_sha:
                    raise ValueError("板端验收结果对象 size/SHA256 已变化，拒绝删除")
                provider.delete(object_key)

            retired_at = self.dependencies.now_iso()
            retired_ref = dict(output_ref)
            retired_ref.update({
                "sha256": expected_sha,
                "size_bytes": expected_size,
                "available": False,
                "deleted_with_version_at": retired_at,
            })
            job_verification = dict(verification)
            job_verification["result_output_storage"] = retired_ref
            job["hardware_verification"] = job_verification

            if isinstance(manifest_verification, Mapping):
                next_manifest = dict(manifest)
                next_verification = dict(manifest_verification)
                next_verification["result_output_storage"] = dict(retired_ref)
                next_manifest["hardware_verification"] = next_verification
                self.dependencies.write_json(manifest_path, next_manifest)

            targets.append(f"storage://{source_id}/{object_key}")
            return True
        except Exception as error:
            errors.append(
                f"清理 RKNN 板端验收结果失败 {job.get('id') or job_file.parent.name}：{error}"
            )
            return False

    def _algorithm_version_active_references(self,
        project_id: str,
        algorithm: Mapping[str, Any],
        version: Mapping[str, Any],
    ) -> List[Dict[str, str]]:
        """Return only references the current persistence model can prove."""
        algorithm_id = str(algorithm.get("id") or "")
        version_id = str(version.get("id") or "")
        model_paths = self._version_model_paths(version)
        version_root = (
            self.dependencies.project_dir(project_id) / "algorithm_versions" / algorithm_id / version_id
        ).resolve() if algorithm_id and version_id else None
        references: List[Dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        def add(kind: str, reference_id: str, reason: str):
            key = (kind, reference_id)
            if key not in seen:
                seen.add(key)
                references.append({"kind": kind, "id": reference_id, "reason": reason})

        for task in self._iter_active_project_tasks(project_id):
            request = self.dependencies.task_artifacts().read_json(task.task_id, task.payload_ref, default={})
            if task.kind is TaskKind.TRAINING:
                task_job = self.dependencies.read_json(self.dependencies.project_dir(project_id) / "jobs" / task.task_id / "job.json", {})
                base_id = str(task_job.get("base_version_id") or (request or {}).get("base_version_id") or "")
                task_algorithm_id = str(
                    task_job.get("asset_algorithm_id")
                    or task_job.get("algorithm_asset_id")
                    or (request or {}).get("algorithm_asset_id")
                    or ""
                )
                if task_algorithm_id == algorithm_id and (not base_id or base_id == version_id):
                    add("TRAINING", task.task_id, f"算法仍有活动训练任务 {task.task_id}")
            elif task.kind is TaskKind.MODEL_CONVERSION:
                job = self.dependencies.read_json(self.dependencies.deployment_job_dir(project_id, task.task_id) / "job.json", {})
                if self._deploy_job_references_version(job, algorithm_id, version_id):
                    add("MODEL_CONVERSION", task.task_id, f"该版本仍有活动模型转换任务 {task.task_id}")
            elif task.kind in {TaskKind.DEPLOYMENT_TEST, TaskKind.DEPLOYMENT_PREPARE}:
                identity = (request or {}).get("model_identity") or {}
                if task.kind is TaskKind.DEPLOYMENT_PREPARE:
                    parent_id = (request or {}).get("parent_task_id")
                    parent = self.dependencies.task_repository().get(parent_id) if parent_id else None
                    if parent and parent.project_id == project_id:
                        parent_request = self.dependencies.task_artifacts().read_json(parent.task_id, parent.payload_ref, default={})
                        identity = parent_request.get("model_identity") or {}
                if identity.get("algorithm_id") == algorithm_id and identity.get("version_id") == version_id:
                    add("DEPLOYMENT_TEST", task.task_id, f"该版本仍有活动检测或准备任务 {task.task_id}")
                    continue
                source_conversion_job_id = str(
                    (request or {}).get("source_conversion_job_id") or ""
                ).strip()
                if not source_conversion_job_id:
                    remote = (request or {}).get("remote_execution")
                    deployment = remote.get("deployment") if isinstance(remote, Mapping) else None
                    board = deployment.get("board") if isinstance(deployment, Mapping) else None
                    if isinstance(board, Mapping):
                        source_conversion_job_id = str(
                            board.get("conversion_job_id") or ""
                        ).strip()
                if source_conversion_job_id:
                    source_job = self.dependencies.read_json(
                        self.dependencies.deployment_job_dir(project_id, source_conversion_job_id) / "job.json",
                        {},
                    )
                    if source_job and self._deploy_job_references_version(
                        source_job, algorithm_id, version_id,
                    ):
                        add(
                            "DEPLOYMENT_TEST",
                            task.task_id,
                            f"该版本仍有活动 RKNN 板端验证任务 {task.task_id}",
                        )
                        continue

                raw = str((request or {}).get("model_path") or "").strip()
                if raw:
                    try:
                        resolved_model = Path(raw).expanduser().resolve()
                        if (
                            resolved_model in model_paths
                            or (
                                version_root is not None
                                and (resolved_model == version_root or version_root in resolved_model.parents)
                            )
                        ):
                            add("DEPLOYMENT_TEST", task.task_id, f"该版本仍有活动部署测试任务 {task.task_id}")
                    except (OSError, RuntimeError):
                        continue

        if algorithm_id and version_id:
            pending_feedback_id = self.dependencies.feedback_repository(project_id).pending_version_reference(
                algorithm_id, version_id,
            )
            if pending_feedback_id:
                add(
                    "ONLINE_FEEDBACK", pending_feedback_id,
                    f"算法版本仍有待人工复核的线上反馈 {pending_feedback_id}",
                )

        jobs_root = self.dependencies.project_dir(project_id) / "jobs"
        for job_file in jobs_root.glob("*/job.json") if jobs_root.exists() else ():
            job = self.dependencies.read_json(job_file, {})
            status = str(job.get("status") or "").lower()
            if status not in {"queued", "running", "paused", "cancel_requested", "waiting", "pending"}:
                continue
            if str(job.get("asset_algorithm_id") or job.get("algorithm_asset_id") or "") != algorithm_id:
                continue
            base_id = str(job.get("base_version_id") or "")
            if not base_id or base_id == version_id:
                add("TRAINING", str(job.get("id") or job_file.parent.name), f"算法仍有活动训练任务 {job.get('id') or job_file.parent.name}")

        deploy_jobs_root = self.dependencies.deploy_root(project_id) / "jobs"
        for job_file in deploy_jobs_root.glob("*/job.json") if deploy_jobs_root.exists() else ():
            job = self.dependencies.read_json(job_file, {})
            if str(job.get("status") or "").lower() not in {"queued", "running", "cancel_requested", "waiting", "pending"}:
                continue
            if self._deploy_job_references_version(job, algorithm_id, version_id):
                add("MODEL_CONVERSION", str(job.get("id") or job_file.parent.name), f"该版本仍有活动模型转换任务 {job.get('id') or job_file.parent.name}")
        return references

    def _cleanup_algorithm_version_artifacts(self,
        project_id: str,
        algorithm: Mapping[str, Any],
        version: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Remove only exact version-owned files; keep task/audit artifacts."""
        algorithm_id = str(algorithm.get("id") or "")
        version_id = str(version.get("id") or "")
        version_root = (self.dependencies.project_dir(project_id) / "algorithm_versions" / algorithm_id / version_id).resolve()
        algorithm_versions_root = (self.dependencies.project_dir(project_id) / "algorithm_versions" / algorithm_id).resolve()
        targets: List[str] = []
        errors: List[str] = []

        # Task state lives in a separate durable store, so repeat the dependency
        # check after the metadata transaction and before touching any file. This
        # closes the create-task/preflight race without pretending both stores can
        # share one filesystem transaction.
        late_references = self._algorithm_version_active_references(project_id, algorithm, version)
        if late_references:
            return {
                "status": "cleanup_failed",
                "targets": [],
                "errors": [
                    "元数据提交后发现新的活动引用，已保留全部版本产物："
                    + "；".join(str(item.get("reason") or item.get("id") or "存在活动引用") for item in late_references)
                ],
            }

        # The version metadata has already been removed atomically. Retire its
        # immutable delivery objects and publication outbox before local source
        # files, so storage-delete failures remain diagnosable and retryable.
        model_assets = ModelArtifactService(
            data_dir=self.dependencies.data_dir(),
            project_dir=self.dependencies.project_dir,
            algorithms_file=self.dependencies.algorithms_file,
            storage_sources_factory=self.dependencies.storage_sources,
            storage_credentials_factory=self.dependencies.storage_credentials,
        )
        model_assets.purge_version(project_id, algorithm_id, version_id)
        ExternalPublicationRepository(self.dependencies.data_dir()).delete_version(
            project_id, algorithm_id, version_id,
        )

        other_paths: set[Path] = set()
        for other in algorithm.get("versions") or []:
            if str(other.get("id") or "") != version_id:
                other_paths.update(self._version_model_paths(other))
        if version_root.exists():
            if algorithm_versions_root not in version_root.parents or version_root == algorithm_versions_root:
                errors.append(f"拒绝清理越界版本目录：{version_root}")
            elif any(version_root == path or version_root in path.parents for path in other_paths):
                errors.append(f"版本目录仍被其他算法版本引用：{version_root}")
            else:
                try:
                    shutil.rmtree(version_root)
                    targets.append(str(version_root))
                except OSError as error:
                    errors.append(f"删除版本目录失败 {version_root}：{error}")

        # Completed conversion records remain auditable, while their exact output
        # files are retired when they are owned by the deleted source version.
        deploy_jobs_root = self.dependencies.deploy_root(project_id) / "jobs"
        for job_file in deploy_jobs_root.glob("*/job.json") if deploy_jobs_root.exists() else ():
            job = self.dependencies.read_json(job_file, {})
            if not self._deploy_job_references_version(job, algorithm_id, version_id):
                continue
            if str(job.get("status") or "").lower() in {"queued", "running", "cancel_requested", "waiting", "pending"}:
                errors.append(f"转换任务在清理阶段重新变为活动状态：{job.get('id') or job_file.parent.name}")
                continue
            job_root = job_file.parent.resolve()
            changed = self._retire_rknn_board_result_output(
                project_id,
                job_file,
                job,
                targets=targets,
                errors=errors,
            )
            for output in job.get("outputs") or []:
                raw = str(output.get("path") or "").strip()
                if not raw:
                    continue
                try:
                    output_path = Path(raw).expanduser().resolve()
                except (OSError, RuntimeError) as error:
                    errors.append(f"转换产物路径无效 {raw}：{error}")
                    continue
                if job_root not in output_path.parents:
                    errors.append(f"拒绝清理非任务专属转换产物：{output_path}")
                    continue
                try:
                    if output_path.is_file():
                        output_path.unlink()
                        targets.append(str(output_path))
                    output["available"] = False
                    output["deleted_with_version_at"] = self.dependencies.now_iso()
                    changed = True
                except OSError as error:
                    errors.append(f"删除转换产物失败 {output_path}：{error}")
            if changed:
                job["source_version_status"] = "deleted"
                job["updated_at"] = self.dependencies.now_iso()
                self.dependencies.write_job_json(job_file, job)

        return {
            "status": "cleanup_failed" if errors else "cleanup_completed",
            "targets": targets,
            "errors": errors,
        }

    def used_model_keys(self, project_id: str) -> set:
        keys = set()
        for a in self.dependencies.catalog(project_id):
            for v in a.get("versions", []):
                if v.get("model_key"):
                    keys.add(v.get("model_key"))
        return keys

    def _algorithm_library_statistics(self, project_id):
        # One shared history read/overlay per request, never one scan per card.
        # Lifetime counts deliberately reuse their established evidence contract.
        history = self.dependencies.training_history(project_id)
        rows, repository, durable = history
        counts = self.dependencies.successful_training_counts(project_id, history_context=history)
        statistics = {identity: {'algorithm_id': identity, 'count': count} for identity, count in counts.items()}
        by_task = {str(row.get('task_id') or row.get('id') or ''): row for row in rows}
        active = {'queued','waiting','pending','starting','running','pausing','paused','resuming'}
        filter_active = {'queued','running','starting','preparing','paused'}
        for identity, task in durable.items():
            if identity not in by_task and task.status in {TaskStatus.QUEUED,TaskStatus.RUNNING,TaskStatus.CANCEL_REQUESTED}:
                payload = self.dependencies.task_artifacts().read_json(identity, task.payload_ref, default={})
                by_task[identity] = payload if isinstance(payload,dict) else {}
        for identity, row in by_task.items():
            if row.get('project_id') and str(row['project_id']) != str(project_id):continue
            algorithm = str(row.get('asset_algorithm_id') or row.get('algorithm_asset_id') or row.get('algorithm_id') or '')
            if not algorithm:continue
            status = str(row.get('status') or '').lower()
            task = durable.get(identity)
            if task is not None:
                status = {TaskStatus.QUEUED:'queued',TaskStatus.RUNNING:'paused' if task.stage=='paused' else 'running',TaskStatus.CANCEL_REQUESTED:'running'}.get(task.status,'terminal')
            item = statistics.setdefault(algorithm,{'algorithm_id':algorithm,'count':counts.get(algorithm,0)})
            if status in active:item.setdefault('active',status)
            if status in filter_active:item['filter_active']=1
        return list(statistics.values())

    def v12_list_algorithms(self, project_id: str, summary_only: bool = False, asset_view: bool = False,
        page: int=1, page_size: int=20, query: str='', algorithm_type: str='', industry: str='', source_type: str='', status: str='', sort: str='updated', library_view: bool=False, training_state: str='', category_ids: str=''):
        if library_view:
            from platform_core.algorithm_sql_store import AlgorithmSqlStore
            from platform_core.external_algorithm_platform import ExternalPlatformRepository
            self.dependencies.get_project(project_id)
            if not summary_only or not asset_view:raise PlatformError('ASSET_INVALID_QUERY','算法库必须使用只读摘要投影','',status_code=422)
            cache=ExternalPlatformRepository(self.dependencies.data_dir()).cache()
            return {'ok':True,**self.dependencies.presentation_store(project_id).library_algorithms(
                statistics=self._algorithm_library_statistics(project_id),master_digest=cache.get('master_data_digest') or '',categories=cache.get('categories') or [],
                page=page,page_size=page_size,query=query,algorithm_type=algorithm_type,industry=industry,source_type=source_type,training_state=training_state,category_ids=category_ids,sort=sort)}
        if asset_view:
            from platform_core.algorithm_sql_store import AlgorithmSqlStore
            self.dependencies.get_project(project_id)
            if not summary_only:raise PlatformError('ASSET_INVALID_QUERY','模型浏览列表必须使用摘要模式','',status_code=422)
            return {'ok':True,**self.dependencies.presentation_store(project_id).asset_algorithms(page=page,page_size=page_size,query=query,algorithm_type=algorithm_type,industry=industry,source_type=source_type,status=status,sort=sort)}
        if summary_only:
            # Reuse the existing process-local bootstrap snapshot for the compact
            # catalog. F5 should not deserialize every version again when the SQL
            # revision is unchanged. Full-detail callers keep their original path.
            revision = algorithm_store_revision(self.dependencies.algorithms_file(project_id))
            cached = self.dependencies.bootstrap_snapshot() or {}
            if (str((cached.get("project") or {}).get("id") or "") == str(project_id)
                    and not cached.get("algorithms_deferred", True)
                    and int(cached.get("algorithm_revision") or 0) == revision):
                return {"ok": True, "items": cached["algorithms"], "algorithm_revision": revision, "cache_state": "fresh"}
        algos = self.dependencies.catalog(project_id, summary_only=summary_only)
        # Exact lifetime success counts require the whole legacy + Durable job
        # history, defeating the lightweight first-paint contract. Return unknown
        # (never fabricate zero) in the compact view; full callers keep exact data.
        counts = {} if summary_only else self.dependencies.successful_training_counts(project_id)
        algos = [{**algorithm, "successful_training_count": (
            None if summary_only else counts.get(str(algorithm.get("id") or ""), 0)
        )} for algorithm in algos]
        if summary_only and algorithm_store_revision(self.dependencies.algorithms_file(project_id)) == revision:
            # Publish only into the original v53 cache, with the same project and
            # revision fence. A concurrent mutation must never revive old cards.
            self.dependencies.publish_bootstrap_snapshot(project_id, revision, algos)
        return {"ok": True, "items": algos, **({"algorithm_revision": revision} if summary_only else {})}

    def v12_create_algorithm(self, project_id: str, payload: AlgorithmReq, asset_view: bool=False):
        self.dependencies.get_project(project_id)
        # External products remain read-only, but users can always create a new
        # independent local algorithm in the same project and canonical SQL store.
        item = create_algorithm_asset(self.dependencies.algorithms_file(project_id), payload.model_dump(), self.dependencies.now_iso())
        return {"ok": True, "algorithm": {'id':item['id']} if asset_view else item}

    def v12_get_algorithm(self, project_id: str, algorithm_id: str, asset_view: bool=False, version_id: str='', page: int=1, page_size: int=20, basic_only: bool=False, quality_view: bool=False):
        self.dependencies.get_project(project_id)
        if asset_view:
            from platform_core.algorithm_sql_store import AlgorithmSqlStore
            store=self.dependencies.presentation_store(project_id)
            if basic_only:return {'ok':True,'project_id':project_id,'algorithm':store.asset_algorithm_basic(algorithm_id)}
            if version_id:
                version=store.asset_version(algorithm_id,version_id)
                response={'ok':True,'project_id':project_id,'algorithm_id':algorithm_id,'version':version,'artifacts':self.dependencies.conversion_catalog(self.dependencies.data_dir()).version_display(project_id,algorithm_id,version_id)}
                if quality_view:
                    # Opt-in read-only delivery quality; the default asset_view keeps
                    # its existing "no discovery/file hashing" contract.
                    response['delivery_quality']=self.dependencies.version_delivery_quality(
                        project_id,algorithm_id,version_id,
                    )
                return response
            return {'ok':True,**store.asset_versions(algorithm_id,page=page,page_size=page_size)}
        item = next(
            (row for row in self.dependencies.catalog(project_id, algorithm_id=algorithm_id) if str(row.get("id") or "") == str(algorithm_id)),
            None,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="训练算法不存在或已被删除")
        return {"ok": True, "algorithm": item}

    def v12_update_algorithm(self, project_id: str, algorithm_id: str, payload: AlgorithmReq, asset_view: bool=False):
        assert_algorithm_mutable(self.dependencies.algorithms_file(project_id), algorithm_id)
        item = update_algorithm_asset(self.dependencies.algorithms_file(project_id), algorithm_id, payload.model_dump(), self.dependencies.now_iso())
        return {"ok": True, "algorithm": {'id':item['id']} if asset_view else item}

    def v12_delete_algorithm(self, project_id: str, algorithm_id: str):
        assert_algorithm_mutable(self.dependencies.algorithms_file(project_id), algorithm_id)
        delete_algorithm_asset(self.dependencies.algorithms_file(project_id), algorithm_id)
        return {"ok": True}

    def v12_pending_models(self, project_id: str):
        used = self.used_model_keys(project_id)
        rows = []
        for m in self.dependencies.list_models(project_id):
            key = f"project::{m['name']}"
            if key not in used and m.get("type") in {"pt", "onnx", "pdparams", "pdmodel", "pdiparams"}:
                rows.append({**m, "model_key": key})
        return {"ok": True, "items": rows}

    def v12_assign_version(self, project_id: str, algorithm_id: str, payload: AlgorithmVersionReq):
        # Minimal-safe-launch: do not mint a verified/training-succeeded version
        # from an arbitrary file. Only the canonical Durable training finalizer
        # may publish verified models and frozen lineage.
        raise HTTPException(
            status_code=409,
            detail="手工模型归属暂未开放：请使用训练任务产物自动归档，确保模型验证和版本血缘完整。",
        )

    def v12_update_version(self, project_id: str, algorithm_id: str, version_id: str, payload: VersionPatchReq, asset_view: bool=False):
        # v42.8 起版本号由训练结束时间唯一生成，不允许人工改写。
        patch: Dict[str, Any] = {}
        if payload.remark is not None:
            patch["remark"] = payload.remark or ""
        result = update_algorithm_version(
            self.dependencies.algorithms_file(project_id), algorithm_id, version_id, patch, now=self.dependencies.now_iso(),
        )

        return {"ok":True} if asset_view else result

    def _safe_launch_reject_external_version_retirement(self, project_id: str, algorithm_id: str) -> None:
        # Remote delete precedes the local algorithm SQL CAS. Until a durable
        # tombstone/compensation contract is verified, reject only ChangLian
        # external algorithm version retirement. Local algorithms are unaffected.
        algorithm = next(
            (row for row in self.dependencies.catalog(project_id)
             if str(row.get("id") or "") == str(algorithm_id)),
            None,
        )
        if (
            algorithm is not None
            and str(algorithm.get("source_type") or "").upper() == "EXTERNAL"
            and str(algorithm.get("provider_type") or "").upper() == "CHANG_LIAN"
        ):
            raise HTTPException(
                status_code=409,
                detail="新畅联远端算法版本删除与回退暂时停用：需先完成远端删除和本地事务失败的持久化恢复验收。",
            )

    def v12_delete_version(self, project_id: str, algorithm_id: str, version_id: str):
        self.dependencies.get_project(project_id)
        self._safe_launch_reject_external_version_retirement(project_id, algorithm_id)
        publish_service = ExternalAlgorithmPublishService(
            data_dir=self.dependencies.data_dir(),
            project_dir=self.dependencies.project_dir,
            algorithms_file=self.dependencies.algorithms_file,
            external_secret_store_factory=self.dependencies.secret_store,
            storage_sources_factory=self.dependencies.storage_sources,
            storage_credentials_factory=self.dependencies.storage_credentials,
        )
        with model_delivery_version_fence(
            self.dependencies.data_dir(), project_id, algorithm_id, version_id,
        ):
            result = delete_algorithm_version(
                self.dependencies.algorithms_file(project_id),
                algorithm_id,
                version_id,
                now=self.dependencies.now_iso(),
                operator="local_user",
                dependency_check=lambda algorithm, version: self._algorithm_version_active_references(project_id, algorithm, version),
                remote_delete=lambda algorithm, version: publish_service.delete_version_for_rollback(
                    project_id=project_id,
                    algorithm=algorithm,
                    version=version,
                ),
                cleanup=lambda algorithm, version: self._cleanup_algorithm_version_artifacts(project_id, algorithm, version),
            )
        return {
            "ok": result.get("cleanup_status") != "cleanup_failed",
            **result,
            "reference_check": {
                "verified": ["training_tasks", "model_conversion_tasks", "deployment_test_tasks", "online_feedback_pending_review"],
                "not_verifiable": ["online_deployment_instances"],
            },
        }

    def v12_rollback_version(self,
        project_id: str,
        algorithm_id: str,
        version_id: str,
        payload: AlgorithmVersionRollbackReq,
    ):
        self.dependencies.get_project(project_id)
        if not str(payload.expected_current_version_id or "").strip():
            raise PlatformError(
                "ALGORITHM_VERSION_EXPECTATION_REQUIRED", "缺少当前版本并发校验",
                "回退请求必须携带页面确认时看到的 current_version_id。",
                "请刷新算法版本列表后重新确认回退。", 409,
            )
        self._safe_launch_reject_external_version_retirement(project_id, algorithm_id)
        publish_service = ExternalAlgorithmPublishService(
            data_dir=self.dependencies.data_dir(),
            project_dir=self.dependencies.project_dir,
            algorithms_file=self.dependencies.algorithms_file,
            external_secret_store_factory=self.dependencies.secret_store,
            storage_sources_factory=self.dependencies.storage_sources,
            storage_credentials_factory=self.dependencies.storage_credentials,
        )
        with model_delivery_version_fence(
            self.dependencies.data_dir(),
            project_id,
            algorithm_id,
            str(payload.expected_current_version_id),
        ):
            result = rollback_algorithm_version(
                self.dependencies.algorithms_file(project_id),
                algorithm_id,
                version_id,
                now=self.dependencies.now_iso(),
                delete_current_version=True,
                operator="local_user",
                expected_current_version_id=payload.expected_current_version_id,
                dependency_check=lambda algorithm, version: self._algorithm_version_active_references(project_id, algorithm, version),
                remote_delete=lambda algorithm, version: publish_service.delete_version_for_rollback(
                    project_id=project_id,
                    algorithm=algorithm,
                    version=version,
                ),
                cleanup=lambda algorithm, version: self._cleanup_algorithm_version_artifacts(project_id, algorithm, version),
            )
        return {
            "ok": result.get("cleanup_status") != "cleanup_failed",
            **result,
            "reference_check": {
                "verified": ["training_tasks", "model_conversion_tasks", "deployment_test_tasks", "online_feedback_pending_review"],
                "not_verifiable": ["online_deployment_instances"],
            },
        }

    def _dry_run_state_snapshot(self,
        project_id: str, algorithm_id: str, service: ModelArtifactService,
    ) -> Dict[str, Any]:
        """Read-only row-set evidence for one dry-run (versions/operations/artifacts)."""
        path = self.dependencies.algorithms_file(project_id)
        algorithms = list_algorithm_assets(path)
        algorithm = next(
            (row for row in algorithms if str(row.get("id") or "") == str(algorithm_id)),
            None,
        )
        versions = [
            row for row in ((algorithm or {}).get("versions") or [])
            if isinstance(row, Mapping)
        ]
        operations = [
            row for row in ((algorithm or {}).get("version_operations") or [])
            if isinstance(row, Mapping)
        ]
        try:
            current = str(resolve_current_version_id(algorithm) or "") if algorithm else ""
        except Exception:  # noqa: BLE001 - a broken pointer is itself evidence, never a 500
            current = ""
        try:
            revision = int(algorithm_store_revision(path))
        except Exception:  # noqa: BLE001
            revision = -1
        return {
            "algorithm_revision": revision,
            "algorithm_present": algorithm is not None,
            "current_version_id": current,
            "version_count": len(versions),
            "version_ids": sorted(str(row.get("id") or "") for row in versions),
            "version_operation_count": len(operations),
            "version_operation_ids": sorted(str(row.get("id") or "") for row in operations),
            "artifact_rows": int(service.repository.summary(project_id=project_id).get("total") or 0),
        }

    def _dry_run_read_only_response(self,
        plan: Mapping[str, Any], before: Mapping[str, Any], after: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Fail closed if a dry-run changed algorithm/version/artifact row counts."""
        rows_unchanged = before == after
        assertion = {
            "state_unchanged": rows_unchanged,
            "algorithm_revision_unchanged": before["algorithm_revision"] == after["algorithm_revision"],
            "current_version_unchanged": before["current_version_id"] == after["current_version_id"],
            "version_rows_unchanged": (
                before["version_count"] == after["version_count"]
                and before["version_ids"] == after["version_ids"]
            ),
            "version_operation_rows_unchanged": (
                before["version_operation_count"] == after["version_operation_count"]
                and before["version_operation_ids"] == after["version_operation_ids"]
            ),
            "artifact_rows_unchanged": before["artifact_rows"] == after["artifact_rows"],
            "before": dict(before),
            "after": dict(after),
        }
        if not rows_unchanged:
            raise PlatformError(
                "DRY_RUN_STATE_CHANGED",
                "Dry-Run 调用前后检测到状态变化，拒绝返回计划",
                json.dumps({"before": dict(before), "after": dict(after)}, ensure_ascii=False),
                "Dry-Run 必须零写入；请重新读取一次计划并核对并发操作。",
                409,
            )
        return {
            "ok": True,
            **dict(plan),
            "dry_run": True,
            "zero_write_assertion": "PASSED",
            "read_only_assertion": assertion,
        }

    def v12_deployment_activation_dry_run(self,
        project_id: str,
        algorithm_id: str,
        version_id: str,
        operation_id: str = "",
        expected_current_version_id: str = "",
    ):
        """Read-only deployment activation Dry-Run; reuses `_dry_run_operation_guard`."""
        self.dependencies.get_project(project_id)
        service = self.dependencies.artifact_service()
        before = self._dry_run_state_snapshot(project_id, algorithm_id, service)
        plan = service.deployment_activation_dry_run(
            project_id, algorithm_id, version_id,
            operation_id=operation_id,
            expected_current_version_id=(expected_current_version_id or None),
        )
        after = self._dry_run_state_snapshot(project_id, algorithm_id, service)
        return self._dry_run_read_only_response(plan, before, after)

    def v12_rollback_dry_run(self,
        project_id: str,
        algorithm_id: str,
        version_id: str,
        operation_id: str = "",
        expected_current_version_id: str = "",
    ):
        """Read-only rollback Dry-Run; reuses `_dry_run_operation_guard`."""
        self.dependencies.get_project(project_id)
        service = self.dependencies.artifact_service()
        before = self._dry_run_state_snapshot(project_id, algorithm_id, service)
        plan = service.rollback_dry_run(
            project_id, algorithm_id, version_id,
            operation_id=operation_id,
            expected_current_version_id=(expected_current_version_id or None),
        )
        after = self._dry_run_state_snapshot(project_id, algorithm_id, service)
        return self._dry_run_read_only_response(plan, before, after)

    def v12_retry_version_cleanup(self, project_id: str, algorithm_id: str, operation_id: str):
        self.dependencies.get_project(project_id)
        result = retry_algorithm_version_cleanup(
            self.dependencies.algorithms_file(project_id),
            algorithm_id,
            operation_id,
            cleanup=lambda algorithm, version: self._cleanup_algorithm_version_artifacts(
                project_id, algorithm, version,
            ),
        )
        return {
            "ok": result.get("cleanup_status") != "cleanup_failed",
            **result,
            "reference_check": {
                "verified": ["training_tasks", "model_conversion_tasks", "deployment_test_tasks", "online_feedback_pending_review"],
                "not_verifiable": ["online_deployment_instances"],
            },
        }

    def v12_download_version(self, project_id: str, algorithm_id: str, version_id: str):
        self.dependencies.authorize_business_file_project(project_id)
        algos = self.dependencies.catalog(project_id)
        for a in algos:
            if a.get("id") == algorithm_id:
                for v in a.get("versions", []):
                    if v.get("id") == version_id:
                        path = Path(v.get("stored_path", ""))
                        identifier = f"versions/{algorithm_id}/{version_id}/{path.name}"
                        return self.dependencies.business_file_response(project_id, 'models', identifier, download=True)
        raise HTTPException(status_code=404, detail="版本不存在")
