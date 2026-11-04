"""Server-owned material paging and summaries for the training picker.

The training UI must never hydrate the whole project material pool in the browser.
Metadata comes from MaterialRepository cursor paging, selected-material facts are
aggregated inside SQLite, and thumbnails are created lazily on demand.
"""
from __future__ import annotations

from .performance_diagnostics import connect_sqlite, observe_connection, observe_duration, measure, stage, count

import hashlib
import json
import math
import os
import sqlite3
import tempfile
import threading
from time import perf_counter
from collections import OrderedDict
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from filelock import FileLock
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.requests import Request

from .annotation_repository import AnnotationRepository
from .negative_pool import NegativePool
from .material_repository import (
    MaterialRepository,
    DATASET_DELETE_CLAIM_FIELD,
    MATERIAL_BATCH_DELETE_CLAIM_FIELD,
    _deferred_material_page_sql,
    decode_material_cursor,
    encode_material_cursor,
)
from .storage.errors import StorageError
from .storage.manager import StorageManager
from .training_scope_review_plans import TrainingScopeReviewPlans
from .training_compatibility import (
    compatibility_page,
    evaluate_training_compatibility_projection,
    resolve_training_compatibility_selection,
)

# Keep the visual page intentionally smaller than the old 120-card page. The
# picker now renders larger previews and only loads thumbnails close to the
# viewport, so 60 rows gives a substantially faster first interaction without
# changing the meaning of "select all filtered".
DEFAULT_PAGE_SIZE = 60
MAX_PAGE_SIZE = 120
MAX_SELECTION_SUMMARY_IDS = 50000
BULK_SELECTION_SCAN_SIZE = 500
# Picker cards are intentionally larger now. 192 px keeps the preview sharp
# enough while avoiding the decode/cache cost of full-size source images.
DEFAULT_THUMBNAIL_SIZE = 192
ALLOWED_THUMBNAIL_SIZES = {160, 192, 224, 256, 320, 384}
_GT_FILTER_COUNTS_LOCK = threading.Lock()
_GT_FILTER_COUNTS: OrderedDict[tuple, int] = OrderedDict()
_GT_FILTER_COUNTS_LIMIT = 128


def _safe_project_path(data_dir: Path, project_id: str) -> Path:
    projects = (data_dir / "projects").resolve()
    project = (projects / str(project_id)).resolve()
    if project.parent != projects:
        raise ValueError("project id must be one safe path component")
    return project


def _public_picker_material(project_id: str, row: dict, annotation: dict) -> dict:
    image_id = str(row.get("id") or "")
    encoded = quote(image_id, safe="")
    annotation_state = str(annotation.get("annotation_state") or "unannotated")
    boxes = [dict(box) for box in (annotation.get("boxes") or [])] if annotation_state == "annotated" else []
    labels = sorted({
        str(box.get("label") or box.get("code") or "").strip()
        for box in boxes
        if str(box.get("label") or box.get("code") or "").strip()
    })
    source_hash = str(row.get("content_sha256") or "").strip().lower()
    annotation_source_hash = str(row.get("annotation_source_content_sha256") or "").strip().lower()
    annotation_issue = (
        "material_unavailable" if row.get("source_available") is False
        else "stale_ground_truth" if source_hash and annotation_source_hash and source_hash != annotation_source_hash
        else "annotation_needs_review" if any(row.get(key) for key in (
            "annotation_needs_review", "external_annotation_needs_review", "needs_review"))
        else "invalid_annotation" if (annotation_state == "annotated" and not boxes)
        or (annotation_state == "confirmed_empty" and annotation.get("boxes"))
        else ""
    )
    return {
        "id": image_id,
        "image_id": image_id,
        "filename": str(row.get("filename") or image_id),
        "storage_source_id": str(row.get("storage_source_id") or "default_local"),
        "created_at": str(row.get("created_at") or ""),
        "width": max(0, int(row.get("width") or 0)),
        "height": max(0, int(row.get("height") or 0)),
        "labels": labels,
        "annotated": annotation_state in {"annotated", "confirmed_empty"},
        "box_count": len(boxes),
        "boxes": boxes[:12],
        "boxes_preview_only": True,
        "boxes_truncated": len(boxes) > 12,
        "processing_status": str(row.get("processing_status") or ""),
        "annotation_state": annotation_state,
        "annotation_issue_type": annotation_issue,
        "training_state": (
            "trainable"
            if annotation_state in {"annotated", "confirmed_empty"}
            else "pending_annotation"
        ),
        "source_available": row.get("source_available") is not False,
        "size_bytes": max(0, int(row.get("size_bytes") or 0)),
        "thumbnail_url": f"/api/v62/projects/{quote(str(project_id), safe='')}/training-materials/{encoded}/thumbnail?size={DEFAULT_THUMBNAIL_SIZE}",
        "content_url": f"/api/v61/projects/{quote(str(project_id), safe='')}/materials/{encoded}/content",
    }


def _normalize_selection_ids(values: object) -> list[str]:
    if not isinstance(values, list):
        raise ValueError("image_ids must be a list")
    ids = list(dict.fromkeys(str(value or "").strip() for value in values if str(value or "").strip()))
    if len(ids) > MAX_SELECTION_SUMMARY_IDS:
        raise ValueError(f"image_ids must not exceed {MAX_SELECTION_SUMMARY_IDS}")
    return ids


def _normalize_labels(values: object) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, list):
        raise ValueError("labels must be a list")
    return tuple(dict.fromkeys(str(value or "").strip() for value in values if str(value or "").strip()))


@lru_cache(maxsize=4)
@stage("usage_pool_build")
def _cached_usage_pool(project_path, task_path, material_revision, algorithm_id, usage_revision, role, exclude_used):
    from .training_material_usage import TrainingMaterialUsage
    repository = MaterialRepository(Path(project_path))
    usage = TrainingMaterialUsage(task_path)
    # Stream only relation identities. Never hydrate a second whole material pool.
    fields = ("group_id","video_task_id","source_group_id","near_duplicate_group_id","sequence_group_id",
              "camera_session_id","capture_session_id","camera_id","session_id","stored_name","stored_path","path",
              "source_root_id","derived_from_image_id")
    columns = ",".join("json_extract(payload_json, '$."+field+"') AS "+field for field in fields)
    combined = {"revision":usage_revision,"coverage":"unknown","by_image_id":{},"excluded_image_ids":[],"unknown_image_ids":[],"state_ids":{"unknown":[],"unused":[]}}
    with closing(observe_connection(connect_sqlite(repository.path, timeout=30))) as db:
        db.row_factory=sqlite3.Row
        cursor=db.execute("SELECT id,content_sha256,"+columns+" FROM materials WHERE processing_status='processed'")
        while True:
            rows=cursor.fetchmany(500)
            if not rows: break
            result=usage.query_filter(repository.project_path.name,algorithm_id,[dict(r) for r in rows],exclude_used=exclude_used,role=role)
            combined["coverage"]=result["coverage"]
            for image_id,fact in result["by_image_id"].items():
                if not fact.get("history_details") and fact["state"] in {"unknown","unused"}:
                    combined["state_ids"][fact["state"]].append(image_id)
                else: combined["by_image_id"][image_id]=fact
            combined["excluded_image_ids"].extend(result["excluded_image_ids"])
            combined["unknown_image_ids"].extend(result["unknown_image_ids"])
    if repository.current_revision()!=material_revision or usage.read_revision()!=usage_revision:
        raise ValueError("素材或历史证据已更新，请重试")
    return combined


@stage("training.usage_filters")
def _usage_filters(repository, filters):
    from .training_material_usage import TrainingMaterialUsage
    body = dict(filters or {})
    body.pop('__usage_sql_exclusion', None)
    state = str(body.get("usage_state") or "")
    if state and state not in {"used", "possible", "selected", "unused", "unknown", "eval_only", "test_reserved"}:
        raise ValueError("invalid usage_state")
    scope = str(body.get("history_scope") or "")
    if scope not in {"", "current_only", "other_only"}: raise ValueError("invalid history_scope")
    algorithm_id = str(body.get("algorithm_asset_id") or "")
    task_path = repository.project_path.parent.parent / "task_runtime" / "tasks.sqlite3"
    policy = str(body.get("history_policy") or "new_for_algorithm")
    if policy not in {"new_for_algorithm", "include_history"}: raise ValueError("invalid history_policy")
    usage_revision = TrainingMaterialUsage(task_path).read_revision()
    browse_only = body.pop("browse_only", False) is True
    if not state and not scope and browse_only:
        return body, {"revision":usage_revision,"coverage":"unknown","by_image_id":{},"excluded_image_ids":[],"unknown_image_ids":[]}
    if not state and not scope:
        # Default first-page/count/bulk operations must not hydrate every
        # material and query the Task usage index in 500-row Python batches.
        # Preserve exact derivative/hash/group matching in the indexed SQL
        # anti-join; explicit history-state/scope filters retain the full path.
        usage_index = TrainingMaterialUsage(task_path)
        if usage_index.has_exposed_records(repository.project_path.name, algorithm_id,
                                           role=str(body.get('role') or 'train'),
                                           include_train_history=policy == 'new_for_algorithm'):
            with closing(usage_index._connect()) as task_db:
                has_task_statuses = task_db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tasks'"
                ).fetchone() is not None
            body['__usage_sql_exclusion'] = {
                'path': str(task_path), 'project_id': repository.project_path.name,
                'algorithm_id': algorithm_id, 'role': str(body.get('role') or 'train'),
                'revision': usage_revision, 'include_train_history': policy == 'new_for_algorithm',
                'has_task_statuses': has_task_statuses,
            }
        return body, {"revision":usage_revision,"coverage":"unknown","by_image_id":{},"excluded_image_ids":[],"unknown_image_ids":[]}
    if ((scope and not state) or (state in {'used','possible'} and scope in {'','current_only'} and str(body.get('role') or 'train')=='train')) and browse_only and task_path.is_file():
        # Scope browsing needs indexed relation existence, not every material's history.
        with closing(TrainingMaterialUsage(task_path)._connect()) as task_db:
            tables={row[0] for row in task_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            schema_ok='training_usage_token_schema' in tables and task_db.execute('SELECT 1 FROM training_usage_token_schema WHERE version=1').fetchone()
        if schema_ok and {'training_usage_tokens','training_material_usage','training_usage_meta'} <= tables:
            body['__usage_sql_exclusion']={'path':str(task_path),'project_id':repository.project_path.name,
                'algorithm_id':algorithm_id,'role':str(body.get('role') or 'train'),
                'revision':usage_revision,'scope_only':state or scope,'has_task_statuses':'tasks' in tables}
            return body, {"revision":usage_revision,"coverage":"unknown","by_image_id":{},"excluded_image_ids":[],"unknown_image_ids":[]}
    count("usage_pool_requests")
    facts = _cached_usage_pool(str(repository.project_path), str(task_path), repository.current_revision(),
        algorithm_id, usage_revision, str(body.get("role") or "train"), policy == "new_for_algorithm")
    excluded=set(facts["excluded_image_ids"])
    if state or scope:
        eligible=[key for key,value in facts["by_image_id"].items() if (not state or value["state"] == state) and (browse_only or not value["excluded"]) and (not scope or (value.get("current_algorithm_trained",False) if scope=="current_only" else value.get("other_algorithm_trained",False) and not value.get("current_algorithm_trained",False)))]
        if state and not scope:
            eligible.extend(i for i in facts.get("state_ids",{}).get(state,[]) if browse_only or i not in excluded)
        body["usage_image_ids"]=eligible
    elif excluded:
        body["usage_excluded_image_ids"]=sorted(excluded)
    return body, facts


@stage("training.page_usage")
def _page_usage_facts(repository, body, rows):
    from .training_material_usage import TrainingMaterialUsage
    path=repository.project_path.parent.parent / "task_runtime" / "tasks.sqlite3"
    return TrainingMaterialUsage(path).query_filter(repository.project_path.name,str(body.get("algorithm_asset_id") or ""),
        rows,exclude_used=body.get("history_policy","new_for_algorithm")=="new_for_algorithm",role=str(body.get("role") or "train"))


def _public_usage_fact(fact, algorithm_id=""):
    """Count consumed training tasks for the current algorithm, not the gallery."""
    all_details=fact.get("history_details") or []
    details=[row for row in all_details if not algorithm_id or row["algorithm_id"] == algorithm_id]
    return {**{k:v for k,v in fact.items() if k not in {"history_details","task_ids"}},
        "training_task_count":len({r["task_id"] for r in details if r["role"]=="train" and r["evidence"]>=2}),
        "possible_training_task_count":len({r["task_id"] for r in details if r["role"]=="train" and r["evidence"]==1}),
        "algorithm_ids":sorted({r["algorithm_id"] for r in all_details})}


def _pool_filters(repository, filters):
    body=dict(filters or {})
    categories=body.get('negative_category_ids') or []
    if body.get('negative_pool_only') or categories:
        from .negative_pool import NegativePool
        pool=NegativePool(repository)
        revision=pool.revision()
        category_ids = pool._ids(categories)
        algorithm_id = str(body.get('algorithm_asset_id') or '')
        with closing(repository._connect()) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'negative_pool_%'")}
        body['__negative_pool_sql'] = {
            'available': 'negative_pool_members' in tables and (not algorithm_id or 'negative_pool_algorithm_members' in tables),
            'algorithm_id': algorithm_id, 'category_ids': category_ids,
        }
        if pool.revision()!=revision:
            raise ValueError('负样本池已更新，请重试')
        body['negative_pool_revision']=revision
    return body


def _picker_filter_sql(filters=None):
    """Shared predicates; formal annotation truth always belongs to AnnotationRepository."""
    f = dict(filters or {})
    clauses, params = [], []
    pool = f.get('__negative_pool_sql')
    if pool is not None:
        if not pool['available']:
            clauses.append('0')
        else:
            from .negative_pool import _LIVE
            clauses.append(_LIVE)
            clauses.append('EXISTS (SELECT 1 FROM negative_pool_members np WHERE np.material_id=m.id)')
            if pool['algorithm_id']:
                clauses.append('EXISTS (SELECT 1 FROM negative_pool_algorithm_members am WHERE am.algorithm_id=? AND am.material_id=m.id)')
                params.append(pool['algorithm_id'])
            if pool['category_ids']:
                clauses.append('EXISTS (SELECT 1 FROM negative_pool_links nl WHERE nl.material_id=m.id AND nl.category_id IN (SELECT value FROM json_each(?)))')
                params.append(json.dumps(pool['category_ids']))
    if f.get('negative_pool_image_ids') is not None:
        clauses.append('m.id IN (SELECT value FROM json_each(?))')
        params.append(json.dumps(f['negative_pool_image_ids']))
    sources = _normalize_selection_ids(f.get("storage_source_ids") or [])
    if sources:
        clauses.append("m.storage_source_id IN (" + ",".join("?" for _ in sources) + ")")
        params.extend(sources)
    for key, operator in (("created_from", ">="), ("created_to", "<=")):
        value = str(f.get(key) or "").strip()
        if value:
            from datetime import datetime
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            clauses.append(f"julianday(m.created_at) {operator} julianday(?)")
            params.append(value + ("T23:59:59.999999+00:00" if key == "created_to" and len(value) == 10 else ""))
    target=f.get('__role_target')
    if target and target.get('labels'):
        labels=list(dict.fromkeys(target['labels']))
        sql=("EXISTS (SELECT 1 FROM annotation_gt.annotation_label_references role_gt "
            "WHERE role_gt.image_id=m.id AND role_gt.annotation_state='annotated' "
            "AND role_gt.box_count>0 AND role_gt.label_code IN ("+','.join('?' for _ in labels)+"))")
        clauses.append(('NOT ' if target['negative'] else '')+sql)
        params.extend(labels)
    state = str(f.get("annotation_state") or "")
    if state:
        if state not in {"annotated", "confirmed_empty", "unannotated"}:
            raise ValueError("invalid annotation_state")
        clauses.append("COALESCE((SELECT a.annotation_state FROM annotation_gt.annotations a WHERE a.image_id=m.id),'unannotated')=?")
        params.append(state)
    if f.get("usage_excluded_image_ids"):
        clauses.append("m.id NOT IN (SELECT value FROM json_each(?))")
        params.append(json.dumps(f["usage_excluded_image_ids"]))
    sql_exclusion = f.get('__usage_sql_exclusion')
    if sql_exclusion and not sql_exclusion.get('scope_only'):
        roles = (("train", "validation") if sql_exclusion['role'] == 'test' else
                 ("train", "test") if sql_exclusion.get('include_train_history', True) else ("test",))
        active_reservation = (
            " OR EXISTS (SELECT 1 FROM usage_index.tasks active "
            "WHERE active.task_id=u.task_id AND active.status IN "
            "('QUEUED','RUNNING','CANCEL_REQUESTED','AWAITING_CONFIRMATION'))"
            if sql_exclusion.get('has_task_statuses') else ''
        )
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM "
            "json_each(picker_relation_tokens(m.id,m.content_sha256,m.payload_json)) rel "
            "CROSS JOIN usage_index.training_usage_tokens t "
            "CROSS JOIN usage_index.training_material_usage u "
            "WHERE t.project_id=? "
            "AND t.token_kind=json_extract(rel.value,'$[0]') "
            "AND t.token_value=json_extract(rel.value,'$[1]') "
            "AND u.task_id=t.task_id AND u.image_id=t.image_id AND u.role=t.role "
            "AND u.algorithm_id=? AND (u.evidence>0" + active_reservation + ") "
            "AND u.role IN (" + ",".join("?" for _ in roles) + "))"
        )
        params.extend((sql_exclusion['project_id'], sql_exclusion['algorithm_id'], *roles))
        # The existing exact-count cache must also expire on Task usage writes.
        clauses.append("(SELECT revision FROM usage_index.training_usage_meta WHERE id=1)=?")
        params.append(sql_exclusion['revision'])
    if sql_exclusion and sql_exclusion.get('scope_only'):
        # Same relation token UDF as admission, so hashes and derivatives match.
        def scope_exists(operator):
            return ("EXISTS (SELECT 1 FROM json_each(picker_relation_tokens(m.id,m.content_sha256,m.payload_json)) rel "
                "CROSS JOIN usage_index.training_usage_tokens t CROSS JOIN usage_index.training_material_usage u "
                "WHERE t.project_id=? AND t.token_kind=json_extract(rel.value,'$[0]') "
                "AND t.token_value=json_extract(rel.value,'$[1]') AND u.task_id=t.task_id "
                "AND u.image_id=t.image_id AND u.role=t.role AND u.algorithm_id"+operator+"? AND u.role='train' AND u.evidence>0)")
        if sql_exclusion['scope_only'] in {'used','possible'}:
            def exposure(roles, condition):
                return ("EXISTS (SELECT 1 FROM json_each(picker_relation_tokens(m.id,m.content_sha256,m.payload_json)) rel "
                    "CROSS JOIN usage_index.training_usage_tokens t CROSS JOIN usage_index.training_material_usage u "
                    "WHERE t.project_id=? AND t.token_kind=json_extract(rel.value,'$[0]') "
                    "AND t.token_value=json_extract(rel.value,'$[1]') AND u.task_id=t.task_id "
                    "AND u.image_id=t.image_id AND u.role=t.role AND u.algorithm_id=? AND u.role="+roles+" AND ("+condition+"))")
            chosen=exposure("'train'",'u.evidence>=2' if sql_exclusion['scope_only']=='used' else 'u.evidence=1')
            clauses.append(chosen)
            params.extend((sql_exclusion['project_id'],sql_exclusion['algorithm_id']))
            if sql_exclusion['scope_only']=='possible':
                clauses.append('NOT '+exposure("'train'",'u.evidence>=2'))
                params.extend((sql_exclusion['project_id'],sql_exclusion['algorithm_id']))
            active=(" OR EXISTS (SELECT 1 FROM usage_index.tasks active WHERE active.task_id=u.task_id AND active.status IN ('QUEUED','RUNNING','CANCEL_REQUESTED','AWAITING_CONFIRMATION'))" if sql_exclusion.get('has_task_statuses') else '')
            clauses.append('NOT '+exposure("'test'",'u.evidence>0'+active))
            params.extend((sql_exclusion['project_id'],sql_exclusion['algorithm_id']))
        elif sql_exclusion['scope_only']=='current_only':
            clauses.append(scope_exists('='))
            params.extend((sql_exclusion['project_id'],sql_exclusion['algorithm_id']))
        else:
            clauses.extend((scope_exists('!='),'NOT '+scope_exists('=')))
            params.extend((sql_exclusion['project_id'],sql_exclusion['algorithm_id'])*2)
        clauses.append('(SELECT revision FROM usage_index.training_usage_meta WHERE id=1)=?')
        params.append(sql_exclusion['revision'])
    if f.get("usage_image_ids") is not None:
        clauses.append("m.id IN (SELECT value FROM json_each(?))")
        params.append(json.dumps(f["usage_image_ids"]))
    if f.get("image_ids") is not None:
        # Caller-owned selection scope, never inferred from global material state.
        ids = _normalize_selection_ids(f["image_ids"])
        clauses.append("m.id IN (SELECT value FROM json_each(?))")
        params.append(json.dumps(ids))
    return clauses, params


def _picker_relation_tokens(image_id, content_hash, payload_json):
    """Exactly the same relation identities used by TrainingMaterialUsage."""
    from .training_splits import _relation_tokens
    payload = json.loads(payload_json or '{}')
    fields = ('group_id', 'video_task_id', 'source_group_id',
              'near_duplicate_group_id', 'sequence_group_id', 'camera_session_id',
              'capture_session_id', 'camera_id', 'session_id', 'stored_name',
              'stored_path', 'path', 'source_root_id', 'derived_from_image_id')
    row = {field: payload.get(field) for field in fields}
    row.update(id=image_id, content_sha256=content_hash)
    return json.dumps(_relation_tokens(row), ensure_ascii=False)


def _attach_usage_exclusion(db, filters):
    sql_exclusion = (filters or {}).get('__usage_sql_exclusion')
    if sql_exclusion:
        # Read-only attached Task evidence, within the same snapshot as GT.
        task_uri = Path(sql_exclusion['path']).resolve().as_uri() + '?mode=ro'
        db.execute('ATTACH DATABASE ? AS usage_index', (task_uri,))
        db.create_function('picker_relation_tokens', 3, _picker_relation_tokens,
                           deterministic=True)


@stage("training.gt_filtered_count")
def _gt_filtered_count_snapshot(
    database: sqlite3.Connection,
    repository: MaterialRepository,
    annotations: AnnotationRepository,
    where: str,
    params: list[object],
    material_revision: int,
    annotation_revision: int,
) -> int:
    """Cache formal-GT counts only for an exact two-database read snapshot.

    Material updates and annotation revisions are independent; both are
    mandatory in the cache identity so a GT edit never serves a stale total.
    """
    material_stat = repository.path.stat()
    annotation_stat = annotations.path.stat()
    key = (
        str(repository.path.resolve()), material_stat.st_dev, material_stat.st_ino,
        material_revision,
        str(annotations.path.resolve()), annotation_stat.st_dev, annotation_stat.st_ino,
        annotation_revision,
        # Bulk selection filters can contain tens of thousands of image IDs.
        # A bounded entry count alone must not retain entire ID lists as keys.
        hashlib.sha256(json.dumps([where, params], ensure_ascii=False,
                                  separators=(",", ":")).encode("utf-8")).digest(),
    )
    with _GT_FILTER_COUNTS_LOCK:
        cached = _GT_FILTER_COUNTS.get(key)
        if cached is not None:
            _GT_FILTER_COUNTS.move_to_end(key)
            count("training_gt_count_cache_hits")
            return cached
    total = int(database.execute(
        "SELECT COUNT(*) FROM materials m" + where, params,
    ).fetchone()[0])
    with _GT_FILTER_COUNTS_LOCK:
        _GT_FILTER_COUNTS[key] = total
        _GT_FILTER_COUNTS.move_to_end(key)
        while len(_GT_FILTER_COUNTS) > _GT_FILTER_COUNTS_LIMIT:
            _GT_FILTER_COUNTS.popitem(last=False)
    return total


@stage("training.gt_page")
def _gt_material_filter_page(
    repository: MaterialRepository,
    annotations: AnnotationRepository,
    *,
    cursor: str | None = None,
    page: int | None = None,
    limit: int,
    query: str = "",
    labels: tuple[str, ...] = (),
    require_ground_truth: bool = False,
    include_payload: bool = False,
    sort_order: str = "oldest",
    filters: dict | None = None,
    count_mode: str = "exact",
) -> dict:
    """Page processed materials while label/GT predicates come from formal GT.

    The query attaches AnnotationRepository read-only truth to the material
    connection, so cursor rows and totals are computed from one SQLite read
    transaction without hydrating annotation JSON or trusting material labels.
    """
    bounded = max(1, min(MAX_SELECTION_SUMMARY_IDS, int(limit)))
    if count_mode not in {"exact", "deferred"}:
        raise ValueError("count_mode must be exact or deferred")
    if sort_order not in ("oldest", "newest"):
        raise ValueError("sort_order must be oldest or newest")
    descending = sort_order == "newest"
    if page is not None and cursor:
        raise ValueError("page and cursor cannot be used together")
    selected_labels = tuple(dict.fromkeys(
        str(value or "").strip() for value in labels if str(value or "").strip()
    ))
    base_clauses = ["m.processing_status='processed'"]
    base_params: list[object] = []
    normalized_query = str(query or "").strip()
    if normalized_query:
        base_clauses.append("m.filename LIKE ? COLLATE NOCASE")
        base_params.append(f"%{normalized_query}%")
    label_mode=str((filters or {}).get('label_mode') or 'any')
    if label_mode not in {'any','all'}: raise ValueError('invalid label_mode')
    if selected_labels and label_mode=='all':
        for code in dict.fromkeys(selected_labels):
            base_clauses.append("EXISTS (SELECT 1 FROM annotation_gt.annotation_label_references gt WHERE gt.image_id=m.id AND gt.annotation_state='annotated' AND gt.box_count>0 AND gt.label_code=?)")
            base_params.append(code)
    elif selected_labels:
        placeholders = ",".join("?" for _ in selected_labels)
        base_clauses.append(
            "EXISTS (SELECT 1 FROM annotation_gt.annotation_label_references gt "
            "WHERE gt.image_id=m.id AND gt.annotation_state='annotated' "
            "AND gt.box_count>0 AND gt.label_code IN (" + placeholders + "))"
        )
        base_params.extend(selected_labels)
    elif require_ground_truth:
        base_clauses.append(
            "EXISTS (SELECT 1 FROM annotation_gt.annotation_label_references gt "
            "WHERE gt.image_id=m.id AND ("
            "(gt.annotation_state='annotated' AND gt.box_count>0) OR "
            "(gt.annotation_state='confirmed_empty' AND gt.scope_ref=1)))"
        )

    pool_filters = _pool_filters(repository, filters)
    extra_clauses, extra_params = _picker_filter_sql(pool_filters)
    base_clauses.extend(extra_clauses)
    base_params.extend(extra_params)
    base_where = " WHERE " + " AND ".join(base_clauses)
    with closing(observe_connection(connect_sqlite(repository.path, timeout=30,
                    uri=bool(pool_filters.get('__usage_sql_exclusion'))))) as database:
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA busy_timeout=30000")
        database.execute("PRAGMA temp_store=FILE")
        database.execute(
            "ATTACH DATABASE ? AS annotation_gt",
            (str(annotations.path),),
        )
        _attach_usage_exclusion(database, pool_filters)
        database.execute("BEGIN")
        try:
            sql_exclusion = pool_filters.get('__usage_sql_exclusion')
            if sql_exclusion and str(database.execute(
                'SELECT revision FROM usage_index.training_usage_meta WHERE id=1'
            ).fetchone()[0]) != str(sql_exclusion['revision']):
                raise ValueError('训练历史已更新，请重试素材查询')
            material_revision = int(database.execute(
                "SELECT value FROM material_meta WHERE key='revision'"
            ).fetchone()[0])
            annotation_revision_row = database.execute(
                "SELECT value FROM annotation_gt.annotation_meta "
                "WHERE key='revision'"
            ).fetchone()
            annotation_revision = (
                int(annotation_revision_row[0])
                if annotation_revision_row is not None else 0
            )
            # Both auxiliary revision markers describe this exact page snapshot.
            # Reading them after COMMIT opened two fresh connections and could
            # mix newer negative evidence with older material/GT page results.
            negative_confirmation_revision = 0
            if database.execute(
                "SELECT 1 FROM annotation_gt.sqlite_master "
                "WHERE type='table' AND name='task_negative_confirmations'"
            ).fetchone() is not None:
                negative_confirmation_revision = int(database.execute(
                    "SELECT COUNT(*) FROM annotation_gt.task_negative_confirmations"
                ).fetchone()[0])
            negative_pool_revision = "0"
            if database.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='negative_pool_meta'"
            ).fetchone() is not None:
                negative_pool_revision = str(database.execute(
                    "SELECT revision FROM negative_pool_meta WHERE id=1"
                ).fetchone()[0])
            if ("negative_pool_revision" in pool_filters
                    and str(pool_filters["negative_pool_revision"]) != negative_pool_revision):
                raise ValueError("负样本池已更新，请重试")
            # The picker only needs a bounded first page and whether another
            # page exists. Exact COUNT(*) with a history/GT filter can scan the
            # entire 200k-material pool before LIMIT ever gets a chance to run.
            total = (_gt_filtered_count_snapshot(
                database, repository, annotations, base_where, base_params,
                material_revision, annotation_revision,
            ) if count_mode == "exact" else None)
            offset = None
            if page is not None:
                page_number = int(page)
                if page_number < 1:
                    raise ValueError("page must be a positive integer")
                if total is not None and page_number > max(1, math.ceil(total / bounded)):
                    raise ValueError(
                        f"page {page_number} exceeds total_pages {max(1, math.ceil(total / bounded))}"
                    )
                offset = (page_number - 1) * bounded
            clauses = list(base_clauses)
            params = list(base_params)
            if cursor:
                created_at, image_id = decode_material_cursor(cursor)
                op = "<" if descending else ">"
                clauses.append(f"(m.created_at {op} ? OR (m.created_at = ? AND m.id {op} ?))")
                params.extend((created_at, created_at, image_id))
            where = " WHERE " + " AND ".join(clauses)
            sql = _deferred_material_page_sql(
                where, descending=descending,
                include_payload=include_payload, offset=offset is not None,
            )
            query_params = [*params, bounded + 1]
            if offset is not None:
                query_params.append(offset)
            rows = database.execute(sql, query_params).fetchall()
            database.execute("COMMIT")
        except Exception:
            database.execute("ROLLBACK")
            raise

    visible = rows[:bounded]
    next_cursor = None
    if len(rows) > bounded and visible:
        next_cursor = encode_material_cursor(
            str(visible[-1]["created_at"]),
            str(visible[-1]["id"]),
        )
    items = (
        [json.loads(row["payload_json"]) for row in visible]
        if include_payload else
        [str(row["id"]) for row in visible]
    )
    return {
        "items": items,
        "next_cursor": next_cursor,
        "total": total,
        "has_next": len(rows) > bounded,
        "material_revision": material_revision,
        "annotation_revision": annotation_revision,
        "negative_confirmation_revision": negative_confirmation_revision,
        "negative_pool_revision": negative_pool_revision,
    }


@lru_cache(maxsize=128)
def _cached_pool_training_totals(
    project_path: str,
    material_revision: int,
    annotation_revision: int,
) -> tuple[int, int, int]:
    """Cache full-pool GT counts by both durable repository revisions."""
    project = Path(project_path)
    annotations = AnnotationRepository(project)
    truth = annotations.training_ground_truth_summary()
    actual_revision = int(truth["revision"])
    if actual_revision != int(annotation_revision):
        return _cached_pool_training_totals(
            project_path,
            int(material_revision),
            actual_revision,
        )
    with closing(observe_connection(connect_sqlite(project / "materials.sqlite3", timeout=30))) as database:
        database.execute("PRAGMA busy_timeout=30000")
        database.execute("PRAGMA temp_store=FILE")
        database.execute(
            "CREATE TEMP TABLE eligible_training_gt_ids ("
            "id TEXT PRIMARY KEY) WITHOUT ROWID"
        )
        eligible_ids = list(truth["eligible_ids"])
        if eligible_ids:
            database.executemany(
                "INSERT OR IGNORE INTO eligible_training_gt_ids(id) VALUES (?)",
                ((image_id,) for image_id in eligible_ids),
            )
        selectable_total = int(database.execute(
            "SELECT COUNT(*) FROM materials "
            "WHERE processing_status='processed'"
        ).fetchone()[0])
        eligible_total = int(database.execute(
            "SELECT COUNT(*) FROM materials m "
            "JOIN eligible_training_gt_ids gt ON gt.id=m.id "
            "WHERE m.processing_status='processed'"
        ).fetchone()[0])
    return selectable_total, eligible_total, actual_revision


def _validated_positive_training_label_codes(repository, annotations, image_ids, candidate_codes):
    """Validate only selected formal positives; stop once every candidate has proof.

    The indexed GT summary supplies candidate box codes, not sufficient proof
    that the material source or box coordinates remain valid. Recheck actual
    selected image identities through the existing training role contract.
    This never scans unselected materials or loads the entire project pool.
    """
    from .training_label_tasks import training_material_role
    pending = set(candidate_codes)
    confirmed = set()
    for offset in range(0, len(image_ids), 500):
        if not pending:
            break
        chunk = image_ids[offset:offset + 500]
        truth = annotations.get_many(chunk)
        candidate_ids = [image_id for image_id in chunk if
            truth[image_id].get("annotation_state") == "annotated" and
            any(str(box.get("label") or box.get("code") or "").strip() in pending
                for box in truth[image_id].get("boxes") or [])]
        if not candidate_ids:
            continue
        materials = {str(row["id"]):row for row in repository.get_many(candidate_ids)}
        for image_id in candidate_ids:
            row = materials.get(image_id)
            if not row or row.get("processing_status") != "processed":
                continue
            annotation = truth[image_id]
            present = {str(box.get("label") or box.get("code") or "").strip()
                for box in annotation.get("boxes") or []} & pending
            if present and training_material_role({**row, **annotation},
                    {"effective_label_codes":sorted(present)})["role"] == "positive":
                confirmed.update(present)
                pending.difference_update(present)
    return [code for code in candidate_codes if code in confirmed]


@stage("training.selection_summary")
def _selection_summary(
    repository: MaterialRepository,
    annotations: AnnotationRepository,
    image_ids: list[str],
    *,
    include_pool_totals: bool = True,
) -> dict:
    """Aggregate selected-material facts while formal GT stays Annotation-owned."""
    start_material_revision = repository.current_revision()
    start_annotation_revision = annotations.current_revision()
    with closing(observe_connection(connect_sqlite(repository.path, timeout=30))) as database:
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA busy_timeout=30000")
        database.execute("PRAGMA temp_store=FILE")
        database.execute(
            "CREATE TEMP TABLE requested_training_material_ids ("
            "id TEXT PRIMARY KEY) WITHOUT ROWID"
        )
        if image_ids:
            database.executemany(
                "INSERT OR IGNORE INTO requested_training_material_ids(id) VALUES (?)",
                ((image_id,) for image_id in image_ids),
            )
        row = database.execute(
            "SELECT COUNT(m.id) AS matched_count, "
            "COALESCE(SUM(CASE WHEN m.processing_status='processed' "
            "THEN 1 ELSE 0 END),0) AS selectable_count, "
            "COALESCE(SUM(CASE WHEN m.processing_status='processed' "
            "THEN m.size_bytes ELSE 0 END),0) AS selectable_size_bytes "
            "FROM requested_training_material_ids r "
            "LEFT JOIN materials m ON m.id=r.id"
        ).fetchone()
        processed_rows = database.execute(
            "SELECT m.id, m.size_bytes "
            "FROM requested_training_material_ids r "
            "JOIN materials m ON m.id=r.id "
            "WHERE m.processing_status='processed' "
            "ORDER BY m.id"
        ).fetchall()
        missing_ids = [str(item[0]) for item in database.execute(
            'SELECT r.id FROM requested_training_material_ids r LEFT JOIN materials m ON m.id=r.id '
            'WHERE m.id IS NULL ORDER BY r.id')]

    processed_ids = [str(item["id"]) for item in processed_rows]
    size_by_id = {
        str(item["id"]): max(0, int(item["size_bytes"] or 0))
        for item in processed_rows
    }
    with measure("training.summary.selected_gt"):
        truth = annotations.training_ground_truth_summary(processed_ids)
    eligible_ids = set(str(value) for value in truth["eligible_ids"])
    eligible_count = len(eligible_ids)
    selectable_count = int(row["selectable_count"] or 0)
    label_counts = dict(truth["label_counts"])
    with measure("training.summary.positive_codes"):
        positive_label_codes = _validated_positive_training_label_codes(
            repository, annotations, processed_ids, list(label_counts))

    material_revision = repository.current_revision()
    selectable_total = eligible_total = None
    pool_annotation_revision = start_annotation_revision
    if include_pool_totals:
        with measure("training.summary.pool_totals"):
            selectable_total, eligible_total, pool_annotation_revision = (
                _cached_pool_training_totals(
                    str(repository.project_path),
                    int(material_revision),
                    int(annotations.current_revision()),
                )
            )
    if (repository.current_revision(), annotations.current_revision()) != (
            start_material_revision, start_annotation_revision) or int(truth["revision"]) != start_annotation_revision:
        raise ValueError("素材或正式标注在汇总期间已变化，请重新读取")
    return {
        "requested_count": len(image_ids),
        "matched_count": int(row["matched_count"] or 0),
        "missing_image_ids": missing_ids,
        "selectable_count": selectable_count,
        "eligible_count": eligible_count,
        "pending_annotation_count": max(0, selectable_count - eligible_count),
        "box_count": int(truth["box_count"] or 0),
        "size_bytes": sum(size_by_id.get(image_id, 0) for image_id in eligible_ids),
        "selectable_size_bytes": int(row["selectable_size_bytes"] or 0),
        "label_codes": list(label_counts),
        "positive_label_codes": positive_label_codes,
        "label_counts": label_counts,
        "selectable_total": selectable_total,
        "eligible_total": eligible_total,
        "pending_annotation_total": (
            max(0, selectable_total - eligible_total)
            if selectable_total is not None and eligible_total is not None else None
        ),
        "annotation_revision": max(
            int(truth["revision"]),
            int(pool_annotation_revision),
        ),
    }


def _bulk_filtered_ids(
    repository: MaterialRepository,
    annotations: AnnotationRepository,
    *,
    query: str = "",
    labels: tuple[str, ...] = (),
    require_ground_truth: bool = False,
    filters: dict | None = None,
) -> tuple[list[str], int]:
    """Resolve a large filtered selection server-side with one HTTP request."""
    if labels or require_ground_truth or filters:
        page = _gt_material_filter_page(
            repository,
            annotations,
            limit=MAX_SELECTION_SUMMARY_IDS,
            query=query,
            labels=labels,
            require_ground_truth=require_ground_truth,
            include_payload=False,
            filters=filters,
        )
        total = max(0, int(page["total"]))
        if total > MAX_SELECTION_SUMMARY_IDS:
            raise ValueError(
                f"筛选结果共 {total} 张，超过单次选择上限 {MAX_SELECTION_SUMMARY_IDS} 张"
            )
        return [str(value) for value in page["items"]], total

    # No GT predicate is needed for the unfiltered training pool. Keep the
    # canonical MaterialRepository cursor path instead of inventing a second
    # material paging owner.
    filters = {
        "query": str(query or "").strip(),
        "processing_status": "processed",
    }
    cursor = None
    ids: list[str] = []
    total = -1
    first = True
    while True:
        page = repository.iter_filtered_ids(
            filters,
            cursor=cursor,
            limit=BULK_SELECTION_SCAN_SIZE,
            include_total=first,
        )
        if first:
            total = max(0, int(page.total))
            if total > MAX_SELECTION_SUMMARY_IDS:
                raise ValueError(
                    f"筛选结果共 {total} 张，超过单次选择上限 {MAX_SELECTION_SUMMARY_IDS} 张"
                )
            first = False
        ids.extend(str(value) for value in page.items)
        if len(ids) > MAX_SELECTION_SUMMARY_IDS:
            raise ValueError(
                f"筛选结果超过单次选择上限 {MAX_SELECTION_SUMMARY_IDS} 张"
            )
        cursor = page.next_cursor
        if not cursor:
            break
    return ids, total if total >= 0 else len(ids)



@lru_cache(maxsize=8)
@stage("role_index_build")
def _cached_role_index(material_path, annotation_path, material_revision, annotation_revision, contract_json, filters_json):
    from .training_label_tasks import training_material_role, task_negative_confirmable
    contract = json.loads(contract_json)
    filters = json.loads(filters_json)
    clauses = ["m.processing_status='processed'"]
    params = []
    if filters.get("query"):
        clauses.append("m.filename LIKE ? COLLATE NOCASE")
        params.append("%" + filters["query"] + "%")
    labels = filters.get("labels") or []
    if labels and filters.get('label_mode')=='all':
        for code in dict.fromkeys(labels):
            clauses.append("EXISTS (SELECT 1 FROM annotation_gt.annotation_label_references r WHERE r.image_id=m.id AND r.annotation_state='annotated' AND r.box_count>0 AND r.label_code=?)")
            params.append(code)
    elif labels:
        clauses.append("EXISTS (SELECT 1 FROM annotation_gt.annotation_label_references r WHERE r.image_id=m.id AND r.annotation_state='annotated' AND r.box_count>0 AND r.label_code IN (" + ",".join("?" for _ in labels) + "))")
        params.extend(labels)
    extra, values = _picker_filter_sql(filters)
    clauses.extend(extra); params.extend(values)
    result = []
    with closing(observe_connection(connect_sqlite(material_path, timeout=30,
                    uri=bool(filters.get('__usage_sql_exclusion'))))) as db:
        db.row_factory = sqlite3.Row
        db.execute("ATTACH DATABASE ? AS annotation_gt", (annotation_path,))
        _attach_usage_exclusion(db, filters)
        db.execute("BEGIN")
        sql_exclusion=filters.get('__usage_sql_exclusion')
        if sql_exclusion and str(db.execute(
            'SELECT revision FROM usage_index.training_usage_meta WHERE id=1'
        ).fetchone()[0]) != str(sql_exclusion['revision']):
            raise ValueError('训练历史已更新，请重试素材查询')
        revisions = (int(db.execute("SELECT value FROM material_meta WHERE key='revision'").fetchone()[0]),
                     int(db.execute("SELECT value FROM annotation_gt.annotation_meta WHERE key='revision'").fetchone()[0]))
        if revisions != (material_revision, annotation_revision):
            raise ValueError("素材或标注已更新，请重试")
        for row in db.execute("SELECT m.id,m.created_at,m.payload_json,a.annotation_state,a.boxes_json,a.scope_json,a.version,a.content_digest FROM materials m LEFT JOIN annotation_gt.annotations a ON a.image_id=m.id WHERE " + " AND ".join(clauses) + " ORDER BY m.created_at,m.id", params):
            payload = json.loads(row["payload_json"])
            payload.update(annotation_state=row["annotation_state"] or "unannotated", boxes=json.loads(row["boxes_json"] or "[]"), annotation_scope=json.loads(row["scope_json"] or "[]"))
            payload.update(id=row["id"], annotation_version=int(row["version"] or 0), annotation_hash=str(row["content_digest"] or ""))
            role = training_material_role(payload, contract)["role"]
            if role == "pending_review" and task_negative_confirmable(payload, contract):
                role = "pending_negative"
            result.append((row["id"], role))
    count("role_candidate_rows",len(result))
    return tuple(result)


@stage("role_page")
def _role_material_page(repository, annotations, contract, *, image_ids=None,
                        query="", labels=(), sample_role="", page=1, limit=60, sort_order="oldest", filters=None, include_payload=True,
                        defer_role_counts=False, count_mode="exact"):
    if sample_role not in {"", "positive", "confirmed_negative", "pending_negative", "pending_review"}:
        raise ValueError("invalid sample_role")
    if not 1 <= int(limit) <= MAX_SELECTION_SUMMARY_IDS or int(page) < 1:
        raise ValueError("invalid role page bounds")
    if sort_order not in {"oldest", "newest"}:
        raise ValueError("invalid sort_order")
    selected = {k:v for k,v in _pool_filters(repository, filters).items() if k in {"storage_source_ids","created_from","created_to","annotation_state","usage_image_ids","usage_excluded_image_ids","__usage_sql_exclusion","image_ids","negative_pool_image_ids","__negative_pool_sql","negative_pool_revision","label_mode","__role_target"}}
    selected.update(query=str(query or "").strip(), labels=sorted(set(labels)))
    if image_ids is not None: selected["image_ids"] = sorted(set(image_ids))
    # Default picker navigation needs the visible page, not every candidate's
    # decoded GT. Keep the historical exact role-count/filter contract for
    # callers that explicitly request it (including role-filtered pages).
    if defer_role_counts and not sample_role:
        page_data = _gt_material_filter_page(repository, annotations,
            limit=limit, page=int(page), query=query, labels=labels,
            sort_order=sort_order, filters=selected, include_payload=include_payload,
            count_mode=count_mode)
        rows = page_data["items"]
        truth = annotations.get_many([row["id"] for row in rows]) if include_payload else {}
        from .training_label_tasks import training_material_role, task_negative_confirmable
        visible = []
        for row in rows:
            if not include_payload:
                visible.append({"id":row})
                continue
            annotation = truth.get(row["id"], {})
            candidate = {**row, "annotation_state":annotation.get("annotation_state", "unannotated"),
                "boxes":annotation.get("boxes") or [], "annotation_scope":annotation.get("annotation_scope") or [],
                "annotation_version":int(annotation.get("version") or 0),
                "annotation_hash":str(annotation.get("content_digest") or "")}
            role = training_material_role(candidate, contract)["role"]
            if role == "pending_review" and task_negative_confirmable(candidate, contract):
                role = "pending_negative"
            visible.append({**row, "sample_role":role})
        revisions = (page_data["material_revision"], page_data["annotation_revision"])
        if (repository.current_revision(), annotations.current_revision()) != revisions:
            raise ValueError("素材或标注已更新，请重试")
        count("role_visible_rows", len(visible))
        return {"items":visible, "total":page_data["total"], "sample_role_counts":None,
                "role_counts_complete":False, "effective_label_codes":list(contract["effective_label_codes"]),
                "page":int(page), "page_size":int(limit), "limit":int(limit), "next_cursor":None,
                "has_next":page_data["has_next"],
                "total_pages":(max(1, math.ceil(page_data["total"]/int(limit)))
                               if page_data["total"] is not None else None),
                "repository_revision":revisions[0], "annotation_revision":revisions[1],
                "negative_confirmation_revision":page_data["negative_confirmation_revision"],
                "negative_pool_revision":page_data["negative_pool_revision"]}
    if sample_role and count_mode=='deferred' and include_payload:
        # Stream authoritative page projections until this result page is full.
        # Never retain all role rows or compute global role counts for a UI page.
        if sample_role in {'positive','confirmed_negative','pending_negative'}:
            selected['__role_target']={'labels':list(contract.get('effective_label_codes') or []),
                'negative':sample_role!='positive'}
        target_start=(int(page)-1)*int(limit)
        matches=[]
        seen=0
        source_page=1
        snapshot=(repository.current_revision(),annotations.current_revision())
        while len(matches)<=int(limit):
            chunk=_role_material_page(repository,annotations,contract,query=query,labels=labels,
                page=source_page,limit=min(MAX_PAGE_SIZE,120),sort_order=sort_order,filters=selected,
                defer_role_counts=True,count_mode='deferred',include_payload=True)
            if (chunk['repository_revision'],chunk['annotation_revision'])!=snapshot:
                raise ValueError('素材或标注已更新，请重试')
            for row in chunk['items']:
                if row['sample_role']!=sample_role: continue
                if seen>=target_start: matches.append(row)
                seen+=1
                if len(matches)>int(limit): break
            if len(matches)>int(limit) or not chunk['has_next']: break
            source_page+=1
        return {**chunk,'items':matches[:int(limit)],'total':None,'total_pages':None,
                'page':int(page),'page_size':int(limit),'limit':int(limit),
                'has_next':len(matches)>int(limit),'sample_role_counts':None,'role_counts_complete':False}
    revisions = (repository.current_revision(), annotations.current_revision())
    count("role_index_requests")
    index = _cached_role_index(str(repository.path), str(annotations.path), *revisions,
        json.dumps(contract, sort_keys=True), json.dumps(selected, sort_keys=True))
    counts = {role:0 for role in ("positive", "confirmed_negative", "pending_negative", "pending_review")}
    for _, role in index: counts[role] = counts.get(role,0) + 1
    visible = [row for row in index if not sample_role or row[1] == sample_role]
    total = len(visible)
    if sort_order == "newest": visible.reverse()
    if int(page) > max(1, math.ceil(total/int(limit))): raise ValueError("page exceeds total_pages")
    visible = visible[(int(page)-1)*int(limit):int(page)*int(limit)]
    rows = {r["id"]:r for r in repository.get_many([r[0] for r in visible])} if include_payload else {i:{"id":i} for i,_ in visible}
    if (repository.current_revision(), annotations.current_revision()) != revisions:
        raise ValueError("素材或标注已更新，请重试")
    negative_pool_revision = NegativePool(repository).revision()
    if ("negative_pool_revision" in selected
            and str(selected["negative_pool_revision"]) != negative_pool_revision):
        raise ValueError("负样本池已更新，请重试")
    return {"items":[{**rows[i], "sample_role":role} for i,role in visible if i in rows],
            "total":total,"sample_role_counts":counts,"effective_label_codes":list(contract["effective_label_codes"]),
            "page":int(page),"page_size":int(limit),"limit":int(limit),"next_cursor":None,
            "total_pages":max(1,math.ceil(total/int(limit))),"repository_revision":revisions[0],"annotation_revision":revisions[1],
            "negative_confirmation_revision":annotations.task_negative_confirmation_revision(), "negative_pool_revision":negative_pool_revision}


def _thumbnail_identity(row: dict) -> str:
    content_hash = str(row.get("content_sha256") or "").strip().lower()
    if len(content_hash) == 64 and all(char in "0123456789abcdef" for char in content_hash):
        return content_hash
    evidence = "|".join((
        str(row.get("id") or ""), str(row.get("etag") or ""),
        str(row.get("updated_at") or ""), str(row.get("size_bytes") or ""),
    ))
    return hashlib.sha256(evidence.encode("utf-8")).hexdigest()


def _thumbnail_path(data_dir: Path, project_id: str, row: dict, size: int) -> Path:
    project_key = hashlib.sha256(str(project_id).encode("utf-8")).hexdigest()[:20]
    root = (data_dir / "cache" / "training-thumbnails" / project_key).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / f"{_thumbnail_identity(row)}-{size}.jpg").resolve()
    if target.parent != root:
        raise ValueError("thumbnail cache escaped its root")
    return target


def _write_thumbnail(source: Path, target: Path, size: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(descriptor)
    temp = Path(temp_name)
    try:
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
            if image.mode in {"RGBA", "LA"}:
                alpha = image.getchannel("A")
                background = Image.new("RGB", image.size, "white")
                background.paste(image.convert("RGB"), mask=alpha)
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")
            image.save(temp, format="JPEG", quality=78, optimize=False, progressive=True)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def training_material_picker_router(
    get_project,
    data_dir_provider,
    project_path_provider=None,
    algorithm_provider=None,
    compatibility_payload_provider=None,
    review_negative_provider=None,
    actor_provider=None,
):
    from fastapi import APIRouter, HTTPException, Query
    from fastapi.responses import FileResponse, RedirectResponse

    router = APIRouter(prefix="/api/v62/projects/{project_id}/training-materials")

    def data_dir() -> Path:
        value = data_dir_provider() if callable(data_dir_provider) else data_dir_provider
        return Path(value).expanduser().resolve()

    @lru_cache(maxsize=128)
    def repository_for_path(project_path: str) -> MaterialRepository:
        """Reuse the lightweight repository object across picker and thumbnail requests.

        MaterialRepository opens short-lived SQLite connections per operation, so sharing the
        object is safe while avoiding schema/bootstrap/migration checks for every thumbnail.
        """
        return MaterialRepository(Path(project_path))

    @lru_cache(maxsize=128)
    def annotation_repository_for_path(project_path: str) -> AnnotationRepository:
        return AnnotationRepository(Path(project_path))

    def materials(project_id: str) -> MaterialRepository:
        get_project(project_id)
        try:
            if project_path_provider is not None:
                project_path = Path(project_path_provider(project_id)).expanduser().resolve()
            else:
                project_path = _safe_project_path(data_dir(), project_id)
            return repository_for_path(str(project_path))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @stage("training.role_contract")
    def task_contract(project_id, body, repository):
        from .training_label_tasks import resolve_training_label_contract
        if algorithm_provider is None:
            raise HTTPException(status_code=503, detail="训练标签适配服务不可用")
        algorithm = algorithm_provider(project_id, str(body.get("algorithm_asset_id") or ""))
        if algorithm is None:
            raise HTTPException(status_code=404, detail="训练算法不存在")
        # Role previews resolve canonical task labels only. Benchmark scope,
        # identity checks and admission remain in the explicit compatibility call.
        # A role preview needs the verified effective label schema, not a
        # frozen checkpoint digest. Formal training admission still hashes the
        # actual best.pt through the default contract path before execution.
        return resolve_training_label_contract(data_dir(), repository.project_path, dict(body), algorithm,
                                               require_positive_evidence=False, include_base_weight_digest=False)

    @router.post("/history")
    def picker_history(project_id: str, payload: dict):
        from .training_material_usage import TrainingMaterialUsage
        repository = materials(project_id)
        row = repository.get(str(payload.get("image_id") or ""))
        if row is None: raise HTTPException(status_code=404, detail="素材不存在")
        task_path = repository.project_path.parent.parent / "task_runtime" / "tasks.sqlite3"
        fact = TrainingMaterialUsage(task_path).query_filter(project_id, str(payload.get("algorithm_asset_id") or ""), [row], exclude_used=False)
        detail = fact["by_image_id"].get(row["id"], {"state":"unknown","task_ids":[]})
        records = detail.get("history_details") or []
        try:
            page, size = int(payload.get("page") or 1), int(payload.get("page_size") or 20)
            if page < 1 or not 1 <= size <= 100: raise ValueError()
        except (ValueError,TypeError): raise HTTPException(status_code=422,detail="invalid history page")
        records.sort(key=lambda r:(r["task_id"],r["role"]),reverse=True)
        exposed_ids=sorted({r["task_id"] for r in records if r["role"]=="train" and r["evidence"]>=2})
        possible_ids=sorted({r["task_id"] for r in records if r["role"]=="train" and r["evidence"]==1})
        visible = records[(page-1)*size:page*size]
        task_ids=sorted({r["task_id"] for r in visible})
        tasks, legacy_trace, last_completed = {}, [], None
        if task_path.is_file():
            with closing(observe_connection(connect_sqlite(task_path.resolve().as_uri()+"?mode=ro", uri=True, timeout=5))) as db:
                db.row_factory=sqlite3.Row
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='tasks'").fetchone():
                    if not records:
                        legacy_trace=[dict(r) for r in db.execute("SELECT task_id,status,created_at,finished_at FROM tasks WHERE project_id=? AND kind='TRAINING' ORDER BY created_at DESC,task_id DESC LIMIT 20",(project_id,))]
                    for task in db.execute("SELECT task_id,status,stage,created_at,finished_at FROM tasks WHERE project_id=? AND task_id IN (SELECT value FROM json_each(?))", (project_id,json.dumps(task_ids))):
                        tasks[task["task_id"]]=dict(task)
                    last_completed=db.execute("SELECT MAX(finished_at) FROM tasks WHERE project_id=? AND task_id IN (SELECT value FROM json_each(?))",(project_id,json.dumps(exposed_ids))).fetchone()[0]
        algorithms = {}
        if algorithm_provider:
            for aid in {r["algorithm_id"] for r in visible}:
                algorithms[aid]=algorithm_provider(project_id,aid) or {}
        items=[]
        for record in visible:
            algorithm=algorithms.get(record["algorithm_id"],{})
            versions=[]
            for version in algorithm.get("versions") or []:
                lineage=version.get("training_lineage") or {}
                if str(version.get("training_job_id") or lineage.get("task_id") or "") != record["task_id"]: continue
                snapshot=str(version.get("snapshot_id") or lineage.get("snapshot_id") or "")
                if snapshot and snapshot != record["snapshot_id"]: continue
                versions.append({"id":version.get("id"),"name":version.get("name") or version.get("version_name")})
            items.append({**record,**tasks.get(record["task_id"],{}),"algorithm_name":algorithm.get("name") or record["algorithm_id"],
                          "version_id":versions[0]["id"] if len(versions)==1 else None,"versions":versions})
        return {**{k:v for k,v in detail.items() if k not in {"history_details","task_ids"}},"coverage":fact["coverage"],
                "legacy_trace":legacy_trace,"items":items,"page":page,"page_size":size,"total":len(records),
                "summary":{"training_task_count":len(exposed_ids),"possible_training_task_count":len(possible_ids),
                           "last_completed_at":last_completed,"algorithm_ids":sorted({r["algorithm_id"] for r in records}),
                           "evidence_scope":"known_indexed_evidence"},"revision":fact["revision"]}

    @router.get("/revision")
    @stage("training.picker_revision")
    def picker_revision(project_id: str, algorithm_asset_id: str = ""):
        from .training_material_usage import TrainingMaterialUsage
        repository = materials(project_id)
        annotations = annotation_repository_for_path(str(repository.project_path))
        usage_revision = TrainingMaterialUsage(repository.project_path.parent.parent / "task_runtime" / "tasks.sqlite3").read_revision()
        return {"repository_revision":repository.current_revision(), "annotation_revision":annotations.current_revision(), "usage_revision":usage_revision, "negative_confirmation_revision":annotations.task_negative_confirmation_revision(), "negative_pool_revision":NegativePool(repository).revision()}

    @router.post("/page")
    def scoped_picker_page(project_id: str, payload: dict):
        repository = materials(project_id)
        annotations = annotation_repository_for_path(str(repository.project_path))
        try:
            size = int(payload.get("page_size") or DEFAULT_PAGE_SIZE)
            if not 1 <= size <= MAX_PAGE_SIZE: raise ValueError("invalid page_size")
            body, usage = _usage_filters(repository, {**payload, "browse_only":True})
            usage_revision = usage['revision']
            page_number = int(body.get("page") or 1)
            result = _gt_material_filter_page(repository, annotations, limit=size, page=page_number,
                query=str(body.get("query") or ""), labels=_normalize_labels(body.get("labels")),
                include_payload=True, sort_order=str(body.get("sort_order") or "newest"),filters=body,
                count_mode=str(body.get("count_mode") or "exact"))
            usage = _page_usage_facts(repository,body,result["items"])
            if usage['revision'] != usage_revision:
                raise ValueError('训练历史已更新，请重试素材查询')
            truth = annotations.get_many([r["id"] for r in result["items"]])
            return {"items":[{**_public_picker_material(project_id,r,truth.get(r["id"],{})),
                    "training_usage":_public_usage_fact(usage["by_image_id"].get(r["id"],{"state":"unknown"}), str(body.get("algorithm_asset_id") or ""))} for r in result["items"]],
                    "total":result["total"],"page":page_number,"page_size":size,
                    "has_next":result["has_next"],
                    "total_pages":(max(1,math.ceil(result["total"]/size)) if result["total"] is not None else None),
                    "repository_revision":result["material_revision"],"annotation_revision":result["annotation_revision"],"usage_revision":usage["revision"]}
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.post("/role-page")
    def training_role_page(project_id: str, payload: dict):
        repository = materials(project_id)
        annotations = annotation_repository_for_path(str(repository.project_path))
        try:
            limit = int(payload.get("page_size") or payload.get("limit") or DEFAULT_PAGE_SIZE)
            if not 1 <= limit <= MAX_PAGE_SIZE:
                raise ValueError("page_size exceeds page limit")
            payload, usage = _usage_filters(repository, {**payload, "browse_only":True})
            usage_revision = usage['revision']
            contract = task_contract(project_id, payload, repository)
            result = _role_material_page(repository, annotations, contract,
                query=str(payload.get("query") or ""), labels=_normalize_labels(payload.get("labels")),
                sample_role=str(payload.get("sample_role") or ""), page=int(payload.get("page") or 1), limit=limit,
                sort_order=str(payload.get("sort_order") or "oldest"), filters=payload,
                defer_role_counts=payload.get("defer_role_counts") is True,
                count_mode=str(payload.get("count_mode") or "exact"))
            usage = _page_usage_facts(repository,payload,result["items"])
            if usage['revision'] != usage_revision:
                raise ValueError('训练历史已更新，请重试素材查询')
            result["usage_revision"] = usage["revision"]
            truth = annotations.get_many([row["id"] for row in result["items"]])
            if (repository.current_revision(), annotations.current_revision()) != (result["repository_revision"], result["annotation_revision"]):
                raise ValueError("素材或标注已更新，请重试")
            from .training_label_tasks import training_material_role
            visible = []
            for row in result["items"]:
                annotation = truth.get(row["id"], {})
                issue = None
                if row["sample_role"] == "pending_review":
                    candidate = {**row, "annotation_state":annotation.get("annotation_state", "unannotated"),
                        "boxes":annotation.get("boxes") or [], "annotation_scope":annotation.get("annotation_scope") or []}
                    issue = training_material_role(candidate, contract).get("scope_issue")
                visible.append({**_public_picker_material(project_id, row, annotation),
                    "training_usage": _public_usage_fact(usage["by_image_id"].get(row["id"], {"state":"unknown"}), str(payload.get("algorithm_asset_id") or "")),
                    "sample_role": row["sample_role"],
                    "sample_role_issue_type": str((issue or {}).get("issue_type") or ""),
                    "annotation_version": int(annotation.get("version") or 0),
                    "source_content_sha256": str(row.get("content_sha256") or "")})
            result["items"] = visible
            return result
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @stage("training.negative_plan")
    def negative_plan(project_id, payload):
        from .training_label_tasks import (task_negative_confirmable, task_partial_scope_confirmable, task_negative_identity,
            task_negative_context, training_material_role, _ORIGINAL_SELECTED_PROJECT_IMAGES)
        repository = materials(project_id)
        annotations = AnnotationRepository(repository.project_path)
        revisions = (repository.current_revision(), annotations.current_revision())
        contract = task_contract(project_id, payload, repository)
        ids = _normalize_selection_ids([*(payload.get("train_image_ids") or []),
            *(payload.get("val_image_ids") or []), *(payload.get("selected_image_ids") or []), *(payload.get("image_ids") or []),
        ])
        rows = _ORIGINAL_SELECTED_PROJECT_IMAGES(repository, repository.project_path, ids)
        counts = dict(positive=0, confirmed_negative=0, pending_negative=0, pending_review=0)
        pending, pending_negatives, pending_partials, problems = [], [], [], []
        confirmed_receipts = {item.get("receipt_id") for item in contract.get("task_negative_confirmations") or []}
        pending_receipt_ids = set()
        labels = list(contract["effective_label_codes"])
        label_set = set(labels)
        class_images = {code: 0 for code in labels}
        class_boxes = {code: 0 for code in labels}
        full, partial = 0, 0
        partial_preview = []
        for row in rows:
            result = training_material_role(row, contract)
            role = result["role"]
            if role == "pending_review" and task_negative_confirmable(row, contract):
                role = "pending_negative"
                evidence = task_negative_identity(row, contract)
                pending.append(evidence)
                pending_negatives.append(evidence)
                pending_receipt_ids.add(evidence["receipt_id"])
            elif role == "pending_review" and task_partial_scope_confirmable(row, contract):
                # A missing target is not grounds to erase the already valid
                # positive boxes. The receipt only covers this task's scope.
                role = "positive"
                evidence = task_negative_identity(row, contract)
                pending.append(evidence)
                pending_partials.append(evidence)
                pending_receipt_ids.add(evidence["receipt_id"])
            counts[role] += 1
            if role == "positive":
                per_image = {}
                for box in row.get("boxes") or []:
                    code = str(box.get("label") or box.get("code") or "").strip()
                    if code in label_set:
                        per_image[code] = per_image.get(code, 0) + 1
                        class_boxes[code] += 1
                for code in per_image:
                    class_images[code] += 1
                if len(per_image) == len(labels):
                    full += 1
                elif per_image:
                    partial += 1
                    # Even when persisted GT already covers the missing
                    # classes, this partial-positive batch receives explicit
                    # task approval; this never widens formal GT.
                    evidence = task_negative_identity(row, contract)
                    if (evidence["receipt_id"] not in confirmed_receipts
                            and evidence["receipt_id"] not in pending_receipt_ids):
                        pending.append(evidence)
                        pending_partials.append(evidence)
                        pending_receipt_ids.add(evidence["receipt_id"])
                    if len(partial_preview) < 8:
                        image_id = str(row.get("id") or row.get("image_id") or "")
                        partial_preview.append({"image_id": image_id,
                            "image_url": f"/api/v62/projects/{project_id}/training-materials/{image_id}/thumbnail",
                            "label_box_counts": per_image,
                            "missing_label_codes": sorted(label_set - set(per_image))})
            elif role == "pending_review" and len(problems) < 10:
                issue = result.get("scope_issue") or {}
                problems.append({"image_id": str(row.get("id") or row.get("image_id") or ""),
                    "issue_type": str(issue.get("issue_type") or "invalid_ground_truth"),
                    "missing_label_codes": list(issue.get("missing_label_codes") or [])})
        if revisions != (repository.current_revision(), annotations.current_revision()):
            raise ValueError("素材或正式标注在样本检查期间发生变化，请重新检查")
        coverage = {"selected_count": len(rows), "eligible_count": len(rows) - counts["pending_review"],
            "full_coverage_count": full, "partial_coverage_count": partial,
            "zero_target_count": counts["confirmed_negative"] + counts["pending_negative"],
            "classes": [{"code": code, "image_count": class_images[code], "box_count": class_boxes[code]} for code in labels],
            "partial_preview": partial_preview, "problems": problems,
            "pending_negative_count": len(pending_negatives),
            "pending_partial_count": len(pending_partials),
            "pending_negative_preview": pending_negatives,
            "material_revision": revisions[0], "annotation_revision": revisions[1]}
        digest = hashlib.sha256(json.dumps({"context":task_negative_context(contract),
            "base_version_id":str(payload.get("base_version_id") or ""),
            "test_image_ids":sorted(_normalize_selection_ids(payload.get("test_image_ids") or [])),
            "revisions": revisions, "selected":sorted(ids),
            "identities":[task_negative_identity(row, contract) for row in rows], "pending":pending}, sort_keys=True).encode()).hexdigest()
        return repository, contract, counts, pending, digest, coverage

    @router.post("/negative-preview")
    def negative_preview(project_id: str, payload: dict):
        try:
            _, contract, counts, pending, digest, coverage = negative_plan(project_id, payload)
            offset = int(payload.get("preview_offset") or 0)
            if offset < 0:
                raise ValueError("invalid negative preview offset")
            previews = coverage.pop("pending_negative_preview")
            return {"counts":counts, "pending_count":coverage["pending_negative_count"],
                    "pending_scope_count":coverage["pending_partial_count"],
                    "preview_offset":offset, "preview_size":20,
                    "pending_preview":[{**e,"image_url":f"/api/v62/projects/{project_id}/training-materials/{e['image_id']}/thumbnail"} for e in previews[offset:offset+20]],
                    "base_training_mode":contract.get("base_training_mode", "mother_model_init"),
                    "proof_digest":digest, "effective_label_codes":contract["effective_label_codes"], "coverage":coverage}
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.post("/confirm-negatives")
    def confirm_negatives(project_id: str, payload: dict, request: Request):
        if payload.get("confirmed") is not True:
            raise HTTPException(status_code=422, detail="explicit confirmation required")
        if actor_provider is None:
            raise HTTPException(status_code=503, detail="authenticated actor unavailable")
        actor = actor_provider(request, project_id)
        try:
            from .training_label_tasks import task_negative_context
            from .material_repository import material_annotation_lifecycle_fence
            repository = materials(project_id)
            with material_annotation_lifecycle_fence(repository.project_path):
                repository, contract, counts, pending, digest, _ = negative_plan(project_id, payload)
                if payload.get("proof_digest") != digest:
                    raise HTTPException(status_code=409, detail="素材或标注已变化，请重新检查并确认")
                if counts["pending_review"]:
                    raise ValueError("存在失效或无效标注，不能确认为负样本")
                receipts = AnnotationRepository(repository.project_path).confirm_task_negatives(
                    task_negative_context(contract), pending, actor)
            return {"confirmed_count":len(receipts), "receipt_ids":receipts}
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.post("/review-negative")
    def review_negative(project_id: str, payload: dict, request: Request):
        if payload.get("confirmed") is not True:
            raise HTTPException(status_code=422, detail="explicit review confirmation required")
        items = payload.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 50 or not all(isinstance(i, dict) for i in items):
            raise HTTPException(status_code=422, detail="review items must contain 1 to 50 images")
        if len({str(i.get("image_id") or "") for i in items}) != len(items):
            raise HTTPException(status_code=422, detail="duplicate review image ids")
        repository = materials(project_id)
        try:
            contract = task_contract(project_id, payload, repository)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if review_negative_provider is None:
            raise HTTPException(status_code=503, detail="formal annotation review unavailable")
        actor = actor_provider(request, project_id) if actor_provider else {}
        succeeded, failures = [], []
        for item in items:
            image_id = str(item.get("image_id") or "")
            try:
                review_negative_provider(project_id, item, list(contract["effective_label_codes"]), actor)
                succeeded.append(image_id)
            except Exception as error:
                if not hasattr(error, "status_code") and not isinstance(error, ValueError):
                    raise
                failures.append({"image_id": image_id, "status_code": getattr(error, "status_code", 422),
                                 "message": str(getattr(error, "detail", str(error)))})
        return {"succeeded": succeeded, "failures": failures, "effective_label_codes": contract["effective_label_codes"]}

    @router.post("/review-scopes")
    def review_missing_scopes(project_id: str, payload: dict, request: Request):
        """Human-attested, per-image review of missing labels on existing formal GT.

        Never infer that an unlabelled image is empty. Every image must already
        have valid formal GT, and the exact missing codes are recomputed from
        authoritative GT rather than accepted from the browser.
        """
        if payload.get("confirmed") is not True:
            raise HTTPException(status_code=422, detail="explicit human review confirmation required")
        items = payload.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 50 or not all(isinstance(item, dict) for item in items):
            raise HTTPException(status_code=422, detail="review items must contain 1 to 50 images")
        ids = [str(item.get("image_id") or "").strip() for item in items]
        if any(not image_id for image_id in ids) or len(set(ids)) != len(ids):
            raise HTTPException(status_code=422, detail="review image ids must be unique and nonempty")
        if actor_provider is None or review_negative_provider is None:
            raise HTTPException(status_code=503, detail="authenticated formal review unavailable")
        material_revision = payload.get("expected_material_revision")
        annotation_revision = payload.get("expected_annotation_revision")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
               for value in (material_revision, annotation_revision)):
            raise HTTPException(status_code=422, detail="material and GT revisions are required")
        repository = materials(project_id)
        annotations = annotation_repository_for_path(str(repository.project_path))
        try:
            contract = task_contract(project_id, payload, repository)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        actor = actor_provider(request, project_id)
        if not str((actor or {}).get("actor_id") or "").strip():
            raise HTTPException(status_code=401, detail="authenticated reviewer required")
        revisions = (material_revision, annotation_revision)
        if revisions != (repository.current_revision(), annotations.current_revision()):
            raise HTTPException(status_code=409, detail="material or GT revision changed; refresh the review")
        materials_by_id = {row["id"]: row for row in repository.get_many(ids)}
        annotations_by_id = annotations.get_many(ids)
        if revisions != (repository.current_revision(), annotations.current_revision()):
            raise HTTPException(status_code=409, detail="material or GT revision changed during review")

        from .training_label_tasks import training_material_role
        allowed = set(contract["effective_label_codes"])
        succeeded, failures = [], []
        for item, image_id in zip(items, ids):
            try:
                codes = item.get("reviewed_label_codes")
                if (not isinstance(codes, list) or not codes or
                        any(not isinstance(code, str) or not code.strip() for code in codes) or
                        len(set(codes)) != len(codes) or not set(codes) <= allowed):
                    raise ValueError("reviewed labels must be explicit active task labels")
                material = materials_by_id.get(image_id)
                annotation = annotations_by_id.get(image_id)
                if material is None or annotation is None:
                    raise ValueError("formal material and GT must exist before batch review")
                source_hash = str(item.get("source_content_sha256") or "").strip().lower()
                expected = item.get("expected_version")
                if (not isinstance(expected, int) or isinstance(expected, bool) or
                        expected < 0 or len(source_hash) != 64 or
                        any(char not in "0123456789abcdef" for char in source_hash) or
                        source_hash != str(material.get("content_sha256") or "").strip().lower() or
                        expected != int(annotation.get("version") or 0)):
                    raise ValueError("material or GT version changed; reopen the image")
                row = {**material, "annotation_state": annotation.get("annotation_state"),
                       "annotation_scope": annotation.get("annotation_scope") or [],
                       "boxes": annotation.get("boxes") or [],
                       "annotation_version": annotation.get("version")}
                issue = training_material_role(row, contract).get("scope_issue")
                if (not issue or issue.get("issue_type") != "partial_review_scope" or
                        set(issue.get("missing_label_codes") or []) != set(codes)):
                    raise ValueError("only the current, exact missing formal GT scope can be batch reviewed")
                if any(str(box.get("label") or box.get("code") or "") in set(codes)
                       for box in annotation.get("boxes") or []):
                    raise ValueError("existing target boxes require individual annotation review")
                review_negative_provider(project_id, item, sorted(codes), actor)
                succeeded.append(image_id)
            except Exception as error:
                if not hasattr(error, "status_code") and not isinstance(error, ValueError):
                    raise
                failures.append({"image_id": image_id, "status_code": getattr(error, "status_code", 422),
                                 "message": str(getattr(error, "detail", str(error)))})
        return {"succeeded": succeeded, "failures": failures,
                "effective_label_codes": contract["effective_label_codes"]}

    def scope_review_owner(project_id, request):
        if actor_provider is None or review_negative_provider is None:
            raise HTTPException(status_code=503, detail="authenticated formal review unavailable")
        actor = actor_provider(request, project_id)
        reviewer_id = str((actor or {}).get("actor_id") or "").strip()
        if not reviewer_id:
            raise HTTPException(status_code=401, detail="authenticated reviewer required")
        return actor, reviewer_id

    @router.post("/review-scope-plans")
    def plan_scope_review(project_id: str, payload: dict, request: Request):
        """Freeze all selected training issues before any human GT attestation.

        Full-filter/cross-page selection is resolved against the *server's*
        compatibility projection. Non-scope issues remain blocked and visible;
        they can never be converted into formal absence evidence by bulk action.
        """
        from .training_label_tasks import training_material_role
        _, reviewer_id = scope_review_owner(project_id, request)
        repository = materials(project_id)
        annotations = annotation_repository_for_path(str(repository.project_path))
        expected = (payload.get('expected_material_revision'), payload.get('expected_annotation_revision'))
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in expected):
            raise HTTPException(422, detail="material and GT revisions are required")
        algorithm = algorithm_provider(project_id, str(payload.get('algorithm_asset_id') or '')) if algorithm_provider else None
        if algorithm is None:
            raise HTTPException(404, detail="training algorithm unavailable")
        if not isinstance(payload.get('selection'), dict):
            raise HTTPException(422, detail="selection must be a review scope object")
        if payload['selection'].get('previous_execution_task_id'):
            raise HTTPException(422, detail="prior deletion selections cannot be used for formal GT review")
        try:
            ids = _normalize_selection_ids(payload.get('train_image_ids') or [])
            request_payload = {**payload, 'train_image_ids':ids,
                               'test_image_ids':_normalize_selection_ids(payload.get('test_image_ids') or [])}
            if compatibility_payload_provider:
                request_payload = compatibility_payload_provider(project_id, algorithm, request_payload)
            projection = evaluate_training_compatibility_projection(
                data_dir(), repository.project_path, request_payload, algorithm)
            chosen = resolve_training_compatibility_selection(projection, payload)['matching_image_ids']
            if not chosen:
                raise ValueError('请先勾选需要人工补审的训练问题素材')
            if len(chosen) > MAX_SELECTION_SUMMARY_IDS:
                raise ValueError('人工补审范围超过单次冻结上限')
            contract = task_contract(project_id, payload, repository)
            codes = set(contract['effective_label_codes'])
            if codes != set(projection.label_contract.get('effective_label_codes') or codes):
                raise ValueError('训练类别契约已变化，请重新预检')
            issues_by_id = {}
            for issue in projection.issues:
                issues_by_id.setdefault(str(issue['image_id']), []).append(issue)
            items = []
            for offset in range(0, len(chosen), 500):
                chunk = chosen[offset:offset + 500]
                by_material = {row['id']:row for row in repository.get_many(chunk)}
                by_annotation = annotations.get_many(chunk)
                for image_id in chunk:
                    issues = issues_by_id.get(image_id, [])
                    row = by_material.get(image_id)
                    gt = by_annotation.get(image_id)
                    problem = ''
                    missing = sorted({str(code) for issue in issues for code in issue.get('missing_label_codes') or []})
                    if not issues or any(issue.get('issue_type') != 'partial_review_scope' for issue in issues):
                        problem = '存在非审核范围类问题，请逐张修复或排除'
                    elif not row or not gt:
                        problem = '素材或正式 GT 不存在，不能批量确认'
                    elif not missing or not set(missing) <= codes:
                        problem = '待审类别与本次训练类别不一致'
                    else:
                        candidate = {**row, 'annotation_state':gt.get('annotation_state'),
                            'boxes':gt.get('boxes') or [], 'annotation_scope':gt.get('annotation_scope') or [],
                            'annotation_version':gt.get('version')}
                        scope = training_material_role(candidate, contract).get('scope_issue')
                        if (not scope or scope.get('issue_type') != 'partial_review_scope'
                                or set(scope.get('missing_label_codes') or []) != set(missing)
                                or any(str(box.get('label') or box.get('code') or '') in set(missing)
                                       for box in gt.get('boxes') or [])):
                            problem = '正式 GT 与待补审范围不一致，请单张核验'
                    source_sha = str((row or {}).get('content_sha256') or '').strip().lower()
                    if not problem and (len(source_sha) != 64 or any(c not in '0123456789abcdef' for c in source_sha)):
                        problem = '原图摘要无效，请修复来源'
                    items.append({'image_id':image_id, 'status':'blocked' if problem else 'pending',
                        'reviewed_label_codes':missing if not problem else [],
                        'expected_version':int(gt.get('version') or 0) if gt else None,
                        'source_content_sha256':source_sha, 'message':problem})
            if expected != (repository.current_revision(), annotations.current_revision()):
                raise HTTPException(409, detail="material or GT changed while freezing review; repeat preflight")
            return TrainingScopeReviewPlans(repository.project_path).create(
                project_id=project_id, actor_id=reviewer_id, request=payload,
                contract_codes=codes, material_revision=expected[0],
                annotation_revision=expected[1], items=items)
        except ValueError as error:
            status = 409 if 'STALE' in str(error) or 'CHANGED' in str(error) else 422
            raise HTTPException(status_code=status, detail=str(error)) from error

    @router.get("/review-scope-plans/{task_id}")
    def read_scope_review_plan(project_id: str, task_id: str, request: Request):
        _, reviewer_id = scope_review_owner(project_id, request)
        repository = materials(project_id)
        try:
            return TrainingScopeReviewPlans(repository.project_path).read(
                task_id, project_id=project_id, actor_id=reviewer_id)
        except LookupError as error:
            raise HTTPException(404, detail=str(error)) from error

    @router.get("/review-scope-plans/{task_id}/results")
    def list_scope_review_results(project_id: str, task_id: str, request: Request,
                                  state: str = 'problems', cursor: int = 0, limit: int = 50):
        _, reviewer_id = scope_review_owner(project_id, request)
        repository = materials(project_id)
        try:
            return TrainingScopeReviewPlans(repository.project_path).results(
                task_id, project_id=project_id, actor_id=reviewer_id,
                state=state, cursor=cursor, limit=limit)
        except LookupError as error:
            raise HTTPException(404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(422, detail=str(error)) from error

    @router.post("/review-scope-plans/{task_id}/execute")
    def execute_scope_review_plan(project_id: str, task_id: str, payload: dict, request: Request):
        if payload.get('confirmed') is not True:
            raise HTTPException(422, detail="explicit human review confirmation required")
        try:
            limit = int(payload.get('max_items', 20))
            if isinstance(payload.get('max_items'), bool) or not 1 <= limit <= 50:
                raise ValueError('review step must contain 1 to 50 images')
        except (ValueError, TypeError) as error:
            raise HTTPException(422, detail='review step must contain 1 to 50 images') from error
        actor, reviewer_id = scope_review_owner(project_id, request)
        repository = materials(project_id)
        annotations = annotation_repository_for_path(str(repository.project_path))
        plans = TrainingScopeReviewPlans(repository.project_path)
        try:
            metadata = plans.metadata(task_id, project_id=project_id, actor_id=reviewer_id)
        except LookupError as error:
            raise HTTPException(404, detail=str(error)) from error
        frozen_request = json.loads(metadata['request_json'])
        try:
            contract = task_contract(project_id, frozen_request, repository)
        except ValueError as error:
            raise HTTPException(409, detail=str(error)) from error
        if set(contract['effective_label_codes']) != set(json.loads(metadata['contract_codes_json'])):
            raise HTTPException(409, detail="training label contract changed; create a new review plan")

        from .training_label_tasks import training_material_role
        def review_one(plan, item):
            # Saving formal GT also updates the material's derived annotation
            # projection and bumps the pool revision. Never compare subsequent
            # steps with the *initial global* revision: each frozen source hash,
            # original GT version and current per-image validity is the CAS.
            image_id = item['image_id']
            row, gt = repository.get(image_id), annotations.get(image_id)
            if not row or not gt:
                raise ValueError('material or formal GT no longer exists')
            sha = item['source_content_sha256']
            previous_gt_source = str(row.get('annotation_source_content_sha256') or '').strip().lower()
            if (len(sha) != 64 or sha != str(row.get('content_sha256') or '').strip().lower()
                    or (previous_gt_source and previous_gt_source != sha)
                    or row.get('processing_status') != 'processed'
                    or row.get(DATASET_DELETE_CLAIM_FIELD) or row.get(MATERIAL_BATCH_DELETE_CLAIM_FIELD)
                    or row.get('source_available') is False or any(row.get(flag) for flag in
                        ('annotation_needs_review','external_annotation_needs_review','needs_review'))):
                raise ValueError('material source changed or requires individual review')
            codes = set(item['reviewed_label_codes'])
            if not codes or not codes <= set(contract['effective_label_codes']):
                raise ValueError('frozen review labels are invalid')
            if int(gt.get('version') or 0) != item['expected_version']:
                # A crash after formal-GT commit but before plan progress commit
                # is retried by reconciling that *same actor's* durable evidence.
                evidence = annotations.negative_review_evidence(
                    image_id, item['expected_version'], reviewer_id, sorted(codes), sha)
                if (evidence and int(gt.get('version') or 0) == evidence['annotation_version']
                        and gt.get('content_digest') == evidence['annotation_digest']):
                    return
                raise ValueError('formal GT version changed; reopen this image')
            candidate = {**row, 'annotation_state':gt.get('annotation_state'),
                         'annotation_scope':gt.get('annotation_scope') or [], 'boxes':gt.get('boxes') or [],
                         'annotation_version':gt.get('version')}
            issue = training_material_role(candidate, contract).get('scope_issue')
            if (not issue or issue.get('issue_type') != 'partial_review_scope'
                    or set(issue.get('missing_label_codes') or []) != codes
                    or any(str(box.get('label') or box.get('code') or '') in codes for box in gt.get('boxes') or [])):
                raise ValueError('GT no longer has the exact missing review scope')
            review_negative_provider(project_id, item, sorted(codes), actor)

        try:
            return plans.execute(task_id, project_id=project_id, actor_id=reviewer_id,
                                 limit=limit, reviewer=review_one)
        except LookupError as error:
            raise HTTPException(404, detail=str(error)) from error

    @router.get("")
    def list_training_materials(
        project_id: str,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        page: int | None = None,
        page_size: int | None = None,
        query: str = "",
        label: list[str] | None = Query(default=None),
        sort_order: str = "oldest",
        storage_source_id: list[str] | None = Query(default=None),
        negative_pool_only: bool = False,
        negative_category_id: list[str] | None = Query(default=None),
        annotation_state: str = "", created_from: str = "", created_to: str = "",
        usage_state: str = "", algorithm_asset_id: str = "", history_policy: str = "new_for_algorithm", role: str = "train", history_scope: str = "",
        count_mode: str = "exact",
        label_mode: str = "any",
    ):
        numbered = page is not None or page_size is not None
        requested_page = int(page or 1) if numbered else None
        requested_size = int(page_size if page_size is not None else limit)
        if not 1 <= requested_size <= MAX_PAGE_SIZE:
            raise HTTPException(status_code=422, detail=f"limit must be between 1 and {MAX_PAGE_SIZE}")
        if count_mode not in {"exact", "deferred"}:
            raise HTTPException(status_code=422, detail="count_mode must be exact or deferred")
        repository = materials(project_id)
        annotation_repository = annotation_repository_for_path(
            str(repository.project_path)
        )
        selected_labels = tuple(label or ())
        shared_filters = {"storage_source_ids":storage_source_id or [], "annotation_state":annotation_state, "created_from":created_from, "created_to":created_to, "negative_pool_only":negative_pool_only,"negative_category_ids":negative_category_id or [],"label_mode":label_mode}
        shared_filters = {k:v for k,v in shared_filters.items() if v}
        try:
            shared_filters, usage = _usage_filters(repository, {**shared_filters, "usage_state":usage_state,"algorithm_asset_id":algorithm_asset_id,"history_policy":history_policy,"role":role,"history_scope":history_scope,"browse_only":True})
            usage_revision = usage['revision']
            if selected_labels or shared_filters or count_mode == "deferred":
                page = _gt_material_filter_page(
                    repository,
                    annotation_repository,
                    cursor=cursor,
                    page=requested_page,
                    limit=requested_size,
                    query=str(query or "").strip(),
                    labels=selected_labels,
                    include_payload=True,
                    sort_order=sort_order,
                    filters=shared_filters,
                    count_mode=count_mode,
                )
                rows = [dict(row) for row in page["items"]]
                next_cursor = page["next_cursor"]
                total = page["total"]
                has_next = page["has_next"]
                repository_revision = int(page["material_revision"])
                annotation_revision = int(page["annotation_revision"])
            else:
                material_page = repository.list_page(
                    cursor=cursor,
                    page=requested_page,
                    limit=requested_size,
                    query=str(query or "").strip(),
                    processing_status="processed",
                    sort_order=sort_order,
                )
                rows = [dict(row) for row in material_page.items]
                next_cursor = material_page.next_cursor
                total = material_page.total
                has_next = bool(next_cursor)
                repository_revision = repository.current_revision()
                annotation_revision = annotation_repository.current_revision()
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        usage = _page_usage_facts(repository,shared_filters,rows)
        if usage['revision'] != usage_revision:
            raise HTTPException(status_code=409, detail='训练历史已更新，请重试素材查询')
        annotations = annotation_repository.get_many(
            [str(row.get("id") or "") for row in rows]
        )
        response = {
            "items": [
                {**_public_picker_material(
                    project_id,
                    row,
                    annotations.get(
                        str(row.get("id") or ""),
                        {"annotation_state": "unannotated", "boxes": []},
                    ),
                ), "training_usage":_public_usage_fact(usage["by_image_id"].get(str(row.get("id")), {"state":"unknown"}), algorithm_asset_id)}
                for row in rows
            ],
            "next_cursor": next_cursor,
            "total": total,
            "limit": requested_size,
            "repository_revision": repository_revision,
            "annotation_revision": annotation_revision,
            "negative_confirmation_revision": annotation_repository.task_negative_confirmation_revision(),
            "negative_pool_revision": NegativePool(repository).revision(),
            "usage_revision": usage["revision"],
        }
        if numbered:
            total_pages = max(1, math.ceil(total / requested_size)) if total is not None else None
            response.update({
                "page": requested_page,
                "page_size": requested_size,
                "total_pages": total_pages,
                "has_previous": requested_page > 1,
                "has_next": has_next if total_pages is None else requested_page < total_pages,
            })
        return response

    @router.get("/ids")
    def list_training_material_ids(
        project_id: str,
        cursor: str | None = None,
        limit: int = 500,
        query: str = "",
        label: list[str] | None = Query(default=None),
    ):
        if not 1 <= int(limit) <= 500:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
        repository = materials(project_id)
        annotation_repository = annotation_repository_for_path(
            str(repository.project_path)
        )
        selected_labels = tuple(label or ())
        try:
            if selected_labels:
                page = _gt_material_filter_page(
                    repository,
                    annotation_repository,
                    cursor=cursor,
                    limit=int(limit),
                    query=str(query or "").strip(),
                    labels=selected_labels,
                    include_payload=False,
                )
                items = page["items"]
                next_cursor = page["next_cursor"]
                total = int(page["total"])
                repository_revision = int(page["material_revision"])
                annotation_revision = int(page["annotation_revision"])
            else:
                material_page = repository.iter_filtered_ids(
                    {
                        "query": str(query or "").strip(),
                        "processing_status": "processed",
                    },
                    cursor=cursor,
                    limit=int(limit),
                    include_total=True,
                )
                items = material_page.items
                next_cursor = material_page.next_cursor
                total = material_page.total
                repository_revision = repository.current_revision()
                annotation_revision = annotation_repository.current_revision()
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "items": items,
            "next_cursor": next_cursor,
            "total": total,
            "repository_revision": repository_revision,
            "annotation_revision": annotation_revision,
            "negative_confirmation_revision": annotation_repository.task_negative_confirmation_revision(),
            "negative_pool_revision": NegativePool(repository).revision(),
        }

    @router.post('/selection-membership')
    def training_selection_membership(project_id: str,payload: dict):
        from .training_selection_reference import selection_membership,selection_context
        materials(project_id)
        try:
            context=selection_context(data_dir(),project_id,payload,str(payload.get('role') or 'train'))
            return {'items':selection_membership(data_dir(),payload.get('selection_ref'),context,payload.get('image_ids') or [])}
        except (ValueError,TypeError) as error:raise HTTPException(422,str(error)) from error

    @router.post('/selection-reference')
    def freeze_training_material_reference(project_id: str, payload: dict):
        from .training_selection_reference import freeze_selection,selection_context
        repository=materials(project_id)
        annotations=annotation_repository_for_path(str(repository.project_path))
        body=dict(payload)
        role=str(body.get('role') or 'train')
        try:
            if not str(body.get('algorithm_asset_id') or ''):raise ValueError('请选择目标算法')
            before=selection_context(data_dir(),project_id,body,role)
            filters,_=_usage_filters(repository,{**body,'browse_only':False})
            labels=_normalize_labels(body.get('labels'))
            query=str(body.get('query') or '').strip()
            selected_role=str(body.get('sample_role') or '')
            if selected_role and selected_role not in {'positive','confirmed_negative','pending_negative','pending_review'}:raise ValueError('invalid sample_role')
            contract=task_contract(project_id,body,repository) if selected_role else None
            def ids():
                page_number=1
                while True:
                    if selected_role:
                        result=_role_material_page(repository,annotations,contract,limit=1000,page=page_number,
                            query=query,labels=labels,sort_order=str(body.get('sort_order') or 'newest'),
                            filters=filters,count_mode='deferred',defer_role_counts=True)
                        yield from (row['id'] for row in result['items'] if row['sample_role']==selected_role)
                    else:
                        result=_gt_material_filter_page(repository,annotations,limit=1000,page=page_number,
                            query=query,labels=labels,sort_order=str(body.get('sort_order') or 'newest'),
                            filters=filters,count_mode='deferred')
                        yield from result['items']
                    if not result['has_next']:break
                    page_number+=1
            # Role-filtered plans must not silently select outside the filter.
            receipt=freeze_selection(data_dir(),before,ids(),request_id=body.get('request_id'),
                request_scope=json.dumps({k:v for k,v in body.items() if k!='request_id'},sort_keys=True))
            if selection_context(data_dir(),project_id,body,role)!=before:
                raise ValueError('素材证据已变化，请重新选择')
            return {**receipt,'role':role,'history_policy':before['history_policy']}
        except (ValueError,TypeError) as error:
            raise HTTPException(422,str(error)) from error

    @router.post("/bulk-selection")
    def resolve_training_material_bulk_selection(project_id: str, payload: dict):
        from .training_material_usage import TrainingMaterialUsage
        repository = materials(project_id)
        body = payload if isinstance(payload, dict) else {}
        try:
            if body.get("all_available"):
                body = {k:v for k,v in body.items() if k in {"algorithm_asset_id","role","all_available","train_labels","base_version_id","model","framework","image_ids","history_policy","label_mode"}}
            body, usage = _usage_filters(repository, {**body, "browse_only":False})
            labels = _normalize_labels(body.get("labels"))
            query = "" if bool(body.get("all_available")) else str(body.get("query") or "").strip()
            if bool(body.get("all_available")):
                labels = ()
            role = str(body.get("role") or "train").strip().lower()
            if role not in {"train", "test"}:
                raise ValueError("role must be train or test")
            annotations = annotation_repository_for_path(
                str(repository.project_path)
            )
            # Bulk selection is an atomic UI operation. Both auxiliary facts
            # already participate in picker page revisions; never accept an
            # ID set assembled while either one changes.
            negative_confirmation_revision = annotations.task_negative_confirmation_revision()
            negative_pool_revision = NegativePool(repository).revision()
            if body.get("sample_role"):
                contract = task_contract(project_id, body, repository)
                role_page = _role_material_page(repository, annotations, contract, query=query, labels=labels,
                    sample_role=str(body["sample_role"]), limit=MAX_SELECTION_SUMMARY_IDS, filters=body, include_payload=False)
                if role_page["total"] > MAX_SELECTION_SUMMARY_IDS:
                    raise ValueError(f"筛选结果共 {role_page['total']} 张，超过单次选择上限 {MAX_SELECTION_SUMMARY_IDS} 张")
                if TrainingMaterialUsage(repository.project_path.parent.parent / "task_runtime" / "tasks.sqlite3").read_revision() != usage['revision']:
                    raise ValueError("训练历史已更新，请重试批量选择")
                if (annotations.task_negative_confirmation_revision() != negative_confirmation_revision
                        or NegativePool(repository).revision() != negative_pool_revision):
                    raise ValueError("负样本池或确认记录已更新，请重新解析批量选择")
                return {"items": [row["id"] for row in role_page["items"]], "total": role_page["total"],
                        "repository_revision": repository.current_revision(),
                        "annotation_revision": annotations.current_revision(), "usage_revision": usage['revision'],
                        "negative_confirmation_revision": negative_confirmation_revision,
                        "negative_pool_revision": negative_pool_revision,
                        "selection_mode": "filtered"}
            ids, total = _bulk_filtered_ids(
                repository,
                annotations,
                query=query,
                labels=labels,
                require_ground_truth=role == "test",
                filters=body,
            )
            if TrainingMaterialUsage(repository.project_path.parent.parent / "task_runtime" / "tasks.sqlite3").read_revision() != usage['revision']:
                raise ValueError("训练历史已更新，请重试批量选择")
            if (annotations.task_negative_confirmation_revision() != negative_confirmation_revision
                    or NegativePool(repository).revision() != negative_pool_revision):
                raise ValueError("负样本池或确认记录已更新，请重新解析批量选择")
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "items": ids,
            "total": total,
            "repository_revision": repository.current_revision(),
            "annotation_revision": annotations.current_revision(),
            "usage_revision": usage['revision'],
            "negative_confirmation_revision": negative_confirmation_revision,
            "negative_pool_revision": negative_pool_revision,
            "selection_mode": "all_available" if bool(body.get("all_available")) else "filtered",
        }

    @router.post("/selection-summary")
    def training_material_selection_summary(project_id: str, payload: dict):
        try:
            image_ids = _normalize_selection_ids(payload.get("image_ids") if isinstance(payload, dict) else None)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        repository = materials(project_id)
        annotations = annotation_repository_for_path(str(repository.project_path))
        try:
            summary = _selection_summary(
                repository, annotations, image_ids,
                include_pool_totals=payload.get("summary_only") is not True,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        # Previewing an empty selection is not a training submission. In
        # particular, an iteration's base_version_id must not invoke the
        # submission-only nonempty train_image_ids contract before picking.
        if (not payload.get("summary_only") and image_ids and payload.get("algorithm_asset_id")
                and (payload.get("train_labels") or payload.get("base_version_id"))):
            try:
                contract = task_contract(project_id, payload, repository)
                roles = _role_material_page(repository, annotations, contract, image_ids=image_ids, limit=1)
                _, _, counts, pending, _, _ = negative_plan(project_id, dict(payload, image_ids=image_ids))
                summary.update(sample_role_counts=counts, effective_label_codes=roles["effective_label_codes"])
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
        return {**summary, "repository_revision": repository.current_revision()}

    @router.post("/compatibility")
    @stage("training.compatibility")
    def training_material_compatibility(project_id: str, payload: dict):
        body = payload if isinstance(payload, dict) else {}
        algorithm_id = str(body.get("algorithm_asset_id") or "").strip()
        if algorithm_provider is None:
            raise HTTPException(status_code=503, detail="训练标签适配服务不可用")
        algorithm = algorithm_provider(project_id, algorithm_id)
        if algorithm is None:
            raise HTTPException(status_code=404, detail="训练算法不存在")
        try:
            selected_ids = (
                body.get("image_ids")
                if "image_ids" in body
                else body.get("train_image_ids")
            )
            image_ids = _normalize_selection_ids(selected_ids)
            request = {
                **body,
                "train_image_ids": image_ids,
                "test_image_ids": list(body.get("test_image_ids") or []),
            }
            if compatibility_payload_provider is not None:
                request = compatibility_payload_provider(
                    project_id,
                    algorithm,
                    request,
                )
            repository = materials(project_id)
            result = evaluate_training_compatibility_projection(
                data_dir(), repository.project_path, request, algorithm,
            )
            if body.get('selection_action') == 'RESOLVE_SELECTION':
                return resolve_training_compatibility_selection(result, body)
            page = compatibility_page(
                result,
                query=str(body.get("query") or ""),
                issue_type=str(body.get("issue_type") or ""),
                missing_label_code=str(body.get("missing_label_code") or ""),
                cursor=str(body.get("cursor") or ""),
                limit=int(body.get("limit") or 50),
                page=body.get("page"),
                page_size=body.get("page_size"),
            )
        except ValueError as error:
            stale_selection = body.get('selection_action') == 'RESOLVE_SELECTION' and any(
                code in str(error) for code in ('TRAINING_SELECTION_STALE', 'TRAINING_SELECTION_CHANGED', 'TRAINING_REVIEW_STALE')
            )
            # Preserve the existing preflight's 422 validation contract. Only
            # the new revision-bound selection mutation reports a CAS conflict.
            raise HTTPException(status_code=409 if stale_selection else 422, detail=str(error)) from error
        items = []
        for item in page["items"]:
            image_id = str(item.get("image_id") or "")
            encoded = quote(image_id, safe="")
            items.append({
                **item,
                "thumbnail_url": (
                    f"/api/v62/projects/{quote(str(project_id), safe='')}"
                    f"/training-materials/{encoded}/thumbnail?size={DEFAULT_THUMBNAIL_SIZE}"
                ),
                "content_url": (
                    f"/api/v61/projects/{quote(str(project_id), safe='')}"
                    f"/materials/{encoded}/content"
                ),
            })
        return {
            **result.summary(),
            **page,
            "items": items,
            "repository_revision": repository.current_revision(),
        }

    @router.get("/{image_id}/robustness-preview")
    def robustness_preview(project_id: str, image_id: str, preset: str = 'bt601_limited'):
        from .training_robustness import PRESETS, transform_rgb
        from io import BytesIO
        import base64
        if preset not in PRESETS:
            raise HTTPException(422, detail='未知颜色预设')
        row = materials(project_id).get(image_id)
        if not row or row.get('_dataset_delete_claim') or row.get('_material_batch_delete_claim') or row.get('source_available') is False:
            raise HTTPException(409, detail='素材当前不可用于预览')
        thumbnail = training_material_thumbnail(project_id, image_id, 256)
        if not getattr(thumbnail, 'path', None):
            raise HTTPException(503, detail='缩略图暂不可用，请从素材详情核对来源后重试')
        def encoded(image):
            stream = BytesIO(); image.save(stream, format='PNG')
            return 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode('ascii')
        with Image.open(thumbnail.path) as source:
            before = source.convert('RGB'); after = transform_rgb(before, preset)
            return {'preset':preset, 'before':encoded(before), 'after':encoded(after),
                    'pixel_changed':before.tobytes()!=after.tobytes(), 'width':before.width, 'height':before.height,
                    'scope':'thumbnail_preview_only', 'transform_version':'rgb_yuv_decoder_mismatch_v1'}

    @router.get("/{image_id}/thumbnail")
    def training_material_thumbnail(project_id: str, image_id: str, size: int = DEFAULT_THUMBNAIL_SIZE):
        repository = materials(project_id)
        row = repository.get(image_id)
        if row is None:
            raise HTTPException(status_code=404, detail="素材不存在")
        requested = int(size)
        thumbnail_size = min(ALLOWED_THUMBNAIL_SIZES, key=lambda value: abs(value - requested))
        target = _thumbnail_path(data_dir(), project_id, dict(row), thumbnail_size)
        if not target.is_file():
            lock_started = perf_counter()
            with FileLock(str(target) + ".lock", timeout=30):
                observe_duration("thumbnail.lock_wait", (perf_counter() - lock_started) * 1000)
                if not target.is_file():
                    count("thumbnail.cache_miss")
                    try:
                        manager = StorageManager(data_dir=data_dir(), project_id=project_id, materials=repository)
                        with measure("thumbnail.materialize"):
                            materialized = manager.materialize(dict(row), read_only=True)
                        with measure("thumbnail.render"):
                            _write_thumbnail(Path(materialized.path), target, thumbnail_size)
                    except (OSError, ValueError, UnidentifiedImageError, StorageError):
                        raise HTTPException(status_code=503, detail={
                            'code':'THUMBNAIL_UNAVAILABLE','message':'缩略图暂不可用，请重试',
                            'retryable':True,
                        })
                else:
                    count("thumbnail.cache_hit")
        else:
            count("thumbnail.cache_hit")
        return FileResponse(
            target,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "private, max-age=604800, immutable",
                "ETag": f'"{target.stem}"',
            },
        )

    return router
