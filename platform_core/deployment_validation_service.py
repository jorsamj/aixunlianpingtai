"""Domain orchestration over the existing persistence, worker and receipt owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict
from fastapi import HTTPException

import asyncio
import shutil
import sys
import uuid
from pathlib import Path
from fastapi import File, Form, UploadFile
from fastapi.responses import JSONResponse
from platform_core.conversion import sha256_file
from platform_core.errors import PlatformError
from platform_core.resource_discovery import OFFICIAL_DOWNLOADABLE_MODELS
from platform_core.task_runtime import ProcessController, TaskKind, TaskRecord, TaskStatus, task_to_public
from platform_core.remote_execution_transport import RemoteExecutionTransportError

@dataclass(frozen=True)
class DeploymentValidationDependencies:
    BASE_DIR: Callable[..., Any]
    IMAGE_EXTS: Callable[..., Any]
    _algorithm_version_for_action: Callable[..., Any]
    _algorithm_version_reference_fence: Callable[..., Any]
    _business_file_url: Callable[..., Any]
    _durable_process_identity: Callable[..., Any]
    _online_feedback_version_model_sha256: Callable[..., Any]
    _online_prediction_evidence: Callable[..., Any]
    _register_prediction_files: Callable[..., Any]
    _remote_execution_transport_service: Callable[..., Any]
    _require_shared_task: Callable[..., Any]
    _testable_version_pt_path: Callable[..., Any]
    deploy_root: Callable[..., Any]
    get_project: Callable[..., Any]
    image_info: Callable[..., Any]
    inference_env_items: Callable[..., Any]
    list_algorithms_internal: Callable[..., Any]
    now_iso: Callable[..., Any]
    project_dir: Callable[..., Any]
    resolve_any_model_path: Callable[..., Any]
    resolve_inference_python: Callable[..., Any]
    resolve_ultralytics_model: Callable[..., Any]
    safe_filename: Callable[..., Any]
    shared_task_artifacts: Callable[..., Any]
    shared_task_repository: Callable[..., Any]


class DeploymentValidationService:
    def __init__(self, dependencies: DeploymentValidationDependencies):
        self.dependencies = dependencies

    def _resolve_v61_test_model(self, project_id: str, *, model_name: str, model_source: str, local_path: str, algorithm_id: str, version_id: str) -> ModelResolution:
        source = str(model_source or "project").lower()
        if source == "deployment_artifact":
            candidate = Path(str(local_path or "")).resolve()
            root = self.dependencies.deploy_root(project_id).resolve()
            if not candidate.is_file() or root not in candidate.parents:
                raise HTTPException(status_code=404, detail="转换产物不存在或不属于当前项目")
            return self.dependencies.resolve_ultralytics_model(str(candidate), project_id)
        if algorithm_id and version_id:
            for algorithm in self.dependencies.list_algorithms_internal(project_id):
                if str(algorithm.get("id")) != str(algorithm_id):
                    continue
                version = next((item for item in algorithm.get("versions", []) if str(item.get("id")) == str(version_id)), None)
                path = self.dependencies._testable_version_pt_path(version or {})
                if path is not None:
                    return self.dependencies.resolve_ultralytics_model(str(path), project_id)
            raise HTTPException(status_code=404, detail="算法版本模型不存在")
        if source == "builtin":
            requested = str(model_name or "yolo11n.pt").strip()
            if Path(requested).is_absolute() or "/" in requested or "\\" in requested:
                raise HTTPException(status_code=400, detail="内置模型只允许使用平台支持的官方模型名")
            canonical = next(
                (name for name in OFFICIAL_DOWNLOADABLE_MODELS if name.casefold() == requested.casefold()),
                None,
            )
            if canonical is None:
                raise HTTPException(status_code=400, detail="内置模型不在平台允许的官方模型列表中")
            return self.dependencies.resolve_ultralytics_model(canonical, project_id)
        path, _, _ = self.dependencies.resolve_any_model_path(project_id, model_name, source, local_path)
        return self.dependencies.resolve_ultralytics_model(str(path), project_id)

    def public_deployment_test(self, task: TaskRecord) -> Dict[str, Any]:
        repository = self.dependencies.shared_task_repository()
        truth = task_to_public(task, repository)
        result = self.dependencies.shared_task_artifacts().read_json(task.task_id, task.result_ref, default={}) if task.result_ref else {}
        request = self.dependencies.shared_task_artifacts().read_json(task.task_id, task.payload_ref, default={})
        preparation = None
        if task.status is TaskStatus.QUEUED and "deployment.input.pending" in task.required_capabilities:
            child = repository.get(task.task_id + "-prepare")
            if child and child.project_id == task.project_id and child.kind is TaskKind.DEPLOYMENT_PREPARE:
                preparation = task_to_public(child, repository)
                truth.update(phase=preparation.get("phase") or "PREPARING_MODEL",
                             current_item=preparation.get("current_item"), progress_percent=0)
        return {
            **truth,
            # v61 compatibility aliases remain for the existing deployment UI/API contract.
            "id": task.task_id,
            "progress": truth.get("progress_percent", task.progress),
            "stage": truth.get("phase", task.stage),
            "result": result or {},
            "input_image_url": request.get("input_image_url", ""),
            "preparation": preparation,
        }

    async def create_deployment_test(self,
        project_id: str,
        model_name: str = Form(""), model_source: str = Form("project"),
        local_path: str = Form(""), algorithm_id: str = Form(""), version_id: str = Form(""),
        conf: float = Form(0.25), inference_framework: str = Form("ultralytics"),
        inference_env_id: str = Form(""),
        detection_batch_id: str = Form(""), detection_item_index: int = Form(-1),
        detection_item_total: int = Form(0), detection_side: str = Form(""),
        model_label: str = Form(""), original_filename: str = Form(""),
        model_scope: str = Form(""),
        creation_id: str = Form(""),
        detection_sides: str = Form(""),
        file: UploadFile = File(...),
    ):
        with self.dependencies._algorithm_version_reference_fence(
            project_id,
            str(algorithm_id or "").strip(),
            str(version_id or "").strip(),
        ):
            if creation_id:
                from platform_core.deployment.scenario_preparation import accept_creation, creation_task_id
                self.dependencies.get_project(project_id)
                if model_scope != "scenario" or model_source != "algorithm_version" or not algorithm_id or not version_id:
                    raise HTTPException(status_code=409, detail="场景检测创建必须指定正式算法训练版本")
                _, version = self.dependencies._algorithm_version_for_action(project_id, algorithm_id, version_id)
                from platform_core.algorithms import is_trainable_version
                if (not is_trainable_version(version, 'ultralytics') or version.get('trainable') is not True
                        or version.get('framework') != 'ultralytics'):
                    raise HTTPException(status_code=409, detail="SCENARIO_MODEL_INELIGIBLE: 仅允许正式成功训练且已核验的模型版本")
                batch_id = str(detection_batch_id or "").strip()
                side = str(detection_side or "").upper()
                expected_sides = sorted(set(filter(None, detection_sides.upper().split(',')))) or [side]
                if (not batch_id or len(batch_id) > 64 or not all(ch.isascii() and (ch.isalnum() or ch in '_-') for ch in batch_id)
                        or side not in {'A', 'B'} or side not in expected_sides or not set(expected_sides) <= {'A', 'B'}
                        or not 0 <= detection_item_index < detection_item_total <= 100000):
                    raise HTTPException(status_code=400, detail="检测批次或图片/模型侧身份无效")
                try:
                    task_id = creation_task_id(project_id, creation_id)
                except ValueError as error:
                    raise HTTPException(status_code=400, detail=str(error)) from error
                extension = Path(file.filename or 'test.jpg').suffix.lower()
                if extension not in self.dependencies.IMAGE_EXTS():
                    extension = '.jpg'
                envs = self.dependencies.inference_env_items(probe_modules=False)
                environment = next((row for row in envs if row.get('framework') == 'ultralytics'
                                    and (row.get('id') == inference_env_id if inference_env_id else row.get('status') == 'ready')), None)
                if not environment or not environment.get('python_path'):
                    raise HTTPException(status_code=400, detail="没有可用的测试环境，请重新选择")
                image = await file.read()
                if not image:
                    raise HTTPException(status_code=400, detail="测试图片为空")
                request = {
                    'model_scope': 'scenario', 'framework': 'ultralytics', 'runtime_format': 'pt',
                    'python_path': environment['python_path'], 'runner_path': str(self.dependencies.BASE_DIR() / 'predict_ultralytics_runner.py'),
                    'conf': max(0.0, min(1.0, float(conf))), 'input_extension': extension,
                    'input_url_template': self.dependencies._business_file_url(project_id, 'predictions', f'{task_id}/input{extension}'),
                    'output_url_template': self.dependencies._business_file_url(project_id, 'predictions', f'{task_id}/result.jpg'),
                    'model_identity': {'algorithm_id': algorithm_id, 'version_id': version_id, 'model_source': model_source,
                                       'label': str(model_label)[:300], 'model_name': str(model_name)[:300], 'framework': 'ultralytics', 'runtime_format': 'pt'},
                    'detection_batch': {'batch_id': batch_id, 'item_index': detection_item_index,
                                        'item_total': detection_item_total, 'side': side,
                                        'expected_sides': expected_sides,
                                        'original_filename': Path(str(original_filename or file.filename or 'test.jpg')).name[:255]},
                }
                try:
                    record = await asyncio.to_thread(accept_creation, self.dependencies.shared_task_repository(), self.dependencies.shared_task_artifacts(),
                                                    project_id, creation_id, request, image, self.dependencies.project_dir(project_id) / 'predictions')
                except ValueError as error:
                    raise HTTPException(status_code=409, detail=str(error)) from error
                return JSONResponse(status_code=202, content=self.public_deployment_test(record))
            return await self._create_deployment_test_under_version_fence(
                project_id=project_id,
                model_name=model_name,
                model_source=model_source,
                local_path=local_path,
                algorithm_id=algorithm_id,
                version_id=version_id,
                conf=conf,
                inference_framework=inference_framework,
                inference_env_id=inference_env_id,
                detection_batch_id=detection_batch_id,
                detection_item_index=detection_item_index,
                detection_item_total=detection_item_total,
                detection_side=detection_side,
                model_label=model_label,
                original_filename=original_filename,
                model_scope=model_scope,
                file=file,
            )

    async def _create_deployment_test_under_version_fence(self,
        project_id: str,
        model_name: str,
        model_source: str,
        local_path: str,
        algorithm_id: str,
        version_id: str,
        conf: float,
        inference_framework: str,
        inference_env_id: str,
        detection_batch_id: str,
        detection_item_index: int,
        detection_item_total: int,
        detection_side: str,
        model_label: str,
        original_filename: str,
        file: UploadFile,
        model_scope: str = "",
    ):
        self.dependencies.get_project(project_id)
        scenario_model = None
        if model_scope == "scenario":
            from platform_core.scenario_models import resolve_scenario_model, ScenarioModelUnavailable
            if model_source != "algorithm_version" or not algorithm_id or not version_id:
                raise HTTPException(status_code=409, detail="SCENARIO_MODEL_INELIGIBLE: 场景实测仅允许可信的正式训练算法版本")
            algorithm, version = self.dependencies._algorithm_version_for_action(project_id, algorithm_id, version_id)
            try:
                scenario_model = resolve_scenario_model(project_id, self.dependencies.project_dir(project_id), algorithm, version,
                    self.dependencies.shared_task_repository(), self.dependencies.shared_task_artifacts())
            except ScenarioModelUnavailable as error:
                raise HTTPException(status_code=409, detail=f"SCENARIO_MODEL_INELIGIBLE: {error}") from error
            model_resolution = self.dependencies.resolve_ultralytics_model(scenario_model["path"], project_id)
        else:
            model_resolution = self._resolve_v61_test_model(
                project_id, model_name=model_name, model_source=model_source, local_path=local_path,
                algorithm_id=algorithm_id, version_id=version_id,
            )
        if not model_resolution.found and not model_resolution.downloadable:
            raise HTTPException(status_code=404, detail="测试模型不存在，且不是允许自动下载的官方模型")
        model_path = str(model_resolution.path) if model_resolution.found else ""
        model_reference = "" if model_resolution.found else model_resolution.reference
        model_reference_type = "" if model_resolution.found else "official_downloadable"
        suffix = (model_resolution.path or Path(model_resolution.reference)).suffix.lower()
        framework = "paddle" if suffix in {".pdparams", ".pdmodel", ".pdiparams"} else "ultralytics"
        python_path = sys.executable if suffix in {".om", ".rknn", ".bmodel"} else self.dependencies.resolve_inference_python(framework, inference_env_id)
        extension = Path(file.filename or "test.jpg").suffix.lower()
        if extension not in self.dependencies.IMAGE_EXTS():
            extension = ".jpg"
        task_id = uuid.uuid4().hex[:12]
        prediction_dir = self.dependencies.project_dir(project_id) / "predictions" / task_id
        prediction_dir.mkdir(parents=True, exist_ok=True)
        input_path = prediction_dir / f"input{extension}"
        output_path = prediction_dir / "result.jpg"
        input_path.write_bytes(await file.read())
        if input_path.stat().st_size <= 0:
            raise HTTPException(status_code=400, detail="测试图片为空")
        batch_id = str(detection_batch_id or "").strip()
        if batch_id:
            if (
                len(batch_id) > 64
                or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in batch_id)
            ):
                raise HTTPException(status_code=400, detail="检测批次 ID 无效")
            if detection_item_index < 0 or detection_item_index >= 100000:
                raise HTTPException(status_code=400, detail="检测图片序号无效")
            if detection_item_total <= 0 or detection_item_total > 100000:
                raise HTTPException(status_code=400, detail="检测批次图片数量无效")
            side = str(detection_side or "").strip().upper()
            if side not in {"A", "B"}:
                raise HTTPException(status_code=400, detail="检测模型侧必须是 A 或 B")
        else:
            side = ""
        safe_original_name = Path(str(original_filename or file.filename or "test.jpg")).name[:255]
        task_model_sha256 = ""
        if algorithm_id and version_id and model_path and Path(model_path).is_file():
            task_model_sha256 = sha256_file(Path(model_path)).lower()
        request = {
            "model_path": model_path,
            "model_reference": model_reference,
            "model_reference_type": model_reference_type,
            "model_status": model_resolution.status,
            "downloadable": model_resolution.downloadable,
            "environment_status": model_resolution.environment_status,
            "input_path": str(input_path), "output_path": str(output_path),
            "input_image_url": self.dependencies._business_file_url(project_id, 'predictions', f'{task_id}/input{extension}'),
            "image_url": self.dependencies._business_file_url(project_id, 'predictions', f'{task_id}/result.jpg'),
            "framework": framework, "python_path": python_path,
            "runner_path": str(self.dependencies.BASE_DIR() / ("predict_paddle_runner.py" if framework == "paddle" else "predict_ultralytics_runner.py")),
            "conf": max(0.0, min(1.0, float(conf))), "runtime_format": suffix.lstrip("."),
            "model_identity": {
                "label": str(model_label or "").strip()[:300],
                "model_name": str(model_name or "").strip()[:300],
                "model_source": str(model_source or "project").strip()[:80],
                "algorithm_id": str(algorithm_id or "").strip()[:128],
                "version_id": str(version_id or "").strip()[:128],
                "model_sha256": task_model_sha256,
                "framework": framework,
                "runtime_format": suffix.lstrip("."),
            },
            "detection_batch": (
                {
                    "batch_id": batch_id,
                    "item_index": int(detection_item_index),
                    "item_total": int(detection_item_total),
                    "side": side,
                    "original_filename": safe_original_name,
                }
                if batch_id else None
            ),
        }
        if scenario_model is not None:
            request["model_scope"] = "scenario"
            request["scenario_model"] = {**scenario_model, "project_path": str(self.dependencies.project_dir(project_id).resolve())}
        try:
            remote_execution = self.dependencies._remote_execution_transport_service().stage_deployment_test(
                project_id=project_id,
                task_id=task_id,
                input_path=input_path,
                model_path=model_path,
                model_reference=model_reference,
                model_reference_type=model_reference_type,
                algorithm_id=algorithm_id,
                version_id=version_id,
                framework=framework,
                runtime_format=suffix.lstrip("."),
                confidence=max(0.0, min(1.0, float(conf))),
            )
        except RemoteExecutionTransportError as error:
            input_path.unlink(missing_ok=True)
            try:
                prediction_dir.rmdir()
            except OSError:
                pass
            raise PlatformError(
                code=error.code,
                message="远程部署准备失败",
                detail=str(error),
                solution="请检查模型资产对象存储、访问凭据和对象完整性后重试。",
                status_code=error.status_code,
            ) from error
        if remote_execution is not None:
            request["remote_execution"] = remote_execution
        if scenario_model is not None:
            from types import SimpleNamespace
            from platform_core.scenario_models import verify_scenario_request
            try:
                verify_scenario_request(SimpleNamespace(
                    task=SimpleNamespace(project_id=project_id),
                    repository=self.dependencies.shared_task_repository(), artifacts=self.dependencies.shared_task_artifacts(),
                ), request)
            except ScenarioModelUnavailable as error:
                input_path.unlink(missing_ok=True)
                try:
                    prediction_dir.rmdir()
                except OSError:
                    pass
                raise HTTPException(status_code=409, detail=f"SCENARIO_MODEL_INELIGIBLE: {error}") from error
        payload_ref = "scenario/request.json" if scenario_model is not None else "request.json"
        self.dependencies.shared_task_artifacts().atomic_write_json(task_id, payload_ref, request)
        record = self.dependencies.shared_task_repository().create(TaskRecord.new(
            task_id, project_id, TaskKind.DEPLOYMENT_TEST, payload_ref, f"deployment-runtime:{suffix}",
            required_capabilities=("deployment.runtime",),
        ))
        return JSONResponse(status_code=202, content=self.public_deployment_test(record))

    def get_deployment_creation(self, project_id: str, creation_id: str):
        from platform_core.deployment.scenario_preparation import creation_state
        self.dependencies.get_project(project_id)
        try:
            state, task = creation_state(self.dependencies.shared_task_repository(), self.dependencies.shared_task_artifacts(), project_id, creation_id)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        from platform_core.deployment.scenario_preparation import staged_creation
        staged = staged_creation(self.dependencies.shared_task_artifacts(), project_id, creation_id, self.dependencies.project_dir(project_id) / "predictions") if state == "NOT_CREATED" else None
        return {"creation_state": state, "task_id": task.task_id if task else None,
                "staged_input_available": staged is not None,
                "task": self.public_deployment_test(task) if task else None}

    async def recover_deployment_creation(self, project_id: str, creation_id: str):
        from platform_core.deployment.scenario_preparation import creation_state, staged_creation, recover_creation
        self.dependencies.get_project(project_id)
        repository, artifacts = self.dependencies.shared_task_repository(), self.dependencies.shared_task_artifacts()
        try:
            state, task = creation_state(repository, artifacts, project_id, creation_id)
            if state == "CREATED":
                return JSONResponse(status_code=202, content=self.public_deployment_test(task))
            if state != "NOT_CREATED":
                raise HTTPException(status_code=409, detail="创建结果仍待核验，请查询原请求")
            predictions = self.dependencies.project_dir(project_id) / "predictions"
            staged = staged_creation(artifacts, project_id, creation_id, predictions)
            if staged is None:
                raise HTTPException(status_code=404, detail="没有可恢复的原图")
            identity = staged[0]["model_identity"]
            with self.dependencies._algorithm_version_reference_fence(project_id, identity["algorithm_id"], identity["version_id"]):
                _, version = self.dependencies._algorithm_version_for_action(project_id, identity["algorithm_id"], identity["version_id"])
                from platform_core.algorithms import is_trainable_version
                if (not is_trainable_version(version, 'ultralytics') or version.get('trainable') is not True
                        or version.get('framework') != 'ultralytics'):
                    raise HTTPException(status_code=409, detail="SCENARIO_MODEL_INELIGIBLE: 模型版本不再符合资格")
                record = await asyncio.to_thread(recover_creation, repository, artifacts, project_id, creation_id, predictions)
            return JSONResponse(status_code=202, content=self.public_deployment_test(record))
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    def get_deployment_test(self, project_id: str, task_id: str):
        return self.public_deployment_test(self.dependencies._require_shared_task(project_id, task_id, TaskKind.DEPLOYMENT_TEST))

    def retry_deployment_test(self, project_id: str, task_id: str):
        from platform_core.deployment.scenario_preparation import creation_lock
        repository, artifacts = self.dependencies.shared_task_repository(), self.dependencies.shared_task_artifacts()
        with creation_lock(artifacts, task_id):
            parent = self.dependencies._require_shared_task(project_id, task_id, TaskKind.DEPLOYMENT_TEST)
            child = repository.get(task_id + '-prepare')
            failed = {TaskStatus.FAILED, TaskStatus.BLOCKED_BY_ENVIRONMENT, TaskStatus.BLOCKED_BY_HARDWARE, TaskStatus.CANCELLED}
            pending = 'deployment.input.pending' in parent.required_capabilities
            if parent.status in failed:
                if any(value is not None for value in (parent.process_pid, parent.process_create_time, parent.process_command_hash)):
                    from platform_core.task_runtime.process_control import ProcessIdentityMismatchError
                    if parent.process_pid is None or parent.process_create_time is None or not parent.process_command_hash:
                        raise HTTPException(status_code=409, detail="原检测进程身份不完整，请先核验，不能重复执行")
                    try:
                        process = ProcessController().inspect(self.dependencies._durable_process_identity(parent))
                        if ProcessController._execution_alive(process):
                            raise HTTPException(status_code=409, detail="原检测进程仍存活，请先停止并核验，不能重复执行")
                    except (ProcessLookupError, ProcessIdentityMismatchError):
                        pass  # exact old process is gone; an unrelated reused PID is never signalled
                    except PermissionError as error:
                        raise HTTPException(status_code=409, detail="无法确认原检测进程已退出，请先核验") from error
                if pending and child and child.status in {TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED}:
                    raise HTTPException(status_code=409, detail="原准备任务仍在收尾，请查询状态后安全重试")
                parent = repository.retry(task_id)
            elif parent.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
                raise HTTPException(status_code=409, detail="只有失败或取消的检测可以重试")
            if pending and child and child.status in failed:
                repository.retry(child.task_id)
            return self.public_deployment_test(parent)

    def cancel_deployment_test(self, project_id: str, task_id: str):
        self.dependencies._require_shared_task(project_id, task_id, TaskKind.DEPLOYMENT_TEST)
        repository = self.dependencies.shared_task_repository()
        task = repository.request_cancel(task_id)
        child = repository.get(task_id + "-prepare")
        if child and child.project_id == project_id and child.kind is TaskKind.DEPLOYMENT_PREPARE:
            repository.request_cancel(child.task_id)
        return self.public_deployment_test(task)

    def promote_deployment_test_to_feedback_evidence(self, project_id: str, task_id: str):
        """Create review evidence from one completed formal algorithm-version detection.

    This is intentionally explicit: running a model test never promotes data or
    writes annotation truth. The returned prediction_id can only enter the
    existing v63 human-review flow.
    """
        from platform_core.online_feedback import validate_prediction_evidence

        task = self.dependencies._require_shared_task(project_id, task_id, TaskKind.DEPLOYMENT_TEST)
        if task.status not in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS}:
            raise HTTPException(status_code=409, detail="只有真实检测成功后才能提交抽检反馈")

        artifacts = self.dependencies.shared_task_artifacts()
        request = artifacts.read_json(task.task_id, task.payload_ref, default={})
        result = artifacts.read_json(task.task_id, task.result_ref, default={}) if task.result_ref else {}
        if not isinstance(request, dict) or not isinstance(result, dict):
            raise HTTPException(status_code=409, detail="检测任务证据不完整，请重新检测")

        identity = request.get("model_identity") if isinstance(request.get("model_identity"), dict) else {}
        if str(identity.get("model_source") or "").lower() != "algorithm_version":
            raise HTTPException(status_code=409, detail="只有正式算法版本检测可以进入抽检反馈")
        algorithm_id = str(identity.get("algorithm_id") or "").strip()
        version_id = str(identity.get("version_id") or "").strip()
        if not algorithm_id or not version_id:
            raise HTTPException(status_code=409, detail="检测任务缺少正式算法版本身份")

        _algorithm, version = self.dependencies._algorithm_version_for_action(project_id, algorithm_id, version_id)
        model_sha256 = self.dependencies._online_feedback_version_model_sha256(version)
        task_model_sha256 = str(identity.get("model_sha256") or "").strip().lower()
        if not task_model_sha256 or task_model_sha256 != model_sha256.lower():
            raise HTTPException(
                status_code=409,
                detail="检测任务使用的模型与当前正式版本模型身份不一致，请重新检测",
            )

        source_input = Path(str(request.get("input_path") or ""))
        source_output = Path(str(result.get("output_path") or request.get("output_path") or ""))
        if not source_input.is_file() or source_input.stat().st_size <= 0:
            raise HTTPException(status_code=409, detail="检测原图证据不可用，请重新检测")
        if not source_output.is_file() or source_output.stat().st_size <= 0:
            raise HTTPException(status_code=409, detail="检测结果图片不可用，请重新检测")

        prediction_id = str(task.task_id)
        root = self.dependencies.project_dir(project_id) / "predictions"
        root.mkdir(parents=True, exist_ok=True)
        input_suffix = source_input.suffix.lower() if source_input.suffix.lower() in self.dependencies.IMAGE_EXTS() else ".jpg"
        evidence_input = root / f"{prediction_id}_input{input_suffix}"
        evidence_result = root / f"{prediction_id}_result.jpg"
        evidence_path = root / f"{prediction_id}.evidence.json"

        if evidence_path.is_file():
            evidence, _, _, _ = self.dependencies._online_prediction_evidence(project_id, prediction_id)
            return {
                "ok": True,
                "idempotent": True,
                "prediction_id": prediction_id,
                "feedback_eligible": True,
                "algorithm_id": evidence["algorithm_id"],
                "version_id": evidence["version_id"],
                "model_sha256": evidence["model_sha256"],
                "input_sha256": evidence["input_sha256"],
                "detections": list(evidence.get("detections") or []),
                "image_url": self.dependencies._business_file_url(project_id, 'predictions', evidence_result.name),
            }

        shutil.copy2(source_input, evidence_input)
        shutil.copy2(source_output, evidence_result)
        info = self.dependencies.image_info(evidence_input)
        evidence = validate_prediction_evidence({
            "schema_version": 1,
            "prediction_id": prediction_id,
            "project_id": project_id,
            "algorithm_id": algorithm_id,
            "version_id": version_id,
            "model_sha256": model_sha256,
            "input_sha256": sha256_file(evidence_input),
            "original_filename": self.dependencies.safe_filename(
                str((request.get("detection_batch") or {}).get("original_filename") or source_input.name)
            ),
            "input_file": evidence_input.name,
            "width": int(info["width"]),
            "height": int(info["height"]),
            "confidence": float(request.get("conf") or 0.25),
            "engine": str(result.get("engine") or request.get("framework") or "ultralytics"),
            "detections": list(result.get("detections") or []),
            "created_at": str(task.finished_at or self.dependencies.now_iso()),
            "source_channel": "quality_center_detection",
        })
        self.dependencies._register_prediction_files(project_id, prediction_id, evidence_input, evidence_result, evidence)
        return {
            "ok": True,
            "idempotent": False,
            "prediction_id": prediction_id,
            "feedback_eligible": True,
            "algorithm_id": algorithm_id,
            "version_id": version_id,
            "model_sha256": model_sha256,
            "input_sha256": evidence["input_sha256"],
            "detections": list(evidence.get("detections") or []),
            "image_url": self.dependencies._business_file_url(project_id, 'predictions', evidence_result.name),
        }
