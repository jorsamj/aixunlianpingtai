"""Domain orchestration over the existing persistence, worker and receipt owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional
from fastapi import Query, HTTPException
from .storage_ingestion_contracts import StorageImportConfirmReq, StorageImportScanReq, StorageRescanConfirmReq, StorageRescanCreateReq

import json
import hashlib
import uuid
from urllib.parse import quote
from pathlib import Path
from fastapi.responses import StreamingResponse
from platform_core.storage.import_confirmation import IMPORT_LABEL_CREATION_BLOCKED_DETAIL, confirm_import, resolve_external_label_mapping
from platform_core.errors import PlatformError
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.storage import StorageError, StorageType
from platform_core.storage.import_candidates import ImportCandidateStore, RescanCandidateStore
from platform_core.storage.import_tasks import MANIFEST_REF as STORAGE_IMPORT_MANIFEST_REF, load_legacy_candidates, server_import_dir
from platform_core.storage.zip_import import ServerZipImportError, resolve_server_zip, safe_member_path
from platform_core.task_runtime import TaskKind, TaskRecord, TaskStatus
from platform_core.remote_execution_transport import RemoteExecutionTransportError

@dataclass(frozen=True)
class StorageIngestionDependencies:
    DATA_DIR: Callable[..., Any]
    _authorize_business_file_project: Callable[..., Any]
    _label_sample_content_type: Callable[..., Any]
    _public_storage_import_task: Callable[..., Any]
    _public_storage_import_text: Callable[..., Any]
    _public_storage_rescan: Callable[..., Any]
    _raise_file_storage_error: Callable[..., Any]
    _remote_execution_transport_service: Callable[..., Any]
    _storage_source_fence: Callable[..., Any]
    _storage_source_runtime_generation: Callable[..., Any]
    get_project: Callable[..., Any]
    material_store: Callable[..., Any]
    project_label_items: Callable[..., Any]
    remember_project_label_aliases: Callable[..., Any]
    shared_task_artifacts: Callable[..., Any]
    shared_task_repository: Callable[..., Any]
    storage_manager: Callable[..., Any]
    storage_source_repository: Callable[..., Any]


class StorageIngestionService:
    def __init__(self, dependencies: StorageIngestionDependencies):
        self.dependencies = dependencies

    def _storage_rescan_task(self, project_id: str, task_id: str):
        self.dependencies.get_project(project_id)
        task = self.dependencies.shared_task_repository().get(task_id)
        if task is None or task.project_id != project_id or task.kind is not TaskKind.MATERIAL_IMPORT:
            raise HTTPException(status_code=404, detail='重扫描任务不存在')
        request = self.dependencies.shared_task_artifacts().read_json(task_id, task.payload_ref, default={})
        if request.get('mode') != 'storage_rescan':
            raise HTTPException(status_code=404, detail='重扫描任务不存在')
        return task

    def _storage_rescan_agent_preflight(self, project_id: str, source_id: str) -> Dict[str, Any]:
        self.dependencies.get_project(project_id)
        source = self.dependencies.storage_source_repository().get(source_id)
        if source is None:
            return {'agent_available': False, 'reason': '存储源不存在', 'eligible_nodes': []}
        if not source.enabled:
            return {'agent_available': False, 'reason': '存储源已停用', 'eligible_nodes': []}
        try:
            source_type = StorageType.parse(source.type)
        except ValueError:
            return {'agent_available': False, 'reason': '存储源类型无效', 'eligible_nodes': []}
        if source_type not in {StorageType.OSS, StorageType.S3}:
            return {
                'agent_available': False,
                'reason': '远程重扫描仅支持 OSS / S3 / MinIO 对象存储',
                'eligible_nodes': [],
            }
        nodes = [
            node for node in ServiceNodeRepository(self.dependencies.shared_task_repository()).list_public()
            if str(node.get('connection_mode') or '') == 'agent'
            and bool(node.get('online'))
            and 'material-import' in set(node.get('effective_capabilities') or [])
        ]
        if not nodes:
            return {
                'agent_available': False,
                'reason': '当前没有在线且已授权素材导入能力的 Agent 节点',
                'eligible_nodes': [],
            }
        try:
            self.dependencies._remote_execution_transport_service().stage_material_storage_scan(
                project_id=project_id,
                task_id='storage-rescan-preflight',
                storage_source_id=source_id,
                prefix='',
                recursive=True,
                import_format='images',
                allow_root=True,
                intent='storage_rescan',
            )
        except RemoteExecutionTransportError as error:
            return {'agent_available': False, 'reason': str(error), 'eligible_nodes': []}
        return {
            'agent_available': True,
            'reason': '',
            'agent_supported_formats': ['images', 'yolo', 'coco', 'voc'],
            'local_supported_formats': ['images', 'yolo', 'coco', 'voc'],
            'eligible_nodes': [
                {
                    'node_id': str(node.get('node_id') or ''),
                    'display_name': str(node.get('display_name') or ''),
                    'build_id': str(node.get('build_id') or ''),
                }
                for node in nodes
            ],
        }

    def storage_rescan_preflight(self, project_id: str, source_id: str):
        result = self._storage_rescan_agent_preflight(project_id, source_id)
        result.setdefault('agent_supported_formats', [])
        result.setdefault('local_supported_formats', ['images', 'yolo', 'coco', 'voc'])
        return {
            'local_available': True,
            'default_execution_mode': 'local',
            **result,
        }

    def create_storage_rescan(self,
        project_id: str,
        source_id: str,
        payload: Optional[StorageRescanCreateReq] = None,
    ):
        self.dependencies.get_project(project_id)
        source = self.dependencies.storage_source_repository().get(source_id)
        if source is None:
            raise HTTPException(status_code=404, detail='存储源不存在')
        if not source.enabled:
            raise HTTPException(status_code=409, detail='存储源已停用')
        request = payload or StorageRescanCreateReq()
        execution_mode = str(request.execution_mode or 'local')
        task_id = uuid.uuid4().hex[:12]
        import_format = str(request.import_format or 'images')
        request_payload: Dict[str, Any] = {
            'mode': 'storage_rescan',
            'execution_mode': execution_mode,
            'storage_source_id': source_id,
            'import_format': import_format,
            'dataset_yaml': str(request.dataset_yaml or ''),
        }
        capabilities = ('storage.rescan',)
        resource_key = f'storage:{source_id}'
        if execution_mode == 'agent':
            preflight = self._storage_rescan_agent_preflight(project_id, source_id)
            if not preflight.get('agent_available'):
                raise HTTPException(
                    status_code=409,
                    detail=str(preflight.get('reason') or '远程重扫描当前不可用'),
                )
            try:
                request_payload['remote_execution'] = (
                    self.dependencies._remote_execution_transport_service().stage_material_storage_scan(
                        project_id=project_id,
                        task_id=task_id,
                        storage_source_id=source_id,
                        prefix='',
                        recursive=True,
                        import_format=import_format,
                        dataset_yaml=str(request.dataset_yaml or ''),
                        allow_root=True,
                        intent='storage_rescan',
                    )
                )
            except RemoteExecutionTransportError as error:
                raise PlatformError(
                    code=error.code,
                    message='远程存储重扫描准备失败',
                    detail=str(error),
                    solution='请检查对象存储连接和远程素材节点后重试。',
                    status_code=error.status_code,
                ) from error
            capabilities = ('agent.remote',)
            resource_key = f'material-rescan:agent:{source_id}'

        with self.dependencies._storage_source_fence():
            admitted_source = self.dependencies.storage_source_repository().get(source_id)
            if (
                admitted_source is None
                or not admitted_source.enabled
                or self.dependencies._storage_source_runtime_generation(admitted_source)
                != self.dependencies._storage_source_runtime_generation(source)
            ):
                raise HTTPException(
                    status_code=409,
                    detail='存储源配置在任务准备期间已变化，请刷新后重试',
                )
            manifest = self.dependencies.shared_task_artifacts().artifact_path(task_id, STORAGE_IMPORT_MANIFEST_REF)
            store = RescanCandidateStore(manifest)
            store.set_meta(
                'source_fingerprint',
                hashlib.sha256(json.dumps(
                    [admitted_source.id, admitted_source.type, admitted_source.config],
                    sort_keys=True,
                ).encode()).hexdigest(),
            )
            self.dependencies.material_store(project_id).snapshot_storage_references(manifest, source_id)
            self.dependencies.shared_task_artifacts().atomic_write_json(task_id, 'request.json', request_payload)
            task = self.dependencies.shared_task_repository().create(TaskRecord.new(
                task_id,
                project_id,
                TaskKind.MATERIAL_IMPORT,
                'request.json',
                resource_key,
                required_capabilities=capabilities,
            ))
        return self.dependencies._public_storage_rescan(task)

    def get_storage_rescan(self, project_id: str, task_id: str):
        return self.dependencies._public_storage_rescan(self._storage_rescan_task(project_id, task_id))

    def confirm_storage_rescan(self, project_id: str, task_id: str, payload: StorageRescanConfirmReq):
        from platform_core.storage.rescan_tasks import confirm_rescan
        task = self._storage_rescan_task(project_id, task_id)
        if task.status is not TaskStatus.AWAITING_CONFIRMATION and task.accepted is not True:
            raise HTTPException(status_code=409, detail='重扫描尚未进入待确认状态')
        artifacts = self.dependencies.shared_task_artifacts()
        request = artifacts.read_json(task_id, task.payload_ref, default={})
        import_format = str(request.get('import_format') or 'images')
        policy = {
            'new': payload.new,
            'missing': payload.missing,
            'changed': payload.changed,
            'annotation_changed': payload.annotation_changed,
            'annotation_removed': payload.annotation_removed,
            'annotation_conflicts': payload.annotation_conflicts,
        }
        annotation_confirmation = None
        try:
            if payload.create_labels:
                raise ValueError(IMPORT_LABEL_CREATION_BLOCKED_DETAIL)
            if import_format in {'yolo', 'coco', 'voc'}:
                manifest = artifacts.artifact_path(task_id, STORAGE_IMPORT_MANIFEST_REF)
                store = RescanCandidateStore(manifest)
                quality = store.quality_summary()
                if quality.get('issues') and not payload.accept_quality_report:
                    raise ValueError('请先确认并接受标注数据质量报告')
                project = self.dependencies.get_project(project_id)
                external_classes = store.external_classes()
                resolved, _ = resolve_external_label_mapping(
                    external_classes,
                    label_mapping=payload.label_mapping,
                    create_labels=[],
                    labels=self.dependencies.project_label_items(project),
                )
                annotation_confirmation = {
                    'label_mapping': resolved,
                    'create_labels': [],
                    'external_classes': [
                        {'class_id': str(row.get('class_id')), 'name': str(row.get('name') or '')}
                        for row in external_classes
                    ],
                    'accept_quality_report': payload.accept_quality_report,
                }
            elif payload.label_mapping:
                raise ValueError('仅标注重新扫描允许提交外部类别映射')
            confirm_rescan(
                artifacts,
                task_id,
                policy,
                annotation_confirmation=annotation_confirmation,
            )
            if annotation_confirmation:
                self.dependencies.remember_project_label_aliases(
                    project_id,
                    annotation_confirmation.get('external_classes') or [],
                    annotation_confirmation.get('label_mapping') or {},
                )
            task = self.dependencies.shared_task_repository().resume_after_confirmation(
                task_id,
                required_capabilities=('storage.rescan',),
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return self.dependencies._public_storage_rescan(task)

    def cancel_storage_rescan(self, project_id: str, task_id: str):
        self._storage_rescan_task(project_id, task_id)
        return self.dependencies._public_storage_rescan(self.dependencies.shared_task_repository().request_cancel(task_id))

    def create_storage_import_scan(self, project_id: str, payload: StorageImportScanReq):
        self.dependencies.get_project(project_id)
        source = self.dependencies.storage_source_repository().get(payload.storage_source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="存储源不存在")
        if not source.enabled:
            raise HTTPException(status_code=409, detail="存储源已停用")
        source_type = StorageType.parse(source.type)
        if payload.mode == "directory_scan" and source_type is not StorageType.LOCAL:
            raise HTTPException(status_code=422, detail="目录扫描只能使用已启用的本地存储")
        if (
            payload.mode == "server_zip"
            and payload.execution_mode == "local"
            and source_type is not StorageType.LOCAL
        ):
            raise HTTPException(status_code=422, detail="本地服务器 ZIP 导入只能使用本地目标存储")
        if (
            payload.execution_mode == "agent"
            and payload.mode in {"server_zip", "storage_scan"}
            and source_type not in {StorageType.OSS, StorageType.S3}
        ):
            raise HTTPException(status_code=422, detail="Agent 素材导入必须选择 OSS/S3/MinIO 对象存储")
        request_payload = payload.model_dump(mode="json")
        resolved_zip = None
        if payload.mode == "server_zip":
            relative_zip = str(payload.zip_path or "").strip()
            try:
                resolved_zip = resolve_server_zip(server_import_dir(self.dependencies.DATA_DIR()), relative_zip)
                target_prefix = safe_member_path(
                    str(payload.target_prefix or "").strip()
                ).as_posix()
            except ServerZipImportError as error:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": error.code,
                        "message": self.dependencies._public_storage_import_text(error.message),
                        "detail": self.dependencies._public_storage_import_text(error.detail),
                        "solution": self.dependencies._public_storage_import_text(error.solution),
                    },
                ) from error
            request_payload["zip_path"] = relative_zip
            request_payload["target_prefix"] = target_prefix
        task_id = uuid.uuid4().hex[:12]
        if payload.execution_mode == "agent":
            try:
                transport = self.dependencies._remote_execution_transport_service()
                if payload.mode == "storage_scan":
                    request_payload["remote_execution"] = transport.stage_material_storage_scan(
                        project_id=project_id,
                        task_id=task_id,
                        storage_source_id=source.id,
                        prefix=str(payload.prefix or ""),
                        recursive=bool(payload.recursive),
                        import_format=payload.import_format,
                        dataset_yaml=str(payload.dataset_yaml or ""),
                    )
                else:
                    request_payload["remote_execution"] = transport.stage_material_import(
                        project_id=project_id,
                        task_id=task_id,
                        archive_path=resolved_zip,
                        storage_source_id=source.id,
                        target_prefix=request_payload["target_prefix"],
                        import_format=payload.import_format,
                        dataset_yaml=str(payload.dataset_yaml or ""),
                    )
            except RemoteExecutionTransportError as error:
                raise PlatformError(
                    code=error.code,
                    message="远程素材导入准备失败",
                    detail=str(error),
                    solution="请检查目标对象存储、服务器 ZIP 文件和访问凭据后重试。",
                    status_code=error.status_code,
                ) from error
        with self.dependencies._storage_source_fence():
            admitted_source = self.dependencies.storage_source_repository().get(source.id)
            if (
                admitted_source is None
                or not admitted_source.enabled
                or self.dependencies._storage_source_runtime_generation(admitted_source)
                != self.dependencies._storage_source_runtime_generation(source)
            ):
                raise HTTPException(
                    status_code=409,
                    detail="存储源配置在任务准备期间已变化，请刷新后重试",
                )
            self.dependencies.shared_task_artifacts().atomic_write_json(task_id, "request.json", request_payload)
            task = self.dependencies.shared_task_repository().create(TaskRecord.new(
                task_id, project_id, TaskKind.MATERIAL_IMPORT, "request.json",
                (
                    f"material-import:agent:{source.id}"
                    if payload.execution_mode == "agent"
                    else f"storage:{source.id}"
                ),
                required_capabilities=(
                    ("agent.remote",)
                    if payload.execution_mode == "agent"
                    else ("storage.import",)
                ),
            ))
        return self.dependencies._public_storage_import_task(task)

    def get_storage_import_scan(self, project_id: str, task_id: str):
        self.dependencies.get_project(project_id)
        task = self.dependencies.shared_task_repository().get(task_id)
        if task is None or task.project_id != project_id or task.kind is not TaskKind.MATERIAL_IMPORT:
            raise HTTPException(status_code=404, detail="存储导入任务不存在")
        return self.dependencies._public_storage_import_task(task)

    def confirm_storage_import(self, project_id: str, task_id: str, payload: StorageImportConfirmReq):
        request_task = self.dependencies.shared_task_repository().get(task_id)
        if request_task and request_task.project_id == project_id:
            request = self.dependencies.shared_task_artifacts().read_json(task_id, request_task.payload_ref, default={})
            if request.get('mode') == 'storage_rescan':
                raise HTTPException(status_code=409, detail='请使用重扫描确认接口选择恢复策略')
        self.dependencies.get_project(project_id)
        task = self.dependencies.shared_task_repository().get(task_id)
        if task is None or task.project_id != project_id or task.kind is not TaskKind.MATERIAL_IMPORT:
            raise HTTPException(status_code=404, detail="存储导入任务不存在")
        repeatable = (
            task.accepted is True
            and task.status in {
                TaskStatus.QUEUED, TaskStatus.RUNNING,
                TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS,
            }
        )
        if task.status is not TaskStatus.AWAITING_CONFIRMATION and not repeatable:
            raise HTTPException(status_code=409, detail="存储扫描尚未进入待确认状态")

        artifacts = self.dependencies.shared_task_artifacts()
        manifest = artifacts.artifact_path(task_id, STORAGE_IMPORT_MANIFEST_REF)
        scan_result = artifacts.read_json(task_id, "scan/result.json", default=None)
        if not manifest.is_file() and not (
            isinstance(scan_result, dict) and isinstance(scan_result.get("candidates"), list)
        ):
            raise HTTPException(status_code=409, detail="存储扫描候选清单不存在")
        candidate_store = ImportCandidateStore(manifest)
        load_legacy_candidates(artifacts, task_id, candidate_store)
        try:
            if payload.create_labels:
                raise ValueError(IMPORT_LABEL_CREATION_BLOCKED_DETAIL)
            project = self.dependencies.get_project(project_id)
            confirmation = confirm_import(candidate_store, artifacts, task_id,
                object_keys=payload.object_keys, label_mapping=payload.label_mapping,
                create_labels=[], accept_quality_report=payload.accept_quality_report,
                labels=self.dependencies.project_label_items(project), create_label=None)
            self.dependencies.remember_project_label_aliases(
                project_id,
                confirmation.get('external_classes') or [],
                confirmation.get('label_mapping') or {},
            )
            updated = self.dependencies.shared_task_repository().resume_after_confirmation(
                task_id,
                required_capabilities=("storage.import",),
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return self.dependencies._public_storage_import_task(updated)

    def _label_review_candidate_store(self, project_id: str, task_id: str):
        self.dependencies.get_project(project_id)
        task = self.dependencies.shared_task_repository().get(task_id)
        if task is None or task.project_id != project_id or task.kind is not TaskKind.MATERIAL_IMPORT:
            raise HTTPException(status_code=404, detail="标签审查任务不存在")
        artifacts = self.dependencies.shared_task_artifacts()
        request = artifacts.read_json(task_id, task.payload_ref, default={})
        mode = str(request.get("mode") or "storage_scan")
        if mode not in {"storage_scan", "directory_scan", "server_zip", "storage_rescan"}:
            raise HTTPException(status_code=404, detail="标签审查任务不存在")
        manifest = artifacts.artifact_path(task_id, STORAGE_IMPORT_MANIFEST_REF)
        if not manifest.is_file():
            scan_result = artifacts.read_json(task_id, "scan/result.json", default={})
            if isinstance(scan_result, dict) and isinstance(scan_result.get("candidates"), list):
                store = ImportCandidateStore(manifest)
                load_legacy_candidates(artifacts, task_id, store)
            else:
                raise HTTPException(status_code=409, detail="标签审查候选清单尚未就绪")
        return task, request, ImportCandidateStore(manifest)

    def label_review_samples_v61(self,
        project_id: str,
        task_id: str,
        class_id: str,
        limit: int = Query(default=8, ge=1, le=12),
    ):
        _task, _request, store = self._label_review_candidate_store(project_id, task_id)
        samples = store.external_class_samples(class_id, limit=limit)
        result = []
        for sample in samples:
            object_key = str(sample.get("object_key") or "")
            content_url = (
                f"/api/v61/projects/{quote(project_id, safe='')}/label-review/"
            f"{quote(task_id, safe='')}/classes/{quote(str(class_id), safe='')}/sample-content"
            f"?object_key={quote(object_key, safe='')}"
            )
            result.append({
                "object_key": object_key,
                "filename": str(sample.get("filename") or Path(object_key).name),
                "width": max(0, int(sample.get("width") or 0)),
                "height": max(0, int(sample.get("height") or 0)),
                "bbox": {
                    "cx": float(sample.get("cx") or 0),
                    "cy": float(sample.get("cy") or 0),
                    "w": float(sample.get("w") or 0),
                    "h": float(sample.get("h") or 0),
                    "clipped": bool(sample.get("clipped")),
                },
                "preview_url": content_url,
                "content_url": content_url,
            })
        return {
            "task_id": task_id,
            "class_id": str(class_id),
            "count": len(result),
            "samples": result,
        }

    def label_review_sample_content_v61(self,
        project_id: str,
        task_id: str,
        class_id: str,
        object_key: str = Query(..., min_length=1, max_length=4096),
    ):
        self.dependencies._authorize_business_file_project(project_id)
        _task, _request, store = self._label_review_candidate_store(project_id, task_id)
        sample = store.external_class_sample(class_id, object_key)
        if sample is None:
            raise HTTPException(status_code=404, detail="该对象不属于当前外部标签样本")
        try:
            provider = self.dependencies.storage_manager(project_id).provider_for(
                str(sample.get("storage_source_id") or "")
            )
            stream = provider.open_reader(str(sample["object_key"]))
        except StorageError as error:
            self.dependencies._raise_file_storage_error(
                error,
                status_code=404 if error.code == "STORAGE_OBJECT_NOT_FOUND" else 503,
            )

        def body():
            try:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()

        return StreamingResponse(
            body(),
            media_type=self.dependencies._label_sample_content_type(str(sample.get("filename") or "")),
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )
