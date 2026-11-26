"""Domain orchestration over the existing persistence, worker and receipt owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from fastapi import Body, Query, Request, HTTPException
from pydantic import BaseModel
from .ai_annotation_contracts import AnnotationComparisonReq, AnnotationDecisionReq, AnnotationDraftBatchReq, AnnotationDraftReq, AnnotationSelectionMembershipReq, AnnotationTaskCreateReq, AnnotationTransferReq, BulkFormalIntentReq

import json
import hashlib
import re
import time
import uuid
import sqlite3
from contextlib import nullcontext
from heapq import nsmallest
from itertools import islice
from pathlib import Path
from fastapi.responses import JSONResponse
from filelock import FileLock, Timeout
from platform_core.algorithms import list_algorithms as list_algorithm_assets
from platform_core.annotation_candidates import CandidateDecision, CandidateStore
from platform_core.annotation_task_service import sync_annotation_statistics
from platform_core.annotation_runtime import prepare_request as prepare_annotation_request
from platform_core.errors import PlatformError
from platform_core.labels import active_label_options, label_governance_fence, normalize_label_aliases
from platform_core.material_repository import material_annotation_lifecycle_fence
from platform_core.task_runtime import TaskKind, TaskRecord, TaskStatus, WorkerInstanceService, task_to_public


class PermanentTransferConflict(ValueError):
    """This frozen transfer cannot apply to the changed source or GT identity."""


@dataclass(frozen=True)
class AiAnnotationDependencies:
    DATA_DIR: Callable[..., Any]
    _annotation_search_worker_errors: Callable[..., Any]
    _annotation_search_worker_lock: Callable[..., Any]
    _material_governance_actor: Callable[..., Any]
    _negative_pool_training_usage: Callable[..., Any]
    _review_training_negative: Callable[..., Any]
    _start_annotation_search_backfill: Callable[..., Any]
    _start_annotation_statistics_backfill: Callable[..., Any]
    _storage_source_fence: Callable[..., Any]
    _v35_model_items: Callable[..., Any]
    _v35_prompt_items: Callable[..., Any]
    _v50_annotation_repository: Callable[..., Any]
    get_project: Callable[..., Any]
    material_store: Callable[..., Any]
    now_iso: Callable[..., Any]
    project_dir: Callable[..., Any]
    project_label_items: Callable[..., Any]
    public_material: Callable[..., Any]
    read_annotation: Callable[..., Any]
    read_annotations_many: Callable[..., Any]
    shared_task_artifacts: Callable[..., Any]
    shared_task_repository: Callable[..., Any]
    v19_read_import_report: Callable[..., Any]
    v19_read_job: Callable[..., Any]


class AiAnnotationService:
    def __init__(self, dependencies: AiAnnotationDependencies):
        self.dependencies = dependencies

    def _persist_annotation_task_create(self,
        project_id: str, payload: AnnotationTaskCreateReq, task_id: str, *, identity: str = "",
    ):
        request, provider_key = self._annotation_create_payload(project_id, payload)
        if identity:
            request["create_request_identity"] = identity
        with self.dependencies._storage_source_fence():
            self.dependencies.shared_task_artifacts().atomic_write_json(task_id, "request.json", request)
            return self.dependencies.shared_task_repository().create(TaskRecord.new(
                task_id, project_id, TaskKind.AI_ANNOTATION, "request.json",
                f"vision:{provider_key}", priority=50,
                required_capabilities=("vision_provider",),
            ))

    def create_annotation_task(self, project_id: str, payload: AnnotationTaskCreateReq):
        request_id = str(payload.request_id or "").strip()
        if not request_id:
            record = self._persist_annotation_task_create(project_id, payload, uuid.uuid4().hex[:12])
            return JSONResponse(status_code=202, content=self.public_annotation_task(record))

        task_id = self._annotation_create_id(project_id, request_id)
        identity = self._annotation_create_identity(payload)
        self.dependencies.get_project(project_id)
        locks = self.dependencies.DATA_DIR() / "task_runtime" / "annotation_create_locks"
        locks.mkdir(parents=True, exist_ok=True)
        try:
            with FileLock(str(locks / f"{task_id}.lock"), timeout=30):
                repository = self.dependencies.shared_task_repository()
                existing = repository.get(task_id)
                if existing is not None:
                    if existing.project_id != project_id or existing.kind is not TaskKind.AI_ANNOTATION:
                        raise HTTPException(status_code=409, detail="AI 标注创建请求身份冲突")
                    frozen = self.dependencies.shared_task_artifacts().read_json(task_id, "request.json", default={})
                    if frozen.get("create_request_identity") != identity:
                        raise HTTPException(status_code=409, detail="创建请求 ID 已绑定不同配置，请重新确认配置")
                    return JSONResponse(status_code=202, content={**self.public_annotation_task(existing), "idempotent": True})

                # A stranded artifact is not proof that the durable queue accepted
                # the task. Do not silently overwrite it on a retry.
                if self.dependencies.shared_task_artifacts().artifact_path(task_id, "request.json").exists():
                    raise HTTPException(status_code=409, detail="创建请求存在未完成的准备记录，请核查原任务")
                record = self._persist_annotation_task_create(project_id, payload, task_id, identity=identity)
                return JSONResponse(status_code=202, content=self.public_annotation_task(record))
        except Timeout as error:
            raise HTTPException(status_code=409, detail="同一 AI 标注请求仍在创建，请按原请求 ID 查询结果") from error

    def _annotation_create_id(self, project_id: str, request_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{12,80}", request_id):
            raise HTTPException(status_code=422, detail="AI 标注创建请求 ID 格式不正确")
        return "ai" + hashlib.sha256(f"annotation-create\x00{project_id}\x00{request_id}".encode("utf-8")).hexdigest()[:20]

    def _annotation_create_identity(self, payload: AnnotationTaskCreateReq) -> str:
        body = payload.model_dump(mode="json", exclude={"request_id"})
        for field in ("review_revision", "expected_remaining"):
            if body.get(field) is None:
                body.pop(field, None)
        # New optional create fields must not change old request_id receipts.
        if body.get("review_scope_policy") == "task_uniform_legacy":
            body.pop("review_scope_policy", None)
        for field in ("expected_material_revision", "expected_annotation_revision"):
            if body.get(field) is None:
                body.pop(field, None)
        if body.get("source_batch_id") is None:
            body.pop("source_batch_id", None)
        return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def get_annotation_task_by_create_request(self, project_id: str, request_id: str):
        self.dependencies.get_project(project_id)
        task_id = self._annotation_create_id(project_id, request_id)
        task = self.dependencies.shared_task_repository().get(task_id)
        if task is None or task.project_id != project_id or task.kind is not TaskKind.AI_ANNOTATION:
            raise HTTPException(status_code=404, detail="尚未找到该 AI 标注创建请求的任务回执")
        return self.public_annotation_task(task)

    def freeze_annotation_selection(self, project_id: str, payload: BaseModel):
        self.dependencies.get_project(project_id)
        from platform_core.training_selection_reference import freeze_selection, read_selection
        repository = self.dependencies.material_store(project_id)
        revision = repository.current_revision()
        context = {"project_id": project_id, "purpose": "ai_annotation"}
        try:
            ids = set(read_selection(self.dependencies.DATA_DIR(), payload.previous_ref, context)) if payload.previous_ref else set()
            ids.difference_update(payload.excluded_image_ids)
            ids.update(payload.image_ids)
            cursor = None
            while True:
                page = repository.iter_filtered_ids({"query": payload.query,"labels":payload.labels, "annotation_state": payload.annotation_state,"partial_labels":[row["code"] for row in self._annotation_label_catalog(self.dependencies.get_project(project_id))] if payload.annotation_state=="partial" else ()}, cursor=cursor, limit=1000, include_total=cursor is None)
                if page.total > 200000:
                    raise ValueError("单任务最多200000张，请缩小筛选范围；未截断选择")
                ids.update(page.items)
                if len(ids) > 200000:
                    raise ValueError("合并选择超过200000张；未截断选择")
                cursor = page.next_cursor
                if not cursor:
                    break
            if repository.current_revision() != revision:
                raise ValueError("素材库发生更新，请重新冻结选择")
            result = freeze_selection(self.dependencies.DATA_DIR(), context, sorted(ids), request_scope="ai_annotation")
            return {**result, "repository_revision": revision,"state_counts":repository.selected_annotation_counts(sorted(ids), [row["code"] for row in self._annotation_label_catalog(self.dependencies.get_project(project_id))])}
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    def annotation_selection_summary(self, project_id: str, payload: BaseModel):
        self.dependencies.get_project(project_id)
        from platform_core.training_selection_reference import read_selection
        try:
            ids = set(read_selection(self.dependencies.DATA_DIR(), payload.previous_ref, {"project_id":project_id,"purpose":"ai_annotation"})) if payload.previous_ref else set()
            ids.difference_update(payload.excluded_image_ids)
            ids.update(payload.image_ids)
            if not ids or len(ids)>200000:
                raise ValueError("选择为空或超过200000张")
            repository=self.dependencies.material_store(project_id)
            revision=repository.current_revision()
            counts=repository.selected_annotation_counts(sorted(ids),[row["code"] for row in self._annotation_label_catalog(self.dependencies.get_project(project_id))])
            if sum(counts.values())!=len(ids) or revision!=repository.current_revision():
                raise ValueError("选择素材已变化，请刷新核验")
            return {"count":len(ids),"state_counts":counts,"repository_revision":revision}
        except ValueError as error:
            raise HTTPException(status_code=409,detail=str(error)) from error

    def annotation_selection_membership(self, project_id: str, payload: AnnotationSelectionMembershipReq):
        self.dependencies.get_project(project_id)
        from platform_core.training_selection_reference import selection_membership
        try:
            return {"items": selection_membership(self.dependencies.DATA_DIR(), payload.selection_ref, {"project_id":project_id,"purpose":"ai_annotation"}, payload.image_ids)}
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    def compare_annotation_preview(self, project_id: str, payload: AnnotationComparisonReq):
        self.dependencies.get_project(project_id)
        from platform_core.annotation_comparison import compare_boxes
        try:
            return compare_boxes(payload.baseline, payload.predictions, complete=payload.complete, threshold=payload.threshold,image_width=payload.image_width)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    def preview_annotation_image(self, project_id: str, payload: AnnotationTaskCreateReq):
        'Explicit one-image model dry run; never create a task, candidate or GT.\n\n    Reuse the same frozen model, prompt, label contract and inference adapter as\n    AI_ANNOTATION. A preview is deliberately bounded and opt-in because the\n    configured provider may be remote and may charge for each inference.\n    '
        if len(payload.image_ids) != 1 or not str(payload.image_ids[0]).strip():
            raise HTTPException(status_code=422, detail="试跑预览每次只能选择一张真实素材")
        self.dependencies.get_project(project_id)
        image_id = str(payload.image_ids[0]).strip()
        rows = self.dependencies.material_store(project_id).get_many([image_id])
        if len(rows) != 1 or str(rows[0].get("id") or "") != image_id:
            raise HTTPException(status_code=409, detail="试跑素材已变化或不存在，请重新选择")
        # Reject known oversized sources before OSS materialization. Check local
        # size again below because metadata is not a trust boundary.
        max_bytes = 16 * 1024 * 1024
        if int(rows[0].get("size_bytes") or 0) > max_bytes:
            raise HTTPException(status_code=413, detail="试跑图片超过 16 MiB，请换一张素材")
        request, _provider_key = self._annotation_create_payload(project_id, payload)
        from platform_core.annotation_runtime import prepare_request
        from platform_core.annotation_task_service import annotate_one, load_task_images

        try:
            runtime = prepare_request(self.dependencies.DATA_DIR(), project_id, request, runtime=True)
            image = load_task_images(project_id, [image_id])[0]
            path = Path(str(image.get("path") or ""))
            if path.stat().st_size > max_bytes:
                raise HTTPException(status_code=413, detail="试跑图片超过 16 MiB，请换一张素材")
            result = annotate_one(runtime, image)
        except HTTPException:
            raise
        except (FileNotFoundError, OSError) as error:
            raise HTTPException(status_code=409, detail="试跑素材暂不可读取，请核查存储源后重试") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)[:300]) from error
        except Exception as error:
            # Provider errors can contain upstream headers; do not echo credentials
            # or third-party response bodies into a browser error message.
            raise HTTPException(status_code=502, detail="AI 模型试跑失败，请检查模型配置与连接状态后重试") from error
        return {
            "image": {
                "id": image_id,
                "filename": str(image.get("filename") or image_id),
                "url": str(image.get("url") or ""),
                "width": int(image.get("width") or 0),
                "height": int(image.get("height") or 0),
            },
            "boxes": result["boxes"],
            "latency_ms": result["latency_ms"],
            "model": result["model"],
            "provider": result["provider"],
            "preview_only": True,
            "diagnostics": result.get("diagnostics", {}),
            "baseline": self.dependencies.read_annotation(project_id, image_id),
        }

    def _require_annotation_review_task(self, project_id: str, task_id: str):
        self.dependencies.get_project(project_id)
        task = self.dependencies.shared_task_repository().get(task_id)
        if task and task.project_id == project_id:
            if task.kind is TaskKind.AI_ANNOTATION:
                return task
            if task.kind is TaskKind.MATERIAL_BATCH:
                request = self.dependencies.shared_task_artifacts().read_json(task_id, task.payload_ref, default={})
                if request.get("operation") == "AI_ANNOTATE":
                    return task
        raise HTTPException(status_code=404, detail="AI annotation task not found")

    def get_annotation_task(self, project_id: str, task_id: str, reader_view: bool = False):
        task = self._require_annotation_review_task(project_id, task_id)
        summary = self._annotation_summary(task)
        if summary and task.kind is TaskKind.AI_ANNOTATION:
            summary = sync_annotation_statistics(
                self.dependencies.shared_task_repository(), task,
                CandidateStore(self.dependencies.shared_task_artifacts(), task_id=task.task_id),
            )
        result = self.public_annotation_task(task, summary=summary, include_review_policy=reader_view)
        if task.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED}:
            generation = self.dependencies.shared_task_artifacts().read_json(task_id, "generation.json", default={})
            if isinstance(generation, dict):
                if generation.get("stopped_reason") and generation["stopped_reason"] != "CANCEL_REQUESTED":
                    result["generation_interruption_code"] = str(generation["stopped_reason"])[:100]
                if isinstance(generation.get("failure_codes"), list):
                    result["generation_failure_codes"] = generation["failure_codes"][:5]
                if isinstance(generation.get("execution"), dict):
                    result["generation_execution"] = generation["execution"]
        if reader_view:
            from platform_core.annotation_reader_views import task_display
            return {"ok":True,"project_id":project_id,"task":task_display(result)}
        return result

    def audit_annotation_task_gt(self, project_id: str, task_id: str,
                                 limit: int = 50, cursor: Optional[str] = None):
        """Explicit, bounded read-only comparison; never infer a whole-task GT total."""
        from platform_core.annotation_gt_audit import audit_gt_commit

        task = self._require_annotation_review_task(project_id, task_id)
        store = CandidateStore(self.dependencies.shared_task_artifacts(), task_id=task.task_id)
        try:
            page = store.read_commit_page(cursor=cursor, limit=limit)
        except FileNotFoundError as error:
            raise HTTPException(status_code=409, detail="任务尚无可核验的候选提交记录") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        ids = [str(row["image_id"]) for row in page.items]
        candidates = store.get_many(ids) if ids else {}
        formal = self.dependencies.read_annotations_many(project_id, ids) if ids else {}
        items = [
            audit_gt_commit(task_id, row, candidates.get(row["image_id"]), formal.get(row["image_id"]))
            for row in page.items
        ]
        states = {state: sum(item["state"] == state for item in items) for state in (
            "same_revision", "retained", "partially_retained", "not_retained",
            "retained_unquantified", "revision_changed_unverifiable", "unverifiable",
        )}
        return {
            "items": items,
            "next_cursor": page.next_cursor,
            "historical_total": page.total,
            "page_counts": states,
            "scope": "page_only",
            "notice": "只核验本页历史提交图；旧记录、空框负样本无版本证据时不能证明当前 GT 归属。",
        }

    def annotation_material_states(self, project_id: str, image_ids: str = ""):
        self.dependencies.get_project(project_id)
        requested = list(dict.fromkeys(
            value.strip() for value in str(image_ids or "").split(",") if value.strip()
        ))
        if len(requested) > 100:
            raise HTTPException(status_code=422, detail="单次最多查询 100 张素材的 AI 标注状态")
        if not requested:
            return {"items": []}

        repository = self.dependencies.shared_task_repository()
        page = repository.list(
            project_id=project_id,
            kinds={TaskKind.AI_ANNOTATION, TaskKind.MATERIAL_BATCH},
            statuses={
                TaskStatus.AWAITING_CONFIRMATION,
                TaskStatus.QUEUED,
                TaskStatus.RUNNING,
                TaskStatus.CANCEL_REQUESTED,
            },
            limit=100,
        )
        ranks = {"candidate_failed": 1, "awaiting_confirmation": 2, "committing": 3}
        projected: Dict[str, Dict[str, Any]] = {}
        for task in page.items:
            if task.kind is TaskKind.MATERIAL_BATCH:
                batch_request = self.dependencies.shared_task_artifacts().read_json(
                    task.task_id, task.payload_ref, default={},
                )
                if str((batch_request or {}).get("operation") or "") != "AI_ANNOTATE":
                    continue
            phase = str(task.stage or "").upper()
            if task.status is TaskStatus.AWAITING_CONFIRMATION:
                public_state = "awaiting_confirmation"
            elif (
                phase in {"REVIEW_QUEUED", "APPLYING_REVIEW"}
                and task.status in {
                    TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED,
                }
            ):
                public_state = "committing"
            else:
                continue
            if not task.result_ref:
                continue

            store = CandidateStore(self.dependencies.shared_task_artifacts(), task_id=task.task_id)
            try:
                rows = store.get_many(requested)
            except (FileNotFoundError, ValueError):
                continue
            for image_id, item in rows.items():
                candidate_status = str(item.get("status") or "")
                if candidate_status == "failed":
                    state = "candidate_failed"
                elif candidate_status not in {"success", "empty"}:
                    continue
                elif public_state == "committing":
                    if item.get("accepted") is not True:
                        continue
                    state = "committing"
                else:
                    state = "awaiting_confirmation"

                current = projected.get(image_id)
                if current and ranks.get(str(current.get("state")), 0) >= ranks[state]:
                    continue
                projected[image_id] = {
                    "image_id": image_id,
                    "state": state,
                    "task_id": task.task_id,
                }
        return {"items": [projected[key] for key in requested if key in projected]}

    def get_annotation_candidates(self,
        project_id: str, task_id: str, limit: int = 50, cursor: Optional[str] = None,
        filter: str = "all", reader_view: bool = False, selection_id: Optional[str] = None,
        request: Request = None,
    ):
        task = self._require_annotation_review_task(project_id, task_id)
        if reader_view and filter != "failed":
            raise HTTPException(422, detail="只读诊断仅支持失败图片分页")
        if not task.result_ref and not self.dependencies.shared_task_artifacts().artifact_path(task_id, "candidates/manifest.json").is_file():
            response = {"items": [], "next_cursor": None, "total": 0, "summary": {},
                    "review_revision": 0, "task": self.public_annotation_task(task),
                    "task_error": {"stage": str(task.stage or "generation"),
                                   "message": str(task.error or "任务尚未生成候选结果，可检查任务状态后重试"),
                                   "code": "CANDIDATES_NOT_GENERATED"}}
            if reader_view:
                from platform_core.annotation_reader_views import failure_page
                return failure_page(project_id,task_id,response)
            return response
        store = CandidateStore(self.dependencies.shared_task_artifacts(), task_id=task.task_id)
        try:
            page = store.read_page(
                cursor=cursor,
                limit=max(1, min(100, int(limit))), filter=filter,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        items = [{key: value for key, value in item.items() if key != "diagnostics"} for item in page.items]
        missing_ids = list(dict.fromkeys(
            str(item.get("image_id") or "")
            for item in items
            if str(item.get("image_id") or "")
            and any(item.get(field) in (None, "") for field in ("url", "filename", "width", "height"))
        ))
        materials = {
            str(row.get("id") or ""): self.dependencies.public_material(project_id, row)
            for row in self.dependencies.material_store(project_id).get_many(missing_ids)
        } if missing_ids else {}
        for item in items:
            material = materials.get(str(item.get("image_id") or ""))
            if not material:
                continue
            for field in ("url", "filename", "width", "height"):
                if item.get(field) in (None, "") and material.get(field) not in (None, ""):
                    item[field] = material[field]
        # Worker freezes this display-only scope in CandidateStore item_json.
        # Do not parse the potentially 21k-image task request on every page GET.
        response = {"items": items, "next_cursor": page.next_cursor, "total": page.total,
                    "summary": {**store.summary(), **store.review_counts()}, "review_revision": store.review_revision(),
                    **({"review_scope_policy": "per_image_required"}
                       if any(item.get("review_scope_policy") == "per_image_required" for item in items) else {})}
        if selection_id and not reader_view:
            actor = self.dependencies._material_governance_actor(request, project_id)['actor_id']
            try:
                selection = self._load_annotation_review_selection(
                    store, project_id, task_id, selection_id, actor, response["review_revision"],
                )
            except HTTPException as error:
                if error.status_code != 409:
                    raise
                response["selection_stale"] = True
            else:
                selected = set(selection['image_ids'])
                for item in items:
                    item["selection_member"] = item["image_id"] in selected
        if cursor in {None, "", "0"}:
            response["label_summary"] = store.label_summary()
        if reader_view:
            from platform_core.annotation_reader_views import failure_page
            return failure_page(project_id,task_id,response)
        return response

    def get_annotation_candidate(self, project_id: str, task_id: str, image_id: str):
        self._require_annotation_review_task(project_id,task_id)
        store=CandidateStore(self.dependencies.shared_task_artifacts(),task_id=task_id)
        try:
            item=store.get(image_id)
        except FileNotFoundError:
            item=None
        if not item:
            raise HTTPException(404,detail='候选图片不存在')
        return {'item':{key:value for key,value in item.items() if key!='diagnostics'},'review_revision':store.review_revision()}

    def save_annotation_review_draft(self, project_id: str, task_id: str, image_id: str, payload: AnnotationDraftReq, request: Request):
        from platform_core.annotations import normalize_boxes
        task = self._require_annotation_review_task(project_id, task_id)
        actor = self.dependencies._material_governance_actor(request, project_id)['actor_id']
        self._annotation_review_operation_path(payload.request_id)
        with FileLock(str(self.dependencies.shared_task_artifacts().artifact_path(task_id, "review.lock")), timeout=30), material_annotation_lifecycle_fence(self.dependencies.project_dir(project_id)):
            task = self._require_annotation_review_task(project_id, task_id)
            if task.status is not TaskStatus.AWAITING_CONFIRMATION:
                raise HTTPException(409, detail="任务当前不可编辑，请先恢复已完成候选审核")
            store = CandidateStore(self.dependencies.shared_task_artifacts(), task_id=task_id)
            item = store.get(image_id)
            material = self.dependencies.material_store(project_id).get(image_id)
            if not item or not material:
                raise HTTPException(404, detail="候选或源素材不存在")
            digest = str(material.get('content_sha256') or '')
            frozen_digest = str(item.get('source_content_sha256') or item.get('content_sha256') or '')
            if (material.get('source_available') is False or material.get('_dataset_delete_claim')
                    or material.get('_material_batch_delete_claim')
                    or (frozen_digest and digest != frozen_digest)
                    or (payload.source_content_sha256 and digest != payload.source_content_sha256)):
                raise HTTPException(409, detail="源素材已变化或不可用，请重新核对")
            labels = {row['code']: row['class_id'] for row in self._annotation_label_catalog(self.dependencies.get_project(project_id))}
            try:
                stable_boxes=[{**box, "id":str(box.get("id") or hashlib.sha256(f"{payload.request_id}:{index}".encode()).hexdigest()[:20])} for index,box in enumerate(payload.boxes)]
                boxes = normalize_boxes(stable_boxes, int(material.get('width') or item.get('width') or 0),
                                        int(material.get('height') or item.get('height') or 0), labels)
                saved = store.save_draft(image_id, boxes, expected_revision=payload.revision,
                                         actor=actor, request_id=payload.request_id, automatic=payload.auto_resolution)
            except (ValueError, KeyError) as error:
                raise HTTPException(409 if 'revision' in str(error).lower() else 422, detail=str(error)) from error
            return {**saved, 'item':store.get(image_id), 'review_revision':store.review_revision(), 'summary':{**store.summary(), **store.review_counts()}, 'label_summary':store.label_summary()}

    def save_annotation_review_drafts_batch(self,
        project_id: str, task_id: str, payload: AnnotationDraftBatchReq, request: Request,
    ):
        """Batch transport only: reuse the original one-image lock, source and CAS contract."""
        self._require_annotation_review_task(project_id, task_id)
        image_ids = [str(row.image_id) for row in payload.items]
        if len(set(image_ids)) != len(image_ids):
            raise HTTPException(422, detail="同一次批量草稿不能包含重复图片")
        results = []
        for entry in payload.items:
            try:
                draft = AnnotationDraftReq(
                    boxes=entry.boxes, revision=entry.revision, request_id=entry.request_id,
                    source_content_sha256=entry.source_content_sha256,
                    auto_resolution=entry.auto_resolution,
                )
                saved = self.save_annotation_review_draft(project_id, task_id, entry.image_id, draft, request)
                results.append({
                    "image_id": entry.image_id, "ok": True, "revision": saved["revision"],
                    "review_revision": saved["review_revision"], "item": saved["item"],
                })
            except HTTPException as error:
                results.append({
                    "image_id": entry.image_id, "ok": False,
                    "error": error.detail, "status_code": error.status_code,
                })
        return {"items": results, "total": len(results), "saved": sum(row["ok"] for row in results)}

    def create_annotation_review_selection(self, project_id: str, task_id: str, payload: BaseModel, request: Request):
        self._require_annotation_review_task(project_id, task_id)
        actor = self.dependencies._material_governance_actor(request, project_id)['actor_id']
        artifacts = self.dependencies.shared_task_artifacts()
        with FileLock(str(artifacts.artifact_path(task_id, 'review.lock')), timeout=30):
            store = CandidateStore(artifacts, task_id=task_id)
            revision = store.review_revision()
            if payload.review_revision is not None and payload.review_revision != revision:
                raise HTTPException(409, detail='审核范围已变化，请刷新后重新选择')
            try:
                counts = store.selection_counts(payload.filter, payload.purpose)
                ids = list(islice(store.iter_selected_ids(filter=payload.filter, purpose=payload.purpose), 50001))
            except ValueError as error:
                raise HTTPException(422, detail=str(error)) from error
            if len(ids) > 50000:
                raise HTTPException(422, detail='筛选范围超过50000张，请缩小筛选')
            if payload.purpose == 'transfer':
                ids, metrics = self._annotation_transfer_eligible_selection(project_id, store, ids)
                if metrics['conflicts']:
                    counts['reasons']['formal_or_source_conflict'] = metrics['conflicts']
            else:
                annotations = self.dependencies._v50_annotation_repository(project_id)
                durable = set()
                for offset in range(0, len(ids), 200):
                    durable.update(annotations.candidate_committed_ids(task_id, ids[offset:offset + 200]))
                if durable:
                    ids = [image_id for image_id in ids if image_id not in durable]
                    counts['reasons']['committed'] = counts['reasons'].get('committed', 0) + len(durable)
            identity = uuid.uuid4().hex
            artifacts.atomic_write_json(task_id, f'review/selections/{identity}.json', {
                'selection_id': identity, 'project_id': project_id, 'task_id': task_id,
                'image_ids': ids, 'filter': payload.filter, 'purpose': payload.purpose,
                'revision': revision, 'actor': actor, 'expires_at': time.time() + 3600,
            })
            return {
                'selection_id': identity, 'total': len(ids), 'count': len(ids),
                'filtered_total': counts['total'], 'excluded': counts['total'] - len(ids), 'reasons': counts['reasons'],
                'filter': payload.filter, 'purpose': payload.purpose, 'review_revision': revision,
            }

    def _load_annotation_review_selection(self, store, project_id, task_id, selection_id, actor, revision):
        if not re.fullmatch(r'[a-f0-9]{32}', selection_id):
            raise HTTPException(422, detail='筛选快照编号无效')
        selection = store.artifacts.read_json(task_id, f'review/selections/{selection_id}.json', default=None)
        if (not isinstance(selection, dict) or selection.get('actor') != actor
                or selection.get('project_id') != project_id or selection.get('task_id') != task_id
                or selection.get('selection_id') != selection_id):
            raise HTTPException(404, detail='筛选快照不存在或无访问权限')
        if selection.get('revision') != revision or float(selection.get('expires_at') or 0) <= time.time():
            raise HTTPException(409, detail='筛选快照已变化或过期，请重新选择')
        ids = selection.get('image_ids')
        if not isinstance(ids, list) or len(ids) > 50000:
            raise HTTPException(409, detail='筛选快照数据无效，请重新选择')
        return selection

    def accept_bulk_formal_intent(self, project_id: str, task_id: str, payload: BulkFormalIntentReq, request: Request):
        from platform_core.annotation_bulk_intents import accept_intent

        actor = self.dependencies._material_governance_actor(request, project_id)["actor_id"]
        task = self._require_annotation_review_task(project_id, task_id)
        return accept_intent(self.dependencies.shared_task_artifacts(), actor, task, payload)

    def read_bulk_formal_intent(self, project_id: str, task_id: str, request_id: str, request: Request):
        from platform_core.annotation_bulk_intents import read_intent

        actor = self.dependencies._material_governance_actor(request, project_id)["actor_id"]
        self._require_annotation_review_task(project_id, task_id)
        return read_intent(self.dependencies.shared_task_artifacts(), actor, project_id, task_id, request_id)

    def _bulk_formal_execution_view(self, project_id, task_id, request_id, actor):
        from platform_core.annotation_bulk_execution import (
            execution_task_id, load_binding, progress_view,
        )
        from platform_core.annotation_bulk_intents import _intent_identity, read_sealed_pointer

        artifacts = self.dependencies.shared_task_artifacts()
        pointer = read_sealed_pointer(artifacts, _intent_identity(actor, project_id, task_id, request_id))
        execution_id = execution_task_id(pointer["operation_id"])
        snapshot = self.dependencies.shared_task_repository().formal_bulk_execution_snapshot(execution_id)
        if snapshot is None:
            raise HTTPException(404, detail={'code': 'FORMAL_BULK_EXECUTION_NOT_FOUND',
                                             'message': '后台正式入库任务尚未建立'})
        record, cancelled, ledger = snapshot
        if record.project_id != project_id:
            raise HTTPException(404, detail={'code': 'FORMAL_BULK_EXECUTION_NOT_FOUND',
                                             'message': '后台正式入库任务尚未建立'})
        try:
            binding = load_binding(artifacts, execution_id, project_id, record.payload_ref)
        except (OSError, ValueError) as error:
            raise HTTPException(503, detail='后台正式入库任务的持久证据无法核验') from error
        if (binding["original_task_id"] != task_id or binding["request_id"] != request_id
                or binding["actor"] != actor or binding["operation_id"] != pointer["operation_id"]
                or binding["manifest_ref"] != pointer["manifest_ref"]):
            raise HTTPException(404, detail={'code': 'FORMAL_BULK_EXECUTION_NOT_FOUND',
                                             'message': '后台正式入库任务尚未建立'})
        return progress_view(record, binding, ledger, cancellation_requested=cancelled)

    def execute_bulk_formal_intent(self, project_id: str, task_id: str, request_id: str, request: Request):
        """Register the single execution task; never write GT inside this request."""
        from platform_core.annotation_bulk_execution import start_execution

        actor = self.dependencies._material_governance_actor(request, project_id)['actor_id']
        task = self._require_annotation_review_task(project_id, task_id)
        if task.status is not TaskStatus.AWAITING_CONFIRMATION:
            raise HTTPException(409, detail='任务当前不可批量入库')
        start_execution(self.dependencies.shared_task_artifacts(), self.dependencies.shared_task_repository(), actor, project_id, task_id, request_id)
        return self._bulk_formal_execution_view(project_id, task_id, request_id, actor)

    def read_bulk_formal_execution(self, project_id: str, task_id: str, request_id: str, request: Request):
        actor = self.dependencies._material_governance_actor(request, project_id)['actor_id']
        self._require_annotation_review_task(project_id, task_id)
        return self._bulk_formal_execution_view(project_id, task_id, request_id, actor)

    def cancel_bulk_formal_execution(self, project_id: str, task_id: str, request_id: str, request: Request):
        actor = self.dependencies._material_governance_actor(request, project_id)['actor_id']
        self._require_annotation_review_task(project_id, task_id)
        view = self._bulk_formal_execution_view(project_id, task_id, request_id, actor)
        if view['status'] in {'CANCELLED', 'SUCCEEDED', 'PARTIAL_SUCCESS', 'FAILED'}:
            return view
        self.dependencies.shared_task_repository().request_cancel(view['execution_task_id'])
        return self._bulk_formal_execution_view(project_id, task_id, request_id, actor)

    def recover_bulk_formal_execution(self, project_id: str, task_id: str, request_id: str, request: Request):
        """Re-verify persisted facts, then requeue a durable evidence block."""
        from platform_core.annotation_bulk_execution import resume_blocked_execution

        actor = self.dependencies._material_governance_actor(request, project_id)['actor_id']
        self._require_annotation_review_task(project_id, task_id)
        resume_blocked_execution(self.dependencies.shared_task_artifacts(), self.dependencies.shared_task_repository(),
                                 actor, project_id, task_id, request_id)
        return self._bulk_formal_execution_view(project_id, task_id, request_id, actor)

    def get_annotation_review_selection_candidates(self,
        project_id: str, task_id: str, selection_id: str, request: Request,
        cursor: int = 0, limit: int = 100, *, ambiguity_revision: int | None = None,
    ):
        """Bounded read of the already frozen selection; no second cache or GT write."""
        self._require_annotation_review_task(project_id, task_id)
        if cursor < 0 or limit < 1 or limit > 200:
            raise HTTPException(422, detail='筛选分页参数无效')
        actor = self.dependencies._material_governance_actor(request, project_id)['actor_id']
        store = CandidateStore(self.dependencies.shared_task_artifacts(), task_id=task_id)
        revision = store.review_revision()
        selection = self._load_annotation_review_selection(
            store, project_id, task_id, selection_id, actor, revision if ambiguity_revision is None else ambiguity_revision,
        )
        if ambiguity_revision is not None and selection.get('purpose') != 'ambiguity':
            raise HTTPException(409, detail='候选快照用途不允许按原消歧范围读取')
        ids = selection['image_ids']
        batch = ids[cursor:cursor + limit]
        entries = store.get_many(batch)
        if len(entries) != len(batch):
            raise HTTPException(409, detail='部分候选图片已变化，请重新选择')
        next_cursor = cursor + len(batch)
        return {
            'items': [
                {key: value for key, value in entries[str(image_id)].items() if key != 'diagnostics'}
                for image_id in batch
            ],
            'total': len(ids), 'next_cursor': str(next_cursor) if next_cursor < len(ids) else None,
            'review_revision': revision, 'selection_revision': selection['revision'], 'filter': selection.get('filter') or 'all',
        }

    def _annotation_transfer_ids(self, store, project_id, task_id, payload, actor, revision):
        if payload.review_revision is not None and payload.review_revision != revision:
            raise HTTPException(409, detail={'code': 'REVIEW_REVISION_CONFLICT',
                                             'message': '候选范围已变化，请重新确认', 'review_revision': revision})
        ids = list(dict.fromkeys(payload.image_ids))
        if not payload.selection_id:
            return ids
        if ids:
            raise HTTPException(422, detail='不能同时提交显式图片和筛选快照')
        selection = self._load_annotation_review_selection(store, project_id, task_id, payload.selection_id, actor, revision)
        if selection.get('purpose') == 'ambiguity':
            raise HTTPException(422, detail='消歧选择不能用于转池，请重新选择')
        excluded = set(payload.excluded_image_ids)
        if not excluded.issubset(selection['image_ids']):
            raise HTTPException(422, detail='排除范围不属于筛选快照')
        return [image_id for image_id in selection['image_ids'] if image_id not in excluded]

    def _annotation_transfer_ineligibility(self, item, material, formal, *, operation_id=None):
        if not item or item.get('status') not in {'success', 'empty'} or not material:
            return '候选不可审核或素材不存在'
        if item.get('gt_committed') or formal.get('boxes'):
            return '已有正式GT，必须在正式标注流程显式处理冲突'
        if (item.get('review_state', 'active') != 'active'
                and (not operation_id or item.get('review_operation_id') != operation_id)):
            return '图片已被其他转移操作占用或不可审核'
        source_hash = item.get('source_content_sha256') or item.get('content_sha256')
        if (material.get('source_available') is False or material.get('_dataset_delete_claim')
                or material.get('_material_batch_delete_claim')
                or (source_hash and source_hash != material.get('content_sha256'))):
            return '源素材已变化或不可用，请重新审核'
        return None

    def _annotation_transfer_eligible_selection(self, project_id, store, ids):
        eligible = []
        metrics = {'with_boxes': 0, 'zero': 0, 'discarded_boxes': 0}
        ineligible_reasons = {}
        materials = self.dependencies.material_store(project_id)
        for offset in range(0, len(ids), 200):
            part = ids[offset:offset + 200]
            candidates = store.get_many(part)
            formal = self.dependencies.read_annotations_many(project_id, part)
            durable = self.dependencies._v50_annotation_repository(project_id).candidate_committed_ids(store.task_id, part)
            rows = {str(row['id']): row for row in materials.get_many(part)}
            for image_id in part:
                item = candidates.get(image_id)
                boxes = (item or {}).get('boxes') or []
                metrics['with_boxes'] += int(bool(boxes))
                metrics['zero'] += int(not boxes and (item or {}).get('status') in {'success', 'empty'})
                metrics['discarded_boxes'] += len(boxes)
                reason = ('已有正式GT，必须在正式标注流程显式处理冲突' if image_id in durable
                          else self._annotation_transfer_ineligibility(item, rows.get(image_id), formal.get(image_id) or {}))
                if reason:
                    ineligible_reasons[reason] = ineligible_reasons.get(reason, 0) + 1
                else:
                    eligible.append(image_id)
        return eligible, {**metrics, 'conflicts': len(ids) - len(eligible), 'ineligible_reasons': ineligible_reasons}

    def _annotation_transfer_identity(self, payload):
        body = payload.model_dump(mode='json', exclude={'review_revision'})
        return body, hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()

    def _annotation_transfer_preview_path(self, request_id):
        return self._annotation_review_operation_path(request_id).replace('review/operations/', 'review/transfer-previews/')

    def _load_annotation_transfer(self, artifacts, task_id, path, store):
        """Migrate old JSON progress once; keep its original bytes as audit evidence."""
        receipt=artifacts.read_json(task_id,path,default=None)
        if isinstance(receipt,dict) and isinstance(receipt.get('items'),dict):
            entries=list(receipt['items'].items())
            for offset in range(0,len(entries),200):
                store.write_transfer_receipts(receipt['request_id'],dict(entries[offset:offset+200]),preserve_existing=True)
            archive=path.replace('review/transfers/','review/transfers-legacy/')
            if not artifacts.artifact_path(task_id,archive).is_file():
                artifacts.atomic_write_json(task_id,archive,receipt)
            receipt={key:value for key,value in receipt.items() if key!='items'}
            receipt['receipt_storage']='candidate_sqlite_v1';receipt['legacy_audit_ref']=archive
            artifacts.atomic_write_json(task_id,path,receipt)
        return receipt

    def transfer_annotation_candidates(self, project_id: str, task_id: str, payload: AnnotationTransferReq, request: Request):
        from platform_core.negative_pool import MemberOperationConflict, NegativePool
        task = self._require_annotation_review_task(project_id, task_id)
        actor = self.dependencies._material_governance_actor(request, project_id)['actor_id']
        artifacts = self.dependencies.shared_task_artifacts()
        path = self._annotation_review_operation_path(payload.request_id).replace('review/operations/', 'review/transfers/')
        body, identity = self._annotation_transfer_identity(payload)
        with FileLock(str(artifacts.artifact_path(task_id, 'review.lock')), timeout=30):
            task = self._require_annotation_review_task(project_id, task_id)
            store = CandidateStore(artifacts, task_id=task_id)
            receipt = self._load_annotation_transfer(artifacts, task_id, path, store)
            if receipt:
                if task.status is not TaskStatus.AWAITING_CONFIRMATION and receipt.get('status') != 'completed':
                    raise HTTPException(409,detail='任务已离开审核阶段，不能继续转移')
                if (receipt['identity'] != identity or receipt['actor'] != actor
                        or ('requested_revision' in receipt and receipt['requested_revision'] != payload.review_revision)):
                    raise HTTPException(409, detail='同一操作编号的范围、操作者或审核修订不一致')
                if receipt.get('status') in {'undone','undo_pending'} or (receipt.get('undo') or {}).get('status') == 'pending':
                    raise HTTPException(409, detail='该转移已撤销或正在撤销，请核验原操作')
                if receipt.get('status') == 'completed':
                    return {'request_id':payload.request_id,'status':'completed','succeeded':len(receipt['image_ids']),
                            'failed':0,'conflicts':0,'total':len(receipt['image_ids']),
                            'items':list(store.read_transfer_receipts(payload.request_id).values()),'idempotent':True,
                            'summary':{**store.summary(),**store.review_counts()},'review_revision':store.review_revision(),
                            'label_summary':store.label_summary()}
            else:
                if task.status is not TaskStatus.AWAITING_CONFIRMATION:
                    raise HTTPException(409, detail='任务当前不可转池，请先恢复审核')
                revision = store.review_revision()
                ids = self._annotation_transfer_ids(store, project_id, task_id, payload, actor, revision)
                preview = artifacts.read_json(task_id, self._annotation_transfer_preview_path(payload.request_id), default=None)
                intent = {'actor': actor, 'identity': identity, 'revision': revision}
                if preview is not None and preview != intent:
                    raise HTTPException(409, detail='转移范围、操作者或审核修订已变化，请重新预检')
                if not ids:
                    raise HTTPException(422, detail='请选择图片')
                if payload.algorithm_id and not any(str(row.get('id')) == payload.algorithm_id for row in list_algorithm_assets(self.dependencies.project_dir(project_id)/'algorithms.json')):
                    raise HTTPException(422, detail='算法不存在')
                if payload.confirm_absent and not payload.algorithm_id:
                    raise HTTPException(422, detail='确认无目标必须指定算法范围')
                receipt = {'identity':identity,'actor':actor,'request_id':payload.request_id,'image_ids':ids,
                           'receipt_storage':'candidate_sqlite_v1','pool_revision_base':NegativePool(self.dependencies.material_store(project_id)).revision(),
                           'body':body,'requested_revision':payload.review_revision,'status':'pending','created_at':self.dependencies.now_iso()}
                artifacts.atomic_write_json(task_id, path, receipt)
            # At most 200 images per call. Reposting the same identity continues the
            # original durable receipt; a lost reply never creates a second transfer.
            # Complete one bounded pass over the frozen set before any failed item
            # is retried. Otherwise a fully failed first page starves later pages.
            statuses=store.transfer_receipt_statuses(payload.request_id)
            pending = [value for value in receipt['image_ids'] if value not in statuses][:200]
            if not pending:
                permanent = store.permanent_transfer_conflicts(payload.request_id)
                pending = [value for value in receipt['image_ids']
                           if statuses.get(value) != 'transferred' and value not in permanent][:200]
            batch_receipts=store.read_transfer_receipts(payload.request_id,image_ids=pending)
            pool = NegativePool(self.dependencies.material_store(project_id))
            project_path = self.dependencies.project_dir(project_id)
            for image_id in pending:
                try:
                    # Formal absence saves acquire label governance before Material lifecycle.
                    label_fence = label_governance_fence(project_path) if payload.confirm_absent else nullcontext()
                    with label_fence, material_annotation_lifecycle_fence(project_path):
                        item = store.get(image_id)
                        material = self.dependencies.material_store(project_id).get(image_id)
                        formal = self.dependencies.read_annotation(project_id, image_id)
                        reason = self._annotation_transfer_ineligibility(item, material, formal, operation_id=payload.request_id)
                        if reason:
                            source = (item or {}).get('source_content_sha256') or (item or {}).get('content_sha256')
                            if (item or {}).get('gt_committed') or formal.get('boxes') or (
                                material and source and source != material.get('content_sha256')
                            ):
                                raise PermanentTransferConflict(reason)
                            raise ValueError(reason)
                        if self.dependencies._v50_annotation_repository(project_id).candidate_committed_ids(task_id, [image_id]):
                            raise PermanentTransferConflict('已有正式GT提交凭据，请先核验原入库操作')
                        existing = batch_receipts.get(image_id) or {}
                        intent = existing.get('pool_intent')
                        pool_before = pool.member_snapshot(image_id)
                        if 'pool_before' in existing and not intent and pool_before != existing['pool_before']:
                            raise PermanentTransferConflict('旧转移记录缺少池提交凭据，请显式核对成员冲突')
                        if 'pool_before' not in existing:
                            existing = {**existing, 'status': 'pending',
                                        'filename': material.get('filename') or item.get('filename') or image_id,
                                        'pool_before': pool_before, 'annotation_version': int(formal.get('version') or 0)}
                        source_sha256 = str(material.get('content_sha256') or '')
                        pool_identity = {
                            'project_id': project_id, 'task_id': task_id, 'actor': actor,
                            'request_id': payload.request_id, 'image_id': image_id, 'action': 'add',
                            'algorithm_id': payload.algorithm_id, 'category_ids': sorted(set(payload.category_ids)),
                            'confirm_absent': payload.confirm_absent, 'annotation_version': existing['annotation_version'],
                            'source_sha256': source_sha256,
                        }
                        operation_id = hashlib.sha256(json.dumps(pool_identity, sort_keys=True).encode()).hexdigest()
                        if intent is None:
                            intent = {**pool_identity, 'operation_id': operation_id, 'expected_revision': pool.revision()}
                        elif intent.get('operation_id') != operation_id:
                            raise PermanentTransferConflict('原转移意图或素材身份已变化，请核对冲突')
                        if not payload.confirm_absent and int(formal.get('version') or 0) != existing['annotation_version']:
                            raise PermanentTransferConflict('正式GT已发生变化，请核对转移冲突')
                        existing = {**existing, 'pool_intent': intent}
                        batch_receipts[image_id] = existing
                        # Write-ahead evidence plus exclusion precede pool mutation.
                        store.write_transfer_receipts(payload.request_id,{image_id:existing})
                        if item.get('review_state', 'active') == 'active':
                            store.set_review_exclusion(
                                image_id, 'pending_transfer', operation_id=payload.request_id, actor=actor,
                                details={'algorithm_id': payload.algorithm_id, 'category_ids': payload.category_ids,
                                         'confirm_absent': payload.confirm_absent},
                            )
                        operation_scope = dict(project_id=project_id, algorithm_id=payload.algorithm_id,
                                               operation_kind='negative_pool.ai_transfer.v1')
                        if payload.confirm_absent and not existing.get('annotation_after'):
                            if (pool.revision() != intent['expected_revision']
                                    and not pool.member_operation(operation_id, **operation_scope)):
                                raise MemberOperationConflict('负样本池修订已变化，请核对后再确认无目标')
                            frozen = artifacts.read_json(task_id, task.payload_ref, default={})
                            codes = list(frozen.get('labels') or [])
                            algorithm = next(row for row in list_algorithm_assets(self.dependencies.project_dir(project_id)/'algorithms.json') if str(row.get('id')) == payload.algorithm_id)
                            from platform_core.training_label_tasks import resolve_training_label_contract
                            contract=resolve_training_label_contract(self.dependencies.DATA_DIR(), self.dependencies.project_dir(project_id),
                                {'train_labels':codes,'framework':'ultralytics'}, algorithm,
                                require_positive_evidence=False, include_base_weight_digest=False)
                            if set(contract['effective_label_codes']) != set(codes):
                                raise ValueError('任务标签必须覆盖完整算法范围，请重新核查')
                            self.dependencies._review_training_negative(project_id, {'image_id':image_id,
                                'expected_version':existing['annotation_version'], 'source_content_sha256':material.get('content_sha256')}, codes, {'actor_id':actor})
                            formal = self.dependencies.read_annotation(project_id, image_id)
                            existing = {**existing, 'annotation_after': {
                                'version': formal.get('version'), 'content_digest': formal.get('content_digest'),
                            }}
                            batch_receipts[image_id] = existing
                            store.write_transfer_receipts(payload.request_id, {image_id: existing})
                        after = existing.get('annotation_after')
                        if after and any(formal.get(key) != value for key, value in after.items()):
                            raise PermanentTransferConflict('确认无目标的正式GT已变化，请核对转移冲突')
                        try:
                            pool_receipt = pool.members(
                                [image_id], category_ids=payload.category_ids,
                                expected_revision=intent['expected_revision'], operation_id=operation_id, **operation_scope,
                            )
                        except ValueError as error:
                            # A rejected transaction has no durable side effect. A saved
                            # receipt or revision conflict must retain the exact intent.
                            if (not isinstance(error, MemberOperationConflict)
                                    and not pool.member_operation(operation_id, **operation_scope)):
                                existing = {**existing, 'pool_intent': None}
                                batch_receipts[image_id] = existing
                            raise
                        transferred = {**existing, 'image_id': image_id, 'status': 'transferred', 'at': self.dependencies.now_iso(),
                                       'pool_operation_revision': pool_receipt['negative_pool_revision']}
                        transferred.pop('error', None)
                        store.set_review_exclusion(image_id, 'transferred', operation_id=payload.request_id, actor=actor,
                                                   details={'algorithm_id':payload.algorithm_id,'category_ids':payload.category_ids,'confirm_absent':payload.confirm_absent},
                                                   transfer_receipt=transferred)
                        batch_receipts[image_id] = transferred
                except (ValueError, HTTPException, PlatformError, OSError, sqlite3.Error) as error:
                    message = str(error.detail if isinstance(error, HTTPException) else error)
                    batch_receipts[image_id] = {**batch_receipts.get(image_id,{}),'image_id':image_id,'status':'failed','error':message,
                                                'permanent_conflict':isinstance(error, PermanentTransferConflict)}
                    failed_item = store.get(image_id)
                    if (failed_item and failed_item.get('status') in {'success','empty'}
                            and not failed_item.get('gt_committed') and failed_item.get('review_state') in {'active', 'pending_transfer'}
                            and failed_item.get('review_operation_id') in {None, '', payload.request_id}):
                        store.set_review_exclusion(image_id, 'blocked', operation_id=payload.request_id, actor=actor, details={'error':message})
                    store.write_transfer_receipts(payload.request_id, {image_id: batch_receipts[image_id]})
            counts=store.transfer_receipt_counts(payload.request_id)
            succeeded = counts.get('transferred',0)
            failed = counts.get('failed',0)
            receipt['pool_revision'] = pool.revision()
            receipt['status'] = 'completed' if succeeded == len(receipt['image_ids']) else 'partial' if succeeded + failed == len(receipt['image_ids']) else 'pending'
            artifacts.atomic_write_json(task_id, path, receipt)
            return {'request_id':payload.request_id,'status':receipt['status'],'succeeded':succeeded,'failed':failed,
                    'conflicts':failed,'total':len(receipt['image_ids']), 'items':list(batch_receipts.values())[-200:],
                    'summary':{**store.summary(), **store.review_counts()},'review_revision':store.review_revision(),'label_summary':store.label_summary()}

    def list_annotation_transfers(self, project_id: str, task_id: str, request: Request, cursor: str, limit: int):
        self._require_annotation_review_task(project_id, task_id)
        actor = self.dependencies._material_governance_actor(request, project_id)['actor_id']
        if cursor and not re.fullmatch(r'[a-f0-9]{64}', cursor):
            raise HTTPException(422, detail='转池记录游标无效')
        artifacts = self.dependencies.shared_task_artifacts()
        directory = artifacts.artifact_path(task_id, 'review/transfers')
        if not directory.is_dir():
            return {'items': [], 'next_cursor': None}
        # Bound receipt deserializations even when many records belong to other operators.
        names = nsmallest(limit + 1, (path.stem for path in directory.iterdir()
                                      if path.suffix == '.json' and re.fullmatch(r'[a-f0-9]{64}', path.stem)
                                      and path.stem > cursor))
        items = []
        for name in names[:limit]:
            receipt = artifacts.read_json(task_id, f'review/transfers/{name}.json', default=None)
            if not isinstance(receipt, dict) or receipt.get('actor') != actor or not receipt.get('request_id'):
                continue
            items.append({key: receipt.get(key) for key in ('request_id', 'status', 'created_at')})
        return {'items': items, 'next_cursor': names[limit - 1] if len(names) > limit else None}

    def get_annotation_transfer(self, project_id: str, task_id: str, request_id: str, offset: int = Query(default=0, ge=0, le=50000), limit: int = Query(default=100, ge=1, le=200), *, request: Request | None = None):
        self._require_annotation_review_task(project_id,task_id)
        path=self._annotation_review_operation_path(request_id).replace('review/operations/','review/transfers/')
        artifacts=self.dependencies.shared_task_artifacts();receipt=artifacts.read_json(task_id,path,default=None)
        if not receipt:raise HTTPException(404,detail='转移记录不存在')
        if request is not None and receipt.get('actor') != self.dependencies._material_governance_actor(request, project_id)['actor_id']:
            raise HTTPException(404, detail='转移记录不存在')
        offset=max(0,offset);limit=max(1,min(200,limit))
        if isinstance(receipt.get('items'),dict):
            all_items=list(receipt['items'].values());items=all_items[offset:offset+limit];total=len(all_items)
            counts = {status: sum(row.get('status') == status for row in all_items) for status in ('transferred', 'failed', 'pending', 'undone')}
            permanent = sum(row.get('status') == 'failed' and row.get('permanent_conflict') is True for row in all_items)
        else:
            store=CandidateStore(artifacts,task_id=task_id)
            items=list(store.read_transfer_receipts(request_id,offset=offset,limit=limit).values())
            counts=store.transfer_receipt_counts(request_id)
            total=counts['total']
            permanent=len(store.permanent_transfer_conflicts(request_id))
        return {**{key:value for key,value in receipt.items() if key not in {'identity','body','items','image_ids'}},
                'status':'undo_pending' if (receipt.get('undo') or {}).get('status') == 'pending' else receipt.get('status'),
                'items':items,'total':len(receipt['image_ids']),'processed':total,
                'failed':counts.get('failed', 0), 'transferred':counts.get('transferred', 0), 'permanent_conflicts':permanent,
                'pending':len(receipt['image_ids'])-total+counts.get('pending', 0),
                'target':{key:receipt.get('body',{}).get(key) for key in ('algorithm_id','category_ids','confirm_absent')},
                'next_cursor':str(offset+len(items)) if offset+len(items)<total else None}

    def undo_annotation_transfer(self, project_id: str, task_id: str, request_id: str, request: Request, *, own: bool = False):
        from platform_core.negative_pool import NegativePool
        actor=self.dependencies._material_governance_actor(request,project_id)['actor_id']
        task=self._require_annotation_review_task(project_id,task_id);artifacts=self.dependencies.shared_task_artifacts()
        path=self._annotation_review_operation_path(request_id).replace('review/operations/','review/transfers/')
        with FileLock(str(artifacts.artifact_path(task_id,'review.lock')),timeout=30), material_annotation_lifecycle_fence(self.dependencies.project_dir(project_id)):
            store=CandidateStore(artifacts,task_id=task_id)
            receipt=self._load_annotation_transfer(artifacts,task_id,path,store)
            if not receipt:raise HTTPException(404,detail='转移记录不存在')
            if own and receipt.get('actor') != actor:
                raise HTTPException(404, detail='转移记录不存在')
            if receipt.get('status')=='undone':return {'ok':True,'status':'undone','idempotent':True}
            if task.status is not TaskStatus.AWAITING_CONFIRMATION or receipt.get('body',{}).get('confirm_absent'):
                raise HTTPException(409,detail='任务已提交或已产生正式人工负样本证据，请走正式冲突处理流程')
            pool=NegativePool(self.dependencies.material_store(project_id));undo=receipt.get('undo')
            counts=store.transfer_receipt_counts(request_id)
            if not undo:
                base=receipt.get('pool_revision_base')
                # One successful members transaction increments the canonical pool
                # revision once. Any other mutation during transfer is a conflict,
                # including changes between batches, not just after completion.
                if base is None or int(receipt.get('pool_revision') or -1)-int(base)!=counts.get('transferred',0):
                    raise HTTPException(409,detail='转移期间负样本池存在其他变更或恢复歧义，请显式核查冲突')
                if pool.revision()!=receipt.get('pool_revision'):
                    raise HTTPException(409,detail='负样本池已变化，请重新核查冲突')
                undo={'status':'pending','before':pool.revision(),'actor':actor}
                receipt['undo']=undo
            pending_ids=undo.get('pending_image_ids')
            rows=store.read_transfer_receipts(request_id,image_ids=pending_ids) if pending_ids else store.read_transfer_receipts(request_id,status='transferred',limit=200)
            materials=self.dependencies.material_store(project_id).get_many(list(rows));formal=self.dependencies.read_annotations_many(project_id,list(rows))
            if any(int((formal.get(key) or {}).get('version') or 0)!=value['annotation_version'] for key,value in rows.items()):
                raise HTTPException(409,detail='正式GT已发生变化，请显式处理冲突后再撤销')
            usage=self.dependencies._negative_pool_training_usage(project_id,materials)
            if any(value.get('state') not in {'unused','unknown',None} for value in usage.values()):
                raise HTTPException(409,detail='已有下游训练使用，请显式处理冲突')
            undo['pending_image_ids']=list(rows)
            artifacts.atomic_write_json(task_id,path,receipt)
            try:
                if rows:
                    pool.restore_members({key:value['pool_before'] for key,value in rows.items()},expected_revision=undo['before'],
                        operation_id=task_id+':undo:'+request_id+':'+hashlib.sha256(','.join(sorted(rows)).encode()).hexdigest())
                    for image_id in rows:
                        store.set_review_exclusion(image_id,'active',operation_id=request_id,actor=receipt['actor'],details={'undone_by':undo['actor']},transfer_receipt={**rows[image_id],'status':'undone'})
            except ValueError as error:raise HTTPException(409,detail=str(error)) from error
            undo.pop('pending_image_ids',None);undo['before']=pool.revision()
            completed=store.transfer_receipt_counts(request_id).get('transferred',0)==0
            receipt['status']='undone' if completed else 'undo_pending';undo['status']='completed' if completed else 'pending'
            artifacts.atomic_write_json(task_id,path,receipt)
            return {'ok':True,'status':'undone' if completed else 'pending','summary':{**store.summary(),**store.review_counts()},
                    'review_revision':store.review_revision(),'label_summary':store.label_summary()}

    def preview_annotation_transfer(self, project_id: str, task_id: str, payload: AnnotationTransferReq, request: Request):
        task = self._require_annotation_review_task(project_id, task_id)
        actor = self.dependencies._material_governance_actor(request, project_id)['actor_id']
        artifacts = self.dependencies.shared_task_artifacts()
        with FileLock(str(artifacts.artifact_path(task_id, 'review.lock')), timeout=30):
            task = self._require_annotation_review_task(project_id, task_id)
            if task.status is not TaskStatus.AWAITING_CONFIRMATION:
                raise HTTPException(409, detail='任务当前不可转池')
            store = CandidateStore(artifacts, task_id=task_id)
            revision = store.review_revision()
            ids = self._annotation_transfer_ids(store, project_id, task_id, payload, actor, revision)
            if not ids:
                raise HTTPException(422, detail='请选择图片')
            _, identity = self._annotation_transfer_identity(payload)
            intent = {'actor': actor, 'identity': identity, 'revision': revision}
            path = self._annotation_transfer_preview_path(payload.request_id)
            prior = artifacts.read_json(task_id, path, default=None)
            if prior is not None and prior != intent:
                raise HTTPException(409, detail='转移范围、操作者或审核修订已变化，请使用新的操作编号')
            eligible, metrics = self._annotation_transfer_eligible_selection(project_id, store, ids)
            result = {**metrics, 'total': len(ids), 'eligible': len(eligible), 'review_revision': revision}
            if revision != store.review_revision():
                raise HTTPException(409, detail='候选范围已变化，请重新预览')
            if prior is None:
                artifacts.atomic_write_json(task_id, path, intent)
            return result

    def get_annotation_candidate_diagnostics(self, project_id: str, task_id: str, image_id: str):
        task = self._require_annotation_review_task(project_id, task_id)
        if not task.result_ref:
            raise HTTPException(status_code=409, detail="任务尚未生成候选结果")
        item = CandidateStore(self.dependencies.shared_task_artifacts(), task_id=task.task_id).get(image_id)
        if not item:
            raise HTTPException(status_code=404, detail="候选图片不存在")
        diagnostics = item.get("diagnostics")
        if diagnostics and diagnostics.get("created_at_epoch") and time.time() - float(diagnostics["created_at_epoch"]) > 30 * 86400:
            return {"image_id": image_id, "diagnostics": None, "status": "DIAGNOSTICS_EXPIRED"}
        return {"image_id": image_id, "diagnostics": diagnostics,
                "status": "available" if diagnostics else "UNVERIFIED_CONTRACT"}

    def decide_annotation_candidates(self, project_id: str, task_id: str, payload: AnnotationDecisionReq, request: Request):
        from filelock import FileLock
        self._require_annotation_review_task(project_id, task_id)
        request_id = str(payload.request_id or "").strip()
        actor = None
        if payload.single_candidate:
            if (not request_id or payload.review_revision is None or len(payload.decisions) != 1
                    or payload.commit or payload.commit_selected or payload.accept_unmentioned or payload.reject_unmentioned
                    or payload.label_mapping or payload.expected_remaining is not None
                    or not payload.decisions[0].image_id or payload.decisions[0].boxes is not None):
                raise HTTPException(422, detail="单图审核仅允许提交一张候选的决定、审核修订及原请求编号")
            actor = self.dependencies._material_governance_actor(request, project_id)["actor_id"]
        if payload.commit_selected:
            ids = [str(item.image_id) for item in payload.decisions]
            if (not request_id or not payload.commit or payload.accept_unmentioned or payload.reject_unmentioned
                    or not 1 <= len(ids) <= 100 or not all(ids) or len(set(ids)) != len(ids)
                    or any(not item.accepted for item in payload.decisions)):
                raise HTTPException(422, detail="部分正式入库必须提供操作编号及 1～100 张唯一且明确通过的候选")
            actor = self.dependencies._material_governance_actor(request, project_id)["actor_id"]
        if request_id:
            self._annotation_review_operation_path(request_id)
        with FileLock(str(self.dependencies.shared_task_artifacts().artifact_path(task_id, "review.lock")), timeout=30):
            if not request_id:
                return self._decide_annotation_candidates(project_id, task_id, payload)
            artifacts = self.dependencies.shared_task_artifacts()
            path = self._annotation_review_operation_path(request_id)
            identity = self._annotation_review_operation_identity(payload)
            previous = artifacts.read_json(task_id, path, default=None)
            if isinstance(previous, dict):
                if ("selected_image_ids" in previous
                        and (not previous.get("actor") or previous["actor"] != actor)):
                    raise HTTPException(404, detail="尚无该审核操作的持久回执")
                if (previous.get("request_id") != request_id
                        or previous.get("project_id") != project_id
                        or previous.get("identity") != identity
                        or ((payload.single_candidate or payload.commit_selected)
                            and (previous.get("actor") != actor or previous.get("task_id") != task_id))):
                    raise HTTPException(status_code=409, detail="同一审核操作编号的提交内容不一致")
                if previous.get("status") == "rejected":
                    raise HTTPException(previous["status_code"], detail=previous["detail"])
                if previous.get("status") == "completed" and isinstance(previous.get("result"), dict):
                    return {**previous["result"], "idempotent": True}
                resolved = self._annotation_review_resolve_receipt(
                    self._require_annotation_review_task(project_id, task_id), previous,
                )
                if resolved != previous:
                    artifacts.atomic_write_json(task_id, path, resolved)
                if resolved.get("status") == "completed":
                    return {**resolved["result"], "idempotent": True}
                if resolved.get("status") == "rejected":
                    raise HTTPException(resolved["status_code"], detail=resolved["detail"])
                # Candidate changes alone cannot prove that a formal batch committed.
                return JSONResponse(status_code=202, content={
                    "status": "pending", "request_id": request_id,
                    "message": "审核结果尚待核验，请查询原操作编号，勿再次提交",
                })
            pending = {
                "request_id": request_id, "project_id": project_id, "task_id": task_id,
                "identity": identity, "status": "pending", "created_at": self.dependencies.now_iso(),
            }
            if payload.commit_selected:
                pending.update(actor=actor, selected_image_ids=ids)
            if payload.single_candidate:
                decision = payload.decisions[0]
                pending.update(actor=actor, single_decision={
                    "image_id": decision.image_id, "accepted": decision.accepted,
                    "review_revision": payload.review_revision,
                })
            artifacts.atomic_write_json(task_id, path, pending)
            try:
                if payload.single_candidate:
                    result = self._decide_single_annotation_candidate(project_id, task_id, decision, pending)
                elif payload.commit_selected:
                    project_path = self.dependencies.project_dir(project_id)
                    with label_governance_fence(project_path), material_annotation_lifecycle_fence(project_path):
                        result = self._decide_annotation_candidates(project_id, task_id, payload)
                else:
                    result = self._decide_annotation_candidates(project_id, task_id, payload)
            except HTTPException as error:
                recovered = self._annotation_review_resolve_receipt(
                    self._require_annotation_review_task(project_id, task_id), pending,
                ) if payload.commit_selected else pending
                result = recovered.get("result")
                if result is None:
                    if payload.commit_selected and recovered.get("status") == "pending":
                        return JSONResponse(status_code=202, content={
                            "status": "pending", "request_id": request_id,
                        })
                    artifacts.atomic_write_json(task_id, path, {
                        **pending, "status": "rejected", "status_code": error.status_code, "detail": error.detail,
                    })
                    raise
            artifacts.atomic_write_json(task_id, path, {**pending, "status": "completed", "result": result})
            return result

    def _annotation_review_operation_path(self, request_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{12,80}", request_id):
            raise HTTPException(status_code=422, detail="审核操作编号格式无效")
        digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
        return f"review/operations/{digest}.json"

    def _annotation_review_operation_identity(self, payload: AnnotationDecisionReq) -> str:
        body = payload.model_dump(mode="json", exclude={"request_id"})
        # Preserve the exact idempotency hash for receipts created before optional
        # per-image scope existed. Only an explicitly present scope changes intent.
        for decision in body.get("decisions") or []:
            if isinstance(decision, dict) and decision.get("review_scope") is None:
                decision.pop("review_scope", None)
        # A false default must not invalidate operation identities from older builds.
        if body.get("commit_selected") is False:
            body.pop("commit_selected", None)
        if body.get("single_candidate") is False:
            body.pop("single_candidate", None)
        canonical = json.dumps(
            body,
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _annotation_review_resolve_receipt(self, task: TaskRecord, receipt: Dict[str, Any]):
        if receipt.get("status") != "pending":
            return receipt
        artifacts = self.dependencies.shared_task_artifacts()
        request_id = str(receipt.get("request_id") or "")
        single = receipt.get("single_decision")
        if "single_decision" in receipt:
            if (receipt.get("project_id") != task.project_id or receipt.get("task_id") != task.task_id
                    or not receipt.get("identity") or not receipt.get("actor")
                    or not isinstance(single, dict) or not single.get("image_id")
                    or type(single.get("accepted")) is not bool or type(single.get("review_revision")) is not int):
                return receipt
            store = CandidateStore(artifacts, task_id=task.task_id)
            evidence = store.single_decision_event(single["image_id"], request_id)
            result = {"ok": True, "status": "completed", "request_id": request_id,
                      "image_id": single["image_id"], "accepted": single["accepted"],
                      "review_revision": single["review_revision"] + 1}
            if evidence != {"identity": receipt["identity"], "actor": receipt["actor"], "result": result}:
                return receipt
            return {**receipt, "status": "completed", "result": result}
        ids = receipt.get("selected_image_ids")
        if ids is not None:
            from platform_core.annotation_task_service import (
                candidate_commit_operation_id, candidate_commit_summary, read_candidate_commit_receipts,
            )
            if (receipt.get("project_id") != task.project_id or receipt.get("task_id") != task.task_id
                    or not 1 <= len(ids) <= 100 or len(set(ids)) != len(ids)):
                return receipt
            operation_id = candidate_commit_operation_id("partial", request_id, receipt["identity"])
            evidence = read_candidate_commit_receipts(task.project_id, task.task_id, operation_id, ids)
            if not evidence:
                # The HTTP selected batch uses one atomic formal write under the
                # same review lock. Zero receipts prove that no formal batch landed.
                return {**receipt, "status": "rejected", "status_code": 409, "detail": {
                    "code": "REVIEW_NOT_COMMITTED", "message": "原操作未写入正式GT，请刷新后重新核对候选",
                }}
            if set(evidence) != set(ids):
                return receipt
            store = CandidateStore(artifacts, task_id=task.task_id)
            journal = store.get_commit_summaries(ids)
            summaries = [candidate_commit_summary(evidence[image_id]) for image_id in ids]
            missing = [summary for summary in summaries if summary["image_id"] not in journal]
            if missing:
                self.dependencies._v50_annotation_repository(task.project_id).repair_candidate_commit_projections(
                    [evidence[summary["image_id"]] for summary in missing],
                )
                store.record_commit_summaries(missing)
            result = self._annotation_selected_commit_response(task, store, {
                "applied_images": len(ids), "applied_image_ids": ids, "completed_image_ids": ids,
                "boxes_added": sum(row["boxes_added"] for row in evidence.values()),
                "image_summaries": [
                    {key: summary.get(key) for key in ("image_id", "box_count", "labels", "annotation_state", "annotation_origin")}
                    for summary in summaries
                ],
                "image_summaries_truncated": False, "commit_journal_ref": "candidates/items.sqlite3",
            })
            return {**receipt, "status": "completed", "result": result}
        if task.status is TaskStatus.AWAITING_CONFIRMATION:
            return receipt
        result = self._annotation_review_recover_task_transition(task, artifacts, request_id)
        return {**receipt, "status": "completed", "result": result} if result is not None else receipt

    def _annotation_review_recover_task_transition(self, task, artifacts, request_id):
        final = artifacts.read_json(task.task_id, "review/result.json", default=None)
        if (isinstance(final, dict) and final.get("review_request_id") == request_id
                and task.status in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS}):
            summary = CandidateStore(artifacts, task_id=task.task_id).summary()
            return {"ok": True, "task": self.public_annotation_task(task, summary=summary), **final}
        confirmation = artifacts.read_json(task.task_id, "review/confirmation.json", default=None)
        if (isinstance(confirmation, dict) and confirmation.get("accepted") is True
                and confirmation.get("review_request_id") == request_id):
            summary = CandidateStore(artifacts, task_id=task.task_id).summary()
            return {
                "ok": True, "queued_for_commit": True,
                "task": self.public_annotation_task(task, summary=summary),
                "review": summary,
                "label_summary": CandidateStore(artifacts, task_id=task.task_id).label_summary(),
            }
        return None

    def get_annotation_review_operation(self, project_id: str, task_id: str, request_id: str, request: Request):
        from filelock import FileLock, Timeout
        task = self._require_annotation_review_task(project_id, task_id)
        path = self._annotation_review_operation_path(request_id)
        receipt = self.dependencies.shared_task_artifacts().read_json(
            task_id, path, default=None,
        )
        def check_access(current):
            if (not isinstance(current, dict) or current.get("request_id") != request_id
                    or current.get("project_id") != project_id):
                raise HTTPException(404, detail="尚无该审核操作的持久回执")
            if "single_decision" in current or "selected_image_ids" in current:
                if current.get("task_id") != task_id:
                    raise HTTPException(404, detail="尚无该审核操作的持久回执")
                # Historical selected receipts can still repair the journal under the
                # review lock. Their original operator cannot be inferred or exposed.
                if "selected_image_ids" in current and not current.get("actor"):
                    return False
                if current.get("actor") != self.dependencies._material_governance_actor(request, project_id)["actor_id"]:
                    raise HTTPException(404, detail="尚无该审核操作的持久回执")
            return True

        visible = check_access(receipt)
        if receipt.get("status") == "pending":
            try:
                with FileLock(str(self.dependencies.shared_task_artifacts().artifact_path(task_id, "review.lock")), timeout=5):
                    receipt = self.dependencies.shared_task_artifacts().read_json(task_id, path, default=None)
                    visible = check_access(receipt)
                    task = self._require_annotation_review_task(project_id, task_id)
                    resolved = self._annotation_review_resolve_receipt(task, receipt)
                    if resolved != receipt:
                        self.dependencies.shared_task_artifacts().atomic_write_json(task_id, path, resolved)
                    receipt = resolved
            except Timeout:
                pass  # The original POST still owns the review lock; expose pending only to its owner.
        if not visible:
            raise HTTPException(404, detail="尚无该审核操作的持久回执")
        if receipt.get("status") == "completed" and isinstance(receipt.get("result"), dict):
            return {"status": "completed", "request_id": request_id, "result": receipt["result"]}
        if receipt.get("status") == "rejected":
            return {"status": "rejected", "request_id": request_id, "detail": receipt["detail"]}
        return JSONResponse(status_code=202, content={
            "status": "pending", "request_id": request_id,
            "task": self.public_annotation_task(task),
            "message": "审核结果尚待核验，请不要重复提交；可查看任务当前状态",
        })

    def _annotation_selected_commit_response(self, task, store, committed):
        summary = sync_annotation_statistics(self.dependencies.shared_task_repository(), task, store)
        return {
            **committed,
            "ok": True, "committed_selected": True, "queued_for_commit": False,
            "task": self.public_annotation_task(task, summary=summary),
            "review": summary, "summary": {**summary, **store.review_counts()},
            "review_revision": store.review_revision(), "label_summary": store.label_summary(),
        }

    def _decide_single_annotation_candidate(self, project_id, task_id, decision, pending):
        task = self._require_annotation_review_task(project_id, task_id)
        if task.status is not TaskStatus.AWAITING_CONFIRMATION:
            raise HTTPException(409, detail="任务当前不可审核")
        project_path = self.dependencies.project_dir(project_id)
        store = CandidateStore(self.dependencies.shared_task_artifacts(), task_id=task_id)
        with label_governance_fence(project_path), material_annotation_lifecycle_fence(project_path):
            if self.dependencies._v50_annotation_repository(project_id).candidate_committed_ids(task_id, [decision.image_id]):
                raise HTTPException(409, detail="已正式入库的图片不可再次审核")
            frozen = store.artifacts.read_json(task_id, task.payload_ref, default={}) or {}
            if task.kind is TaskKind.MATERIAL_BATCH:
                frozen = frozen.get("options") or {}
            policy = frozen.get("review_scope_policy") or "task_uniform_legacy"
            if policy not in {"task_uniform_legacy", "per_image_required"}:
                raise HTTPException(409, detail="任务审核范围策略无效")
            label_ids = {str(row["code"]): int(row["class_id"]) for row in self._annotation_label_catalog(self.dependencies.get_project(project_id))}
            if decision.review_scope is not None:
                manifest = store.artifacts.read_json(task_id, "candidates/manifest.json", default={}) or {}
                allowed = set(frozen.get("labels") or manifest.get("labels") or []) & label_ids.keys()
                if not decision.accepted or not decision.review_scope or not set(decision.review_scope).issubset(allowed):
                    raise HTTPException(400, detail="逐图审核类别不属于本任务有效标签范围")
            if policy == "per_image_required":
                self._check_single_supplement_decision(project_id, decision, frozen)
            try:
                return store.apply_single_decision(
                    decision, expected_revision=pending["single_decision"]["review_revision"],
                    request_id=pending["request_id"], identity=pending["identity"], actor=pending["actor"],
                    label_ids=label_ids,
                )
            except ValueError as error:
                raise HTTPException(409, detail=str(error)) from error

    def _check_single_supplement_decision(self, project_id, decision, frozen):
        image_id = decision.image_id
        maps = [frozen.get(key) for key in (
            "per_image_missing_review_scopes", "per_image_annotation_versions", "per_image_source_hashes",
        )]
        if not all(isinstance(mapping, dict) and image_id in mapping for mapping in maps):
            raise HTTPException(409, detail="逐图补审冻结凭据缺失，禁止提交")
        missing, version, source_hash = (mapping[image_id] for mapping in maps)
        if (not isinstance(missing, list) or not missing or any(not isinstance(code, str) for code in missing)
                or type(version) is not int or not isinstance(source_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", source_hash)):
            raise HTTPException(409, detail="逐图补审冻结凭据无效，禁止提交")
        if decision.accepted and (not decision.review_scope or not set(decision.review_scope).issubset(missing)):
            raise HTTPException(400, detail="请明确选择创建任务时冻结的已审核类别")
        material = self.dependencies.material_store(project_id).get(image_id) or {}
        formal = self.dependencies.read_annotation(project_id, image_id)
        if (int(formal.get("version") or 0) != version
                or str(material.get("content_sha256") or "").strip().lower() != source_hash
                or material.get("source_available") is False
                or material.get("_dataset_delete_claim") or material.get("_material_batch_delete_claim")):
            raise HTTPException(409, detail="逐图补审所依据的正式 GT 或素材已变化，请重新创建任务")

    def _decide_annotation_candidates(self, project_id: str, task_id: str, payload: AnnotationDecisionReq):
        task = self._require_annotation_review_task(project_id, task_id)
        if task.status is not TaskStatus.AWAITING_CONFIRMATION:
            raise HTTPException(status_code=409, detail="任务尚未生成可审核候选结果")
        store = CandidateStore(self.dependencies.shared_task_artifacts(), task_id=task.task_id)
        if payload.review_revision is not None and payload.review_revision != store.review_revision():
            raise HTTPException(409, detail={'code':'REVIEW_REVISION_CONFLICT','message':'审核范围已变化，请重新核对数量', 'review_revision':store.review_revision()})
        if payload.expected_remaining is not None and payload.expected_remaining != store.review_counts()['remaining_reviewable']:
            raise HTTPException(409, detail={'code':'REVIEW_COUNT_CONFLICT','message':'可审核数量已变化，请重新确认','remaining_reviewable':store.review_counts()['remaining_reviewable']})
        frozen = store.artifacts.read_json(task.task_id, task.payload_ref, default={})
        policy = str((frozen or {}).get("review_scope_policy") or "task_uniform_legacy")
        if policy not in {"task_uniform_legacy", "per_image_required"}:
            raise HTTPException(status_code=409, detail="任务审核范围策略无效，请核查冻结任务")
        if policy == "per_image_required" and (payload.accept_unmentioned or payload.reject_unmentioned):
            raise HTTPException(status_code=400, detail="逐图补审禁止自动接受或拒绝未查看的其他分页")
        decisions = [
            CandidateDecision(str(item.image_id), bool(item.accepted), item.boxes, item.review_scope)
            for item in payload.decisions
        ]
        decided_ids = {item.image_id for item in decisions}
        if payload.commit_selected:
            if (not payload.commit or payload.accept_unmentioned or payload.reject_unmentioned
                    or not 1 <= len(decisions) <= 100
                    or len(decided_ids) != len(decisions)
                    or any(not decision.accepted for decision in decisions)):
                raise HTTPException(status_code=422, detail="仅已选正式入库要求 1～100 张唯一且明确通过的候选，禁止更改未选择范围")
            if (store.get_commit_summaries(decided_ids)
                    or self.dependencies._v50_annotation_repository(project_id).candidate_committed_ids(task_id, decided_ids)):
                raise HTTPException(409, detail="已正式入库的图片不可再次提交")
        if payload.reject_unmentioned and payload.accept_unmentioned:
            raise HTTPException(status_code=400, detail="未明确选择的素材不能同时接受和拒绝")

        mapping = {
            str(source).strip(): str(target).strip()
            for source, target in dict(payload.label_mapping or {}).items()
            if str(source).strip() or str(target).strip()
        }
        if any(not source or not target for source, target in mapping.items()):
            raise HTTPException(status_code=400, detail="标签统一映射不能包含空标签")
        catalog = self._annotation_label_catalog(self.dependencies.get_project(project_id))
        label_ids = {str(item["code"]): int(item["class_id"]) for item in catalog}
        source_labels = (
            {str(item["label"]) for item in store.label_summary()}
            if mapping
            else set()
        )
        unknown_sources = sorted(set(mapping) - source_labels)
        unknown_targets = sorted(set(mapping.values()) - set(label_ids))
        if unknown_sources:
            raise HTTPException(status_code=400, detail="标签统一映射包含不存在的候选标签：" + "、".join(unknown_sources))
        if unknown_targets:
            raise HTTPException(status_code=400, detail="标签统一映射目标不在当前有效标签库：" + "、".join(unknown_targets))
        if policy == "per_image_required" or any(item.review_scope is not None for item in decisions):
            from platform_core.annotation_task_service import _canonical_review_scope
            manifest = store.artifacts.read_json(task.task_id, "candidates/manifest.json", default={})
            requested = list((frozen or {}).get("labels") or (manifest or {}).get("labels") or [])
            try:
                available_scope = set(_canonical_review_scope(requested, mapping, label_ids))
            except ValueError as error:
                raise HTTPException(status_code=400, detail="任务审核标签已失效，请重新核对") from error
            frozen_scopes = (frozen or {}).get("per_image_missing_review_scopes")
            frozen_versions = (frozen or {}).get("per_image_annotation_versions")
            frozen_hashes = (frozen or {}).get("per_image_source_hashes")
            if policy == "per_image_required":
                if (not isinstance(frozen_scopes, dict) or not isinstance(frozen_versions, dict)
                        or not isinstance(frozen_hashes, dict)
                        or set(frozen_scopes) != set(frozen_versions) or set(frozen_scopes) != set(frozen_hashes)):
                    raise HTTPException(status_code=409, detail="逐图补审冻结凭据缺失，禁止提交")
            for item in decisions:
                if item.review_scope is None:
                    if policy == "per_image_required" and item.accepted:
                        raise HTTPException(status_code=400, detail="每张接受的素材必须明确提供已审核类别")
                    continue
                values = item.review_scope
                if (not item.accepted or not isinstance(values, list) or not 1 <= len(values) <= 128
                        or any(not isinstance(code, str) or code != code.strip() for code in values)
                        or len(set(values)) != len(values)
                        or not set(values).issubset(available_scope)):
                    raise HTTPException(status_code=400, detail="逐图审核类别不属于本任务有效标签范围")
                if policy == "per_image_required" and (
                        item.image_id not in frozen_scopes
                        or not set(values).issubset(set(frozen_scopes[item.image_id]))):
                    raise HTTPException(status_code=400, detail="逐图确认类别超出了创建时冻结的缺失范围")
            if policy == "per_image_required" and decisions:
                ids = list(dict.fromkeys(item.image_id for item in decisions))
                if len(ids) > 200:
                    raise HTTPException(status_code=400, detail="单次逐图审核最多提交 200 张素材")
                current_annotations = self.dependencies.read_annotations_many(project_id, ids)
                current_materials = {str(row.get("id") or ""): row for row in self.dependencies.material_store(project_id).get_many(ids)}
                for image_id in ids:
                    current_gt = current_annotations.get(image_id) or {}
                    material = current_materials.get(image_id) or {}
                    if (int(current_gt.get("version") or 0) != frozen_versions.get(image_id)
                            or str(material.get("content_sha256") or "").strip().lower() != frozen_hashes.get(image_id)
                            or material.get("source_available") is False
                            or material.get("_dataset_delete_claim") or material.get("_material_batch_delete_claim")):
                        raise HTTPException(status_code=409, detail="逐图补审所依据的正式 GT 或素材已变化，请重新创建任务")
        for decision in decisions:
            for box in decision.boxes or []:
                source = str(box.get("label") or "").strip()
                if not source or (source not in label_ids and source not in mapping):
                    raise HTTPException(
                        status_code=400,
                        detail=f"候选框标签不在当前有效标签库：{source or '(empty)'}",
                    )

        if payload.commit_selected:
            from platform_core.annotation_task_service import (
                commit_candidate_decisions, _canonical_review_scope, candidate_commit_operation_id,
            )
            candidate_request = (
                (frozen or {}).get("options") or {}
                if task.kind is TaskKind.MATERIAL_BATCH else (frozen or {})
            )
            manifest = self.dependencies.shared_task_artifacts().read_json(task_id, "candidates/manifest.json", default={})
            scope_policy = str(candidate_request.get("review_scope_policy") or "task_uniform_legacy")
            if scope_policy not in {"task_uniform_legacy", "per_image_required"}:
                raise HTTPException(status_code=409, detail="冻结审核范围策略无效")
            frozen_versions = candidate_request.get("per_image_annotation_versions") if scope_policy == "per_image_required" else None
            frozen_scopes = candidate_request.get("per_image_missing_review_scopes") if scope_policy == "per_image_required" else None
            frozen_hashes = candidate_request.get("per_image_source_hashes") if scope_policy == "per_image_required" else None
            if scope_policy == "per_image_required" and not all(isinstance(value, dict) for value in (frozen_versions, frozen_scopes, frozen_hashes)):
                raise HTTPException(status_code=409, detail="逐图补审冻结凭据不完整，不能直接入库")
            def persist_selected():
                store.apply_decisions(decisions, allowed_statuses={"success", "empty"})
                store.remap_selected_labels(decided_ids, mapping, label_ids)

            try:
                scope = _canonical_review_scope(
                    candidate_request.get("labels") or (manifest or {}).get("labels") or [],
                    mapping, label_ids,
                )
                committed = commit_candidate_decisions(
                    project_id, task_id, store,
                    overwrite=bool(candidate_request.get("overwrite")),
                    review_scope=scope,
                    require_per_image_scope=scope_policy == "per_image_required",
                    frozen_annotation_versions=frozen_versions,
                    frozen_missing_review_scopes=frozen_scopes,
                    frozen_material_hashes=frozen_hashes,
                    selected_image_ids=[decision.image_id for decision in decisions],
                    selected_candidates=store.preview_selected_decisions(decisions, mapping, label_ids),
                    persist_selected=persist_selected,
                    operation_id=candidate_commit_operation_id(
                        "partial", payload.request_id.strip(), self._annotation_review_operation_identity(payload),
                    ),
                )
            except (ValueError, RuntimeError) as error:
                raise HTTPException(status_code=409, detail="已选正式 GT 提交失败，请核对素材与已入库审计："+str(error)) from error
            return self._annotation_selected_commit_response(task, store, committed)
        try:
            store.apply_decisions(
                decisions,
                allowed_statuses={"success", "empty"},
            )
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail=str(error) if "跨标签" in str(error) else "审核范围包含不存在或生成失败的素材",
            ) from error
        reject_all_without_mapping = (
            bool(payload.reject_unmentioned)
            and not bool(payload.accept_unmentioned)
            and not mapping
            and all(not decision.accepted for decision in decisions)
        )
        if not reject_all_without_mapping:
            try:
                store.remap_labels(mapping, label_ids)
            except ValueError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
        if payload.accept_unmentioned:
            store.decide_unmentioned(True, exclude=decided_ids)
        elif payload.reject_unmentioned:
            store.decide_unmentioned(False, exclude=decided_ids)
        summary = sync_annotation_statistics(self.dependencies.shared_task_repository(), task, store)
        if store.review_counts()["unreviewed_reviewable"] or not payload.commit:
            return {
                "ok": True,
                "task": self.public_annotation_task(task, summary=summary),
                "review": summary, "summary": {**summary,**store.review_counts()}, "review_revision":store.review_revision(),
                "label_summary": store.label_summary(),
            }

        if not summary.get("accepted"):
            result = {
                "applied_images": 0,
                "applied_image_ids": [],
                "boxes_added": 0,
                "review": summary,
                "completed_image_ids": [],
                "image_summaries": [],
                "image_summaries_truncated": False,
            }
            if payload.request_id:
                result["review_request_id"] = payload.request_id
            self.dependencies.shared_task_artifacts().atomic_write_json(task.task_id, "review/result.json", result)
            final_status = TaskStatus.PARTIAL_SUCCESS if summary.get("failed") else TaskStatus.SUCCEEDED
            updated = self.dependencies.shared_task_repository().complete_review(
                task.task_id,
                final_status,
                "review/result.json",
                accepted=False,
            )
            return {"ok": True, "task": self.public_annotation_task(updated, summary=summary), **result}

        confirmation = {
            "accepted": True,
            "confirmed_at": self.dependencies.now_iso(),
            "label_mapping": mapping,
            "review": summary,
        }
        if payload.request_id:
            confirmation["review_request_id"] = payload.request_id
        self.dependencies.shared_task_artifacts().atomic_write_json(
            task.task_id, "review/confirmation.json", confirmation,
        )
        try:
            updated = self.dependencies.shared_task_repository().resume_after_review_confirmation(task.task_id)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {
            "ok": True,
            "queued_for_commit": True,
            "task": self.public_annotation_task(updated, summary=summary),
            "review": summary,
            "label_summary": store.label_summary(),
        }

    def cancel_annotation_task(self, project_id: str, task_id: str):
        self._require_annotation_review_task(project_id, task_id)
        return self.public_annotation_task(self.dependencies.shared_task_repository().request_cancel(task_id))

    def retry_annotation_task(self, project_id: str, task_id: str, retry_payload: Optional[Dict[str, Any]] = Body(default=None)):
        from filelock import FileLock, Timeout

        task = self._require_annotation_review_task(project_id, task_id)
        if task.kind is TaskKind.MATERIAL_BATCH:
            if task.status not in {TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.PARTIAL_SUCCESS,
                                   TaskStatus.BLOCKED_BY_ENVIRONMENT, TaskStatus.BLOCKED_BY_HARDWARE}:
                raise HTTPException(status_code=409, detail="只有未完成的批处理任务可以重试")
            with self.dependencies._storage_source_fence():
                return self.public_annotation_task(self.dependencies.shared_task_repository().retry(task_id))
        try:
            with FileLock(str(self.dependencies.shared_task_artifacts().artifact_path(task_id, "review.lock")), timeout=5):
                # An earlier decision and a resumed generation cannot share ownership.
                task = self._require_annotation_review_task(project_id, task_id)
                if task.kind is not TaskKind.AI_ANNOTATION or task.status not in {
                    TaskStatus.AWAITING_CONFIRMATION, TaskStatus.CANCELLED, TaskStatus.FAILED,
                    TaskStatus.BLOCKED_BY_ENVIRONMENT, TaskStatus.BLOCKED_BY_HARDWARE,
                } or (task.accepted is not None and not (task.status is TaskStatus.CANCELLED and task.accepted is False)):
                    raise HTTPException(status_code=409, detail="仅未审核、尚未完成的 AI 标注任务可以继续生成")
                artifacts = self.dependencies.shared_task_artifacts()
                request = artifacts.read_json(task.task_id, task.payload_ref, default=None)
                if not isinstance(request, dict) or not request.get("image_ids"):
                    raise HTTPException(status_code=409, detail="冻结图片列表已损坏，无法继续执行")
                if artifacts.artifact_path(task_id, "review/confirmation.json").is_file() or artifacts.artifact_path(task_id, "review/result.json").is_file():
                    raise HTTPException(status_code=409, detail="该任务已有正式审核确认，不能重新生成候选框")
                summary = {}
                if artifacts.artifact_path(task_id, "candidates/manifest.json").is_file():
                    summary = CandidateStore(artifacts, task_id=task_id).statistics()
                if summary.get("gt_committed"):
                    raise HTTPException(status_code=409, detail="任务已有人工审核记录，请先处理审核结果，不可覆盖候选框")
                total = len(request["image_ids"])
                if request.get("preview_count"):
                    total = min(total, max(0, int(request["preview_count"])))
                if summary.get("total", 0) >= total and not summary.get("failed"):
                    raise HTTPException(status_code=409, detail="图片已全部识别完成，请直接审核已有候选框")
                selected = (retry_payload or {}).get('image_ids')
                if selected is not None:
                    if not isinstance(selected,list) or not 1 <= len(selected) <= 200 or any(not isinstance(value,str) for value in selected):
                        raise HTTPException(422,detail='单次重试须选择1至200张失败或未处理图片')
                    selected=list(dict.fromkeys(selected))
                    frozen_ids=set(map(str,request['image_ids']))
                    existing=CandidateStore(artifacts,task_id=task_id).get_many(selected) if artifacts.artifact_path(task_id,'candidates/manifest.json').is_file() else {}
                    if any(value not in frozen_ids or (value in existing and existing[value].get('status')!='failed') for value in selected):
                        raise HTTPException(409,detail='只能重试本任务失败或未处理图片，成功候选和草稿保持不变')
                artifacts.atomic_write_json(task_id,'generation/retry-selection.json',{'image_ids':selected,'created_at':self.dependencies.now_iso()})
                with self.dependencies._storage_source_fence():
                    try:
                        resumed = self.dependencies.shared_task_repository().resume_annotation_generation(
                            task_id, generation_progress=70 * summary.get("total", 0) / max(1, total),
                        )
                    except ValueError as error:
                        raise HTTPException(status_code=409, detail=str(error)) from error
                return self.public_annotation_task(resumed, summary=summary)
        except Timeout as error:
            raise HTTPException(status_code=409, detail="审核操作正在进行，请稍后重试") from error

    def review_completed_annotation_task(self, project_id: str, task_id: str):
        """Recover already-persisted successes for human review, never formal GT."""
        from filelock import FileLock, Timeout

        self._require_annotation_review_task(project_id, task_id)
        try:
            with FileLock(str(self.dependencies.shared_task_artifacts().artifact_path(task_id, "review.lock")), timeout=5):
                task = self._require_annotation_review_task(project_id, task_id)
                artifacts = self.dependencies.shared_task_artifacts()
                if not artifacts.artifact_path(task_id, "candidates/manifest.json").is_file():
                    raise HTTPException(status_code=409, detail="尚无已保存的候选结果，可尝试继续任务")
                store = CandidateStore(artifacts, task_id=task_id)
                summary = store.statistics()
                if not summary.get("success", 0) + summary.get("empty", 0):
                    raise HTTPException(status_code=409, detail="尚无识别完成的图片，可尝试继续任务")
                if ((task.accepted is not None and not (task.status is TaskStatus.CANCELLED and task.accepted is False))
                        or summary.get("gt_committed")
                        or artifacts.artifact_path(task_id, "review/confirmation.json").is_file()
                        or artifacts.artifact_path(task_id, "review/result.json").is_file()):
                    raise HTTPException(status_code=409, detail="任务已有正式审核确认，不允许恢复重复审核")
                try:
                    recovered = self.dependencies.shared_task_repository().recover_annotation_candidates_for_review(task_id)
                except ValueError as error:
                    raise HTTPException(status_code=409, detail=str(error)) from error
                return self.public_annotation_task(recovered, summary=summary)
        except Timeout as error:
            raise HTTPException(status_code=409, detail="审核操作正在进行，请稍后重试") from error

    def list_annotation_tasks(self, project_id: str, limit: int = 50, cursor: Optional[str] = None,
                              status: str = "", q: str = "", retry_index: bool = False, reader_view: bool = False):
        self.dependencies.get_project(project_id)
        selected_status = str(status or "").strip().upper()
        if selected_status and selected_status not in {item.value for item in TaskStatus}:
            raise HTTPException(status_code=422, detail="AI 标注任务状态筛选条件无效")
        repository = self.dependencies.shared_task_repository()
        query = str(q or "").strip()
        if len(query) > 120:
            raise HTTPException(status_code=422, detail="搜索内容最多 120 个字符")
        if query:
            if retry_index:
                repository.retry_failed_annotation_search(project_id)
                with self.dependencies._annotation_search_worker_lock():
                    self.dependencies._annotation_search_worker_errors().pop(project_id, None)
            progress = repository.annotation_search_progress(project_id)
            if progress["failed"]:
                return JSONResponse(status_code=503, content={
                    "detail": f"{progress['failed']} 条历史任务的原始请求不可读取，搜索暂不完整；修复记录后点击重试索引",
                    "index_failed": True,
                })
            with self.dependencies._annotation_search_worker_lock():
                error = self.dependencies._annotation_search_worker_errors().get(project_id)
            if error:
                from platform_core.training_reader_views import text
                return JSONResponse(status_code=503, content={"detail": text(error) if reader_view else error, "index_failed": True})
            if progress["pending"]:
                self.dependencies._start_annotation_search_backfill(project_id)
                return JSONResponse(status_code=202, content={
                    "indexing": True,
                    **({"ok":True,"project_id":project_id} if reader_view else {}),
                    "indexed": progress["total"] - progress["pending"],
                    "total": progress["total"],
                    "remaining": progress["pending"],
                    "items": [], "next_cursor": None,
                })
        page = repository.list(
            project_id=project_id,
            kinds={TaskKind.AI_ANNOTATION},
            statuses={selected_status} if selected_status else None,
            limit=max(1, min(100, int(limit))),
            cursor=cursor,
            annotation_query=query,
        )
        statistics = repository.annotation_statistics_many(
            project_id, [task.task_id for task in page.items],
        )
        missing_statistics = [
            task.task_id for task in page.items
            if task.task_id not in statistics and task.result_ref
            and task.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED}
        ]
        self.dependencies._start_annotation_statistics_backfill(
            project_id, missing_statistics, repository, self.dependencies.shared_task_artifacts(),
        )
        worker_runtime = WorkerInstanceService(repository).list_runtime()
        queued_candidates = (
            repository.queued_candidates()
            if any(task.status is TaskStatus.QUEUED for task in page.items)
            else ()
        )
        response = {
            "items": [
                self.public_annotation_task(
                    task,
                    summary=(statistics.get(task.task_id) or {}).get("counts"),
                    statistics_synced_at=(statistics.get(task.task_id) or {}).get("synced_at"),
                    worker_runtime=worker_runtime,
                    queued_candidates=queued_candidates,
                )
                for task in page.items
            ],
            "next_cursor": page.next_cursor,
            "statistics_indexing": bool(missing_statistics),
        }


        if reader_view:
            from platform_core.annotation_reader_views import task_display
            response.update(ok=True, project_id=project_id)
            response["items"]=[task_display(row) for row in response["items"]]
        return response

    def _annotation_label_catalog(self, project: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {
                'code': str(item['code']),
                'class_id': int(item['class_id']),
                'display_name_zh': str(
                    item.get('display_name_zh')
                    or item.get('display_name')
                    or item['code']
                ),
                'aliases': normalize_label_aliases(item.get('aliases') or []),
            }
            for item in active_label_options(self.dependencies.project_label_items(project))
        ]

    def _annotation_summary(self, task: TaskRecord) -> dict:
        artifacts = self.dependencies.shared_task_artifacts()
        if not task.result_ref and not artifacts.artifact_path(task.task_id, "candidates/manifest.json").is_file():
            return {}
        try:
            return CandidateStore(artifacts, task_id=task.task_id).summary()
        except (FileNotFoundError, ValueError):
            return {}

    def _annotation_create_payload(self, project_id: str, payload: AnnotationTaskCreateReq) -> tuple[dict, str]:
        # Web submission owns selection/material validation only. Model/prompt
        # selection and immutable configuration snapshots belong to the shared
        # worker-safe annotation_runtime owner used by both v60 and Material Batch.
        self.dependencies.get_project(project_id)
        image_ids = list(dict.fromkeys(

            str(value) for value in payload.image_ids if str(value)
        ))
        if payload.selection_ref:
            from platform_core.training_selection_reference import read_selection
            if payload.source_batch_id:
                raise HTTPException(status_code=422, detail="批次与冻结选择不能混用")
            try:
                frozen_ids = read_selection(self.dependencies.DATA_DIR(), payload.selection_ref, {"project_id": project_id,"purpose":"ai_annotation"})
            except ValueError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
            image_ids = sorted((set(frozen_ids) - set(payload.excluded_image_ids)) | set(image_ids))
            if len(image_ids) > 200000:
                raise HTTPException(status_code=422, detail="选择超过单任务200000张容量")

        batch_id = str(payload.source_batch_id or "").strip()
        if batch_id:
            if image_ids:
                raise HTTPException(status_code=422, detail="来源 ZIP 批次与逐张图片选择不可同时提交")
            if not re.fullmatch(r"[0-9a-f]{10}", batch_id):
                raise HTTPException(status_code=422, detail="ZIP 批次编号格式不正确")
            batch = self.dependencies.v19_read_job(project_id, batch_id)
            if batch.get("status") != "done" or str(batch.get("batch_id") or batch_id) != batch_id:
                raise HTTPException(status_code=409, detail="来源 ZIP 批次尚未完成或已发生变化，请重新打开导入结果")
            source_ids = list(dict.fromkeys(
                str(value) for value in self.dependencies.v19_read_import_report(project_id, batch_id, batch).get("imported_image_ids") or []
                if str(value)
            ))
            if not source_ids:
                raise HTTPException(status_code=409, detail="来源 ZIP 批次没有可信的已入库图片")
            image_ids = []
            for offset in range(0, len(source_ids), 500):
                chunk = source_ids[offset:offset + 500]
                current = self.dependencies.read_annotations_many(project_id, chunk)
                image_ids.extend(
                    image_id for image_id in chunk
                    if str((current.get(image_id) or {}).get("annotation_state") or "unannotated") == "unannotated"
                )
        if not image_ids:
            raise HTTPException(status_code=400, detail="本批次没有待标注原图，或尚未选择素材")

        strict_review = payload.review_scope_policy == "per_image_required"
        if strict_review:
            if not str(payload.request_id or "").strip():
                raise HTTPException(status_code=422, detail="逐图补审必须使用可恢复的创建请求 ID")
            if (payload.expected_material_revision is None or payload.expected_annotation_revision is None
                    or payload.expected_material_revision < 0 or payload.expected_annotation_revision < 0):
                raise HTTPException(status_code=422, detail="逐图补审必须提供素材与正式 GT 修订号")
            if payload.preview_count or payload.overwrite:
                raise HTTPException(status_code=400, detail="逐图补审不允许预览截断或整体覆盖历史标注")

        existing = set()
        materials = self.dependencies.material_store(project_id)
        material_revision = materials.current_revision() if strict_review else None
        annotations = self.dependencies._v50_annotation_repository(project_id) if strict_review else None
        annotation_revision = annotations.current_revision() if strict_review else None
        if strict_review and (material_revision != payload.expected_material_revision
                              or annotation_revision != payload.expected_annotation_revision):
            raise HTTPException(status_code=409, detail="补审素材或正式 GT 修订已变化，请重新核验选择")
        scoped_materials = {} if strict_review else None
        for offset in range(0, len(image_ids), 500):
            for image in materials.get_many(image_ids[offset:offset + 500]):
                image_id = str(image.get("id") or "")
                if image_id:
                    existing.add(image_id)
                    if strict_review:
                        # Freeze only source identity and availability, not full
                        # per-material metadata/JSON for a 21k-image task.
                        scoped_materials[image_id] = {
                            key: image.get(key) for key in (
                                "content_sha256", "source_available", "_dataset_delete_claim",
                                "_material_batch_delete_claim", "annotation_needs_review",
                                "external_annotation_needs_review", "needs_review",
                            )
                        }
        missing = sorted(set(image_ids) - existing)
        if missing:
            raise HTTPException(
                status_code=400,
                detail="以下素材不存在：" + "、".join(missing[:20]),
            )

        request = payload.model_dump(mode="json")
        request.update({
            "image_ids": image_ids,
            "schema_version": 2,
        })
        try:
            # _v35_model_items() performs the one-time legacy secret migration.
            # prepare_annotation_request() is the only owner that interprets the
            # model/prompt configuration and freezes it for Durable execution.
            prepared = prepare_annotation_request(
                self.dependencies.DATA_DIR(),
                project_id,
                request,
                runtime=False,
                model_configs=self.dependencies._v35_model_items(),
                prompt_templates=self.dependencies._v35_prompt_items(),
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        provider_key = str(prepared.get("model_config_id") or "")
        if not provider_key:
            raise HTTPException(status_code=400, detail="AI_MODEL_CONFIG_NOT_FOUND: 请选择可用模型配置")
        if strict_review:
            from platform_core.training_label_tasks import training_material_scope_issue

            scopes, versions, hashes = {}, {}, {}
            required = {"effective_label_codes": list(prepared["labels"])}
            for offset in range(0, len(image_ids), 500):
                chunk = image_ids[offset:offset + 500]
                current = self.dependencies.read_annotations_many(project_id, chunk)
                for image_id in chunk:
                    material = scoped_materials[image_id]
                    annotation = current.get(image_id) or {}
                    source_hash = str(material.get("content_sha256") or "").strip().lower()
                    recorded_source = str(annotation.get("source_content_sha256") or "").strip().lower()
                    if (not re.fullmatch(r"[0-9a-f]{64}", source_hash)
                            or (recorded_source and recorded_source != source_hash)
                            or material.get("source_available") is False
                            or material.get("_dataset_delete_claim")
                            or material.get("_material_batch_delete_claim")
                            or material.get("annotation_needs_review")
                            or material.get("external_annotation_needs_review") or material.get("needs_review")):
                        raise HTTPException(status_code=409, detail="补审素材缺少可信来源或原标注已失效，请重新核查")
                    issue = training_material_scope_issue({"id": image_id, **annotation}, required)
                    if (not issue or issue["issue_type"] not in {"partial_review_scope", "missing_annotation"}
                            or not issue.get("missing_label_codes")):
                        raise HTTPException(status_code=409, detail="所选素材已无对应标签缺口，请刷新补审范围")
                    scopes[image_id] = list(issue["missing_label_codes"])
                    versions[image_id] = int(annotation.get("version") or 0)
                    hashes[image_id] = source_hash
            if (materials.current_revision() != material_revision
                    or annotations.current_revision() != annotation_revision):
                raise HTTPException(status_code=409, detail="补审冻结期间素材或正式 GT 已变化，请重新提交")
            prepared.update({
                "review_scope_policy": "per_image_required",
                "per_image_missing_review_scopes": scopes,
                "per_image_annotation_versions": versions,
                "per_image_source_hashes": hashes,
                "selection_material_revision": material_revision,
                "selection_annotation_revision": annotation_revision,
            })
        return prepared, provider_key

    def public_annotation_task(self,
        task: TaskRecord,
        *,
        summary: Optional[dict] = None,
        worker_runtime=None,
        queued_candidates=None,
        statistics_synced_at: Optional[str] = None,
        include_review_policy: bool = False,
    ) -> Dict[str, Any]:
        progress_summary = summary or {}
        repository = self.dependencies.shared_task_repository()
        truth = task_to_public(
            task,
            repository,
            worker_runtime=worker_runtime,
            queued_candidates=queued_candidates,
        )
        request = self.dependencies.shared_task_artifacts().read_json(task.task_id, task.payload_ref, default={})
        checkpoint = self.dependencies.shared_task_artifacts().read_json(task.task_id, "checkpoints/worker.json", default={})
        is_batch = task.kind is TaskKind.MATERIAL_BATCH and request.get("operation") == "AI_ANNOTATE"
        if is_batch:
            request = request.get("options") or {}
        native_inference_config = None
        if isinstance(request, dict):
            frozen_model = request.get("model_config_snapshot") or {}
            if isinstance(frozen_model, dict) and (frozen_model.get("provider_adapter") or frozen_model.get("provider_type")) == "wevisone_vl":
                from platform_core.providers.wevisone_vision import effective_detection_config
                native_inference_config = effective_detection_config(frozen_model, request.get("labels") or [])
        requested_total = len((request or {}).get("image_ids") or []) if isinstance(request, dict) else 0
        preview_count = int((request or {}).get("preview_count") or 0) if isinstance(request, dict) else 0
        if preview_count:
            requested_total = min(requested_total, max(0, preview_count))
        total_count = max(requested_total, int(progress_summary.get("total") or 0))
        if is_batch:
            total_count = max(total_count, int(checkpoint.get("total") or 0))
        completed_count = max(
            int((checkpoint or {}).get("processed" if is_batch else "next_index") or 0) if isinstance(checkpoint, dict) else 0,
            int(progress_summary.get("total") or 0),
        )
        # A failed-only retry may reduce the failed population. The last checkpoint
        # is not an upper bound once failed rows have been replaced by successes.
        failed_count = (
            int(progress_summary.get("failed") or 0) if isinstance(summary, dict) and "failed" in summary
            else int((checkpoint or {}).get("failed") or 0) if isinstance(checkpoint, dict) else 0
        )
        policy_projection = {}
        if include_review_policy and isinstance(request, dict) and request and (
            task.kind is TaskKind.AI_ANNOTATION or is_batch
        ):
            policy = request.get("review_scope_policy", "task_uniform_legacy")
            if policy in ("task_uniform_legacy", "per_image_required"):
                policy_projection["review_scope_policy"] = policy
        return {
            **policy_projection,
            "id": task.task_id,
            "project_id": task.project_id,
            "kind": task.kind.value,
            "status": truth["status"],
            "persisted_status": truth["persisted_status"],
            "priority": truth["priority"],
            "queue_rank": truth["queue_rank"],
            "resource_queue_position": truth["resource_queue_position"],
            "resource_wait_reason": truth["resource_wait_reason"],
            "worker_id": truth["worker_id"],
            "lease_expires_at": truth["lease_expires_at"],
            "progress": truth["progress_percent"],
            "progress_percent": truth["progress_percent"],
            "stage": truth["phase"],
            "phase": truth["phase"],
            "current_item": truth["current_item"],
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "finished_at": task.finished_at,
            "retry_of": task.retry_of,
            "accepted": task.accepted,
            "error": task.error,
            "name": str((request or {}).get("task_name") or "AI自动标注任务") if isinstance(request, dict) else "AI自动标注任务",
            "requested_labels": list((request or {}).get("labels") or []) if isinstance(request, dict) else [],
            "model_config_id": str((request or {}).get("model_config_id") or "") if isinstance(request, dict) else "",
            "model_config_name": str((request or {}).get("model_config_name") or "") if isinstance(request, dict) else "",
            "model_provider": str((request or {}).get("model_provider") or "") if isinstance(request, dict) else "",
            "model_config_revision": str((request or {}).get("model_config_revision") or "") if isinstance(request, dict) else "",
            "native_inference_config": native_inference_config,
            "total_count": total_count,
            "completed_count": min(total_count, completed_count) if total_count else completed_count,
            "remaining_count": max(0, total_count - completed_count),
            "failed_count": failed_count,
            "summary": progress_summary,
            "stage_statistics": progress_summary if "gt_committed" in progress_summary else None,
            "statistics_synced_at": statistics_synced_at,
        }
