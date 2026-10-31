"""Durable material operations with selections frozen before queue publication."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import uuid
from contextlib import closing, nullcontext
from dataclasses import asdict, replace
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

from filelock import FileLock

from .annotation_repository import AnnotationRepository
from .annotation_quality import audit_cleaning_annotations
from .cleaning import DurableHashIndex, clean_options
from .cleaning import ImageDecodeError
from .cleaning_analysis_runtime import CleaningAnalysisRuntime
from .cleaning_batches import clean_batch, reset_stale_clean_successes
from .labels import active_project_label_ids, label_governance_fence
from .material_repository import (
    MATERIAL_BATCH_DELETE_CLAIM_FIELD,
    MaterialTaskInputConflictError,
    MaterialRepository,
    material_annotation_lifecycle_fence,
)
from .material_repository_batch import _transform_many
from .online_feedback import OnlineFeedbackRepository
from .material_selection import MaterialSelectionSpec, SelectionScope
from .materials import mark_ready
from .storage.errors import StorageError, redact_storage_error
from .storage.import_tasks import _provider
from .storage.manager import StorageManager
from .storage.source_repository import StorageSource, StorageSourceRepository
from .task_runtime import TaskKind, TaskRecord, TaskStatus, task_to_public
from .task_runtime.models import utc_now
from .task_runtime.task_logs import append_task_log

BATCH_SIZE = 500
REMAP_BATCH_SIZE = 100
MAX_REMAP_SELECTION = 100000
MAX_LARGE_EXPLICIT_SELECTION = 100000
SELECTION_REF = "selection.sqlite3"
CHECKPOINT_REF = "checkpoints/worker.json"
RESULT_REF = "result.json"
MATERIAL_INTEGRITY_REF = "material-integrity.sqlite3"
MATERIAL_INTEGRITY_PLAN_DIR = "dedup-plans"


class BatchOperation(str, Enum):
    MARK_CLEAN_SKIPPED = "MARK_CLEAN_SKIPPED"
    CLEAN = "CLEAN"
    DELETE_INDEX = "DELETE_INDEX"
    DELETE_SOURCE = "DELETE_SOURCE"
    ADD_LABELS = "ADD_LABELS"
    REMOVE_LABELS = "REMOVE_LABELS"
    REMAP_ANNOTATION_LABELS = "REMAP_ANNOTATION_LABELS"
    REPAIR_ANNOTATION_PROJECTIONS = "REPAIR_ANNOTATION_PROJECTIONS"
    AUDIT_LABEL_INTEGRITY = "AUDIT_LABEL_INTEGRITY"
    AUDIT_MATERIAL_INTEGRITY = "AUDIT_MATERIAL_INTEGRITY"
    AI_ANNOTATE = "AI_ANNOTATE"


NOT_READY = set()


class BatchRequestError(ValueError):
    def __init__(self, code, message, status_code=422):
        super().__init__(message)
        self.code, self.status_code = code, status_code


_MATERIAL_INTEGRITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_metadata (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS issue_items (
    group_key TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    content_sha256 TEXT NOT NULL DEFAULT '',
    image_id TEXT NOT NULL,
    details_json TEXT NOT NULL,
    PRIMARY KEY(group_key, image_id)
);
CREATE INDEX IF NOT EXISTS ix_material_integrity_items
    ON issue_items(issue_type, group_key, image_id);
CREATE INDEX IF NOT EXISTS ix_material_integrity_image
    ON issue_items(image_id, group_key);
CREATE TABLE IF NOT EXISTS issue_groups (
    group_key TEXT PRIMARY KEY,
    issue_type TEXT NOT NULL,
    content_sha256 TEXT NOT NULL DEFAULT '',
    image_count INTEGER NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_material_integrity_groups
    ON issue_groups(issue_type, group_key);
"""


_MATERIAL_INTEGRITY_PLAN_SCHEMA = """
CREATE TABLE IF NOT EXISTS plan_metadata (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plan_items (
    group_key TEXT NOT NULL,
    image_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('KEEP','DELETE')),
    content_sha256 TEXT NOT NULL,
    annotation_digest TEXT NOT NULL,
    PRIMARY KEY(group_key, image_id)
);
CREATE INDEX IF NOT EXISTS ix_material_integrity_plan_action
    ON plan_items(action, image_id);
CREATE TABLE IF NOT EXISTS plan_groups (
    group_key TEXT PRIMARY KEY,
    keeper_image_id TEXT NOT NULL,
    keeper_reason TEXT NOT NULL,
    delete_count INTEGER NOT NULL
);
"""


_MATERIAL_INTEGRITY_EXECUTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS integrity_plan_groups (
    group_key TEXT PRIMARY KEY,
    keeper_image_id TEXT NOT NULL,
    keeper_content_sha256 TEXT NOT NULL,
    keeper_annotation_digest TEXT NOT NULL,
    keeper_reason TEXT NOT NULL,
    delete_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS integrity_plan_items (
    image_id TEXT PRIMARY KEY,
    group_key TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    annotation_digest TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_integrity_plan_items_group
    ON integrity_plan_items(group_key, image_id);
"""


def _safe_project_path(data_dir, project_id):
    project = str(project_id or "").strip()
    if (
        not project
        or any(character in project for character in ("/", "\\"))
        or not all(character.isalnum() or character in {"_", "-"} for character in project)
    ):
        raise ValueError("project id must be one safe path component")
    projects_root = (Path(data_dir).resolve() / "projects").resolve()
    project_path = (projects_root / project).resolve()
    if project_path.parent != projects_root:
        raise ValueError("project id escaped projects root")
    return project, project_path


def parse_request(payload):
    if not isinstance(payload, dict):
        raise ValueError("material batch request must be an object")
    operation = BatchOperation(str(payload.get("operation") or "").upper())
    if operation is BatchOperation.AUDIT_LABEL_INTEGRITY:
        raise BatchRequestError(
            "LABEL_INTEGRITY_DEDICATED_PREPARE_REQUIRED",
            "标签完整性审计必须通过项目级专用入口创建，不能伪造普通素材 selection",
            422,
        )
    if operation is BatchOperation.REPAIR_ANNOTATION_PROJECTIONS:
        raise BatchRequestError(
            "LABEL_PREVIEW_REPAIR_DEDICATED_PREPARE_REQUIRED",
            "历史缩略图修复只能由已完成的标签完整性审计创建",
            422,
        )
    if operation is BatchOperation.AUDIT_MATERIAL_INTEGRITY:
        raise BatchRequestError(
            "MATERIAL_INTEGRITY_DEDICATED_PREPARE_REQUIRED",
            "素材完整性审计必须通过项目级专用入口创建，不能伪造普通素材 selection",
            422,
        )
    selection = MaterialSelectionSpec.from_mapping(payload.get("selection_spec"))
    explicit_limit = (
        MAX_LARGE_EXPLICIT_SELECTION
        if operation in {BatchOperation.CLEAN, BatchOperation.MARK_CLEAN_SKIPPED, BatchOperation.DELETE_INDEX}
        else BATCH_SIZE
    )
    if len(selection.image_ids) > explicit_limit:
        if explicit_limit == BATCH_SIZE:
            raise ValueError("explicit selection is limited to 500 IDs; use FILTERED for larger selections")
        raise ValueError(f"explicit selection is limited to {explicit_limit} IDs")
    if len(selection.filters.labels) > BATCH_SIZE or len(selection.filters.storage_source_ids) > BATCH_SIZE:
        raise ValueError("filter arrays are limited to 500 values")
    options = payload.get("options", {})
    if not isinstance(options, dict):
        raise ValueError("options must be an object")
    options = dict(options)
    if operation is BatchOperation.CLEAN:
        options = clean_options(options)
    if operation is BatchOperation.AI_ANNOTATE and int(options.get("preview_count") or 0):
        raise ValueError("AI batch processes the confirmed selection; use CURRENT_PAGE or SELECTED for a preview")
    if operation in {BatchOperation.ADD_LABELS, BatchOperation.REMOVE_LABELS}:
        labels = options.get("labels")
        if not isinstance(labels, list) or not labels or len(labels) > BATCH_SIZE:
            raise ValueError("options.labels must contain between 1 and 500 labels")
        if any(not isinstance(label, str) or not label.strip() for label in labels):
            raise ValueError("labels must be nonempty strings")
        options["labels"] = list(dict.fromkeys(label.strip() for label in labels))
    return operation, selection, options


def _predicate(materials, selection):
    if selection.scope is SelectionScope.FILTERED:
        return materials._filters(selection.filters)
    return ["m.id IN (" + ",".join("?" for _ in selection.image_ids) + ")"], list(selection.image_ids)


def _explicit_selection_count(database, image_ids, materials=None, filters=None):
    database.execute(
        "CREATE TEMP TABLE IF NOT EXISTS material_batch_explicit_selection ("
        "image_id TEXT PRIMARY KEY) WITHOUT ROWID"
    )
    database.execute("DELETE FROM material_batch_explicit_selection")
    database.executemany(
        "INSERT INTO material_batch_explicit_selection(image_id) VALUES (?)",
        ((str(image_id),) for image_id in image_ids),
    )
    clauses, params = materials._filters(filters) if materials is not None and filters is not None else ([], [])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return int(database.execute(
        "SELECT COUNT(*) FROM materials m "
        "JOIN material_batch_explicit_selection s ON s.image_id=m.id" + where,
        params,
    ).fetchone()[0])


def _confirmation_token(project_id, operation, selection, options):
    body = [project_id, operation.value, selection.as_dict(),
            {key: value for key, value in options.items() if key != "confirmation_token"}]
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return "DELETE_SOURCE:" + digest


def _assert_clear_authorization(options, actor, project):
    if not options.get('clear_project'):
        return
    if not actor or not actor.get('actor_id'):
        raise BatchRequestError('MATERIAL_CLEAR_SESSION_REQUIRED', '清空项目需要已核验的登录会话', 401)
    name = str((project or {}).get('name') or '')
    if not name or options.get('project_name_confirmation') != name:
        raise BatchRequestError('MATERIAL_CLEAR_NAME_CONFIRMATION_REQUIRED', '项目名称确认不一致', 409)


def _general_delete_preview(project_id, materials, selection, options, repository, artifacts, actor, project, *, owner_task_id=None):
    from .training_compatibility import _file_digest
    _assert_clear_authorization(options, actor, project)
    if options.get('clear_project') and (selection.scope is not SelectionScope.FILTERED or any(selection.filters.as_dict().values())):
        raise BatchRequestError('MATERIAL_CLEAR_SCOPE_INVALID', '清空项目必须选择未筛选的全部当前素材', 422)
    annotations = AnnotationRepository(materials.project_path)
    with label_governance_fence(materials.project_path), material_annotation_lifecycle_fence(materials.project_path):
        if materials.current_revision() != selection.repository_revision:
            raise BatchRequestError('BATCH_SELECTION_STALE', '素材范围已变化，请重新预览', 409)
        with closing(materials._connect()) as database:
            if selection.scope is SelectionScope.FILTERED:
                clauses, params = _predicate(materials, selection)
                where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
            else:
                _explicit_selection_count(database, selection.image_ids, materials, selection.filters)
                clauses, params = materials._filters(selection.filters)
                clauses.append('m.id IN (SELECT image_id FROM material_batch_explicit_selection)')
                where = ' WHERE ' + ' AND '.join(clauses)
            rows = [materials._row_payload(row) for row in database.execute('SELECT m.id,m.payload_json FROM materials m' + where + ' ORDER BY m.id', params)]
        records = {}
        for offset in range(0, len(rows), BATCH_SIZE):
            records.update(annotations.get_many([row['id'] for row in rows[offset:offset+BATCH_SIZE]]))
        plan_id, credential = uuid.uuid4().hex, secrets.token_urlsafe(32)
        owner_task_id = str(owner_task_id or plan_id)
        summary = {'plan_id':plan_id,'audit_task_id':owner_task_id,'project_id':str(project_id),
            'general_deletion':True,'actor_id':str((actor or {}).get('actor_id') or ''),
            'clear_project':bool(options.get('clear_project')),'project_name':str((project or {}).get('name') or ''),
            'selection_spec':selection.as_dict(),'scope':selection.scope.value,'operation':'DELETE_INDEX',
            'material_revision':materials.current_revision(),'annotation_revision':annotations.current_revision(),
            'label_schema_digest':_file_digest(materials.project_path/'meta.json'),
            'selected_count':len(rows),'delete_count':len(rows),'included_groups':0,'kept_count':0,
            'retained_count':0,'manual_required_count':0,'unverifiable_count':0,
            'skipped_groups':0,'skipped_item_count':0,'protected_item_count':0,'protected_groups':0,
            'manual_required_groups':0,'anomaly_groups':0,'anomaly_item_count':0,
            'skip_reasons':{},'protection_reason_counts':{},
            'gt_count':sum(int(records[row['id']].get('version') or 0)>0 for row in rows),
            'current_test_count':sum(str(row.get('split') or '').lower()=='test' for row in rows),
            'physical_retained_count':len(rows),'reclaimed_bytes':0,'reclamation_state':'DEFERRED_SAFETY_UNVERIFIED',
            'created_at':utc_now(),'execution_task_id':None,
            'credential_sha256':hashlib.sha256(credential.encode()).hexdigest()}
        # Reference evidence informs impact; it never authorizes physical deletion.
        try:
            references = _historical_material_references(project_id, materials.project_path, repository, artifacts, with_reasons=True)
            selected_ids = {row['id'] for row in rows}
            summary['historical_reference_count'] = len({key for key, values in references.items() if key in selected_ids and any(value.get('reason') not in {'ACTIVE_TASK_INPUT', 'CURRENT_TEST_ROLE'} for value in values)})
            summary['active_reference_count'] = len({key for key, values in references.items() if key in selected_ids and any(value.get('reason')=='ACTIVE_TASK_INPUT' and value.get('task_status') in {'RUNNING','CANCEL_REQUESTED'} for value in values)})
            summary['reference_diagnostics_state'] = 'COMPLETED'
        except (ValueError, OSError, sqlite3.Error, BatchRequestError):
            summary.update(historical_reference_count=None, active_reference_count=None, reference_diagnostics_state='UNAVAILABLE')
        path = artifacts.artifact_path(owner_task_id, _material_integrity_plan_ref(plan_id))
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as plan:
            plan.executescript(_MATERIAL_INTEGRITY_PLAN_SCHEMA)
            plan.executemany('INSERT INTO plan_metadata VALUES (?,?)', ((key,json.dumps(value,ensure_ascii=False,sort_keys=True)) for key,value in summary.items()))
            plan.executemany('INSERT INTO plan_items VALUES (?,?,?,?,?)',
                (('EXPLICIT_SELECTION',row['id'],'DELETE',str(row.get('content_sha256') or ''),annotations.record_digest(records[row['id']])) for row in rows))
            plan.commit()
    return {**{key:value for key,value in summary.items() if key!='credential_sha256'},
        'confirmation_credential':credential,
        'preview_items':_material_integrity_preview_items(project_id,materials,[row['id'] for row in rows[:20]]),
        'preview_groups':[], 'preview_groups_truncated':False}



def estimate_batch(project_id, materials, payload, *, repository=None, artifacts=None, actor=None, project=None):
    operation, selection, options = parse_request(payload)
    with closing(materials._connect()) as database:
        database.execute("BEGIN")
        revision = materials._revision(database)
        if selection.scope is SelectionScope.FILTERED:
            clauses, params = _predicate(materials, selection)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            count = int(database.execute("SELECT COUNT(*) FROM materials m" + where, params).fetchone()[0])
        else:
            count = _explicit_selection_count(
                database, selection.image_ids, materials, selection.filters,
            )
    confirmed_selection = replace(selection, repository_revision=revision)
    result = {"operation": operation.value, "count": count, "total": count,
              "repository_revision": revision, "revision": revision,
              "selection_spec": confirmed_selection.as_dict(), "supported": operation not in NOT_READY}
    if operation is BatchOperation.DELETE_SOURCE:
        result["confirmation_token"] = _confirmation_token(project_id, operation, confirmed_selection, options)
    if operation is BatchOperation.DELETE_INDEX and repository is not None and artifacts is not None:
        result['deletion_preview'] = _general_delete_preview(project_id, materials, confirmed_selection, options, repository, artifacts, actor, project)
    return result


def prepare_batch(project_id, materials, artifacts, payload, *, task_id=None):
    """Freeze a batch selection durably without publishing executable queue truth yet."""
    operation, selection, options = parse_request(payload)
    if operation is BatchOperation.AI_ANNOTATE:
        from .annotation_runtime import prepare_request
        options = prepare_request(materials.project_path.parent.parent, project_id, options, runtime=False)
    if selection.repository_revision is None:
        raise BatchRequestError("BATCH_ESTIMATE_REQUIRED", "estimate and provide selection_spec.repository_revision first", 409)
    if operation is BatchOperation.DELETE_SOURCE and options.get("confirmation_token") != _confirmation_token(
        project_id, operation, selection, options,
    ):
        raise BatchRequestError("DELETE_SOURCE_CONFIRMATION_REQUIRED", "confirm source deletion using the estimate confirmation_token", 409)
    task_id = str(task_id or uuid.uuid4().hex)
    request_payload = {
        "operation": operation.value,
        "selection_spec": selection.as_dict(),
        "options": options,
    }
    execution_mode = str(payload.get("execution_mode") or "").strip().lower()
    remote_execution = payload.get("remote_execution")
    scheduling = payload.get("scheduling")
    if scheduling is not None:
        if operation is not BatchOperation.CLEAN or not isinstance(scheduling, dict):
            raise BatchRequestError(
                "BATCH_SCHEDULING_INVALID",
                "node scheduling is supported only for CLEAN material batches",
                422,
            )
        scheduling_mode = str(scheduling.get("mode") or "auto").strip().lower()
        scheduling_node = str(scheduling.get("node_id") or "").strip()
        queue_policy = str(scheduling.get("queue_policy") or "normal").strip().lower()
        if scheduling_mode not in {"auto", "node"}:
            raise BatchRequestError("BATCH_SCHEDULING_INVALID", "cleaning scheduling mode must be auto or node", 422)
        if scheduling_mode == "auto" and (scheduling_node or queue_policy != "normal"):
            raise BatchRequestError("BATCH_SCHEDULING_INVALID", "automatic cleaning scheduling cannot pin a node or queue policy", 422)
        if scheduling_mode == "node" and (not scheduling_node or queue_policy not in {"normal", "front", "preempt"}):
            raise BatchRequestError("BATCH_SCHEDULING_INVALID", "manual cleaning scheduling requires node_id and a valid queue policy", 422)
        request_payload["scheduling"] = {
            "mode": scheduling_mode,
            "node_id": scheduling_node,
            "queue_policy": queue_policy,
        }
    if execution_mode or remote_execution is not None:
        if operation is not BatchOperation.CLEAN:
            raise BatchRequestError(
                "BATCH_REMOTE_EXECUTION_UNSUPPORTED",
                "remote execution is currently supported only for CLEAN material batches",
                422,
            )
        if execution_mode not in {"local", "agent"}:
            raise BatchRequestError(
                "BATCH_EXECUTION_MODE_INVALID",
                "cleaning execution_mode must be local or agent",
                422,
            )
        request_payload["execution_mode"] = execution_mode
        if execution_mode == "agent":
            if not isinstance(remote_execution, dict):
                raise BatchRequestError(
                    "BATCH_REMOTE_EXECUTION_REQUIRED",
                    "Agent cleaning requires an explicit portable remote_execution contract",
                    422,
                )
            request_payload["remote_execution"] = dict(remote_execution)
        elif remote_execution is not None:
            raise BatchRequestError(
                "BATCH_REMOTE_EXECUTION_INVALID",
                "local cleaning cannot publish a remote_execution contract",
                422,
            )
    required_capabilities = (
        ("agent.remote",)
        if operation is BatchOperation.CLEAN and request_payload.get("execution_mode") == "agent"
        else ("materials.batch",)
    )
    selection_path = artifacts.artifact_path(task_id, SELECTION_REF)
    existing_request = artifacts.read_json(task_id, "request.json", default=None)
    if existing_request is not None:
        if existing_request != request_payload:
            raise BatchRequestError("BATCH_TASK_ID_CONFLICT", "task id is already prepared for a different material batch", 409)
        with closing(BatchSelection(selection_path)) as manifest:
            if not manifest.frozen():
                raise BatchRequestError("BATCH_SELECTION_NOT_FROZEN", "prepared batch selection is incomplete", 409)
        return TaskRecord.new(
            task_id, project_id, TaskKind.MATERIAL_BATCH, "request.json",
            f"materials:{project_id}", required_capabilities=required_capabilities,
        )
    try:
        with closing(BatchSelection(selection_path)):
            pass
        with closing(materials._connect()) as database:
            database.execute("ATTACH DATABASE ? AS batch_selection", (str(selection_path),))
            database.execute("PRAGMA batch_selection.synchronous=FULL")
            database.execute("BEGIN IMMEDIATE")
            if materials._revision(database) != selection.repository_revision:
                raise BatchRequestError("MATERIAL_REVISION_CHANGED", "material repository changed; re-estimate before confirming", 409)
            if selection.scope is SelectionScope.FILTERED:
                clauses, params = _predicate(materials, selection)
                where = " WHERE " + " AND ".join(clauses) if clauses else ""
                inserted = database.execute(
                    "INSERT INTO batch_selection.selection(image_id) SELECT m.id FROM main.materials m" + where,
                    params,
                ).rowcount
            else:
                database.executemany(
                    "INSERT INTO batch_selection.selection(image_id) VALUES (?)",
                    ((str(image_id),) for image_id in selection.image_ids),
                )
                inserted = int(database.execute(
                    "SELECT COUNT(*) FROM batch_selection.selection s "
                    "JOIN main.materials m ON m.id=s.image_id"
                ).fetchone()[0])
                if inserted != len(selection.image_ids):
                    raise BatchRequestError("MATERIAL_SELECTION_CHANGED", "selected materials are missing; re-estimate before confirming", 409)
                clauses, params = materials._filters(selection.filters)
                if clauses:
                    database.execute(
                        "DELETE FROM batch_selection.selection WHERE image_id NOT IN ("
                        "SELECT m.id FROM main.materials m WHERE " + " AND ".join(clauses) + ")",
                        params,
                    )
                    inserted = int(database.execute(
                        "SELECT COUNT(*) FROM batch_selection.selection"
                    ).fetchone()[0])
            database.executemany(
                "INSERT INTO batch_selection.meta(key,value) VALUES (?,?)",
                (("frozen", utc_now()), ("repository_revision", str(selection.repository_revision))),
            )
            database.commit()
        artifacts.atomic_write_json(task_id, "request.json", request_payload)
        with closing(BatchSelection(selection_path)) as manifest:
            artifacts.atomic_write_json(task_id, CHECKPOINT_REF, manifest.summary())
        return TaskRecord.new(
            task_id, project_id, TaskKind.MATERIAL_BATCH, "request.json",
            f"materials:{project_id}", required_capabilities=required_capabilities,
        )
    except Exception as error:
        try:
            artifacts.atomic_write_json(task_id, "creation_failure.json", {
                "task_id": task_id, "status": "CREATION_FAILED", "error": redact_storage_error(error),
            })
        except Exception:
            pass
        if isinstance(error, BatchRequestError):
            raise
        raise BatchRequestError("BATCH_CREATION_FAILED", f"material batch creation failed: {redact_storage_error(error)}", 500) from error


def publish_prepared_batch(task, repository, artifacts):
    """Publish one previously frozen batch exactly once into TaskRepository."""
    existing = repository.get(task.task_id)
    if existing is not None:
        if existing.project_id != task.project_id or existing.kind is not TaskKind.MATERIAL_BATCH:
            raise BatchRequestError("BATCH_TASK_ID_CONFLICT", "task id is already owned by another durable task", 409)
        return existing
    request = artifacts.read_json(task.task_id, task.payload_ref, default=None)
    selection_path = artifacts.artifact_path(task.task_id, SELECTION_REF)
    if not isinstance(request, dict) or not selection_path.is_file():
        raise BatchRequestError("BATCH_NOT_PREPARED", "material batch artifacts are incomplete", 409)
    with closing(BatchSelection(selection_path)) as manifest:
        if not manifest.frozen():
            raise BatchRequestError("BATCH_SELECTION_NOT_FROZEN", "material batch selection is incomplete", 409)
    try:
        return repository.create(task, artifacts=artifacts)
    except Exception as error:
        if isinstance(error, BatchRequestError):
            raise
        raise BatchRequestError("BATCH_PUBLICATION_FAILED", f"material batch publication failed: {redact_storage_error(error)}", 500) from error


def create_batch(project_id, materials, repository, artifacts, payload, *, actor=None, project=None):
    operation, selection, options = parse_request(payload)
    if operation is BatchOperation.DELETE_SOURCE:
        raise BatchRequestError('PHYSICAL_DELETE_SAFETY_UNVERIFIED', '尚未证明物理回收安全，请使用逻辑删除保留源字节', 409)
    if operation is BatchOperation.DELETE_INDEX:
        plan_id = str(options.get('deletion_plan_id') or '')
        if not plan_id:
            raise BatchRequestError('BATCH_DELETE_PREVIEW_REQUIRED', '请先预览并确认服务端冻结的删除范围', 409)
        path = artifacts.artifact_path(plan_id, _material_integrity_plan_ref(plan_id))
        if not path.is_file():
            raise BatchRequestError('MATERIAL_INTEGRITY_PLAN_NOT_FOUND', '删除计划不存在', 404)
        with closing(sqlite3.connect(path)) as plan:
            metadata = _json_metadata(plan)
        if metadata.get('project_id') != str(project_id) or metadata.get('actor_id') != str((actor or {}).get('actor_id') or ''):
            raise BatchRequestError('MATERIAL_DELETE_ACTOR_CHANGED', '删除计划项目或操作人不一致', 403)
        if metadata.get('selection_spec') != selection.as_dict():
            raise BatchRequestError('MATERIAL_DELETE_SCOPE_CHANGED', '删除范围与预览不一致', 409)
        if metadata.get('clear_project'):
            _assert_clear_authorization({'clear_project':True,'project_name_confirmation':options.get('project_name_confirmation')}, actor, project)
            if metadata.get('project_name') != str((project or {}).get('name') or ''):
                raise BatchRequestError('MATERIAL_CLEAR_NAME_CHANGED', '项目名称已变化，请重新预览', 409)
        return execute_material_integrity_plan(project_id, SimpleNamespace(task_id=plan_id), plan_id,
            options.get('confirmation_credential'), materials, repository, artifacts, actor=actor)
    task = prepare_batch(project_id, materials, artifacts, payload)
    operation, _, _ = parse_request(payload)
    if operation is BatchOperation.DELETE_SOURCE:
        path = artifacts.artifact_path(task.task_id, SELECTION_REF)
        with closing(BatchSelection(path)) as manifest:
            rows = manifest.database.execute(
                "SELECT image_id FROM selection ORDER BY image_id"
            ).fetchall()
            image_ids = [str(row[0]) for row in rows]
        with material_annotation_lifecycle_fence(materials.project_path):
            _assert_not_referenced_by_active_tasks(
                project_id, image_ids, materials, repository, artifacts
            )
            return publish_prepared_batch(task, repository, artifacts)
    return publish_prepared_batch(task, repository, artifacts)


def create_material_integrity_audit(project_id, repository, artifacts):
    """Publish one project-level audit without inventing a material selection."""
    task_id = uuid.uuid4().hex
    request = {
        "operation": BatchOperation.AUDIT_MATERIAL_INTEGRITY.value,
        "audit_scope": "PROJECT",
    }
    checkpoint = {
        "total": None,
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "selection_frozen": False,
        "audit_ref": MATERIAL_INTEGRITY_REF,
    }
    artifacts.atomic_write_json(task_id, "request.json", request)
    artifacts.atomic_write_json(task_id, CHECKPOINT_REF, checkpoint)
    task = TaskRecord.new(
        task_id,
        str(project_id),
        TaskKind.MATERIAL_BATCH,
        "request.json",
        f"materials:{project_id}",
        required_capabilities=("materials.batch",),
    )
    return repository.create(task, artifacts=artifacts)


def _material_integrity_plan_ref(plan_id):
    value = str(plan_id or "").strip().lower()
    if len(value) != 32 or any(character not in "0123456789abcdef" for character in value):
        raise BatchRequestError(
            "MATERIAL_INTEGRITY_PLAN_INVALID", "素材治理计划编号无效", 404,
        )
    return f"{MATERIAL_INTEGRITY_PLAN_DIR}/{value}.sqlite3"


def _json_metadata(database):
    return {
        str(row[0]): json.loads(row[1])
        for row in database.execute(
            "SELECT key,value_json FROM plan_metadata"
        ).fetchall()
    }


def _audit_metadata(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
        return {
            str(row[0]): json.loads(row[1])
            for row in database.execute(
                "SELECT key,value_json FROM audit_metadata"
            ).fetchall()
        }


def _collect_known_image_ids(value, output=None):
    """Read only explicit image-id fields; arbitrary JSON strings are never paths."""
    output = output if output is not None else set()
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in {
                "image_id", "material_id", "source_image_id",
            } and isinstance(item, (str, int)):
                if str(item).strip():
                    output.add(str(item).strip())
            elif normalized in {
                "image_ids", "material_ids", "train_image_ids", "test_image_ids",
                "val_image_ids", "validation_image_ids",
                "selected_train_image_ids", "effective_train_image_ids",
                "pending_annotation_image_ids",
            } and isinstance(item, (list, tuple, set)):
                output.update(str(entry).strip() for entry in item if str(entry).strip())
            elif normalized in {"ids", "roles", "splits"} and isinstance(item, dict):
                for values in item.values():
                    if isinstance(values, (list, tuple, set)):
                        output.update(
                            str(entry).strip() for entry in values
                            if str(entry).strip()
                        )
            elif isinstance(item, (dict, list, tuple)):
                _collect_known_image_ids(item, output)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect_known_image_ids(item, output)
    return output


def _historical_material_references(
    project_id, project_path, repository, artifacts, *, exclude_task_id=None,
    with_reasons=False, reference_image_ids=None,
):
    """Conservatively preserve material inputs referenced by durable history."""
    protected = set()
    references = {}
    wanted = None if reference_image_ids is None else set(map(str, reference_image_ids))

    def preserve(image_ids, reason, source, *, is_protected=True, **evidence):
        if is_protected:
            protected.update(image_ids)
        if with_reasons:
            for image_id in image_ids:
                if wanted is None or image_id in wanted:
                    item = {"reason": reason, "source": source, "protected": is_protected, **evidence}
                    if item not in references.setdefault(image_id, []):
                        references[image_id].append(item)

    # A request is releasable only when all durable contracts prove that it
    # never reached materialization. Absence of input-freeze alone is not proof:
    # legacy execution/recovery can own a Snapshot, bundle or checkpoint.
    request_only = []
    dependent_tasks = set()

    def collect_task_dependencies(value, owner_task_id=None):
        if isinstance(value, dict):
            for key, item in value.items():
                if (str(key).lower() in {'task_id', 'retry_of'}
                        or str(key).lower().endswith('_task_id')) and isinstance(item, str):
                    if str(key).lower() != 'task_id' or item != owner_task_id:
                        dependent_tasks.add(item)
                elif (str(key).lower() == 'task_ids' or str(key).lower().endswith('_task_ids')) and isinstance(item, list):
                    dependent_tasks.update(str(task_id) for task_id in item if isinstance(task_id, (str, int)))
                elif isinstance(item, (dict, list)):
                    collect_task_dependencies(item, owner_task_id)
        elif isinstance(value, list):
            for item in value:
                collect_task_dependencies(item, owner_task_id)

    def has_payload_dependency(value):
        if isinstance(value, dict):
            for key, item in value.items():
                name = str(key).lower()
                if item and (name.endswith(('_ref', '_reference', '_path'))
                        or any(word in name for word in ('snapshot', 'checkpoint', 'recovery', 'retry', 'bundle', 'freeze', 'dependency', 'dependencies', 'manifest', 'artifact'))
                        or name in {'dataset_revision_id', 'training_lineage', 'evaluation', 'result', 'model_artifact'}):
                    return True
                if isinstance(item, (dict, list)) and has_payload_dependency(item):
                    return True
        elif isinstance(value, list):
            return any(has_payload_dependency(item) for item in value)
        return False

    def scan_error(error):
        raise BatchRequestError('MATERIAL_INTEGRITY_HISTORY_UNAVAILABLE',
            '历史任务依赖无法核验，已阻止自动治理：' + redact_storage_error(error), 409) from error

    cursor = None
    while True:
        page = repository.list(
            project_id=str(project_id),
            kinds=tuple(TaskKind),
            limit=100,
            cursor=cursor,
        )
        for task in page.items:
            if task.task_id == exclude_task_id:
                continue
            try:
                payload = artifacts.read_json(task.task_id, task.payload_ref, default=None)
                if task.kind in (TaskKind.TRAINING, TaskKind.MODEL_CONVERSION) and not isinstance(payload, dict):
                    raise ValueError('historical task payload is missing or invalid')
            except (OSError, ValueError, TypeError) as error:
                raise BatchRequestError('MATERIAL_INTEGRITY_HISTORY_UNAVAILABLE',
                    '历史任务依赖无法核验，已阻止自动治理：' + redact_storage_error(error), 409) from error
            # A failed PREPARE child's bare ownership link is not recovery;
            # materialized or unknown output on that child still protects it.
            preparation_request_only = False
            if task.kind is TaskKind.TRAINING_PREPARE and task.status is TaskStatus.FAILED:
                preparation_request_only = not (task.result_ref or task.retry_of or has_payload_dependency(payload))
                preparation_root = artifacts.artifact_path(task.task_id, '.')
                for root, dirs, files in os.walk(preparation_root, onerror=scan_error):
                    if any((Path(root) / name).is_symlink() for name in dirs):
                        preparation_request_only = False
                    for name in files:
                        path = Path(root) / name
                        if path.is_symlink() or path.relative_to(preparation_root).as_posix() not in {task.payload_ref, task.log_ref}:
                            preparation_request_only = False
            if not preparation_request_only:
                collect_task_dependencies(payload, task.task_id)
            if task.retry_of:
                dependent_tasks.add(str(task.retry_of))
            if task.kind not in (TaskKind.TRAINING, TaskKind.MODEL_CONVERSION):
                continue
            freeze = artifacts.read_json(task.task_id, "input-freeze.json", default={})
            freeze_present = artifacts.artifact_path(task.task_id, "input-freeze.json").is_file()
            reason = (
                "ACTIVE_TASK_INPUT" if task.status in _ACTIVE_INPUT_STATUSES else
                "MODEL_CONVERSION_HISTORY" if task.kind == TaskKind.MODEL_CONVERSION else
                "TRAINING_FAILED_WITH_FREEZE" if task.status == TaskStatus.FAILED and freeze_present else
                "TRAINING_FAILED_NO_FREEZE" if task.status == TaskStatus.FAILED else
                "TRAINING_COMPLETED_HISTORY" if task.status == TaskStatus.SUCCEEDED else
                "TRAINING_HISTORY"
            )
            evidence = {
                "task_id": task.task_id, "task_kind": task.kind.value,
                "task_status": task.status.value, "freeze_present": freeze_present,
                "evidence_status": "recorded_not_revalidated" if freeze_present else "payload_reference_only",
            }
            payload_ids = _collect_known_image_ids(payload)
            if task.kind is TaskKind.TRAINING and task.status is TaskStatus.FAILED and not freeze_present:
                dependency = bool(
                    not isinstance(payload, dict) or has_payload_dependency(payload)
                    or task.result_ref or task.retry_of or task.attempt
                    or task.process_pid or task.process_create_time or task.process_command_hash
                    or str(payload.get('training_input_state') or '').upper() == 'READY'
                )
                task_root = artifacts.artifact_path(task.task_id, '.')
                allowed = {task.payload_ref, task.log_ref}
                # cleanup_task() creates this exact synchronization lock even
                # for NO_OBJECTS. The ledger itself and every other lock/output
                # remain durable evidence; symlink checks below still apply.
                allowed.add('remote-material/staging-cleanup.json.lock')
                preparation_error = artifacts.read_json(task.task_id, 'input-preparation-error.json', default=None)
                diagnostic_only = bool(isinstance(preparation_error, dict)
                    and preparation_error.get('task_id') == task.task_id
                    and preparation_error.get('project_id') == str(project_id)
                    and preparation_error.get('input_freeze_created') is False
                    and preparation_error.get('stage') == 'training_input_preparation_failed'
                    and not has_payload_dependency({key: value for key, value in preparation_error.items() if key != 'issues_ref'})
                    and preparation_error.get('issues_ref') in (None, '', 'input-compatibility/manifest.json'))
                if diagnostic_only:
                    allowed.add('input-preparation-error.json')
                    manifest = artifacts.read_json(task.task_id, 'input-compatibility/manifest.json', default=None)
                    if (isinstance(manifest, dict) and isinstance(manifest.get('pages'), list)
                            and not has_payload_dependency({key: value for key, value in manifest.items() if key != 'pages'})):
                        allowed.add('input-compatibility/manifest.json')
                        for diagnostic_page in manifest['pages']:
                            ref = str(diagnostic_page.get('ref') or '') if isinstance(diagnostic_page, dict) else ''
                            if ref.startswith('input-compatibility/pages/') and ref.endswith('.json'):
                                artifacts.artifact_path(task.task_id, ref)
                                rows = artifacts.read_json(task.task_id, ref, default=None)
                                if (isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
                                        and not has_payload_dependency(rows)):
                                    allowed.add(ref)
                for root, dirs, files in os.walk(task_root, onerror=scan_error):
                    if any((Path(root) / name).is_symlink() for name in dirs):
                        dependency = True
                    for name in files:
                        path = Path(root) / name
                        ref = path.relative_to(task_root).as_posix()
                        if path.is_symlink() or ref not in allowed:
                            dependency = True
                            if path.suffix.lower() == '.json':
                                document = artifacts.read_json(task.task_id, ref, default=None)
                                preserve(_collect_known_image_ids(document), 'TRAINING_FAILED_DURABLE_DEPENDENCY', ref, **evidence)
                if not dependency:
                    request_only.append((task, payload_ids, evidence))
                else:
                    preserve(payload_ids, 'TRAINING_FAILED_DURABLE_DEPENDENCY', 'task_payload', **evidence)
            else:
                preserve(payload_ids, reason, "task_payload", **evidence)
            preserve(_collect_known_image_ids(freeze), reason, "input_freeze", **evidence)
        cursor = page.next_cursor
        if not cursor:
            break

    active_kinds = (
        TaskKind.TRAINING_PREPARE, TaskKind.AI_ANNOTATION,
        TaskKind.MATERIAL_IMPORT, TaskKind.CLEANING, TaskKind.MATERIAL_BATCH,
    )
    cursor = None
    while True:
        page = repository.list(
            project_id=str(project_id), kinds=active_kinds,
            statuses=_ACTIVE_INPUT_STATUSES, limit=100, cursor=cursor,
        )
        for task in page.items:
            if task.task_id == exclude_task_id:
                continue
            preserve(_collect_known_image_ids(
                artifacts.read_json(task.task_id, task.payload_ref, default={})
            ), "ACTIVE_TASK_INPUT", "task_payload", task_id=task.task_id,
                task_kind=task.kind.value, task_status=task.status.value)
            selection_path = artifacts.artifact_path(task.task_id, SELECTION_REF)
            if selection_path.is_file():
                with closing(sqlite3.connect(
                    selection_path.as_uri() + "?mode=ro", uri=True
                )) as selection:
                    if selection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='selection'"
                    ).fetchone():
                        preserve({
                            str(row[0]) for row in selection.execute(
                                "SELECT image_id FROM selection"
                            ).fetchall()
                        }, "ACTIVE_TASK_INPUT", "frozen_selection", task_id=task.task_id,
                            task_kind=task.kind.value, task_status=task.status.value)
        cursor = page.next_cursor
        if not cursor:
            break

    snapshots = (Path(project_path) / "snapshots").resolve()
    if snapshots.is_dir() and snapshots.parent == Path(project_path).resolve():
        for path in snapshots.rglob("*.json"):
            try:
                if snapshots not in path.resolve().parents:
                    continue
                snapshot = json.loads(path.read_text(encoding="utf-8"))
                collect_task_dependencies(snapshot)
                all_ids = _collect_known_image_ids(snapshot)
                test_ids = set(map(str, snapshot.get("test_image_ids") or [])) if isinstance(snapshot, dict) else set()
                if isinstance(snapshot, dict):
                    for key in ("ids", "roles", "splits"):
                        roles = snapshot.get(key) or {}
                        if isinstance(roles, dict) and isinstance(roles.get("test"), list):
                            test_ids.update(map(str, roles["test"]))
                source = path.relative_to(snapshots).as_posix()
                preserve(all_ids - test_ids, "IMMUTABLE_SNAPSHOT", source)
                preserve(all_ids & test_ids, "FROZEN_TEST_SNAPSHOT", source)
            except (OSError, ValueError, TypeError) as error:
                raise BatchRequestError(
                    "MATERIAL_INTEGRITY_HISTORY_UNAVAILABLE",
                    "历史素材快照无法核验，已阻止自动治理："
                    + redact_storage_error(error),
                    409,
                ) from error
    try:
        from .algorithms import list_algorithms
        algorithms = list_algorithms(Path(project_path) / "algorithms.json")
        collect_task_dependencies(algorithms)
        preserve(_collect_known_image_ids(algorithms), "MODEL_OR_EVALUATION_HISTORY", "algorithm_versions")
    except Exception as error:
        raise BatchRequestError(
            "MATERIAL_INTEGRITY_MODEL_HISTORY_UNAVAILABLE",
            "模型版本与独立评测引用无法核验，已阻止自动治理："
            + redact_storage_error(error),
            409,
        ) from error
    for task, image_ids, evidence in request_only:
        referenced = task.task_id in dependent_tasks
        preserve(image_ids,
            'TRAINING_FAILED_DURABLE_DEPENDENCY' if referenced else 'TRAINING_FAILED_REQUEST_ONLY',
            'task_payload', is_protected=referenced,
            **{**evidence, 'evidence_status': 'dependent_history' if referenced else 'request_only_provenance_retained'},
        )
    return references if with_reasons else protected


def _material_integrity_keeper(items, protected_ids, manual_keeper=None):
    ids = {str(item["image_id"]) for item in items}
    if manual_keeper:
        keeper = str(manual_keeper)
        if keeper not in ids:
            raise BatchRequestError(
                "MATERIAL_INTEGRITY_KEEPER_INVALID",
                "人工保留项不属于所选重复组", 422,
            )
        return keeper

    def score(item):
        details = item["details"]
        annotation_state = str(details.get("annotation_state") or "")
        return (
            int(str(item["image_id"]) in protected_ids),
            int(bool(details.get("storage_source_id"))),
            int(annotation_state in {"annotated", "confirmed_empty"}),
            int(str(details.get("processing_status") or "").lower() in {"ready", "processed", "completed"}),
            int(bool(details.get("import_batch_id"))),
            # Stable lexical identity is the final deterministic tie breaker.
            str(item["image_id"]),
        )

    return max(items, key=score)["image_id"]


def _material_integrity_preview_items(project_id, materials, ids):
    annotations = AnnotationRepository(materials.project_path).get_many(ids)
    return [dict(
        image_id=str(row['id']), filename=row.get('filename') or str(row['id']),
        content_sha256=str(row.get('content_sha256') or ''),
        width=int(row.get('width') or 0), height=int(row.get('height') or 0),
        content_url=f"/api/v61/projects/{project_id}/materials/{row['id']}/content",
        annotation_state=(annotations.get(str(row['id'])) or {}).get('annotation_state') or 'unannotated',
        annotation_scope=list((annotations.get(str(row['id'])) or {}).get('annotation_scope') or []),
        boxes=list((annotations.get(str(row['id'])) or {}).get('boxes') or []),
    ) for row in materials.get_many(ids)]


def _material_integrity_import_evidence(project_id, rows, repository, artifacts, evidence=None):
    """Read bounded, non-secret provenance from the existing import Task Owner."""
    from .training_compatibility import annotation_import_batches

    evidence = {} if evidence is None else evidence
    for row in rows:
        for task_id in annotation_import_batches(row):
            if task_id not in evidence:
                task = repository.get(task_id)
                evidence[task_id] = {'verified_task_owner': False, 'status': 'UNVERIFIED'}
                if task is None or task.project_id != project_id or task.kind is not TaskKind.MATERIAL_IMPORT:
                    continue
                try:
                    confirmation = artifacts.read_json(task_id, 'scan/confirmation.json', default=None)
                except (OSError, ValueError, TypeError):
                    evidence[task_id]['status'] = 'CONFIRMATION_UNREADABLE'
                    continue
                if isinstance(confirmation, dict) and confirmation.get('accepted') is True:
                    evidence[task_id] = {'verified_task_owner': True, 'status': 'CONFIRMED_IMPORT_OWNER',
                        'external_classes': confirmation.get('external_classes') or [],
                        'label_mapping': confirmation.get('label_mapping') or {}, 'members': {}, 'checked_hashes': set()}
            current = evidence[task_id]
            sha = str(row.get('content_sha256') or '')
            if not current.get('verified_task_owner') or sha in current['checked_hashes']:
                continue
            current['checked_hashes'].add(sha)
            try:
                from .storage.import_candidates import ImportCandidateStore
                manifest = ImportCandidateStore.read_annotation_provenance(
                    artifacts.artifact_path(task_id, 'scan/candidates.sqlite3'), sha)
            except (OSError, ValueError, TypeError, sqlite3.Error):
                current['status'] = 'MANIFEST_UNVERIFIED'
                continue
            if manifest and manifest['label_mapping'] == current['label_mapping'] and manifest['external_classes'] == current['external_classes']:
                current['members'].update(manifest['members'])
    return evidence


def create_material_integrity_plan(
    project_id, audit_task, materials, repository, artifacts, payload,
    *, candidate_image_ids=None, persist=True, actor=None,
):
    from .training_compatibility import _file_digest
    if audit_task.status is not TaskStatus.SUCCEEDED:
        raise BatchRequestError(
            "MATERIAL_INTEGRITY_AUDIT_NOT_READY",
            "素材完整性审计尚未成功完成", 409,
        )
    payload = payload if isinstance(payload, dict) else {}
    scope = str(payload.get("scope") or "SAFE_ALL").strip().upper()
    if scope not in {"SAFE_ALL", "SELECTED_GROUPS", "MANUAL_GROUPS", "FILTERED", "SELECTED_IMAGES", "DISCARD_CONFLICTS"}:
        raise BatchRequestError(
            "MATERIAL_INTEGRITY_PLAN_SCOPE_INVALID", "素材治理范围无效", 422,
        )
    for name in ('group_keys', 'image_ids', 'excluded_image_ids', 'excluded_group_keys'):
        values = payload.get(name) or []
        if not isinstance(values, list) or len(values) > 10000 or any(not isinstance(value, (str, int)) for value in values):
            raise BatchRequestError('MATERIAL_INTEGRITY_SELECTION_INVALID', '选择范围必须是最多 10000 项的标识列表', 422)
    group_keys = list(dict.fromkeys(
        str(value).strip() for value in (payload.get("group_keys") or [])
        if str(value).strip()
    ))
    if scope in {"SELECTED_GROUPS", "MANUAL_GROUPS"} and not group_keys:
        raise BatchRequestError(
            "MATERIAL_INTEGRITY_GROUPS_REQUIRED", "请选择需要治理的重复组", 422,
        )
    if scope == "DISCARD_CONFLICTS" and payload.get("confirm_discard_conflicts") is not True:
        raise BatchRequestError(
            "MATERIAL_INTEGRITY_DISCARD_CONFIRMATION_REQUIRED",
            "放弃冲突组需要明确确认；删除只涉及可删索引及标注，历史和 Test 保持保护", 422,
        )
    if len(group_keys) > 10000:
        raise BatchRequestError(
            "MATERIAL_INTEGRITY_GROUPS_TOO_MANY", "一次最多选择 10000 个重复组", 422,
        )
    decisions = payload.get("manual_decisions") or {}
    if not isinstance(decisions, dict):
        raise BatchRequestError(
            "MATERIAL_INTEGRITY_DECISIONS_INVALID", "人工保留决策格式无效", 422,
        )

    selected_images = set(str(value) for value in (
        candidate_image_ids if candidate_image_ids is not None else (payload.get("image_ids") or [])
    ))
    excluded_images = set(str(value) for value in (payload.get('excluded_image_ids') or []))
    excluded_groups = set(str(value) for value in (payload.get('excluded_group_keys') or []))
    if max(len(excluded_images), len(excluded_groups)) > 10000:
        raise BatchRequestError('MATERIAL_INTEGRITY_SELECTION_INVALID', '排除范围过大，请缩小筛选范围', 422)
    if candidate_image_ids is not None:
        scope = 'SELECTED_IMAGES'
    if scope == "SELECTED_IMAGES" and (not selected_images or (candidate_image_ids is None and len(selected_images) > 10000)):
        raise BatchRequestError("MATERIAL_INTEGRITY_SELECTION_INVALID", "请选择 1–10000 张素材", 422)
    issue_type = str(payload.get("issue_type") or "").upper()
    issue_types = {"DUPLICATE_IDENTICAL", "DUPLICATE_ANNOTATION_CONFLICT",
                   "MATERIAL_OBJECT_MISSING", "CONTENT_HASH_MISMATCH",
                   "INVALID_IMAGE", "MATERIAL_SCAN_UNVERIFIED"}
    if issue_type and issue_type not in issue_types:
        raise BatchRequestError("MATERIAL_INTEGRITY_FILTER_INVALID", "问题筛选无效", 422)

    audit_path = artifacts.artifact_path(audit_task.task_id, MATERIAL_INTEGRITY_REF)
    if not audit_path.is_file():
        raise BatchRequestError(
            "MATERIAL_INTEGRITY_AUDIT_UNAVAILABLE", "素材完整性审计结果不可用", 409,
        )
    metadata = _audit_metadata(audit_path)
    annotations = AnnotationRepository(materials.project_path)
    material_revision = materials.current_revision()
    annotation_revision = annotations.current_revision()
    if (
        int(metadata.get("material_revision") or -1) != material_revision
        or int(metadata.get("annotation_revision") or -1) != annotation_revision
        or metadata.get('label_schema_digest') != _file_digest(materials.project_path / 'meta.json')
    ):
        raise BatchRequestError(
            "MATERIAL_INTEGRITY_AUDIT_STALE",
            "素材或标注已变化，请重新运行完整性审计", 409,
        )

    try:
        reference_reasons = _historical_material_references(
            project_id, materials.project_path, repository, artifacts, with_reasons=True)
        reference_diagnostics_state = 'COMPLETED'
    except (ValueError, OSError, sqlite3.Error, BatchRequestError):
        # Unknown history cannot make current identities immortal. Bytes are
        # retained unconditionally, so uncertainty still cannot authorize GC.
        reference_reasons, reference_diagnostics_state = {}, 'UNAVAILABLE'
    # References remain impact evidence; current identity deletion retains bytes.
    protected = set()
    for reasons in reference_reasons.values():
        for reason in reasons:
            reason['protected'] = False
    review_basis = payload.get('review_basis')
    if review_basis is not None:
        from .training_compatibility import _file_digest
        if (not isinstance(review_basis, dict) or review_basis.get('confirmed_all_filtered') is not True
                or not isinstance(review_basis.get('import_batch_id'), str) or not review_basis['import_batch_id']
                or len(review_basis['import_batch_id']) > 200):
            raise BatchRequestError('GT_REVIEW_CONFIRMATION_REQUIRED', '请明确核对来源批次及全部筛选范围后确认', 422)
        if (review_basis.get('annotation_revision') != annotation_revision
                or review_basis.get('material_revision') != material_revision
                or metadata.get('label_schema_digest') != _file_digest(materials.project_path / 'meta.json')):
            raise BatchRequestError('MATERIAL_INTEGRITY_AUDIT_STALE', '审核版本已变化，请重新审计', 409)
        scope, group_keys, decisions = 'MANUAL_GROUPS', [], {}
        observation = str(review_basis.get('observation') or '')
        review_group_count = 0
        with closing(sqlite3.connect(audit_path.as_uri() + '?mode=ro', uri=True)) as review:
            review.row_factory = sqlite3.Row
            candidates = review.execute("SELECT g.group_key,g.details_json,i.image_id,COUNT(*) AS candidates "
                "FROM issue_groups g JOIN issue_items i ON i.group_key=g.group_key "
                "WHERE g.issue_type='DUPLICATE_ANNOTATION_CONFLICT' "
                "AND json_extract(i.details_json,'$.import_batch_id')=? "
                "GROUP BY g.group_key", (review_basis['import_batch_id'],)).fetchall()
            for row in candidates:
                diagnosis = json.loads(row['details_json']).get('gt_diagnosis') or {}
                if observation and observation != diagnosis.get('cohort') and observation not in diagnosis.get('observations', []):
                    continue
                review_group_count += 1
                if row['candidates'] != 1 or row['image_id'] not in diagnosis.get('verified_source_image_ids', []):
                    continue
                group_keys.append(row['group_key'])
                decisions[row['group_key']] = row['image_id']
        if not group_keys:
            raise BatchRequestError('GT_REVIEW_NO_UNIQUE_SOURCE', '没有可唯一定位该来源GT的组；请逐组人工核对', 409)
        review_basis = {'kind': 'HUMAN_CONFIRMED_SOURCE_NOT_AUTOMATIC_GT_TRUTH',
            'import_batch_id': review_basis['import_batch_id'], 'observation': observation,
            'confirmed_group_count': len(group_keys), 'annotation_revision': annotation_revision,
            'filtered_group_count': review_group_count, 'unverified_or_ambiguous_group_count': review_group_count - len(group_keys),
            'material_revision': material_revision}
    with closing(sqlite3.connect(audit_path.as_uri() + "?mode=ro", uri=True)) as audit:
        audit.row_factory = sqlite3.Row
        duplicate_types = ("DUPLICATE_IDENTICAL", "DUPLICATE_ANNOTATION_CONFLICT")
        params = list(duplicate_types)
        where = "g.issue_type IN (?,?)"
        join = ""
        if scope in {"FILTERED", "SELECTED_IMAGES", "SELECTED_GROUPS"}:
            where, params = "1=1", []
        if scope == "FILTERED" and issue_type:
            where, params = "g.issue_type=?", [issue_type]
        if scope == 'FILTERED' and payload.get('group_key'):
            where += ' AND g.group_key=?'
            params.append(str(payload['group_key']))
        if scope == "SELECTED_IMAGES":
            audit.execute("CREATE TEMP TABLE selected_images(image_id TEXT PRIMARY KEY) WITHOUT ROWID")
            audit.executemany("INSERT INTO selected_images VALUES (?)", ((value,) for value in selected_images))
            where = "EXISTS (SELECT 1 FROM issue_items i JOIN selected_images s ON s.image_id=i.image_id WHERE i.group_key=g.group_key)"
            found = audit.execute("SELECT COUNT(DISTINCT i.image_id) FROM issue_items i JOIN selected_images s ON s.image_id=i.image_id").fetchone()[0]
            if found != len(selected_images):
                raise BatchRequestError("MATERIAL_INTEGRITY_SELECTION_INVALID", "所选图片不属于当前审计", 409)
        if scope in {"SELECTED_GROUPS", "MANUAL_GROUPS"} or (scope == "DISCARD_CONFLICTS" and group_keys):
            audit.execute(
                "CREATE TEMP TABLE selected_integrity_groups "
                "(group_key TEXT PRIMARY KEY) WITHOUT ROWID"
            )
            audit.executemany(
                "INSERT INTO selected_integrity_groups(group_key) VALUES (?)",
                ((group_key,) for group_key in group_keys),
            )
            join = " JOIN selected_integrity_groups s ON s.group_key=g.group_key"
        if scope == "DISCARD_CONFLICTS":
            where, params = "1=1", []
        groups = audit.execute(
            f"SELECT g.group_key,g.issue_type FROM issue_groups g{join} "
            f"WHERE {where} ORDER BY g.group_key",
            params,
        ).fetchall()
        if (scope in {"SELECTED_GROUPS", "MANUAL_GROUPS"} or (scope == "DISCARD_CONFLICTS" and group_keys)) and len(groups) != len(group_keys):
            raise BatchRequestError(
                "MATERIAL_INTEGRITY_GROUPS_CHANGED",
                "所选问题组已变化，请刷新审计结果后重试", 409,
            )
        anomaly_ids = {
            str(row[0]) for row in audit.execute(
                "SELECT DISTINCT image_id FROM issue_items "
                "WHERE issue_type NOT IN (?,?)", duplicate_types,
            ).fetchall()
        }
        duplicate_ids = {
            str(row[0]) for row in audit.execute(
                "SELECT DISTINCT image_id FROM issue_items WHERE issue_type IN (?,?)",
                duplicate_types,
            )
        }
        planned = []
        planned_groups = []
        review_groups = []
        skip_reasons = {}
        included_groups = kept_count = delete_count = 0
        manual_required_groups = protected_groups = anomaly_groups = 0
        skipped_item_count = protected_item_count = anomaly_item_count = 0
        selected_ids, counted_protected, unverifiable_ids, manual_ids = set(), set(), set(), set()
        planned_ids = set()
        for group in groups:
            group_key = str(group["group_key"])
            if group_key in excluded_groups:
                continue
            rows = audit.execute(
                "SELECT image_id,content_sha256,details_json FROM issue_items "
                "WHERE group_key=? ORDER BY image_id", (group_key,),
            ).fetchall()
            items = [
                {
                    "image_id": str(row["image_id"]),
                    "content_sha256": str(row["content_sha256"]),
                    "details": json.loads(row["details_json"] or "{}"),
                }
                for row in rows
            ]
            ids = {item["image_id"] for item in items}
            chosen_ids = ids.intersection(selected_images) if scope == "SELECTED_IMAGES" else ids
            chosen_ids = chosen_ids - excluded_images
            if not chosen_ids:
                continue
            selected_ids.update(chosen_ids)
            group_protected = set()
            for item in items:
                if str(item['details'].get('split') or '').lower() == 'test':
                    role_reason = {'reason': 'CURRENT_TEST_ROLE', 'source': 'material_index', 'protected': False}
                    if role_reason not in reference_reasons.setdefault(item['image_id'], []):
                        reference_reasons[item['image_id']].append(role_reason)
            counted_protected.update(chosen_ids.intersection(group_protected))
            if (scope in {'DISCARD_CONFLICTS', 'SELECTED_IMAGES', 'FILTERED'} and payload.get('delete_mode') != 'KEEP_ONE') or payload.get('delete_mode') == 'DISCARD':
                disposable = chosen_ids - planned_ids
                if not disposable:
                    continue
                planned_groups.append((group_key, '', 'EXPLICIT_DISCARD_UNPROTECTED', len(disposable)))
                included_groups += 1
                kept_count += len(ids - disposable)
                for item in items:
                    if item['image_id'] in disposable:
                        planned.append((group_key,item['image_id'],'DELETE',item['content_sha256'],str(item['details'].get('annotation_digest') or '')))
                        planned_ids.add(item['image_id']); delete_count += 1
                continue
            if str(group['issue_type']) not in duplicate_types:
                for item in items:
                    image_id = item['image_id']
                    if image_id not in chosen_ids or image_id in planned_ids:
                        continue
                    if str(group['issue_type']) == 'MATERIAL_SCAN_UNVERIFIED':
                        unverifiable_ids.add(image_id)
                        continue
                    # An anomaly filter must not become a back door around
                    # the duplicate keeper and conflicting-GT review contract.
                    if image_id in duplicate_ids:
                        manual_ids.add(image_id)
                        skip_reasons['DUPLICATE_REQUIRES_REVIEW'] = skip_reasons.get('DUPLICATE_REQUIRES_REVIEW', 0) + 1
                        continue
                    if image_id in group_protected:
                        continue
                    planned.append((group_key, image_id, 'DELETE', item['content_sha256'], str(item['details'].get('annotation_digest') or '')))
                    planned_ids.add(image_id)
                    delete_count += 1
                continue
            if scope == "DISCARD_CONFLICTS":
                if ids.intersection(anomaly_ids):
                    reason = "ANOMALOUS_MATERIAL"
                    anomaly_groups += 1
                    anomaly_item_count += len(ids)
                    if len(review_groups) < 20:
                        review_groups.append({
                            "group_key": group_key, "issue_type": str(group["issue_type"]),
                            "image_count": len(ids), "reason": reason,
                            "protected_count": len(group_protected),
                        })
                    skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                    skipped_item_count += len(ids)
                    continue
                disposable = chosen_ids - group_protected - planned_ids
                if not disposable:
                    protected_groups += 1
                    if len(review_groups) < 20:
                        review_groups.append({
                            "group_key": group_key, "issue_type": str(group["issue_type"]),
                            "image_count": len(ids), "reason": "MULTIPLE_PROTECTED_REFERENCES",
                            "protected_count": len(group_protected),
                        })
                    skip_reasons["MULTIPLE_PROTECTED_REFERENCES"] = skip_reasons.get("MULTIPLE_PROTECTED_REFERENCES", 0) + 1
                    skipped_item_count += len(ids)
                    continue
                # No fabricated keeper: this is an explicit discard, including
                # all unprotected copies when no immutable/Test keeper exists.
                planned_groups.append((group_key, "", "EXPLICIT_DISCARD_UNPROTECTED", len(disposable)))
                included_groups += 1
                kept_count += len(ids - disposable)
                for item in items:
                    if item["image_id"] not in disposable:
                        continue
                    planned.append((
                        group_key, item["image_id"], "DELETE",
                        item["content_sha256"],
                        str(item["details"].get("annotation_digest") or ""),
                    ))
                    planned_ids.add(item["image_id"])
                    delete_count += 1
                continue
            reason = ""
            if ids.intersection(anomaly_ids):
                reason = "ANOMALOUS_MATERIAL"
                anomaly_groups += 1
                anomaly_item_count += len(ids)
            elif (
                str(group["issue_type"]) == "DUPLICATE_ANNOTATION_CONFLICT"
                and not decisions.get(group_key)
            ):
                reason = "MANUAL_DECISION_REQUIRED"
                manual_required_groups += 1
                manual_ids.update(chosen_ids)
            elif group_protected == ids and len(group_protected) > 1:
                reason = "MULTIPLE_PROTECTED_REFERENCES"
                protected_groups += 1
                protected_item_count += len(group_protected)
            if reason:
                if len(review_groups) < 20:
                    review_groups.append({
                        "group_key": group_key, "issue_type": str(group['issue_type']),
                        "image_count": len(ids), "reason": reason,
                        "protected_count": len(group_protected),
                    })
                skipped_item_count += len(ids)
                skip_reasons[reason] = int(skip_reasons.get(reason) or 0) + 1
                continue
            # A partially selected duplicate group must retain an unselected item.
            candidates = items if decisions.get(group_key) else ([item for item in items if item['image_id'] in group_protected] or [item for item in items if item['image_id'] not in chosen_ids] or items)
            keeper = _material_integrity_keeper(
                candidates, group_protected, decisions.get(group_key),
            )
            keeper_reason = (
                "MANUAL_DECISION" if decisions.get(group_key)
                else "HISTORICAL_REFERENCE" if keeper in group_protected
                else "VERIFIED_SOURCE_AND_ANNOTATION"
            )
            kept_ids = {str(keeper)} | group_protected
            group_delete_count = len(chosen_ids - kept_ids - planned_ids)
            planned_groups.append((group_key, keeper, keeper_reason, group_delete_count))
            kept_count += len(items) - group_delete_count - len(kept_ids)
            for item in items:
                action = "KEEP" if item["image_id"] in kept_ids else "DELETE"
                if action == 'DELETE' and (item['image_id'] not in chosen_ids or item['image_id'] in planned_ids):
                    continue
                planned.append((
                    group_key, item["image_id"], action,
                    item["content_sha256"],
                    str(item["details"].get("annotation_digest") or ""),
                ))
                kept_count += int(action == "KEEP")
                delete_count += int(action == "DELETE")
                if action == 'DELETE':
                    planned_ids.add(item['image_id'])
            included_groups += 1

        # Freeze anomaly annotation truth too, through the same repository.
        missing_digests = [row[1] for row in planned if not row[4]]
        digests = {}
        for offset in range(0, len(missing_digests), BATCH_SIZE):
            digests.update({key: annotations.record_digest(record) for key, record in annotations.get_many(missing_digests[offset:offset+BATCH_SIZE]).items()})
        planned = [(group, image_id, action, digest, annotation_digest or digests.get(image_id, ''))
                   for group, image_id, action, digest, annotation_digest in planned]

    plan_id = uuid.uuid4().hex
    credential = secrets.token_urlsafe(32)
    reason_image_ids = {}
    for image_id in selected_ids:
        for entry in reference_reasons.get(image_id, []):
            if entry.get('protected') is True:
                reason_image_ids.setdefault(entry['reason'], set()).add(image_id)
    summary = {
        "plan_id": plan_id,
        "project_id": str(project_id),
        "actor_id": str((actor or {}).get('actor_id') or ''),
        "operation": BatchOperation.DELETE_INDEX.value,
        "audit_task_id": audit_task.task_id,
        "scope": scope,
        "review_basis": review_basis,
        "discard_mode": scope == "DISCARD_CONFLICTS",
        "selected_count": len(selected_ids),
        "retained_count": len(selected_ids - planned_ids),
        "unverifiable_count": len(unverifiable_ids),
        "manual_required_count": len(manual_ids),
        "material_revision": material_revision,
        "annotation_revision": annotation_revision,
        "label_schema_digest": metadata['label_schema_digest'],
        "included_groups": included_groups,
        "kept_count": kept_count,
        "delete_count": delete_count,
        "skipped_groups": sum(skip_reasons.values()),
        "manual_required_groups": manual_required_groups,
        "protected_groups": protected_groups,
        "anomaly_groups": anomaly_groups,
        "skipped_item_count": skipped_item_count,
        "protected_item_count": len(counted_protected),
        "physical_retained_count": len(planned_ids),
        "reclaimed_bytes": 0,
        "reclamation_state": "DEFERRED_SAFETY_UNVERIFIED",
        "reference_diagnostics_state": reference_diagnostics_state,
        "historical_reference_count": len({key for key, values in reference_reasons.items() if key in selected_ids and any(value.get('reason') not in {'ACTIVE_TASK_INPUT', 'CURRENT_TEST_ROLE'} for value in values)}) if reference_diagnostics_state=='COMPLETED' else None,
        "active_reference_count": len({key for key,values in reference_reasons.items() if key in selected_ids and any(value.get('reason')=='ACTIVE_TASK_INPUT' and value.get('task_status') in {'RUNNING','CANCEL_REQUESTED'} for value in values)}) if reference_diagnostics_state=='COMPLETED' else None,
        "current_test_count": sum(any(value.get('reason')=='CURRENT_TEST_ROLE' for value in reference_reasons.get(key,[])) for key in selected_ids),
        "protection_reason_counts": {reason: len(image_ids)
                                     for reason, image_ids in sorted(reason_image_ids.items())},
        "anomaly_item_count": anomaly_item_count,
        "skip_reasons": skip_reasons,
        "created_at": utc_now(),
        "credential_sha256": hashlib.sha256(credential.encode()).hexdigest(),
        "execution_task_id": None,
    }
    if persist:
        plan_path = artifacts.artifact_path(audit_task.task_id, _material_integrity_plan_ref(plan_id))
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(plan_path)) as plan:
            plan.executescript(_MATERIAL_INTEGRITY_PLAN_SCHEMA)
            plan.execute("BEGIN IMMEDIATE")
            plan.executemany(
                "INSERT INTO plan_metadata(key,value_json) VALUES (?,?)",
                ((key, json.dumps(value, ensure_ascii=False, sort_keys=True))
                 for key, value in summary.items()),
            )
            plan.executemany(
                "INSERT INTO plan_items(group_key,image_id,action,content_sha256,annotation_digest) "
                "VALUES (?,?,?,?,?)", planned,
            )
            plan.executemany(
                "INSERT INTO plan_groups(group_key,keeper_image_id,keeper_reason,delete_count) "
                "VALUES (?,?,?,?)", planned_groups,
            )
            plan.commit()
    public = {key: value for key, value in summary.items() if key != "credential_sha256"}
    public["preview_groups"] = [
        {
            "group_key": group_key,
            "keeper_image_id": keeper,
            "keeper_reason": reason,
            "delete_count": count,
        }
        for group_key, keeper, reason, count in planned_groups[:20]
    ]
    public["preview_groups_truncated"] = len(planned_groups) > 20
    public['review_groups'] = review_groups
    preview_ids = [row[1] for row in planned if row[2] == 'DELETE'][:20]
    if not preview_ids:
        preview_ids = sorted(selected_ids)[:20]
    public['preview_items'] = _material_integrity_preview_items(project_id, materials, preview_ids)
    for item in public['preview_items']:
        item['protection_reasons'] = reference_reasons.get(item['image_id'], [])
    deletion_ids = sorted(planned_ids)
    annotation_count = 0
    for offset in range(0, len(deletion_ids), BATCH_SIZE):
        records = annotations.get_many(deletion_ids[offset:offset+BATCH_SIZE])
        annotation_count += sum(int(record.get('version') or 0)>0 or (annotations.project_path / 'annotations' / f'{image_id}.json').is_file() for image_id, record in records.items())
    public['annotation_count'] = annotation_count
    public['gt_count'] = annotation_count
    if persist:
        public["confirmation_credential"] = credential
    else:
        public.pop('plan_id', None)
    return public


def execute_material_integrity_plan(
    project_id, audit_task, plan_id, credential, materials, repository, artifacts,
    *, actor=None,
):
    plan_path = artifacts.artifact_path(
        audit_task.task_id, _material_integrity_plan_ref(plan_id)
    )
    with FileLock(str(plan_path) + ".lock", timeout=60):
        return _execute_material_integrity_plan_locked(
            project_id, audit_task, plan_id, credential,
            materials, repository, artifacts,
            actor=actor,
        )


def _execute_material_integrity_plan_locked(
    project_id, audit_task, plan_id, credential, materials, repository, artifacts,
    *, actor=None,
):
    from .training_compatibility import _file_digest
    plan_path = artifacts.artifact_path(
        audit_task.task_id, _material_integrity_plan_ref(plan_id)
    )
    if not plan_path.is_file():
        raise BatchRequestError(
            "MATERIAL_INTEGRITY_PLAN_NOT_FOUND", "素材治理计划不存在", 404,
        )
    annotations = AnnotationRepository(materials.project_path)
    with closing(sqlite3.connect(plan_path)) as plan:
        plan.row_factory = sqlite3.Row
        metadata = _json_metadata(plan)
        if metadata.get('project_id') not in (None,str(project_id)):
            raise BatchRequestError('MATERIAL_DELETE_PROJECT_CHANGED','删除计划项目不一致',403)
        if actor is not None and metadata.get('actor_id','') != str(actor.get('actor_id') or ''):
            raise BatchRequestError('MATERIAL_DELETE_ACTOR_CHANGED','删除计划操作人不一致，请重新预览',403)
        expected = str(metadata.get("credential_sha256") or "")
        actual = hashlib.sha256(str(credential or "").encode()).hexdigest()
        if not credential or not hmac.compare_digest(expected, actual):
            raise BatchRequestError(
                "MATERIAL_INTEGRITY_CONFIRMATION_REQUIRED",
                "治理确认凭证无效，请重新生成预览", 409,
            )
        # The frozen plan owns one deterministic task identity, including a
        # retry after publication succeeded but recording its ID was interrupted.
        existing_id = str(metadata.get("execution_task_id") or "")
        if not existing_id and repository.get(str(plan_id)) is not None:
            existing_id = str(plan_id)
        if existing_id:
            existing = repository.get(existing_id)
            if existing is None:
                raise BatchRequestError(
                    "MATERIAL_INTEGRITY_EXECUTION_UNAVAILABLE",
                    "治理任务状态不可用，请联系管理员", 409,
                )
            existing_request = artifacts.read_json(existing.task_id, existing.payload_ref, default={})
            if existing.project_id != str(project_id) or (existing_request.get('options') or {}).get('material_integrity_plan_id') != str(plan_id):
                raise BatchRequestError('MATERIAL_INTEGRITY_EXECUTION_UNAVAILABLE', '治理任务归属不一致，已阻止执行', 409)
            return existing
        if (
            materials.current_revision() != int(metadata["material_revision"])
            or annotations.current_revision() != int(metadata["annotation_revision"])
            or metadata.get('label_schema_digest') != _file_digest(materials.project_path / 'meta.json')
        ):
            raise BatchRequestError(
                "MATERIAL_INTEGRITY_PLAN_STALE",
                "素材或标注已变化，请重新生成治理预览", 409,
            )
        rows = plan.execute(
            "SELECT group_key,image_id,action,content_sha256,annotation_digest "
            "FROM plan_items ORDER BY image_id"
        ).fetchall()
        group_rows = plan.execute(
            "SELECT group_key,keeper_image_id,keeper_reason,delete_count "
            "FROM plan_groups ORDER BY group_key"
        ).fetchall()
        delete_ids = [str(row["image_id"]) for row in rows if row["action"] == "DELETE"]
        if not delete_ids:
            raise BatchRequestError('MATERIAL_INTEGRITY_PLAN_EMPTY', '没有可安全删除的素材，本次未创建删除任务', 409)
        ids = [str(row["image_id"]) for row in rows]
        current_materials = {
            str(row.get("id")): row
            for offset in range(0, len(ids), BATCH_SIZE)
            for row in materials.get_many(ids[offset:offset + BATCH_SIZE])
        }
        current_annotations = {}
        for offset in range(0, len(ids), BATCH_SIZE):
            current_annotations.update(annotations.get_many(ids[offset:offset + BATCH_SIZE]))
        for row in rows:
            image_id = str(row["image_id"])
            material = current_materials.get(image_id)
            annotation = current_annotations.get(image_id)
            if (
                material is None or annotation is None
                or str(material.get("content_sha256") or "").lower()
                    != str(row["content_sha256"] or "").lower()
                or annotations.record_digest(annotation)
                    != str(row["annotation_digest"] or "")
            ):
                raise BatchRequestError(
                    "MATERIAL_INTEGRITY_PLAN_STALE",
                    "治理范围中的素材身份或标注已变化，请重新生成预览", 409,
                )

        task_id = str(plan_id)
        request = {
            "operation": BatchOperation.DELETE_INDEX.value,
            "selection_spec": {
                # The immutable server-side manifest is the execution truth.
                # FILTERED is intentionally empty here so request parsing never
                # re-serializes a >500-ID browser selection.
                "scope": SelectionScope.FILTERED.value,
                "filters": {},
                "image_ids": [],
                "repository_revision": int(metadata["material_revision"]),
            },
            "options": {
                "material_integrity_audit_id": audit_task.task_id,
                "material_integrity_plan_id": str(plan_id),
                "planned_groups": int(metadata.get("included_groups") or 0),
                "planned_kept": int(metadata.get("kept_count") or 0),
                "planned_skipped_groups": int(metadata.get("skipped_groups") or 0),
                "actor_id": str(metadata.get('actor_id') or ''),
            },
        }
        selection_path = artifacts.artifact_path(task_id, SELECTION_REF)
        previous_request = artifacts.read_json(task_id, "request.json", default=None)
        if previous_request is not None and previous_request != request:
            raise BatchRequestError(
                'MATERIAL_INTEGRITY_EXECUTION_CONFLICT',
                '任务文件归属或冻结请求不一致，已阻止执行', 409,
            )
        with closing(BatchSelection(selection_path)) as manifest:
            manifest.database.executescript(_MATERIAL_INTEGRITY_EXECUTION_SCHEMA)
            with manifest.transaction():
                manifest.database.executemany(
                    "INSERT OR IGNORE INTO selection(image_id) VALUES (?)",
                    ((image_id,) for image_id in delete_ids),
                )
                by_id = {str(row["image_id"]): row for row in rows}
                manifest.database.executemany(
                    "INSERT OR IGNORE INTO integrity_plan_items"
                    "(image_id,group_key,content_sha256,annotation_digest) VALUES (?,?,?,?)",
                    (
                        (
                            str(row["image_id"]), str(row["group_key"]),
                            str(row["content_sha256"]), str(row["annotation_digest"]),
                        )
                        for row in rows if row["action"] == "DELETE"
                    ),
                )
                manifest.database.executemany(
                    "INSERT OR IGNORE INTO integrity_plan_groups"
                    "(group_key,keeper_image_id,keeper_content_sha256,"
                    "keeper_annotation_digest,keeper_reason,delete_count) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        (
                            str(row["group_key"]), str(row["keeper_image_id"]),
                            str(by_id[str(row["keeper_image_id"])]["content_sha256"]) if row["keeper_image_id"] else "",
                            str(by_id[str(row["keeper_image_id"])]["annotation_digest"]) if row["keeper_image_id"] else "",
                            str(row["keeper_reason"]), int(row["delete_count"]),
                        )
                        for row in group_rows
                    ),
                )
                manifest.database.executemany(
                    "INSERT OR IGNORE INTO meta(key,value) VALUES (?,?)",
                    (
                        ("frozen", utc_now()),
                        ("repository_revision", str(metadata["material_revision"])),
                        ("material_integrity_plan_id", str(plan_id)),
                        ("label_schema_digest", metadata['label_schema_digest']),
                    ),
                )
                # A publication failure can leave a complete, unclaimed
                # manifest. Reuse it only after comparing *all* immutable
                # identities and untouched execution state with this plan.
                expected_items = [
                    (str(row['image_id']), str(row['group_key']),
                     str(row['content_sha256']), str(row['annotation_digest']))
                    for row in rows if row['action'] == 'DELETE'
                ]
                expected_groups = [
                    (str(row['group_key']), str(row['keeper_image_id']),
                     str(by_id[str(row['keeper_image_id'])]['content_sha256']) if row['keeper_image_id'] else '',
                     str(by_id[str(row['keeper_image_id'])]['annotation_digest']) if row['keeper_image_id'] else '',
                     str(row['keeper_reason']), int(row['delete_count']))
                    for row in group_rows
                ]
                actual_selection = [tuple(row) for row in manifest.database.execute(
                    'SELECT image_id,state,attempts,source_deleted,error FROM selection ORDER BY image_id'
                )]
                actual_items = [tuple(row) for row in manifest.database.execute(
                    'SELECT image_id,group_key,content_sha256,annotation_digest FROM integrity_plan_items ORDER BY image_id'
                )]
                actual_groups = [tuple(row) for row in manifest.database.execute(
                    'SELECT group_key,keeper_image_id,keeper_content_sha256,keeper_annotation_digest,keeper_reason,delete_count FROM integrity_plan_groups ORDER BY group_key'
                )]
                frozen_meta = dict(manifest.database.execute('SELECT key,value FROM meta'))
                if (actual_selection != [(image_id, 'pending', 0, 0, None) for image_id in delete_ids]
                        or actual_items != expected_items or actual_groups != expected_groups
                        or frozen_meta.get('material_integrity_plan_id') != str(plan_id)
                        or frozen_meta.get('label_schema_digest') != metadata['label_schema_digest']
                        or frozen_meta.get('repository_revision') != str(metadata['material_revision'])):
                    raise BatchRequestError(
                        'MATERIAL_INTEGRITY_EXECUTION_CONFLICT',
                        '未发布任务的冻结范围或执行状态不一致，请重新生成预览', 409,
                    )
            checkpoint = manifest.summary()
        artifacts.atomic_write_json(task_id, "request.json", request)
        artifacts.atomic_write_json(task_id, CHECKPOINT_REF, checkpoint)
        task = TaskRecord.new(
            task_id, str(project_id), TaskKind.MATERIAL_BATCH, "request.json",
            f"materials:{project_id}", required_capabilities=("materials.batch",),
        )
        with material_annotation_lifecycle_fence(materials.project_path):
            published = publish_prepared_batch(task, repository, artifacts)
        plan.execute(
            "UPDATE plan_metadata SET value_json=? WHERE key='execution_task_id'",
            (json.dumps(task_id),),
        )
        plan.commit()
        return published


def _training_payload_image_ids(payload):
    if not isinstance(payload, dict):
        return set()
    ids = set()
    for key in (
        "train_image_ids", "test_image_ids", "selected_train_image_ids",
        "effective_train_image_ids", "pending_annotation_image_ids",
    ):
        value = payload.get(key)
        if isinstance(value, (list, tuple)):
            ids.update(str(item) for item in value if str(item or "").strip())
    for key in ("requested_split", "admission_request", "split", "selection"):
        ids.update(_training_payload_image_ids(payload.get(key)))
    return ids


_ACTIVE_INPUT_STATUSES = (
    TaskStatus.QUEUED,
    TaskStatus.RUNNING,
    TaskStatus.CANCEL_REQUESTED,
)


def _conversion_calibration_references(payload):
    if not isinstance(payload, dict):
        return {}, set()
    remote = payload.get("remote_execution")
    conversion = remote.get("conversion") if isinstance(remote, dict) else None
    calibration = conversion.get("calibration") if isinstance(conversion, dict) else None
    items = calibration.get("items") if isinstance(calibration, dict) else None
    by_id = {}
    object_refs = set()
    for item in items or ():
        if not isinstance(item, dict):
            continue
        image_id = str(item.get("image_id") or "").strip()
        source_id = str(item.get("storage_source_id") or "").strip()
        object_key = str(item.get("object_key") or "")
        if image_id:
            by_id[image_id] = dict(item)
        if source_id and object_key:
            object_refs.add((source_id, object_key))
    return by_id, object_refs


def _assert_not_referenced_by_active_tasks(
    project_id, image_ids, materials, repository, artifacts,
):
    candidates = {str(value) for value in image_ids if str(value or "").strip()}
    if not candidates:
        return
    candidate_ids_by_ref = {}
    candidate_list = sorted(candidates)
    for offset in range(0, len(candidate_list), BATCH_SIZE):
        for row in materials.get_many(candidate_list[offset:offset + BATCH_SIZE]):
            reference = (
                str(row.get("storage_source_id") or ""),
                str(row.get("object_key") or ""),
            )
            if reference[0] and reference[1]:
                candidate_ids_by_ref.setdefault(reference, set()).add(
                    str(row.get("id") or "")
                )
    candidate_refs = set(candidate_ids_by_ref)
    cursor = None
    while True:
        page = repository.list(
            project_id=str(project_id),
            kinds=(TaskKind.TRAINING, TaskKind.MODEL_CONVERSION),
            statuses=_ACTIVE_INPUT_STATUSES,
            limit=100,
            cursor=cursor,
        )
        for task in page.items:
            payload = artifacts.read_json(task.task_id, task.payload_ref, default={})
            if task.kind is TaskKind.TRAINING:
                referenced = _training_payload_image_ids(payload)
                frozen = artifacts.read_json(task.task_id, "input-freeze.json", default={})
                referenced.update(_training_payload_image_ids(frozen))
                conflict = sorted(candidates.intersection(referenced))
                code = "MATERIAL_ACTIVE_TRAINING_REFERENCE"
                message = "该素材正在被活动训练任务引用，不能删除："
            else:
                referenced, object_refs = _conversion_calibration_references(payload)
                conflict_ids = set(candidates.intersection(referenced))
                for reference in candidate_refs.intersection(object_refs):
                    conflict_ids.update(candidate_ids_by_ref.get(reference, ()))
                conflict = sorted(conflict_ids)
                code = "MATERIAL_ACTIVE_CONVERSION_REFERENCE"
                message = "该素材正在被活动 RKNN 校准任务引用，不能删除："
            if conflict:
                raise BatchRequestError(
                    code,
                    message + ", ".join(conflict[:10]),
                    409,
                )
        cursor = page.next_cursor
        if not cursor:
            break


def _active_delete_selection_conflicts(project_id, image_ids, repository, artifacts):
    candidates = list(dict.fromkeys(
        str(value).strip() for value in image_ids if str(value).strip()
    ))
    if not candidates:
        return []
    conflicts = set()
    cursor = None
    while True:
        page = repository.list(
            project_id=str(project_id),
            kinds=(TaskKind.MATERIAL_BATCH,),
            statuses=_ACTIVE_INPUT_STATUSES,
            limit=100,
            cursor=cursor,
        )
        for task in page.items:
            request = artifacts.read_json(task.task_id, task.payload_ref, default={})
            if str((request or {}).get("operation") or "") not in {
                BatchOperation.DELETE_INDEX.value,
                BatchOperation.DELETE_SOURCE.value,
            }:
                continue
            path = artifacts.artifact_path(task.task_id, SELECTION_REF)
            if not path.is_file():
                raise BatchRequestError(
                    "MATERIAL_DELETE_STATE_UNAVAILABLE",
                    "活动素材删除任务缺少选择清单，已拒绝新的任务受理",
                    409,
                )
            with closing(BatchSelection(path)) as manifest:
                for offset in range(0, len(candidates), BATCH_SIZE):
                    chunk = candidates[offset:offset + BATCH_SIZE]
                    placeholders = ",".join("?" for _ in chunk)
                    conflicts.update(
                        str(row[0])
                        for row in manifest.database.execute(
                            f"SELECT image_id FROM selection WHERE image_id IN ({placeholders})",
                            chunk,
                        ).fetchall()
                    )
        cursor = page.next_cursor
        if not cursor:
            break
    return sorted(conflicts)


def assert_material_input_admission(
    project_id,
    image_ids,
    materials,
    repository,
    artifacts,
    *,
    expected_inputs=None,
):
    """Final admission check for tasks that still need canonical source bytes."""
    candidates = list(dict.fromkeys(
        str(value).strip() for value in image_ids if str(value).strip()
    ))
    with material_annotation_lifecycle_fence(materials.project_path):
        conflicts = _active_delete_selection_conflicts(
            project_id, candidates, repository, artifacts,
        )
        if conflicts:
            raise BatchRequestError(
                "MATERIAL_ACTIVE_DELETE_REFERENCE",
                "该素材已进入活动删除任务，不能受理新的训练或转换："
                + ", ".join(conflicts[:10]),
                409,
            )
        try:
            materials.assert_task_input_admission(
                candidates, expected_inputs=expected_inputs,
            )
        except MaterialTaskInputConflictError as error:
            raise BatchRequestError(error.code, str(error), 409) from error


_SCHEMA = """
CREATE TABLE IF NOT EXISTS selection (
    image_id TEXT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','running','succeeded','failed')),
    error TEXT, tombstone_json TEXT, source_deleted INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_selection_state ON selection(state,image_id);
CREATE TABLE IF NOT EXISTS counters(state TEXT PRIMARY KEY, count INTEGER NOT NULL);
INSERT OR IGNORE INTO counters VALUES ('pending',0),('running',0),('succeeded',0),('failed',0);
CREATE TRIGGER IF NOT EXISTS selection_insert AFTER INSERT ON selection BEGIN
    UPDATE counters SET count=count+1 WHERE state=NEW.state;
END;
CREATE TRIGGER IF NOT EXISTS selection_update AFTER UPDATE OF state ON selection WHEN OLD.state <> NEW.state BEGIN
    UPDATE counters SET count=count-1 WHERE state=OLD.state;
    UPDATE counters SET count=count+1 WHERE state=NEW.state;
END;
CREATE TRIGGER IF NOT EXISTS selection_delete AFTER DELETE ON selection BEGIN
    UPDATE counters SET count=count-1 WHERE state=OLD.state;
END;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
"""


class BatchSelection:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.database = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        self.database.row_factory = sqlite3.Row
        self.database.execute("PRAGMA journal_mode=WAL")
        self.database.execute("PRAGMA synchronous=FULL")
        self.database.executescript(_SCHEMA)

    def close(self):
        self.database.close()

    def frozen(self):
        return self.database.execute("SELECT 1 FROM meta WHERE key='frozen'").fetchone() is not None

    def rows(self, states=("pending", "running")):
        return self.database.execute(
            "SELECT * FROM selection WHERE state IN (" + ",".join("?" for _ in states) + ") ORDER BY image_id LIMIT ?",
            (*states, BATCH_SIZE),
        ).fetchall()

    def transition(self, ids, state, error=None, *, commit_guard=None):
        if len(ids) > BATCH_SIZE:
            raise ValueError("selection updates are limited to 500")
        with self.transaction():
            self.database.executemany(
                "UPDATE selection SET state=?, error=?, attempts=attempts+? WHERE image_id=?",
                ((state, error, int(state == "running"), image_id) for image_id in ids),
            )
            if commit_guard is not None:
                commit_guard()

    def transaction(self):
        from contextlib import contextmanager

        @contextmanager
        def commit():
            self.database.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.database.commit()
            except BaseException:
                self.database.rollback()
                raise
        return commit()

    def summary(self, current=None):
        counts = dict(self.database.execute("SELECT state,count FROM counters"))
        flagged = self.database.execute("SELECT value FROM meta WHERE key='clean_flagged'").fetchone()
        errors = [{"image_id": row[0], "error": row[1], "retryable": True} for row in self.database.execute(
            "SELECT image_id,error FROM selection WHERE state='failed' ORDER BY image_id LIMIT 10",
        )]
        return {"total": sum(counts.values()), "processed": counts["succeeded"] + counts["failed"],
                "succeeded": counts["succeeded"], "failed": counts["failed"], "current_image_id": current,
                "current": current, "errors": errors, "error_examples": errors,
                "flagged": int(flagged[0]) if flagged else 0,
                "selection_frozen": self.frozen()}

    def remap_result(self):
        changed_images = changed_boxes = changed_scope_images = noop_resolved = 0
        for row in self.database.execute(
            "SELECT tombstone_json FROM selection "
            "WHERE state='succeeded' AND tombstone_json IS NOT NULL"
        ):
            try:
                plan = json.loads(row[0])
            except (TypeError, ValueError):
                continue
            if plan.get("operation") != BatchOperation.REMAP_ANNOTATION_LABELS.value:
                continue
            if plan.get("noop_resolved"):
                noop_resolved += 1
                continue
            boxes = max(0, int(plan.get("changed_boxes") or 0))
            scope_changed = int(bool(plan.get("changed_scope")))
            changed_boxes += boxes
            changed_scope_images += scope_changed
            changed_images += int(boxes > 0 or scope_changed)
        failure_reasons = {
            str(row[0]): int(row[1])
            for row in self.database.execute(
                "SELECT error,COUNT(*) FROM selection "
                "WHERE state='failed' AND error IS NOT NULL GROUP BY error"
            )
        }
        return {
            "changed_images": changed_images,
            "changed_boxes": changed_boxes,
            "changed_scope_images": changed_scope_images,
            "noop_resolved": noop_resolved,
            "failure_reasons": failure_reasons,
        }


def create_annotation_remap_by_labels(
    project_id, materials, repository, artifacts, source_labels, target_label,
    *, retire_sources_on_success=True,
):
    """Freeze the live AnnotationRepository union of canonical source labels."""
    sources = list(dict.fromkeys(
        str(value).strip() for value in (source_labels or [])
        if str(value).strip()
    ))
    target = str(target_label or "").strip()
    if not sources or not target:
        raise BatchRequestError(
            "MATERIAL_REMAP_LABEL_REQUIRED",
            "原标签和目标标签不能为空",
            400,
        )
    if len(sources) > 50:
        raise BatchRequestError(
            "MATERIAL_REMAP_TOO_MANY_LABELS",
            "一次最多统一 50 个来源标签",
            422,
        )
    if target in sources:
        raise BatchRequestError(
            "MATERIAL_REMAP_INVALID",
            "目标标签不能同时作为来源标签",
            400,
        )

    annotations = AnnotationRepository(materials.project_path)
    with label_governance_fence(materials.project_path):
        active = active_project_label_ids(materials.project_path) or {}
        unavailable = [
            code for code in [*sources, target] if code not in active
        ]
        if unavailable:
            raise BatchRequestError(
                "MATERIAL_REMAP_TARGET_UNAVAILABLE",
                "来源或目标标签已不存在或已停用，请刷新后重新确认",
                409,
            )
        if retire_sources_on_success and OnlineFeedbackRepository(
            materials.project_path
        ).pending_label_reference(sources):
            raise BatchRequestError(
                "ONLINE_FEEDBACK_LABEL_ACTIVE",
                "来源标签仍有待审核的线上正确预测反馈，请先处理反馈再统一退役",
                409,
            )
        frozen = annotations.live_reference_snapshot(sources)

    image_ids = list(frozen["image_ids"])
    total = len(image_ids)
    if total <= 0:
        raise BatchRequestError(
            "MATERIAL_REMAP_SOURCE_UNUSED",
            "当前没有正式标注引用所选来源标签",
            409,
        )
    if total > MAX_REMAP_SELECTION:
        raise BatchRequestError(
            "MATERIAL_REMAP_SELECTION_TOO_LARGE",
            f"一次标签变换最多支持 {MAX_REMAP_SELECTION} 张素材",
            422,
        )

    task_id = uuid.uuid4().hex
    selection_path = artifacts.artifact_path(task_id, SELECTION_REF)
    request_payload = {
        "operation": BatchOperation.REMAP_ANNOTATION_LABELS.value,
        "options": {
            "source_labels": sources,
            "source_label": sources[0] if len(sources) == 1 else "",
            "target_label": target,
            "retire_sources_on_success": bool(retire_sources_on_success),
        },
        "selection_spec": {
            "scope": "LABEL_REFERENCE",
            "source_labels": sources,
            "reference_owner": "annotation_repository",
            "annotation_revision": int(frozen["revision"]),
        },
    }
    try:
        with closing(BatchSelection(selection_path)) as manifest:
            manifest.database.execute("BEGIN IMMEDIATE")
            try:
                for offset in range(0, total, BATCH_SIZE):
                    chunk = image_ids[offset:offset + BATCH_SIZE]
                    material_ids = {
                        str(item["id"]) for item in materials.get_many(chunk)
                    }
                    missing = [
                        image_id for image_id in chunk
                        if image_id not in material_ids
                    ]
                    if missing:
                        sample = ", ".join(missing[:10])
                        raise BatchRequestError(
                            "MATERIAL_REMAP_ORPHAN_ANNOTATION",
                            "正式标注存在但素材记录缺失，请先运行标签完整性审计："
                            + sample,
                            409,
                        )
                    manifest.database.executemany(
                        "INSERT OR IGNORE INTO selection(image_id) VALUES (?)",
                        ((image_id,) for image_id in chunk),
                    )
                manifest.database.executemany(
                    "INSERT INTO meta(key,value) VALUES (?,?)",
                    (
                        ("frozen", utc_now()),
                        ("repository_revision", str(frozen["revision"])),
                        ("reference_owner", "annotation_repository"),
                        ("selection_kind", "annotation_label_reference"),
                        ("source_labels", json.dumps(sources, ensure_ascii=False)),
                        ("target_label", target),
                    ),
                )
                manifest.database.execute("COMMIT")
            except Exception:
                manifest.database.execute("ROLLBACK")
                raise
        artifacts.atomic_write_json(task_id, "request.json", request_payload)
        with closing(BatchSelection(selection_path)) as manifest:
            artifacts.atomic_write_json(
                task_id, CHECKPOINT_REF, manifest.summary()
            )
        task = TaskRecord.new(
            task_id, project_id, TaskKind.MATERIAL_BATCH, "request.json",
            f"materials:{project_id}",
            required_capabilities=("materials.batch",),
        )
        return repository.create(task, artifacts=artifacts)
    except BatchRequestError:
        raise
    except Exception as error:
        raise BatchRequestError(
            "MATERIAL_REMAP_CREATE_FAILED",
            f"标签变换任务创建失败：{redact_storage_error(error)}",
            500,
        ) from error


def create_annotation_remap_by_label(
    project_id, materials, repository, artifacts, source_label, target_label,
):
    return create_annotation_remap_by_labels(
        project_id,
        materials,
        repository,
        artifacts,
        [source_label],
        target_label,
        retire_sources_on_success=True,
    )

def create_annotation_remap_batch(
    project_id, materials, repository, artifacts, image_ids,
    source_label, target_label,
):
    ids = list(dict.fromkeys(
        str(value).strip() for value in (image_ids or []) if str(value).strip()
    ))
    if not ids:
        raise BatchRequestError(
            "MATERIAL_REMAP_SELECTION_REQUIRED",
            "请选择需要调整标签的素材",
            400,
        )
    if len(ids) > MAX_REMAP_SELECTION:
        raise BatchRequestError(
            "MATERIAL_REMAP_SELECTION_TOO_LARGE",
            f"一次标签变换最多支持 {MAX_REMAP_SELECTION} 张素材",
            422,
        )
    source = str(source_label or "").strip()
    target = str(target_label or "").strip()
    if not source or not target:
        raise BatchRequestError(
            "MATERIAL_REMAP_LABEL_REQUIRED",
            "原标签和目标标签不能为空",
            400,
        )
    task_id = uuid.uuid4().hex
    selection_path = artifacts.artifact_path(task_id, SELECTION_REF)
    request_payload = {
        "operation": BatchOperation.REMAP_ANNOTATION_LABELS.value,
        "options": {"source_label": source, "target_label": target},
    }
    try:
        with closing(BatchSelection(selection_path)):
            pass
        with closing(materials._connect()) as database:
            database.execute(
                "ATTACH DATABASE ? AS batch_selection", (str(selection_path),)
            )
            database.execute("PRAGMA batch_selection.synchronous=FULL")
            database.execute("BEGIN IMMEDIATE")
            try:
                revision = materials._revision(database)
                for offset in range(0, len(ids), BATCH_SIZE):
                    chunk = ids[offset:offset + BATCH_SIZE]
                    database.executemany(
                        "INSERT OR IGNORE INTO batch_selection.selection(image_id) "
                        "VALUES (?)",
                        ((image_id,) for image_id in chunk),
                    )
                missing = database.execute(
                    "SELECT s.image_id FROM batch_selection.selection s "
                    "LEFT JOIN main.materials m ON m.id=s.image_id "
                    "WHERE m.id IS NULL ORDER BY s.image_id LIMIT 11"
                ).fetchall()
                if missing:
                    sample = ", ".join(str(row[0]) for row in missing[:10])
                    raise BatchRequestError(
                        "MATERIAL_REMAP_SELECTION_CHANGED",
                        f"部分素材不存在，请刷新后重试：{sample}",
                        409,
                    )
                database.executemany(
                    "INSERT INTO batch_selection.meta(key,value) VALUES (?,?)",
                    (
                        ("frozen", utc_now()),
                        ("repository_revision", str(revision)),
                        ("selection_kind", "annotation_label_remap"),
                    ),
                )
                database.execute("COMMIT")
            except Exception:
                database.execute("ROLLBACK")
                raise
        artifacts.atomic_write_json(task_id, "request.json", request_payload)
        with closing(BatchSelection(selection_path)) as manifest:
            artifacts.atomic_write_json(
                task_id, CHECKPOINT_REF, manifest.summary()
            )
        task = TaskRecord.new(
            task_id, project_id, TaskKind.MATERIAL_BATCH, "request.json",
            f"materials:{project_id}",
            required_capabilities=("materials.batch",),
        )
        return repository.create(task, artifacts=artifacts)
    except BatchRequestError:
        raise
    except Exception as error:
        raise BatchRequestError(
            "MATERIAL_REMAP_CREATION_FAILED",
            f"标签变换任务创建失败：{redact_storage_error(error)}",
            500,
        ) from error


def _check_active(context, stage="processing", current=None, progress=None):
    current_task = context.repository.heartbeat(
        context.task.task_id, context.lease.lease_token, stage=stage, current_item=current, progress=progress,
    )
    if current_task.status is TaskStatus.CANCEL_REQUESTED:
        raise InterruptedError("material batch cancelled")


def _object_missing(error):
    """Recognize structured provider not-found errors, including wrapped SDK errors."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, FileNotFoundError):
            return True
        if str(getattr(error, "code", "")) in {"STORAGE_OBJECT_NOT_FOUND", "NoSuchKey", "NotFound", "404"}:
            return True
        response = getattr(error, "response", None)
        if isinstance(response, dict):
            if str((response.get("Error") or {}).get("Code", "")) in {"NoSuchKey", "NotFound", "404"}:
                return True
        elif getattr(response, "status_code", None) == 404:
            return True
        if getattr(error, "status", None) == 404:
            return True
        error = error.__cause__
    return False


def _atomic_write_json_file(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _retire_merged_source_labels(
    data_dir: Path, project_id: str, sources, target: str,
) -> list[str]:
    sources = list(dict.fromkeys(
        str(value).strip() for value in (sources or []) if str(value).strip()
    ))
    if not sources:
        return []
    project_path = data_dir / "projects" / project_id
    meta_path = project_path / "meta.json"
    projects_path = data_dir / "projects.json"
    with label_governance_fence(project_path):
        annotation_remaining = AnnotationRepository(project_path).label_reference_preview(
            sources
        )
        if int(annotation_remaining.get("affected_images") or 0) != 0:
            raise BatchRequestError(
                "ANNOTATION_REMAP_REFERENCES_REMAIN",
                "ANNOTATION_REMAP_REFERENCES_REMAIN: 标签统一完成后又出现新的 AnnotationRepository 来源标签引用，已阻止来源标签退役",
                409,
            )
        material_remaining = MaterialRepository(project_path).label_reference_preview(
            sources
        )
        if int(material_remaining.get("affected_images") or 0) != 0:
            raise BatchRequestError(
                "MATERIAL_REMAP_REFERENCES_REMAIN",
                "MATERIAL_REMAP_REFERENCES_REMAIN: 标签统一完成后又出现新的 MaterialRepository 来源标签引用，已阻止来源标签退役",
                409,
            )
        with FileLock(str(projects_path) + ".lock", timeout=60):
            with FileLock(str(meta_path) + ".lock", timeout=60):
                project = json.loads(meta_path.read_text(encoding="utf-8"))
                labels = list(project.get("labels") or [])
                metadata = project.setdefault("label_meta", [])
                while len(metadata) < len(labels):
                    metadata.append({})
                if target not in labels:
                    raise BatchRequestError(
                        "MATERIAL_REMAP_TARGET_UNAVAILABLE",
                        "目标标签已不存在，不能完成来源标签退役",
                        409,
                    )
                target_index = labels.index(target)
                frozen_label_names = list(sources)
                for source_code in sources:
                    if source_code in labels:
                        source_meta = metadata[labels.index(source_code)]
                        if isinstance(source_meta, dict):
                            frozen_label_names.append(str(source_meta.get("display_name") or ""))
                if OnlineFeedbackRepository(project_path).pending_label_reference(
                    frozen_label_names
                ):
                    raise BatchRequestError(
                        "ONLINE_FEEDBACK_LABEL_ACTIVE",
                        "来源标签仍有待审核的线上正确预测反馈，已阻止来源标签退役",
                        409,
                    )
                target_meta = (
                    metadata[target_index]
                    if isinstance(metadata[target_index], dict)
                    else {}
                )
                metadata[target_index] = target_meta
                if (
                    str(target_meta.get("status") or "active").lower() != "active"
                    or target_meta.get("active") is False
                ):
                    raise BatchRequestError(
                        "MATERIAL_REMAP_TARGET_UNAVAILABLE",
                        "目标标签已停用，不能完成来源标签退役",
                        409,
                    )
                retired = []
                merged_at = utc_now()
                for source in sources:
                    if source not in labels:
                        raise BatchRequestError(
                            "MATERIAL_REMAP_SOURCE_SCHEMA_CHANGED",
                            f"来源标签 {source} 已从标签配置中消失",
                            409,
                        )
                    index = labels.index(source)
                    row = metadata[index] if isinstance(metadata[index], dict) else {}
                    metadata[index] = row
                    status = str(row.get("status") or "active").lower()
                    if row.get("active") is False and status == "active":
                        status = "inactive"
                    if status == "merged" and str(row.get("merged_into") or "") == target:
                        retired.append(source)
                        continue
                    if status != "active":
                        raise BatchRequestError(
                            "MATERIAL_REMAP_SOURCE_SCHEMA_CHANGED",
                            f"来源标签 {source} 状态已变化，请人工复核",
                            409,
                        )
                    row["status"] = "merged"
                    row["merged_into"] = target
                    row["merged_at"] = merged_at
                    retired.append(source)
                project["updated_at"] = merged_at
                _atomic_write_json_file(meta_path, project)

                projects = []
                if projects_path.is_file():
                    try:
                        value = json.loads(projects_path.read_text(encoding="utf-8"))
                        projects = value if isinstance(value, list) else []
                    except Exception:
                        projects = []
                replaced = False
                for index, item in enumerate(projects):
                    if str(item.get("id") or "") == str(project_id):
                        projects[index] = project
                        replaced = True
                        break
                if not replaced:
                    projects.append(project)
                _atomic_write_json_file(projects_path, projects)
        return retired

def _material_delete_token(task_id, image_id):
    return f"material_delete_{str(task_id)[:32]}_" + hashlib.sha256(str(image_id).encode('utf-8')).hexdigest()[:24]


class MaterialBatchHandler:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).resolve()

    def run(self, context):
        payload = context.artifacts.read_json(
            context.task.task_id, context.task.payload_ref, default={}
        )
        if str((payload or {}).get("operation") or "").upper() == "SMART_AUDIT":
            from .smart_material_audit.worker import run_audit
            return run_audit(context,self.data_dir)
        if str((payload or {}).get("operation") or "").upper() == BatchOperation.AUDIT_LABEL_INTEGRITY.value:
            try:
                return self._run_label_integrity_audit(context)
            except BaseException as error:
                append_task_log(context, "error", f"{type(error).__name__}: {error}")
                raise
        if str((payload or {}).get("operation") or "").upper() == BatchOperation.AUDIT_MATERIAL_INTEGRITY.value:
            try:
                return self._run_material_integrity_audit(context)
            except BaseException as error:
                append_task_log(context, "error", f"{type(error).__name__}: {error}")
                raise
        selection_path = context.artifacts.artifact_path(context.task.task_id, SELECTION_REF)
        selection_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(selection_path) + ".lock", timeout=60):
            with closing(BatchSelection(selection_path)) as manifest:
                try:
                    return self._run(context, manifest)
                except BaseException as error:
                    append_task_log(context, "error", f"{type(error).__name__}: {error}")
                    if not isinstance(error, PermissionError):
                        context.save_checkpoint(manifest.summary())
                    raise

    def _run(self, context, manifest):
        payload = context.artifacts.read_json(context.task.task_id, context.task.payload_ref)
        if str((payload or {}).get("operation") or "").upper() == BatchOperation.REMAP_ANNOTATION_LABELS.value:
            return self._run_annotation_remap(context, manifest, payload)
        if str((payload or {}).get("operation") or "").upper() == BatchOperation.REPAIR_ANNOTATION_PROJECTIONS.value:
            return self._run_annotation_projection_repair(context, manifest, payload)
        operation, selection, options = parse_request(payload)
        if operation is BatchOperation.AI_ANNOTATE:
            confirmation = context.artifacts.read_json(
                context.task.task_id, "review/confirmation.json", default=None,
            )
            if isinstance(confirmation, dict) and confirmation.get("accepted") is True:
                from .annotation_task_service import commit_confirmed_review
                return commit_confirmed_review(context)
        project = str(context.task.project_id or '').strip()
        if (
            not project
            or any(character in project for character in ('/', '\\'))
            or not all(character.isalnum() or character in {'_', '-'} for character in project)
        ):
            raise ValueError('project id must be one safe path component')
        projects_root = (self.data_dir / 'projects').resolve()
        project_path = (projects_root / project).resolve()
        if project_path.parent != projects_root:
            raise ValueError('project id escaped projects root')
        materials = MaterialRepository(project_path)
        confirmed_revision = manifest.database.execute("SELECT value FROM meta WHERE key='repository_revision'").fetchone()
        if not manifest.frozen() or confirmed_revision is None or confirmed_revision[0] != str(selection.repository_revision):
            raise BatchRequestError("BATCH_SELECTION_NOT_FROZEN", "batch has no confirmed immutable selection; create and confirm a new batch", 409)
        if context.task.retry_of:
            # A CLEAN task may be safely preempted between the durable
            # selection transition to "running" and result persistence. Reset
            # only incomplete rows; succeeded rows remain immutable.
            retry_states = ("failed", "running") if operation is BatchOperation.CLEAN else ("failed",)
            while batch := manifest.rows(retry_states):
                _check_active(context)
                manifest.transition([row["image_id"] for row in batch], "pending")
        if operation is BatchOperation.DELETE_INDEX:
            self._reconcile_index_retirement_backups(context, manifest, project_path, materials)
        if options.get("material_integrity_plan_id"):
            self._validate_material_integrity_execution(
                context, manifest, project_path, materials,
            )
        append_task_log(context, "processing", f"operation={operation.value} total={manifest.summary()['total']}")
        sources = StorageSourceRepository(self.data_dir / "storage" / "storage_sources.sqlite3") if operation is BatchOperation.DELETE_SOURCE else None
        source_cache, providers = {}, {}
        manager = index = annotation = None
        if operation is BatchOperation.AI_ANNOTATE:
            from .annotation_batches import AnnotationBatch
            annotation = AnnotationBatch(self.data_dir, project, materials, context, manifest, options)
        if operation is BatchOperation.CLEAN:
            manager = StorageManager(data_dir=self.data_dir, project_id=project, materials=materials,
                provider_resolver=lambda source, _secret: _provider(self.data_dir, project, source))
            index = DurableHashIndex(manifest.database, lambda: _check_active(context, "duplicate_lookup"))
            if context.task.retry_of:
                reset_stale_clean_successes(context, manifest, materials, _check_active)
        while batch := manifest.rows():
            _check_active(context)
            ids = [row["image_id"] for row in batch]
            if operation is BatchOperation.DELETE_SOURCE:
                with material_annotation_lifecycle_fence(project_path):
                    _assert_not_referenced_by_active_tasks(
                        project, ids, materials, context.repository, context.artifacts
                    )
            manifest.transition(ids, "running")
            current = ids[0]
            context.save_checkpoint(manifest.summary(current))
            if operation is BatchOperation.DELETE_SOURCE:
                self._delete_sources(context, manifest, materials, batch, sources, source_cache, providers)
            elif operation is BatchOperation.CLEAN:
                clean_batch(context, manifest, materials, batch, options, manager, index, _check_active)
            elif operation is BatchOperation.AI_ANNOTATE:
                annotation.process(materials, batch, _check_active)
            else:
                try:
                    existing = {row["id"] for row in materials.get_many(ids)}
                    found = [image_id for image_id in ids if image_id in existing]
                    missing = [image_id for image_id in ids if image_id not in existing]
                    if operation is BatchOperation.MARK_CLEAN_SKIPPED:
                        decided_at = context.task.created_at
                        _transform_many(materials, found, lambda row: mark_ready(row, decided_at), batch_size=BATCH_SIZE)
                    elif operation is BatchOperation.ADD_LABELS:
                        materials.add_labels_many(found, options["labels"], batch_size=BATCH_SIZE)
                    elif operation is BatchOperation.REMOVE_LABELS:
                        materials.remove_labels_many(found, options["labels"], batch_size=BATCH_SIZE)
                    elif operation is BatchOperation.DELETE_INDEX:
                        self._delete_index_rows(
                            context, manifest, materials, ids, project_path
                        )
                        found, missing = [], []
                    else:
                        raise BatchRequestError("BATCH_OPERATION_NOT_READY", operation.value)
                    manifest.transition(found, "succeeded")
                    manifest.transition(missing, "succeeded" if operation is BatchOperation.DELETE_INDEX else "failed",
                                        None if operation is BatchOperation.DELETE_INDEX else "MATERIAL_NOT_FOUND")
                except (PermissionError, InterruptedError):
                    raise
                except Exception as error:
                    public_error = redact_storage_error(error)
                    manifest.transition(ids, "failed", public_error)
                    append_task_log(context, "batch_error", public_error)
            _check_active(context)
            checkpoint = manifest.summary()
            context.save_checkpoint(checkpoint)
            append_task_log(context, "checkpoint", f"processed={checkpoint['processed']} succeeded={checkpoint['succeeded']} failed={checkpoint['failed']}")
        audit_summary = None
        if operation is BatchOperation.CLEAN:
            audit_summary = audit_cleaning_annotations(
                project_path,
                manifest.database,
                materials,
                enabled=bool(options.get("annotation_audit", True)),
            )
        summary = manifest.summary()
        if operation is BatchOperation.DELETE_INDEX:
            summary.update(logical_removed=summary['succeeded'],physical_retained=summary['succeeded'],
                reclaimed_bytes=0,skipped=0,reclamation_state='DEFERRED_SAFETY_UNVERIFIED')
        if operation is BatchOperation.CLEAN:
            summary.update({
                "clean_results_ref": SELECTION_REF,
                "annotation_audit": audit_summary,
                "review_required": bool(
                    summary["flagged"]
                    or (audit_summary or {}).get("review_images")
                ),
                "scan_only": True,
            })
        context.save_checkpoint(summary)
        context.artifacts.atomic_write_json(context.task.task_id, RESULT_REF, summary)
        if annotation is not None:
            return annotation.finish()
        status = (TaskStatus.PARTIAL_SUCCESS if summary["succeeded"] else TaskStatus.FAILED) if summary["failed"] else TaskStatus.SUCCEEDED
        append_task_log(context, "finished", status.value)
        return status, RESULT_REF

    def _reconcile_index_retirement_backups(self, context, manifest, project_path, materials):
        """Reconcile only this task's durable GT/identity commit boundary."""
        annotations = AnnotationRepository(project_path)
        from .training_compatibility import _file_digest
        schema = manifest.database.execute("SELECT value FROM meta WHERE key='label_schema_digest'").fetchone()
        has_plan = manifest.database.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='integrity_plan_items'"
        ).fetchone()
        if not has_plan:
            return
        pending = manifest.database.execute(
            "SELECT i.* FROM integrity_plan_items i JOIN selection s ON s.image_id=i.image_id "
            "WHERE s.state!='succeeded' ORDER BY i.image_id"
        )
        while rows := pending.fetchmany(BATCH_SIZE):
            for item in rows:
                _check_active(context, "retirement_recovery")
                image_id = str(item['image_id'])
                token = _material_delete_token(context.task.task_id, image_id)
                with label_governance_fence(project_path), material_annotation_lifecycle_fence(project_path):
                    material = materials.get(image_id)
                    retired = materials.retirement(context.task.task_id, image_id)
                    if retired and material is None:
                        annotations.complete_delete(token)
                        manifest.transition([image_id], 'succeeded')
                        continue
                    if not annotations.delete_backup_count(token):
                        continue
                    # Preserve evidence on identity/schema drift. Never attach old
                    # GT to replaced bytes or overwrite a concurrent human edit.
                    current = annotations.get(image_id)
                    if (retired or material is None
                            or str(material.get('content_sha256') or '').lower() != str(item['content_sha256'] or '').lower()
                            or not schema or schema[0] != _file_digest(project_path / 'meta.json')
                            or (int(current.get('version') or 0) > 0
                                and annotations.record_digest(current) != str(item['annotation_digest'] or ''))):
                        manifest.transition([image_id], 'failed', 'MATERIAL_RETIREMENT_RECOVERY_CONFLICT')
                        continue
                    try:
                        annotations.restore_delete(token)
                    except (OSError, ValueError, sqlite3.Error):
                        manifest.transition([image_id], 'failed', 'MATERIAL_RETIREMENT_RECOVERY_CONFLICT')

    def _validate_material_integrity_execution(
        self, context, manifest, project_path, materials,
    ):
        """Fail individual planned deletes closed when frozen identity drifted."""
        exists = manifest.database.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='integrity_plan_groups'"
        ).fetchone()
        if not exists:
            raise BatchRequestError(
                "MATERIAL_INTEGRITY_EXECUTION_INCOMPLETE",
                "治理任务缺少冻结组清单", 409,
            )
        annotations = AnnotationRepository(project_path)
        groups = manifest.database.execute(
            "SELECT * FROM integrity_plan_groups ORDER BY group_key"
        ).fetchall()
        items = manifest.database.execute(
            "SELECT i.* FROM integrity_plan_items i JOIN selection s ON s.image_id=i.image_id "
            "WHERE s.state!='succeeded' ORDER BY i.image_id"
        ).fetchall()
        from .training_compatibility import _file_digest
        schema = manifest.database.execute("SELECT value FROM meta WHERE key='label_schema_digest'").fetchone()
        schema_changed = not schema or schema[0] != _file_digest(project_path / 'meta.json')
        all_ids = [str(row["keeper_image_id"]) for row in groups if row["keeper_image_id"]]
        all_ids.extend(str(row["image_id"]) for row in items)
        current_materials = {}
        current_annotations = {}
        for offset in range(0, len(all_ids), BATCH_SIZE):
            chunk = all_ids[offset:offset + BATCH_SIZE]
            current_materials.update({
                str(row.get("id")): row for row in materials.get_many(chunk)
            })
            current_annotations.update(annotations.get_many(chunk))
        deletes_by_group = {}
        for row in items:
            deletes_by_group.setdefault(str(row["group_key"]), []).append(
                str(row["image_id"])
            )
        failed = {}
        group_keys = {str(row['group_key']) for row in groups}

        def identity_matches(image_id, expected_hash, expected_annotation):
            material = current_materials.get(str(image_id))
            annotation = current_annotations.get(str(image_id))
            return bool(
                material is not None and annotation is not None
                and str(material.get("content_sha256") or "").lower()
                    == str(expected_hash or "").lower()
                and annotations.record_digest(annotation)
                    == str(expected_annotation or "")
            )

        for row in groups:
            if not row["keeper_image_id"]:
                if str(row["keeper_reason"]) != "EXPLICIT_DISCARD_UNPROTECTED":
                    for image_id in deletes_by_group.get(str(row["group_key"]), ()):
                        failed[image_id] = "MATERIAL_INTEGRITY_KEEPER_CHANGED"
                continue
            if not identity_matches(
                row["keeper_image_id"], row["keeper_content_sha256"],
                row["keeper_annotation_digest"],
            ):
                for image_id in deletes_by_group.get(str(row["group_key"]), ()):
                    failed[image_id] = "MATERIAL_INTEGRITY_KEEPER_CHANGED"
        for row in items:
            image_id = str(row["image_id"])
            if current_materials.get(image_id) is None and materials.retirement(context.task.task_id,image_id):
                continue
            if schema_changed:
                failed[image_id] = 'MATERIAL_INTEGRITY_PLAN_STALE'
            # Ordinary anomaly deletes have no keeper row. Duplicate groups
            # must always have a frozen group decision, including explicit discard.
            if (str(row['group_key']).startswith('DUPLICATE_')
                    and str(row['group_key']) not in group_keys):
                failed[image_id] = 'MATERIAL_INTEGRITY_EXECUTION_INCOMPLETE'
            if image_id not in failed and not identity_matches(
                image_id, row["content_sha256"], row["annotation_digest"],
            ):
                failed[image_id] = "MATERIAL_INTEGRITY_DELETE_IDENTITY_CHANGED"
        for reason in sorted(set(failed.values())):
            ids = sorted(image_id for image_id, value in failed.items() if value == reason)
            for offset in range(0, len(ids), BATCH_SIZE):
                manifest.transition(ids[offset:offset + BATCH_SIZE], "failed", reason)
            append_task_log(
                context, "integrity_guard", f"reason={reason} count={len(ids)}",
            )

    def _run_label_integrity_audit(self, context):
        from .label_integrity import AUDIT_REF, run_label_integrity_audit

        project = str(context.task.project_id or "").strip()
        if (
            not project
            or any(character in project for character in ("/", "\\"))
            or not all(character.isalnum() or character in {"_", "-"} for character in project)
        ):
            raise ValueError("project id must be one safe path component")
        projects_root = (self.data_dir / "projects").resolve()
        project_path = (projects_root / project).resolve()
        if project_path.parent != projects_root:
            raise ValueError("project id escaped projects root")

        append_task_log(context, "processing", "operation=AUDIT_LABEL_INTEGRITY scope=PROJECT")

        def progress(scanned):
            checkpoint = {
                "total": None,
                "processed": int(scanned),
                "succeeded": int(scanned),
                "failed": 0,
                "selection_frozen": False,
                "audit_ref": AUDIT_REF,
            }
            context.save_checkpoint(checkpoint)
            _check_active(
                context,
                "AUDITING_LABEL_INTEGRITY",
                f"已审计 {int(scanned)} 条标注真相",
                50.0,
            )

        result = run_label_integrity_audit(
            project_path,
            context.artifacts.artifact_path(context.task.task_id, AUDIT_REF),
            progress=progress,
        )
        checkpoint = {
            "total": int(result["scanned_images"]),
            "processed": int(result["scanned_images"]),
            "succeeded": int(result["scanned_images"]),
            "failed": 0,
            "selection_frozen": False,
            "audit_ref": AUDIT_REF,
            "affected_images": int(result["affected_images"]),
            "issue_count": int(result["issue_count"]),
        }
        context.save_checkpoint(checkpoint)
        context.artifacts.atomic_write_json(context.task.task_id, RESULT_REF, result)
        _check_active(
            context,
            "AUDITING_LABEL_INTEGRITY",
            f"审计完成 · {result['affected_images']} 张素材存在问题",
            99.0,
        )
        append_task_log(context, "finished", TaskStatus.SUCCEEDED.value)
        return TaskStatus.SUCCEEDED, RESULT_REF

    def _run_material_integrity_audit(self, context):
        """Audit indexed duplicates and stored bytes under the existing batch owner."""
        project, project_path = _safe_project_path(self.data_dir, context.task.project_id)
        materials = MaterialRepository(project_path)
        annotations = AnnotationRepository(project_path)
        manager = StorageManager(
            data_dir=self.data_dir,
            project_id=project,
            materials=materials,
            provider_resolver=lambda source, _secret: _provider(
                self.data_dir, project, source
            ),
        )
        artifact_path = context.artifacts.artifact_path(
            context.task.task_id, MATERIAL_INTEGRITY_REF
        )
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        material_revision = materials.current_revision()
        annotation_revision = annotations.current_revision()
        total = materials.summary()["total"]
        processed = scan_failures = 0
        append_task_log(
            context,
            "processing",
            f"operation={BatchOperation.AUDIT_MATERIAL_INTEGRITY.value} scope=PROJECT total={total}",
        )

        def checkpoint(stage, current=None):
            progress = int(processed * 100 / max(1, total))
            value = {
                "total": total,
                "processed": processed,
                "succeeded": processed - scan_failures,
                "failed": scan_failures,
                "selection_frozen": False,
                "audit_ref": MATERIAL_INTEGRITY_REF,
            }
            context.save_checkpoint(value)
            _check_active(context, stage, current, progress)

        with closing(sqlite3.connect(artifact_path)) as audit:
            audit.executescript(_MATERIAL_INTEGRITY_SCHEMA)
            audit.execute("BEGIN IMMEDIATE")
            audit.execute("DELETE FROM audit_metadata")
            audit.execute("DELETE FROM issue_items")
            audit.execute("DELETE FROM issue_groups")

            # Share one canonical Material SHA256 grouping with label Full Audit.
            # Training admission and both audits use the same GT comparison.
            from .training_splits import training_annotation_digest
            from .training_compatibility import diagnose_annotation_conflict, annotation_import_batches, _file_digest
            conflict_diagnoses = {}
            import_evidence = {}
            label_ids = active_project_label_ids(project_path)
            label_schema_digest = _file_digest(project_path / 'meta.json')
            duplicate_groups = materials.duplicate_content_groups()
            for digest, image_ids in duplicate_groups.items():
                records: dict[str, dict] = {}
                for offset in range(0, len(image_ids), BATCH_SIZE):
                    records.update(annotations.get_many(image_ids[offset:offset + BATCH_SIZE]))
                annotation_digests = {
                    training_annotation_digest(records[image_id])
                    for image_id in image_ids
                }
                issue_type = (
                    "DUPLICATE_IDENTICAL"
                    if len(annotation_digests) == 1
                    else "DUPLICATE_ANNOTATION_CONFLICT"
                )
                group_key = f"{issue_type}:{digest}"
                indexed = {
                    str(row["id"]): row
                    for row in materials.get_many(image_ids)
                }
                if issue_type == 'DUPLICATE_ANNOTATION_CONFLICT':
                    comparison_rows = [
                        {**indexed.get(image_id, {}), **records[image_id], 'id': image_id,
                         'content_sha256': digest} for image_id in image_ids
                    ]
                    _material_integrity_import_evidence(project, comparison_rows, context.repository,
                        context.artifacts, import_evidence)
                    diagnosis = diagnose_annotation_conflict(comparison_rows, label_ids, import_evidence)
                    # Persist only a disposable audit projection. Detailed box
                    # candidate pairs are read on demand from formal GT.
                    diagnosis.pop('pairs')
                    conflict_diagnoses[group_key] = diagnosis
                for image_id in image_ids:
                    record = records[image_id]
                    row = indexed.get(image_id) or {}
                    details = {
                        "filename": row.get("filename") or image_id,
                        "storage_source_id": row.get("storage_source_id") or "",
                        "import_batch_id": (annotation_import_batches({**row, **record}) or [''])[0]
                            if len(annotation_import_batches({**row, **record})) <= 1 else '',
                        "import_batch_ids": annotation_import_batches({**row, **record}),
                        "split": row.get("split") or "unassigned",
                        "annotation_state": record.get("annotation_state") or "unannotated",
                        "annotation_scope": list(record.get("annotation_scope") or []),
                        "box_count": len(record.get("boxes") or []),
                        "labels": sorted({
                            str(box.get("label") or box.get("code") or "")
                            for box in (record.get("boxes") or [])
                            if str(box.get("label") or box.get("code") or "")
                        }),
                        "annotation_digest": annotations.record_digest(record),
                        "processing_status": row.get("processing_status") or "",
                        "created_at": row.get("created_at") or "",
                    }
                    audit.execute(
                        "INSERT INTO issue_items(group_key,issue_type,content_sha256,image_id,details_json) "
                        "VALUES (?,?,?,?,?)",
                        (group_key, issue_type, digest, image_id, json.dumps(details, ensure_ascii=False, sort_keys=True)),
                    )

            # Stored-object/hash/decode verification is intentionally background
            # work and reuses StorageManager plus the cleaning decoder owner.
            analysis = CleaningAnalysisRuntime()
            cursor = None
            try:
                while True:
                    page = materials.list_page(cursor=cursor, limit=BATCH_SIZE)
                    if not page.items:
                        break
                    page_annotations = annotations.get_many([str(row['id']) for row in page.items])
                    for row in page.items:
                        image_id = str(row.get("id") or "")
                        issue_type = ""
                        detail = ""
                        try:
                            local = manager.materialize(row)
                            analysis.analyze(
                                local.path,
                                require_blur=False,
                                content_sha256=local.content_sha256,
                                check_active=lambda: _check_active(
                                    context, "AUDITING_MATERIAL_INTEGRITY", image_id
                                ),
                            )
                        except ImageDecodeError as error:
                            issue_type, detail = "INVALID_IMAGE", redact_storage_error(error)
                        except StorageError as error:
                            code = str(getattr(error, "code", ""))
                            if code in {"SOURCE_CONTENT_CHANGED", "STORAGE_SHA256_MISMATCH"}:
                                issue_type = "CONTENT_HASH_MISMATCH"
                            elif code in {
                                "STORAGE_OBJECT_NOT_FOUND", "SOURCE_UNAVAILABLE",
                                "STORAGE_SOURCE_NOT_FOUND", "NoSuchKey", "NotFound", "404",
                            }:
                                issue_type = "MATERIAL_OBJECT_MISSING"
                            else:
                                scan_failures += 1
                                issue_type = "MATERIAL_SCAN_UNVERIFIED"
                            detail = redact_storage_error(error)
                        except FileNotFoundError as error:
                            issue_type, detail = "MATERIAL_OBJECT_MISSING", redact_storage_error(error)
                        except Exception as error:
                            scan_failures += 1
                            issue_type = "MATERIAL_SCAN_UNVERIFIED"
                            detail = redact_storage_error(error)
                        if issue_type:
                            group_key = f"{issue_type}:{image_id}"
                            details = {
                                "filename": row.get("filename") or image_id,
                                "storage_source_id": row.get("storage_source_id") or "",
                                "import_batch_id": row.get("import_batch_id") or row.get("batch_id") or "",
                                "split": row.get("split") or "unassigned",
                                "detail": detail,
                                "annotation_digest": annotations.record_digest(page_annotations[image_id]),
                            }
                            audit.execute(
                                "INSERT OR REPLACE INTO issue_items"
                                "(group_key,issue_type,content_sha256,image_id,details_json) VALUES (?,?,?,?,?)",
                                (
                                    group_key,
                                    issue_type,
                                    str(row.get("content_sha256") or "").lower(),
                                    image_id,
                                    json.dumps(details, ensure_ascii=False, sort_keys=True),
                                ),
                            )
                        processed += 1
                        if processed % 25 == 0:
                            checkpoint("AUDITING_MATERIAL_INTEGRITY", image_id)
                    cursor = page.next_cursor
                    if not cursor:
                        break
            finally:
                analysis.close()
                manager._providers.clear()

            audit.execute(
                "INSERT INTO issue_groups(group_key,issue_type,content_sha256,image_count,details_json) "
                "SELECT group_key,issue_type,content_sha256,COUNT(*),'{}' FROM issue_items "
                "GROUP BY group_key,issue_type,content_sha256"
            )
            audit.executemany('UPDATE issue_groups SET details_json=? WHERE group_key=?',
                ((json.dumps({'gt_diagnosis': value}, ensure_ascii=False), key)
                 for key, value in conflict_diagnoses.items()))
            group_count = int(audit.execute("SELECT COUNT(*) FROM issue_groups").fetchone()[0])
            affected_images = int(audit.execute("SELECT COUNT(DISTINCT image_id) FROM issue_items").fetchone()[0])
            issue_counts = {
                str(row[0]): int(row[1])
                for row in audit.execute(
                    "SELECT issue_type,COUNT(*) FROM issue_items GROUP BY issue_type ORDER BY issue_type"
                ).fetchall()
            }
            metadata = {
                "created_at": utc_now(),
                "material_revision": material_revision,
                "annotation_revision": annotation_revision,
                "snapshot_only": True,
                "gt_diagnosis_version": 1,
                "label_schema_digest": label_schema_digest,
            }
            audit.executemany(
                "INSERT INTO audit_metadata(key,value_json) VALUES (?,?)",
                ((key, json.dumps(value, ensure_ascii=False, sort_keys=True)) for key, value in metadata.items()),
            )
            audit.execute("COMMIT")

        result = {
            "scanned_images": processed,
            "affected_images": affected_images,
            "issue_groups": group_count,
            "issue_counts": issue_counts,
            "scan_failures": scan_failures,
            "audit_ref": MATERIAL_INTEGRITY_REF,
            "metadata": metadata,
        }
        checkpoint("AUDITING_MATERIAL_INTEGRITY")
        context.artifacts.atomic_write_json(context.task.task_id, RESULT_REF, result)
        append_task_log(context, "finished", TaskStatus.SUCCEEDED.value)
        return TaskStatus.SUCCEEDED, RESULT_REF

    def _run_annotation_projection_repair(self, context, manifest, payload):
        """Reconcile stale Material previews from frozen formal GT, never edit GT."""
        from .annotations import annotation_summary

        _project_id, project_path = _safe_project_path(self.data_dir, context.task.project_id)
        if not manifest.frozen():
            raise BatchRequestError(
                "BATCH_SELECTION_NOT_FROZEN", "缩略图修复缺少冻结范围", 409,
            )
        if context.task.retry_of:
            while stale := manifest.rows(("failed", "running")):
                _check_active(context, "REPAIRING_ANNOTATION_PREVIEWS")
                manifest.transition([item["image_id"] for item in stale], "pending")
        annotations = AnnotationRepository(project_path)
        materials = MaterialRepository(project_path)
        total = int(manifest.summary().get("total") or 0)
        append_task_log(
            context, "processing",
            f"operation={BatchOperation.REPAIR_ANNOTATION_PROJECTIONS.value} total={total}",
        )
        while batch := manifest.rows():
            _check_active(context, "REPAIRING_ANNOTATION_PREVIEWS")
            batch = list(batch[:REMAP_BATCH_SIZE])
            ids = [str(row["image_id"]) for row in batch]
            manifest.transition(ids, "running")
            # Shared lifecycle fence prevents concurrent human GT updates or
            # source deletion between the CAS check and derived projection write.
            with material_annotation_lifecycle_fence(project_path):
                current = annotations.get_many(ids)
                projected = {
                    str(row["id"]): row for row in materials.get_many(ids)
                }
                for item in batch:
                    image_id = str(item["image_id"])
                    plan = {}
                    try:
                        plan = json.loads(item["tombstone_json"] or "{}")
                        if plan.get("operation") != BatchOperation.REPAIR_ANNOTATION_PROJECTIONS.value:
                            raise ValueError("PROJECTION_REPAIR_PLAN_INVALID")
                        record = current[image_id]
                        material = projected.get(image_id)
                        if material is None:
                            raise ValueError("MATERIAL_NOT_FOUND")
                        if (
                            int(record.get("version") or 0) != int(plan.get("expected_version") or 0)
                            or annotations.record_digest(record) != str(plan.get("expected_digest") or "")
                        ):
                            raise ValueError("ANNOTATION_CHANGED_DURING_PROJECTION_REPAIR")
                        if int(record.get("version") or 0) <= 0:
                            raise ValueError("LEGACY_ANNOTATION_REQUIRES_FORMAL_MIGRATION")
                        formal = annotation_summary(
                            record.get("boxes") or [], record.get("annotation_state"),
                        )
                        expected_preview = formal["annotation_preview"]
                        if (material.get("annotation_preview") or []) == expected_preview:
                            plan["noop_resolved"] = True
                        else:
                            projection = {
                                key: formal[key]
                                for key in (
                                    "annotation_preview", "labels", "label_counts",
                                    "box_count", "annotation_state", "annotated",
                                )
                            }
                            projection.update({
                                "annotation_scope": list(record.get("annotation_scope") or []),
                                "annotation_version": int(record["version"]),
                                "annotation_hash": annotations.record_digest(record),
                            })
                            materials.patch_annotation_projections({image_id: projection})
                            updated = materials.get(image_id)
                            if updated is None or (updated.get("annotation_preview") or []) != expected_preview:
                                raise ValueError("PROJECTION_REPAIR_NOT_PERSISTED")
                            plan["projection_repaired"] = True
                        manifest.database.execute(
                            "UPDATE selection SET tombstone_json=? WHERE image_id=?",
                            (json.dumps(plan, ensure_ascii=False, sort_keys=True), image_id),
                        )
                        manifest.transition([image_id], "succeeded")
                    except (PermissionError, InterruptedError):
                        raise
                    except Exception as error:
                        public_error = redact_storage_error(error)
                        manifest.transition([image_id], "failed", public_error)
                        append_task_log(
                            context, "projection_repair_conflict",
                            f"image_id={image_id} error={public_error}",
                        )
            checkpoint = manifest.summary()
            context.save_checkpoint(checkpoint)
            _check_active(
                context, "REPAIRING_ANNOTATION_PREVIEWS",
                f"正在校验缩略图派生框 {checkpoint['processed']}/{max(1, total)}",
                min(99.0, round(checkpoint["processed"] * 99.0 / max(1, total), 1)),
            )
        summary = manifest.summary()
        repaired = noop = 0
        for row in manifest.database.execute(
            "SELECT tombstone_json FROM selection WHERE state='succeeded'"
        ):
            plan = json.loads(row[0] or "{}")
            repaired += int(bool(plan.get("projection_repaired")))
            noop += int(bool(plan.get("noop_resolved")))
        summary.update({
            "changed_images": repaired,
            "noop_resolved": noop,
            "audit_task_id": str((payload.get("options") or {}).get("audit_task_id") or ""),
        })
        context.save_checkpoint(summary)
        context.artifacts.atomic_write_json(context.task.task_id, RESULT_REF, summary)
        status = (
            TaskStatus.PARTIAL_SUCCESS if summary["failed"] and summary["succeeded"]
            else TaskStatus.FAILED if summary["failed"]
            else TaskStatus.SUCCEEDED
        )
        append_task_log(context, "finished", status.value)
        return status, RESULT_REF

    def _run_annotation_remap(self, context, manifest, payload):
        options = dict((payload or {}).get("options") or {})
        repair_mode = bool(options.get("repair_mode"))
        mapping_options = [
            dict(item) for item in (options.get("mappings") or [])
            if isinstance(item, dict)
        ]
        multi_mapping_mode = repair_mode and bool(mapping_options)
        sources = list(dict.fromkeys(
            str(value).strip()
            for value in (
                [item.get("source_label") for item in mapping_options]
                if multi_mapping_mode
                else options.get("source_labels")
                or [options.get("source_label")]
            )
            if str(value or "").strip()
        ))
        target = str(options.get("target_label") or "").strip()
        if (
            not sources
            or (not multi_mapping_mode and (not target or target in sources))
            or any(
                not str(item.get("target_label") or "").strip()
                or str(item.get("target_label") or "").strip()
                == str(item.get("source_label") or "").strip()
                for item in mapping_options
            )
        ):
            raise BatchRequestError(
                "MATERIAL_REMAP_INVALID",
                "标签变换任务的来源标签和目标标签无效",
                409,
            )
        source_text = "、".join(sources[:3])
        if len(sources) > 3:
            source_text += f" 等 {len(sources)} 个标签"
        project = str(context.task.project_id or "").strip()
        if (
            not project
            or any(character in project for character in ('/', '\\'))
            or not all(character.isalnum() or character in {'_', '-'} for character in project)
        ):
            raise ValueError('project id must be one safe path component')
        projects_root = (self.data_dir / 'projects').resolve()
        project_path = (projects_root / project).resolve()
        if project_path.parent != projects_root:
            raise ValueError('project id escaped projects root')
        if not manifest.frozen():
            raise BatchRequestError(
                "BATCH_SELECTION_NOT_FROZEN",
                "标签变换任务缺少已冻结素材范围",
                409,
            )
        if context.task.retry_of:
            while failed := manifest.rows(("failed",)):
                _check_active(context, "REMAPPING_ANNOTATION_LABELS")
                manifest.transition(
                    [row["image_id"] for row in failed], "pending"
                )

        annotations = AnnotationRepository(project_path)
        materials = MaterialRepository(project_path)
        total = max(0, int(manifest.summary().get("total") or 0))
        append_task_log(
            context, "processing",
            f"operation={BatchOperation.REMAP_ANNOTATION_LABELS.value} total={total}",
        )

        expected_targets = {
            str(item.get("source_label") or "").strip():
            str(item.get("target_label") or "").strip()
            for item in mapping_options
        }
        if multi_mapping_mode and len(expected_targets) != len(mapping_options):
            raise BatchRequestError(
                "MATERIAL_REMAP_INVALID",
                "同一个来源标签不能在一个修复任务中映射到多个目标",
                409,
            )

        def target_class_ids(targets):
            meta_path = project_path / "meta.json"
            if not meta_path.is_file():
                raise BatchRequestError(
                    "MATERIAL_REMAP_PROJECT_MISSING",
                    "项目标签配置不存在",
                    409,
                )
            project_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            labels = list(project_meta.get("labels") or [])
            metadata = list(project_meta.get("label_meta") or [])
            wanted = set(targets)
            resolved = {}
            for index, code in enumerate(labels):
                code = str(code)
                if code not in wanted:
                    continue
                info = (
                    metadata[index]
                    if index < len(metadata) and isinstance(metadata[index], dict)
                    else {}
                )
                if (
                    str(info.get("status") or "active").lower() == "active"
                    and info.get("active") is not False
                ):
                    resolved[code] = index
            if set(resolved) != wanted:
                raise BatchRequestError(
                    "MATERIAL_REMAP_TARGET_UNAVAILABLE",
                    "目标标签已不存在或已停用，请重新确认标签映射",
                    409,
                )
            return resolved

        while batch := manifest.rows():
            _check_active(context, "REMAPPING_ANNOTATION_LABELS")
            batch = list(batch[:REMAP_BATCH_SIZE])
            ids = [str(row["image_id"]) for row in batch]
            manifest.transition(ids, "running")
            target_ids = target_class_ids(
                set(expected_targets.values()) if multi_mapping_mode else {target}
            )
            current_target_id = target_ids.get(target)
            existing = (
                set(ids)
                if repair_mode
                else {str(item["id"]) for item in materials.get_many(ids)}
            )
            missing_ids = [image_id for image_id in ids if image_id not in existing]
            if missing_ids:
                manifest.transition(missing_ids, "failed", "MATERIAL_NOT_FOUND")
                for image_id in missing_ids:
                    append_task_log(
                        context, "remap_missing_material",
                        f"image_id={image_id}",
                    )
            active_rows = [
                row for row in batch if str(row["image_id"]) in existing
            ]
            active_ids = [str(row["image_id"]) for row in active_rows]
            snapshots = annotations.get_many(active_ids) if active_ids else {}
            executable = []
            plans = {}
            failed = []
            for row in active_rows:
                image_id = str(row["image_id"])
                current = snapshots[image_id]
                current_digest = annotations.record_digest(current)
                plan = None
                if row["tombstone_json"]:
                    try:
                        plan = json.loads(row["tombstone_json"])
                    except (TypeError, ValueError):
                        plan = None
                if not isinstance(plan, dict):
                    if multi_mapping_mode:
                        failed.append((image_id, "MATERIAL_REMAP_PLAN_CONFLICT"))
                        continue
                    preview = annotations.plan_label_remap(
                        current,
                        source_labels=sources,
                        target_label=target,
                        target_class_id=current_target_id,
                    )
                    plan = {
                        "operation": BatchOperation.REMAP_ANNOTATION_LABELS.value,
                        "source_labels": sources,
                        "source_label": sources[0] if len(sources) == 1 else "",
                        "target_label": target,
                        "source_digest": current_digest,
                        "result_digest": preview["content_digest"],
                        "changed_boxes": int(preview["changed_boxes"]),
                        "changed_scope": int(preview.get("changed_scope") or 0),
                        "target_class_id": int(current_target_id),
                        "planned_at": utc_now(),
                    }
                    manifest.database.execute(
                        "UPDATE selection SET tombstone_json=? WHERE image_id=?",
                        (json.dumps(plan, ensure_ascii=False), image_id),
                    )
                plan_sources = list(dict.fromkeys(
                    str(value).strip()
                    for value in (
                        plan.get("source_labels")
                        or [plan.get("source_label")]
                    )
                    if str(value or "").strip()
                ))
                plan_mappings = [
                    dict(item) for item in (plan.get("mappings") or [])
                    if isinstance(item, dict)
                ]
                if multi_mapping_mode:
                    plan_targets = {
                        str(item.get("source_label") or "").strip():
                        str(item.get("target_label") or "").strip()
                        for item in plan_mappings
                    }
                    plan_valid = bool(plan_mappings) and all(
                        expected_targets.get(source) == mapped_target
                        for source, mapped_target in plan_targets.items()
                    ) and set(plan_sources) == set(plan_targets)
                else:
                    plan_valid = (
                        plan_sources == sources
                        and str(plan.get("target_label") or "") == target
                    )
                if (
                    plan.get("operation") != BatchOperation.REMAP_ANNOTATION_LABELS.value
                    or not plan_valid
                ):
                    failed.append((image_id, "MATERIAL_REMAP_PLAN_CONFLICT"))
                    continue
                source_digest = str(plan.get("source_digest") or "")
                result_digest = str(plan.get("result_digest") or "")
                try:
                    if multi_mapping_mode:
                        target_identity_changed = any(
                            int(item.get("target_class_id"))
                            != int(target_ids.get(str(item.get("target_label") or "")))
                            for item in plan_mappings
                        )
                    else:
                        planned_target_id = plan.get("target_class_id")
                        target_identity_changed = (
                            planned_target_id is not None
                            and int(planned_target_id) != int(current_target_id)
                        )
                except (TypeError, ValueError):
                    failed.append((image_id, "MATERIAL_REMAP_PLAN_CONFLICT"))
                    continue
                if target_identity_changed and repair_mode:
                    failed.append((
                        image_id,
                        "LABEL_INTEGRITY_TARGET_IDENTITY_CHANGED",
                    ))
                    continue
                if current_digest == source_digest and target_identity_changed:
                    preview = annotations.plan_label_remap(
                        current,
                        source_labels=sources,
                        target_label=target,
                        target_class_id=current_target_id,
                    )
                    plan.update({
                        "result_digest": preview["content_digest"],
                        "changed_boxes": int(preview["changed_boxes"]),
                        "changed_scope": int(preview.get("changed_scope") or 0),
                        "target_class_id": int(current_target_id),
                        "replanned_at": utc_now(),
                    })
                    result_digest = str(plan["result_digest"])
                    manifest.database.execute(
                        "UPDATE selection SET tombstone_json=? WHERE image_id=?",
                        (json.dumps(plan, ensure_ascii=False), image_id),
                    )
                if current_digest not in {source_digest, result_digest}:
                    current_references = {
                        str(box.get("label") or box.get("code") or "").strip()
                        for box in (current.get("boxes") or [])
                        if str(box.get("label") or box.get("code") or "").strip()
                    }
                    current_references.update(
                        str(value).strip()
                        for value in (current.get("annotation_scope") or [])
                        if str(value or "").strip()
                    )
                    if repair_mode and not (
                        set(plan_sources) & current_references
                    ):
                        plan.update({
                            "noop_resolved": True,
                            "resolved_at": utc_now(),
                        })
                        manifest.database.execute(
                            "UPDATE selection SET tombstone_json=? WHERE image_id=?",
                            (json.dumps(plan, ensure_ascii=False), image_id),
                        )
                        manifest.transition([image_id], "succeeded")
                        continue
                    failed.append((
                        image_id,
                        "ANNOTATION_CHANGED_DURING_REMAP",
                    ))
                    continue
                plans[image_id] = plan
                executable.append({
                    "image_id": image_id,
                    "expected_digest": current_digest,
                    **({"mappings": plan_mappings} if multi_mapping_mode else {}),
                })

            if executable:
                outcomes = annotations.remap_labels_if_digests(
                    executable,
                    source_labels=sources,
                    target_label=target,
                    target_class_id=current_target_id,
                    project_material=True,
                )
                for outcome in outcomes:
                    image_id = str(outcome["image_id"])
                    plan = plans[image_id]
                    if outcome.get("status") == "stale":
                        failed.append((
                            image_id,
                            "ANNOTATION_CHANGED_DURING_REMAP",
                        ))
                        continue
                    if str(outcome.get("content_digest") or "") != str(
                        plan.get("result_digest") or ""
                    ):
                        failed.append((
                            image_id,
                            "ANNOTATION_REMAP_RESULT_MISMATCH",
                        ))
                        continue
                    manifest.transition([image_id], "succeeded")

            for image_id, error in failed:
                manifest.transition([image_id], "failed", error)
                append_task_log(
                    context, "remap_conflict",
                    f"image_id={image_id} error={error}",
                )

            checkpoint = manifest.summary()
            processed = max(0, int(checkpoint.get("processed") or 0))
            progress = min(
                99.0, round(processed * 99.0 / max(1, total), 1)
            )
            current_item = (
                f"正在批量修复标签 {processed}/{max(1, total)} · "
                f"{len(mapping_options)} 个映射"
                if multi_mapping_mode else
                f"正在批量统一标签 {processed}/{max(1, total)} · "
                f"{source_text} → {target}"
            )
            context.save_checkpoint(checkpoint)
            _check_active(
                context,
                "REMAPPING_ANNOTATION_LABELS",
                current_item,
                progress,
            )
            append_task_log(
                context, "checkpoint",
                f"processed={processed} succeeded={checkpoint['succeeded']} "
                f"failed={checkpoint['failed']}",
            )

        summary = manifest.summary()
        summary.update(manifest.remap_result())
        summary.update({
            "source_labels": sources,
            "source_label": sources[0] if len(sources) == 1 else "",
            "target_label": target,
            "mappings": mapping_options if multi_mapping_mode else [],
            "mapping_count": len(mapping_options) if multi_mapping_mode else 1,
            **{
                key: int(options.get(key) or 0)
                for key in (
                    "candidate_images", "still_requires_repair",
                )
                if options.get(key) is not None
            },
        })
        summary["already_resolved"] = (
            int(options.get("already_resolved") or 0)
            + int(summary.get("noop_resolved") or 0)
        )
        if (
            not summary["failed"]
            and bool(options.get("retire_sources_on_success"))
        ):
            annotation_remaining = annotations.label_reference_preview(sources)
            if int(annotation_remaining.get("affected_images") or 0) != 0:
                raise BatchRequestError(
                    "ANNOTATION_REMAP_REFERENCES_REMAIN",
                    "ANNOTATION_REMAP_REFERENCES_REMAIN: 标签统一已处理完成，但 AnnotationRepository 仍有来源标签引用，已阻止自动退役",
                    409,
                )
            material_remaining = materials.label_reference_preview(sources)
            if int(material_remaining.get("affected_images") or 0) != 0:
                raise BatchRequestError(
                    "MATERIAL_REMAP_REFERENCES_REMAIN",
                    "MATERIAL_REMAP_REFERENCES_REMAIN: 标签统一已处理完成，但 MaterialRepository 投影仍有来源标签引用，已阻止自动退役",
                    409,
                )
            summary["retirement_verification"] = {
                "annotation_repository": annotation_remaining,
                "material_repository": material_remaining,
            }
            summary["retired_source_labels"] = _retire_merged_source_labels(
                self.data_dir, project, sources, target,
            )
        context.save_checkpoint(summary)
        context.artifacts.atomic_write_json(
            context.task.task_id, RESULT_REF, summary
        )
        status = (
            TaskStatus.PARTIAL_SUCCESS
            if summary["failed"] and summary["succeeded"]
            else TaskStatus.FAILED
            if summary["failed"]
            else TaskStatus.SUCCEEDED
        )
        append_task_log(context, "finished", status.value)
        return status, RESULT_REF

    def _delete_sources(self, context, manifest, materials, batch, sources, source_cache, providers):
        # Cross-project aliases, retired records and detached consumers cannot
        # yet be proven absent. Never turn a logical-delete authorization into GC.
        for item in batch:
            manifest.transition([item['image_id']], 'failed', 'PHYSICAL_DELETE_SAFETY_UNVERIFIED')
        return

    def _delete_index_rows(
        self,
        context,
        manifest,
        materials,
        image_ids,
        project_path,
        *,
        required_claim=None,
    ):
        """Delete material identity and Ground Truth through their existing owners."""
        annotations = AnnotationRepository(project_path)
        for image_id in image_ids:
            token = _material_delete_token(context.task.task_id, image_id)
            legacy = Path(project_path) / "annotations" / f"{image_id}.json"
            legacy_bytes = legacy.read_bytes() if legacy.is_file() else None
            try:
                with label_governance_fence(project_path), material_annotation_lifecycle_fence(project_path):
                    if materials.get(image_id) is None and materials.retirement(context.task.task_id,image_id):
                        annotations.complete_delete(token)
                        manifest.transition([image_id], 'succeeded')
                        continue
                    self._assert_integrity_delete_identity(
                        manifest, materials, annotations, image_id,
                    )
                    current = materials.get(image_id)
                    if required_claim is not None and (
                        current is None
                        or str(current.get(MATERIAL_BATCH_DELETE_CLAIM_FIELD) or "")
                        != str(required_claim)
                    ):
                        raise BatchRequestError(
                            "MATERIAL_DELETE_CLAIM_LOST",
                            "素材源删除占用已丢失，已阻止索引提交",
                            409,
                        )
                    retired_annotation = annotations.get(image_id)
                    annotations.prepare_delete(token, [image_id])
                    legacy.unlink(missing_ok=True)
                    annotations.finalize_delete(token)
                    try:
                        request = context.artifacts.read_json(context.task.task_id, context.task.payload_ref, default={})
                        materials.retire_many([image_id], task_id=context.task.task_id,
                            actor_id=str((request.get('options') or {}).get('actor_id') or ''),
                            annotations={image_id: retired_annotation})
                    except Exception:
                        annotations.restore_delete(token)
                        if legacy_bytes is not None and not legacy.exists():
                            legacy.parent.mkdir(parents=True, exist_ok=True)
                            legacy.write_bytes(legacy_bytes)
                        raise
                    annotations.complete_delete(token)
                    manifest.transition([image_id], "succeeded")
            except (PermissionError, InterruptedError):
                raise
            except Exception as error:
                if materials.get(image_id) is not None:
                    try:
                        annotations.restore_delete(token)
                    except Exception:
                        pass
                    if legacy_bytes is not None and not legacy.exists():
                        legacy.parent.mkdir(parents=True, exist_ok=True)
                        legacy.write_bytes(legacy_bytes)
                manifest.transition([image_id], "failed", redact_storage_error(error))
                append_task_log(
                    context,
                    "index_delete_error",
                    f"image_id={image_id} {redact_storage_error(error)}",
                )

    def _assert_integrity_delete_identity(
        self, manifest, materials, annotations, image_id,
    ):
        if not manifest.database.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='integrity_plan_items'"
        ).fetchone():
            return
        from .training_compatibility import _file_digest
        schema = manifest.database.execute("SELECT value FROM meta WHERE key='label_schema_digest'").fetchone()
        if not schema or schema[0] != _file_digest(materials.project_path / 'meta.json'):
            raise BatchRequestError(
                'MATERIAL_INTEGRITY_PLAN_STALE', '标签映射已变化，请重新审计和生成治理预览', 409,
            )
        current = materials.get(str(image_id))
        row = manifest.database.execute(
            "SELECT i.group_key AS planned_group_key,i.content_sha256,i.annotation_digest,"
            "g.group_key AS keeper_group_key,"
            "g.keeper_image_id,g.keeper_content_sha256,g.keeper_annotation_digest,g.keeper_reason "
            "FROM integrity_plan_items i LEFT JOIN integrity_plan_groups g "
            "ON g.group_key=i.group_key WHERE i.image_id=?",
            (str(image_id),),
        ).fetchone()
        if row is None:
            raise BatchRequestError(
                "MATERIAL_INTEGRITY_ITEM_UNPLANNED",
                "删除项不属于冻结治理计划", 409,
            )

        def matches(candidate_id, expected_hash, expected_annotation):
            material = materials.get(str(candidate_id))
            annotation = annotations.get(str(candidate_id))
            return bool(
                material is not None and annotation is not None
                and str(material.get("content_sha256") or "").lower()
                    == str(expected_hash or "").lower()
                and annotations.record_digest(annotation)
                    == str(expected_annotation or "")
            )

        if not matches(image_id, row["content_sha256"], row["annotation_digest"]):
            raise BatchRequestError(
                "MATERIAL_INTEGRITY_DELETE_IDENTITY_CHANGED",
                "待清理素材身份已变化，已跳过该项", 409,
            )
        if (str(row['planned_group_key']).startswith('DUPLICATE_')
                and row['keeper_group_key'] is None):
            raise BatchRequestError(
                'MATERIAL_INTEGRITY_EXECUTION_INCOMPLETE',
                '重复 GT 组缺少冻结的保留或放弃决策，已阻止删除', 409,
            )
        if row['keeper_group_key'] is not None and not row['keeper_image_id'] and row['keeper_reason'] != "EXPLICIT_DISCARD_UNPROTECTED":
            raise BatchRequestError(
                "MATERIAL_INTEGRITY_EXECUTION_INCOMPLETE",
                "治理计划缺少有效保留项或人工放弃确认", 409,
            )
        if row['keeper_image_id'] and not matches(
            row["keeper_image_id"], row["keeper_content_sha256"],
            row["keeper_annotation_digest"],
        ):
            raise BatchRequestError(
                "MATERIAL_INTEGRITY_KEEPER_CHANGED",
                "本组保留素材已变化，已跳过该组清理", 409,
            )

    def recover(self, context):
        return self.run(context)


def public_batch(task, artifacts, repository=None):
    checkpoint = artifacts.read_json(task.task_id, CHECKPOINT_REF, default={})
    request = artifacts.read_json(task.task_id, task.payload_ref, default={})
    if request.get('operation')=='SMART_AUDIT' and (task.status is TaskStatus.QUEUED or checkpoint.get('execution_generation')!=task.attempt):
        checkpoint={'total':checkpoint.get('total'),'processed':0,'succeeded':0,'failed':0,'selection_frozen':bool(checkpoint.get('selection_frozen'))}
    result = (
        artifacts.read_json(task.task_id, RESULT_REF, default={})
        if request.get("operation") in {
            BatchOperation.REMAP_ANNOTATION_LABELS.value,
            BatchOperation.REPAIR_ANNOTATION_PROJECTIONS.value,
            BatchOperation.AUDIT_LABEL_INTEGRITY.value,
            BatchOperation.AUDIT_MATERIAL_INTEGRITY.value,
            BatchOperation.DELETE_INDEX.value,
        }
        else {}
    )
    if request.get("operation") == "SMART_AUDIT" and task.result_ref:
        result = artifacts.read_json(task.task_id,task.result_ref,default={})
    truth = task_to_public(task, repository) if repository is not None else None
    frozen = bool(checkpoint.get("selection_frozen"))
    error_examples = checkpoint.get("error_examples", [])[:10]
    if task.error and not error_examples:
        error_examples = [{"error": redact_storage_error(task.error)}]
    available = artifacts.artifact_path(task.task_id, task.log_ref).is_file()
    options = dict(request.get("options") or {})
    integrity_progress = {}
    if options.get("material_integrity_plan_id"):
        integrity_progress = {
            "planned_groups": int(options.get("planned_groups") or 0),
            "completed_groups": 0,
            "failed_groups": 0,
            "kept_count": int(options.get("planned_kept") or 0),
            "skipped_groups": int(options.get("planned_skipped_groups") or 0),
        }
        selection_path = artifacts.artifact_path(task.task_id, SELECTION_REF)
        if selection_path.is_file():
            try:
                with closing(sqlite3.connect(
                    selection_path.as_uri() + "?mode=ro", uri=True
                )) as selection:
                    if selection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='integrity_plan_groups'"
                    ).fetchone():
                        integrity_progress["completed_groups"] = int(selection.execute(
                            "SELECT COUNT(*) FROM integrity_plan_groups g "
                            "WHERE NOT EXISTS (SELECT 1 FROM integrity_plan_items i "
                            "JOIN selection s ON s.image_id=i.image_id "
                            "WHERE i.group_key=g.group_key AND s.state<>'succeeded')"
                        ).fetchone()[0])
                        integrity_progress["failed_groups"] = int(selection.execute(
                            "SELECT COUNT(DISTINCT i.group_key) FROM integrity_plan_items i "
                            "JOIN selection s ON s.image_id=i.image_id WHERE s.state='failed'"
                        ).fetchone()[0])
            except sqlite3.Error:
                pass
    remap_sources = []
    remap_target = ""
    retire_sources = False
    if request.get("operation") == BatchOperation.REMAP_ANNOTATION_LABELS.value:
        remap_sources = [
            str(value).strip()
            for value in (options.get("source_labels") or [options.get("source_label")])
            if str(value or "").strip()
        ]
        remap_target = str(options.get("target_label") or "").strip()
        retire_sources = bool(options.get("retire_sources_on_success"))
    repair_stats = {
        key: int(result.get(key, options.get(key)) or 0)
        for key in (
            "candidate", "candidate_images", "still_requires_repair",
            "already_resolved", "mapping_count", "noop_resolved",
        )
        if result.get(key, options.get(key)) is not None
    }
    return {"id": task.task_id, "task_id": task.task_id, "project_id": task.project_id,
            "kind": task.kind.value, "operation": request.get("operation"),
            "status": truth["status"] if truth else task.status.value,
            "persisted_status": truth["persisted_status"] if truth else task.status.value,
            "priority": truth["priority"] if truth else task.priority,
            "queue_rank": truth["queue_rank"] if truth else task.queue_rank,
            "resource_queue_position": truth["resource_queue_position"] if truth else None,
            "resource_queue_position_exact": truth["resource_queue_position_exact"] if truth else False,
            "resource_wait_reason": truth["resource_wait_reason"] if truth else task.resource_wait_reason,
            "worker_id": truth["worker_id"] if truth else task.worker_id,
            "lease_expires_at": truth["lease_expires_at"] if truth else task.lease_expires_at,
            "progress_percent": truth["progress_percent"] if truth else task.progress,
            "stage": truth["phase"] if truth else task.stage,
            "phase": truth["phase"] if truth else task.stage,
            "current_item": truth["current_item"] if truth else task.current_item,
            "total": checkpoint.get("total") if frozen else None,
            "processed": checkpoint.get("processed", 0), "succeeded": checkpoint.get("succeeded", 0),
            "failed": checkpoint.get("failed", 0), "current_image_id": checkpoint.get("current_image_id"),
            "flagged": checkpoint.get("flagged", 0),
            "scan_only": request.get("operation") in {BatchOperation.CLEAN.value,"SMART_AUDIT"},
            "review_required": request.get("operation") == BatchOperation.AI_ANNOTATE.value and task.status is TaskStatus.AWAITING_CONFIRMATION,
            "review_url": (f"/api/v60/projects/{task.project_id}/annotation-tasks/{task.task_id}"
                           if request.get("operation") == BatchOperation.AI_ANNOTATE.value else None),
            "results_url": (f"/api/v62/projects/{task.project_id}/smart-material-audit/{task.task_id}/findings" if request.get("operation")=="SMART_AUDIT" else f"/api/v62/projects/{task.project_id}/material-batches/{task.task_id}/results"
                            if request.get("operation") in {BatchOperation.CLEAN.value,BatchOperation.DELETE_INDEX.value,"SMART_AUDIT"} else None),
            "error_examples": error_examples, "selection_frozen": frozen,
            "result": result if result else None,
            "logical_removed": result.get('logical_removed',checkpoint.get('logical_removed',0)),
            "physical_retained": result.get('physical_retained',checkpoint.get('physical_retained',0)),
            "reclaimed_bytes": 0 if request.get('operation')==BatchOperation.DELETE_INDEX.value else None,
            "reclamation_state": 'DEFERRED_SAFETY_UNVERIFIED' if request.get('operation')==BatchOperation.DELETE_INDEX.value else None,
            "source_labels": remap_sources,
            "target_label": remap_target,
            "mappings": list(options.get("mappings") or []),
            "retire_sources_on_success": retire_sources,
            "changed_images": result.get("changed_images"),
            "changed_boxes": result.get("changed_boxes"),
            "material_integrity_audit_id": options.get("material_integrity_audit_id"),
            "material_integrity_plan_id": options.get("material_integrity_plan_id"),
            **integrity_progress,
            **repair_stats,
            **({"smart_audit_progress":checkpoint.get("smart_audit_progress"),"smart_audit_summary":result,
                "attempt":task.attempt,"result_ready":bool(task.result_ref)} if request.get("operation")=="SMART_AUDIT" else {}),
            "log_available": available, "log_ref": task.log_ref if available else None,
            "created_at": task.created_at, "updated_at": task.updated_at, "finished_at": task.finished_at}


def create_training_integrity_plan(project_id, audit_task, materials, repository, artifacts, payload, selection_provider=None, *, actor=None):
    """Resolve training issue selection on the server, then use the only deletion plan."""
    from .training_compatibility import diagnose_training_duplicates, evaluate_training_compatibility_projection
    body = payload if isinstance(payload, dict) else {}
    if (body.get('expected_material_revision') != materials.current_revision()
            or body.get('expected_annotation_revision') != AnnotationRepository(materials.project_path).current_revision()):
        raise BatchRequestError('MATERIAL_INTEGRITY_SELECTION_STALE', '素材或标注已变化，请重新检查训练输入', 409)
    source_task_id = str(body.get('training_task_id') or '')
    selection = body.get('training_selection')
    if source_task_id:
        source = repository.get(source_task_id)
        if source is None or source.project_id != str(project_id) or source.kind is not TaskKind.TRAINING:
            raise BatchRequestError('MATERIAL_INTEGRITY_TRAINING_NOT_FOUND', '训练任务不存在', 404)
        selection = artifacts.read_json(source_task_id, source.payload_ref, default=None)
    if not isinstance(selection, dict):
        raise BatchRequestError('MATERIAL_INTEGRITY_SELECTION_INVALID', '训练输入范围不可用', 422)
    if not source_task_id and selection_provider is not None:
        selection = selection_provider(project_id, None, selection)
    algorithm_id = str(selection.get('algorithm_asset_id') or '')
    if algorithm_id:
        from .algorithms import list_algorithms
        algorithm = next((row for row in list_algorithms(materials.project_path/'algorithms.json') if str(row.get('id') or '')==algorithm_id),None)
        if algorithm is None:
            raise BatchRequestError('TRAINING_ALGORITHM_NOT_FOUND','训练算法不存在',404)
        result = evaluate_training_compatibility_projection(materials.project_path.parent.parent,materials.project_path,selection,algorithm)
    else:
        # Read compatibility for historical duplicate-only tasks with no algorithm
        # identity; never pretend this is a full label-contract diagnosis.
        result = diagnose_training_duplicates(materials.project_path, selection, current_only=bool(source_task_id))
    query = str(body.get('query') or '').strip().casefold()
    issue_type = str(body.get('issue_type') or '')
    if body.get('all_issues') is True:
        query, issue_type = '', ''
    if len(query) > 256 or len(issue_type)>128:
        raise BatchRequestError('MATERIAL_INTEGRITY_FILTER_INVALID', '训练冲突筛选无效', 422)
    candidates = {str(item['image_id']) for item in result.issues
        if (not issue_type or item['issue_type'] == issue_type)
        and (not query or any(query in str(item.get(key) or '').casefold()
            for key in ('image_id', 'filename', 'content_sha256', 'duplicate_group_id')))}
    selected = body.get('image_ids') or []
    excluded = body.get('excluded_image_ids') or []
    for values in (selected, excluded):
        if not isinstance(values, list) or len(values) > 10000 or any(not isinstance(value, str) for value in values):
            raise BatchRequestError('MATERIAL_INTEGRITY_SELECTION_INVALID', '选择或排除范围无效', 422)
    if not set(selected).issubset(candidates) or not set(excluded).issubset(candidates):
        raise BatchRequestError('MATERIAL_INTEGRITY_SELECTION_CHANGED', '所选图片不属于当前训练冲突筛选，请重新检查', 409)
    filtered_count = len(candidates)
    chosen = candidates - set(excluded) if body.get('all_filtered') is True or body.get('all_issues') is True else set(selected)
    previous_execution = str(body.get('previous_execution_task_id') or '')
    retained_count = 0
    if previous_execution:
        previous = repository.get(previous_execution)
        if (previous is None or previous.project_id != str(project_id)
                or previous.kind is not TaskKind.MATERIAL_BATCH):
            raise BatchRequestError('MATERIAL_INTEGRITY_EXECUTION_UNAVAILABLE', '原删除任务不存在或不属于当前项目', 404)
        request = artifacts.read_json(previous.task_id, previous.payload_ref, default={})
        if (request.get('operation') != BatchOperation.DELETE_INDEX.value
                or not (request.get('options') or {}).get('material_integrity_plan_id')
                or previous.status in _ACTIVE_INPUT_STATUSES):
            raise BatchRequestError('MATERIAL_INTEGRITY_EXECUTION_NOT_READY', '原任务仍在执行或不是安全治理任务，请查看原任务', 409)
        path = artifacts.artifact_path(previous.task_id, SELECTION_REF)
        if not path.is_file():
            raise BatchRequestError('MATERIAL_INTEGRITY_EXECUTION_UNAVAILABLE', '原任务冻结选择不可用', 409)
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as frozen:
            remaining = {str(row[0]) for row in frozen.execute("SELECT image_id FROM selection WHERE state<>'succeeded'")}
        retained_count = len(remaining)
        chosen = candidates.intersection(remaining)
    if not chosen:
        raise BatchRequestError('MATERIAL_INTEGRITY_SELECTION_EMPTY', '当前范围没有已选择的冲突素材', 409)
    if body.get('delete_mode') == 'KEEP_ONE':
        plan = create_material_integrity_plan(project_id,audit_task,materials,repository,artifacts,
            {'scope':'SELECTED_IMAGES','delete_mode':'KEEP_ONE','manual_decisions':body.get('manual_decisions') or {}},candidate_image_ids=chosen,actor=actor)
    else:
        plan = _general_delete_preview(project_id,materials,
            MaterialSelectionSpec.from_mapping({'scope':'SELECTED','image_ids':sorted(chosen),'repository_revision':materials.current_revision()}),
            {},repository,artifacts,actor,None,owner_task_id=audit_task.task_id)
    # The exact full range remains in the same durable plan; return bounded preview only.
    plan.pop('selection_spec', None)
    plan['training_selection'] = {'filtered_count':filtered_count, 'selected_count':len(chosen),
        'excluded_count':len(excluded), 'query':query, 'issue_type':issue_type,
        'retained_execution_count':retained_count, 'previous_execution_task_id':previous_execution or None,
        'training_task_id':source_task_id or None, 'evidence_basis':'current_canonical_annotations'}
    return plan


def material_integrity_gt_comparison(project_id, materials, repository, artifacts, payload):
    from .training_compatibility import diagnose_annotation_conflict

    ids = payload.get('image_ids')
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 100
            or any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids)):
        raise BatchRequestError('GT_COMPARISON_SELECTION_INVALID', '请选择1–100张同SHA素材', 422)
    annotations = AnnotationRepository(materials.project_path)
    revisions = materials.current_revision(), annotations.current_revision()
    for name, revision in zip(('expected_material_revision', 'expected_annotation_revision'), revisions):
        if payload.get(name) is not None and payload[name] != revision:
            raise BatchRequestError('MATERIAL_INTEGRITY_AUDIT_STALE', '素材或GT已变化，请重新检查', 409)
    current = {str(row['id']): row for row in materials.get_many(ids)}
    if set(current) != set(ids):
        raise BatchRequestError('GT_COMPARISON_IDENTITY_CHANGED', '部分素材不属于当前项目或已删除', 409)
    formal = annotations.get_many(ids)
    reasons = _historical_material_references(project_id, materials.project_path, repository, artifacts,
        with_reasons=True, reference_image_ids=ids)
    rows = []
    for image_id in ids:
        material, gt = current[image_id], formal.get(image_id) or {}
        protection = list(reasons.get(image_id, []))
        if str(material.get('split') or '').lower() == 'test':
            protection.append({'reason': 'CURRENT_TEST_ROLE', 'protected': True, 'source': 'material_index'})
        rows.append({'image_id': image_id, 'content_sha256': material.get('content_sha256'),
            'filename': material.get('filename') or image_id, 'width': material.get('width'), 'height': material.get('height'),
            'storage_source_id': material.get('storage_source_id'),
            'import_batch_id': material.get('import_batch_id') or material.get('batch_id'), 'split': material.get('split'),
            'annotation_state': gt.get('annotation_state'), 'annotation_scope': gt.get('annotation_scope') or [],
            'boxes': gt.get('boxes') or [], 'annotation_version': gt.get('version'),
            'reference_reasons': protection, 'protection_reasons': protection,
            'content_url': f'/api/v61/projects/{project_id}/materials/{image_id}/content'})
    if any(not row['content_sha256'] for row in rows):
        raise BatchRequestError('GT_COMPARISON_UNVERIFIED_HASH', '缺少SHA256，不能叠加比较', 409)
    diagnosis = diagnose_annotation_conflict(rows, active_project_label_ids(materials.project_path),
        _material_integrity_import_evidence(project_id, rows, repository, artifacts))
    if revisions != (materials.current_revision(), annotations.current_revision()):
        raise BatchRequestError('MATERIAL_INTEGRITY_AUDIT_STALE', '读取期间GT变化，请重新检查', 409)
    return {'items': rows, 'diagnosis': diagnosis, 'material_revision': revisions[0], 'annotation_revision': revisions[1]}


def material_integrity_conflict_review(project_id, audit_task, materials, repository, artifacts,
                                     cursor='', limit=25, observation='', import_batch=''):
    """Page existing audit evidence; no GT writes, extra jobs or plan Owner."""
    from collections import Counter
    from .training_compatibility import _file_digest

    path = artifacts.artifact_path(audit_task.task_id, MATERIAL_INTEGRITY_REF)
    metadata = _audit_metadata(path)
    if (metadata.get('material_revision') != materials.current_revision()
            or metadata.get('annotation_revision') != AnnotationRepository(materials.project_path).current_revision()
            or metadata.get('label_schema_digest', _file_digest(materials.project_path / 'meta.json'))
               != _file_digest(materials.project_path / 'meta.json')):
        raise BatchRequestError('MATERIAL_INTEGRITY_AUDIT_STALE', '素材、GT或标签已变化，请重新审计', 409)
    if metadata.get('gt_diagnosis_version') != 1:
        return {'available': False, 'message': '历史审计未包含GT分类证据，请重新审计；原证据不改写', 'items': []}
    reasons = _historical_material_references(project_id, materials.project_path, repository, artifacts, with_reasons=True)
    protected = {key for key, values in reasons.items() if any(value.get('protected') for value in values)}
    observations, all_images, protected_images = Counter(), set(), set()
    batch_counts = Counter()
    cohort_counts, cohort_mapping_counts = Counter(), Counter()
    summaries, proven, source_reviewable = [], 0, 0
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as audit:
        audit.row_factory = sqlite3.Row
        members = {}
        for row in audit.execute("SELECT group_key,image_id,details_json FROM issue_items WHERE issue_type='DUPLICATE_ANNOTATION_CONFLICT' ORDER BY group_key,image_id"):
            members.setdefault(row['group_key'], []).append({'image_id': row['image_id'], **json.loads(row['details_json'])})
        for group in audit.execute("SELECT * FROM issue_groups WHERE issue_type='DUPLICATE_ANNOTATION_CONFLICT' ORDER BY group_key"):
            items = members.get(group['group_key'], [])
            diagnosis = json.loads(group['details_json']).get('gt_diagnosis') or {}
            ids = {item['image_id'] for item in items}
            protected_here = ids & protected | {item['image_id'] for item in items if str(item.get('split') or '').lower() == 'test'}
            batches = sorted({str(batch) for item in items for batch in item.get('import_batch_ids') or
                              ([item['import_batch_id']] if item.get('import_batch_id') else [])})
            batch_counts.update(batches)
            all_images.update(ids)
            protected_images.update(protected_here)
            observations.update(diagnosis.get('observations') or [])
            mapping_proven = bool(diagnosis.get('proven_mapping_error_count') or diagnosis.get('verified_import_mapping_difference_count'))
            proven += mapping_proven
            cohort_counts[diagnosis.get('cohort', 'OTHER')] += 1
            cohort_mapping_counts[diagnosis.get('cohort', 'OTHER')] += mapping_proven
            verified_ids = set(diagnosis.get('verified_source_image_ids') or [])
            unique_verified_batch = any(sum(item.get('import_batch_id') == batch for item in items) == 1
                and any(item['image_id'] in verified_ids and item.get('import_batch_id') == batch for item in items) for batch in batches)
            source_reviewable += unique_verified_batch
            if observation and observation != diagnosis.get('cohort') and observation not in diagnosis.get('observations', []):
                continue
            if import_batch and import_batch not in batches:
                continue
            summaries.append({'group_key': group['group_key'], 'content_sha256': group['content_sha256'],
                'image_count': len(ids), 'protected_count': len(protected_here), 'diagnosis': diagnosis,
                'import_batches': batches,
                'recommendation': {'purpose': 'IDENTITY_RETENTION_NOT_GT_CORRECTNESS',
                    'image_id': _material_integrity_keeper([
                        {'image_id': item['image_id'], 'details': item} for item in items], protected_here),
                    'reason': 'RETAIN_PROTECTED_IDENTITY' if protected_here else 'EXISTING_VERIFIED_KEEPER_RULE'},
                'members': [{'image_id': item['image_id'], 'filename': item.get('filename'),
                    'import_batch_id': item.get('import_batch_id'), 'split': item.get('split'),
                    'annotation_state': item.get('annotation_state'), 'box_count': item.get('box_count'),
                    'labels': item.get('labels'), 'protected': item['image_id'] in protected_here} for item in items[:20]],
                'members_truncated': len(items) > 20})
    visible = [row for row in summaries if row['group_key'] > cursor][:limit + 1]
    metrics = [row['diagnosis'].get('iou_summary') or {} for row in summaries]
    matched = sum(metric.get('matched_count', 0) for metric in metrics)
    coordinate_statistics = {'population': 'DETERMINISTIC_REFERENCE_TO_OTHER_MEMBERS_GREEDY_CANDIDATES',
        'matched_count': matched,
        'min_iou': min((metric['min'] for metric in metrics if metric.get('min') is not None), default=None),
        'mean_iou': sum(metric['mean'] * metric['matched_count'] for metric in metrics if metric.get('mean') is not None) / matched if matched else None,
        'max_pixel_delta': max((metric['max_pixel_delta'] for metric in metrics if metric.get('max_pixel_delta') is not None), default=None),
        'unverifiable_pairs': sum(metric.get('unverifiable_pairs', 0) for metric in metrics),
        'histogram': dict(sum((Counter(metric.get('histogram') or {}) for metric in metrics), Counter()))}
    if (metadata['material_revision'] != materials.current_revision()
            or metadata['annotation_revision'] != AnnotationRepository(materials.project_path).current_revision()
            or metadata['label_schema_digest'] != _file_digest(materials.project_path / 'meta.json')):
        raise BatchRequestError('MATERIAL_INTEGRITY_AUDIT_STALE', '读取期间素材或GT发生变化，请重新审计', 409)
    return {'available': True, 'audit_task_id': audit_task.task_id,
        'material_revision': metadata['material_revision'], 'annotation_revision': metadata['annotation_revision'],
        'label_schema_digest': metadata['label_schema_digest'],
        'total_groups': len(members),
        'filtered_groups': len(summaries), 'total_images': len(all_images),
        'protected_image_count': len(protected_images), 'proven_mapping_groups': proven,
        'manual_review_groups': len(members), 'source_assisted_review_groups': source_reviewable,
        'individual_only_review_groups': len(members) - source_reviewable,
        'observation_counts': dict(observations), 'import_batch_group_counts': dict(batch_counts), 'items': visible[:limit],
        'cohort_counts': dict(cohort_counts), 'cohort_proven_mapping_counts': dict(cohort_mapping_counts),
        'filtered_coordinate_statistics': coordinate_statistics,
        'next_cursor': visible[limit - 1]['group_key'] if len(visible) > limit else None,
        'automatic_gt_write_allowed': False}


def material_integrity_governance_summary(project_id, audit_task, materials, repository, artifacts):
    if audit_task.status is not TaskStatus.SUCCEEDED:
        raise BatchRequestError('MATERIAL_INTEGRITY_AUDIT_NOT_READY', '素材审计尚未完整成功，请查看原任务', 409)
    metadata = _audit_metadata(artifacts.artifact_path(audit_task.task_id, MATERIAL_INTEGRITY_REF))
    stale = (metadata.get('material_revision') != materials.current_revision()
        or metadata.get('annotation_revision') != AnnotationRepository(materials.project_path).current_revision())
    deleted = failed = 0
    cursor = None
    while True:
        page = repository.list(project_id=str(project_id), kinds=[TaskKind.MATERIAL_BATCH], limit=100, cursor=cursor)
        for task in page.items:
            request = artifacts.read_json(task.task_id, task.payload_ref, default={})
            if (request.get('options') or {}).get('material_integrity_audit_id') != audit_task.task_id:
                continue
            truth = public_batch(task, artifacts, repository)
            deleted += int(truth.get('succeeded') or 0)
            failed += int(truth.get('failed') or 0)
        cursor = page.next_cursor
        if not cursor:
            break
    if stale:
        return {'available':False, 'stale':True, 'actually_deleted_count':deleted, 'failed_count':failed,
            'message':'旧审计已过期；已删除数量来自持久任务，不以旧分组推断当前待治理数量，请重新审计'}
    plan = create_material_integrity_plan(project_id, audit_task, materials, repository, artifacts,
        {'scope':'FILTERED'}, persist=False)
    return {'available':True, 'stale':False, 'found_image_count':plan['selected_count'],
        'historical_retained_count':plan['protected_item_count'],
        'pending_image_count':plan['selected_count']-plan['protected_item_count'],
        'safe_delete_count':plan['delete_count'], 'manual_required_count':plan['manual_required_count'],
        'unverifiable_count':plan['unverifiable_count'], 'actually_deleted_count':deleted, 'failed_count':failed,
        'protection_reason_counts':plan.get('protection_reason_counts', {}),
        'historical_reference_count':plan.get('historical_reference_count'),
        'active_reference_count':plan.get('active_reference_count'),
        'current_test_count':plan.get('current_test_count'), 'gt_count':plan.get('gt_count'),
        'reference_diagnostics_state':plan.get('reference_diagnostics_state'),
        'physical_retained_count':plan.get('physical_retained_count'), 'reclaimed_bytes':0,
        'reclamation_state':'DEFERRED_SAFETY_UNVERIFIED',
        'material_revision':plan['material_revision'], 'annotation_revision':plan['annotation_revision']}


def material_batch_router(
    get_project,
    material_store,
    task_repository,
    task_artifacts,
    storage_source_fence=None,
    training_selection_provider=None,
    actor_provider=None,
):
    # FastAPI resolves postponed endpoint annotations in this module's globals.
    # Bind Request only when mounting HTTP routes; workers do not require ASGI.
    global Request
    from fastapi import APIRouter, Body, HTTPException, Request
    from fastapi.responses import FileResponse

    router = APIRouter(prefix="/api/v62/projects/{project_id}/material-batches")
    integrity = APIRouter(prefix="/api/v62/projects/{project_id}/material-integrity")

    def invoke(function, *args):
        try:
            return function(*args)
        except BatchRequestError as error:
            raise HTTPException(error.status_code, detail={"code": error.code, "message": str(error)}) from error
        except (ValueError, TypeError) as error:
            raise HTTPException(422, detail={"code": "INVALID_BATCH_REQUEST", "message": str(error)}) from error

    def require_task(project_id, task_id):
        get_project(project_id)
        task = task_repository().get(task_id)
        if task is None or task.project_id != project_id or task.kind is not TaskKind.MATERIAL_BATCH:
            raise HTTPException(404, detail="material batch not found")
        return task

    def require_integrity_audit(project_id, task_id):
        task = require_task(project_id, task_id)
        request = task_artifacts().read_json(task_id, task.payload_ref, default={})
        if request.get("operation") != BatchOperation.AUDIT_MATERIAL_INTEGRITY.value:
            raise HTTPException(404, detail="material integrity audit not found")
        return task

    @integrity.post('/gt-comparison')
    def integrity_gt_comparison(project_id: str, payload: dict = Body(...)):
        get_project(project_id)
        return invoke(material_integrity_gt_comparison, project_id, material_store(project_id),
            task_repository(), task_artifacts(), payload)

    @router.post("/estimate")
    def estimate(project_id: str, request: Request, payload: dict = Body(...)):
        project = get_project(project_id)
        actor = actor_provider(request, project_id) if actor_provider else {}
        return invoke(lambda: estimate_batch(project_id, material_store(project_id), payload,
            repository=task_repository(),artifacts=task_artifacts(),actor=actor,project=project))

    @router.post("", status_code=202)
    def create(project_id: str, request: Request, payload: dict = Body(...)):
        project = get_project(project_id)
        actor = actor_provider(request, project_id) if actor_provider else {}
        fence = storage_source_fence() if storage_source_fence else nullcontext()
        with fence:
            task = invoke(lambda: create_batch(project_id,material_store(project_id),task_repository(),task_artifacts(),payload,actor=actor,project=project))
        return public_batch(task, task_artifacts(), task_repository())

    @router.get("")
    def list_batches(project_id: str, active_only: bool = False, limit: int = 50, cursor: str = ""):
        get_project(project_id)
        statuses = (
            [
                TaskStatus.QUEUED,
                TaskStatus.RUNNING,
                TaskStatus.CANCEL_REQUESTED,
            ]
            if active_only else None
        )
        try:
            page = task_repository().list(
                project_id=project_id,
                kinds=[TaskKind.MATERIAL_BATCH],
                statuses=statuses,
                limit=limit,
                cursor=cursor or None,
            )
        except ValueError as error:
            raise HTTPException(422, detail=str(error)) from error
        return {
            "items": [
                public_batch(task, task_artifacts(), task_repository())
                for task in page.items
            ],
            "next_cursor": page.next_cursor,
        }

    @router.get("/{task_id}")
    def get(project_id: str, task_id: str):
        return public_batch(require_task(project_id, task_id), task_artifacts(), task_repository())

    @router.post("/{task_id}/cancel")
    def cancel(project_id: str, task_id: str):
        require_task(project_id, task_id)
        return public_batch(task_repository().request_cancel(task_id), task_artifacts(), task_repository())

    @router.get("/{task_id}/results")
    def results(project_id: str, task_id: str, cursor: str = "", limit: int = 100):
        task = require_task(project_id, task_id)
        request = task_artifacts().read_json(task_id, task.payload_ref, default={})
        if request.get("operation") == BatchOperation.DELETE_INDEX.value:
            if not 1 <= limit <= BATCH_SIZE:
                raise HTTPException(422, detail='limit must be between 1 and 500')
            with closing(BatchSelection(task_artifacts().artifact_path(task_id, SELECTION_REF))) as selection:
                rows=selection.database.execute('SELECT image_id,state,error FROM selection WHERE image_id>? ORDER BY image_id LIMIT ?',(cursor,limit)).fetchall()
                next_cursor=rows[-1][0] if rows and selection.database.execute('SELECT 1 FROM selection WHERE image_id>? LIMIT 1',(rows[-1][0],)).fetchone() else None
            return {'items':[{'image_id':row[0],'item_state':row[1],'item_error':row[2],
                'logical_removed':row[1]=='succeeded','physical_retained':True,'reclaimed_bytes':0} for row in rows],
                'succeeded_image_ids':[row[0] for row in rows if row[1]=='succeeded'],'next_cursor':next_cursor,'reclamation_state':'DEFERRED_SAFETY_UNVERIFIED'}
        if request.get("operation") != BatchOperation.CLEAN.value:
            raise HTTPException(409, detail="this task has no cleaning results")
        if not 1 <= limit <= BATCH_SIZE:
            raise HTTPException(422, detail="limit must be between 1 and 500")
        path = task_artifacts().artifact_path(task_id, SELECTION_REF)
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
            database.execute("BEGIN")
            if database.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='clean_results'").fetchone() is None:
                return {"items": [], "next_cursor": None, "scan_only": True}
            rows = database.execute(
                "SELECT r.image_id,r.result_json,s.state,s.error FROM clean_results r "
                "JOIN selection s ON s.image_id=r.image_id WHERE r.image_id>? ORDER BY r.image_id LIMIT ?",
                (cursor, limit),
            ).fetchall()
            next_cursor = rows[-1][0] if rows and database.execute(
                "SELECT 1 FROM clean_results WHERE image_id>? LIMIT 1", (rows[-1][0],),
            ).fetchone() else None
            return {"items": [{**json.loads(row[1]), "item_state": row[2], "item_error": row[3]} for row in rows],
                    "next_cursor": next_cursor, "scan_only": True}

    @router.post("/{task_id}/retry", status_code=202)
    def retry(project_id: str, task_id: str):
        task = require_task(project_id, task_id)
        if "materials.smart_audit" in task.required_capabilities:
            raise HTTPException(409,detail="请从智能分析入口核验开关并重试")
        if task.status not in {TaskStatus.FAILED, TaskStatus.PARTIAL_SUCCESS, TaskStatus.CANCELLED,
                               TaskStatus.BLOCKED_BY_ENVIRONMENT, TaskStatus.BLOCKED_BY_HARDWARE}:
            raise HTTPException(409, detail="only incomplete terminal batches can be retried")
        fence = storage_source_fence() if storage_source_fence else nullcontext()
        with fence:
            retried = task_repository().retry(task_id)
        return public_batch(retried, task_artifacts(), task_repository())

    @router.get("/{task_id}/log")
    def log(project_id: str, task_id: str):
        task = require_task(project_id, task_id)
        path = task_artifacts().artifact_path(task_id, task.log_ref)
        if not path.is_file():
            raise HTTPException(404, detail="task log unavailable")
        return FileResponse(path, media_type="text/plain", filename=f"{task_id}.log")


    @integrity.get("/audits/latest")
    def latest_integrity_audit(project_id: str):
        """Find the newest durable audit across all task pages, never only the first 50."""
        get_project(project_id)
        repository, artifacts = task_repository(), task_artifacts()
        cursor = None
        newer_deletions = []
        while True:
            page = repository.list(
                project_id=project_id, kinds=[TaskKind.MATERIAL_BATCH],
                limit=100, cursor=cursor,
            )
            for task in page.items:
                request = artifacts.read_json(task.task_id, task.payload_ref, default={})
                operation = request.get("operation") if isinstance(request, dict) else None
                if operation == BatchOperation.AUDIT_MATERIAL_INTEGRITY.value:
                    related = next(
                        (item for item, audit_id in newer_deletions
                         if audit_id == task.task_id), None,
                    )
                    published = public_batch(related, artifacts, repository) if related else None
                    return {
                        "task": public_batch(task, artifacts, repository),
                        "governance_task": published,
                        "deletion_task": published,
                    }
                if operation == BatchOperation.DELETE_INDEX.value:
                    options = request.get("options") or {}
                    newer_deletions.append((
                        task, str(options.get("material_integrity_audit_id") or ""),
                    ))
            cursor = page.next_cursor
            if not cursor:
                return {"task": None, "governance_task": None, "deletion_task": None}

    @integrity.post("/audits", status_code=202)
    def create_integrity_audit(project_id: str):
        get_project(project_id)
        task = create_material_integrity_audit(
            project_id, task_repository(), task_artifacts()
        )
        return public_batch(task, task_artifacts(), task_repository())

    @integrity.get("/audits/{task_id}/groups")
    def integrity_groups(
        project_id: str, task_id: str, cursor: str = "", limit: int = 50,
        issue_type: str = "",
    ):
        from .training_compatibility import _file_digest
        require_integrity_audit(project_id, task_id)
        if not 1 <= int(limit) <= 100:
            raise HTTPException(422, detail="limit must be between 1 and 100")
        path = task_artifacts().artifact_path(task_id, MATERIAL_INTEGRITY_REF)
        if not path.is_file():
            raise HTTPException(409, detail="material integrity audit is not ready")
        clauses, params = ["group_key>?"], [str(cursor or "")]
        if issue_type:
            clauses.append("issue_type=?")
            params.append(str(issue_type).upper())
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
            database.row_factory = sqlite3.Row
            count_where = ' WHERE issue_type=?' if issue_type else ''
            count_params = (str(issue_type).upper(),) if issue_type else ()
            total_images = database.execute('SELECT COUNT(DISTINCT image_id) FROM issue_items' + count_where, count_params).fetchone()[0]
            total_groups = database.execute('SELECT COUNT(*) FROM issue_groups' + count_where, count_params).fetchone()[0]
            metadata = _audit_metadata(path)
            materials = material_store(project_id)
            stale = (metadata.get('material_revision') != materials.current_revision()
                     or metadata.get('annotation_revision') != AnnotationRepository(materials.project_path).current_revision()
                     or metadata.get('label_schema_digest') != _file_digest(materials.project_path / 'meta.json'))
            rows = database.execute(
                "SELECT * FROM issue_groups WHERE " + " AND ".join(clauses)
                + " ORDER BY group_key LIMIT ?",
                (*params, int(limit) + 1),
            ).fetchall()
        visible = rows[:int(limit)]
        return {
            "total_images": total_images,
            "total_groups": total_groups,
            "stale": stale,
            "items": [
                {
                    "group_key": str(row["group_key"]),
                    "issue_type": str(row["issue_type"]),
                    "content_sha256": str(row["content_sha256"]),
                    "image_count": int(row["image_count"]),
                    "details": json.loads(row["details_json"] or "{}"),
                }
                for row in visible
            ],
            "next_cursor": str(visible[-1]["group_key"]) if len(rows) > int(limit) else None,
        }

    @integrity.get("/audits/{task_id}/groups/{group_key:path}/items")
    def integrity_group_items(
        project_id: str, task_id: str, group_key: str,
        cursor: str = "", limit: int = 50,
    ):
        from .training_compatibility import _file_digest
        require_integrity_audit(project_id, task_id)
        if not 1 <= int(limit) <= 100:
            raise HTTPException(422, detail="limit must be between 1 and 100")
        path = task_artifacts().artifact_path(task_id, MATERIAL_INTEGRITY_REF)
        if not path.is_file():
            raise HTTPException(409, detail="material integrity audit is not ready")
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
            database.row_factory = sqlite3.Row
            rows = database.execute(
                "SELECT * FROM issue_items WHERE group_key=? AND image_id>? "
                "ORDER BY image_id LIMIT ?",
                (str(group_key), str(cursor or ""), int(limit) + 1),
            ).fetchall()
            total_images = database.execute('SELECT COUNT(*) FROM issue_items WHERE group_key=?', (str(group_key),)).fetchone()[0]
        visible = rows[:int(limit)]
        ids = [str(row["image_id"]) for row in visible]
        materials = material_store(project_id)
        metadata = _audit_metadata(path)
        if (metadata.get('material_revision') != materials.current_revision()
                or metadata.get('annotation_revision') != AnnotationRepository(materials.project_path).current_revision()
                or metadata.get('label_schema_digest') != _file_digest(materials.project_path / 'meta.json')):
            raise HTTPException(409, detail={
                'code': 'MATERIAL_INTEGRITY_AUDIT_STALE',
                'message': '审计快照已过期，不能混用旧问题分组和当前图片标注，请重新审计',
            })
        current_materials = {
            str(row.get("id")): row for row in materials.get_many(ids)
        }
        annotations = AnnotationRepository(materials.project_path)
        current_annotations = annotations.get_many(ids)
        references = _historical_material_references(
            project_id, materials.project_path, task_repository(), task_artifacts(),
            with_reasons=True, reference_image_ids=ids,
        )
        items = []
        for row in visible:
            image_id = str(row["image_id"])
            material = current_materials.get(image_id) or {}
            annotation = current_annotations.get(image_id) or {}
            snapshot = json.loads(row["details_json"] or "{}")
            items.append({
                "image_id": image_id,
                "content_sha256": str(material.get("content_sha256") or row['content_sha256'] or ''),
                "annotation_version": int(annotation.get('version') or 0),
                "protection_reasons": references.get(image_id, []),
                "filename": material.get("filename") or snapshot.get("filename") or image_id,
                "storage_source_id": material.get("storage_source_id") or snapshot.get("storage_source_id") or "",
                "import_batch_id": material.get("import_batch_id") or material.get("batch_id") or snapshot.get("import_batch_id") or "",
                "split": material.get("split") or snapshot.get("split") or "unassigned",
                "width": int(material.get("width") or 0),
                "height": int(material.get("height") or 0),
                "content_url": f"/api/v61/projects/{project_id}/materials/{image_id}/content",
                "annotation_state": annotation.get("annotation_state") or snapshot.get("annotation_state") or "unannotated",
                "annotation_scope": list(annotation.get("annotation_scope") or []),
                "boxes": list(annotation.get("boxes") or []),
                "snapshot": snapshot,
            })
        from .training_compatibility import diagnose_annotation_conflict
        return {
            "group_key": str(group_key),
            "total_images": total_images,
            "items": items,
            "comparison_scope": "PAGE_MEMBERS",
            "gt_diagnosis": diagnose_annotation_conflict(
                items, active_project_label_ids(materials.project_path),
                _material_integrity_import_evidence(project_id, items, task_repository(), task_artifacts()))
                if str(group_key).startswith('DUPLICATE_') else None,
            "next_cursor": ids[-1] if len(rows) > int(limit) else None,
        }

    @integrity.post("/audits/{task_id}/training-plans", status_code=201)
    def create_training_plan(project_id: str, task_id: str, request: Request, payload: dict = Body(...)):
        task = require_integrity_audit(project_id, task_id)
        actor = actor_provider(request,project_id) if actor_provider else {}
        return invoke(lambda: create_training_integrity_plan(project_id,task,material_store(project_id),task_repository(),task_artifacts(),payload,training_selection_provider,actor=actor))

    @integrity.get('/audits/{task_id}/conflict-review')
    def integrity_conflict_review(project_id: str, task_id: str, cursor: str = '', limit: int = 25,
                                 observation: str = '', import_batch: str = ''):
        task = require_integrity_audit(project_id, task_id)
        if not 1 <= limit <= 50:
            raise HTTPException(422, detail='limit must be between 1 and 50')
        return invoke(material_integrity_conflict_review, project_id, task, material_store(project_id),
            task_repository(), task_artifacts(), cursor, limit, observation, import_batch)

    @integrity.get("/audits/{task_id}/governance-summary")
    def integrity_governance_summary(project_id: str, task_id: str):
        task = require_integrity_audit(project_id, task_id)
        return invoke(material_integrity_governance_summary, project_id, task, material_store(project_id),
            task_repository(), task_artifacts())

    @integrity.post("/audits/{task_id}/dedup-plans", status_code=201)
    def create_integrity_plan(
        project_id: str, task_id: str, request: Request, payload: dict = Body(...),
    ):
        task = require_integrity_audit(project_id, task_id)
        actor = actor_provider(request,project_id) if actor_provider else {}
        return invoke(lambda: create_material_integrity_plan(project_id,task,material_store(project_id),task_repository(),task_artifacts(),payload,actor=actor))

    @integrity.post(
        "/audits/{task_id}/dedup-plans/{plan_id}/execute", status_code=202,
    )
    def execute_integrity_plan(
        project_id: str, task_id: str, plan_id: str, request: Request,
        payload: dict = Body(...),
    ):
        task = require_integrity_audit(project_id, task_id)
        actor = actor_provider(request,project_id) if actor_provider else {}
        published = invoke(lambda: execute_material_integrity_plan(project_id,task,plan_id,str((payload or {}).get('confirmation_credential') or ''),material_store(project_id),task_repository(),task_artifacts(),actor=actor))
        return public_batch(published, task_artifacts(), task_repository())

    # Training/agent routes are mounted once by app.py with their dependencies.
    # A nested mount here would shadow that configured owner.
    from .label_integrity import label_integrity_router
    root = APIRouter()
    root.include_router(router)
    root.include_router(integrity)
    root.include_router(label_integrity_router(
        get_project, material_store, task_repository, task_artifacts,
    ))
    return root


def worker_registration(data_dir):
    capabilities = {"materials.batch"}
    from .smart_material_audit import require_enabled
    try:
        require_enabled(data_dir)
    except (ValueError,OSError):
        pass  # Optional configuration must never prevent the original Worker starting.
    else:
        capabilities.add("materials.smart_audit")
    return {"handlers": {TaskKind.MATERIAL_BATCH: MaterialBatchHandler(data_dir)}, "capabilities": capabilities}
