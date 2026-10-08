"""Server-owned material paging and summaries for the training picker.

The training UI must never hydrate the whole project material pool in the browser.
Metadata comes from MaterialRepository cursor paging, selected-material facts are
aggregated inside SQLite, and thumbnails are created lazily on demand.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from filelock import FileLock
from PIL import Image, ImageOps, UnidentifiedImageError

from .annotation_repository import AnnotationRepository
from .material_repository import (
    MaterialRepository,
    decode_material_cursor,
    encode_material_cursor,
)
from .storage.errors import StorageError
from .storage.manager import StorageManager
from .training_compatibility import compatibility_page, evaluate_training_compatibility

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


def _gt_material_filter_page(
    repository: MaterialRepository,
    annotations: AnnotationRepository,
    *,
    cursor: str | None = None,
    limit: int,
    query: str = "",
    labels: tuple[str, ...] = (),
    require_ground_truth: bool = False,
    include_payload: bool = False,
) -> dict:
    """Page processed materials while label/GT predicates come from formal GT.

    The query attaches AnnotationRepository read-only truth to the material
    connection, so cursor rows and totals are computed from one SQLite read
    transaction without hydrating annotation JSON or trusting material labels.
    """
    bounded = max(1, min(MAX_SELECTION_SUMMARY_IDS, int(limit)))
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
            total = int(database.execute(
                "SELECT COUNT(*) FROM materials m" + base_where,
                base_params,
            ).fetchone()[0])
            clauses = list(base_clauses)
            params = list(base_params)
            if cursor:
                created_at, image_id = decode_material_cursor(cursor)
                clauses.append(
                    "(m.created_at > ? OR (m.created_at = ? AND m.id > ?))"
                )
                params.extend((created_at, created_at, image_id))
            where = " WHERE " + " AND ".join(clauses)
            columns = (
                "m.id, m.created_at, m.payload_json"
                if include_payload else
                "m.id, m.created_at"
            )
            rows = database.execute(
                f"SELECT {columns} FROM materials m"
                + where
                + " ORDER BY m.created_at, m.id LIMIT ?",
                [*params, bounded + 1],
            ).fetchall()
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
) -> tuple[list[str], int]:
    """Resolve a large filtered selection server-side with one HTTP request."""
    if labels or require_ground_truth:
        page = _gt_material_filter_page(
            repository,
            annotations,
            limit=MAX_SELECTION_SUMMARY_IDS,
            query=query,
            labels=labels,
            require_ground_truth=require_ground_truth,
            include_payload=False,
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

    @router.get("")
    def list_training_materials(
        project_id: str,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        query: str = "",
        label: list[str] | None = Query(default=None),
    ):
        if not 1 <= int(limit) <= MAX_PAGE_SIZE:
            raise HTTPException(status_code=422, detail=f"limit must be between 1 and {MAX_PAGE_SIZE}")
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
                    include_payload=True,
                )
                rows = [dict(row) for row in page["items"]]
                next_cursor = page["next_cursor"]
                total = int(page["total"])
                repository_revision = int(page["material_revision"])
                annotation_revision = int(page["annotation_revision"])
            else:
                material_page = repository.list_page(
                    cursor=cursor,
                    limit=int(limit),
                    query=str(query or "").strip(),
                    processing_status="processed",
                )
                rows = [dict(row) for row in material_page.items]
                next_cursor = material_page.next_cursor
                total = material_page.total
                repository_revision = repository.current_revision()
                annotation_revision = annotation_repository.current_revision()
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        annotations = annotation_repository.get_many(
            [str(row.get("id") or "") for row in rows]
        )
        return {
            "items": [
                _public_picker_material(
                    project_id,
                    row,
                    annotations.get(
                        str(row.get("id") or ""),
                        {"annotation_state": "unannotated", "boxes": []},
                    ),
                )
                for row in rows
            ],
            "next_cursor": next_cursor,
            "total": total,
            "limit": int(limit),
            "repository_revision": repository_revision,
            "annotation_revision": annotation_revision,
        }

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
        }

    @router.post("/bulk-selection")
    def resolve_training_material_bulk_selection(project_id: str, payload: dict):
        repository = materials(project_id)
        body = payload if isinstance(payload, dict) else {}
        try:
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
            ids, total = _bulk_filtered_ids(
                repository,
                annotations,
                query=query,
                labels=labels,
                require_ground_truth=role == "test",
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
            result = evaluate_training_compatibility(
                data_dir(), repository.project_path, request, algorithm,
            )
            page = compatibility_page(
                result,
                query=str(body.get("query") or ""),
                issue_type=str(body.get("issue_type") or ""),
                cursor=str(body.get("cursor") or ""),
                limit=int(body.get("limit") or 50),
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
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
