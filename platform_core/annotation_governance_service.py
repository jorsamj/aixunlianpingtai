"""Existing governance orchestration. Persistence, locks and receipts retain their original owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional, Mapping, Tuple
from fastapi import HTTPException
from .annotation_governance_contracts import AddLabelReq, AnnotationSave, LabelUpdateReq, V52LabelRemapReq, V54LabelUnifyReq, V54LabelsUnifyPreviewReq, V54LabelsUnifyReq

import re
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from platform_core.annotations import normalize_boxes, restore_box_provenance
from platform_core.annotation_repository import AnnotationConflictError, AnnotationLabelStateError, AnnotationRepository
from platform_core.errors import PlatformError
from platform_core.labels import active_label_options, label_governance_fence
from platform_core.material_repository import AnnotationMaterialLifecycleError
from platform_core.material_batches import BatchRequestError as MaterialBatchRequestError, create_annotation_remap_batch, create_annotation_remap_by_labels, public_batch as public_material_batch

@dataclass(frozen=True)
class AnnotationGovernanceDependencies:
    _V50_DATASET_DELETE_CLAIM_FIELD: Callable[..., Any]
    _annotation_box_source_fallback: Callable[..., Any]
    _online_feedback_repository: Callable[..., Any]
    _prune_canonical_label_alias_conflicts: Callable[..., Any]
    _set_project_label_aliases: Callable[..., Any]
    _validate_label_aliases: Callable[..., Any]
    default_label_color: Callable[..., Any]
    ensure_label: Callable[..., Any]
    get_project: Callable[..., Any]
    material_store: Callable[..., Any]
    normalize_label: Callable[..., Any]
    now_iso: Callable[..., Any]
    project_dir: Callable[..., Any]
    project_label_items: Callable[..., Any]
    read_annotation: Callable[..., Any]
    save_project: Callable[..., Any]
    shared_task_artifacts: Callable[..., Any]
    shared_task_repository: Callable[..., Any]
    write_annotation: Callable[..., Any]


class AnnotationGovernanceService:
    def __init__(self, dependencies: AnnotationGovernanceDependencies):
        self.dependencies = dependencies

    def add_label(self, project_id: str, payload: AddLabelReq):
        with label_governance_fence(self.dependencies.project_dir(project_id)):
            return self._add_label_locked(project_id, payload)

    def _add_label_locked(self, project_id: str, payload: AddLabelReq):
        project = self.dependencies.get_project(project_id)
        normalized_code = self.dependencies.normalize_label(payload.label)
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", normalized_code):
            raise HTTPException(
                status_code=422,
                detail="标签编码只允许英文、数字、_、-，且必须以英文字母开头",
            )
        try:
            aliases = (
                self.dependencies._validate_label_aliases(
                    project,
                    payload.aliases,
                    target_class_id=None,
                    target_code=normalized_code,
                    target_display_name=payload.display_name or normalized_code,
                )
                if payload.aliases is not None else None
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        idx = self.dependencies.ensure_label(project, normalized_code)
        project = self.dependencies.get_project(project_id)
        meta = project.setdefault("label_meta", [])
        while len(meta) < len(project.get("labels", [])):
            code = project["labels"][len(meta)]
            meta.append({"code": code, "display_name": code, "color": self.dependencies.default_label_color(len(meta)), "type": "bbox", "hotkey": str(len(meta)+1) if len(meta) < 9 else ""})
        if idx < len(meta):
            # Explicit creation of a previously soft-deleted canonical label
            # reactivates the same project class id instead of allocating a new one.
            meta[idx]["status"] = "active"
            meta[idx]["active"] = True
            meta[idx].pop("deleted_at", None)
            if payload.display_name:
                meta[idx]["display_name"] = payload.display_name
            if payload.color:
                meta[idx]["color"] = payload.color
            if aliases is not None:
                self.dependencies._set_project_label_aliases(
                    project, project["labels"][idx], aliases, replace=True,
                )
        self.dependencies._prune_canonical_label_alias_conflicts(project)
        self.dependencies.save_project(project)
        return {
            "ok": True,
            "class_id": idx,
            "labels": project["labels"],
            "label_meta": project.get("label_meta", []),
            "items": active_label_options(self.dependencies.project_label_items(project)),
        }

    def v12_update_label(self, project_id: str, class_id: int, payload: LabelUpdateReq):
        with label_governance_fence(self.dependencies.project_dir(project_id)):
            return self._v12_update_label_locked(project_id, class_id, payload)

    def _v12_update_label_locked(self, project_id: str, class_id: int, payload: LabelUpdateReq):
        project = self.dependencies.get_project(project_id)
        labels = project.get("labels", [])
        if class_id < 0 or class_id >= len(labels):
            raise HTTPException(status_code=404, detail="标签不存在")
        pending_code = self.dependencies.normalize_label(payload.code) if payload.code else labels[class_id]
        current_meta = project.get("label_meta", [])
        current_display = (
            current_meta[class_id].get("display_name")
            if class_id < len(current_meta) and isinstance(current_meta[class_id], dict)
            else labels[class_id]
        )
        pending_display = payload.display_name if payload.display_name is not None else current_display
        if pending_code != labels[class_id] or str(pending_display) != str(current_display):
            pending_feedback_id = self.dependencies._online_feedback_repository(project_id).pending_label_reference(
                [str(labels[class_id]), str(current_display or "")]
            )
            if pending_feedback_id:
                raise HTTPException(
                    status_code=409,
                    detail="该标签仍有待审核的线上正确预测反馈，请先完成审核或忽略后再修改编码/名称",
                )
        try:
            validated_aliases = (
                self.dependencies._validate_label_aliases(
                    project,
                    payload.aliases,
                    target_class_id=class_id,
                    target_code=pending_code,
                    target_display_name=pending_display or pending_code,
                )
                if payload.aliases is not None else None
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if payload.code:
            code = self.dependencies.normalize_label(payload.code)
            if not code:
                raise HTTPException(status_code=400, detail="标签编码不能为空")
            if code != labels[class_id] and code in labels:
                raise HTTPException(status_code=400, detail="标签编码已存在")
            if code != labels[class_id]:
                references = AnnotationRepository(
                    self.dependencies.project_dir(project_id)
                ).label_reference_preview([str(labels[class_id])])
                if int(references.get("affected_images") or 0) > 0:
                    raise HTTPException(
                        status_code=409,
                        detail="该标签已被正式标注引用，不能同步改编码；请使用“统一标签”后台任务",
                    )
            labels[class_id] = code
        meta = project.setdefault("label_meta", [])
        while len(meta) < len(labels):
            idx = len(meta)
            meta.append({"code": labels[idx], "display_name": labels[idx], "color": self.dependencies.default_label_color(idx), "type": "bbox", "hotkey": str(idx+1) if idx < 9 else ""})
        m = meta[class_id]
        m["code"] = labels[class_id]
        if payload.display_name is not None:
            m["display_name"] = payload.display_name or labels[class_id]
        if payload.color:
            m["color"] = payload.color
        if payload.hotkey is not None:
            m["hotkey"] = payload.hotkey
        if validated_aliases is not None:
            self.dependencies._set_project_label_aliases(
                project, labels[class_id], validated_aliases, replace=True,
            )
        self.dependencies._prune_canonical_label_alias_conflicts(project)
        self.dependencies.save_project(project)
        return {"ok": True, "items": self.dependencies.project_label_items(project)}

    def v12_delete_label(self, project_id: str, class_id: int):
        with label_governance_fence(self.dependencies.project_dir(project_id)):
            return self._v12_delete_label_locked(project_id, class_id)

    def _v12_delete_label_locked(self, project_id: str, class_id: int):
        project = self.dependencies.get_project(project_id)
        labels = project.get("labels", [])
        if class_id < 0 or class_id >= len(labels):
            raise HTTPException(status_code=404, detail="标签不存在")
        code = str(labels[class_id])
        references = AnnotationRepository(
            self.dependencies.project_dir(project_id)
        ).label_reference_preview([code])
        if int(references.get("affected_images") or 0) > 0:
            raise HTTPException(
                status_code=400,
                detail="该标签仍被正式标注或 confirmed_empty 范围引用，请先统一标签后再删除",
            )
        meta = project.setdefault("label_meta", [])
        while len(meta) < len(labels):
            index = len(meta)
            meta.append({
                "code": labels[index],
                "display_name": labels[index],
                "color": self.dependencies.default_label_color(index),
                "type": "bbox",
                "hotkey": str(index + 1) if index < 9 else "",
                "aliases": [],
            })
        item = meta[class_id]
        if str(item.get("status") or "active").lower() != "active":
            return {"ok": True, "items": active_label_options(self.dependencies.project_label_items(project))}
        pending_feedback_id = self.dependencies._online_feedback_repository(project_id).pending_label_reference(
            [code, str(item.get("display_name") or code)]
        )
        if pending_feedback_id:
            raise HTTPException(
                status_code=409,
                detail="该标签仍有待审核的线上正确预测反馈，请先完成审核或忽略后再删除",
            )
        # Soft delete preserves project class ids. Physical compaction would require
        # rewriting every higher class id and is deliberately not part of this HTTP path.
        item["status"] = "inactive"
        item["active"] = False
        item["deleted_at"] = self.dependencies.now_iso()
        self.dependencies.save_project(project)
        return {"ok": True, "items": active_label_options(self.dependencies.project_label_items(project))}

    def get_annotation(self, project_id: str, image_id: str, reader_view: bool=False):
        self.dependencies.get_project(project_id)
        rows = self.dependencies.material_store(project_id).get_many([str(image_id)])
        img = rows[0] if rows else None
        if not img:
            raise HTTPException(status_code=404, detail="图片不存在")
        ann = self.dependencies.read_annotation(project_id, image_id)
        if reader_view:
            from platform_core.material_reader_views import annotation_display
            return annotation_display(project_id,img,ann)
        return {"ok": True, **ann, "image": img, "annotation": ann}

    def save_annotation(self, project_id: str, image_id: str, payload: AnnotationSave):
        project = self.dependencies.get_project(project_id)
        materials = self.dependencies.material_store(project_id)
        rows = materials.get_many([str(image_id)])
        img = rows[0] if rows else None
        if not img:
            raise HTTPException(status_code=404, detail="图片不存在")
        if img.get(self.dependencies._V50_DATASET_DELETE_CLAIM_FIELD()) or img.get("source_available") is False:
            raise PlatformError(
                code="ANNOTATION_MATERIAL_UNAVAILABLE",
                message="素材当前不可审核",
                detail="素材正在删除或来源已不可用，本次标注未保存。",
                solution="请刷新素材列表；如来源恢复可用，再重新进入标注工作台。",
                status_code=409,
            )
        current_content_sha256 = str(img.get("content_sha256") or "").strip().lower()
        submitted_content_sha256 = str(payload.source_content_sha256 or "").strip().lower()
        reviewed_label_codes = sorted({
            str(code or "").strip()
            for code in payload.reviewed_label_codes
            if str(code or "").strip()
        })
        if payload.expected_version is None:
            raise PlatformError(
                code="ANNOTATION_EXPECTED_VERSION_REQUIRED",
                message="标注提交缺少版本信息",
                detail="保存标注必须携带打开工作台时读取的标注版本。",
                solution="请刷新当前图片，重新核对标注框和待审核标签后提交。",
                status_code=422,
            )
        if not submitted_content_sha256:
            raise PlatformError(
                code="ANNOTATION_MATERIAL_GENERATION_REQUIRED",
                message="标注提交缺少素材代际信息",
                detail="保存标注必须携带打开工作台时读取的素材内容摘要。",
                solution="请刷新当前图片，重新查看真实图片后提交。",
                status_code=422,
            )
        if submitted_content_sha256 and submitted_content_sha256 != current_content_sha256:
            raise PlatformError(
                code="ANNOTATION_MATERIAL_GENERATION_CHANGED",
                message="素材内容已经变化",
                detail="当前素材与打开标注工作台时看到的内容不是同一代，本次提交未写入。",
                solution="请刷新当前图片，基于最新内容重新标注和审核。",
                status_code=409,
            )
        label_ids = {
            str(item["code"]): int(item["class_id"])
            for item in active_label_options(self.dependencies.project_label_items(project))
        }
        existing_annotation = self.dependencies.read_annotation(project_id, image_id)
        existing_boxes = list(existing_annotation.get("boxes") or [])
        if "*" in reviewed_label_codes:
            raise PlatformError(
                code="ANNOTATION_REVIEW_SCOPE_WILDCARD_FORBIDDEN",
                message="审核范围不允许使用通配符",
                detail="必须逐项确认本次真实完成审核的标签，不能写入 *。",
                solution="请只勾选已经查看图片并完成审核的具体标签。",
                status_code=422,
            )
        unavailable_reviewed = sorted(set(reviewed_label_codes) - set(label_ids))
        if unavailable_reviewed:
            raise PlatformError(
                code="ANNOTATION_LABEL_STATE_CHANGED",
                message="标签状态已变化，标注未保存",
                detail="以下标签已停用、合并或不存在：" + "、".join(unavailable_reviewed),
                solution="请刷新当前图片和标签列表，确认当前有效标签后重新保存。",
                status_code=409,
            )
        try:
            clean_boxes = normalize_boxes(
                payload.boxes,
                int(img.get("width") or 0),
                int(img.get("height") or 0),
                label_ids,
            )
            clean_boxes = restore_box_provenance(
                clean_boxes, existing_boxes,
                existing_source_fallback=self.dependencies._annotation_box_source_fallback(img),
                new_source="manual",
            )
        except KeyError as error:
            missing_label = str(error.args[0] or "")
            raise PlatformError(
                code="ANNOTATION_LABEL_NOT_FOUND",
                message="标注保存失败",
                detail=f"标签 {missing_label} 不在标签库中",
                solution="请到配置中心的标签管理中创建或启用该标签。",
                status_code=422,
            ) from error
        except ValueError as error:
            raise PlatformError(
                code="ANNOTATION_INVALID_BOX",
                message="标注保存失败",
                detail=str(error),
                solution="请检查标注框是否位于图片内部且宽高大于零。",
                status_code=422,
            ) from error
        if clean_boxes and payload.annotation_state == "unannotated":
            raise PlatformError(
                code="ANNOTATION_STATE_BOXES_MISMATCH",
                message="待标注状态不能包含标注框",
                detail="只有清空全部标注框后才能保存为待标注。",
                solution="请保留标注框并保存为已标注，或清空标注框后保存为待标注。",
                status_code=422,
            )
        if not clean_boxes and payload.annotation_state not in {"unannotated", "confirmed_empty"}:
            raise PlatformError(
                code="ANNOTATION_EMPTY_CONFIRMATION_REQUIRED",
                message="请确认无目标",
                detail="空标注必须明确选择保存为待标注，或确认当前图片没有目标。",
                solution="清空错误标注后保存为待标注；只有完成类别审核后才能确认无目标。",
                status_code=409,
            )
        annotation_state = "annotated" if clean_boxes else payload.annotation_state
        existing_scope = {
            str(code).strip()
            for code in (existing_annotation.get("annotation_scope") or [])
            if str(code).strip()
        }
        if annotation_state == "unannotated":
            next_scope = []
        elif annotation_state == "confirmed_empty":
            # Former positive review does not prove absence after deleting its boxes.
            next_scope = reviewed_label_codes
        else:
            next_scope = sorted(existing_scope | set(reviewed_label_codes))
        if annotation_state == "confirmed_empty" and not reviewed_label_codes:
            raise PlatformError(
                code="ANNOTATION_REVIEW_LABEL_REQUIRED",
                message="请选择已经完成审核的标签",
                detail="无目标素材必须明确选择本次确实检查过的类别，不能创建无范围的负样本。",
                solution="勾选已逐类检查的标签后，使用“保存并确认审核”。",
                status_code=409,
            )
        try:
            saved_annotation = self.dependencies.write_annotation(
                project_id,
                image_id,
                clean_boxes,
                annotation_state,
                annotation_scope=next_scope,
                expected_version=payload.expected_version,
                source_content_sha256=(
                    submitted_content_sha256 or current_content_sha256
                ),
                reviewed_label_codes=reviewed_label_codes,
                review_evidence=({'actor_id': payload._review_actor,
                    'reviewed_label_codes': payload._review_codes or reviewed_label_codes,
                    'source_content_sha256': current_content_sha256} if payload._review_actor else None),
            )
        except AnnotationConflictError as error:
            raise PlatformError(
                code="ANNOTATION_CONCURRENT_MODIFICATION",
                message="标注已被其他操作更新",
                detail=(
                    f"当前图片标注已从版本 {error.expected_version} 更新为 "
                    f"{error.actual_version}，本次保存未覆盖最新标注。"
                ),
                solution="请刷新当前图片，核对最新标注后再保存。",
                status_code=409,
            ) from error
        except AnnotationLabelStateError as error:
            raise PlatformError(
                code=error.code,
                message="标签状态已变化，标注未保存",
                detail=str(error),
                solution="请刷新当前图片和标签列表，确认当前有效标签后重新保存。",
                status_code=409,
            ) from error
        except AnnotationMaterialLifecycleError as error:
            raise PlatformError(
                code="ANNOTATION_MATERIAL_LIFECYCLE_CHANGED",
                message="素材状态在保存期间发生变化",
                detail=str(error),
                solution="请刷新素材和标注工作台，基于当前内容重新审核后提交。",
                status_code=409,
            ) from error
        fresh = materials.get(str(image_id))
        fresh_content_sha256 = str((fresh or {}).get("content_sha256") or "").strip().lower()
        if not fresh or fresh.get(self.dependencies._V50_DATASET_DELETE_CLAIM_FIELD()) or fresh.get("source_available") is False:
            raise PlatformError(
                code="ANNOTATION_MATERIAL_UNAVAILABLE",
                message="素材状态在保存期间发生变化",
                detail="标注已按版本写入，但素材已删除、正在删除或来源不可用，不能作为训练真值。",
                solution="请刷新素材列表并确认当前状态。",
                status_code=409,
            )
        if fresh_content_sha256 != current_content_sha256:
            materials.patch({str(image_id): {
                "annotation_needs_review": True,
                "annotation_review_reason": "SOURCE_CONTENT_CHANGED",
                "needs_review": True,
            }})
            raise PlatformError(
                code="ANNOTATION_MATERIAL_GENERATION_CHANGED",
                message="素材内容在保存期间发生变化",
                detail="本次标注不能证明最新素材代际已经完成审核，系统已保持重新审核标记。",
                solution="请刷新当前图片，基于最新内容重新标注和审核。",
                status_code=409,
            )
        # Online-feedback material enters the review queue as pending_decision.
        # Once the human review saves formal truth it becomes ordinary processed
        # training data; without this transition the reviewed sample could never
        # enter the next-round training selection (only processed rows are
        # selectable). This is the same existing Material owner projection, not a
        # second GT store.
        if (
            annotation_state in {"annotated", "confirmed_empty"}
            and bool((fresh or {}).get("online_feedback_needs_review"))
        ):
            materials.patch({str(image_id): {
                "processing_status": "processed",
                "online_feedback_needs_review": False,
                "online_feedback_reviewed_at": self.dependencies.now_iso(),
            }})
            fresh = materials.get(str(image_id)) or fresh
        reviewed_added = sorted(set(next_scope) - existing_scope)
        return {
            "ok": True,
            "image": fresh,
            "annotation": saved_annotation,
            "saved_boxes": len(clean_boxes),
            "reviewed_label_codes_added": reviewed_added,
            "review_evidence": {
                "annotation_version": int(saved_annotation.get("version") or 0),
                "annotation_digest": str(saved_annotation.get("content_digest") or ""),
                "source_content_sha256": current_content_sha256,
                "annotation_scope": list(saved_annotation.get("annotation_scope") or []),
                "reviewed_label_codes_added": reviewed_added,
                "saved_at": str(saved_annotation.get("updated_at") or ""),
            },
        }

    def v52_remap_import_labels(self, project_id: str, payload: V52LabelRemapReq):
        self.dependencies.get_project(project_id)
        ids = [str(x).strip() for x in (payload.image_ids or []) if str(x).strip()]
        source = self.dependencies.normalize_label(payload.source_label)
        target = self.dependencies.normalize_label(payload.target_label)
        if not ids:
            raise HTTPException(status_code=400, detail='请选择需要调整标签的素材')
        if not source or not target:
            raise HTTPException(status_code=400, detail='原标签和新标签不能为空')
        if source == target:
            return {
                'ok': True,
                'changed_images': 0,
                'changed_boxes': 0,
                'source_label': source,
                'target_label': target,
            }
        project = self.dependencies.get_project(project_id)
        active_targets = {
            str(item.get('code')): int(item.get('class_id'))
            for item in active_label_options(self.dependencies.project_label_items(project))
        }
        if target not in active_targets:
            raise HTTPException(
                status_code=409,
                detail='目标标签必须来自当前有效标签库；如需新标签，请先在“标签管理”中显式创建',
            )
        try:
            task = create_annotation_remap_batch(
                project_id,
                self.dependencies.material_store(project_id),
                self.dependencies.shared_task_repository(),
                self.dependencies.shared_task_artifacts(),
                ids,
                source,
                target,
            )
        except MaterialBatchRequestError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        return JSONResponse(
            status_code=202,
            content=public_material_batch(
                task, self.dependencies.shared_task_artifacts(), self.dependencies.shared_task_repository()
            ),
        )

    def _v54_resolve_unify_sources(self, project_id: str, source_class_ids):
        project = self.dependencies.get_project(project_id)
        catalog = active_label_options(self.dependencies.project_label_items(project))
        by_id = {int(item.get('class_id', -1)): item for item in catalog}
        ids = list(dict.fromkeys(int(value) for value in (source_class_ids or [])))
        if not ids:
            raise HTTPException(status_code=400, detail='请至少选择一个来源标签')
        if len(ids) > 50:
            raise HTTPException(status_code=422, detail='一次最多统一 50 个来源标签')
        missing = [value for value in ids if value not in by_id]
        if missing:
            raise HTTPException(status_code=404, detail='部分来源标签不存在或已停用，请刷新后重试')
        return project, catalog, [by_id[value] for value in ids]

    def _v54_start_unify(self, project_id: str, source_class_ids, target_label: str):
        _project, catalog, source_items = self._v54_resolve_unify_sources(
            project_id, source_class_ids,
        )
        target = self.dependencies.normalize_label(target_label)
        active_targets = {str(item.get('code')) for item in catalog}
        if target not in active_targets:
            raise HTTPException(
                status_code=409,
                detail='目标标签必须来自当前有效标签库；如需新标签，请先显式创建',
            )
        sources = [str(item.get('code') or '').strip() for item in source_items]
        if target in sources:
            raise HTTPException(status_code=400, detail='目标标签不能同时作为来源标签')
        try:
            task = create_annotation_remap_by_labels(
                project_id,
                self.dependencies.material_store(project_id),
                self.dependencies.shared_task_repository(),
                self.dependencies.shared_task_artifacts(),
                sources,
                target,
                retire_sources_on_success=True,
            )
        except MaterialBatchRequestError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        return JSONResponse(
            status_code=202,
            content=public_material_batch(
                task, self.dependencies.shared_task_artifacts(), self.dependencies.shared_task_repository()
            ),
        )

    def v54_label_schema(self, project_id: str):
        project = self.dependencies.get_project(project_id)
        governance = self.dependencies.project_label_items(project)
        items = active_label_options(governance)
        references = AnnotationRepository(
            self.dependencies.project_dir(project_id)
        ).label_reference_usage()
        for x in items:
            code = str(x.get('code'))
            ref = references.get(code, {})
            x['usage_images'] = int(ref.get('positive_images') or 0)
            x['usage_boxes'] = int(ref.get('boxes') or 0)
            x['scope_images'] = int(ref.get('scope_images') or 0)
            x['affected_images'] = int(ref.get('affected_images') or 0)
        return {'ok': True, 'items': items, 'governance': governance}

    def v54_preview_unify_labels(self,
        project_id: str, payload: V54LabelsUnifyPreviewReq,
    ):
        _project, _catalog, source_items = self._v54_resolve_unify_sources(
            project_id, payload.source_class_ids,
        )
        sources = [str(item.get('code') or '').strip() for item in source_items]
        return {
            'ok': True,
            'source_labels': sources,
            **AnnotationRepository(
                self.dependencies.project_dir(project_id)
            ).label_reference_preview(sources),
        }

    def v54_unify_labels(self, project_id: str, payload: V54LabelsUnifyReq):
        return self._v54_start_unify(
            project_id, payload.source_class_ids, payload.target_label,
        )

    def v54_unify_label(self, project_id: str, class_id: int, payload: V54LabelUnifyReq):
        return self._v54_start_unify(project_id, [class_id], payload.target_label)
