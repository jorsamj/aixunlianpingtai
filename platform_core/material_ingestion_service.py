"""Domain orchestration over the existing persistence, worker and receipt owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Mapping, Tuple
from fastapi import Query, Request, HTTPException
from .material_ingestion_contracts import V19ImportStartReq, V19MultipartUploadReq, V36SourceImportScanReq, V36SourceImportStartReq, V55UploadDecisionsReq

import json
import hashlib
import os
import shutil
import time
import uuid
import zipfile
from urllib.parse import quote
from io import BytesIO
from pathlib import Path
from fastapi import File, Form, UploadFile
from fastapi.responses import JSONResponse, Response
from filelock import FileLock
from platform_core.annotations import atomic_write_json
from platform_core.storage.import_confirmation import IMPORT_LABEL_CREATION_BLOCKED_DETAIL, resolve_external_label_mapping
from platform_core.errors import PlatformError
from platform_core.labels import active_label_options
from platform_core.materials import mark_ready
from platform_core.storage import zip_folders
from platform_core.upload_batches import UploadRequestBusy, apply_decisions
from platform_core.cleaning_management_contracts import V47CleanReq

@dataclass(frozen=True)
class MaterialIngestionDependencies:
    V19_ZIP_PHASE_LABELS: Callable[..., Any]
    V19_ZIP_PHASE_WINDOWS: Callable[..., Any]
    V36_ANNOTATED_IMPORT_BLOCKED_DETAIL: Callable[..., Any]
    _authorize_business_file_project: Callable[..., Any]
    _plain_upload_images_claimed: Callable[..., Any]
    _v19_cleanup_uncommitted_job: Callable[..., Any]
    _v19_fifo_import_jobs: Callable[..., Any]
    _v19_fifo_queue_position: Callable[..., Any]
    _v19_finish_cancel: Callable[..., Any]
    _v19_job_record_token: Callable[..., Any]
    _v19_multipart_repository: Callable[..., Any]
    _v19_prepare_scan: Callable[..., Any]
    _v19_recover_multipart_finalize: Callable[..., Any]
    _v19_schedule_multipart_finalize: Callable[..., Any]
    _v19_stop_fence: Callable[..., Any]
    _v19_store_folder_scan: Callable[..., Any]
    _v19_write_job_locked: Callable[..., Any]
    _v33_get_task: Callable[..., Any]
    _v36_detect_source_annotation_formats: Callable[..., Any]
    _v36_is_url: Callable[..., Any]
    _v36_load_source_jobs: Callable[..., Any]
    _v36_normalize_source: Callable[..., Any]
    _v36_run_source_import: Callable[..., Any]
    _v36_scan_local_root: Callable[..., Any]
    _v36_scan_url: Callable[..., Any]
    _v36_write_source_job: Callable[..., Any]
    _v47_remove_prepared_clean_task_record: Callable[..., Any]
    _v47_reset_failed_clean_task_record: Callable[..., Any]
    _v47_restore_clean_task_record: Callable[..., Any]
    _v55_read_upload_batch: Callable[..., Any]
    _v62_prepare_clean_compat: Callable[..., Any]
    _v62_publish_clean_compat: Callable[..., Any]
    get_project: Callable[..., Any]
    list_algorithms_internal: Callable[..., Any]
    material_store: Callable[..., Any]
    now_iso: Callable[..., Any]
    project_label_items: Callable[..., Any]
    read_annotations_many: Callable[..., Any]
    read_json: Callable[..., Any]
    remember_project_label_aliases: Callable[..., Any]
    safe_filename: Callable[..., Any]
    upload_batch_store: Callable[..., Any]
    v19_import_jobs_dir: Callable[..., Any]
    v19_import_worker: Callable[..., Any]
    v19_job_dir: Callable[..., Any]
    v19_job_file: Callable[..., Any]
    v19_normalize_zip_path: Callable[..., Any]
    v19_read_class_samples: Callable[..., Any]
    v19_read_import_report: Callable[..., Any]
    v19_read_job: Callable[..., Any]
    v19_read_scan_images: Callable[..., Any]
    v19_scan_zip: Callable[..., Any]
    v19_update_job: Callable[..., Any]
    v19_write_class_samples: Callable[..., Any]
    v19_write_job: Callable[..., Any]
    v19_write_scan_images: Callable[..., Any]


class MaterialIngestionService:
    def __init__(self, dependencies: MaterialIngestionDependencies):
        self.dependencies = dependencies

    async def upload_images(self,
        project_id: str, files: List[UploadFile] = File(...),
        dataset_id: str = Form("default"), storage_source_id: str = Form("default_local"),
        upload_request_id: Optional[str] = Form(None),
        mining_algorithm_id: str = Form(""), mining_version_id: str = Form(""),
    ):
        request_id = str(upload_request_id or "").strip()
        if request_id:
            store = self.dependencies.upload_batch_store(project_id)
            try:
                async with store.claim_upload_request(request_id):
                    return await self.dependencies._plain_upload_images_claimed(
                        project_id, files, dataset_id, storage_source_id, request_id,
                        mining_algorithm_id, mining_version_id,
                    )
            except UploadRequestBusy as error:
                raise PlatformError(
                    "UPLOAD_REQUEST_IN_PROGRESS", "该上传请求正在执行",
                    str(error), "请等待已有请求完成，不要重复提交", 409,
                ) from error
            except ValueError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
        return await self.dependencies._plain_upload_images_claimed(
            project_id, files, dataset_id, storage_source_id, None,
            mining_algorithm_id, mining_version_id,
        )

    def v19_unannotated_import_page(self, project_id: str, job_id: str, cursor: int = 0, limit: int = 150):
        """Materialized ZIP subset, bounded pages; never send all 10k IDs to UI."""
        if not 1 <= limit <= 200 or cursor < 0:
            raise HTTPException(status_code=422, detail="素材分页范围不正确")
        job = self.dependencies.v19_read_job(project_id, job_id)
        if job.get("status") != "done":
            raise HTTPException(status_code=409, detail="ZIP 尚未完成导入，不能开始人工标注")
        ids = list(dict.fromkeys(str(item) for item in self.dependencies.v19_read_import_report(project_id, job_id, job).get("imported_image_ids") or [] if str(item)))
        selected: list[str] = []
        index = cursor
        while index < len(ids) and len(selected) < limit:
            chunk = ids[index:index + min(200, len(ids) - index)]
            current = self.dependencies.read_annotations_many(project_id, chunk)
            for image_id in chunk:
                if str((current.get(image_id) or {}).get("annotation_state") or "unannotated") == "unannotated":
                    selected.append(image_id)
                index += 1
                if len(selected) >= limit:
                    break
        return {"image_ids": selected, "next_cursor": index if index < len(ids) else None,
                "source_batch_id": job_id, "total_imported": len(ids)}

    def v19_import_folders(self, project_id: str, job_id: str, offset: int = Query(0, ge=0),
                           limit: int = Query(50, ge=1, le=100)):
        self.dependencies.get_project(project_id)
        job = self.dependencies.v19_read_job(project_id, job_id)
        scan = self.dependencies.read_json(self.dependencies.v19_job_dir(project_id, job_id) / 'scan-folders.json', {})
        if not job.get('folder_confirmation_required') or not scan or scan.get('source_scan_digest') != job.get('source_scan_digest'):
            raise HTTPException(409, detail='当前任务没有可用的文件夹扫描证据')
        rows = scan['items']
        return dict(source_scan_digest=scan['source_scan_digest'], total=len(rows),
                    items=rows[offset:offset + limit],
                    next_offset=offset + limit if offset + limit < len(rows) else None)

    def v19_retry_folder_classification(self, project_id: str, job_id: str):
        self.dependencies.get_project(project_id)
        with self.dependencies._v19_stop_fence(project_id, job_id):
            job = self.dependencies.v19_read_job(project_id, job_id)
            if (job.get('status') not in {'done', 'failed'} or job.get('history_hidden')
                    or not job.get('folder_confirmation')):
                raise HTTPException(409, detail='当前任务不具备归集恢复条件')
            report = self.dependencies.v19_read_import_report(project_id, job_id, job)
            if not report.get('imported_image_ids'):
                raise HTTPException(409, detail='没有已入库的素材身份可供修复')
            self._v19_apply_folder_classification(project_id, job, report)
            if not (report['folder_classification']['applied'] or report['folder_classification']['pending']):
                raise HTTPException(409, detail='没有可核验的正式素材可供修复')
            job['report'] = report
            self.dependencies._v19_write_job_locked(project_id, job)
            return self.v19_public_job(project_id, self.dependencies.v19_read_job(project_id, job_id))

    def v19_create_multipart_upload(self, project_id: str, dataset_id: str, payload: V19MultipartUploadReq):
        self.dependencies.get_project(project_id)
        if payload.algorithm_id and not any(str(row.get('id')) == payload.algorithm_id for row in self.dependencies.list_algorithms_internal(project_id)):
            raise HTTPException(422, detail='目标算法不存在，请刷新负样本池')
        filename = self.dependencies.safe_filename(payload.file_name or "dataset.zip")
        if Path(filename).suffix.lower() != ".zip":
            raise HTTPException(status_code=400, detail="文件类型不支持：请上传 .zip 压缩包。")
        repository = self.dependencies._v19_multipart_repository(project_id)
        if payload.resume_upload_id:
            # An explicit resume must never create a new empty task on a file mismatch.
            try:
                previous = repository.get(payload.resume_upload_id)
            except FileNotFoundError as error:
                raise HTTPException(status_code=409, detail="原 ZIP 上传会话已失效，请重新选择上传") from error
            if (
                str(previous.get("fingerprint") or "") != str(payload.fingerprint or "")
                or str(previous.get("dataset_id") or "") != str(dataset_id)
                or str(previous.get("file_name") or "") != filename
                or int(previous.get("file_size") or 0) != int(payload.file_size)
                or str(previous.get("status") or "") not in {"uploading", "paused"}
            ):
                raise HTTPException(status_code=409, detail="ZIP 文件身份与原上传会话不一致，已拒绝创建新任务")
        try:
            session = repository.create_or_resume(
                dataset_id=dataset_id, file_name=filename, file_size=int(payload.file_size),
                fingerprint=str(payload.fingerprint or ""), part_size=int(payload.part_size or 0),
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        job_id = str(session["upload_id"])
        current = self.dependencies.read_json(self.dependencies.v19_job_file(project_id, job_id), {})
        if not isinstance(current, dict) or not current:
            current = {
                "id": job_id, "project_id": project_id, "dataset_id": dataset_id,
                "batch_id": job_id, "file_name": filename,
                "folder_confirmation_requested": payload.folder_confirmation and not payload.algorithm_id,
                "file_size_mb": round(int(payload.file_size) / 1024 / 1024, 2),
                "uploaded_bytes": int(session.get("received_bytes") or 0),
                "upload_progress": float(session.get("upload_progress") or 0),
                "status": "uploading", "stage": "正在上传 ZIP", "progress": 0,
                "phase": "UPLOAD", "phase_completed": int(session.get("received_bytes") or 0),
                "phase_total": int(payload.file_size), "phase_unit": "bytes",
                "message": "分片上传已创建，可断点续传",
                "upload_session_id": job_id, "total_parts": int(session.get("total_parts") or 0),
                "created_at": self.dependencies.now_iso(), "updated_at": self.dependencies.now_iso(),
            }
        else:
            current.update({
                "status": "uploading", "stage": "正在上传 ZIP",
                "uploaded_bytes": int(session.get("received_bytes") or 0),
                "upload_progress": float(session.get("upload_progress") or 0),
                "phase": "UPLOAD", "phase_completed": int(session.get("received_bytes") or 0),
                "phase_total": int(payload.file_size), "phase_unit": "bytes",
                "message": f"继续上传：已完成 {len(session.get('completed_parts') or [])}/{int(session.get('total_parts') or 0)} 个分片",
                "updated_at": self.dependencies.now_iso(),
            })
        frozen_algorithm = str(current.get('upload_algorithm_id') or '')
        if payload.algorithm_id and frozen_algorithm and frozen_algorithm != payload.algorithm_id:
            raise HTTPException(409, detail='ZIP 目标算法已冻结，不能切换算法续传')
        if payload.algorithm_id:
            if current.get('folder_confirmation_requested'):
                raise HTTPException(409, detail='文件夹确认任务不绑定算法')
            current['upload_algorithm_id'] = payload.algorithm_id
        self.dependencies.v19_write_job(project_id, current)
        return {"ok": True, **session, "job": self.v19_public_job(project_id, current, image_limit=0)}

    async def v19_upload_multipart_part(self, project_id: str, upload_id: str, part_number: int, request: Request):
        self.dependencies.get_project(project_id)
        repository = self.dependencies._v19_multipart_repository(project_id)
        try:
            payload = await request.body()
            result = repository.write_part(upload_id, part_number, BytesIO(payload))
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="ZIP 上传会话不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        job = self.dependencies.read_json(self.dependencies.v19_job_file(project_id, upload_id), {})
        if isinstance(job, dict) and job and job.get("status") == "uploading" and result.get("status") == "uploading":
            completed = len(result.get("completed_parts") or [])
            total_parts = int(result.get("total_parts") or 0)
            job.update({
                "status": "uploading", "stage": "正在上传 ZIP",
                "uploaded_bytes": int(result.get("received_bytes") or 0),
                "upload_progress": float(result.get("upload_progress") or 0),
                "phase": "UPLOAD",
                "phase_completed": int(result.get("received_bytes") or 0),
                "phase_total": int(result.get("file_size") or job.get("phase_total") or 0),
                "phase_unit": "bytes",
                "message": f"已完成 {completed}/{total_parts} 个分片",
                "updated_at": self.dependencies.now_iso(),
            })
            self.dependencies.v19_write_job(project_id, job)
        return {"ok": True, **result}

    def v19_pause_multipart_upload(self, project_id: str, upload_id: str):
        self.dependencies.get_project(project_id)
        job = self.dependencies.v19_read_job(project_id, upload_id)
        if str(job.get("status") or "") not in {"uploading", "paused"}:
            raise HTTPException(status_code=409, detail="已进入合并或正式导入阶段，不能暂停上传")
        try:
            session = self.dependencies._v19_multipart_repository(project_id).pause(upload_id)
        except (FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        self.dependencies.v19_update_job(
            project_id, upload_id, status="paused", stage="已暂停，等待继续上传",
            phase="UPLOAD", uploaded_bytes=int(session.get("received_bytes") or 0),
            upload_progress=float(session.get("upload_progress") or 0),
            phase_completed=int(session.get("received_bytes") or 0),
            message=f"已暂停，保存 {len(session.get('completed_parts') or [])}/{session.get('total_parts')} 个分片",
        )
        return {"ok": True, **session}

    def v19_cancel_multipart_upload(self, project_id: str, upload_id: str):
        # Compatibility route for older clients.  Cancellation ownership and its
        # safety/cleanup contract remain in the one unified job service below.
        try:
            session = self.dependencies._v19_multipart_repository(project_id).get(upload_id)
        except FileNotFoundError:
            session = {}
        result = self._v19_cancel_import_job(project_id, upload_id)
        legacy_result = {**session, **result, "ok": True}
        if (
            str(result.get("status") or "").strip().lower() in {"cancelled", "canceled"}
            and result.get("cleanup_status") == "complete"
        ):
            legacy_result.update(completed_parts=[], received_bytes=0)
        return legacy_result

    def v19_complete_multipart_upload(self, project_id: str, upload_id: str):
        self.dependencies.get_project(project_id)
        job = self.dependencies.v19_read_job(project_id, upload_id)
        status = str(job.get("status") or "").strip().lower()
        if status in {"cancelled", "canceled"} or job.get("cancel_requested"):
            raise HTTPException(status_code=409, detail="ZIP 任务已取消，无法合并")
        repository = self.dependencies._v19_multipart_repository(project_id)
        try:
            session = repository.get(upload_id)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="ZIP 上传会话不存在") from error
        if str(session.get("status") or "") in {"paused", "cancelled"}:
            raise HTTPException(status_code=409, detail="ZIP 会话已暂停或取消，无法合并")

        if status in {"selecting", "running", "done"}:
            return self.v19_public_job(project_id, job, image_limit=500 if status == "selecting" else 0)
        if status not in {"merging", "validating"}:
            completed = len(session.get("completed_parts") or [])
            total = int(session.get("total_parts") or 0)
            if str(session.get("status") or "") != "completed" and completed != total:
                raise HTTPException(
                    status_code=409,
                    detail=f"ZIP 分片尚未全部上传：{completed}/{total}",
                )
            with self.dependencies._v19_stop_fence(project_id, upload_id):
                if self.dependencies.v19_read_job(project_id, upload_id).get("cancel_requested"):
                    raise HTTPException(status_code=409, detail="ZIP 任务正在取消，不能继续合并")
                self.dependencies.v19_update_job(
                    project_id, upload_id,
                    status="merging", stage="正在合并 ZIP 分片", progress=35,
                    upload_progress=100,
                    phase="MERGE", phase_completed=0,
                    phase_total=int(session.get("file_size") or 0), phase_unit="bytes",
                    phase_progress=0, phase_elapsed_seconds=0, eta_seconds=None,
                    message="所有分片已上传，后台正在合并 ZIP；页面可以关闭",
                )

        self.dependencies._v19_schedule_multipart_finalize(project_id, upload_id)
        current = self.dependencies.v19_read_job(project_id, upload_id)
        return JSONResponse(
            status_code=202,
            content=self.v19_public_job(project_id, current, image_limit=0),
        )

    async def v19_create_import_job(self, project_id: str, dataset_id: str, file: UploadFile = File(...),
                                    folder_confirmation: bool = Form(False)):
        self.dependencies.get_project(project_id)
        filename = self.dependencies.safe_filename(file.filename or "dataset.zip")
        if Path(filename).suffix.lower() != ".zip":
            raise HTTPException(status_code=400, detail="文件类型不支持：请上传 .zip 压缩包。")
        job_id = uuid.uuid4().hex[:10]
        jd = self.dependencies.v19_job_dir(project_id, job_id)
        jd.mkdir(parents=True, exist_ok=True)
        zip_path = jd / "source.zip"
        upload_started = time.time()
        uploaded_bytes = 0
        try:
            # 分块落盘，避免大 ZIP 一次性读入内存。
            with zip_path.open("wb") as out:
                while True:
                    chunk = await file.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    uploaded_bytes += len(chunk)
        except Exception as e:
            shutil.rmtree(jd, ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"文件接收失败：{e}")
        upload_seconds = round(max(0.0, time.time() - upload_started), 2)
        if uploaded_bytes <= 0:
            shutil.rmtree(jd, ignore_errors=True)
            raise HTTPException(status_code=400, detail="上传失败：ZIP 文件为空。")
        scan_started = time.time()
        try:
            scan = self.dependencies._v19_prepare_scan(project_id, self.dependencies.v19_scan_zip(zip_path, folder_confirmation=True)
                                     if folder_confirmation is True else self.dependencies.v19_scan_zip(zip_path))
            if folder_confirmation is True:
                self.dependencies._v19_store_folder_scan(project_id, job_id, zip_path, scan)
        except zipfile.BadZipFile:
            shutil.rmtree(jd, ignore_errors=True)
            raise HTTPException(status_code=400, detail="ZIP 校验失败：压缩包已损坏、格式不正确或不是有效 ZIP。")
        except Exception as e:
            shutil.rmtree(jd, ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"ZIP 校验失败：{e}")
        scan_seconds = round(max(0.0, time.time() - scan_started), 2)
        if scan.get("image_count", 0) == 0:
            shutil.rmtree(jd, ignore_errors=True)
            raise HTTPException(status_code=400, detail="ZIP 内容不匹配：压缩包内没有识别到支持的图片文件。")
        scan_images = list(scan.pop("images", []) or [])
        scan_class_samples = dict(scan.pop("class_samples", {}) or {})
        self.dependencies.v19_write_scan_images(project_id, job_id, scan_images)
        self.dependencies.v19_write_class_samples(project_id, job_id, scan_class_samples)
        job = {
            "id": job_id, "project_id": project_id, "dataset_id": dataset_id,
            "batch_id": job_id,
            "file_name": filename, "file_size_mb": round(uploaded_bytes / 1024 / 1024, 2),
            "uploaded_bytes": uploaded_bytes, "upload_seconds": upload_seconds, "scan_seconds": scan_seconds,
            "status": "selecting", "stage": "上传与校验完成", "progress": 48,
            "sample_classification_required": scan.get("scan_kind") != "RAW_UNANNOTATED",
            "phase": "WAITING_CONFIRMATION",
            "phase_completed": 1, "phase_total": 1, "phase_unit": "step",
            "phase_progress": 100, "eta_seconds": None,
            "message": (
                "上传与ZIP校验完成，等待确认标签并开始后台导入"
                if scan.get("label_confirmation_required")
                else "ZIP 扫描完成，未检测到标注，可按原图直接入库" if scan.get("scan_kind") == "RAW_UNANNOTATED"
                else "上传与ZIP校验完成，请选择正样本标签或负样本分类后导入"
            ),
            "scan_images_ref": "scan-images.json",
            "class_samples_ref": "scan-class-samples.json",
            "created_at": self.dependencies.now_iso(), "uploaded_at": self.dependencies.now_iso(), "updated_at": self.dependencies.now_iso(), **scan,
        }
        self.dependencies.v19_write_job(project_id, job)
        return self.v19_public_job(project_id, job, image_limit=500)

    def v19_cancel_import_job(self, project_id: str, job_id: str):
        return self._v19_cancel_import_job(project_id, job_id)

    def v19_stop_import_job(self, project_id: str, job_id: str):
        # Backward-compatible alias for historical clients; one service owns safety.
        return self._v19_cancel_import_job(project_id, job_id)

    def v19_start_import_job(self, project_id: str, job_id: str, payload: V19ImportStartReq):
        # Same-project submit is one atomic operation even across API processes.
        with FileLock(str(self.dependencies.v19_import_jobs_dir(project_id) / ".enqueue.lock"), timeout=120):
            # Starting and cancelling share the same per-job fence.  Once a
            # cancellation request is durable no concurrent tab/process can queue
            # the job or freeze a new label mapping behind it.
            with self.dependencies._v19_stop_fence(project_id, job_id):
                return self._v19_start_import_job_locked(project_id, job_id, payload)

    def v19_label_samples(self, project_id: str, job_id: str, class_id: str):
        self.dependencies.get_project(project_id)
        job = self.dependencies.v19_read_job(project_id, job_id)
        if str(job.get("status") or "").lower() != "selecting":
            raise HTTPException(status_code=409, detail="当前 ZIP 已不在标签确认阶段")
        if str(class_id) not in {str(row.get("class_id")) for row in job.get("external_classes", [])}:
            raise HTTPException(status_code=404, detail="外部标签不存在")
        samples = self.dependencies.v19_read_class_samples(project_id, job_id).get(str(class_id), [])[:8]
        route = (
            f"/api/v19/projects/{quote(project_id, safe='')}/import/jobs/{quote(job_id, safe='')}"
        f"/classes/{quote(str(class_id), safe='')}/sample-content"
        )
        return {"job_id": job_id, "class_id": str(class_id), "samples": [
            {
                "filename": row.get("filename") or "",
                "bbox": row.get("bbox") or {},
                "bboxes": (row.get("bboxes") or [row.get("bbox") or {}])[:256],
                "preview_url": f"{route}?index={index}",
                "content_url": f"{route}?index={index}",
            }
            for index, row in enumerate(samples)
        ], "count": len(samples)}

    def v19_label_sample_content(self, project_id: str, job_id: str, class_id: str, index: int = Query(ge=0, le=11)):
        self.dependencies._authorize_business_file_project(project_id)
        sample = self._v19_zip_class_sample(project_id, job_id, class_id, index)
        image_path = str(sample.get("image_path") or "")
        suffix = Path(image_path).suffix.lower()
        content_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        if suffix not in content_types:
            raise HTTPException(status_code=415, detail="不支持预览此图片格式")
        archive = self.dependencies.v19_job_dir(project_id, job_id) / "source.zip"
        if not archive.is_file():
            raise HTTPException(status_code=409, detail="ZIP 原始文件已不可用，无法查看样本")
        try:
            with zipfile.ZipFile(archive) as zf:
                entries = [
                    info for info in zf.infolist()
                    if self.dependencies.v19_normalize_zip_path(info.filename) == image_path
                ]
                if len(entries) != 1:
                    raise HTTPException(status_code=404, detail="ZIP 原图不存在或路径有歧义")
                entry = entries[0]
                if entry.is_dir() or entry.file_size > 12 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="预览图片超过 12 MiB 限制")
                with zf.open(entry) as source:
                    content = source.read(12 * 1024 * 1024 + 1)
                if len(content) > 12 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="预览图片超过 12 MiB 限制")
        except (KeyError, zipfile.BadZipFile, RuntimeError, OSError) as error:
            raise HTTPException(status_code=404, detail="ZIP 样本已不可用") from error
        return Response(content=content, media_type=content_types[suffix], headers={
            "Cache-Control": "private, max-age=60",
            "X-Content-Type-Options": "nosniff",
        })

    def v19_list_import_jobs(self, project_id: str):
        self.dependencies.get_project(project_id)
        self.dependencies._v19_multipart_repository(project_id).cleanup_expired_if_due(interval_seconds=60)
        jobs = []
        d = self.dependencies.v19_import_jobs_dir(project_id)
        for jf in d.glob("*/job.json"):
            job = self.dependencies.read_json(jf, {})
            if job and not job.get("history_hidden"):
                self.dependencies._v19_recover_multipart_finalize(project_id, job)
                # Selecting jobs keep a bounded preview for compatibility. Running/terminal polling stays O(1).
                preview = 300 if job.get("status") == "selecting" else 0
                jobs.append(self.v19_public_job(project_id, job, image_limit=preview))
        positions = {
            str(job.get("id") or ""): pos
            for pos, job in enumerate(self.dependencies._v19_fifo_import_jobs(project_id), 1)
        }
        for job in jobs:
            job["queue_position"] = positions.get(str(job.get("id") or ""))
        jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return {"ok": True, "items": jobs}

    def v19_get_import_job(self, project_id: str, job_id: str, include_images: bool = False, image_limit: int = 500):
        self.dependencies.get_project(project_id)
        job = self.dependencies.v19_read_job(project_id, job_id)
        self.dependencies._v19_recover_multipart_finalize(project_id, job)
        result = self.v19_public_job(project_id, job, image_limit=image_limit if include_images else 0)
        queue_phase = str(job.get("phase") or "").upper()
        result["queue_position"] = self.dependencies._v19_fifo_queue_position(project_id, job_id) if queue_phase == "QUEUE" or (not queue_phase and job.get("status") == "running") else None
        return result

    def v19_clear_terminal_import_jobs(self, project_id: str, job_ids: str = ""):
        self.dependencies.get_project(project_id)
        requested = [value for value in job_ids.split(",") if value]
        if len(requested) > 200 or len(job_ids) > 26000:
            raise HTTPException(status_code=422, detail="一次核验的历史任务过多，请分批清空")
        deleted = []
        kept = []
        candidates = {path.parent.name for path in self.dependencies.v19_import_jobs_dir(project_id).glob("*/job.json")}
        for job_id in sorted(candidates | set(requested)):
            try:
                self._v19_hide_terminal_job(project_id, job_id)
                deleted.append(job_id)
            except HTTPException as error:
                kept.append({"id": job_id, "reason": error.detail, "http_status": error.status_code})
            except Exception as error:
                self._v19_job_diagnostic(project_id, job_id, error, operation="history_cleanup")
                kept.append({"id": job_id, "reason": "临时文件清理失败，记录已保留", "http_status": 503})
        return {"ok": True, "deleted": len(deleted), "deleted_ids": deleted, "kept": kept}

    def v19_delete_import_job(self, project_id: str, job_id: str):
        return self._v19_hide_terminal_job(project_id, job_id)

    def v36_scan_source_import(self, project_id: str, dataset_id: str, payload: V36SourceImportScanReq):
        self.dependencies.get_project(project_id)
        source = self.dependencies._v36_normalize_source(payload.source)
        if not source:
            raise HTTPException(status_code=400, detail="请填写本机路径或服务器 URL")
        if self.dependencies._v36_is_url(source):
            scan = self.dependencies._v36_scan_url(source)
            return {
                "ok": True,
                **scan,
                "label_confirmation_required": False,
                "legacy_annotated_import_blocked": False,
                "annotation_check": "worker_preflight",
            }

        root = Path(source).expanduser()
        scan = self.dependencies._v36_scan_local_root(root)
        formats = self.dependencies._v36_detect_source_annotation_formats(root)
        blocked = bool(formats)
        return {
            "ok": True,
            **scan,
            "detected_annotation_formats": formats,
            "label_confirmation_required": blocked,
            "legacy_annotated_import_blocked": blocked,
            "import_block_reason": self.dependencies.V36_ANNOTATED_IMPORT_BLOCKED_DETAIL() if blocked else "",
        }

    def v36_list_source_import_jobs(self, project_id: str, dataset_id: str):
        self.dependencies.get_project(project_id)
        items = [x for x in self.dependencies._v36_load_source_jobs(project_id) if x.get("dataset_id") == dataset_id]
        return {"items": items[:100]}

    def v36_start_source_import_job(self, project_id: str, dataset_id: str, payload: V36SourceImportStartReq):
        self.dependencies.get_project(project_id)
        source = self.dependencies._v36_normalize_source(payload.source)
        if not source:
            raise HTTPException(status_code=400, detail="请填写本机路径或服务器 URL")
        if not self.dependencies._v36_is_url(source):
            root = Path(source).expanduser()
            if not root.exists():
                raise HTTPException(status_code=400, detail=f"路径不存在：{root}")
            formats = self.dependencies._v36_detect_source_annotation_formats(root)
            if formats:
                raise HTTPException(
                    status_code=409,
                    detail=f"{self.dependencies.V36_ANNOTATED_IMPORT_BLOCKED_DETAIL()}（检测到：{' / '.join(formats)}）",
                )
        job_id = uuid.uuid4().hex[:12]
        task = {
            "id": job_id,
            "name": payload.task_name or "地址读取导入",
            "source": source,
            "source_type": "url" if self.dependencies._v36_is_url(source) else "local_path",
            "dataset_id": dataset_id,
            "status": "queued",
            "status_text": "排队中",
            "stage": "等待开始",
            "progress": 0,
            "created_at": self.dependencies.now_iso(),
            "updated_at": self.dependencies.now_iso(),
        }
        self.dependencies._v36_write_source_job(project_id, task)
        data = payload.dict()
        import threading as _threading
        th = _threading.Thread(target=self.dependencies._v36_run_source_import, args=(project_id, dataset_id, job_id, data), daemon=True)
        th.start()
        return task

    def v55_get_upload_batch(self, project_id: str, batch_id: str):
        self.dependencies.get_project(project_id)
        batch = self.dependencies._v55_read_upload_batch(self.dependencies.upload_batch_store(project_id), batch_id)
        return self._v55_enrich_upload_batch(project_id, batch)

    def v55_apply_upload_batch_decisions(self,
        project_id: str,
        batch_id: str,
        payload: V55UploadDecisionsReq,
    ):
        self.dependencies.get_project(project_id)
        clean_ids = {
            str(image_id).strip()
            for image_id in (payload.clean_image_ids or [])
            if str(image_id).strip()
        }
        ready_ids = {
            str(image_id).strip()
            for image_id in (payload.ready_image_ids or [])
            if str(image_id).strip()
        }
        store = self.dependencies.upload_batch_store(project_id)
        try:
            store._path(batch_id)
        except ValueError:
            raise HTTPException(status_code=404, detail='上传批次不存在')
        with store.locked(batch_id):
            original = self.dependencies._v55_read_upload_batch(store, batch_id, locked=True)
            upload_request_status = str(original.get('upload_request_status') or 'SUCCEEDED').upper()
            if upload_request_status != 'SUCCEEDED':
                raise HTTPException(status_code=409, detail='上传批次尚未完成，不能提交清洗决策')
            clean_task_id = str(original.get('clean_task_id') or '')
            associated_clean_ids = [
                str(image_id)
                for image_id in original.get('clean_task_image_ids', [])
            ]
            if bool(clean_task_id) != bool(associated_clean_ids):
                raise HTTPException(status_code=400, detail='上传批次清洗任务关联不完整')
            associated_clean_set = set(associated_clean_ids)
            if clean_ids:
                materials = self.dependencies.material_store(project_id)
                indexed = {}
                sorted_clean_ids = sorted(clean_ids)
                for offset in range(0, len(sorted_clean_ids), 500):
                    indexed.update({
                        str(row.get('id')): row
                        for row in materials.get_many(sorted_clean_ids[offset:offset + 500])
                    })
                not_unannotated = []
                for image_id in sorted(clean_ids):
                    row = indexed.get(image_id) or {}
                    annotation_state = str(
                        row.get('annotation_state')
                        or row.get('annotation_status')
                        or ('annotated' if row.get('annotated') else 'unannotated')
                    ).strip().lower()
                    if annotation_state != 'unannotated':
                        not_unannotated.append(image_id)
                if not_unannotated:
                    raise HTTPException(
                        status_code=409,
                        detail='批量上传入口只允许把未标注素材送入图片质量清洗；带标注素材请使用标注质量审计',
                    )
            if clean_task_id and clean_ids - associated_clean_set:
                raise HTTPException(
                    status_code=400,
                    detail='每个上传批次只支持一个清洗任务，不能追加新的清洗图片',
                )
            if clean_task_id and ready_ids & associated_clean_set:
                raise HTTPException(
                    status_code=400,
                    detail='已提交清洗的图片不能改为无需清洗',
                )
            try:
                updated = apply_decisions(original, clean_ids, ready_ids)
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error))

            if not clean_task_id and clean_ids:
                associated_clean_ids = [
                    str(item.get('image_id'))
                    for item in updated.get('items', [])
                    if str(item.get('image_id')) in clean_ids
                ]
                associated_clean_set = set(associated_clean_ids)
                clean_task_id = self._v55_upload_clean_task_id(
                    project_id,
                    batch_id,
                    associated_clean_ids,
                )
                updated['clean_task_id'] = clean_task_id
                updated['clean_task_image_ids'] = associated_clean_ids

            clean_request = None
            prepared_created = False
            failed_task_snapshot: Optional[Dict[str, Any]] = None
            terminal_clean_task = False
            if clean_task_id:
                clean_request = V47CleanReq(
                    image_ids=associated_clean_ids,
                    task_name=f'上传批次 {batch_id} 清洗',
                )
                existing_task = self.dependencies._v33_get_task(project_id, 'clean_tasks', clean_task_id)
                existing_status = str((existing_task or {}).get('status') or '')
                terminal_clean_task = existing_status in {
                    'awaiting_confirmation', 'done', 'succeeded', 'success', 'completed',
                }
                if existing_status == 'failed':
                    failed_task_snapshot = dict(existing_task or {})
                    self.dependencies._v47_reset_failed_clean_task_record(project_id, clean_task_id)
                try:
                    _, prepared_created = self.dependencies._v62_prepare_clean_compat(
                        project_id,
                        clean_request,
                        task_id=clean_task_id,
                    )
                except ValueError as error:
                    raise HTTPException(status_code=400, detail=str(error))

            decided_at = self.dependencies.now_iso()
            updated['updated_at'] = decided_at
            # A replay after a successful/awaiting task only records the same
            # decision in the batch; it must not regress confirmed material back
            # to ``cleaning``. Failed tasks are explicitly reset above and may be
            # retried with the same deterministic task id.
            material_clean_ids = set() if terminal_clean_task else set(clean_ids)
            affected_ids = material_clean_ids | ready_ids
            decision_fields = (
                'processing_status',
                'clean_skipped',
                'clean_decision',
                'clean_decision_at',
                'updated_at',
            )
            backups: Dict[str, Dict[str, Tuple[bool, Any]]] = {}
            applied_values: Dict[str, Dict[str, Any]] = {}

            def apply_material_decisions(rows):
                found = {
                    str(row.get('id'))
                    for row in rows
                    if str(row.get('id')) in affected_ids
                }
                missing = affected_ids - found
                if missing:
                    raise ValueError(f"图片不存在：{', '.join(sorted(missing))}")
                for index, row in enumerate(rows):
                    image_id = str(row.get('id'))
                    if image_id not in affected_ids:
                        continue
                    backups[image_id] = {
                        field: (field in row, row.get(field))
                        for field in decision_fields
                    }
                    if image_id in ready_ids:
                        rows[index] = mark_ready(row, decided_at)
                    elif image_id in material_clean_ids:
                        changed = dict(row)
                        changed.update({
                            'processing_status': 'cleaning',
                            'clean_skipped': False,
                            'clean_decision': 'clean',
                            'clean_decision_at': decided_at,
                            'updated_at': decided_at,
                        })
                        rows[index] = changed
                    applied_values[image_id] = {
                        field: rows[index].get(field)
                        for field in decision_fields
                    }
                return None

            try:
                store._write_unlocked(batch_id, updated)
                self.dependencies.material_store(project_id).mutate_ids(affected_ids, apply_material_decisions)
                if clean_task_id:
                    self.dependencies._v62_publish_clean_compat(project_id, clean_task_id)
            except Exception as error:
                store._write_unlocked(batch_id, original)
                if backups:
                    def restore_material_decisions(rows):
                        for row in rows:
                            image_id = str(row.get('id'))
                            before = backups.get(image_id)
                            expected = applied_values.get(image_id)
                            if before is None or expected is None:
                                continue
                            for field, (existed, value) in before.items():
                                # Restore only fields still owned by this
                                # transaction. A concurrent filename/updated_at
                                # edit must survive the rollback.
                                if row.get(field) != expected.get(field):
                                    continue
                                if existed:
                                    row[field] = value
                                else:
                                    row.pop(field, None)
                    self.dependencies.material_store(project_id).mutate_ids(backups, restore_material_decisions)
                if prepared_created and clean_task_id:
                    self.dependencies._v47_remove_prepared_clean_task_record(project_id, clean_task_id)
                elif failed_task_snapshot and clean_task_id:
                    self.dependencies._v47_restore_clean_task_record(project_id, clean_task_id, failed_task_snapshot)
                if isinstance(error, ValueError):
                    raise HTTPException(status_code=400, detail=str(error))
                raise HTTPException(status_code=500, detail=f'保存上传决策失败：{error}')

            persisted = store._read_unlocked(batch_id)
        return self._v55_enrich_upload_batch(project_id, persisted)

    def v52_import_review(self, project_id: str, job_id: str):
        job = self.dependencies.v19_read_job(project_id, job_id)
        report = self.dependencies.v19_read_import_report(project_id, job_id, job)
        ids = list(dict.fromkeys(
            str(value).strip()
            for value in (report.get('imported_image_ids') or [])
            if str(value).strip()
        ))
        images = self.dependencies.material_store(project_id).get_many(ids)
        annotations: Dict[str, Dict[str, Any]] = {}
        for offset in range(0, len(ids), 500):
            annotations.update(self.dependencies.read_annotations_many(project_id, ids[offset:offset + 500]))
        counts: Dict[str, int] = {}
        for img in images:
            ann = annotations.get(str(img.get('id'))) or {}
            for b in ann.get('boxes', []):
                label = str(b.get('label') or '').strip()
                if label:
                    counts[label] = counts.get(label, 0) + 1
        return {
            'ok': True,
            'job': {'id': job.get('id'), 'file_name': job.get('file_name'), 'status': job.get('status'), 'detected_format': report.get('detected_format')},
            'report': report,
            'image_ids': ids,
            'images': images,
            'label_box_counts': counts,
        }

    def v19_zip_display_progress(self, job: Mapping[str, Any]) -> Dict[str, Any]:
        """Canonical product-facing ZIP progress projection.

    phase counters are factual. overall_progress is only a stable display
    projection over those server-owned phases; browser code must not invent
    a second set of phase weights.
    """
        status = str(job.get("status") or "").strip().lower()
        phase = str(job.get("phase") or "").strip().upper()
        if not phase:
            phase = {
                "uploading": "UPLOAD",
                "merging": "MERGE",
                "validating": "SCAN",
                "selecting": "WAITING_CONFIRMATION" if job.get("label_confirmation_required") else "READY",
                "queued": "QUEUE",
                "waiting": "QUEUE",
                "running": "ANNOTATION_PARSE",
                "done": "DONE",
                "failed": "FAILED",
            }.get(status, "")

        try:
            done = max(0.0, float(job.get("phase_completed") or 0))
        except (TypeError, ValueError):
            done = 0.0
        try:
            total = max(0.0, float(job.get("phase_total") or 0))
        except (TypeError, ValueError):
            total = 0.0
        if total > 0:
            phase_progress: Optional[float] = min(100.0, done / total * 100.0)
        else:
            raw_phase_progress = job.get("phase_progress")
            if raw_phase_progress in (None, ""):
                phase_progress = None
            else:
                try:
                    phase_progress = max(0.0, min(100.0, float(raw_phase_progress)))
                except (TypeError, ValueError):
                    phase_progress = None

        if status == "done" or phase == "DONE":
            overall = 100.0
            phase_progress = 100.0
        elif status == "failed" or phase == "FAILED":
            try:
                overall = max(0.0, min(99.0, float(job.get("progress") or 0)))
            except (TypeError, ValueError):
                overall = 0.0
        else:
            start, end = self.dependencies.V19_ZIP_PHASE_WINDOWS().get(phase, (0.0, 99.0))
            overall = start if phase_progress is None else start + (end - start) * phase_progress / 100.0
            overall = max(0.0, min(99.0, overall))

        return {
            "phase": phase or None,
            "phase_label": self.dependencies.V19_ZIP_PHASE_LABELS().get(phase, str(job.get("stage") or phase or "ZIP 导入")),
            "phase_progress": round(phase_progress, 2) if phase_progress is not None else None,
            "overall_progress": round(overall, 2),
            "completed": job.get("phase_completed"),
            "total": job.get("phase_total"),
            "unit": str(job.get("phase_unit") or ""),
            "elapsed_seconds": job.get("phase_elapsed_seconds"),
            "eta_seconds": job.get("eta_seconds") if phase_progress is not None else None,
            "message": str(job.get("message") or ""),
            "updated_at": job.get("updated_at"),
        }

    def v19_public_job(self, project_id: str, job: Dict[str, Any], image_limit: int = 0) -> Dict[str, Any]:
        result = dict(job or {})
        result.pop("images", None)
        result.pop('folder_confirmation', None)
        if result.get('folder_confirmation_required'):
            image_limit = 0
        # A readable but stale job.json is not proof that a worker still runs after
        # a failed state write. A diagnostic only invalidates that exact file
        # revision; a later successful write restores the original authority.
        if str(result.get("status") or "").lower() not in {"done", "failed", "cancelled", "canceled"}:
            if self._v19_unresolved_diagnostic(project_id, str(result.get("id"))):
                result.update(last_known_status=result.get("status"), status="unknown",
                              verificationReason="UNAVAILABLE", error="任务状态写入或执行异常，最后记录不能代表实际执行状态；请核验任务诊断。")
        result["zip_display_progress"] = self.v19_zip_display_progress(result)
        limit = max(0, min(500, int(image_limit or 0)))
        if limit:
            images = self.dependencies.v19_read_scan_images(project_id, str(result.get("id") or ""))
            result["images"] = images[:limit]
            result["images_truncated"] = len(images) > limit
        return result

    def _v19_phase_metrics(self,
        phase: str,
        completed: int | float | None,
        total: int | float | None,
        *,
        started_at: float | None = None,
    ) -> Dict[str, Any]:
        done = max(0.0, float(completed or 0))
        target = max(0.0, float(total or 0))
        phase_progress = round(min(100.0, done / target * 100.0), 2) if target > 0 else None
        elapsed = None
        eta = None
        if started_at is not None:
            elapsed = round(max(0.0, time.time() - float(started_at)), 2)
            if done > 0 and target > done:
                eta = round(max(0.0, elapsed / done * (target - done)), 2)
            elif target > 0 and done >= target:
                eta = 0.0
        return {
            "phase": str(phase or "").upper(),
            "phase_completed": completed,
            "phase_total": total,
            "phase_progress": phase_progress,
            "phase_elapsed_seconds": elapsed,
            "eta_seconds": eta,
        }

    def _v19_job_diagnostic(self, project_id: str, job_id: str, error: Exception, *, operation: str,
                            job=None, report=None, committed=False):
        """Independent failure evidence, never a replacement successful task record."""
        import logging
        logger = logging.getLogger(__name__)
        logger.error("ZIP job %s/%s %s failed: %s", project_id, job_id, operation, error, exc_info=True)
        evidence = {
            "project_id": project_id, "job_id": job_id, "operation": operation,
            "code": "ZIP_JOB_RECORD_UNAVAILABLE", "outcome": "unknown",
            "error": str(getattr(error, "detail", error)), "recorded_at": self.dependencies.now_iso(),
            "file_name": (job or {}).get("file_name"),
            "formal_commit_completed": bool(committed),
            "observed_record": self.dependencies._v19_job_record_token(project_id, job_id),
            "report": {k: v for k, v in (report or {}).items() if k in {
                "imported_images", "annotated_images", "boxes", "missing_images",
                "skipped_images", "invalid_boxes", "unmatched_labels", "batch_id",
            }},
        }
        try:
            path = self.dependencies.v19_import_jobs_dir(project_id) / ".diagnostics" / (str(job_id) + ".json")
            path.parent.mkdir(parents=True, exist_ok=True)
            previous = self.dependencies.read_json(path, {})
            decisive = {"state_update", "worker_failure", "worker_exit", "finalize_exit", "rollback"}
            if (operation not in decisive and previous.get("operation") in decisive
                    and previous.get("observed_record") == evidence.get("observed_record")):
                # Secondary temp-cleanup errors must never erase proof that the
                # worker stopped, or resurrect its stale RUNNING FIFO predecessor.
                evidence = {**previous, "secondary_error": {
                    "operation": operation, "error": evidence["error"],
                    "recorded_at": evidence["recorded_at"],
                }}
            atomic_write_json(path, evidence)
        except Exception:
            logger.exception("ZIP diagnostic persistence failed for %s/%s", project_id, job_id)

    def _v19_unresolved_diagnostic(self, project_id, job_id):
        diagnostic = self.dependencies.read_json(self.dependencies.v19_import_jobs_dir(project_id) / ".diagnostics" / (str(job_id) + ".json"), {})
        if diagnostic.get("operation") not in {"state_update", "worker_failure", "worker_exit", "finalize_exit", "rollback"}:
            return None
        token = self.dependencies._v19_job_record_token(project_id, job_id)
        return diagnostic if token and diagnostic.get("observed_record") == token else None

    def _v19_assert_frozen_mapping_targets_active(self,
        project_id: str,
        label_mapping: Optional[Dict[str, str]],
    ) -> None:
        targets = sorted({
            str(value).strip()
            for value in dict(label_mapping or {}).values()
            if str(value).strip()
        })
        if not targets:
            return
        active = {
            str(item.get("code") or "").strip()
            for item in active_label_options(self.dependencies.project_label_items(self.dependencies.get_project(project_id)))
            if str(item.get("code") or "").strip()
        }
        unavailable = [code for code in targets if code not in active]
        if unavailable:
            raise HTTPException(
                status_code=409,
                detail=(
                    "ZIP 标签映射目标已失效，请恢复标签后重试或重新创建导入任务："
                    + "、".join(unavailable[:10])
                ),
            )

    def _v19_apply_folder_classification(self, project_id, job, report):
        from platform_core.negative_pool import NegativePool

        plan = job['folder_confirmation']
        rule_digest = job['folder_confirmation_digest']
        if (zip_folders.digest(plan) != rule_digest or plan['project_id'] != project_id or plan['job_id'] != job['id']):
            raise ValueError('冻结的文件夹归集身份已变化')
        materials = self.dependencies.material_store(project_id)
        pool = NegativePool(materials)
        applied, pending = 0, 0
        errors = {}
        examples = []
        ids = report.get('imported_image_ids') or []
        for offset in range(0, len(ids), 500):
            grouped = {}
            for row in materials.get_many(ids[offset:offset + 500]):
                source = row.get('zip_folder_source') or {}
                key = source.get('folder_key')
                rule = plan['rules'].get(key)
                if (not rule or row.get('import_batch_id') != job['id'] or source.get('job_id') != job['id']
                        or source.get('rule_digest') != rule_digest or source.get('source_zip_sha256') != plan['source_zip_sha256']
                        or source.get('source_scan_digest') != plan['scan_digest']
                        or zip_folders.folder_key(source.get('source_path') or '.') != key
                        or any(source.get(field) != value for field, value in rule.items())):
                    continue
                if len(examples) < 10:
                    examples.append({'source_path': source['source_path'], 'material_id': row['id'],
                                     'usage_intent': source['usage_intent']})
                if source.get('classification_status') == 'applied':
                    applied += 1
                elif rule['sample_type'] == 'negative':
                    grouped.setdefault(key, []).append(row['id'])
            for key, chunk in grouped.items():
                try:
                    pool.members(chunk, category_ids=plan['rules'][key]['negative_category_ids'],
                                 zip_folder={'job_id': job['id'], 'rule_digest': rule_digest, 'folder_key': key})
                    applied += len(chunk)
                except Exception as error:
                    pending += len(chunk)
                    if len(errors) < 20:
                        errors.setdefault(key, str(error)[:180])
        report['folder_classification'] = {
            'status': 'pending' if pending else 'applied', 'applied': applied, 'pending': pending,
            'unavailable': max(0, len(ids) - applied - pending),
            'examples': examples, 'errors': [{'folder_key': key, 'error': reason} for key, reason in errors.items()],
        }

    def _v19_cancel_import_job(self, project_id: str, job_id: str) -> Dict[str, Any]:
        self.dependencies.get_project(project_id)
        schedule_finalize = False
        with self.dependencies._v19_stop_fence(project_id, job_id):
            job = self.dependencies.v19_read_job(project_id, job_id)
            status = str(job.get("status") or "").strip().lower()
            phase = str(job.get("phase") or "").strip().upper()

            if status in {"cancelled", "canceled"} and job.get("cleanup_status") == "complete":
                return self.v19_public_job(project_id, job)
            if status == "done" or phase == "DB_COMMIT":
                raise HTTPException(
                    status_code=409,
                    detail="该任务已进入正式提交或已完成，不能伪装为取消；如需撤销必须使用独立的安全撤销流程。",
                )
            if status == "failed" and job.get("cleanup_status") != "failed":
                raise HTTPException(
                    status_code=409,
                    detail="失败任务可能已产生正式数据，必须先完成完整性审计，不能直接取消清理。",
                )

            cleanup_retry = status in {"cancelled", "canceled"} or (
                status == "failed" and job.get("cleanup_status") == "failed"
            )
            worker_cancellable = status in {"running", "queued", "waiting"} and phase in {
                "QUEUE", "EXTRACT", "ANNOTATION_PARSE", "UPLOAD", "MERGE", "VERIFY", "SCAN",
            }
            if status not in {"uploading", "paused", "selecting", "merging", "validating"} and not cleanup_retry and not worker_cancellable:
                raise HTTPException(
                    status_code=409,
                    detail="当前任务阶段不能安全取消；服务器未删除任何任务或正式数据。",
                )

            job.update(
                cancel_requested=True, cancel_requested_at=job.get("cancel_requested_at") or self.dependencies.now_iso(),
                stage="正在安全取消并清理", message="服务器已收到取消请求，正在停止当前阶段",
            )
            self.dependencies.v19_write_job(project_id, job)

            if status in {"uploading", "paused"}:
                try:
                    self.dependencies._v19_multipart_repository(project_id).cancel(job_id)
                except FileNotFoundError:
                    pass
                except ValueError as error:
                    raise HTTPException(status_code=409, detail=str(error)) from error
                job = self.dependencies._v19_finish_cancel(
                    project_id, job_id,
                    message="已取消上传并清理本任务尚未提交的 ZIP 分片缓存",
                )
                return self.v19_public_job(project_id, job)

            if status == "selecting" or cleanup_retry:
                job = self.dependencies._v19_finish_cancel(
                    project_id, job_id,
                    message="已取消导入并清理本任务尚未提交的 ZIP 与扫描缓存",
                )
                return self.v19_public_job(project_id, job)

            if status in {"merging", "validating"}:
                schedule_finalize = True
            elif worker_cancellable:
                return self.v19_public_job(project_id, self.dependencies.v19_read_job(project_id, job_id))

        if schedule_finalize:
            self.dependencies._v19_schedule_multipart_finalize(project_id, job_id)
        return self.v19_public_job(project_id, self.dependencies.v19_read_job(project_id, job_id))

    def _v19_confirm_folder_rules(self, project_id, job_id, job, payload):
        from platform_core.negative_pool import NegativePool

        frozen = job.get('folder_confirmation')
        if (not payload.source_scan_digest or payload.source_scan_digest != job.get('source_scan_digest')
                or payload.folder_rules is None):
            raise HTTPException(409, detail='文件夹待确认或扫描证据已变化，请重新读取当前任务')
        if payload.algorithm_id or payload.sample_type or payload.intended_label_codes or payload.negative_category_ids:
            raise HTTPException(422, detail='文件夹规则不能与整包归类或算法绑定混用')
        if job.get('folder_mapping_conflict'):
            raise HTTPException(409, detail='外部类别身份或标注路径不唯一，请修正目录或拆分 ZIP 后导入')
        if job.get('unreadable_annotation_files') or (job.get('scan_kind') == 'ANNOTATION_INVALID' and not job.get('external_classes')):
            raise HTTPException(409, detail='ZIP 中的外部标注无法核验，请修复标注后重新上传')
        images = self.dependencies.v19_read_scan_images(project_id, job_id)
        if zip_folders.scan_identity(project_id, job_id, job['source_zip_sha256'], images, job) != payload.source_scan_digest:
            raise HTTPException(409, detail='扫描图片清单已变化，无法确认')
        if frozen:
            active = {code for rule in frozen['rules'].values() for code in rule['intended_label_codes']}
            categories = {cat for rule in frozen['rules'].values() for cat in rule['negative_category_ids']}
        else:
            active = {str(row['code']) for row in active_label_options(self.dependencies.project_label_items(self.dependencies.get_project(project_id)))}
            categories = {str(row['id']) for row in NegativePool(self.dependencies.material_store(project_id)).categories() if row.get('enabled')}
        try:
            selected, rules = zip_folders.normalize_rules(images, payload.selected_paths, payload.folder_rules, active, categories)
        except (TypeError, ValueError) as error:
            raise HTTPException(409 if frozen else 422, detail=str(error)) from error
        if frozen and (rules != frozen['rules'] or selected != frozen['selected_paths']
                       or (payload.label_mapping and payload.label_mapping != frozen['label_mapping'])):
            raise HTTPException(409, detail='该任务的文件夹或标签映射已冻结，不能更改')
        return {'scan_digest': payload.source_scan_digest, 'selected_paths': selected, 'rules': rules}

    def _v19_start_import_job_locked(self, project_id: str, job_id: str, payload: V19ImportStartReq):
        job = self.dependencies.v19_read_job(project_id, job_id)
        if job.get("history_hidden"):
            raise HTTPException(status_code=409, detail="该记录已清空历史并释放临时文件，不能重复启动")
        if job.get("cancel_requested"):
            raise HTTPException(status_code=409, detail="该 ZIP 任务正在取消，不能确认标签或启动正式导入")
        folder_plan = None
        if job.get('folder_confirmation_required'):
            folder_plan = self._v19_confirm_folder_rules(project_id, job_id, job, payload)
            if job.get('folder_confirmation') and job.get('status') == 'done':
                return self.v19_public_job(project_id, job)
        elif payload.folder_rules is not None or payload.source_scan_digest:
            raise HTTPException(409, detail='该任务没有文件夹扫描证据')
        if job.get("status") == "running":
            return self.v19_public_job(project_id, job)
        if job.get("status") not in {"selecting", "failed"}:
            raise HTTPException(status_code=400, detail="当前导入任务状态不允许重新开始")

        if job.get("status") == "failed":
            # The legacy ZIP worker committed Material before bounded formal GT.
            # Never restart a partially indexed failed import: re-running it
            # generates new image IDs and silently duplicates source material.
            imported_ids = list(self.dependencies.v19_read_import_report(project_id, job_id, job).get("imported_image_ids") or [])
            materials = self.dependencies.material_store(project_id)
            for offset in range(0, len(imported_ids), 500):
                if materials.get_many(imported_ids[offset:offset + 500]):
                    raise HTTPException(
                        status_code=409,
                        detail="该失败任务已有素材写入正式索引，禁止重复导入；请先完成 Material/Annotation 完整性审计与恢复。",
                    )

        if payload.create_labels:
            raise HTTPException(status_code=409, detail=IMPORT_LABEL_CREATION_BLOCKED_DETAIL)

        classes = list(job.get("external_classes") or [])
        if classes:
            project = self.dependencies.get_project(project_id)
            existing_digest = str(job.get("label_confirmation_digest") or "")
            existing_mapping = {
                str(key): str(value)
                for key, value in dict(job.get("label_mapping") or {}).items()
            }
            if existing_digest:
                requested_mapping = {
                    str(key): str(value)
                    for key, value in dict(payload.label_mapping or {}).items()
                }
                if requested_mapping and requested_mapping != existing_mapping:
                    raise HTTPException(
                        status_code=409,
                        detail="该 ZIP 任务的标签映射已经确认冻结，失败重试不能更换映射",
                    )
                try:
                    resolved, _ = resolve_external_label_mapping(
                        classes,
                        label_mapping=existing_mapping,
                        create_labels=[],
                        labels=self.dependencies.project_label_items(project),
                    )
                except ValueError as error:
                    raise HTTPException(status_code=409, detail=str(error)) from error
                create = []
            else:
                try:
                    resolved, _ = resolve_external_label_mapping(
                        classes,
                        label_mapping=payload.label_mapping,
                        create_labels=[],
                        labels=self.dependencies.project_label_items(project),
                    )
                    create = []
                except ValueError as error:
                    raise HTTPException(status_code=409, detail=str(error)) from error
                confirmation = {
                    "label_mapping": resolved,
                    "create_labels": [],
                    "external_classes": [
                        {"class_id": str(row.get("class_id")), "name": str(row.get("name") or "")}
                        for row in classes
                    ],
                }
                job.update({
                    "label_mapping": resolved,
                    "create_labels": create,
                    "label_confirmation_required": False,
                    "label_confirmed_at": self.dependencies.now_iso(),
                    "label_confirmation_digest": hashlib.sha256(json.dumps(
                        confirmation, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                    ).encode("utf-8")).hexdigest(),
                })
                if folder_plan is None:
                    self.dependencies.v19_write_job(project_id, job)
            self.dependencies.remember_project_label_aliases(project_id, classes, resolved)
        elif payload.label_mapping:
            raise HTTPException(status_code=422, detail="当前 ZIP 没有可确认的外部标注类别")

        # Raw ZIPs default to unclassified import, but an explicit positive/negative
        # upload intent remains optional and must retain its existing association.
        # The classification is never formal GT, even for empty sidecar files.
        if folder_plan is None and (job.get("sample_classification_required") or str(payload.sample_type or "").strip()
                                    or payload.intended_label_codes or payload.negative_category_ids):
            from platform_core.negative_pool import NegativePool
            chosen_type = str(
                payload.sample_type
                or job.get("upload_sample_type")
                or ("unclassified" if job.get("scan_kind") == "RAW_UNANNOTATED" else "")
            ).strip()
            frozen_type = str(job.get("upload_sample_type") or "")
            if chosen_type not in {"positive", "negative", "unclassified"}:
                raise HTTPException(status_code=422, detail="请选择原图暂存、正样本标签或负样本分类")
            if chosen_type == "unclassified" and job.get("scan_kind") != "RAW_UNANNOTATED":
                raise HTTPException(status_code=422, detail="仅未标注原图可跳过正负样本分类")
            if frozen_type and chosen_type != frozen_type:
                raise HTTPException(status_code=409, detail="本次 ZIP 的正负样本选择已冻结，不能在失败重试时改变")
            codes = sorted(set(str(v).strip() for v in (payload.intended_label_codes or job.get("upload_intended_label_codes") or []) if str(v).strip()))
            categories = sorted(set(str(v).strip() for v in (payload.negative_category_ids or job.get("upload_negative_category_ids") or []) if str(v).strip()))
            if chosen_type == "unclassified":
                if codes or categories:
                    raise HTTPException(status_code=422, detail="原图暂存不得隐式指定正负样本或正式标签")
            elif chosen_type == "positive":
                active = {str(item.get("code") or "") for item in active_label_options(self.dependencies.project_label_items(self.dependencies.get_project(project_id)))}
                if not codes or any(code not in active for code in codes) or categories:
                    raise HTTPException(status_code=422, detail="正样本须选择至少一个有效目标标签，不能选择负样本分类")
            else:
                valid = {str(row['id']) for row in NegativePool(self.dependencies.material_store(project_id)).categories() if row.get('enabled')}
                if not categories or any(code not in valid for code in categories) or codes:
                    raise HTTPException(status_code=422, detail="负样本须选择至少一个有效分类，不能选择目标标签")
            if frozen_type and (codes != sorted(job.get("upload_intended_label_codes") or [])
                                or categories != sorted(job.get("upload_negative_category_ids") or [])):
                raise HTTPException(status_code=409, detail="本次 ZIP 样本选择已冻结，失败重试不能更改")
            job.update(upload_sample_type=chosen_type, upload_intended_label_codes=codes,
                       upload_negative_category_ids=categories)

        target_algorithm = str(job.get('upload_algorithm_id') or payload.algorithm_id or '')
        if target_algorithm:
            if payload.algorithm_id and payload.algorithm_id != target_algorithm:
                raise HTTPException(409, detail='ZIP 目标算法已冻结，不能在重试时切换')
            if not any(str(row.get('id')) == target_algorithm for row in self.dependencies.list_algorithms_internal(project_id)):
                raise HTTPException(422, detail='目标算法已不存在')
            if job.get('upload_sample_type') != 'negative':
                raise HTTPException(422, detail='负样本池上传必须确认负样本类型及分类')
            job['upload_algorithm_id'] = target_algorithm

        selected_paths = payload.selected_paths or []
        if folder_plan is not None:
            selected_paths = folder_plan['selected_paths']
            if not job.get('folder_confirmation'):
                folder_plan.update(label_mapping=dict(job.get('label_mapping') or {}),
                                   source_zip_sha256=job['source_zip_sha256'], project_id=project_id, job_id=job_id)
                job['folder_confirmation'] = folder_plan
                job['folder_confirmation_digest'] = zip_folders.digest(folder_plan)
        elif selected_paths:
            allowed = {x.get("path") for x in self.dependencies.v19_read_scan_images(project_id, job_id)}
            selected_paths = [x for x in selected_paths if x in allowed]
            if not selected_paths:
                raise HTTPException(status_code=400, detail="没有选择有效图片")
        import threading
        highest_sequence = max(
            (int(self.dependencies.read_json(filename, {}).get("enqueue_sequence") or 0)
             for filename in self.dependencies.v19_import_jobs_dir(project_id).glob("*/job.json")),
            default=0,
        )
        job.update(
            enqueued_at=self.dependencies.now_iso(), enqueue_sequence=highest_sequence + 1,
            status="running",
            stage="等待项目导入资源",
            progress=48,
            phase="QUEUE", phase_completed=0, phase_total=1, phase_unit="step",
            phase_progress=0, phase_elapsed_seconds=0, eta_seconds=None,
            selected_count=len(selected_paths) or job.get("image_count", 0),
            message="标签确认已冻结，正在等待项目级导入锁",
        )
        self.dependencies.v19_write_job(project_id, job, allow_restart=True)
        th = threading.Thread(
            target=self.dependencies.v19_import_worker,
            args=(project_id, job.get("dataset_id") or "default", job_id, selected_paths),
            daemon=True,
        )
        th.start()
        return self.v19_public_job(project_id, self.dependencies.v19_read_job(project_id, job_id))

    def _v19_hide_terminal_job(self, project_id: str, job_id: str):
        self.dependencies.get_project(project_id)
        with self.dependencies._v19_stop_fence(project_id, job_id):
            job = self.dependencies.v19_read_job(project_id, job_id)
            if str(job.get("status") or "").lower() not in {"done", "failed", "cancelled", "canceled"}:
                raise HTTPException(status_code=409, detail="任务正在执行或等待确认，不能直接删除；如需终止，请使用正式取消流程。")
            try:
                cleanup = self.dependencies._v19_cleanup_uncommitted_job(project_id, job_id, preserve_report=True)
            except Exception as error:
                self._v19_job_diagnostic(project_id, job_id, error, operation="history_cleanup", job=job)
                raise HTTPException(status_code=503, detail="临时文件清理失败，任务记录与导入证据已保留，可安全重试") from error
            # Preserve the original task and bounded report: UI history dismissal
            # must never erase evidence or unlink the shared stop fence.
            job.update(project_id=project_id, batch_id=job.get("batch_id") or job_id,
                       history_hidden=True, history_hidden_at=self.dependencies.now_iso(),
                       temporary_cleanup=cleanup)
            self.dependencies.v19_write_job(project_id, job)
            # Keep history addressable by the original project+job ID, but outside
            # normal */job.json discovery. Leave the existing stop-lock inode in
            # place so concurrent waiters can never acquire a second lock.
            archive = self.dependencies.v19_import_jobs_dir(project_id) / ".history" / job_id
            try:
                archive.mkdir(parents=True, exist_ok=True)
                source_report = self.dependencies.v19_job_dir(project_id, job_id) / "report.json"
                if source_report.is_file():
                    os.replace(source_report, archive / "report.json")
                source_job = self.dependencies.v19_job_dir(project_id, job_id) / "job.json"
                if source_job.is_file():
                    os.replace(source_job, archive / "job.json")
            except OSError as error:
                self._v19_job_diagnostic(project_id, job_id, error, operation="history_archive", job=job)
                raise HTTPException(status_code=503, detail="历史归档未完成，证据仍保留；请按同一任务 ID 重试清理") from error
            return {"ok": True, "id": job_id, "history_hidden": True,
                    "evidence_retained": True, "cleanup": cleanup}

    def _v19_zip_class_sample(self, project_id: str, job_id: str, class_id: str, index: int) -> Dict[str, Any]:
        self.dependencies.get_project(project_id)
        job = self.dependencies.v19_read_job(project_id, job_id)
        if str(job.get("status") or "").lower() != "selecting":
            raise HTTPException(status_code=409, detail="仅待确认的 ZIP 导入任务可查看原始标签样本")
        if str(class_id) not in {str(row.get("class_id")) for row in job.get("external_classes", [])}:
            raise HTTPException(status_code=404, detail="外部标签不存在")
        samples = self.dependencies.v19_read_class_samples(project_id, job_id).get(str(class_id), [])
        if index < 0 or index >= len(samples):
            raise HTTPException(status_code=404, detail="该标签没有可预览的样本")
        return dict(samples[index])

    def _v55_enrich_upload_batch(self, project_id: str, batch: Dict[str, Any]) -> Dict[str, Any]:
        image_ids = list(dict.fromkeys(
            str(item.get('image_id') or '')
            for item in (batch.get('items') or [])
            if str(item.get('image_id') or '')
        ))
        images: Dict[str, Dict[str, Any]] = {}
        materials = self.dependencies.material_store(project_id)
        for offset in range(0, len(image_ids), 500):
            for image in materials.get_many(image_ids[offset:offset + 500]):
                image_id = str(image.get('id') or '')
                if image_id:
                    images[image_id] = dict(image)
        enriched = dict(batch)
        enriched['items'] = []
        for stored_item in batch.get('items', []):
            item = dict(stored_item)
            image = images.get(str(item.get('image_id')))
            item['image'] = image
            item['missing'] = image is None
            enriched['items'].append(item)
        enriched['clean_task_id'] = batch.get('clean_task_id')
        return enriched

    def _v55_upload_clean_task_id(self,
        project_id: str,
        batch_id: str,
        image_ids: List[str],
    ) -> str:
        identity = json.dumps(
            [str(project_id), str(batch_id), [str(image_id) for image_id in image_ids]],
            ensure_ascii=False,
            separators=(',', ':'),
        )
        return hashlib.sha256(identity.encode('utf-8')).hexdigest()[:12]
