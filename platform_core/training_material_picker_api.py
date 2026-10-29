"""Server-owned material paging and summaries for the training picker.

The training UI must never hydrate the whole project material pool in the browser.
Metadata comes from MaterialRepository cursor paging, selected-material facts are
aggregated inside SQLite, and thumbnails are created lazily on demand.
"""
from __future__ import annotations

from .performance_diagnostics import observe_connection, stage, count

import hashlib
import json
import math
import os
import sqlite3
import tempfile
import threading
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
    _deferred_material_page_sql,
    decode_material_cursor,
    encode_material_cursor,
)
from .storage.errors import StorageError
from .storage.manager import StorageManager
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
        "boxes": boxes,
        "processing_status": str(row.get("processing_status") or ""),
        "annotation_state": annotation_state,
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
    with closing(observe_connection(sqlite3.connect(repository.path, timeout=30))) as db:
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


def _usage_filters(repository, filters):
    from .training_material_usage import TrainingMaterialUsage
    body = dict(filters or {})
    state = str(body.get("usage_state") or "")
    if state and state not in {"used", "possible", "selected", "unused", "unknown", "eval_only"}:
        raise ValueError("invalid usage_state")
    scope = str(body.get("history_scope") or "")
    if scope not in {"", "current_only", "other_only"}: raise ValueError("invalid history_scope")
    algorithm_id = str(body.get("algorithm_asset_id") or "")
    task_path = repository.project_path.parent.parent / "task_runtime" / "tasks.sqlite3"
    policy = str(body.get("history_policy") or "new_for_algorithm")
    if policy not in {"new_for_algorithm", "include_history"}: raise ValueError("invalid history_policy")
    usage_revision = TrainingMaterialUsage(task_path).read_revision()
    if policy == "include_history" and not state and not scope:
        return body, {"revision":usage_revision,"coverage":"unknown","by_image_id":{},"excluded_image_ids":[],"unknown_image_ids":[]}
    count("usage_pool_requests")
    facts = _cached_usage_pool(str(repository.project_path), str(task_path), repository.current_revision(),
        algorithm_id, usage_revision, str(body.get("role") or "train"), policy == "new_for_algorithm")
    excluded=set(facts["excluded_image_ids"])
    if state or scope:
        eligible=[key for key,value in facts["by_image_id"].items() if (not state or value["state"] == state) and not value["excluded"] and (not scope or (value.get("current_algorithm_trained",False) and not value.get("other_algorithm_trained",False) if scope=="current_only" else value.get("other_algorithm_trained",False) and not value.get("current_algorithm_trained",False)))]
        if state and not scope:
            eligible.extend(i for i in facts.get("state_ids",{}).get(state,[]) if i not in excluded)
        body["usage_image_ids"]=eligible
    elif excluded:
        body["usage_excluded_image_ids"]=sorted(excluded)
    return body, facts


def _page_usage_facts(repository, body, rows):
    from .training_material_usage import TrainingMaterialUsage
    path=repository.project_path.parent.parent / "task_runtime" / "tasks.sqlite3"
    return TrainingMaterialUsage(path).query_filter(repository.project_path.name,str(body.get("algorithm_asset_id") or ""),
        rows,exclude_used=body.get("history_policy","new_for_algorithm")=="new_for_algorithm",role=str(body.get("role") or "train"))


def _public_usage_fact(fact):
    details=fact.get("history_details") or []
    return {**{k:v for k,v in fact.items() if k not in {"history_details","task_ids"}},
        "training_task_count":len({r["task_id"] for r in details if r["role"]=="train" and r["evidence"]>=2}),
        "possible_training_task_count":len({r["task_id"] for r in details if r["role"]=="train" and r["evidence"]==1}),
        "algorithm_ids":sorted({r["algorithm_id"] for r in details})}


def _pool_filters(repository, filters):
    body=dict(filters or {})
    categories=body.get('negative_category_ids') or []
    if body.get('negative_pool_only') or categories:
        from .negative_pool import NegativePool
        pool=NegativePool(repository)
        revision=pool.revision()
        body['negative_pool_image_ids']=pool.candidate_ids(category_ids=categories)
        if pool.revision()!=revision:
            raise ValueError('负样本池已更新，请重试')
        body['negative_pool_revision']=revision
    return body


def _picker_filter_sql(filters=None):
    """Shared predicates; formal annotation truth always belongs to AnnotationRepository."""
    f = dict(filters or {})
    clauses, params = [], []
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
    state = str(f.get("annotation_state") or "")
    if state:
        if state not in {"annotated", "confirmed_empty", "unannotated"}:
            raise ValueError("invalid annotation_state")
        clauses.append("COALESCE((SELECT a.annotation_state FROM annotation_gt.annotations a WHERE a.image_id=m.id),'unannotated')=?")
        params.append(state)
    if f.get("usage_excluded_image_ids"):
        clauses.append("m.id NOT IN (SELECT value FROM json_each(?))")
        params.append(json.dumps(f["usage_excluded_image_ids"]))
    if f.get("usage_image_ids") is not None:
        clauses.append("m.id IN (SELECT value FROM json_each(?))")
        params.append(json.dumps(f["usage_image_ids"]))
    if f.get("image_ids") is not None:
        # Caller-owned selection scope, never inferred from global material state.
        ids = _normalize_selection_ids(f["image_ids"])
        clauses.append("m.id IN (SELECT value FROM json_each(?))")
        params.append(json.dumps(ids))
    return clauses, params


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
) -> dict:
    """Page processed materials while label/GT predicates come from formal GT.

    The query attaches AnnotationRepository read-only truth to the material
    connection, so cursor rows and totals are computed from one SQLite read
    transaction without hydrating annotation JSON or trusting material labels.
    """
    bounded = max(1, min(MAX_SELECTION_SUMMARY_IDS, int(limit)))
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
    if selected_labels:
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
    with closing(sqlite3.connect(repository.path, timeout=30)) as database:
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA busy_timeout=30000")
        database.execute("PRAGMA temp_store=FILE")
        database.execute(
            "ATTACH DATABASE ? AS annotation_gt",
            (str(annotations.path),),
        )
        database.execute("BEGIN")
        try:
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
            total = _gt_filtered_count_snapshot(
                database, repository, annotations, base_where, base_params,
                material_revision, annotation_revision,
            )
            offset = None
            if page is not None:
                page_number = int(page)
                total_pages = max(1, math.ceil(total / bounded))
                if page_number < 1:
                    raise ValueError("page must be a positive integer")
                if page_number > total_pages:
                    raise ValueError(
                        f"page {page_number} exceeds total_pages {total_pages}"
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
    with closing(sqlite3.connect(project / "materials.sqlite3", timeout=30)) as database:
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


def _selection_summary(
    repository: MaterialRepository,
    annotations: AnnotationRepository,
    image_ids: list[str],
) -> dict:
    """Aggregate selected-material facts while formal GT stays Annotation-owned."""
    with closing(sqlite3.connect(repository.path, timeout=30)) as database:
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
    truth = annotations.training_ground_truth_summary(processed_ids)
    eligible_ids = set(str(value) for value in truth["eligible_ids"])
    eligible_count = len(eligible_ids)
    selectable_count = int(row["selectable_count"] or 0)
    label_counts = dict(truth["label_counts"])

    material_revision = repository.current_revision()
    selectable_total, eligible_total, pool_annotation_revision = (
        _cached_pool_training_totals(
            str(repository.project_path),
            int(material_revision),
            int(annotations.current_revision()),
        )
    )
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
        "label_counts": label_counts,
        "selectable_total": selectable_total,
        "eligible_total": eligible_total,
        "pending_annotation_total": max(0, selectable_total - eligible_total),
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
    if labels:
        clauses.append("EXISTS (SELECT 1 FROM annotation_gt.annotation_label_references r WHERE r.image_id=m.id AND r.annotation_state='annotated' AND r.box_count>0 AND r.label_code IN (" + ",".join("?" for _ in labels) + "))")
        params.extend(labels)
    extra, values = _picker_filter_sql(filters)
    clauses.extend(extra); params.extend(values)
    result = []
    with closing(observe_connection(sqlite3.connect(material_path, timeout=30))) as db:
        db.row_factory = sqlite3.Row
        db.execute("ATTACH DATABASE ? AS annotation_gt", (annotation_path,))
        db.execute("BEGIN")
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
                        query="", labels=(), sample_role="", page=1, limit=60, sort_order="oldest", filters=None, include_payload=True):
    if sample_role not in {"", "positive", "confirmed_negative", "pending_negative", "pending_review"}:
        raise ValueError("invalid sample_role")
    if not 1 <= int(limit) <= MAX_SELECTION_SUMMARY_IDS or int(page) < 1:
        raise ValueError("invalid role page bounds")
    if sort_order not in {"oldest", "newest"}:
        raise ValueError("invalid sort_order")
    selected = {k:v for k,v in _pool_filters(repository, filters).items() if k in {"storage_source_ids","created_from","created_to","annotation_state","usage_image_ids","usage_excluded_image_ids","image_ids","negative_pool_image_ids","negative_pool_revision"}}
    selected.update(query=str(query or "").strip(), labels=sorted(set(labels)))
    if image_ids is not None: selected["image_ids"] = sorted(set(image_ids))
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

    def task_contract(project_id, body, repository):
        from .training_label_tasks import resolve_training_label_contract
        if algorithm_provider is None:
            raise HTTPException(status_code=503, detail="训练标签适配服务不可用")
        algorithm = algorithm_provider(project_id, str(body.get("algorithm_asset_id") or ""))
        if algorithm is None:
            raise HTTPException(status_code=404, detail="训练算法不存在")
        # Role previews resolve canonical task labels only. Benchmark scope,
        # identity checks and admission remain in the explicit compatibility call.
        return resolve_training_label_contract(data_dir(), repository.project_path, dict(body), algorithm,
                                               require_positive_evidence=False)

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
            with closing(sqlite3.connect(task_path.resolve().as_uri()+"?mode=ro", uri=True, timeout=5)) as db:
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
            body, usage = _usage_filters(repository, payload)
            page_number = int(body.get("page") or 1)
            result = _gt_material_filter_page(repository, annotations, limit=size, page=page_number,
                query=str(body.get("query") or ""), labels=_normalize_labels(body.get("labels")),
                include_payload=True, sort_order=str(body.get("sort_order") or "newest"),filters=body)
            usage = _page_usage_facts(repository,body,result["items"])
            truth = annotations.get_many([r["id"] for r in result["items"]])
            return {"items":[{**_public_picker_material(project_id,r,truth.get(r["id"],{})),
                    "training_usage":_public_usage_fact(usage["by_image_id"].get(r["id"],{"state":"unknown"}))} for r in result["items"]],
                    "total":result["total"],"page":page_number,"page_size":size,"total_pages":max(1,math.ceil(result["total"]/size)),
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
            payload, usage = _usage_filters(repository, payload)
            contract = task_contract(project_id, payload, repository)
            result = _role_material_page(repository, annotations, contract,
                query=str(payload.get("query") or ""), labels=_normalize_labels(payload.get("labels")),
                sample_role=str(payload.get("sample_role") or ""), page=int(payload.get("page") or 1), limit=limit,
                sort_order=str(payload.get("sort_order") or "oldest"), filters=payload)
            usage = _page_usage_facts(repository,payload,result["items"])
            result["usage_revision"] = usage["revision"]
            truth = annotations.get_many([row["id"] for row in result["items"]])
            if (repository.current_revision(), annotations.current_revision()) != (result["repository_revision"], result["annotation_revision"]):
                raise ValueError("素材或标注已更新，请重试")
            result["items"] = [{**_public_picker_material(project_id, row, truth.get(row["id"], {})),
                                "training_usage": _public_usage_fact(usage["by_image_id"].get(row["id"], {"state":"unknown"})),
                                "sample_role": row["sample_role"],
                                "annotation_version": int(truth.get(row["id"], {}).get("version") or 0),
                                "source_content_sha256": str(row.get("content_sha256") or "")}
                               for row in result["items"]]
            return result
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    def negative_plan(project_id, payload):
        from .training_label_tasks import (task_negative_confirmable, task_negative_identity,
            task_negative_context, training_material_role, _ORIGINAL_SELECTED_PROJECT_IMAGES)
        repository = materials(project_id)
        contract = task_contract(project_id, payload, repository)
        ids = _normalize_selection_ids([*(payload.get("train_image_ids") or []),
            *(payload.get("val_image_ids") or []), *(payload.get("selected_image_ids") or []), *(payload.get("image_ids") or []),
            *(payload.get("test_image_ids") or [])])
        rows = _ORIGINAL_SELECTED_PROJECT_IMAGES(repository, repository.project_path, ids)
        counts = dict(positive=0, confirmed_negative=0, pending_negative=0, pending_review=0)
        pending = []
        for row in rows:
            role = training_material_role(row, contract)["role"]
            if role == "pending_review" and task_negative_confirmable(row, contract):
                role = "pending_negative"
                pending.append(task_negative_identity(row, contract))
            counts[role] += 1
        digest = hashlib.sha256(json.dumps({"context":task_negative_context(contract),
            "selected":sorted(ids), "identities":[task_negative_identity(row, contract) for row in rows], "pending":pending}, sort_keys=True).encode()).hexdigest()
        return repository, contract, counts, pending, digest

    @router.post("/negative-preview")
    def negative_preview(project_id: str, payload: dict):
        try:
            _, contract, counts, pending, digest = negative_plan(project_id, payload)
            return {"counts":counts, "pending_count":len(pending), "pending_preview":[{**e,"image_url":f"/api/v62/projects/{project_id}/training-materials/{e['image_id']}/thumbnail"} for e in pending[:20]],
                    "proof_digest":digest, "effective_label_codes":contract["effective_label_codes"]}
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
                repository, contract, counts, pending, digest = negative_plan(project_id, payload)
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
    ):
        numbered = page is not None or page_size is not None
        requested_page = int(page or 1) if numbered else None
        requested_size = int(page_size if page_size is not None else limit)
        if not 1 <= requested_size <= MAX_PAGE_SIZE:
            raise HTTPException(status_code=422, detail=f"limit must be between 1 and {MAX_PAGE_SIZE}")
        repository = materials(project_id)
        annotation_repository = annotation_repository_for_path(
            str(repository.project_path)
        )
        selected_labels = tuple(label or ())
        shared_filters = {"storage_source_ids":storage_source_id or [], "annotation_state":annotation_state, "created_from":created_from, "created_to":created_to, "negative_pool_only":negative_pool_only,"negative_category_ids":negative_category_id or []}
        shared_filters = {k:v for k,v in shared_filters.items() if v}
        try:
            shared_filters, usage = _usage_filters(repository, {**shared_filters, "usage_state":usage_state,"algorithm_asset_id":algorithm_asset_id,"history_policy":history_policy,"role":role,"history_scope":history_scope})
            if selected_labels or shared_filters:
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
                )
                rows = [dict(row) for row in page["items"]]
                next_cursor = page["next_cursor"]
                total = int(page["total"])
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
                repository_revision = repository.current_revision()
                annotation_revision = annotation_repository.current_revision()
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        usage = _page_usage_facts(repository,shared_filters,rows)
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
                ), "training_usage":_public_usage_fact(usage["by_image_id"].get(str(row.get("id")), {"state":"unknown"}))}
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
            total_pages = max(1, math.ceil(total / requested_size))
            response.update({
                "page": requested_page,
                "page_size": requested_size,
                "total_pages": total_pages,
                "has_previous": requested_page > 1,
                "has_next": requested_page < total_pages,
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

    @router.post("/bulk-selection")
    def resolve_training_material_bulk_selection(project_id: str, payload: dict):
        repository = materials(project_id)
        body = payload if isinstance(payload, dict) else {}
        try:
            if body.get("all_available"):
                body = {k:v for k,v in body.items() if k in {"algorithm_asset_id","role","all_available","train_labels","base_version_id","model","framework","image_ids","history_policy","negative_pool_only","negative_category_ids"}}
            body, usage = _usage_filters(repository, body)
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
            if body.get("sample_role"):
                contract = task_contract(project_id, body, repository)
                role_page = _role_material_page(repository, annotations, contract, query=query, labels=labels,
                    sample_role=str(body["sample_role"]), limit=MAX_SELECTION_SUMMARY_IDS, filters=body, include_payload=False)
                if role_page["total"] > MAX_SELECTION_SUMMARY_IDS:
                    raise ValueError("filtered selection exceeds maximum")
                return {"items": [row["id"] for row in role_page["items"]], "total": role_page["total"],
                        "repository_revision": repository.current_revision(), "selection_mode": "filtered"}
            ids, total = _bulk_filtered_ids(
                repository,
                annotations,
                query=query,
                labels=labels,
                require_ground_truth=role == "test",
                filters=body,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "items": ids,
            "total": total,
            "repository_revision": repository.current_revision(),
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
        summary = _selection_summary(repository, annotations, image_ids)
        if payload.get("algorithm_asset_id") and (payload.get("train_labels") or payload.get("base_version_id")):
            try:
                contract = task_contract(project_id, payload, repository)
                roles = _role_material_page(repository, annotations, contract, image_ids=image_ids, limit=1)
                _, _, counts, pending, _ = negative_plan(project_id, dict(payload, image_ids=image_ids))
                summary.update(sample_role_counts=counts, effective_label_codes=roles["effective_label_codes"])
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
        return {**summary, "repository_revision": repository.current_revision()}

    @router.post("/compatibility")
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
            with FileLock(str(target) + ".lock", timeout=30):
                if not target.is_file():
                    try:
                        manager = StorageManager(data_dir=data_dir(), project_id=project_id, materials=repository)
                        materialized = manager.materialize(dict(row))
                        _write_thumbnail(Path(materialized.path), target, thumbnail_size)
                    except (OSError, ValueError, UnidentifiedImageError, StorageError):
                        encoded = quote(str(image_id), safe="")
                        return RedirectResponse(
                            f"/api/v61/projects/{quote(str(project_id), safe='')}/materials/{encoded}/content",
                            status_code=307,
                        )
        return FileResponse(
            target,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "private, max-age=604800, immutable",
                "ETag": f'"{target.stem}"',
            },
        )

    return router
