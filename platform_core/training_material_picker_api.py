"""Server-owned material paging for the training picker.

The picker must never hydrate the whole project material pool in the browser.
Metadata comes from MaterialRepository cursor paging, while thumbnails are
created lazily on demand and cached by immutable content identity where
possible.  The full-resolution material endpoint remains the fallback for
providers that cannot be materialized by this lightweight route.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from urllib.parse import quote

from filelock import FileLock
from PIL import Image, ImageOps, UnidentifiedImageError

from .material_repository import MaterialRepository
from .storage.errors import StorageError
from .storage.manager import StorageManager

DEFAULT_PAGE_SIZE = 120
MAX_PAGE_SIZE = 240
DEFAULT_THUMBNAIL_SIZE = 256
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

    def materials(project_id: str) -> MaterialRepository:
        get_project(project_id)
        try:
            return MaterialRepository(_safe_project_path(data_dir(), project_id))
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
                        # Provider/image failures may be handled by the existing authoritative content route.
                        # Programming errors are intentionally not swallowed here.
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
