"""Domain orchestration over the existing persistence, worker and receipt owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from fastapi import HTTPException
from .runtime_catalog_contracts import LocalModelScanReq, PaddleDetectReq, PaddleEnvReq, TrainServerReq, TrainingRobustnessPolicyReq, UltralyticsEnvDetectReq

import json
import hashlib
import re
import os
import subprocess
import sys
import time
import threading
import uuid
from pathlib import Path
import requests
from fastapi import File, UploadFile
from filelock import FileLock, Timeout
from platform_core.annotations import atomic_write_json
from platform_core.conversion import sha256_file
from platform_core.mother_model_assets import asset_selection as _verified_mother_model_asset, get_asset as _get_mother_model_asset, initial_asset as _register_mother_model_asset, list_assets as _list_mother_model_assets, put_asset as _update_mother_model_asset, verify_checkpoint_in_sandbox as _verify_mother_model_checkpoint, verify_trusted_official_checkpoint as _verify_official_mother_model_checkpoint, verifier_environment_status as _mother_model_verifier_environment, public_asset_status as _public_mother_model_asset_status
from platform_core.mother_model_inventory import project_node_inventory as _project_node_mother_models
from platform_core.resource_discovery.request_scope import resolve_discovery_request_roots
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_runtime import TaskKind, TaskRecord, TaskStatus, WorkerInstanceService
from platform_core.training_devices import discover_training_devices, training_python
from platform_core.gpu_resources import GPUResourceManager, read_gpu_runtime_truth

@dataclass(frozen=True)
class RuntimeCatalogDependencies:
    APP_DISPLAY_NAME: Callable[..., Any]
    APP_VERSION: Callable[..., Any]
    BASE_DIR: Callable[..., Any]
    BUILD_ID: Callable[..., Any]
    DATA_DIR: Callable[..., Any]
    LOCAL_MODELS_FILE: Callable[..., Any]
    PADDLE_ENV_FILE: Callable[..., Any]
    SERVERS_FILE: Callable[..., Any]
    TRAINING_CATALOG: Callable[..., Any]
    _create_discovery_task: Callable[..., Any]
    _detect_paddle_candidate: Callable[..., Any]
    _discovery_cache: Callable[..., Any]
    _prepared_mother_model_rows: Callable[..., Any]
    _public_discovery_task: Callable[..., Any]
    _record_legacy_health: Callable[..., Any]
    _remote_capabilities: Callable[..., Any]
    _system_recommendation_payload: Callable[..., Any]
    _worker_gpu_recommendation: Callable[..., Any]
    default_paddle_roots: Callable[..., Any]
    get_active_paddle_env: Callable[..., Any]
    get_active_ultralytics_env: Callable[..., Any]
    inference_env_items: Callable[..., Any]
    list_models_internal: Callable[..., Any]
    logger: Callable[..., Any]
    now_iso: Callable[..., Any]
    read_json: Callable[..., Any]
    resolve_ultralytics_model: Callable[..., Any]
    scan_paddle_weights: Callable[..., Any]
    scan_paddledet_algorithms: Callable[..., Any]
    shared_task_artifacts: Callable[..., Any]
    shared_task_repository: Callable[..., Any]


class RuntimeCatalogService:
    def __init__(self, dependencies: RuntimeCatalogDependencies):
        self.dependencies = dependencies

    def system_version(self, ):
        return {
            "version": self.dependencies.APP_VERSION(),
            "build_id": self.dependencies.BUILD_ID(),
            "name": "算法训练",
            "data_dir": str(self.dependencies.DATA_DIR()),
            "base_dir": str(self.dependencies.BASE_DIR()),
            "persistent": True,
        }

    def list_worker_runtime(self, ):
        return {"items": WorkerInstanceService(self.dependencies.shared_task_repository()).list_runtime()}

    def gpu_runtime_truth(self, ):
        return read_gpu_runtime_truth(self.dependencies.shared_task_repository())

    def training_robustness_policy(self, ):
        from platform_core.training_robustness import read_global_policy
        return read_global_policy(self.dependencies.DATA_DIR())

    def save_training_robustness_policy(self, payload: TrainingRobustnessPolicyReq):
        from platform_core.training_robustness import save_global_policy
        try:
            return save_global_policy(self.dependencies.DATA_DIR(), payload.policy, payload.expected_revision)
        except ValueError as error:
            raise HTTPException(status_code=409 if 'revision' in str(error) else 422, detail=str(error)) from error

    def system_recommendation(self, probe_local_cuda: bool = False):
        # Routine reads are fast and neutral: a Web host's GPU is not evidence
        # about the Worker selected for training. Local CUDA probing is diagnostic
        # opt-in, not part of opening the training creation form.
        if not probe_local_cuda:
            try:
                confirmed = self.dependencies._worker_gpu_recommendation(self.gpu_runtime_truth())
                if confirmed is not None:
                    return confirmed
            except Exception:
                # The recommendation is advisory. A telemetry outage must not
                # block creation or change the actual training admission owner.
                pass
            return self.dependencies._system_recommendation_payload()
        cuda = False
        gpu_name = "未检测到可用 CUDA"
        try:
            probe = subprocess.run(
                [sys.executable, "-c", "import json,torch; c=bool(torch.cuda.is_available()); print(json.dumps({'cuda':c,'gpu':torch.cuda.get_device_name(0) if c else ''},ensure_ascii=False))"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
            )
            if probe.returncode == 0 and probe.stdout.strip():
                info = json.loads(probe.stdout.strip().splitlines()[-1])
                cuda = bool(info.get("cuda"))
                gpu_name = str(info.get("gpu") or gpu_name)
        except subprocess.TimeoutExpired:
            gpu_name = "CUDA 探测超时（平台仍可使用）"
        except Exception:
            pass
        return self.dependencies._system_recommendation_payload(cuda, gpu_name)

    def list_local_models(self, limit: int = 200, cursor: Optional[str] = None):
        cache = self.dependencies._discovery_cache()
        metadata = cache.metadata()["models"]
        if metadata["completed_generation"] > 0:
            try:
                page = cache.list_models(limit=max(1, min(5000, int(limit))), cursor=cursor)
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
            return {
                "ok": True,
                "items": list(page.items),
                "total": metadata["row_count"],
                "next_cursor": page.next_cursor,
                "roots": [],
                "updated_at": metadata["completed_at"] or "",
                "scan_id": metadata["scan_id"],
                "generation": metadata["completed_generation"],
            }
        # Preserve an existing pre-migration cache until the first durable scan.
        data = self.dependencies.read_json(self.dependencies.LOCAL_MODELS_FILE(), {})
        if isinstance(data, list):
            return {"ok": True, "items": data, "total": len(data), "roots": [], "updated_at": ""}
        return data or {"ok": True, "items": [], "total": 0, "roots": [], "updated_at": ""}

    def scan_local_models(self, payload: LocalModelScanReq):
        submitted_roots = [value for value in (payload.roots or []) if str(value).strip()]
        scope = payload.scope or ("directory" if submitted_roots else "full")
        if scope == "directory" and not submitted_roots:
            raise HTTPException(status_code=422, detail="指定目录扫描至少需要一个目录")
        try:
            roots = resolve_discovery_request_roots(scope, submitted_roots)
        except ValueError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return self.dependencies._public_discovery_task(self.dependencies._create_discovery_task("local_models", scope, roots))

    def get_ultralytics_env(self, ):
        cache = self.dependencies._discovery_cache()
        metadata = cache.metadata()["environment"]
        candidates = cache.list_environments()
        return {
            "ok": True,
            "active": self.dependencies.get_active_ultralytics_env(),
            "candidates": candidates,
            "items": candidates,
            "updated_at": metadata["completed_at"] or "",
            "scan_id": metadata["scan_id"],
            "generation": metadata["completed_generation"],
        }

    def detect_ultralytics_env(self, payload: UltralyticsEnvDetectReq):
        try:
            roots = resolve_discovery_request_roots(payload.scope, payload.roots)
        except ValueError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return self.dependencies._public_discovery_task(
            self.dependencies._create_discovery_task("ultralytics_environment", payload.scope, roots)
        )

    def get_resource_discovery_task(self, task_id: str):
        task = self.dependencies.shared_task_repository().get(task_id)
        if (
            task is None
            or task.project_id != "__system__"
            or task.kind is not TaskKind.RESOURCE_DISCOVERY
        ):
            raise HTTPException(status_code=404, detail="资源检测任务不存在")
        return self.dependencies._public_discovery_task(task)

    def cancel_resource_discovery_task(self, task_id: str):
        task = self.dependencies.shared_task_repository().get(task_id)
        if (
            task is None
            or task.project_id != "__system__"
            or task.kind is not TaskKind.RESOURCE_DISCOVERY
        ):
            raise HTTPException(status_code=404, detail="资源检测任务不存在")
        return self.dependencies._public_discovery_task(self.dependencies.shared_task_repository().request_cancel(task_id))

    def training_catalog(self, ):
        return {"ok": True, **self.dependencies.TRAINING_CATALOG()}

    async def upload_preinstalled_base_model(self, file: UploadFile = File(...)):
        """Explicit opt-in preload to durable storage. Does not invoke Ultralytics."""
        filename = str(file.filename or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\.pt", filename, re.IGNORECASE):
            raise HTTPException(status_code=422, detail="母模型文件名仅支持字母数字点横线下划线，必须为 .pt")
        root = self.dependencies.DATA_DIR() / "models"
        root.mkdir(parents=True, exist_ok=True)
        path = root / filename
        temp = root / f".{uuid.uuid4().hex}.model-upload"
        digest = hashlib.sha256()
        size = 0
        try:
            with temp.open("xb") as stream:
                while chunk := await file.read(4 * 1024 * 1024):
                    size += len(chunk)
                    if size > 1024 * 1024 * 1024:
                        raise HTTPException(status_code=413, detail="母模型最大允许 1 GiB")
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if size < 1024:
                raise HTTPException(status_code=422, detail="母模型文件过小")
            with FileLock(str(root / f".{filename}.lock"), timeout=30):
                if path.is_file():
                    if path.stat().st_size != size or sha256_file(path) != digest.hexdigest():
                        raise HTTPException(status_code=409, detail="同名权重内容不同；请换名称上传，不能静默覆盖母模型")
                    reused = True
                else:
                    os.replace(temp, path)
                    reused = False
            asset = _register_mother_model_asset(self.dependencies.DATA_DIR(), path, digest.hexdigest())
            # Official, byte-for-byte pinned weights need no pickle load or sandbox.
            # All unknown or repacked PT files retain the explicit sandbox gate.
            official = _verify_official_mother_model_checkpoint(path)
            if official:
                asset = _update_mother_model_asset(self.dependencies.DATA_DIR(), {
                    "asset_id": asset["asset_id"], "name": filename,
                    "path": str(path.resolve()), "size_bytes": size,
                    "node_locations": [{"node_id": "controller", "state": "PRESENT", "sha256": digest.hexdigest()}],
                    **official, "verified_at": time.time(),
                })
            return {"ok": True, "reused": reused, "name": filename, "path": str(path.resolve()),
                    "asset_id": asset["asset_id"], "validation_status": asset["validation_status"],
                    "size_bytes": size, "sha256": digest.hexdigest(), "model_status": "FOUND"}
        except Timeout as error:
            raise HTTPException(status_code=409, detail="相同母模型正在上传，请稍后重试") from error
        finally:
            temp.unlink(missing_ok=True)
            await file.close()

    def list_mother_model_assets(self, ):
        """Cached evidence only. GET must never import torch or scan Agent disks."""
        return {"items": [_public_mother_model_asset_status(item) for item in _list_mother_model_assets(self.dependencies.DATA_DIR())],
                "verification_environment": _mother_model_verifier_environment()}

    def list_mother_model_node_inventory(self, ):
        """Show bounded Agent-discovered paths; never infer verified/installed PT."""
        nodes = ServiceNodeRepository(self.dependencies.shared_task_repository()).list_public()
        return {"items": _project_node_mother_models(nodes)}

    def install_mother_model_to_node(self, asset_id: str, payload: Dict[str, Any]):
        """Queue an Agent-owned installation; never write to a remote path in Web."""
        if not re.fullmatch(r"pt_[0-9a-f]{24}", asset_id):
            raise HTTPException(422, detail="母模型资产编号无效")
        node_id = str(payload.get("node_id") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", node_id):
            raise HTTPException(422, detail="请从现有服务节点中选择目标服务器")
        asset = _verified_mother_model_asset(self.dependencies.DATA_DIR(), asset_id)
        if asset is None:
            raise HTTPException(409, detail="母模型尚未通过安全校验，或文件已变化；请先重新校验")
        try:
            node = ServiceNodeRepository(self.dependencies.shared_task_repository()).get_public(node_id)
        except Exception as error:
            if getattr(error, "status_code", 0) == 404:
                raise HTTPException(404, detail="目标服务节点不存在") from error
            raise
        if (not node.get("online") or node.get("connection_mode") != "agent"
                or "model-upload" not in (node.get("effective_capabilities") or [])):
            raise HTTPException(409, detail="目标节点离线或未启用模型安装能力；请在节点配置和 Agent 中启用 model-upload")
        repository = self.dependencies.shared_task_repository()
        for candidate in repository.list(project_id="__system__", kinds=(TaskKind.MODEL_INSTALL,), limit=100).items:
            if candidate.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED}:
                continue
            previous = self.dependencies.shared_task_artifacts().read_json(candidate.task_id, candidate.payload_ref, default={})
            if (isinstance(previous, dict) and previous.get("asset_id") == asset_id
                    and previous.get("node_id") == node_id):
                return {"ok": True, "deduplicated": True, "task_id": candidate.task_id,
                        "status": candidate.status.value}
        task_id = "minstall_" + uuid.uuid4().hex
        request = {"asset_id": asset_id, "node_id": node_id, "sha256": asset["sha256"],
                   "size_bytes": int(asset["size_bytes"]), "execution_mode": "agent",
                   "scheduling": {"mode": "node", "node_id": node_id},
                   "remote_execution": {"version": 1, "task_kind": "MODEL_INSTALL",
                                        "transport": "agent-artifact-v1"}}
        self.dependencies.shared_task_artifacts().atomic_write_json(task_id, "request.json", request)
        task = repository.create(TaskRecord.new(
            task_id, "__system__", TaskKind.MODEL_INSTALL, "request.json",
            f"model-install:{node_id}", required_capabilities=("agent.model.install",),
        ))
        return {"ok": True, "deduplicated": False, "task_id": task.task_id, "status": task.status.value}

    def list_mother_model_installations(self, cursor: Optional[str] = None):
        """Project only authoritative task status and same-generation Agent receipt."""
        page = self.dependencies.shared_task_repository().list(project_id="__system__", kinds=(TaskKind.MODEL_INSTALL,),
                                             limit=100, cursor=cursor)
        artifacts = self.dependencies.shared_task_artifacts()
        rows = []
        for task in page.items:
            payload = artifacts.read_json(task.task_id, task.payload_ref, default={})
            if not isinstance(payload, dict):
                continue
            receipt = artifacts.read_json(task.task_id, task.result_ref, default={}) if task.result_ref else {}
            valid_receipt = (task.status is TaskStatus.SUCCEEDED and isinstance(receipt, dict)
                             and receipt.get("sha256") == payload.get("sha256")
                             and receipt.get("asset_id") == payload.get("asset_id")
                             and receipt.get("node_id") == payload.get("node_id")
                             and receipt.get("execution_generation") == task.attempt)
            rows.append({"task_id": task.task_id, "asset_id": payload.get("asset_id"),
                         "node_id": payload.get("node_id"), "status": task.status.value,
                         "progress": task.progress, "stage": task.stage, "error": task.error,
                         "created_at": task.created_at, "finished_at": task.finished_at,
                         "installed": bool(valid_receipt),
                         "verified_sha256": receipt.get("sha256") if valid_receipt else None})
        return {"items": rows, "next_cursor": page.next_cursor}

    def cancel_mother_model_installation(self, task_id: str):
        task = self.dependencies.shared_task_repository().get(task_id)
        if task is None or task.kind is not TaskKind.MODEL_INSTALL or task.project_id != "__system__":
            raise HTTPException(404, detail="母模型安装任务不存在")
        if task.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED}:
            return {"ok": True, "task_id": task_id, "status": task.status.value}
        try:
            result = self.dependencies.shared_task_repository().request_cancel(task_id)
        except ValueError as error:
            raise HTTPException(409, detail=str(error)) from error
        return {"ok": True, "task_id": task_id, "status": result.status.value}

    def register_discovered_mother_model(self, payload: Dict[str, Any]):
        """Import an *exact cached controller discovery result* into managed assets.

    This is an explicit user action. It cannot copy an arbitrary local path or
    treat an unverified remote heartbeat path as a training-ready checkpoint.
    """
        reference = str(payload.get("path") or "").strip()
        if not reference or len(reference) > 1000:
            raise HTTPException(status_code=422, detail="请指定已发现的模型路径")
        cache = self.dependencies._discovery_cache()
        if cache.metadata()["models"]["completed_generation"] < 1:
            raise HTTPException(status_code=409, detail="尚未完成本机模型扫描，请先检测目录")
        discovered = cache.find_model_by_path(reference)
        if not discovered or str(discovered.get("format") or "").lower() != "pt":
            raise HTTPException(status_code=404, detail="此文件不在上次成功的本机 .pt 扫描结果中")
        source = Path(str(discovered["path"]))
        if source.is_symlink() or not source.is_file():
            raise HTTPException(status_code=409, detail="发现的母模型已移动或不是普通文件，请重新扫描")
        size = source.stat().st_size
        if size < 1024 or size > 1024 * 1024 * 1024 or size != discovered.get("size_bytes"):
            raise HTTPException(status_code=409, detail="模型大小已变化或超出 1GiB 限制，请重新扫描")
        root = self.dependencies.DATA_DIR() / "models"
        root.mkdir(parents=True, exist_ok=True)
        temp = root / f".{uuid.uuid4().hex}.discovered-model"
        digest = hashlib.sha256()
        copied = 0
        try:
            with source.open("rb") as origin, temp.open("xb") as target:
                while chunk := origin.read(4 * 1024 * 1024):
                    copied += len(chunk)
                    if copied > 1024 * 1024 * 1024:
                        raise HTTPException(status_code=413, detail="发现的母模型超过 1GiB")
                    digest.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            if copied != size:
                raise HTTPException(status_code=409, detail="扫描后模型内容已变化，请重新扫描")
            suffix = digest.hexdigest()[:16]
            destination = root / f"discovered-{suffix}.pt"
            with FileLock(str(root / f".discovered-{suffix}.lock"), timeout=30):
                if destination.exists():
                    if destination.stat().st_size != copied or sha256_file(destination) != digest.hexdigest():
                        raise HTTPException(status_code=409, detail="已存在同名但内容不同的母模型")
                    reused = True
                else:
                    os.replace(temp, destination)
                    reused = False
            asset = _register_mother_model_asset(self.dependencies.DATA_DIR(), destination, digest.hexdigest(), source="controller_discovery")
            return {"ok": True, "reused": reused, "asset_id": asset["asset_id"],
                    "validation_status": asset["validation_status"], "sha256": digest.hexdigest()}
        except Timeout as error:
            raise HTTPException(status_code=409, detail="模型正在登记，请稍后重试") from error
        finally:
            temp.unlink(missing_ok=True)

    def verify_mother_model_asset(self, asset_id: str):
        """Trigger a fenced, local sandbox probe; never deserialize in Web."""
        if not re.fullmatch(r"pt_[0-9a-f]{24}", asset_id):
            raise HTTPException(status_code=422, detail="母模型资产编号格式不正确")
        asset = _get_mother_model_asset(self.dependencies.DATA_DIR(), asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="母模型资产不存在")
        path = Path(str(asset.get("path") or ""))
        if not path.is_file() or path.stat().st_size != asset.get("size_bytes"):
            raise HTTPException(status_code=409, detail="母模型文件已丢失或大小变化，请重新上传")
        # The registry already uses FileLock. Keep the same asset owner and use a
        # per-asset OS lock across Web workers, not a process-local _active set.
        lock = FileLock(str(self.dependencies.DATA_DIR() / "models" / f".{asset_id}.verify.lock"), timeout=0, thread_local=False)
        try:
            lock.acquire(timeout=0)
        except Timeout:
            return {"accepted": True, "asset_id": asset_id, "validation_status": "CHECKING", "deduplicated": True}

        def run_probe():
            try:
                result = _verify_official_mother_model_checkpoint(path) or _verify_mother_model_checkpoint(path)
                if path.is_file() and sha256_file(path) == asset["sha256"]:
                    _update_mother_model_asset(self.dependencies.DATA_DIR(), {"asset_id": asset_id, **result, "verified_at": time.time()})
                else:
                    _update_mother_model_asset(self.dependencies.DATA_DIR(), {"asset_id": asset_id, "validation_status": "INVALID", "trainable": False, "validation_error": "PT_SHA256_CHANGED"})
            except Exception:
                self.dependencies.logger().exception("Mother model sandbox probe failed for asset %s", asset_id)
                _update_mother_model_asset(self.dependencies.DATA_DIR(), {"asset_id": asset_id, "validation_status": "FAILED", "trainable": False, "validation_error": "PT_PROBE_FAILED"})
            finally:
                lock.release()

        try:
            _update_mother_model_asset(self.dependencies.DATA_DIR(), {"asset_id": asset_id, "validation_status": "CHECKING", "trainable": False, "validation_started_at": time.time()})
            threading.Thread(target=run_probe, name=f"mother-model-verify-{asset_id}", daemon=True).start()
        except Exception:
            lock.release()
            raise
        return {"accepted": True, "asset_id": asset_id, "validation_status": "CHECKING"}

    def list_base_models(self, project_id: Optional[str] = None):
        """训练页基础模型下拉框。区分 Ultralytics 可训练权重和飞桨模型源。"""
        items: List[Dict[str, Any]] = self.dependencies._prepared_mother_model_rows()
        for name in ["yolo11n.pt", "yolo11s.pt", "yolo11m.pt"]:
            resolution = self.dependencies.resolve_ultralytics_model(name, project_id)
            items.append({
                "label": f"官方 Ultralytics：{name}",
                "value": name,
                "source": "official",
                "framework_key": "ultralytics",
                "train_framework": "ultralytics",
                "trainable": True,
                "note": "已发现本地权重。" if resolution.found else "尚未预置，须先在训练资源上传，训练时不自动下载。",
                **resolution.as_dict(),
            })
        active_env = self.dependencies.get_active_ultralytics_env()
        for m in active_env.get("models", []) if isinstance(active_env.get("models", []), list) else []:
            candidate = Path(str(m.get("path") or ""))
            if candidate.suffix.lower() == ".pt" and candidate.is_file() and candidate.stat().st_size >= 1024:
                items.append({
                    "label": f"已检测 Ultralytics 环境模型：{m.get('name')}",
                    "value": m.get("path"),
                    "source": "ultralytics_env",
                    "framework_key": "ultralytics",
                    "train_framework": "ultralytics",
                    "trainable": True,
                    "note": f"来自已保存 Ultralytics 环境：{active_env.get('root', '')}",
                    "model_status": "FOUND",
                    "downloadable": False,
                    "environment_status": str(active_env.get("status") or "AVAILABLE").upper(),
                })
        if project_id:
            try:
                for m in self.dependencies.list_models_internal(project_id):
                    if m.get("type") == "pt":
                        items.append({
                            "label": f"当前项目模型：{m['name']}",
                            "value": m["path"],
                            "source": "project",
                            "framework_key": "ultralytics",
                            "train_framework": "ultralytics",
                            "trainable": True,
                            "note": "可基于上一次 best.pt 继续训练。",
                            "model_status": "FOUND",
                            "downloadable": False,
                            "environment_status": str(active_env.get("status") or "AVAILABLE").upper(),
                        })
            except Exception:
                pass
        local = self.dependencies.read_json(self.dependencies.LOCAL_MODELS_FILE(), {})
        for m in (local.get("items", []) if isinstance(local, dict) else []):
            local_candidate = Path(str(m.get("path") or ""))
            if m.get("trainable_current_platform") and local_candidate.suffix.lower() == ".pt" and local_candidate.is_file() and local_candidate.stat().st_size >= 1024:
                items.append({
                    "label": f"本机 .pt：{m.get('name')}",
                    "value": m.get("path"),
                    "source": "local_scan",
                    "framework_key": "ultralytics",
                    "train_framework": "ultralytics",
                    "trainable": True,
                    "note": m.get("note") or "本机路径只适合本机训练。",
                    "model_status": "FOUND",
                    "downloadable": False,
                    "environment_status": str(active_env.get("status") or "AVAILABLE").upper(),
                })
            elif m.get("trainable_paddle"):
                items.append({
                    "label": f"本机飞桨权重：{m.get('name')}",
                    "value": m.get("path"),
                    "source": "local_scan",
                    "framework_key": "paddle",
                    "train_framework": "paddle",
                    "trainable": False,
                    "note": "这是飞桨训练权重，需要 PaddleX/PaddleDetection 训练执行器；不能直接用于 Ultralytics 训练。"
                })
            elif m.get("framework_key") == "paddle_service":
                model_name = m.get("detected_model_name") or "PP-YOLOE-S_human"
                items.append({
                    "label": f"飞桨服务脚本：{model_name}",
                    "value": model_name,
                    "source": "local_scan",
                    "framework_key": "paddle_service",
                    "train_framework": "paddle",
                    "trainable": False,
                    "note": "这是通过 create_model 加载的服务脚本，可用于推理/预标注；不是独立训练权重。"
                })
        return {"ok": True, "items": items}

    def get_paddle_env(self, ):
        return {"ok": True, "active": self.dependencies.get_active_paddle_env(), "updated_at": self.dependencies.now_iso()}

    def select_paddle_env(self, payload: PaddleEnvReq):
        env = {
            "name": payload.name or "本机飞桨",
            "python_path": (payload.python_path or sys.executable).strip().strip('"'),
            "paddledet_dir": (payload.paddledet_dir or os.environ.get("MC_PADDLEDET_DIR", "")).strip().strip('"'),
            "paddlex_dir": (payload.paddlex_dir or os.environ.get("MC_PADDLEX_DIR", "")).strip().strip('"'),
            "updated_at": self.dependencies.now_iso(),
        }
        if env["python_path"] and not Path(env["python_path"]).exists():
            raise HTTPException(status_code=400, detail="飞桨 Python 路径不存在")
        if env["paddledet_dir"] and not Path(env["paddledet_dir"]).exists():
            # 允许先保存但标记不可训练，避免用户只是先配置地址
            env["warning"] = "PaddleDetection 目录不存在，飞桨训练会失败；请先安装或修正目录。"
        elif env["paddledet_dir"]:
            scan = self.dependencies.scan_paddledet_algorithms(env["paddledet_dir"])
            env["algorithm_scan"] = scan
            env["weight_scan"] = self.dependencies.scan_paddle_weights(env["paddledet_dir"])
        atomic_write_json(self.dependencies.PADDLE_ENV_FILE(), env)
        return {"ok": True, "active": env}

    def test_paddle_env(self, payload: PaddleEnvReq):
        py = (payload.python_path or sys.executable).strip().strip('"')
        if not Path(py).exists():
            raise HTTPException(status_code=400, detail="Python 路径不存在")
        code = "import json\nmods={}\nfor m in ['paddle','paddlex']:\n    try:\n        mod=__import__(m); mods[m]=getattr(mod,'__version__','installed')\n    except Exception as e:\n        mods[m]='missing:'+str(e)\nprint(json.dumps(mods, ensure_ascii=False))"
        try:
            cp = subprocess.run([py, "-c", code], capture_output=True, text=True, timeout=20)
            out = (cp.stdout or cp.stderr or "").strip()
            data = json.loads(out.splitlines()[-1]) if out else {}
            alg_scan = self.dependencies.scan_paddledet_algorithms(payload.paddledet_dir or "") if payload.paddledet_dir else {"ok": False, "items": [], "total": 0, "families": {}, "error": "未填写 PaddleDetection 目录"}
            return {"ok": True, "python_path": py, "modules": data, "paddledet_exists": Path(payload.paddledet_dir or "").exists(), "paddlex_exists": Path(payload.paddlex_dir or "").exists(), "algorithm_scan": {"ok": alg_scan.get("ok"), "total": alg_scan.get("total",0), "families": alg_scan.get("families",{}), "error": alg_scan.get("error","")}}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"检测失败：{e}")

    def list_paddle_env_algorithms(self, ):
        env = self.dependencies.get_active_paddle_env()
        scan = self.dependencies.scan_paddledet_algorithms(env.get("paddledet_dir", "")) if env.get("paddledet_dir") else {"ok": False, "items": [], "total": 0, "families": {}, "error": "未配置 PaddleDetection 目录"}
        return {"ok": True, **scan}

    def scan_paddle_env_algorithms(self, payload: PaddleEnvReq):
        scan = self.dependencies.scan_paddledet_algorithms(payload.paddledet_dir or "")
        return {"ok": True, **scan}

    def detect_paddle_env(self, payload: PaddleDetectReq):
        roots = payload.roots or self.dependencies.default_paddle_roots()
        candidates=[]
        seen=set()
        for r in roots:
            if not r:
                continue
            root = Path(str(r).strip().strip('"')).expanduser()
            key=str(root).lower()
            if key in seen:
                continue
            seen.add(key)
            try:
                c=self.dependencies._detect_paddle_candidate(root)
                if c:
                    candidates.append(c)
            except Exception:
                pass
            if len(candidates)>=10:
                break
        active = candidates[0] if candidates else {}
        return {"ok": True, "candidates": candidates, "active": active}

    def list_train_servers(self, ):
        return self.dependencies.read_json(self.dependencies.SERVERS_FILE(), [])

    def save_train_server(self, payload: TrainServerReq):
        name = payload.name.strip()
        base_url = payload.base_url.strip().rstrip("/")
        if not name or not base_url:
            raise HTTPException(status_code=400, detail="服务器名称和地址不能为空")
        server_id = uuid.uuid4().hex[:10]
        item = {"id": server_id, "name": name, "base_url": base_url, "api_key": payload.api_key or "", "created_at": self.dependencies.now_iso()}
        with FileLock(str(self.dependencies.SERVERS_FILE()) + ".lock", timeout=30):
            servers = self.dependencies.read_json(self.dependencies.SERVERS_FILE(), [])
            servers.insert(0, item)
            atomic_write_json(self.dependencies.SERVERS_FILE(), servers[:20])
        return item

    def delete_train_server(self, server_id: str):
        with FileLock(str(self.dependencies.SERVERS_FILE()) + ".lock", timeout=30):
            servers = [s for s in self.dependencies.read_json(self.dependencies.SERVERS_FILE(), []) if s.get("id") != server_id]
            atomic_write_json(self.dependencies.SERVERS_FILE(), servers)
        return {"ok": True}

    def test_train_server(self, payload: TrainServerReq):
        base_url = payload.base_url.strip().rstrip("/")
        try:
            headers = {"X-API-Key": payload.api_key or ""}
            r = requests.get(f"{base_url}/api/remote/health", headers=headers, timeout=8)
            r.raise_for_status()
            data = r.json()
            # A draft connection test must never overwrite a different saved
            # identity. Saved entries may reuse the measured capabilities on GET.
            for saved in self.dependencies.read_json(self.dependencies.SERVERS_FILE(), []):
                if (str(saved.get("base_url") or "").rstrip("/") == base_url
                        and str(saved.get("api_key") or "") == str(payload.api_key or "")
                        and str(saved.get("name") or "") == str(payload.name or "").strip()):
                    caps = {"ok": True, **data} if isinstance(data, dict) else {"ok": False}
                    self.dependencies._record_legacy_health(str(saved.get("id") or ""), saved, caps)
            return {"ok": True, "response": data}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"连接失败：{e}")

    def test_saved_train_server(self, server_id: str):
        """Explicitly probe a configured legacy target; no probe on list/read."""
        server = next((row for row in self.dependencies.read_json(self.dependencies.SERVERS_FILE(), []) if row.get("id") == server_id), None)
        if server is None:
            raise HTTPException(status_code=404, detail="训练服务器不存在")
        capabilities = self.dependencies._remote_capabilities(server)
        self.dependencies._record_legacy_health(server_id, server, capabilities)
        if not capabilities.get("ok"):
            raise HTTPException(status_code=503, detail="训练服务器检测失败，请检查网络或服务配置")
        return {"ok": True, "last_checked_at": self.dependencies.now_iso()}

    def training_devices(self, ):
        return discover_training_devices(training_python(self.dependencies.DATA_DIR()))

    def gpu_resources(self, ):
        return GPUResourceManager(self.dependencies.shared_task_repository(), self.dependencies.shared_task_artifacts()).summary()

    def v12_app_info(self, ):
        return {"ok": True, "name": self.dependencies.APP_DISPLAY_NAME(), "version": self.dependencies.APP_VERSION()}

    def v16_inference_envs(self, ):
        return {"ok": True, "items": self.dependencies.inference_env_items()}
