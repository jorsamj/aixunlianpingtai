"""Durable preparation of the original scenario detection task, using its existing queue."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re

from filelock import FileLock, Timeout

from ..algorithms import list_algorithms
from ..task_runtime import TaskKind, TaskRecord, TaskStatus


def creation_task_id(project, creation_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", str(creation_id)):
        raise ValueError("检测创建身份无效")
    return "detect-" + hashlib.sha256(f"{project}:{creation_id}".encode()).hexdigest()[:32]


def creation_lock(artifacts, task_id, timeout=10):
    path = artifacts.artifact_path(task_id, "creation.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(path), timeout=timeout)


def accept_creation(repository, artifacts, project, creation_id, request, image, predictions):
    task_id = creation_task_id(project, creation_id)
    frozen = {**request, "input_sha256": hashlib.sha256(image).hexdigest(), "creation_id": creation_id}
    digest = hashlib.sha256(json.dumps(frozen, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with creation_lock(artifacts, task_id):
        return _accept_locked(repository, artifacts, project, creation_id, request, image, predictions, task_id, frozen, digest)


def _accept_locked(repository, artifacts, project, creation_id, request, image, predictions, task_id, frozen, digest):
    existing = repository.get(task_id)
    if existing is not None:
        stored = artifacts.read_json(task_id, existing.payload_ref, default={})
        if existing.project_id != project or stored.get("creation_digest") != digest:
            raise ValueError("CREATION_ID_CONFLICT: 相同创建身份对应不同图片、模型或参数")
        return existing
    if committed_evidence(repository, artifacts, task_id):
        raise ValueError("CREATION_HISTORY_UNKNOWN: 创建记录不完整，禁止重复创建")
    staged = artifacts.read_json(task_id, "scenario/request.json", default={})
    if staged and staged.get("creation_digest") != digest:
        raise ValueError("CREATION_ID_CONFLICT: 已暂存的创建身份对应不同内容")
    extension = request["input_extension"]
    folder = Path(predictions) / task_id
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / ("input" + extension)
    source.write_bytes(image)
    payload = {**request, "creation_id": creation_id, "creation_digest": digest,
               "input_sha256": frozen["input_sha256"], "input_path": str(source),
               "output_path": str(folder / "result.jpg"), "preparation_state": "PENDING",
               "preparation_task_id": task_id + "-prepare"}
    # The API supplies the existing canonical controlled URL contract.
    payload["input_image_url"] = request["input_url_template"].format(task_id=task_id, extension=extension)
    payload["image_url"] = request["output_url_template"].format(task_id=task_id)
    artifacts.atomic_write_json(task_id, "scenario/request.json", payload)
    artifacts.atomic_write_json(task_id + "-prepare", "request.json", {"parent_task_id": task_id})
    parent = replace(TaskRecord.new(task_id, project, TaskKind.DEPLOYMENT_TEST, "scenario/request.json",
                                   "deployment-runtime:.pt", required_capabilities=("deployment.input.pending",)),
                     stage="PREPARING_MODEL")
    child = TaskRecord.new(task_id + "-prepare", project, TaskKind.DEPLOYMENT_PREPARE, "request.json",
                           "deployment-prepare:" + task_id, required_capabilities=("deployment.prepare",))
    return repository.create_deployment_pair(parent, child)


def committed_evidence(repository, artifacts, task_id):
    return (repository.get(task_id + "-prepare") is not None
            or artifacts.artifact_path(task_id, "result.json").exists()
            or any(artifacts.artifact_path(task_id, "scenario").glob("prepared-*.json")))


def staged_creation(artifacts, project, creation_id, predictions):
    task_id = creation_task_id(project, creation_id)
    payload = artifacts.read_json(task_id, "scenario/request.json", default={})
    extension = payload.get("input_extension", "")
    if payload.get("creation_id") != creation_id or not re.fullmatch(r"\.[a-z0-9]{1,8}", extension):
        return None
    source = Path(predictions) / task_id / ("input" + extension)
    if not source.is_file() or not source.stat().st_size:
        return None
    return payload, source


def recover_creation(repository, artifacts, project, creation_id, predictions):
    task_id = creation_task_id(project, creation_id)
    with creation_lock(artifacts, task_id):
        existing = repository.get(task_id)
        if existing is not None:
            if existing.project_id != project or existing.kind is not TaskKind.DEPLOYMENT_TEST:
                raise PermissionError("检测请求身份不匹配")
            return existing
        staged = staged_creation(artifacts, project, creation_id, predictions)
        if staged is None:
            raise ValueError("没有可恢复的原图，请核验原请求")
        payload, source = staged
        keys = ("model_scope", "framework", "runtime_format", "python_path", "runner_path", "conf",
                "input_extension", "input_url_template", "output_url_template", "model_identity", "detection_batch")
        request = {key: payload[key] for key in keys}
        image = source.read_bytes()
        frozen = {**request, "input_sha256": hashlib.sha256(image).hexdigest(), "creation_id": creation_id}
        digest = hashlib.sha256(json.dumps(frozen, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if payload.get("creation_digest") != digest or payload.get("input_sha256") != frozen["input_sha256"]:
            raise ValueError("恢复原图或创建参数身份发生变化")
        return _accept_locked(repository, artifacts, project, creation_id, request, image, predictions, task_id, frozen, digest)

def creation_state(repository, artifacts, project, creation_id):
    task_id = creation_task_id(project, creation_id)
    task = repository.get(task_id)
    if task is not None:
        if task.project_id != project or task.kind is not TaskKind.DEPLOYMENT_TEST:
            raise PermissionError("检测请求身份不匹配")
        return "CREATED", task
    try:
        with creation_lock(artifacts, task_id, timeout=0):
            task = repository.get(task_id)
            return ("CREATED", task) if task is not None else (("UNKNOWN", None) if committed_evidence(repository, artifacts, task_id) else ("NOT_CREATED", None))
    except Timeout:
        return "CREATING", None


class ScenarioPreparationHandler:
    def __init__(self, data_dir, *, transport_factory=None):
        self.data_dir = Path(data_dir)
        self.transport_factory = transport_factory

    def _transport(self, context):
        if self.transport_factory:
            return self.transport_factory()
        from ..remote_execution_transport import RemoteExecutionTransportService
        from ..storage.source_repository import StorageSourceRepository
        from ..secrets import SecretCredentialStore, KeyringSecretStore
        sources = StorageSourceRepository(self.data_dir / "storage" / "storage_sources.sqlite3")
        credentials = SecretCredentialStore(KeyringSecretStore())
        return RemoteExecutionTransportService(data_dir=self.data_dir,
            project_dir=lambda project: self.data_dir / "projects" / project,
            algorithms_file=lambda project: self.data_dir / "projects" / project / "algorithms.json",
            storage_sources_factory=lambda: sources, storage_credentials_factory=lambda: credentials,
            task_artifacts=context.artifacts, task_repository=context.repository)

    def run(self, context):
        if not context.task.task_id.endswith("-prepare"):
            raise PermissionError("检测准备任务身份无效")
        target = context.task.task_id[:-len("-prepare")]
        def check():
            current = context.run_owned(lambda: context.repository.get(target))
            if context.cancel_requested() or current is None or current.status is not TaskStatus.QUEUED:
                raise InterruptedError("检测准备已停止")
        try:
            parent = context.run_owned(lambda: context.repository.get(target))
            if parent is None or parent.project_id != context.task.project_id:
                raise PermissionError("检测准备项目不匹配")
            if "deployment.input.pending" not in parent.required_capabilities:
                return TaskStatus.SUCCEEDED, None  # activation committed before a Worker restart
            link = context.artifacts.read_json(context.task.task_id, context.task.payload_ref)
            if link.get("parent_task_id") != target:
                raise PermissionError("检测准备任务关联错误")
            request = context.artifacts.read_json(target, parent.payload_ref)
            check()
            context.heartbeat(stage="PREPARING_MODEL", current_item="核验正式模型身份与内容")
            from ..scenario_models import resolve_scenario_model
            project = self.data_dir / "projects" / parent.project_id
            identity = request["model_identity"]
            algorithms = list_algorithms(project / "algorithms.json")
            algorithm = next(row for row in algorithms if row["id"] == identity["algorithm_id"])
            version = next(row for row in algorithm["versions"] if row["id"] == identity["version_id"])
            model = resolve_scenario_model(parent.project_id, project, algorithm, version,
                                           context.repository, context.artifacts)
            check()
            source = Path(request["input_path"])
            if hashlib.sha256(source.read_bytes()).hexdigest() != request["input_sha256"]:
                raise ValueError("检测原图身份发生变化")
            context.heartbeat(stage="PREPARING_INPUT", current_item="准备模型与图片的远程存储引用")
            remote = self._transport(context).stage_deployment_test(
                project_id=parent.project_id, task_id=target, input_path=source, model_path=model["path"],
                model_reference="", model_reference_type="", algorithm_id=identity["algorithm_id"],
                version_id=identity["version_id"], framework="ultralytics", runtime_format="pt", confidence=request["conf"])
            check()
            ready = {**request, "preparation_state": "READY", "model_path": model["path"],
                     "scenario_model": {**model, "project_path": str(project.resolve())},
                     "model_identity": {**identity, "model_sha256": model["model_sha256"]}}
            if remote is not None:
                ready["remote_execution"] = remote
            prepared_ref = f"scenario/prepared-{context.task.attempt}.json"
            context.artifacts.atomic_write_json(target, prepared_ref, ready)
            context.run_owned(lambda: context.repository.settle_deployment_preparation(target, context.lease, prepared_ref=prepared_ref))
            return TaskStatus.SUCCEEDED, None
        except InterruptedError:
            raise
        except Exception as error:
            from ..task_runtime import ExecutionFencedError
            if isinstance(error, ExecutionFencedError) or context.lease_lost:
                raise
            message = f"{getattr(error, 'code', type(error).__name__)}: {error}"
            context.run_owned(lambda: context.repository.settle_deployment_preparation(target, context.lease, error=message))
            raise

    recover = run
