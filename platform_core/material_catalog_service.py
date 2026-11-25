"""Material browsing, dataset directory and read-only label/quality projections.
Persistence, GT, storage and annotation-index lifecycle stay with their existing
injected owners. This module never imports app or opens a new repository.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Literal
from .material_catalog_contracts import DatasetReq

import uuid
from fastapi import HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from platform_core.labels import active_label_options
from platform_core.storage import StorageError
from platform_core.snapshots import is_training_ground_truth

@dataclass(frozen=True)
class MaterialCatalogDependencies:
    _annotation_label_catalog: Callable[..., Any]
    _authorize_business_file_project: Callable[..., Any]
    _material_legacy_zip_batch_ids: Callable[..., Any]
    _raise_file_storage_error: Callable[..., Any]
    _v52_schedule_annotation_index: Callable[..., Any]
    datasets_file: Callable[..., Any]
    ensure_default_datasets: Callable[..., Any]
    fast_json_response: Callable[..., Any]
    get_project: Callable[..., Any]
    load_images: Callable[..., Any]
    material_store: Callable[..., Any]
    normalize_box_for_project: Callable[..., Any]
    now_iso: Callable[..., Any]
    project_label_items: Callable[..., Any]
    public_material: Callable[..., Any]
    read_annotation: Callable[..., Any]
    read_annotations_many: Callable[..., Any]
    storage_manager: Callable[..., Any]
    write_json: Callable[..., Any]


class MaterialCatalogService:
    def __init__(self, dependencies: MaterialCatalogDependencies):
        self.dependencies = dependencies

    def list_materials_v61(self,
        project_id: str, cursor: Optional[str] = None, limit: int = 100,
        page: Optional[int] = None, page_size: Optional[int] = None,
        query: str = "", storage_source_id: Optional[List[str]] = Query(default=None),
        processing_status: Optional[str] = None,
        label: Optional[List[str]] = Query(default=None), annotated: Optional[bool] = None,
        annotation_state: Optional[Literal["unannotated", "annotated", "confirmed_empty", "partial", "needs_review"]] = None,
        source_batch_id: Optional[str] = None, quality_status: Optional[Literal["pending_decision", "processed", "issue"]] = None,
        created_from: Optional[str] = None, created_to: Optional[str] = None,
        reader_view: bool = False,
    ):
        self.dependencies.get_project(project_id)
        numbered = page is not None or page_size is not None
        requested_page = int(1 if page is None else page) if numbered else None
        requested_size = int(page_size if page_size is not None else limit)
        if reader_view and requested_size>120:raise HTTPException(422,detail='素材浏览每页最多120条')
        if numbered and (requested_page is None or requested_page < 1):
            raise HTTPException(status_code=422, detail="page must be at least 1")
        if requested_size < 1 or requested_size > 1000:
            raise HTTPException(
                status_code=422,
                detail="page_size must be between 1 and 1000",
            )
        try:
            material_page = self.dependencies.material_store(project_id).list_page(
                cursor=cursor, page=requested_page, limit=requested_size, query=query,
                storage_source_ids=storage_source_id, processing_status=processing_status,
                labels=label, annotated=annotated, annotation_state=annotation_state,
                source_batch_id=source_batch_id, source_batch_image_ids=self.dependencies._material_legacy_zip_batch_ids(project_id,source_batch_id), quality_status=quality_status, created_from=created_from, created_to=created_to,
                partial_labels=[row["code"] for row in self.dependencies._annotation_label_catalog(self.dependencies.get_project(project_id))] if annotation_state=="partial" else (),
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if reader_view:
            from platform_core.material_reader_views import material_display
            items = [material_display(project_id, item) for item in material_page.items]
        else:
            items = [self.dependencies.public_material(project_id, item) for item in material_page.items]
        response = {
            "items": items,
            "next_cursor": material_page.next_cursor,
            "total": material_page.total,
        }
        if numbered:
            total_pages = max(
                1,
                (int(material_page.total) + requested_size - 1) // requested_size,
            )
            response.update({
                "page": requested_page,
                "page_size": requested_size,
                "total_pages": total_pages,
                "has_previous": requested_page > 1,
                "has_next": requested_page < total_pages,
            })
        if reader_view:
            response.update(ok=True,project_id=project_id)
        return response

    def list_material_ids_v61(self,
        project_id: str, cursor: Optional[str] = None, limit: int = 1000,
        query: str = "", storage_source_id: Optional[List[str]] = Query(default=None),
        processing_status: Optional[str] = None,
        label: Optional[List[str]] = Query(default=None), annotated: Optional[bool] = None,
        annotation_state: Optional[Literal["unannotated", "annotated", "confirmed_empty", "partial", "needs_review"]] = None,
        source_batch_id: Optional[str] = None, quality_status: Optional[Literal["pending_decision", "processed", "issue"]] = None,
        created_from: Optional[str] = None, created_to: Optional[str] = None,
        narrow: bool = False, expected_revision: Optional[int] = None,
    ):
        self.dependencies.get_project(project_id)
        repository = self.dependencies.material_store(project_id)
        revision = repository.current_revision()
        if expected_revision is not None and revision != expected_revision:
            raise HTTPException(status_code=409, detail="素材库已更新，请重新解析当前筛选结果")
        filters = dict(query=query, storage_source_ids=storage_source_id or (),
                       source_batch_id=source_batch_id, source_batch_image_ids=self.dependencies._material_legacy_zip_batch_ids(project_id,source_batch_id), quality_status=quality_status, created_from=created_from, created_to=created_to,
                       processing_status=processing_status, labels=label or (), annotated=annotated, annotation_state=annotation_state, partial_labels=[row["code"] for row in self.dependencies._annotation_label_catalog(self.dependencies.get_project(project_id))] if annotation_state=="partial" else ())
        from platform_core.material_selection import MaterialFilters
        try:
            filters=MaterialFilters.from_mapping(filters).as_dict() | {"source_batch_image_ids":filters.get("source_batch_image_ids",())}
        except (ValueError, TypeError) as error:
            raise HTTPException(400,detail=str(error)) from error
        if narrow:
            # Bulk selection needs only IDs. Reuse the canonical material predicate,
            # avoiding list_page() JSON/detail hydration for every selected image.
            page = repository.iter_filtered_ids(filters, cursor=cursor, limit=limit,
                                                include_total=cursor is None)
        else:
            page = repository.list_ids(cursor=cursor, limit=limit, **filters)
        if repository.current_revision() != revision:
            raise HTTPException(status_code=409, detail="素材库在解析期间发生变化，请重试")
        return {"items": page.items, "next_cursor": page.next_cursor,
                "total": page.total, "repository_revision": revision}

    def material_status_counts_v61(self,
        project_id: str, storage_source_id: Optional[List[str]] = Query(default=None),
    ):
        self.dependencies.get_project(project_id)
        # One database snapshot, one aggregation on cache miss; unlike two
        # page-size=1 requests this never hydrates image JSON or a page of cards.
        return self.dependencies.material_store(project_id).processing_status_counts(storage_source_id)

    def material_content_v61(self, project_id: str, image_id: str):
        self.dependencies._authorize_business_file_project(project_id)
        try:
            manager = self.dependencies.storage_manager(project_id)
            row = manager.material(image_id)
            resolved = manager.materialize(row)
            from platform_core.storage.http import StoredSourceFileResponse
            return StoredSourceFileResponse(resolved.path, manager=manager, material=row,
                headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
        except StorageError as error:
            self.dependencies._raise_file_storage_error(error, status_code=404 if error.code in {"MATERIAL_NOT_FOUND", "STORAGE_OBJECT_NOT_FOUND"} else 503)
        except (OSError, ValueError):
            raise HTTPException(404, detail='文件不存在或无权访问') from None

    def material_thumbnail_v61(self, project_id: str, image_id: str, request: Request, edge: int = Query(384, ge=16, le=1024)):
        """Read-derived cache only. Keep the verified bytes locked through delivery."""
        from starlette.background import BackgroundTask
        self.dependencies._authorize_business_file_project(project_id)
        try:
            manager = self.dependencies.storage_manager(project_id)
            # Validation happens exactly once under the payload lock inside cache.
            # Passing that same lock to the response closes the former release/
            # reacquire race without hashing the payload for a second time.
            path, lock = manager.thumbnail(image_id, max_edge=edge, hold_verified_lock=True)
            etag = f'"{path.stem}"'
            cache_headers = {
                'Cache-Control':'private, no-cache, must-revalidate',
                'ETag':etag,
                'Vary':'Cookie, Authorization',
                'X-Content-Type-Options':'nosniff',
            }
            # Authorization occurs above even for 304; the browser must revalidate
            # each reuse and can never obtain a shared/public thumbnail cache hit.
            if etag in (part.strip() for part in request.headers.get('if-none-match','').split(',')):
                lock.release()
                return Response(status_code=304, headers=cache_headers)
            try:
                stream = path.open('rb')
                size = path.stat().st_size
            except BaseException:
                lock.release()
                raise
            def close():
                if not stream.closed:
                    stream.close()
                    lock.release()
            def chunks():
                try:
                    while chunk := stream.read(64 * 1024):
                        yield chunk
                finally:
                    close()
            return StreamingResponse(chunks(), media_type='image/jpeg',
                headers={**cache_headers,'Content-Length':str(size)},
                background=BackgroundTask(close))
        except StorageError as error:
            self.dependencies._raise_file_storage_error(error, status_code=503)
        except (OSError, ValueError) as error:
            raise HTTPException(503, detail='缩略图暂不可用，可重试；原图和正式 GT 未修改') from error

    def list_datasets(self, project_id: str):
        self.dependencies.get_project(project_id)
        datasets = self.dependencies.ensure_default_datasets(project_id)
        images = self.dependencies.load_images(project_id)
        image_ids = [
            str(image.get("id") or "")
            for image in images
            if str(image.get("id") or "")
        ]
        annotations: Dict[str, Dict[str, Any]] = {}
        for offset in range(0, len(image_ids), 500):
            annotations.update(
                self.dependencies.read_annotations_many(project_id, image_ids[offset:offset + 500])
            )
        stats: Dict[str, Dict[str, int]] = {}
        for image in images:
            dataset_id = str(image.get("dataset_id") or "default")
            row = stats.setdefault(
                dataset_id, {"images": 0, "annotated_images": 0, "boxes": 0}
            )
            row["images"] += 1
            annotation = annotations.get(str(image.get("id") or "")) or {}
            count = len(annotation.get("boxes") or [])
            row["boxes"] += count
            if count:
                row["annotated_images"] += 1
        return {
            "ok": True,
            "items": [
                {
                    **dataset,
                    **stats.get(
                        str(dataset.get("id") or "default"),
                        {"images": 0, "annotated_images": 0, "boxes": 0},
                    ),
                }
                for dataset in datasets
            ],
        }

    def create_dataset(self, project_id: str, payload: DatasetReq):
        self.dependencies.get_project(project_id)
        if not payload.name.strip():
            raise HTTPException(status_code=400, detail="数据集名称不能为空")
        ds = self.dependencies.ensure_default_datasets(project_id)
        item = {"id": uuid.uuid4().hex[:12], "name": payload.name.strip(), "description": payload.description or "", "created_at": self.dependencies.now_iso(), "updated_at": self.dependencies.now_iso()}
        ds.append(item)
        self.dependencies.write_json(self.dependencies.datasets_file(project_id), ds)
        return item

    def update_dataset(self, project_id: str, dataset_id: str, payload: DatasetReq):
        self.dependencies.get_project(project_id)
        ds = self.dependencies.ensure_default_datasets(project_id)
        for item in ds:
            if item.get("id") == dataset_id:
                item["name"] = payload.name.strip() or item.get("name", "数据集")
                item["description"] = payload.description or ""
                item["updated_at"] = self.dependencies.now_iso()
                self.dependencies.write_json(self.dependencies.datasets_file(project_id), ds)
                return item
        raise HTTPException(status_code=404, detail="数据集不存在")

    def list_images(self, project_id: str, dataset_id: Optional[str] = None):
        self.dependencies.get_project(project_id)
        all_images = self.dependencies.load_images(project_id)
        manager = self.dependencies.storage_manager(project_id)
        size_patches = {}
        # v42.12：旧数据的标注摘要迁移改为后台索引，首屏不再逐张读取 annotation JSON。
        # 已有摘要直接返回；缺摘要的图片先以轻量元数据返回，后台完成后前端自动刷新一次。
        if any(not x.get("annotation_summary_at") for x in all_images):
            self.dependencies._v52_schedule_annotation_index(project_id, all_images)
        for img in all_images:
            img.update(self.dependencies.public_material(project_id, img))
            img.setdefault("box_count", 0)
            img.setdefault("annotated", bool(img.get("box_count")))
            img.setdefault("labels", [])
            img.setdefault("annotation_preview", [])
            if not img.get("size_bytes"):
                try:
                    normalized = manager.material(img)
                    img["size_bytes"] = int(
                        manager.provider_for(str(normalized["storage_source_id"]))
                        .stat(str(normalized["object_key"]))
                        .size_bytes
                    )
                except Exception:
                    img["size_bytes"] = 0
                if img.get("id") is not None:
                    size_patches[str(img.get("id"))] = {"size_bytes": img["size_bytes"]}
            img["split"] = (img.get("split") or "unassigned").lower()
            img["processing_status"] = "processed" if int(img.get("box_count") or 0)>0 else (img.get("processing_status") or ("processed" if img.get("cleaned_at") else "unprocessed"))
            img["annotation_index_pending"] = not bool(img.get("annotation_summary_at"))
        if size_patches:
            self.dependencies.material_store(project_id).patch(size_patches)
        images = all_images
        if dataset_id:
            images = [img for img in images if img.get("dataset_id", "default") == dataset_id]
        return self.dependencies.fast_json_response(images)

    def dataset_quality_report(self, project_id: str, dataset_id: Optional[str] = None, include_empty: bool = False) -> Dict[str, Any]:
        project = self.dependencies.get_project(project_id)
        images = self.dependencies.load_images(project_id)
        if dataset_id:
            images = [img for img in images if img.get("dataset_id", "default") == dataset_id]
        result = {
            "image_count": len(images),
            "annotated_images": 0,
            "box_count": 0,
            "splits": {"unassigned": {"images": 0, "boxes": 0}, "train": {"images": 0, "boxes": 0}, "val": {"images": 0, "boxes": 0}, "test": {"images": 0, "boxes": 0}},
            "label_usage": {label: 0 for label in project.get("labels", [])},
            "invalid_boxes": 0,
            "empty_images": 0,
            "unannotated_images": 0,
            "can_train": False,
            "warnings": [],
        }
        for img in images:
            split = (img.get("split") or "unassigned").lower()
            if split not in result["splits"]:
                split = "unassigned"
            ann = self.dependencies.read_annotation(project_id, img["id"])
            clean = []
            for b in ann.get("boxes", []):
                nb = self.dependencies.normalize_box_for_project(project_id, img, b, create_label=False)
                if nb:
                    clean.append(nb)
                else:
                    result["invalid_boxes"] += 1
            if is_training_ground_truth(ann.get("annotation_state"), clean):
                result["splits"][split]["images"] += 1
            if clean and ann.get("annotation_state") == "annotated":
                result["annotated_images"] += 1
            elif ann.get("annotation_state") == "confirmed_empty":
                result["empty_images"] += 1
            else:
                result["unannotated_images"] += 1
            for b in clean:
                result["box_count"] += 1
                result["splits"][split]["boxes"] += 1
                label = project.get("labels", [])[int(b["class_id"])] if int(b["class_id"]) < len(project.get("labels", [])) else str(b["class_id"])
                result["label_usage"][label] = result["label_usage"].get(label, 0) + 1
        if result["image_count"] == 0:
            result["warnings"].append("当前数据集没有图片")
        if result["box_count"] == 0:
            result["warnings"].append("当前数据集没有有效标注框，无法训练出目标检测模型")
        if result["splits"]["train"]["boxes"] == 0:
            result["warnings"].append("训练集没有有效标注框")
        if result["splits"]["val"]["boxes"] == 0:
            result["warnings"].append("试验集没有有效标注框，训练过程中无法进行独立验证")
        if result["splits"]["test"]["boxes"] == 0:
            result["warnings"].append("评测集没有有效标注框，训练完成后无法进行独立最终评测")
        unused = [k for k, v in result["label_usage"].items() if v == 0]
        if unused:
            result["warnings"].append("以下标签没有样本：" + "、".join(unused))
        result["can_train"] = result["splits"]["train"]["images"] > 0
        return result

    def v12_list_labels(self, project_id: str):
        project = self.dependencies.get_project(project_id)
        governance = self.dependencies.project_label_items(project)
        return {
            "ok": True,
            "items": active_label_options(governance),
            "governance": governance,
        }

    def v17_dataset_quality(self, project_id: str, dataset_id: str, include_empty: bool = False):
        return {"ok": True, "quality": self.dataset_quality_report(project_id, dataset_id, include_empty)}

    def v12_dataset_summary(self, project_id: str, dataset_id: str):
        self.dependencies.get_project(project_id)
        images = [x for x in self.dependencies.load_images(project_id) if x.get("dataset_id", "default") == dataset_id]
        counts = {"train": 0, "val": 0, "test": 0, "unmarked": 0, "images": len(images), "boxes": 0, "annotated": 0}
        for img in images:
            split = (img.get("split") or "train").lower()
            if split not in {"train", "val", "test"}: split = "train"
            counts[split] += 1
            ann = self.dependencies.read_annotation(project_id, img["id"])
            boxes = len(ann.get("boxes", []))
            counts["boxes"] += boxes
            if boxes: counts["annotated"] += 1
            else: counts["unmarked"] += 1
        return {"ok": True, "summary": counts}
