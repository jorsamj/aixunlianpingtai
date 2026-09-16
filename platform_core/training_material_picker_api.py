"""Server-owned material paging and summaries for the training picker.

The training UI must never hydrate the whole project material pool in the browser.
Metadata comes from MaterialRepository cursor paging, selected-material facts are
aggregated inside SQLite, and thumbnails are created lazily on demand.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from filelock import FileLock
from PIL import Image, ImageOps, UnidentifiedImageError

from .material_repository import MaterialRepository
from .storage.errors import StorageError
from .storage.manager import StorageManager

DEFAULT_PAGE_SIZE = 120
MAX_PAGE_SIZE = 240
MAX_SELECTION_SUMMARY_IDS = 50000
# Cards render at 96 CSS px. 192 px keeps 2x-density displays sharp without
# decoding and caching unnecessarily large 256 px images for the picker.
DEFAULT_THUMBNAIL_SIZE = 192
ALLOWED_THUMBNAIL_SIZES = {160, 192, 224, 256, 320, 384}


def _safe_project_path(data_dir: Path, project_id: str) -> Path:
    projects = (data_dir / "projects").resolve()
    project = (projects / str(project_id)).resolve()
    if project.parent != projects:
        raise ValueError("project id must be one safe path component")
    return project


def _public_picker_material(project_id: str, row: dict) -> dict:
    image_id = str(row.get("id") or "")
    encoded = quote(image_id, safe="")
    return {
        "id": image_id,
        "filename": str(row.get("filename") or image_id),
        "labels": [str(value) for value in (row.get("labels") or [])],
        "annotated": bool(row.get("annotated")),
        "box_count": max(0, int(row.get("box_count") or 0)),
        "processing_status": str(row.get("processing_status") or ""),
        "annotation_state": str(row.get("annotation_state") or row.get("annotation_status") or ""),
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


def _selection_summary(repository: MaterialRepository, image_ids: list[str]) -> dict:
    """Aggregate selected-material truth without hydrating material payload JSON."""
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
            "COALESCE(SUM(CASE WHEN m.annotated <> 0 THEN 1 ELSE 0 END), 0) AS eligible_count, "
            "COALESCE(SUM(CASE WHEN m.annotated <> 0 THEN m.box_count ELSE 0 END), 0) AS box_count, "
            "COALESCE(SUM(CASE WHEN m.annotated <> 0 THEN m.size_bytes ELSE 0 END), 0) AS size_bytes "
            "FROM requested_training_material_ids r "
            "LEFT JOIN materials m ON m.id = r.id"
        ).fetchone()
        label_rows = database.execute(
            "SELECT ml.label_code AS label_code, COUNT(DISTINCT ml.material_id) AS material_count "
            "FROM requested_training_material_ids r "
            "JOIN materials m ON m.id = r.id AND m.annotated <> 0 "
            "JOIN material_labels ml ON ml.material_id = m.id "
            "GROUP BY ml.label_code ORDER BY ml.label_code"
        ).fetchall()
        eligible_total = int(database.execute(
            "SELECT COUNT(*) FROM materials WHERE annotated <> 0"
        ).fetchone()[0])
    label_counts = {str(item["label_code"]): int(item["material_count"]) for item in label_rows}
    return {
        "requested_count": len(image_ids),
        "matched_count": int(row["matched_count"] or 0),
        "eligible_count": int(row["eligible_count"] or 0),
        "box_count": int(row["box_count"] or 0),
        "size_bytes": int(row["size_bytes"] or 0),
        "label_codes": list(label_counts),
        "label_counts": label_counts,
        "eligible_total": eligible_total,
    }


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


def training_material_picker_router(get_project, data_dir_provider):
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

    def materials(project_id: str) -> MaterialRepository:
        get_project(project_id)
        try:
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
        try:
            page = repository.list_page(
                cursor=cursor,
                limit=int(limit),
                query=str(query or "").strip(),
                labels=tuple(label or ()),
                annotated=True,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "items": [_public_picker_material(project_id, dict(row)) for row in page.items],
            "next_cursor": page.next_cursor,
            "total": page.total,
            "limit": int(limit),
            "repository_revision": repository.current_revision(),
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
        try:
            page = repository.iter_filtered_ids(
                {
                    "query": str(query or "").strip(),
                    "labels": tuple(label or ()),
                    "annotated": True,
                },
                cursor=cursor,
                limit=int(limit),
                include_total=True,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "items": page.items,
            "next_cursor": page.next_cursor,
            "total": page.total,
            "repository_revision": repository.current_revision(),
        }

    @router.post("/selection-summary")
    def training_material_selection_summary(project_id: str, payload: dict):
        try:
            image_ids = _normalize_selection_ids(payload.get("image_ids") if isinstance(payload, dict) else None)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        repository = materials(project_id)
        summary = _selection_summary(repository, image_ids)
        return {**summary, "repository_revision": repository.current_revision()}

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
