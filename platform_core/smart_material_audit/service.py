"""Optional task admission over the original repositories and frozen selection."""
from __future__ import annotations

from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re

from filelock import FileLock

from . import require_enabled
from .contract import FEATURE
from ..material_repository import MaterialRepository
from ..material_selection import MaterialSelectionSpec, SelectionScope
from ..task_runtime import TaskKind, TaskRecord
from ..task_runtime.models import utc_now

OPERATION = "SMART_AUDIT"
CAPABILITY = "materials.smart_audit"


def reject(code, message, status=409):
    from ..material_batches import BatchRequestError
    raise BatchRequestError(code, message, status)


def configuration(data_dir):
    try:
        return require_enabled(data_dir)
    except (ValueError, OSError) as error:
        text = str(error)
        code = text.split(":", 1)[0] if text.startswith("SMART_AUDIT_") else "SMART_AUDIT_CONFIGURATION_INVALID"
        reject(code, text, 409 if code == "SMART_AUDIT_DISABLED" else 503)


def project_path(data_dir, project_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(project_id)):
        reject("SMART_AUDIT_PROJECT_INVALID", "项目身份无效", 422)
    projects = (Path(data_dir)/"projects").resolve()
    project = (projects/str(project_id)).resolve()
    if project.parent != projects:
        reject("SMART_AUDIT_PROJECT_INVALID", "项目路径无效", 422)
    return project


def _selection(data_dir, project_id, value, config):
    from ..material_batches import _predicate
    try:
        selection = MaterialSelectionSpec.from_mapping(value)
    except (TypeError, ValueError) as error:
        reject("SMART_AUDIT_SELECTION_INVALID", str(error), 422)
    if selection.scope is not SelectionScope.FILTERED and len(selection.image_ids) > config["max_images"]:
        reject("SMART_AUDIT_SCOPE_LIMIT", "显式选择超过已验证的分析上限",422)
    if len(selection.filters.labels) > 500 or len(selection.filters.storage_source_ids) > 500:
        reject("SMART_AUDIT_SELECTION_INVALID", "筛选条件数量超过500",422)
    materials = MaterialRepository.open_readonly(project_path(data_dir, project_id))
    clauses, params = _predicate(materials, selection)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with closing(materials._connect()) as database:
        database.execute("BEGIN")
        revision = materials._revision(database)
        count = int(database.execute("SELECT COUNT(*) FROM materials m"+where, params).fetchone()[0])
        if count > config["max_images"]:
            reject("SMART_AUDIT_SCOPE_LIMIT", f"当前范围{count}张，当前已验证分析上限{config['max_images']}张，请缩小选择；大库未验收", 422)
        ids = [str(row[0]) for row in database.execute("SELECT m.id FROM materials m"+where+" ORDER BY m.id", params)]
    return replace(selection, repository_revision=revision), ids


def estimate_audit(data_dir, project_id, selection):
    config = configuration(data_dir)
    frozen, ids = _selection(data_dir, project_id, selection, config)
    return {"operation": OPERATION, "count": len(ids), "total": len(ids), "max_images": config["max_images"],
            "selection_spec": frozen.as_dict(), "supported": True, "read_only": True, "feature": FEATURE}


def _options(value):
    if not isinstance(value, dict):
        reject("SMART_AUDIT_OPTIONS_INVALID", "options必须是对象", 422)
    unknown = set(value)-{"request_id", "threshold", "algorithm_id", "version_id"}
    if unknown:
        reject("SMART_AUDIT_OPTIONS_INVALID", "不支持客户端分析证据/字段："+", ".join(sorted(unknown)), 422)
    request_id = value.get("request_id")
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", request_id):
        reject("SMART_AUDIT_REQUEST_ID_REQUIRED", "必须提供可恢复的请求身份", 422)
    threshold = value.get("threshold", .4)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 < threshold < 2:
        reject("SMART_AUDIT_THRESHOLD_INVALID", "视觉特征距离阈值必须在0到2之间", 422)
    algorithm, version = str(value.get("algorithm_id") or ""), str(value.get("version_id") or "")
    if bool(algorithm) != bool(version) or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", v) for v in (algorithm,version) if v):
        reject("SMART_AUDIT_MODEL_INVALID", "模型算法与版本身份必须同时有效", 422)
    return {"request_id": request_id, "threshold": float(threshold), "algorithm_id": algorithm, "version_id": version}


def create_audit(data_dir, project_id, repository, artifacts, payload, *, actor):
    from ..material_batches import BatchSelection
    config = configuration(data_dir)
    if not isinstance(payload, dict) or set(payload)-{"selection_spec", "options"}:
        reject("SMART_AUDIT_REQUEST_INVALID", "分析请求字段无效", 422)
    options = _options(payload.get("options", {}))
    selection = MaterialSelectionSpec.from_mapping(payload.get("selection_spec"))
    if selection.repository_revision is None:
        reject("SMART_AUDIT_ESTIMATE_REQUIRED", "请先预览并确认本次分析范围")
    request = {"operation": OPERATION, "selection_spec": selection.as_dict(), "options": options,
               "actor_id": str((actor or {}).get("actor_id") or "")}
    task_id = "smart_" + hashlib.sha256(f"{project_id}:{options['request_id']}".encode()).hexdigest()[:32]
    request_path = artifacts.artifact_path(task_id, "request.json")
    request_path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(request_path)+".lock", timeout=5):
        existing = artifacts.read_json(task_id, "request.json", default=None)
        if existing is not None:
            if existing != request:
                reject("SMART_AUDIT_REQUEST_CONFLICT", "原请求身份已关联不同范围、参数或操作人")
            current = repository.get(task_id)
            if current is not None:
                if current.project_id != project_id or current.kind != TaskKind.MATERIAL_BATCH:
                    reject("SMART_AUDIT_REQUEST_CONFLICT", "原任务身份不一致")
                return current
        frozen, ids = _selection(data_dir, project_id, selection.as_dict(), config)
        if frozen.repository_revision != selection.repository_revision:
            reject("SMART_AUDIT_SELECTION_CHANGED", "素材已变化，请重新预览")
        if not ids:
            reject("SMART_AUDIT_EMPTY", "本次范围没有可分析素材", 422)
        with closing(BatchSelection(artifacts.artifact_path(task_id, "selection.sqlite3"))) as manifest:
            with manifest.transaction():
                manifest.database.execute("DELETE FROM selection")
                manifest.database.executemany("INSERT INTO selection(image_id) VALUES (?)", ((v,) for v in ids))
                manifest.database.executemany("INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)",
                    (("frozen", utc_now()), ("repository_revision", str(frozen.repository_revision))))
            artifacts.atomic_write_json(task_id, "checkpoints/worker.json", manifest.summary())
        artifacts.atomic_write_json(task_id, "request.json", request)
        task = TaskRecord.new(task_id, str(project_id), TaskKind.MATERIAL_BATCH, "request.json", f"materials:{project_id}",
            required_capabilities=("materials.batch", CAPABILITY))
        return repository.create(task, artifacts=artifacts)
