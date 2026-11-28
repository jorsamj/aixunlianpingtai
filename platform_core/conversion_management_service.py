"""Domain orchestration over the existing persistence, worker and receipt owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping
from fastapi import Query, HTTPException
from .conversion_management_contracts import DeployJobReq, DeployResourceReq, ModelExportReq

import json
import asyncio
import hashlib
import math
import re
import os
import shutil
import sys
import time
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import requests
from fastapi import File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from filelock import FileLock, Timeout
from platform_core.algorithms import project_current_version
from platform_core.conversion import sha256_file, validate_target
from platform_core.errors import PlatformError
from platform_core.model_artifacts import ModelArtifactService, SUCCESSFUL_CONVERSION_STATUSES, delivery_artifact_quality_preflight
from platform_core.material_repository import material_annotation_lifecycle_fence
from platform_core.secrets import secret_ref
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_runtime import TaskKind, TaskRecord, TaskStatus, task_to_public
from platform_core.material_batches import BatchRequestError as MaterialBatchRequestError, assert_material_input_admission
from platform_core.external_algorithm_publish import request_external_auto_publish_for_conversion_if_enabled
from platform_core.remote_execution_transport import RemoteExecutionTransportError, SUPPORTED_PORTABLE_RKNN_CHIPS

@dataclass(frozen=True)
class ConversionManagementDependencies:
    BASE_DIR: Callable[..., Any]
    DATA_DIR: Callable[..., Any]
    DEPLOY_PROCESS_REGISTRY: Callable[..., Any]
    DEPLOY_REMOTE_THREADS: Callable[..., Any]
    DEPLOY_RESOURCES_FILE: Callable[..., Any]
    IMAGE_EXTS: Callable[..., Any]
    V423_DEPLOY_TARGET_NAMES: Callable[..., Any]
    _CONVERSION_HISTORY_PROJECTION: Callable[..., Any]
    _DEPLOY_BUILTIN_RESOURCE_CACHE: Callable[..., Any]
    _DEPLOY_RESOURCES_WRITE_LOCK: Callable[..., Any]
    _algorithm_version_reference_fence: Callable[..., Any]
    _authorize_business_file_project: Callable[..., Any]
    _builtin_deploy_resource_cache_meta: Callable[..., Any]
    _builtin_deploy_resource_summary: Callable[..., Any]
    _builtin_deploy_resources: Callable[..., Any]
    _business_file_url: Callable[..., Any]
    _conversion_contract_for_source: Callable[..., Any]
    _copy_if_exists: Callable[..., Any]
    _create_target_deploy_files: Callable[..., Any]
    _deploy_job_version_identity: Callable[..., Any]
    _deploy_resource_by_id: Callable[..., Any]
    _deploy_resource_public: Callable[..., Any]
    _deploy_resource_runtime: Callable[..., Any]
    _detect_agent_deploy_resource: Callable[..., Any]
    _detect_local_deploy_resource: Callable[..., Any]
    _find_job_for_model: Callable[..., Any]
    _find_model_meta: Callable[..., Any]
    _finish_background_conversion_detection: Callable[..., Any]
    _inspect_conversion_resource: Callable[..., Any]
    _load_saved_deploy_resources: Callable[..., Any]
    _remote_conversion_resource_online: Callable[..., Any]
    _remote_execution_transport_service: Callable[..., Any]
    _resolve_business_file: Callable[..., Any]
    _resolve_deploy_source: Callable[..., Any]
    _run_background_conversion_detection: Callable[..., Any]
    _save_deploy_resources: Callable[..., Any]
    _storage_source_fence: Callable[..., Any]
    _storage_source_runtime_generation: Callable[..., Any]
    _try_export_paddledet_infer: Callable[..., Any]
    _try_export_ultralytics_onnx: Callable[..., Any]
    _v35_secret_store: Callable[..., Any]
    _version_deploy_conversion_defaults: Callable[..., Any]
    _write_export_json: Callable[..., Any]
    _write_export_text: Callable[..., Any]
    _write_job_json: Callable[..., Any]
    _zip_dir: Callable[..., Any]
    algorithm_presentation_store: Callable[..., Any]
    algorithm_repository: Callable[..., Any]
    algorithms_file: Callable[..., Any]
    deploy_root: Callable[..., Any]
    get_active_paddle_env: Callable[..., Any]
    get_active_ultralytics_env: Callable[..., Any]
    get_project: Callable[..., Any]
    job_report: Callable[..., Any]
    list_algorithms_internal: Callable[..., Any]
    list_models_internal: Callable[..., Any]
    load_images: Callable[..., Any]
    material_store: Callable[..., Any]
    now_iso: Callable[..., Any]
    project_dir: Callable[..., Any]
    public_deployment_test: Callable[..., Any]
    read_json: Callable[..., Any]
    resolve_any_model_path: Callable[..., Any]
    resolve_material_path: Callable[..., Any]
    safe_filename: Callable[..., Any]
    shared_task_artifacts: Callable[..., Any]
    shared_task_repository: Callable[..., Any]
    storage_credentials: Callable[..., Any]
    storage_source_repository: Callable[..., Any]
    write_json: Callable[..., Any]


class ConversionManagementService:
    def __init__(self, dependencies: ConversionManagementDependencies):
        self.dependencies = dependencies

    def v39_list_deploy_resources(self, detect_missing: bool = True):
        from platform_core.conversion_resource_detection import observe
        builtin = (self.dependencies._builtin_deploy_resources() if detect_missing else
            (self.dependencies._DEPLOY_BUILTIN_RESOURCE_CACHE().snapshot()["items"] or self.dependencies._builtin_deploy_resource_summary()))
        return {"ok": True, "items": [self.dependencies._deploy_resource_public(observe(x)) for x in builtin + self.dependencies._load_saved_deploy_resources()], **self.dependencies._builtin_deploy_resource_cache_meta()}

    def v39_create_deploy_resource(self, payload: DeployResourceReq):
        if not payload.name.strip():
            raise HTTPException(status_code=400, detail="请输入部署资源名称")
        item = payload.model_dump(); resource_id = uuid.uuid4().hex[:12]
        api_key = str(item.pop("api_key", "") or "")
        if api_key:
            reference = secret_ref("deploy-resource", resource_id)
            self.dependencies._v35_secret_store().set(reference, api_key)
            item["secret_ref"] = reference
        item.update({"id": resource_id, "created_at": self.dependencies.now_iso(), "updated_at": self.dependencies.now_iso(),
                     "config_revision": uuid.uuid4().hex, "status": "unchecked", "targets": []})
        with self.dependencies._DEPLOY_RESOURCES_WRITE_LOCK():
            items = self.dependencies._load_saved_deploy_resources(); items.insert(0, item); self.dependencies._save_deploy_resources(items)
        return self.dependencies._deploy_resource_public(item)

    def v39_update_deploy_resource(self, resource_id: str, payload: DeployResourceReq):
        with self.dependencies._DEPLOY_RESOURCES_WRITE_LOCK():
            items = self.dependencies._load_saved_deploy_resources()
            for i, x in enumerate(items):
                if x.get("id") == resource_id:
                    data = payload.model_dump(); api_key = str(data.pop("api_key", "") or "")
                    # Display-only edits are not SDK changes and must not erase a
                    # legitimate scan, including a scan another Web worker runs.
                    sdk_fields = set(DeployResourceReq.model_fields)-{'name','remark','api_key'}
                    changed = any(data.get(field) != x.get(field, DeployResourceReq.model_fields[field].default)
                                  for field in sdk_fields)
                    reference = str(x.get("secret_ref") or secret_ref("deploy-resource", resource_id))
                    if api_key:
                        previous = self.dependencies._v35_secret_store().get(str(x.get('secret_ref') or '')) if x.get('secret_ref') else ''
                        changed = changed or previous != api_key
                    if not changed and all(x.get(k)==v for k,v in data.items()):
                        return self.dependencies._deploy_resource_public(x)
                    new = {**x, **data, "updated_at": self.dependencies.now_iso()}
                    if changed:
                        new.update(config_revision=uuid.uuid4().hex, status="unchecked", targets=[],
                            supported_chips=[], supported_precisions=[], last_checked_at="", detection_error="")
                        for field in ("remote_health", "sophon_probe", "agent_nodes",
                                      "detection_run", "detection_config_key",
                                      "detection_environment_fingerprint", "detection_timings_ms",
                                      "rknn_python", "rknn_version", "model_transform_path",
                                      "model_deploy_path", "run_calibration_path", "model_tool_path",
                                      "detected_soc_versions"):
                            new.pop(field, None)
                    if api_key:
                        self.dependencies._v35_secret_store().set(reference, api_key); new["secret_ref"] = reference
                    items[i] = new; self.dependencies._save_deploy_resources(items); return self.dependencies._deploy_resource_public(new)
        raise HTTPException(status_code=404, detail="部署资源不存在")

    def v39_delete_deploy_resource(self, resource_id: str):
        with self.dependencies._DEPLOY_RESOURCES_WRITE_LOCK():
            items = self.dependencies._load_saved_deploy_resources()
            removed = next((x for x in items if x.get("id") == resource_id), None)
            if not removed:
                raise HTTPException(status_code=404, detail="部署资源不存在")
            self.dependencies._save_deploy_resources([x for x in items if x.get("id") != resource_id])
        if removed.get("secret_ref"):
            self.dependencies._v35_secret_store().delete(str(removed.get("secret_ref")))
        return {"ok": True}

    def v39_detect_deploy_resource(self, resource_id: str, force: bool = True):
        from platform_core.conversion_resource_detection import observe, resource_configuration_key
        resource = self.dependencies._deploy_resource_by_id(resource_id)
        if resource_id.startswith("builtin_"):
            return self.dependencies._deploy_resource_public(self.dependencies._inspect_conversion_resource(resource, force=force))
        identity = resource_configuration_key(resource)
        run_id = str((resource.get('detection_run') or {}).get('id') or '')
        # Coalesce the same resource across Web workers. Different resource IDs do
        # not hold each other's SDK inspection locks; no global lock during probe.
        probe_lock = self.dependencies.DEPLOY_RESOURCES_FILE().with_name(
            ".conversion-probe-" + hashlib.sha256(resource_id.encode()).hexdigest()[:24] + ".lock")
        lock = FileLock(str(probe_lock), timeout=90)
        waiting_at = time.perf_counter()
        try:
            lock.acquire()
        except Timeout as error:
            raise HTTPException(status_code=409, detail="此转换资源仍在检测中，请稍后读取结果或重试") from error
        lock_wait_ms = round((time.perf_counter()-waiting_at)*1000, 3)
        try:
            fresh = self.dependencies._deploy_resource_by_id(resource_id)
            if resource_configuration_key(fresh) != identity:
                raise HTTPException(409, detail="资源配置已变化，请重新检测")
            if str((fresh.get('detection_run') or {}).get('id') or '') != run_id:
                raise HTTPException(409, detail="检测任务已被新的资源检测取代")
            if str(fresh.get("last_checked_at") or "") != str(resource.get("last_checked_at") or ""):
                # Another worker finished this configuration while we waited.
                return self.dependencies._deploy_resource_public(observe(fresh))
            try:
                checked = self.dependencies._inspect_conversion_resource(fresh, force=force)
            except Exception:
                # detect() already records a timestamped failure observation in
                # its resource cache. Preserve that evidence across Web workers
                # instead of returning an error while leaving an old ready row.
                checked = observe(fresh)
                if (checked.get("detection") or {}).get("state") != "failed":
                    raise
            with self.dependencies._DEPLOY_RESOURCES_WRITE_LOCK():
                items = self.dependencies._load_saved_deploy_resources()
                idx = next((i for i,x in enumerate(items) if x.get("id")==resource_id), None)
                if idx is None or resource_configuration_key(items[idx]) != identity:
                    raise HTTPException(409, detail="资源配置已变化，请重新检测")
                if str((items[idx].get('detection_run') or {}).get('id') or '') != run_id:
                    raise HTTPException(409, detail="检测任务已被新的资源检测取代")
                clean = dict(checked); clean.pop("api_key", None)
                clean['detection_timings_ms'] = {**(clean.get('detection_timings_ms') or {}),
                    'lock_wait_ms':lock_wait_ms}
                # Metadata-only edits may arrive during the SDK scan. Preserve
                # their newer values; they do not invalidate the SDK config key.
                items[idx] = {**items[idx], **{k:v for k,v in clean.items()
                    if k not in {'detection','name','remark','updated_at'}}}
                self.dependencies._save_deploy_resources(items)
        finally:
            lock.release()
        return self.dependencies._deploy_resource_public(checked)

    def v39_start_deploy_resource_detection(self, resource_id: str):
        """Bounded start, shared by tabs/Web workers; status uses the existing GET.

    This is not a second SDK cache or task truth. The saved resource row owns
    its in-flight run ID, and the existing detector/file lock does the work.
    A crashed worker's lease expires in observe(); an explicit retry can claim
    the resource again without ever reporting a fabricated success.
    """
        import socket
        import psutil
        from platform_core.conversion_resource_detection import observe, resource_configuration_key
        if resource_id.startswith('builtin_'):
            # Built-ins use the pre-existing, background-refreshed environment cache.
            return self.dependencies._deploy_resource_public(observe(self.dependencies._deploy_resource_by_id(resource_id)))
        with self.dependencies._DEPLOY_RESOURCES_WRITE_LOCK():
            items = self.dependencies._load_saved_deploy_resources()
            current = next((row for row in items if row.get('id') == resource_id), None)
            if current is None:
                raise HTTPException(status_code=404, detail='部署资源不存在')
            observation = observe(current)
            if observation['detection']['state'] == 'checking':
                return self.dependencies._deploy_resource_public(observation)
            run_id = uuid.uuid4().hex
            current['detection_run'] = {
                'id':run_id, 'state':'checking', 'started_at':self.dependencies.now_iso(),
                'config_key':resource_configuration_key(current),
                'owner_host':socket.gethostname(), 'owner_pid':os.getpid(),
                'owner_started_at':psutil.Process(os.getpid()).create_time(),
            }
            self.dependencies._save_deploy_resources(items)
            pending = self.dependencies._deploy_resource_public(observe(current))
        try:
            thread = threading.Thread(target=self.dependencies._run_background_conversion_detection,
                args=(resource_id, run_id), name='conversion-sdk-'+resource_id, daemon=True)
            thread.start()
        except Exception as error:
            self.dependencies._finish_background_conversion_detection(resource_id, run_id, error)
            raise HTTPException(503, detail='无法启动SDK检测，请检查服务状态后重试') from error
        return pending

    def v39_conversion_resource_detection_status(self, resource_id: str):
        from platform_core.conversion_resource_detection import observe
        return self.dependencies._deploy_resource_public(observe(self.dependencies._deploy_resource_by_id(resource_id)))

    def v39_detect_local_deploy_resources(self, ):
        """只检测当前机器真正存在的部署编译器；不存在的不会伪造为 ready。"""
        from platform_core.conversion_resource_detection import resource_configuration_key
        items = self.dependencies._load_saved_deploy_resources()
        original_items = [dict(row) for row in items]
        found = []
        candidates = [
            {"name":"本机瑞芯微 RKNN-Toolkit2", "kind":"rockchip", "mode":"local", "python_path":sys.executable, "tool_root":""},
            {"name":"本机 NVIDIA TensorRT", "kind":"tensorrt", "mode":"local", "tool_root":""},
            {"name":"本机算能 TPU-MLIR", "kind":"sophon", "mode":"local", "tool_root":os.environ.get("TPUC_ROOT", "")},
            {"name":"本机华为 CANN ATC", "kind":"ascend", "mode":"local", "tool_root":os.environ.get("ASCEND_TOOLKIT_HOME", ""), "env_script":"/usr/local/Ascend/ascend-toolkit/set_env.sh" if os.name != 'nt' else ""},
        ]
        for candidate in candidates:
            existing = next((x for x in items if x.get("kind")==candidate["kind"] and x.get("mode")=="local"), None)
            if existing:
                # Never replace an explicitly configured RKNN Python with sys.executable.
                # Re-detect the user's saved environment, including failure transitions.
                checked = self.dependencies._detect_local_deploy_resource(self.dependencies._deploy_resource_runtime(existing))
                checked.pop("api_key", None)
                if existing.get("secret_ref"):
                    checked["secret_ref"] = existing["secret_ref"]
                checked["updated_at"] = self.dependencies.now_iso()
                index = items.index(existing)
                items[index] = checked
                if checked.get("status") == "ready":
                    found.append(self.dependencies._deploy_resource_public(checked))
                continue
            chk = self.dependencies._detect_local_deploy_resource({**candidate, "id": uuid.uuid4().hex[:12], "created_at":self.dependencies.now_iso(), "updated_at":self.dependencies.now_iso()})
            if chk.get("status") == "ready":
                items.insert(0, chk)
                found.append(self.dependencies._deploy_resource_public(chk))
        with self.dependencies._DEPLOY_RESOURCES_WRITE_LOCK():
            # Explicit auto-detect is a bulk operation. Preserve configurations
            # edited during its slow SDK probes rather than restoring stale rows.
            latest = self.dependencies._load_saved_deploy_resources()
            for detected in items:
                before = next((x for x in original_items if x.get("id")==detected.get("id")), None)
                current = next((x for x in latest if x.get("id")==detected.get("id")), None)
                if before is None:
                    if current is None and detected.get("status")=="ready" and not any(
                        str(row.get("kind") or "")==str(detected.get("kind") or "")
                        and str(row.get("mode") or "local")=="local" for row in latest
                    ):
                        latest.insert(0, detected)
                elif (current is not None and detected != before and
                      resource_configuration_key(current)==resource_configuration_key(before) and
                      str(current.get("last_checked_at") or "")==str(before.get("last_checked_at") or "")):
                    latest[latest.index(current)] = detected
            self.dependencies._save_deploy_resources(latest)
        # A configuration changed while probing must not be reported as one of
        # this request's successful registrations/detections.
        found_ids = {str(row.get("id") or "") for row in found}
        accepted_found = [self.dependencies._deploy_resource_public(row) for row in latest
                          if str(row.get("id") or "") in found_ids
                          and row.get("status") == "ready"
                          and any(str(row.get("last_checked_at") or "") == str(candidate.get("last_checked_at") or "")
                                  for candidate in found if candidate.get("id") == row.get("id"))]
        return {"ok": True, "found": accepted_found, "items": self.dependencies._builtin_deploy_resources() + latest}

    def _deploy_source_models(self, project_id: str) -> List[Dict[str, Any]]:
        items=[]
        for m in self.dependencies.list_models_internal(project_id):
            ext = "." + str(m.get("type") or "")
            if ext in {".pt", ".pth", ".onnx", ".pdparams", ".pdmodel", ".pdiparams", ".engine", ".bmodel", ".om"}:
                items.append({"id":f"model::{m.get('name')}","kind":"project_model","name":m.get("name"),"path":m.get("path"),"type":m.get("type"),"framework":m.get("framework"),"job_id":m.get("job_id"),"config_path":m.get("config_path"),"size_mb":m.get("size_mb"),"label":m.get("name")})
        for a in self.dependencies.list_algorithms_internal(project_id):
            current_version_id = str(a.get("current_version_id") or "")
            versions = list(a.get("versions", []) or [])
            versions.sort(key=lambda version: 0 if str(version.get("id") or "") == current_version_id else 1)
            for v in versions:
                p=Path(str(v.get("stored_path") or ""))
                if p.exists():
                    is_current = str(v.get("id") or "") == current_version_id
                    current_suffix = "（当前）" if is_current else ""
                    items.append({"id":f"version::{a.get('id')}::{v.get('id')}","kind":"algorithm_version","name":v.get("model_name") or p.name,"path":str(p),"type":p.suffix.lower().lstrip('.'),"framework":v.get("report",{}).get("framework", ""),"job_id":v.get("job_id", ""),"config_path":"","size_mb":v.get("size_mb",0),"algorithm_id":a.get("id"),"algorithm_name":a.get("name"),"version_id":v.get("id"),"version_name":v.get("version_name"),"is_current_version":is_current,"label":f"{a.get('name')} / {v.get('version_name')}{current_suffix} / {p.name}"})
        return items

    def _deploy_selected_algorithm_version(self, project_id: str, algorithm_id: str, version_id: str):
        """Read one conversion source through the existing indexed algorithm store.

    The source-model list is a separate browse API. Resolving an explicit
    version must not enumerate every model, job.json or algorithm in a project.
    """
        from platform_core.algorithm_sql_store import AlgorithmSqlStore
        self.dependencies.get_project(project_id)
        algorithm = self.dependencies.algorithm_repository(project_id).read_one(str(algorithm_id))
        if not algorithm:
            return None, None
        version = next((v for v in algorithm.get("versions", [])
                        if str(v.get("id") or "") == str(version_id)), None)
        if version and not version.get("report") and (version.get("job_id") or version.get("stored_path")):
            # Preserve legacy lazy report projection, but only for this version.
            version = dict(version)
            try:
                path = Path(str(version.get("stored_path"))) if version.get("stored_path") else None
                report = self.dependencies.job_report(project_id, version.get("job_id") or "", path)
                if report:
                    version["report"] = report
            except Exception:
                pass
        return project_current_version(algorithm), version

    def v39_deploy_source_models(self, project_id: str):
        return {"ok": True, "items": self._deploy_source_models(project_id)}

    def _deploy_job_dir(self, project_id: str, job_id: str) -> Path:
        return self.dependencies.deploy_root(project_id)/"jobs"/job_id

    def _deploy_prepare_calibration(self, project_id: str, dataset_id: str, split: str, limit: int, dst: Path) -> int:
        dst.mkdir(parents=True, exist_ok=True)
        images=self.dependencies.load_images(project_id)
        selected=[]
        for im in images:
            if dataset_id and im.get("dataset_id","default") != dataset_id: continue
            if split and split != "all" and im.get("split","train") != split: continue
            src=self.dependencies.resolve_material_path(project_id,im)
            selected.append((src, im))
        if limit>0: selected=selected[:limit]
        for i,(src,im) in enumerate(selected):
            shutil.copy2(src,dst/f"{i:05d}_{self.dependencies.safe_filename(im.get('original_name') or src.name)}")
        return len(selected)

    def v39_resolve_conversion(self, project_id: str, payload: DeployJobReq):
        from platform_core.conversion_resource_detection import observe
        from platform_core.conversion_csc import csc_capabilities
        began=time.perf_counter()
        source=self.dependencies._resolve_deploy_source(project_id,payload.source_id)
        source_done=time.perf_counter()
        resource=observe(self.dependencies._deploy_resource_by_id(payload.resource_id)) if payload.resource_id else {}
        resource_done=time.perf_counter()
        result=self.dependencies._conversion_contract_for_source(project_id,source,resource,dict(payload.params or {}),payload.target,preview=True)
        result['timings_ms']={'source_lookup':round((source_done-began)*1000,3),
            'resource_read':round((resource_done-source_done)*1000,3),
            'contract_resolution':round((time.perf_counter()-resource_done)*1000,3),
            'total':round((time.perf_counter()-began)*1000,3)}
        if result.get('ready') and resource and (resource.get('detection') or {}).get('state') in {'not_checked','checking','expired','failed'}:
            result.update(ready=False,status='pending_detection',errors=['所选资源尚未完成有效检测，请检测该资源后重试'])
        result['resource_detection']=resource.get('detection') or {}
        result['csc_capabilities']=csc_capabilities(payload.target)
        return result

    def _write_deploy_job(self, project_id: str, job: Dict[str, Any]):
        jd=self._deploy_job_dir(project_id,job["id"]); jd.mkdir(parents=True,exist_ok=True); self.dependencies._write_job_json(jd/"job.json",job)

    def _read_deploy_job(self, project_id: str, job_id: str) -> Dict[str, Any]:
        jf=self._deploy_job_dir(project_id,job_id)/"job.json"
        if not jf.exists(): raise HTTPException(status_code=404,detail="转换任务不存在")
        return self._overlay_durable_deploy_job(self.dependencies.read_json(jf,{}))

    def _overlay_durable_deploy_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(job or {})
        task_id = str(result.get("task_id") or "")
        repository = self.dependencies.shared_task_repository()
        durable = repository.get(task_id) if task_id else None
        if not durable or durable.kind is not TaskKind.MODEL_CONVERSION:
            return result
        truth = task_to_public(durable, repository)
        result.update(
            durable_status=durable.status.value,
            task_status=truth["status"],
            progress=truth["progress_percent"],
            stage=truth["phase"],
            current_item=truth["current_item"],
            priority=truth["priority"],
            queue_rank=truth["queue_rank"],
            resource_queue_position=truth["resource_queue_position"],
            resource_wait_reason=truth["resource_wait_reason"],
            worker_id=truth["worker_id"],
            lease_expires_at=truth["lease_expires_at"],
        )
        if durable.status is TaskStatus.QUEUED:
            result["status"] = "waiting_resource" if truth["status"] == "WAITING_RESOURCE" else "queued"
        elif durable.status in {TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED}:
            result["status"] = "running"
        elif durable.status is TaskStatus.BLOCKED_BY_HARDWARE:
            result["status"] = "blocked_by_hardware"
        elif durable.status is TaskStatus.BLOCKED_BY_ENVIRONMENT:
            result["status"] = "blocked_by_environment"
        elif durable.status is TaskStatus.CANCELLED:
            result["status"] = "stopped"
        elif durable.status is TaskStatus.FAILED:
            result["status"] = "failed"
        return result

    def _safe_extract_zip(self, zf: zipfile.ZipFile, dst: Path) -> None:
        """Extract zip while rejecting path traversal entries."""
        dst = dst.resolve()
        for member in zf.infolist():
            target = (dst / member.filename).resolve()
            try:
                target.relative_to(dst)
            except ValueError:
                raise RuntimeError(f"ZIP 包含非法路径：{member.filename}")
        zf.extractall(dst)

    def _sync_remote_deploy_job(self, project_id: str, job_id: str):
        jd=self._deploy_job_dir(project_id,job_id); jf=jd/"job.json"; job=self.dependencies.read_json(jf,{})
        resource=self.dependencies._deploy_resource_by_id(str(job.get("resource_id") or "")); base=str(resource.get("base_url") or "").rstrip("/"); key=str(resource.get("api_key") or "")
        try:
            source_raw = str(job.get("source_path") or "").strip()
            source = Path(source_raw) if source_raw else None
            if source is None or not source.is_file():
                raise ValueError("远程转换源模型不存在或不是有效文件，请检查任务源文件")
            params = job.get("params") or {}
            # Path("") becomes "."; an absent optional config is not a file.
            config_raw = str(params.get("config_path") or "").strip()
            cfg = Path(config_raw).expanduser() if config_raw else None
            if cfg is not None and not cfg.is_file():
                raise ValueError("远程转换配置文件不存在或不是有效文件，请检查 config_path")
            files={"source_model":(source.name,source.open("rb"),"application/octet-stream")}
            cfg_fp=None
            if cfg is not None: cfg_fp=cfg.open("rb"); files["config_file"]=(cfg.name,cfg_fp,"application/octet-stream")
            cal_dir=Path(job.get("calibration_dir") or "") if job.get("calibration_dir") else None
            cal_zip=None
            if cal_dir and cal_dir.exists():
                cal_zip=jd/"calibration.zip"
                with zipfile.ZipFile(cal_zip,"w",zipfile.ZIP_DEFLATED) as zf:
                    for p in cal_dir.rglob("*"):
                        if p.is_file(): zf.write(p,p.relative_to(cal_dir))
                files["calibration_zip"]=(cal_zip.name,cal_zip.open("rb"),"application/zip")
            job.update({"status":"running","stage":"上传到转换服务器","progress":5,"message":"正在上传源模型","updated_at":self.dependencies.now_iso()});self.dependencies._write_job_json(jf,job)
            r=requests.post(base+"/api/deploy/convert",headers={"X-API-Key":key},files=files,data={"target":job.get("target"),"params_json":json.dumps(params,ensure_ascii=False),"source_trace_json":json.dumps(job.get("source_trace") or {},ensure_ascii=False)},timeout=600)
            for v in files.values():
                try:v[1].close()
                except:pass
            if not r.ok: raise RuntimeError(f"远程创建任务失败 HTTP {r.status_code}: {r.text[:1000]}")
            rid=r.json().get("job_id"); job["remote_job_id"]=rid; job["stage"]="远程转换中"; job["progress"]=8;self.dependencies._write_job_json(jf,job)
            while True:
                cur=self.dependencies.read_json(jf,{})
                if cur.get("cancel_requested"):
                    try:requests.post(base+f"/api/deploy/jobs/{rid}/stop",headers={"X-API-Key":key},timeout=10)
                    except:pass
                    cur.update(status="stopped",stage="已停止",message="用户停止",updated_at=self.dependencies.now_iso());self.dependencies._write_job_json(jf,cur);return
                rr=requests.get(base+f"/api/deploy/jobs/{rid}",headers={"X-API-Key":key},timeout=15)
                if not rr.ok: raise RuntimeError(f"同步远程任务失败：{rr.text[:800]}")
                remote=rr.json()
                lr=requests.get(base+f"/api/deploy/jobs/{rid}/log",headers={"X-API-Key":key},timeout=15)
                if lr.ok:(jd/"convert.log").write_text(lr.text,encoding="utf-8",errors="ignore")
                cur=self.dependencies.read_json(jf,{})
                cur.update(status=remote.get("status",cur.get("status")),stage=remote.get("stage",cur.get("stage")),progress=remote.get("progress",cur.get("progress",0)),message=remote.get("message",cur.get("message")),error=remote.get("error",""),updated_at=self.dependencies.now_iso(),remote_status=remote)
                self.dependencies._write_job_json(jf,cur)
                if remote.get("status") in {"done","failed","stopped"}: break
                time.sleep(2)
            cur=self.dependencies.read_json(jf,{})
            if cur.get("status")=="done":
                zr=requests.get(base+f"/api/deploy/jobs/{rid}/artifacts.zip",headers={"X-API-Key":key},timeout=600)
                if not zr.ok: raise RuntimeError("远程转换完成，但部署产物下载失败："+zr.text[:800])
                zp=jd/"remote_artifacts.zip";zp.write_bytes(zr.content);ad=jd/"artifacts";ad.mkdir(exist_ok=True)
                with zipfile.ZipFile(zp,"r") as zf:self._safe_extract_zip(zf,ad)
                outputs=[]
                for p in ad.rglob("*"):
                    if p.is_file():
                        outputs.append({"name":p.name,"path":str(p),"rel":str(p.relative_to(jd)),
                                        "size_mb":round(p.stat().st_size/1024/1024,3),
                                        "size_bytes":p.stat().st_size,"sha256":sha256_file(p)})
                # Local receipt has an explicit timezone and is not a fabricated
                # remote-worker completion event.
                received_at=datetime.now(timezone.utc).isoformat()
                manifest_path=ad/"manifest.json"
                cur.update(outputs=outputs,finished_at=received_at,conversion_finished_at=received_at,
                           conversion_completion_source="local_artifact_receipt_utc",
                           manifest_path=str(manifest_path) if manifest_path.is_file() else "",
                           message="远程转换完成，部署产物已拉回平台",progress=100)
                self.dependencies._write_job_json(jf,cur)
                request_external_auto_publish_for_conversion_if_enabled(
                    data_dir=self.dependencies.DATA_DIR(), project_id=project_id, conversion_job=cur,
                )
        except Exception as e:
            cur=self.dependencies.read_json(jf,job);cur.update(status="failed",stage="转换失败",message=str(e),error=str(e),finished_at=self.dependencies.now_iso(),updated_at=self.dependencies.now_iso());self.dependencies._write_job_json(jf,cur)
            with (jd/"convert.log").open("a",encoding="utf-8",errors="ignore") as f:f.write(f"\n[{self.dependencies.now_iso()}] 远程转换失败：{e}\n")
        finally:
            self.dependencies.DEPLOY_REMOTE_THREADS().pop(job_id,None)

    def v39_create_deploy_job(self, project_id: str, payload: DeployJobReq):
        if not payload.request_id:
            return self._v39_create_deploy_job_with_version_fence(project_id, payload)
        job_id = self._deploy_request_job_id(project_id, payload.request_id)
        locks = self.dependencies.DATA_DIR() / "task_runtime" / "conversion_create_locks"
        locks.mkdir(parents=True, exist_ok=True)
        try:
            # Only the same idempotency key is serialized. Other conversions do not
            # contend for this lock; persistent jobs remain the single source of truth.
            with FileLock(str(locks / f"{job_id}.lock"), timeout=30):
                job_path = self._deploy_job_dir(project_id, job_id)
                if (job_path / "job.json").exists():
                    previous = self.dependencies.read_json(job_path / "job.json", {})
                    if (previous.get("project_id") != project_id or
                            previous.get("request_id") != payload.request_id or
                            previous.get("request_identity") != self._deploy_request_identity(payload)):
                        raise HTTPException(status_code=409, detail="转换请求 ID 已绑定不同内容，不可重复提交")
                    return {"ok": True, "job": self._read_deploy_job(project_id, job_id), "idempotent": True}
                if job_path.exists():
                    # A crash may leave source/calibration files without a durable
                    # receipt. Never silently launch a second conversion over them.
                    raise HTTPException(status_code=409, detail="转换请求存在未确认的准备目录，请检查原任务后处理")
                return self._v39_create_deploy_job_with_version_fence(project_id, payload)
        except Timeout as error:
            raise PlatformError(
                code="CONVERSION_CREATE_IN_PROGRESS", status_code=409,
                message="相同转换请求正在创建，请按请求 ID 查询结果",
                detail=payload.request_id, solution="请保留原请求 ID，不要换一个 ID 重复提交。",
            ) from error

    def _deploy_request_job_id(self, project_id: str, request_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{12,80}", str(request_id or "")):
            raise HTTPException(status_code=422, detail="转换请求 ID 格式不正确")
        return hashlib.sha256(f"conversion\x00{project_id}\x00{request_id}".encode("utf-8")).hexdigest()[:24]

    def _deploy_request_identity(self, payload: DeployJobReq) -> str:
        canonical = payload.model_dump(mode="json", exclude={"request_id"})
        return hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest()

    def v39_conversion_job_by_request(self, project_id: str, request_id: str):
        self.dependencies.get_project(project_id)
        job_id = self._deploy_request_job_id(project_id, request_id)
        path = self._deploy_job_dir(project_id, job_id)
        if (path / "job.json").exists():
            job = self.dependencies.read_json(path / "job.json", {})
            if job.get("project_id") == project_id and job.get("request_id") == request_id:
                return {"ok": True, "found": True, "pending": False,
                        "job": self._read_deploy_job(project_id, job_id)}
            raise HTTPException(status_code=409, detail="转换请求 ID 状态冲突")
        # A submitted HTTP request may still be preparing input files before its
        # first job receipt. No-result alone is never permission to use a new ID.
        return {"ok": True, "found": False, "pending": path.exists()}

    def _v39_create_deploy_job_with_version_fence(self, project_id: str, payload: DeployJobReq):
        source = self.dependencies._resolve_deploy_source(project_id, payload.source_id)
        algorithm_id = str(source.get("algorithm_id") or "").strip()
        version_id = str(source.get("version_id") or "").strip()
        from platform_core.model_artifacts import conversion_catalog_fence
        with self.dependencies._algorithm_version_reference_fence(
            project_id, algorithm_id, version_id,
        ):
            with conversion_catalog_fence(self.dependencies.DATA_DIR()):
                return self._v39_create_deploy_job_under_version_fence(project_id, payload)

    def _v39_create_deploy_job_under_version_fence(self,
        project_id: str,
        payload: DeployJobReq,
    ):
        source=self.dependencies._resolve_deploy_source(project_id,payload.source_id)
        # Safe-launch isolation: legacy Material.split is not the algorithm
        # version's frozen train/validation/test Snapshot. Do not silently
        # calibrate version INT8 from unrelated live material.
        if (
            str(source.get("kind") or "") == "algorithm_version"
            and str((payload.params or {}).get("precision") or "").strip().lower() == "int8"
        ):
            raise HTTPException(
                status_code=409,
                detail="算法版本 INT8 转换暂时停用：校准集尚未与版本冻结 Snapshot 绑定；可选择 FP16 或 ONNX。",
            )
        from platform_core.conversion_resource_detection import observe
        resource=observe(self.dependencies._deploy_resource_by_id(payload.resource_id))
        resource_mode = str(resource.get("mode") or "local").strip().lower()
        chip_target = str(payload.target or "").strip().lower() in {"rockchip", "sophon", "ascend"}
        if chip_target:
            if str(resource.get("kind") or "").strip().lower() != str(payload.target).strip().lower():
                raise HTTPException(status_code=400, detail=f"{payload.target} 转换必须选择对应芯片部署资源")
        # Every configured SDK/remote/Agent resource has the same evidence gate.
        # Built-in ONNX/Paddle exports are freshly checked by their existing
        # environment scanner and have no saved config-revision record.
        if not resource.get('builtin'):
            evidence = resource.get('detection') or {}
            if evidence.get('state') != 'available':
                code = 400 if evidence.get('state') in {'failed', 'unavailable'} else 409
                raise HTTPException(status_code=code, detail='SDK能力证据不可用于正式转换（'+str(evidence.get('state') or 'unknown')+'）；请在转换资源中检测并等待完成')
        if resource_mode == "agent":
            # Agent registry is a lightweight online/authorization observation;
            # keep the frozen SDK capability from the saved detector result.
            live_agent = self.dependencies._detect_agent_deploy_resource(resource)
            if live_agent.get('status') != 'ready':
                raise HTTPException(status_code=409, detail='当前没有在线且已授权的转换 Agent')
        elif resource_mode == "remote":
            self.dependencies._remote_conversion_resource_online(resource)
        else:
            for field in ('python_path', 'tool_root', 'env_script'):
                location = str(resource.get(field) or '').strip()
                if location and not Path(location).exists():
                    raise HTTPException(status_code=409, detail=f'本机SDK环境路径已不可访问：{field}，请重新检测')
        if resource.get("status") != "ready":
            raise HTTPException(status_code=400, detail="当前部署资源不可用，请先到“部署资源”执行检测")
        if payload.target not in (resource.get("targets") or []):
            # Ultralytics/Paddle 内置资源只做直接导出；芯片转换必须选择对应芯片资源。
            raise HTTPException(status_code=400, detail=f"该资源不支持 {payload.target}。当前支持：{', '.join(resource.get('targets') or []) or '无'}")
        params=dict(payload.params or {})
        params.pop("onnx_source_reused", None)
        if payload.target in {"sophon","rockchip","ascend"}:
            # Discard inherited deployment precision: training dtype is not a compiler default.
            if not (payload.params or {}).get("precision"):
                params.pop("precision", None)
            contract=self.dependencies._conversion_contract_for_source(project_id,source,resource,params,payload.target)
            if not contract["ready"]:
                raise HTTPException(status_code=400,detail="；".join(contract["errors"])+"（请求芯片："+str(params.get("chip") or params.get("local_chip_id") or "未选择")+"）")
            params=contract["params"]
            params["parameter_sources"]=contract["parameter_sources"]
        version = source.get("_resolved_version")
        if str(source.get("kind") or "") == "algorithm_version":
            if version is None:
                algorithm = next((a for a in self.dependencies.list_algorithms_internal(project_id)
                                  if str(a.get("id") or "") == str(source.get("algorithm_id") or "")), None)
                version = next((v for v in (algorithm.get("versions") or [])
                                if str(v.get("id") or "") == str(source.get("version_id") or "")), None) if algorithm else None
            if version:
                defaults = self.dependencies._version_deploy_conversion_defaults(project_id, version)
                if payload.target == "sophon" and not any(params.get(k) for k in ("input_size", "input_height", "input_width")):
                    params["input_height"] = defaults["input_height"]
                    params["input_width"] = defaults["input_width"]
                if not str(params.get("input_size") or "").strip():
                    params["input_size"] = defaults["input_size"]
                if not str(params.get("precision") or "").strip():
                    inherited = defaults.get("training_precision") or "fp16"
                    if str(payload.target or "").lower() == "rockchip":
                        supported = {
                            str(value or "").lower()
                            for value in (resource.get("supported_precisions") or ["fp16", "int8"])
                        }
                        inherited = inherited if inherited in supported else ("fp16" if "fp16" in supported else "")
                        if not inherited:
                            raise HTTPException(status_code=400, detail="RKNN 资源不支持训练精度且未提供 FP16 兼容精度；请检查转换资源。")
                    params["precision"] = inherited
                params["source_training_precision"] = defaults.get("training_precision") or ""
                params["source_training_imgsz"] = defaults["input_size"]
        if str(payload.target or "").strip().lower() == "rockchip":
            precision = str(params.get("precision") or "fp16").strip().lower()
            chip = str(params.get("chip") or "").strip().lower()
            supported_chips = {
                str(value or "").strip().lower()
                for value in (resource.get("supported_chips") or [])
                if re.fullmatch(r"rk\d{4}",str(value or "").strip().lower())
            }
            supported_precisions = {
                str(value or "").strip().lower()
                for value in (resource.get("supported_precisions") or ["fp16", "int8"])
                if str(value or "").strip()
            }
            if precision not in supported_precisions:
                raise HTTPException(
                    status_code=400,
                    detail=f"该 RKNN 资源当前不支持精度 {precision or '未选择'}；可用：{'、'.join(sorted(supported_precisions)) or '无'}",
                )
            if not chip or chip not in supported_chips:
                raise HTTPException(
                    status_code=400,
                    detail=f"该 RKNN 资源当前不支持芯片 {chip or '未选择'}；实际已检测可用：{'、'.join(sorted(supported_chips)) or '无'}",
                )
            params["chip"] = chip
        portable_calibration = None
        calibration_source_generations: Dict[str, tuple[Any, ...]] = {}
        if (
            resource_mode == "agent"
            and str(payload.target or "").strip().lower() == "rockchip"
            and str(params.get("precision") or "fp16").strip().lower() == "int8"
        ):
            with self.dependencies._storage_source_fence():
                calibration_source_generations = {
                    candidate.id: self.dependencies._storage_source_runtime_generation(candidate)
                    for candidate in self.dependencies.storage_source_repository().list()
                }
            try:
                portable_calibration = self.dependencies._remote_execution_transport_service().build_rknn_calibration_snapshot(
                    project_id=project_id,
                    dataset_id=payload.dataset_id,
                    split=payload.calibration_split,
                    limit=max(1, int(payload.calibration_count)),
                )
            except RemoteExecutionTransportError as error:
                raise PlatformError(
                    code=error.code,
                    message="RKNN INT8 校准集准备失败",
                    detail=str(error),
                    solution="请确认校准图片位于已启用 OSS/S3/MinIO，且每张图片都有稳定 object_key、size 与 SHA256，然后重试。",
                    status_code=error.status_code,
                ) from error
            params["calibration_count"] = int(portable_calibration["item_count"])
            params["calibration_snapshot"] = str(portable_calibration["snapshot_id"])
        job_id=(self._deploy_request_job_id(project_id, payload.request_id)
                if payload.request_id else uuid.uuid4().hex[:12])
        jd=self._deploy_job_dir(project_id,job_id);srcd=jd/"source";srcd.mkdir(parents=True,exist_ok=True)
        src=Path(str(source.get("path")));local_src=srcd/src.name;shutil.copy2(src,local_src)
        params.setdefault("config_path",source.get("config_path") or "")
        params.setdefault("model_name",src.stem)

        # 芯片 SDK 的 Python 往往和训练/导出 Python 不是同一个环境。
        # 在任务快照里同时保存 Ultralytics/Paddle 导出环境，确保 .pt/.pdparams 能先真实转 ONNX，再进入厂商编译器。
        resource_for_job=self.dependencies._deploy_resource_public(resource)
        ultra_env=self.dependencies.get_active_ultralytics_env() or {}
        if ultra_env.get("python_path") and not resource_for_job.get("ultralytics_python"):
            resource_for_job["ultralytics_python"]=ultra_env.get("python_path")
        paddle_env=self.dependencies.get_active_paddle_env() or {}
        if paddle_env.get("python_path") and not resource_for_job.get("paddle_python"):
            resource_for_job["paddle_python"]=paddle_env.get("python_path")
        if paddle_env.get("paddledet_dir") and not resource_for_job.get("paddledet_dir"):
            resource_for_job["paddledet_dir"]=paddle_env.get("paddledet_dir")
        if paddle_env.get("paddle2onnx_path") and not resource_for_job.get("paddle2onnx_path"):
            resource_for_job["paddle2onnx_path"]=paddle_env.get("paddle2onnx_path")
        cal_dir=None
        if resource_mode != "agent" and payload.target in {"sophon", "rockchip", "tensorrt"} and str(params.get("precision") or "").lower()=="int8":
            cal_dir=jd/"calibration"
            count=self._deploy_prepare_calibration(project_id,payload.dataset_id,payload.calibration_split,max(1,int(payload.calibration_count)),cal_dir)
            if count<=0: raise HTTPException(status_code=400,detail="INT8 转换需要校准图片，但当前选择的数据集/分组没有可用图片")
            params["calibration_count"]=count
            calibration_hash = hashlib.sha256()
            for image_path in sorted(path for path in cal_dir.rglob('*') if path.is_file()):
                calibration_hash.update(image_path.name.encode('utf-8'))
                calibration_hash.update(sha256_file(image_path).encode('ascii'))
            params["calibration_snapshot"] = calibration_hash.hexdigest()
        if payload.target == "onnx" and src.suffix.lower() == ".onnx":
            for key in ("precision", "opset", "simplify", "dynamic", "input_size", "input_width", "input_height", "batch"):
                params.pop(key, None)
            params["onnx_source_reused"] = True
        try:
            params = validate_target(payload.target, params)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        source_sha256 = sha256_file(local_src)
        source_trace = {
            "source_id": payload.source_id,
            "version_id": source.get("version_id") or "",
            "algorithm_id": source.get("algorithm_id") or "",
            "sha256": source_sha256,
        }
        # The label order belongs to the trained model, not to today's project
        # catalog. Freeze it for every conversion target so ONNX/RKNN/TRT/OM
        # evidence can never silently compare a different class order.
        if version:
            for field in ("label_schema", "label_codes", "yolo", "training_lineage", "snapshot_id", "snapshot"):
                if field in version:
                    source_trace[field] = json.loads(json.dumps(version[field], ensure_ascii=False))
            from platform_core.model_metadata import model_metadata
            frozen_labels = model_metadata(self.dependencies.DATA_DIR(), version)
            raw_status = str(frozen_labels.get("label_validation_status") or "UNKNOWN").lower()
            status = raw_status if raw_status in {"verified", "unknown", "conflict"} else "unknown"
            codes = list(frozen_labels.get("tags") or []) if status == "verified" else []
            schema = source_trace.get("label_schema")
            schema_rows = schema if isinstance(schema, list) else []
            try:
                schema_rows = sorted(schema_rows, key=lambda row: int(row.get("class_id")))
            except (TypeError, ValueError):
                schema_rows = []
            if status == "verified":
                source_trace["label_codes"] = codes
            source_trace["label_binding"] = {
                "status": status,
                "source": frozen_labels.get("label_source") or "unknown",
                "class_count": len(codes) if status == "verified" else None,
                "class_ids": [row.get("class_id") for row in schema_rows] if status == "verified" else [],
                "mapping_sha256": hashlib.sha256(json.dumps(codes,
                    ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
                    if status == "verified" else "",
                "schema_sha256": hashlib.sha256(json.dumps(schema_rows,
                    ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                    if schema_rows else "",
                "source_sha256": source_sha256,
                "algorithm_id": str(source.get("algorithm_id") or ""),
                "version_id": str(source.get("version_id") or ""),
                "reason": str(frozen_labels.get("label_error") or "")[:500],
            }
            if status == "verified":
                class_ids = [row.get("class_id") for row in schema_rows] if schema_rows else list(range(len(codes)))
                if (class_ids != list(range(len(codes)))
                        or len(codes) == 0
                        or (schema_rows and [str(row.get("code") or "").strip() for row in schema_rows] != codes)):
                    source_trace["label_binding"].update(
                        status="conflict", class_count=None, class_ids=[],
                        mapping_sha256="", reason="class_id/order/code 与冻结类别映射不一致",
                    )
                    source_trace.pop("label_codes", None)
                else:
                    source_trace["label_binding"]["class_ids"] = class_ids
            else:
                # A historical label_codes field may be an unverified claim. It must
                # not survive as if it were the formal verified contract.
                source_trace.pop("label_codes", None)
        else:
            source_trace["label_binding"] = {
                "status": "unknown",
                "source": "unknown",
                "class_count": None,
                "class_ids": [],
                "mapping_sha256": "",
                "schema_sha256": "",
                "source_sha256": source_sha256,
                "algorithm_id": str(source.get("algorithm_id") or ""),
                "version_id": str(source.get("version_id") or ""),
                "reason": "源模型版本不可用，无法取得冻结类别合同",
            }
        preprocessing = params.get("preprocessing") if isinstance(params.get("preprocessing"), Mapping) else {}
        source_trace["preprocessing_contract"] = {
            "status": "declared" if preprocessing else "unknown",
            "owner": preprocessing.get("owner", "caller"),
            "pixel_format": preprocessing.get("pixel_format", ""),
            "channel_format": preprocessing.get("channel_format", ""),
            "letterbox": preprocessing.get("letterbox"),
            "letterbox_mode": preprocessing.get("letterbox_mode", ""),
            "pad_value": preprocessing.get("pad_value"),
            "resize_interpolation": preprocessing.get("resize_interpolation", ""),
            "mean": preprocessing.get("mean"),
            "scale": preprocessing.get("scale"),
            "input_width": params.get("input_width"),
            "input_height": params.get("input_height"),
            "batch": params.get("batch"),
            "dynamic": params.get("dynamic"),
        }
        source_trace["output_contract"] = {
            "status": "declared" if params.get("model_output_contract") else "unsupported",
            "layout": params.get("model_output_contract") or "",
        }
        job={"id":job_id,"project_id":project_id,"source_id":payload.source_id,"source_name":src.name,"source_path":str(local_src),"source_meta":{k:v for k,v in source.items() if k!="_resolved_version"},"source_trace":source_trace,"target":payload.target,"resource_id":payload.resource_id,"resource":resource_for_job,"params":params,"requested_params":dict(payload.params or {}),"dataset_id":payload.dataset_id,"calibration_split":payload.calibration_split,"calibration_dir":str(cal_dir) if cal_dir else "","status":"queued","stage":"等待启动","progress":0,"message":"等待启动","created_at":self.dependencies.now_iso(),"updated_at":self.dependencies.now_iso(),"outputs":[],"request_id":str(payload.request_id or ""),"request_identity":self._deploy_request_identity(payload) if payload.request_id else ""}
        portable_conversion = None
        conversion_target = str(payload.target or "").strip().lower()
        should_stage_portable = (
            (resource_mode == "agent" and conversion_target in {"onnx", "rockchip"})
            or (resource_mode == "local" and conversion_target == "onnx")
        )
        if should_stage_portable:
            try:
                portable_conversion = self.dependencies._remote_execution_transport_service().stage_model_conversion(
                    project_id=project_id,
                    task_id=job_id,
                    source_id=payload.source_id,
                    source_path=src,
                    algorithm_id=str(source.get("algorithm_id") or ""),
                    version_id=str(source.get("version_id") or ""),
                    target=payload.target,
                    params=params,
                    calibration_snapshot=portable_calibration,
                )
                job["remote_portability"] = {
                    "status": "ready",
                    "transport": "object-storage-v1",
                    "task_kind": "MODEL_CONVERSION",
                }
            except RemoteExecutionTransportError as error:
                if resource_mode == "agent":
                    raise PlatformError(
                        code=error.code,
                        message="Agent 模型转换准备失败",
                        detail=str(error),
                        solution="请检查模型资产对象存储、源模型完整性、目标参数以及 Agent conversion / conversion.rknn 节点状态后重试。",
                        status_code=error.status_code,
                    ) from error
                # Portable staging remains additive for the existing local path.
                job["remote_portability"] = {
                    "status": "unavailable",
                    "code": error.code,
                    "message": str(error),
                }
        if resource_mode=="remote" and conversion_target != "sophon":
            self._write_deploy_job(project_id,job)
            th=threading.Thread(target=self._sync_remote_deploy_job,args=(project_id,job_id),daemon=True);self.dependencies.DEPLOY_REMOTE_THREADS()[job_id]=th;th.start()
        else:
            request_payload = {
                "algorithm_id": str(source.get("algorithm_id") or source_trace.get("algorithm_id") or ""),
                "version_id": str(source.get("version_id") or source_trace.get("version_id") or ""),
                "source_id": str(source.get("id") or job["source_id"]),
                "job_dir": str(jd),
                "worker_path": str(self.dependencies.BASE_DIR() / "deployment_worker.py"),
                "python_path": sys.executable,
                "execution_mode": resource_mode,
                "target": conversion_target,
            }
            if resource_mode == "remote":
                request_payload["remote_connection"] = {"base_url": resource.get("base_url"), "secret_ref": resource.get("secret_ref")}
            if portable_conversion is not None:
                request_payload["remote_execution"] = portable_conversion
            calibration_items = list(
                ((portable_calibration or {}).get("items") or [])
            )
            try:
                with self.dependencies._storage_source_fence(), material_annotation_lifecycle_fence(
                    self.dependencies.project_dir(project_id)
                ):
                    if calibration_items:
                        current_sources = self.dependencies.storage_source_repository()
                        changed_sources = set()
                        for item in calibration_items:
                            calibration_source_id = str(
                                item.get("storage_source_id") or ""
                            )
                            if not calibration_source_id:
                                continue
                            current_source = current_sources.get(calibration_source_id)
                            current_generation = (
                                self.dependencies._storage_source_runtime_generation(current_source)
                                if current_source is not None
                                else None
                            )
                            if current_generation != calibration_source_generations.get(
                                calibration_source_id
                            ):
                                changed_sources.add(calibration_source_id)
                        changed_sources = sorted(changed_sources)
                        if changed_sources:
                            raise PlatformError(
                                "STORAGE_SOURCE_GENERATION_CHANGED",
                                "RKNN 校准存储源在任务准备期间已变化",
                                "、".join(changed_sources),
                                "请刷新校准素材并重新创建转换任务。",
                                409,
                            )
                        assert_material_input_admission(
                            project_id,
                            [str(item.get("image_id") or "") for item in calibration_items],
                            self.dependencies.material_store(project_id),
                            self.dependencies.shared_task_repository(),
                            self.dependencies.shared_task_artifacts(),
                            expected_inputs=calibration_items,
                        )
                    self._write_deploy_job(project_id,job)
                    self.dependencies.shared_task_artifacts().atomic_write_json(job_id, "request.json", request_payload)
                    self.dependencies.shared_task_repository().create(TaskRecord.new(
                        job_id, project_id, TaskKind.MODEL_CONVERSION, "request.json",
                        f"conversion:{resource.get('id') or payload.target}",
                        required_capabilities=(
                            ("agent.remote",)
                            if resource_mode == "agent"
                            else ("conversion.runtime",)
                        ),
                    ))
            except MaterialBatchRequestError as error:
                raise PlatformError(
                    code=error.code,
                    message="模型转换素材已不可安全受理",
                    detail=str(error),
                    solution="请等待素材删除结束后刷新校准集，或取消删除任务后重试。",
                    status_code=error.status_code,
                ) from error
            job["task_id"] = job_id
            self._write_deploy_job(project_id, job)
        return {"ok":True,"job":job}

    def _eligible_rknn_board_nodes(self, chip: str) -> list[dict[str, Any]]:
        chip = str(chip or "").strip().lower()
        if chip not in SUPPORTED_PORTABLE_RKNN_CHIPS:
            return []
        rows = ServiceNodeRepository(self.dependencies.shared_task_repository()).list_public()
        eligible = []
        for node in rows:
            if (
                str(node.get("connection_mode") or "") != "agent"
                or not bool(node.get("online"))
                or "deployment-test.rknn" not in set(node.get("effective_capabilities") or [])
            ):
                continue
            runtime = node.get("runtime")
            runtime = dict(runtime) if isinstance(runtime, Mapping) else {}
            board = runtime.get("rknn_board")
            board = dict(board) if isinstance(board, Mapping) else {}
            if not bool(board.get("available")) or str(board.get("chip") or "").strip().lower() != chip:
                continue
            eligible.append({
                "node_id": str(node.get("node_id") or ""),
                "display_name": str(node.get("display_name") or ""),
                "build_id": str(node.get("build_id") or ""),
                "chip": chip,
                "rknn_lite_version": str(board.get("rknn_lite_version") or ""),
            })
        return eligible

    def _rknn_hardware_validation_context(self, project_id: str, job_id: str) -> dict[str, Any]:
        self.dependencies.get_project(project_id)
        job = self._read_deploy_job(project_id, job_id)
        if str(job.get("target") or "").strip().lower() not in {"rockchip", "rknn"}:
            raise HTTPException(status_code=400, detail="只有 RKNN 转换任务支持瑞芯微板端验证")
        job_dir = self._deploy_job_dir(project_id, job_id).resolve()
        manifest_path = (job_dir / "artifacts" / "manifest.json").resolve()
        if not manifest_path.is_file():
            raise HTTPException(status_code=409, detail="RKNN 转换产物尚未形成可验证 manifest")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise HTTPException(status_code=409, detail="RKNN 转换 manifest 无法读取")
        target = manifest.get("target") if isinstance(manifest, Mapping) else None
        output = manifest.get("output") if isinstance(manifest, Mapping) else None
        if (
            not isinstance(target, Mapping)
            or str(target.get("kind") or "") != "rockchip"
            or not isinstance(output, Mapping)
        ):
            raise HTTPException(status_code=409, detail="当前转换结果不是可验证的 RKNN 产物")
        chip = str(target.get("chip") or "").strip().lower()
        if chip not in SUPPORTED_PORTABLE_RKNN_CHIPS:
            raise HTTPException(status_code=400, detail=f"当前板端验证不支持芯片 {chip or '未指定'}")

        model_name = Path(str(output.get("file_name") or "")).name
        model_path = (job_dir / "artifacts" / model_name).resolve()
        if (
            not model_name
            or model_path.parent != (job_dir / "artifacts").resolve()
            or model_path.suffix.lower() != ".rknn"
            or not model_path.is_file()
            or model_path.stat().st_size <= 0
        ):
            raise HTTPException(status_code=409, detail="RKNN 模型文件不存在或不可验证")
        expected_sha = str(output.get("sha256") or "").strip().lower()
        try:
            expected_size = int(output.get("size_bytes") or 0)
        except (TypeError, ValueError):
            expected_size = 0
        if (
            not re.fullmatch(r"[0-9a-f]{64}", expected_sha)
            or expected_size <= 0
            or model_path.stat().st_size != expected_size
            or sha256_file(model_path) != expected_sha
        ):
            raise HTTPException(status_code=409, detail="RKNN 模型与转换 manifest 的 size/SHA256 不一致")

        return {
            "job": job,
            "job_dir": job_dir,
            "manifest": manifest,
            "chip": chip,
            "model_name": model_name,
            "model_path": model_path,
            "model_sha256": expected_sha,
            "model_size_bytes": expected_size,
            "hardware_verified": manifest.get("hardware_verified") is True,
            "board_nodes": self._eligible_rknn_board_nodes(chip),
        }

    def v39_rknn_hardware_test_preflight(self, project_id: str, job_id: str):
        context = self._rknn_hardware_validation_context(project_id, job_id)
        nodes = list(context["board_nodes"])
        already_verified = bool(context["hardware_verified"])
        ready = bool(nodes) and not already_verified
        reason = ""
        solution = ""
        if already_verified:
            reason = "该 RKNN 产物已完成板端 Runtime 验证"
        elif not nodes:
            reason = f"当前没有匹配 {str(context['chip']).upper()} 的在线瑞芯微板端节点"
            solution = "请先在对应 Rockchip 设备安装 Node Agent / RKNNLite，并确认节点 ONLINE 且 effective capability 包含 deployment-test.rknn。"
        return {
            "ok": True,
            "ready": ready,
            "already_verified": already_verified,
            "chip": context["chip"],
            "model": {
                "file_name": context["model_name"],
                "size_bytes": context["model_size_bytes"],
                "sha256": context["model_sha256"],
            },
            "board_nodes": nodes,
            "reason": reason,
            "solution": solution,
        }

    def _rknn_hardware_acceptance_report(self, project_id: str, job_id: str) -> dict[str, Any]:
        context = self._rknn_hardware_validation_context(project_id, job_id)
        if not context["hardware_verified"]:
            raise HTTPException(status_code=409, detail="该 RKNN 产物尚未完成真实板端 Runtime 验证")
        manifest = context["manifest"]
        job = context["job"]
        verification = manifest.get("hardware_verification") if isinstance(manifest, Mapping) else None
        job_verification = job.get("hardware_verification") if isinstance(job, Mapping) else None
        if not isinstance(verification, Mapping):
            raise HTTPException(status_code=409, detail="当前板端验收记录缺少 durable hardware_verification 证据")
        chip = str(verification.get("chip") or "").strip().lower()
        task_id = str(verification.get("task_id") or "").strip()
        node_id = str(verification.get("node_id") or "").strip()
        engine = str(verification.get("engine") or "").strip().lower()
        verified_at = str(verification.get("verified_at") or "").strip()
        model_sha = str(verification.get("model_sha256") or "").strip().lower()
        try:
            generation = int(verification.get("execution_generation") or 0)
            model_size = int(verification.get("model_size_bytes") or 0)
            inference_ms = float(verification.get("inference_ms"))
            output_count = int(verification.get("output_count"))
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=409, detail="当前板端验收记录的数值证据无效") from error
        input_evidence = verification.get("input")
        if not isinstance(input_evidence, Mapping):
            raise HTTPException(status_code=409, detail="当前板端验收记录缺少测试图 evidence")
        input_sha = str(input_evidence.get("sha256") or "").strip().lower()
        try:
            input_size = int(input_evidence.get("size_bytes") or 0)
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=409, detail="当前板端验收记录的测试图 size 无效") from error
        if (
            chip != str(context["chip"])
            or not task_id
            or generation <= 0
            or not node_id
            or engine != "rknn-lite2"
            or not verified_at
            or model_sha != str(context["model_sha256"])
            or model_size != int(context["model_size_bytes"])
            or not re.fullmatch(r"[0-9a-f]{64}", input_sha)
            or input_size <= 0
            or inference_ms < 0
            or output_count <= 0
        ):
            raise HTTPException(status_code=409, detail="当前板端验收记录不满足完整留证要求")
        if isinstance(job_verification, Mapping):
            if (
                str(job_verification.get("task_id") or "") != task_id
                or str(job_verification.get("node_id") or "") != node_id
                or str(job_verification.get("chip") or "").strip().lower() != chip
            ):
                raise HTTPException(status_code=409, detail="job.json 与 manifest 的板端验收 evidence 不一致")
        target = manifest.get("target") if isinstance(manifest, Mapping) else {}
        return {
            "ok": True,
            "report_version": 1,
            "status": "passed",
            "acceptance_scope": "rknn_runtime_hardware",
            "project_id": str(project_id),
            "conversion_job_id": str(job_id),
            "model": {
                "file_name": context["model_name"],
                "size_bytes": context["model_size_bytes"],
                "sha256": context["model_sha256"],
            },
            "target": {
                "chip": chip,
                "precision": str((target or {}).get("precision") or ""),
            },
            "board": {
                "node_id": node_id,
                "rknn_lite_version": str(verification.get("rknn_lite_version") or ""),
            },
            "verification": {
                "task_id": task_id,
                "execution_generation": generation,
                "verified_at": verified_at,
                "engine": engine,
                "input": {
                    "file_name": Path(str(input_evidence.get("file_name") or "input")).name,
                    "size_bytes": input_size,
                    "sha256": input_sha,
                },
                "inference_ms": inference_ms,
                "output_count": output_count,
                "output_shapes": list(verification.get("output_shapes") or []),
            },
            "accuracy_verified": False,
            # Read-only delivery quality projection for the same conversion job. The
            # RKNN runtime report only proves hardware execution; formal activation
            # still requires bound numeric evidence and is never inferred here.
            "hardware_acceptance": "VERIFIED",
            "device_calls_verified": True,
            "delivery_quality": self._conversion_delivery_quality_projection(project_id, job),
            "statement": "本报告仅证明该 RKNN 产物已在匹配 Rockchip 板卡上完成 RKNNLite Runtime 推理验证，不代表算法准确率或业务效果验收。",
        }

    def v39_rknn_hardware_acceptance_report(self,
        project_id: str,
        job_id: str,
        download: bool = Query(False),
    ):
        report = self._rknn_hardware_acceptance_report(project_id, job_id)
        headers = {}
        if download:
            safe_job = re.sub(r"[^A-Za-z0-9._-]+", "-", str(job_id)).strip("-") or "rknn"
            headers["Content-Disposition"] = f'attachment; filename="rknn-hardware-acceptance-{safe_job}.json"'
        return JSONResponse(content=report, headers=headers)

    async def v39_create_rknn_hardware_test(self,
        project_id: str,
        job_id: str,
        file: UploadFile = File(...),
        *,
        request_id: str = "",
        model_sha256: str = "",
        input_sha256: str = "",
    ):
        if request_id or model_sha256 or input_sha256:
            task_id = self._rknn_hardware_request_task_id(project_id, job_id, request_id)
            image = await file.read()
            if not image:
                raise HTTPException(400, detail="板端验证图片为空")
            if (not re.fullmatch(r"[a-f0-9]{64}", model_sha256)
                    or hashlib.sha256(image).hexdigest() != input_sha256):
                raise HTTPException(409, detail="模型或测试图 SHA256 不匹配")
            return await asyncio.to_thread(self._create_rknn_hardware_request,
                project_id, job_id, task_id, request_id, model_sha256, input_sha256, image, file.filename)
        context = self._rknn_hardware_validation_context(project_id, job_id)
        algorithm_id, version_id = self.dependencies._deploy_job_version_identity(context["job"])
        with self.dependencies._algorithm_version_reference_fence(
            project_id, algorithm_id, version_id,
        ):
            return await self._v39_create_rknn_hardware_test_under_version_fence(
                project_id, job_id, file,
            )

    @staticmethod
    def _rknn_hardware_request_task_id(project_id, job_id, request_id):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{16,80}", request_id):
            raise HTTPException(422, detail="板端验证请求编号无效")
        identity = json.dumps(["rknn-hardware", project_id, job_id, request_id])
        return hashlib.sha256(identity.encode()).hexdigest()[:32]

    def _rknn_hardware_receipt(self, record, frozen, *, status_code=200):
        return JSONResponse(status_code=status_code, content={
            **self.dependencies.public_deployment_test(record),
            "board_nodes": frozen["board_nodes"],
            "source_conversion_job_id": frozen["source_conversion_job_id"],
            "chip": frozen["chip"], "request_id": frozen["request_id"],
            "model_sha256": frozen["model_sha256"], "input_sha256": frozen["input_sha256"],
        })

    def _load_rknn_hardware_request(self, project_id, job_id, request_id):
        self.dependencies.get_project(project_id)
        task_id = self._rknn_hardware_request_task_id(project_id, job_id, request_id)
        record = self.dependencies.shared_task_repository().get(task_id)
        if record is None or record.project_id != project_id or record.kind is not TaskKind.DEPLOYMENT_TEST:
            raise HTTPException(404, detail="板端验证请求尚未登记")
        payload = self.dependencies.shared_task_artifacts().read_json(task_id, record.payload_ref, default={})
        frozen = payload.get("hardware_request") or {}
        if frozen.get("request_id") != request_id or frozen.get("source_conversion_job_id") != job_id:
            raise HTTPException(404, detail="板端验证请求身份不匹配")
        return record, frozen

    def v39_rknn_hardware_test_receipt(self, project_id, job_id, request_id):
        record, frozen = self._load_rknn_hardware_request(project_id, job_id, request_id)
        return self._rknn_hardware_receipt(record, frozen)

    def v39_retry_unstarted_rknn_hardware_test(self, project_id, job_id, request_id):
        from platform_core.deployment.scenario_preparation import creation_lock
        record, frozen = self._load_rknn_hardware_request(project_id, job_id, request_id)
        repository, artifacts = self.dependencies.shared_task_repository(), self.dependencies.shared_task_artifacts()
        identity = (frozen["algorithm_id"], frozen["version_id"])
        with self.dependencies._algorithm_version_reference_fence(project_id, *identity):
            with creation_lock(artifacts, record.task_id):
                record, frozen = self._load_rknn_hardware_request(project_id, job_id, request_id)
                if record.status is TaskStatus.QUEUED and record.retry_of == record.task_id and not record.attempt:
                    return self._rknn_hardware_receipt(record, frozen, status_code=202)
                if (record.status not in {TaskStatus.CANCELLED, TaskStatus.FAILED} or record.attempt
                        or record.worker_id or record.lease_expires_at or any(value is not None for value in (
                            record.process_pid, record.process_create_time, record.process_command_hash,
                        ))):
                    raise HTTPException(409, detail="原板端执行已领取或停止证据不足，不能恢复")
                context = self._rknn_hardware_validation_context(project_id, job_id)
                if (self.dependencies._deploy_job_version_identity(context["job"]) != identity
                        or context["model_sha256"] != frozen["model_sha256"] or context["chip"] != frozen["chip"]
                        or context["hardware_verified"] or not context["board_nodes"]
                        or self._rknn_input_size(context["job"]) != frozen["input_size"]
                        or str(context["manifest"]["target"].get("precision") or "") != frozen["precision"]):
                    raise HTTPException(409, detail="原验证模型、目标或板端条件已变化")
                record = repository.retry(record.task_id)
                return self._rknn_hardware_receipt(record, frozen, status_code=202)

    def _create_rknn_hardware_request(self, project_id, job_id, task_id, request_id, model_sha, input_sha, image, filename):
        self.dependencies.get_project(project_id)
        repository = self.dependencies.shared_task_repository()
        artifacts = self.dependencies.shared_task_artifacts()
        lock = artifacts.artifact_path(task_id, "hardware-request.lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(lock), timeout=60):
            record = repository.get(task_id)
            prior = artifacts.read_json(task_id, "request.json", default={})
            intent = artifacts.read_json(task_id, "hardware-intent.json", default={})
            frozen = prior.get("hardware_request") or intent
            extension = self._rknn_input_extension(filename)
            if frozen and any(frozen.get(key) != value for key, value in {
                "request_id": request_id, "source_conversion_job_id": job_id,
                "model_sha256": model_sha, "input_sha256": input_sha, "input_extension": extension,
            }.items()):
                raise HTTPException(409, detail="板端验证原请求内容已变化")
            if record is not None:
                if (not prior.get("hardware_request") or record.project_id != project_id
                        or record.kind is not TaskKind.DEPLOYMENT_TEST):
                    raise HTTPException(409, detail="板端验证任务编号已被占用")
                return self._rknn_hardware_receipt(record, frozen, status_code=202)
            context = self._rknn_hardware_validation_context(project_id, job_id)
            algorithm, version = self.dependencies._deploy_job_version_identity(context["job"])
            if not algorithm or not version or context["model_sha256"] != model_sha:
                raise HTTPException(409, detail="缺少可核验的算法版本或转换产物已变化")
            def validated_context(expected):
                current = self._rknn_hardware_validation_context(project_id, job_id)
                current_identity = dict(request_id=request_id, source_conversion_job_id=job_id,
                    algorithm_id=algorithm, version_id=version, model_sha256=model_sha, input_sha256=input_sha,
                    chip=current["chip"], board_nodes=current["board_nodes"],
                    input_size=self._rknn_input_size(current["job"]),
                    input_extension=extension,
                    precision=str(current["manifest"]["target"].get("precision") or ""))
                if (current["model_sha256"] != model_sha
                        or self.dependencies._deploy_job_version_identity(current["job"]) != (algorithm, version)
                        or expected and {k: v for k, v in expected.items() if k != "board_nodes"} !=
                                      {k: v for k, v in current_identity.items() if k != "board_nodes"}):
                    raise HTTPException(409, detail="板端验证冻结的转换模型或参数已变化")
                if current["hardware_verified"]:
                    raise HTTPException(409, detail="该 RKNN 产物已完成板端 Runtime 验证")
                return current, current_identity

            with self.dependencies._algorithm_version_reference_fence(project_id, algorithm, version):
                context, current_identity = validated_context(frozen)
                frozen = frozen or current_identity
                if not intent:
                    artifacts.atomic_write_json(task_id, "hardware-intent.json", frozen)
            if not prior:
                self._create_rknn_hardware_test(project_id, job_id, context, image, filename,
                                                task_id=task_id, hardware_request=frozen, publish=False)
            with self.dependencies._algorithm_version_reference_fence(project_id, algorithm, version):
                validated_context(frozen)
                record = self._publish_rknn_hardware_task(project_id, task_id, frozen["chip"])
                return self._rknn_hardware_receipt(record, frozen, status_code=202)

    async def _v39_create_rknn_hardware_test_under_version_fence(self,
        project_id: str,
        job_id: str,
        file: UploadFile,
    ):
        context = self._rknn_hardware_validation_context(project_id, job_id)
        return self._create_rknn_hardware_test(project_id, job_id, context, await file.read(), file.filename)

    @staticmethod
    def _rknn_input_size(job):
        params = job.get("params")
        try:
            return int((params if isinstance(params, Mapping) else {}).get("input_size") or 640)
        except (TypeError, ValueError):
            return 640

    def _rknn_input_extension(self, filename):
        extension = Path(filename or "test.jpg").suffix.lower()
        return extension if extension in self.dependencies.IMAGE_EXTS() else ".jpg"

    def _create_rknn_hardware_test(self, project_id, job_id, context, image, filename, *,
                                   task_id=None, hardware_request=None, publish=True):
        chip = str(context["chip"])
        model_path = context["model_path"]
        if context["hardware_verified"]:
            raise HTTPException(status_code=409, detail="该 RKNN 产物已完成板端 Runtime 验证")

        nodes = list(context["board_nodes"])
        if not nodes:
            raise PlatformError(
                code="RKNN_BOARD_NODE_UNAVAILABLE",
                message="没有可用的瑞芯微板端验证节点",
                detail=f"需要在线、已授权 deployment-test.rknn 且真实识别为 {chip.upper()} 的 RKNNLite Agent",
                solution="请在对应 RK3568/RK3576 设备部署 Node Agent，并安装可用的 RKNN-Toolkit-Lite2 后重试。",
                status_code=409,
            )

        extension = self._rknn_input_extension(filename)
        task_id = task_id or uuid.uuid4().hex[:12]
        prediction_dir = self.dependencies.project_dir(project_id) / "predictions" / task_id
        prediction_dir.mkdir(parents=True, exist_ok=True)
        input_path = prediction_dir / f"input{extension}"
        input_path.write_bytes(image)
        if input_path.stat().st_size <= 0:
            input_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="板端验证图片为空")

        input_size = self._rknn_input_size(context["job"])
        try:
            remote_execution = self.dependencies._remote_execution_transport_service().stage_rknn_board_validation(
                project_id=project_id,
                task_id=task_id,
                conversion_job_id=job_id,
                model_path=model_path,
                input_path=input_path,
                chip=chip,
                input_size=input_size,
            )
        except RemoteExecutionTransportError as error:
            input_path.unlink(missing_ok=True)
            try:
                prediction_dir.rmdir()
            except OSError:
                pass
            raise PlatformError(
                code=error.code,
                message="RKNN 板端验证准备失败",
                detail=str(error),
                solution="请检查对象存储、RKNN 产物完整性和板端节点状态后重试。",
                status_code=error.status_code,
            ) from error

        request = {
            "execution_mode": "agent",
            "framework": "rknn",
            "runtime_format": "rknn",
            "source_conversion_job_id": job_id,
            "chip": chip,
            "input_size": input_size,
            "model_path": str(model_path),
            "input_path": str(input_path),
            "image_url": self.dependencies._business_file_url(project_id, 'predictions', f'{task_id}/result.jpg'),
            "remote_execution": remote_execution,
        }
        if hardware_request:
            request["hardware_request"] = hardware_request
        self.dependencies.shared_task_artifacts().atomic_write_json(task_id, "request.json", request)
        if not publish:
            return None
        record = self._publish_rknn_hardware_task(project_id, task_id, chip)
        return JSONResponse(status_code=202, content={
            **self.dependencies.public_deployment_test(record),
            "board_nodes": nodes,
            "source_conversion_job_id": job_id,
            "chip": chip,
        })

    def _publish_rknn_hardware_task(self, project_id, task_id, chip):
        return self.dependencies.shared_task_repository().create(TaskRecord.new(
            task_id, project_id, TaskKind.DEPLOYMENT_TEST, "request.json",
            f"deployment-rknn-board:{chip}", required_capabilities=("agent.remote",),
        ))

    def _conversion_history_csc(self, job):
        params=job.get('params') or {}
        csc=params.get('csc') or {}
        return str(csc.get('preset') or 'legacy_unknown') if isinstance(csc,dict) else 'legacy_unknown'

    def _conversion_history_page(self, project_id, **query):
        try:
            if query.get('csc')=='unknown': query['csc']='legacy_unknown'
            return self.dependencies._CONVERSION_HISTORY_PROJECTION().query(self.dependencies.deploy_root(project_id)/'jobs',
                read_json=self.dependencies.read_json,overlay=self._overlay_durable_deploy_job,csc_value=self._conversion_history_csc,**query)
        except ValueError as error:
            raise HTTPException(422,detail=str(error)) from error

    def v39_list_deploy_jobs(self, project_id: str):
        # Preserve the generic legacy response; version views use their scoped projection.
        root=self.dependencies.deploy_root(project_id)/'jobs';rows=[]
        for jf in root.glob('*/job.json'):
            job=self._overlay_durable_deploy_job(self.dependencies.read_json(jf,{}))
            if job:rows.append(job)
        rows.sort(key=lambda row:row.get('created_at',''),reverse=True)
        return {'ok':True,'items':rows[:100]}

    def _delivery_model_artifact_service(self, ) -> ModelArtifactService:
        """Read-only ModelArtifact owner used by delivery quality projections."""
        return ModelArtifactService(
            data_dir=self.dependencies.DATA_DIR(),
            project_dir=self.dependencies.project_dir,
            algorithms_file=self.dependencies.algorithms_file,
            storage_sources_factory=self.dependencies.storage_source_repository,
            storage_credentials_factory=self.dependencies.storage_credentials,
        )

    def _model_artifact_quality_row(self, row: Mapping[str, Any]) -> Dict[str, Any]:
        """One fail-closed read-only quality row (never raises, never writes)."""
        try:
            quality = delivery_artifact_quality_preflight(self.dependencies.DATA_DIR(), row)
        except Exception as error:  # noqa: BLE001 - projection degrades readably
            quality = {
                "schema": "delivery-quality-preflight-v1",
                "target": str(row.get("target") or ""),
                "formal_activation_eligible": False,
                "present_as_formal_activation": False,
                "delivery_presentation": "UNVERIFIED_ATTACHMENT",
                "hardware_acceptance": "NOT_VERIFIED",
                "present_as_hardware_accepted": False,
                "attachment_delivery_allowed": False,
                "numeric_status_alone_is_sufficient": False,
                "code": "ELIGIBILITY_CHECK_FAILED",
                "reasons": [f"{type(error).__name__}: {error}"[:300]],
            }
        return {
            "artifact_id": str(row.get("artifact_id") or ""),
            "target": str(row.get("target") or ""),
            "file_name": str(row.get("file_name") or ""),
            "sha256": str(row.get("sha256") or ""),
            "quality_preflight": quality,
            "formal_activation_eligible": bool(quality.get("formal_activation_eligible")),
            "present_as_formal_activation": bool(quality.get("present_as_formal_activation")),
            "delivery_presentation": str(quality.get("delivery_presentation") or "UNVERIFIED_ATTACHMENT"),
            "hardware_acceptance": str(quality.get("hardware_acceptance") or "NOT_VERIFIED"),
            "present_as_hardware_accepted": bool(quality.get("present_as_hardware_accepted")),
            "attachment_delivery_allowed": bool(quality.get("attachment_delivery_allowed")),
            "numeric_status_alone_is_sufficient": False,
            "code": str(quality.get("code") or ""),
            "reasons": list(quality.get("reasons") or []),
        }

    def _version_delivery_quality(self,
        project_id: str, algorithm_id: str, version_id: str,
    ) -> Dict[str, Any]:
        """Opt-in, read-only delivery quality for one algorithm version.

    Uses the same ModelArtifact discovery as the delivery/publish path, so a
    legal but unverified conversion remains an attachment while only really
    eligible evidence can present as formal activation. No device/external
    platform call and no write.
    """
        service = self._delivery_model_artifact_service()
        reasons: List[str] = []
        rows: List[Mapping[str, Any]] = []
        try:
            algorithm, version = service._current_version(project_id, algorithm_id, version_id)
            if algorithm is None:
                reasons.append("ALGORITHM_NOT_FOUND")
            elif version is None:
                reasons.append("ALGORITHM_VERSION_NOT_FOUND")
            else:
                rows = service.discover_version_artifacts(project_id, algorithm, version)
        except Exception as error:  # noqa: BLE001 - read projection never breaks
            reasons.append(f"ARTIFACT_DISCOVERY_FAILED: {type(error).__name__}"[:300])
        artifacts = [self._model_artifact_quality_row(row) for row in rows]
        formal = [row for row in artifacts if row["formal_activation_eligible"]]
        attachments = [
            row for row in artifacts
            if row["attachment_delivery_allowed"] and not row["formal_activation_eligible"]
        ]
        if not artifacts:
            reasons.append("NO_DELIVERABLE_ARTIFACTS")
        formal_activation_eligible = bool(artifacts) and len(formal) == len(artifacts)
        return {
            "schema": "version-delivery-quality-v1",
            "project_id": str(project_id),
            "algorithm_id": str(algorithm_id),
            "version_id": str(version_id),
            "dry_run": False,
            "device_calls": False,
            "external_platform_calls": False,
            "numeric_status_alone_is_sufficient": False,
            "formal_activation_eligible": formal_activation_eligible,
            "present_as_formal_activation": formal_activation_eligible,
            "delivery_presentation": "FORMAL_ACTIVATION" if formal_activation_eligible else "UNVERIFIED_ATTACHMENT",
            "hardware_acceptance": "NOT_VERIFIED",
            "present_as_hardware_accepted": False,
            "attachment_delivery_allowed": bool(attachments),
            "artifacts": artifacts,
            "reasons": list(dict.fromkeys(reasons)),
        }

    def _conversion_delivery_quality_projection(self,
        project_id: str, job: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Read-only conversion/delivery quality projection for one conversion job.

    Reuses ``delivery_artifact_quality_preflight`` (and therefore
    ``assert_delivery_quality_eligibility``) on the registered ModelArtifact
    rows. Raw job outputs remain downloadable/archivable but are never
    presented as formal activation or hardware acceptance. Never writes, never
    calls a device or an external platform; failures degrade to readable
    reasons instead of a 500.
    """
        job = job if isinstance(job, Mapping) else {}
        job_id = str(job.get("id") or "")
        artifacts: List[Dict[str, Any]] = []
        reasons: List[str] = []
        try:
            rows = (
                self._delivery_model_artifact_service().repository.list_by_conversion_job(
                    project_id, job_id,
                ) if job_id else []
            )
        except Exception as error:  # noqa: BLE001 - projection must never break reads
            rows = []
            reasons.append(f"MODEL_ARTIFACT_READ_FAILED: {type(error).__name__}"[:300])
        for row in rows:
            artifacts.append(self._model_artifact_quality_row(row))
        raw_outputs: List[Dict[str, Any]] = []
        job_root = self._deploy_job_dir(project_id, job_id) if job_id else None
        for output in job.get("outputs") or []:
            if not isinstance(output, Mapping) or not output.get("rel"):
                continue
            raw_path = Path(str(output.get("path") or ""))
            available = bool(raw_path.is_file())
            if not available and job_root is not None:
                try:
                    available = self.dependencies._resolve_business_file(
                        project_id, "deployment", f"jobs/{job_id}/{output.get('rel')}",
                    ).path.is_file()
                except Exception:  # noqa: BLE001 - archive availability is evidence only
                    available = False
            raw_outputs.append({
                "name": str(output.get("name") or ""),
                "rel": str(output.get("rel") or ""),
                "sha256": str(output.get("sha256") or ""),
                "archive_download_allowed": available,
                "delivery_presentation": "ARCHIVE_DOWNLOAD_ONLY" if available else "UNAVAILABLE",
                "formal_activation_eligible": False,
                "present_as_formal_activation": False,
                "hardware_acceptance": "NOT_VERIFIED",
            })
        formal = [row for row in artifacts if row["formal_activation_eligible"]]
        attachments = [row for row in artifacts if row["attachment_delivery_allowed"] and not row["formal_activation_eligible"]]
        if not artifacts:
            reasons.append("MODEL_ARTIFACT_NOT_REGISTERED")
        formal_activation_eligible = bool(artifacts) and len(formal) == len(artifacts)
        return {
            "schema": "conversion-delivery-quality-v1",
            "conversion_job_id": job_id,
            "project_id": str(project_id),
            "dry_run": False,
            "device_calls": False,
            "external_platform_calls": False,
            "numeric_status_alone_is_sufficient": False,
            "hardware_verified": job.get("hardware_verified") is True,
            "hardware_acceptance": "VERIFIED" if job.get("hardware_verified") is True else "NOT_VERIFIED",
            "present_as_hardware_accepted": job.get("hardware_verified") is True,
            "archive_download_allowed": any(row["archive_download_allowed"] for row in raw_outputs),
            "attachment_delivery_allowed": bool(attachments),
            "formal_activation_eligible": formal_activation_eligible,
            "present_as_formal_activation": formal_activation_eligible,
            "delivery_presentation": "FORMAL_ACTIVATION" if formal_activation_eligible else "UNVERIFIED_ATTACHMENT",
            "artifacts": artifacts,
            "unregistered_outputs": raw_outputs,
            "reasons": list(dict.fromkeys(reasons)),
        }

    def v39_get_deploy_job(self, project_id: str, job_id: str):
        job = self._read_deploy_job(project_id,job_id)
        return {**job, "delivery_quality": self._conversion_delivery_quality_projection(project_id, job)}

    def _numeric_conversion_dir(self, project_id: str, verification_id: str) -> Path:
        if not re.fullmatch(r"nv_[a-f0-9]{24}", str(verification_id or "")):
            raise HTTPException(status_code=422, detail="数值验证 ID 不合法")
        return self.dependencies.deploy_root(project_id) / "numeric-validations" / verification_id

    def _numeric_frozen_imgsz(self, params: dict) -> list:
        """Only an explicitly frozen conversion size may drive numeric comparison."""
        params = params if isinstance(params, dict) else {}
        if not any(key in params for key in ("input_size", "input_height", "input_width")):
            return []
        try:
            from platform_core.conversion import conversion_input_shape
            height, width = conversion_input_shape(params)
        except (TypeError, ValueError):
            return []
        return [height, width]

    def _numeric_conversion_artifact(self, job_dir: Path, manifest: dict, suffix: str, *, required: bool) -> tuple[Path | None, str]:
        """Resolve a unique frozen output, never the alphabetically first artifact."""
        root = (job_dir / "artifacts").resolve()
        records = manifest.get("outputs") if isinstance(manifest.get("outputs"), list) else []
        recorded = [row for row in records if isinstance(row, dict)
                    and str(row.get("name") or "").lower().endswith(suffix)]
        if records:
            if len(recorded) != 1:
                if not required and not recorded:
                    return None, "not_applicable"
                raise HTTPException(status_code=409, detail=f"转换 manifest 中 {suffix} 产物身份不唯一或缺失")
            row = recorded[0]
            relative = Path(str(row["name"]))
            if relative.is_absolute() or ".." in relative.parts:
                raise HTTPException(status_code=409, detail="转换 manifest 包含越界产物路径")
            path = (root / relative).resolve()
        else:
            candidates = sorted(root.glob(f"*{suffix}"))
            if not candidates and not required:
                return None, "not_applicable"
            if len(candidates) != 1:
                raise HTTPException(status_code=409, detail=f"无法唯一确认历史 {suffix} 转换产物")
            path = candidates[0].resolve()
            row = {}
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size <= 0:
            raise HTTPException(status_code=409, detail=f"{suffix} 产物缺失、为空或越过冻结目录")
        expected_sha = str(row.get("sha256") or "")
        if expected_sha and expected_sha != sha256_file(path):
            raise HTTPException(status_code=409, detail=f"{suffix} 产物 SHA256 与转换 manifest 不一致")
        expected_size = row.get("size_bytes")
        if expected_size is not None and (type(expected_size) is not int or expected_size != path.stat().st_size):
            raise HTTPException(status_code=409, detail=f"{suffix} 产物大小与转换 manifest 不一致")
        return path, "verified" if expected_sha else "unverified"

    def _numeric_conversion_public(self, project_id: str, verification_id: str) -> dict:
        directory = self._numeric_conversion_dir(project_id, verification_id)
        receipt = self.dependencies.read_json(directory / "request.json", {})
        if receipt.get("project_id") != project_id:
            raise HTTPException(status_code=404, detail="数值验证记录不存在")
        task = self.dependencies.shared_task_repository().get(verification_id)
        if task is None or task.kind is not TaskKind.MODEL_CONVERSION or task.project_id != project_id:
            raise HTTPException(status_code=404, detail="数值验证任务不存在")
        result = self.dependencies.read_json(directory / "result.json", {})
        return {"id": verification_id, "conversion_job_id": receipt["conversion_job_id"],
                "created_at": receipt.get("created_at"), "task": task_to_public(task, self.dependencies.shared_task_repository()),
                "result": result if result else None}

    def v39_list_numeric_validations(self, project_id: str, job_id: str):
        self._read_deploy_job(project_id, job_id)
        root = self.dependencies.deploy_root(project_id) / "numeric-validations"
        rows = []
        for directory in sorted(root.glob("nv_*/request.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:300] if root.exists() else []:
            receipt = self.dependencies.read_json(directory, {})
            if receipt.get("project_id") == project_id and receipt.get("conversion_job_id") == job_id:
                try:
                    rows.append(self._numeric_conversion_public(project_id, directory.parent.name))
                except HTTPException:
                    continue
            if len(rows) >= 20:
                break
        return {"ok": True, "items": rows}

    def v39_get_numeric_validation(self, project_id: str, job_id: str, verification_id: str):
        self._read_deploy_job(project_id, job_id)
        result = self._numeric_conversion_public(project_id, verification_id)
        if result["conversion_job_id"] != job_id:
            raise HTTPException(status_code=404, detail="数值验证任务不属于当前转换")
        return {"ok": True, **result}

    @staticmethod
    def _numeric_verification_id(project_id: str, job_id: str, request_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{12,80}", request_id):
            raise HTTPException(status_code=422, detail="数值验证请求 ID 不合法")
        return "nv_" + hashlib.sha256(f"{project_id}:{job_id}:{request_id}".encode()).hexdigest()[:24]

    def v39_find_numeric_validation(self, project_id: str, job_id: str, request_id: str):
        verification_id = self._numeric_verification_id(project_id, job_id, request_id)
        result = self.v39_get_numeric_validation(project_id, job_id, verification_id)
        receipt = self.dependencies.read_json(self._numeric_conversion_dir(project_id, verification_id) / "request.json", {})
        if receipt.get("request_id") != request_id:
            raise HTTPException(status_code=404, detail="数值验证请求不存在")
        return result

    def v39_create_numeric_validation(self,
        project_id: str, job_id: str, files: List[UploadFile] = File(...),
        request_id: str = Form(""),
        confidence: float = Form(0.25), nms_iou: float = Form(0.7),
        *, sample_sha256: str = "",
    ):
        """Freeze real samples and enqueue PT-vs-ONNX only; never assert BMODEL pass."""
        # Direct in-process callers (including legacy tests) receive the FastAPI
        # Form parameter descriptor rather than an HTTP-decoded default value.
        confidence = float(confidence) if isinstance(confidence, (int, float)) else 0.25
        nms_iou = float(nms_iou) if isinstance(nms_iou, (int, float)) else 0.7
        job = self._read_deploy_job(project_id, job_id)
        if str(job.get("status") or "").lower() not in {"done", "blocked_by_hardware"}:
            raise HTTPException(status_code=409, detail="转换产物尚未完成，无法进行数值比较")
        if not 1 <= len(files) <= 12:
            raise HTTPException(status_code=422, detail="每批请选择 1～12 张真实图片")
        expected_samples = sample_sha256.split(",") if sample_sha256 else []
        if expected_samples and (not request_id or len(expected_samples) != len(files)
                or any(not re.fullmatch(r"[0-9a-f]{64}", digest) for digest in expected_samples)):
            raise HTTPException(422, detail="验证样本摘要与请求身份不一致")
        if (not math.isfinite(confidence) or not 0 < confidence < 1
                or not math.isfinite(nms_iou) or not 0 < nms_iou < 1):
            raise HTTPException(status_code=422, detail="验证置信度和 NMS IoU 必须在 0 与 1 之间")
        job_dir = self._deploy_job_dir(project_id, job_id).resolve()
        source_path = Path(str(job.get("source_path") or "")).resolve()
        manifest = self.dependencies.read_json(job_dir / "artifacts" / "manifest.json", {})
        onnx_path, onnx_identity = self._numeric_conversion_artifact(job_dir, manifest, ".onnx", required=True)
        bmodel_path, bmodel_identity = self._numeric_conversion_artifact(job_dir, manifest, ".bmodel", required=False)
        if not source_path.is_file() or source_path.suffix.lower() not in {".pt", ".pth"}:
            raise HTTPException(status_code=422, detail="源版本不是可用 PT，暂无法进行 PT／ONNX 比较")
        if not source_path.is_relative_to(job_dir):
            raise HTTPException(status_code=409, detail="源模型不在本次转换的冻结目录中")
        source_sha = str((job.get("source_trace") or {}).get("sha256") or "")
        if source_sha and source_sha != sha256_file(source_path):
            raise HTTPException(status_code=409, detail="冻结 PT 源权重 SHA256 不一致")
        verification_id = (self._numeric_verification_id(project_id, job_id, request_id)
                           if request_id else "nv_" + uuid.uuid4().hex[:24])
        directory = self._numeric_conversion_dir(project_id, verification_id)
        created_directory = False
        (self.dependencies.deploy_root(project_id) / "numeric-validations").mkdir(parents=True, exist_ok=True)
        lock_root = self.dependencies.DATA_DIR() / "task_runtime" / "conversion_create_locks"
        lock_root.mkdir(parents=True, exist_ok=True)
        try:
            with FileLock(str(lock_root / f"{verification_id}.lock"), timeout=30):
                if (directory / "request.json").is_file():
                    receipt = self.dependencies.read_json(directory / "request.json", {})
                    if receipt.get("project_id") != project_id or receipt.get("conversion_job_id") != job_id or receipt.get("request_id") != request_id:
                        raise HTTPException(status_code=409, detail="相同验证请求标识已有不同任务")
                    if float(receipt.get("confidence", 0.25)) != confidence or float(receipt.get("nms_iou", 0.7)) != nms_iou:
                        raise HTTPException(status_code=409, detail="相同请求 ID 的验证阈值不同，请发起新验证")
                    if (receipt.get("sample_sha256") or []) != expected_samples:
                        raise HTTPException(409, detail="原验证样本摘要不一致")
                    if expected_samples:
                        total = 0
                        for file, expected in zip(files, expected_samples):
                            hasher = hashlib.sha256()
                            size = 0
                            while chunk := file.file.read(1024 * 1024):
                                size += len(chunk)
                                total += len(chunk)
                                if size > 10 * 1024 * 1024 or total > 60 * 1024 * 1024:
                                    raise HTTPException(413, detail="单图不能超过 10 MB，整批不能超过 60 MB")
                                hasher.update(chunk)
                            if hasher.hexdigest() != expected:
                                raise HTTPException(409, detail="重选的验证样本与原请求不一致")
                    return {"ok": True, "idempotent": True, **self._numeric_conversion_public(project_id, verification_id)}
                if directory.exists():
                    raise HTTPException(status_code=409, detail="验证任务准备状态未知，请核对原请求")
                images_dir = directory / "images"
                images_dir.mkdir(parents=True, exist_ok=False)
                created_directory = True
                names = []
                total = 0
                for index, file in enumerate(files):
                    suffix = Path(file.filename or "").suffix.lower()
                    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
                        raise HTTPException(status_code=422, detail=f"第 {index+1} 张不是允许的图片格式")
                    name = f"image_{index+1:02d}{suffix}"
                    size = 0
                    hasher = hashlib.sha256() if expected_samples else None
                    with (images_dir / name).open("wb") as output:
                        while True:
                            chunk = file.file.read(1024 * 1024)
                            if not chunk:
                                break
                            size += len(chunk)
                            total += len(chunk)
                            if size > 10 * 1024 * 1024 or total > 60 * 1024 * 1024:
                                raise HTTPException(status_code=413, detail="单图不能超过 10 MB，整批不能超过 60 MB")
                            output.write(chunk)
                            if hasher is not None:
                                hasher.update(chunk)
                    if hasher is not None and hasher.hexdigest() != expected_samples[index]:
                        raise HTTPException(409, detail="上传的验证样本与已确认摘要不一致")
                    from PIL import Image
                    try:
                        with Image.open(images_dir / name) as picture:
                            if picture.width * picture.height > 24_000_000:
                                raise ValueError("图片像素超过 2400 万")
                            picture.verify()
                    except Exception as error:
                        raise HTTPException(status_code=422, detail=f"第 {index+1} 张图片无法解码：{error}") from error
                    names.append(name)
                onnx_evidence = manifest.get("onnx") if isinstance(manifest.get("onnx"), dict) else {}
                source_evidence = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
                frozen_preprocessing = source_evidence.get("preprocessing_contract") if isinstance(source_evidence.get("preprocessing_contract"), dict) else {}
                request_preprocessing = (job.get("params") or {}).get("preprocessing") if isinstance((job.get("params") or {}).get("preprocessing"), Mapping) else {}
                for field in ("pixel_format", "channel_format", "letterbox", "letterbox_mode",
                              "pad_value", "resize_interpolation", "mean", "scale"):
                    if (field in frozen_preprocessing and field in request_preprocessing
                            and frozen_preprocessing.get(field) != request_preprocessing.get(field)):
                        raise HTTPException(
                            status_code=409,
                            detail=f"验证请求的预处理字段 {field} 与转换 manifest 冻结合同冲突",
                        )
                receipt = {
                    "id": verification_id, "project_id": project_id, "conversion_job_id": job_id,
                    "created_at": self.dependencies.now_iso(), "request_id": request_id,
                    **({"sample_sha256": expected_samples} if expected_samples else {}),
                    "source_path": str(source_path), "onnx_path": str(onnx_path),
                    "source_sha256": source_sha or sha256_file(source_path),
                    "onnx_sha256": str(onnx_evidence.get("sha256") or sha256_file(onnx_path)),
                    "bmodel_path": str(bmodel_path) if bmodel_path else "",
                    "bmodel_sha256": sha256_file(bmodel_path) if bmodel_path else "",
                    "bmodel_expected": str(job.get("target") or "").lower() == "sophon",
                    "artifact_identity": {"onnx": onnx_identity, "bmodel": bmodel_identity},
                    "sophon_python": str((manifest.get("tool") or {}).get("python_path") or (job.get("resource") or {}).get("python_path") or ""),
                    "precision": str((job.get("params") or {}).get("precision") or "fp32"),
                    "confidence": confidence, "nms_iou": nms_iou,
                    "input_color_order": str((job.get("params") or {}).get("input_color_order") or ((job.get("params") or {}).get("preprocessing") or {}).get("pixel_format") or "rgb"),
                    "preprocessing": dict((job.get("params") or {}).get("preprocessing") or {}),
                    # Frozen input contract: the conversion manifest's real ONNX input
                    # shapes plus the explicitly requested size (never a silent 640).
                    "input_shapes": onnx_evidence.get("input_shapes") if isinstance(onnx_evidence.get("input_shapes"), list) else [],
                    "frozen_imgsz": self._numeric_frozen_imgsz(job.get("params") or {}),
                    "frozen_batch": (int((job.get("params") or {}).get("batch"))
                                     if type((job.get("params") or {}).get("batch")) is int else None),
                    "label_codes": source_evidence.get("label_codes") if isinstance(source_evidence.get("label_codes"), list) else [],
                    "label_schema": source_evidence.get("label_schema") if isinstance(source_evidence.get("label_schema"), list) else [],
                    "label_binding": source_evidence.get("label_binding") if isinstance(source_evidence.get("label_binding"), dict) else {},
                    "preprocessing_contract": source_evidence.get("preprocessing_contract") if isinstance(source_evidence.get("preprocessing_contract"), dict) else {},
                    "output_contract": source_evidence.get("output_contract") if isinstance(source_evidence.get("output_contract"), dict) else {},
                    "image_names": names, "source_type": "PT", "compared_type": "ONNX",
                }
                self.dependencies.write_json(directory / "request.json", receipt)
                self.dependencies.shared_task_artifacts().atomic_write_json(verification_id, "request.json", {
                    "execution_mode": "numeric_verification", "conversion_job_id": job_id,
                    "verification_dir": str(directory), "worker_path": str(self.dependencies.BASE_DIR() / "conversion_numeric_verification_worker.py"),
                    "python_path": sys.executable,
                })
                self.dependencies.shared_task_repository().create(TaskRecord.new(
                    verification_id, project_id, TaskKind.MODEL_CONVERSION, "request.json",
                    "conversion:numeric-verification", required_capabilities=("conversion.runtime",),
                ))
                return {"ok": True, **self._numeric_conversion_public(project_id, verification_id)}
        except Timeout as error:
            raise HTTPException(status_code=409, detail="相同验证请求尚在受理中，请按原请求 ID 查询") from error
        except Exception:
            # A rejected upload has no durable task and must not leave dozens of
            # partially written images or poison same-request retry semantics.
            if created_directory and self.dependencies.shared_task_repository().get(verification_id) is None:
                shutil.rmtree(directory, ignore_errors=True)
            raise

    def v39_deploy_job_log(self, project_id: str, job_id: str):
        jd=self._deploy_job_dir(project_id,job_id)
        for p in [jd/"convert.log",jd/"worker.stdout.log"]:
            if p.exists():return p.read_text(encoding="utf-8",errors="ignore")[-160000:]
        return "暂无转换日志"

    def v39_stop_deploy_job(self, project_id: str, job_id: str):
        job=self._read_deploy_job(project_id,job_id);job["cancel_requested"]=True
        proc=self.dependencies.DEPLOY_PROCESS_REGISTRY().get(job_id)
        durable = self.dependencies.shared_task_repository().get(job_id)
        if durable and durable.status in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED}:
            self.dependencies.shared_task_repository().request_cancel(job_id)
        if proc and proc.poll() is None:
            try:proc.terminate();time.sleep(.5)
            except:pass
            if proc.poll() is None:
                try:proc.kill()
                except:pass
            self.dependencies.DEPLOY_PROCESS_REGISTRY().pop(job_id,None)
            job.update(status="stopped",stage="已停止",message="用户停止",updated_at=self.dependencies.now_iso())
        self._write_deploy_job(project_id,job)
        return {"ok":True}

    def v39_delete_deploy_job(self, project_id: str, job_id: str):
        job = self._read_deploy_job(project_id, job_id)
        status = str(job.get("status") or "").strip().lower()
        if status in {
            "running", "queued", "waiting_resource", "cancel_requested",
            "stopping", "waiting", "pending",
        }:
            raise HTTPException(status_code=400, detail="运行中的任务请先停止")

        model_assets = ModelArtifactService(
            data_dir=self.dependencies.DATA_DIR(),
            project_dir=self.dependencies.project_dir,
            algorithms_file=self.dependencies.algorithms_file,
            storage_sources_factory=self.dependencies.storage_source_repository,
            storage_credentials_factory=self.dependencies.storage_credentials,
        )
        artifact_refs = model_assets.conversion_job_artifact_references(project_id, job)
        if status in SUCCESSFUL_CONVERSION_STATUSES:
            raise PlatformError(
                "CONVERSION_JOB_DELIVERY_IMMUTABLE",
                "已产生成果的转换记录不能单独删除",
                (
                    f"job_id={job_id}; status={status}; "
                f"canonical_artifacts={len(artifact_refs)}"
                ),
                "转换成果属于算法版本交付链和审计记录。若需退役成果，请删除或回退对应算法版本，由版本清理 owner 统一处理 ModelArtifact、存储对象和发布映射。",
                409,
            )
        if artifact_refs:
            preview = "、".join(
                str(row.get("artifact_id") or "-") for row in artifact_refs[:10]
            )
            raise PlatformError(
                "CONVERSION_JOB_ARTIFACT_REFERENCED",
                "转换记录仍被模型资产引用",
                f"job_id={job_id}; artifact_id={preview}",
                "请保留该转换记录；若要退役交付成果，请通过算法版本删除或回退流程处理。",
                409,
            )

        job_dir = self._deploy_job_dir(project_id, job_id)
        try:
            shutil.rmtree(job_dir)
        except OSError as error:
            raise PlatformError(
                "CONVERSION_JOB_DELETE_FAILED",
                "转换记录删除失败",
                str(error),
                "请检查任务目录文件占用和权限后重试；平台不会把未确认删除的任务报告为成功。",
                409,
            ) from error
        if job_dir.exists():
            raise PlatformError(
                "CONVERSION_JOB_DELETE_FAILED",
                "转换记录删除结果无法确认",
                str(job_dir),
                "请检查任务目录权限后重试。",
                409,
            )
        return {"ok": True, "job_id": str(job_id)}

    def v39_download_deploy_package(self, project_id: str, job_id: str):
        self.dependencies._authorize_business_file_project(project_id)
        job=self._read_deploy_job(project_id,job_id);jd=self._deploy_job_dir(project_id,job_id);ad=jd/"artifacts"
        if job.get("status")!="done" or not ad.exists():raise HTTPException(status_code=400,detail="当前任务还没有可下载部署产物")
        members = []
        for output in job.get('outputs') or []:
            if not isinstance(output, dict) or not output.get('rel'):
                raise HTTPException(404, detail='文件不存在或无权访问')
            from platform_core.business_files import _ALLOWED, _parts
            if Path(str(output['rel'])).suffix.lower() not in _ALLOWED['deployment']:
                continue
            descriptor = self.dependencies._resolve_business_file(project_id, 'deployment', f"jobs/{job_id}/{output['rel']}")
            parts = _parts(str(output['rel']))
            relative = parts[1:] if parts[0] == 'artifacts' else parts
            if not relative:
                raise HTTPException(404, detail='文件不存在或无权访问')
            members.append((descriptor, Path('model').joinpath(*relative)))
        if not members or len({archive_path.as_posix() for _, archive_path in members}) != len(members):
            raise HTTPException(404, detail='文件不存在或无权访问')
        package=jd/f"deploy_{job_id}.zip"
        from platform_core.business_files import _plain
        _plain(jd, self.dependencies.DATA_DIR())
        if package.exists() or package.is_symlink():
            _plain(package, self.dependencies.DATA_DIR())
        with zipfile.ZipFile(package,"w",zipfile.ZIP_DEFLATED) as zf:
            for item, archive_path in members:
                zf.write(item.path, archive_path)
        return FileResponse(package,filename=f"{self.dependencies.safe_filename(job.get('source_name') or 'model')}_{job.get('target')}_deploy.zip",
                            headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})

    def v423_version_deployments(self, project_id: str, algorithm_id: str, version_id: str,
        page: int=1, page_size: int=100, status: str='', target: str='', chip: str='',
        precision: str='', csc: str='', created_from: str='', created_to: str='', force: bool=False, asset_view: bool=False):
        self.dependencies.get_project(project_id)
        if asset_view:
            from platform_core.model_asset_views import conversion_record, text
            from platform_core.algorithm_sql_store import AlgorithmSqlStore
            store=self.dependencies.algorithm_presentation_store(project_id)
            version=store.asset_version(algorithm_id,version_id,detail=False)
            history=self._conversion_history_page(project_id,algorithm_id=algorithm_id,version_id=version_id,page=page,page_size=page_size,status=status,target=target,chip=chip,precision=precision,csc=csc,created_from=created_from,created_to=created_to,force=force,include_facets=True)
            rows=[conversion_record(job,self.dependencies.deploy_root(project_id)) for job in history['items']]
            for row in rows:row['target_name']=self.dependencies.V423_DEPLOY_TARGET_NAMES().get(row.get('target'),row.get('target'))
            history['filter_options']={key:[value for value in values if isinstance(value,str) and text(value)==value] for key,values in history.get('filter_options',{}).items()}
            return {'ok':True,'project_id':project_id,'algorithm_id':algorithm_id,'version_id':version_id,'version':version,**{key:value for key,value in history.items() if key not in ('items','diagnostics')},'diagnostics':[{'error':text(row.get('error'))} for row in history.get('diagnostics',[])],'items':rows}
        # Conversion history is scoped to one algorithm. Hydrating the full project
        # algorithm graph also deserializes unrelated versions and frozen evidence.
        algo = next(iter(self.dependencies.list_algorithms_internal(
            project_id, algorithm_id=algorithm_id, summary_only=True)), None)
        if not algo:
            raise HTTPException(status_code=404, detail='算法不存在')
        version = next((v for v in (algo.get('versions') or []) if v.get('id') == version_id), None)
        if not version:
            raise HTTPException(status_code=404, detail='算法版本不存在')
        history = self._conversion_history_page(project_id,algorithm_id=algorithm_id,version_id=version_id,
            page=page,page_size=page_size,status=status,target=target,chip=chip,precision=precision,csc=csc,
            created_from=created_from,created_to=created_to,force=force)
        rows = []
        for job in history['items']:
            outputs = []
            for out in job.get('outputs') or []:
                pp = Path(str(out.get('path') or ''))
                outputs.append({
                    'name': out.get('name') or pp.name, 'size_mb': out.get('size_mb'), 'rel': out.get('rel'),
                    'exists': bool(pp.exists()),
                    'download_url': f"/api/v39/projects/{project_id}/deploy/jobs/{job.get('id')}/artifact?rel={requests.utils.quote(str(out.get('rel') or ''))}" if out.get('rel') and pp.suffix.lower() not in {'.py','.md'} else ''
                })
            target = str(job.get('target') or '')
            rows.append({
                'id': job.get('id'), 'target': target, 'target_name': self.dependencies.V423_DEPLOY_TARGET_NAMES().get(target, target or '-'),
                'status': job.get('status'), 'stage': job.get('stage'), 'progress': job.get('progress'),
                'source_name': job.get('source_name') or '',
                'resource_name': (job.get('resource') or {}).get('name') or '',
                'params': job.get('params') or {}, 'requested_params':job.get('requested_params') or {},
                'execution_evidence':job.get('execution_evidence') or {},
                'source_identity':{k:(job.get('source_trace') or {}).get(k) for k in ('source_id','sha256','algorithm_id','version_id')},
                'outputs': outputs,
                'task_id': job.get('task_id') or '', 'task_status': job.get('task_status') or '',
                'durable_status': job.get('durable_status') or '', 'current_item': job.get('current_item') or '',
                'priority': job.get('priority'), 'queue_rank': job.get('queue_rank'),
                'resource_queue_position': job.get('resource_queue_position'),
                'resource_wait_reason': job.get('resource_wait_reason') or '',
                'worker_id': job.get('worker_id') or '', 'lease_expires_at': job.get('lease_expires_at') or '',
                'conversion_status': job.get('conversion_status') or '',
                'validation_status': job.get('validation_status') or '',
                'runtime_verified': bool(job.get('runtime_verified')),
                'hardware_verified': bool(job.get('hardware_verified')),
                'hardware_verification': job.get('hardware_verification') or None,
                'package_url': f"/api/v39/projects/{project_id}/deploy/jobs/{job.get('id')}/package" if job.get('status') == 'done' else '',
                'created_at': job.get('created_at'), 'finished_at': job.get('finished_at'),
                'message': job.get('message') or '', 'error': job.get('error') or ''
            })
        rows.sort(key=lambda x: x.get('created_at') or '', reverse=True)
        # Only source identity and conversion controls belong in this response.
        # Full evaluation/label contracts can be megabytes and are unrelated to
        # conversion history; the original version record remains unchanged.
        visible_version = {key: version[key] for key in (
            'id', 'version_no', 'version_name', 'model_name', 'stored_path',
            'size_mb', 'status', 'framework', 'created_at', 'model_metadata',
        ) if key in version}
        visible_version["conversion_defaults"] = self.dependencies._version_deploy_conversion_defaults(project_id, version)
        return {'ok': True, **{k:v for k,v in history.items() if k!='items'},
            'algorithm': {'id': algo.get('id'), 'name': algo.get('name')}, 'version': visible_version, 'items': rows}

    def v30_export_model_package(self, project_id: str, payload: ModelExportReq):
        try:
            return self._do_export_model_package(project_id, payload)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"导出失败：{type(e).__name__}: {e}")

    def v32_export_model_package(self, project_id: str, payload: ModelExportReq):
        return self.v30_export_model_package(project_id, payload)

    def _do_export_model_package(self, project_id: str, payload: ModelExportReq):
        project = self.dependencies.get_project(project_id)
        p = self.dependencies.project_dir(project_id)
        if payload.algorithm_id and payload.version_id:
            model_path = None
            model_name = payload.model_name or "algorithm_version_model"
            model_key = ""
            for a in self.dependencies.list_algorithms_internal(project_id):
                if a.get("id") == payload.algorithm_id:
                    v = next((x for x in a.get("versions", []) if x.get("id") == payload.version_id), None)
                    if v:
                        model_path = Path(v.get("stored_path", "")); model_name = v.get("model_name") or model_path.name
                        model_key = f"algorithm::{payload.algorithm_id}::{payload.version_id}"
                    break
            if not model_path or not model_path.exists() or not model_path.is_file():
                raise HTTPException(status_code=404, detail="算法版本模型不存在。")
        else:
            model_path, model_name, model_key = self.dependencies.resolve_any_model_path(project_id, payload.model_name, payload.model_source, payload.local_path or "")
        meta = self.dependencies._find_model_meta(project_id, model_path, model_name)
        job = self.dependencies._find_job_for_model(project_id, meta)
        target = (payload.deployment_target or "platform_package").strip()
        if target not in {"platform_package", "paddledet_weight", "paddledet_infer", "ultralytics_onnx", "sophon_prepare"}:
            raise HTTPException(status_code=400, detail=f"不支持的导出目标：{target}")
        suffix = model_path.suffix.lower()
        framework = meta.get("framework") or ("paddle" if suffix in {".pdparams", ".pdmodel", ".pdiparams"} else "ultralytics" if suffix == ".pt" else "unknown")
        if target.startswith("paddledet") and framework != "paddle":
            raise HTTPException(status_code=400, detail="当前导出目标是飞桨部署包，但所选模型不是飞桨模型。请选择 .pdparams/.pdmodel/.pdiparams。")
        if target == "ultralytics_onnx" and suffix != ".pt":
            raise HTTPException(status_code=400, detail="ONNX 导出目前只支持 Ultralytics .pt 模型。")
        labels = self._export_labels(project, meta, job)
        export_conf = self._build_export_config(payload, model_path, framework, labels)
        export_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        pkg_name = f"export_{self.dependencies.safe_filename(model_path.stem)}_{target}_{export_id}"
        work = p / "exports" / pkg_name
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)

        copied_models = self._copy_model_related_files(model_path, work / "model")
        cfg_path = meta.get("config_path") or meta.get("generated_config_path") or meta.get("algorithm_config_path") or job.get("generated_config_path") or job.get("algorithm_config_path") or ""
        cfg_file = ""
        if cfg_path and self.dependencies._copy_if_exists(cfg_path, work / "config" / Path(str(cfg_path)).name):
            cfg_file = f"config/{Path(str(cfg_path)).name}"
        if payload.include_dataset_labels:
            (work / "labels").mkdir(parents=True, exist_ok=True)
            self.dependencies._write_export_text(work / "labels" / "label_list.txt", "\n".join(labels))
            self.dependencies._write_export_json(work / "labels" / "labels.json", labels)
        if payload.include_report:
            report_dir = work / "report"
            report_dir.mkdir(parents=True, exist_ok=True)
            if job:
                jf = p / "jobs" / str(meta.get("job_id")) / "job.json"
                if jf.exists(): shutil.copy2(jf, report_dir / "job.json")
                for log_name in ["train.log", "log.txt"]:
                    lf = p / "jobs" / str(meta.get("job_id")) / log_name
                    if lf.exists(): shutil.copy2(lf, report_dir / log_name)
            try:
                self.dependencies._write_export_json(report_dir / "train_report.json", self.dependencies.job_report(project_id, meta.get("job_id", ""), model_path))
            except Exception as e:
                self.dependencies._write_export_text(report_dir / "train_report_error.txt", str(e))

        convert_result = {"ok": False, "note": "", "outputs": []}
        if target == "paddledet_infer":
            penv = self.dependencies.get_active_paddle_env()
            convert_result = self.dependencies._try_export_paddledet_infer(project_id, penv.get("python_path", ""), model_path, {**meta, "config_path": cfg_path}, work, export_conf)
        elif target == "ultralytics_onnx":
            convert_result = self.dependencies._try_export_ultralytics_onnx(project_id, model_path, work / "converted", export_conf)
        elif target == "sophon_prepare":
            convert_result = {"ok": True, "note": "已生成算能/边缘部署准备包；该包用于后续芯片工具链转换，不直接等于可运行 bmodel。", "outputs": []}
        elif target == "paddledet_weight":
            convert_result = {"ok": True, "note": "已生成 PaddleDetection 权重部署包；可继续用 PaddleDetection 配置 + .pdparams 加载部署。", "outputs": []}
        else:
            convert_result = {"ok": True, "note": "已生成平台验证包；适合本机检测台、归档和后续转换。", "outputs": []}

        metadata = {
            "export_id": export_id,
            "export_time": self.dependencies.now_iso(),
            "project_id": project_id,
            "project_name": project.get("name"),
            "model_name": model_path.name,
            "model_file": f"model/{model_path.name}",
            "model_path_source": str(model_path),
            "model_key": model_key,
            "model_type": suffix.lstrip("."),
            "deployment_target": target,
            "framework": framework,
            "num_classes": int(meta.get("num_classes") or job.get("num_classes") or len(labels) or 0),
            "labels": labels,
            "config_path_source": str(cfg_path or ""),
            "config_file": cfg_file,
            "job_id": meta.get("job_id", ""),
            "job_name": meta.get("job_name", ""),
            "export_config": export_conf,
            "conversion": convert_result,
            "copied_models": copied_models,
        }
        self.dependencies._write_export_json(work / "model_meta.json", metadata)
        self.dependencies._create_target_deploy_files(work, target, metadata, export_conf, convert_result)
        note = convert_result.get("note") or "导出包已生成。"
        readme = f"""# 畅联云算法导出包

模型：{model_path.name}
导出目标：{target}
框架：{framework}
类别数：{metadata['num_classes']}
导出时间：{metadata['export_time']}

## 导出结果
{note}

## 目录
- model/：模型文件，飞桨推理模型会包含关联文件
- config/：部署目标配置、运行参数、转换说明
- labels/：标签列表
- report/：训练报告和训练日志（如勾选）
- converted/：Ultralytics ONNX 转换产物（如选择）
- inference_model/：PaddleDetection export_model 推理模型（如选择且转换成功）

## 使用提醒
1. 平台验证包：直接用于本系统检测台、项目归档和交接。
2. PaddleDetection 权重包：用于飞桨代码环境继续加载 .pdparams。
3. Paddle 推理模型：优先看 inference_model 目录；若转换失败，请查看 export_model_command.txt。
4. ONNX 包：优先看 converted 目录；若转换失败，请查看 export_onnx_command.txt。
5. 算能/边缘盒子准备包：不是最终 bmodel，需继续使用目标芯片工具链转换、量化和实机验证。

## 蒸馏说明
导出不是蒸馏。蒸馏需要教师模型、学生模型、蒸馏数据和单独训练任务。
"""
        self.dependencies._write_export_text(work / "README.md", readme)
        zip_path = p / "exports" / f"{pkg_name}.zip"
        self.dependencies._zip_dir(work, zip_path)
        metadata.update(zip_sha256=sha256_file(zip_path), zip_size_bytes=zip_path.stat().st_size)
        self.dependencies._write_export_json(work / 'model_meta.json', metadata)
        return {
            "ok": True,
            "name": zip_path.name,
            "download_url": self.dependencies._business_file_url(project_id, 'exports', zip_path.name),
            "path": str(zip_path),
            "note": note,
            "metadata": metadata,
            "conversion_ok": bool(convert_result.get("ok")),
        }

    def _build_export_config(self, payload: ModelExportReq, model_path: Path, framework: str, labels: List[str]) -> Dict[str, Any]:
        cfg = dict(payload.export_config or {})
        target = payload.deployment_target or "platform_package"
        def _int(key, default):
            try:
                return int(cfg.get(key, default))
            except Exception:
                return default
        def _float(key, default):
            try:
                return float(cfg.get(key, default))
            except Exception:
                return default
        conf = {
            "deployment_target": target,
            "framework": framework,
            "input_size": _int("input_size", 320 if framework == "paddle" else 640),
            "confidence": _float("confidence", 0.25),
            "device": str(cfg.get("device") or "cpu"),
            "precision": str(cfg.get("precision") or "fp32"),
            "runtime": str(cfg.get("runtime") or target),
            "include_source_model": bool(cfg.get("include_source_model", True)),
            "try_convert": bool(payload.try_convert),
            "label_count": len(labels),
            "labels": labels,
            "model_file": f"model/{model_path.name}",
        }
        if target == "sophon_prepare":
            conf.update({
                "target_chip": str(cfg.get("target_chip") or "bm1684x/bm1688/cv186ah 待确认"),
                "quantization": str(cfg.get("quantization") or "fp32"),
                "note": "本包是算能/边缘盒子转换准备包，不直接等于 bmodel。需在目标设备工具链中继续转换、量化和验证。",
            })
        elif target == "paddledet_infer":
            conf.update({"expected_outputs": ["inference_model/*.pdmodel", "inference_model/*.pdiparams", "inference_model/infer_cfg.yml"]})
        elif target == "ultralytics_onnx":
            conf.update({
                "onnx_dynamic": bool(cfg.get("onnx_dynamic", False)),
                "onnx_simplify": bool(cfg.get("onnx_simplify", False)),
                "onnx_opset": _int("onnx_opset", 12),
                "expected_outputs": ["converted/*.onnx"],
            })
        return conf

    def _copy_model_related_files(self, model_path: Path, model_dir: Path) -> List[str]:
        model_dir.mkdir(parents=True, exist_ok=True)
        copied = []
        if model_path.exists() and model_path.is_file():
            dst = model_dir / model_path.name
            shutil.copy2(model_path, dst)
            copied.append(dst.name)
        if model_path.suffix.lower() in {".pdmodel", ".pdiparams"}:
            stem = Path(str(model_path.with_suffix("")))
            for cand in [model_path.with_suffix(".pdmodel"), model_path.with_suffix(".pdiparams"), Path(str(stem) + ".pdiparams.info"), model_path.with_suffix(".yml"), model_path.with_suffix(".yaml")]:
                if cand.exists() and cand.is_file() and cand.name not in copied:
                    shutil.copy2(cand, model_dir / cand.name)
                    copied.append(cand.name)
        return copied

    def _export_labels(self, project: Dict[str, Any], meta: Dict[str, Any], job: Dict[str, Any]) -> List[str]:
        raw = job.get("labels") or meta.get("labels") or project.get("labels") or []
        if isinstance(raw, dict):
            raw = raw.get("items") or raw.get("labels") or []
        if not isinstance(raw, list):
            raw = []
        names = [self._export_label_name(x, i).strip() for i, x in enumerate(raw)]
        names = [x for x in names if x]
        n = int(meta.get("num_classes") or job.get("num_classes") or len(names) or 0)
        while n and len(names) < n:
            names.append(f"class_{len(names)}")
        return names

    def _export_label_name(self, x: Any, i: int) -> str:
        if isinstance(x, dict):
            return str(x.get("name") or x.get("display_name") or x.get("code") or f"class_{i}")
        if x is None:
            return f"class_{i}"
        return str(x)
