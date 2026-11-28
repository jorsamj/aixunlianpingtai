"""Domain orchestration over the existing persistence, worker and receipt owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from fastapi import Query, HTTPException
from .cleaning_management_contracts import V47CleanConfirmReq, V47CleanReq, V47CleanRuntimeReq

import json
import sqlite3
from contextlib import closing
from platform_core.task_node_assignments import CentralTaskAllocator, NodeAssignmentError
from platform_core.task_runtime import TaskKind, TaskStatus
from platform_core.material_batches import SELECTION_REF as MATERIAL_BATCH_SELECTION_REF, _material_integrity_plan_ref, _json_metadata

@dataclass(frozen=True)
class CleaningManagementDependencies:
    _require_material_delete_preview: Callable[..., Any]
    _v33_get_task: Callable[..., Any]
    _v33_load_tasks: Callable[..., Any]
    _v47_clean_agent_preflight: Callable[..., Any]
    _v47_clean_compat_task: Callable[..., Any]
    _v47_material_batch_request: Callable[..., Any]
    _v62_prepare_clean_compat: Callable[..., Any]
    _v62_publish_clean_compat: Callable[..., Any]
    get_project: Callable[..., Any]
    material_store: Callable[..., Any]
    now_iso: Callable[..., Any]
    public_material: Callable[..., Any]
    shared_task_artifacts: Callable[..., Any]
    shared_task_repository: Callable[..., Any]


class CleaningManagementService:
    def __init__(self, dependencies: CleaningManagementDependencies):
        self.dependencies = dependencies

    def v47_list_clean_tasks(self, project_id: str):
        self.dependencies.get_project(project_id)
        return {'items': self.dependencies._v33_load_tasks(project_id, 'clean_tasks')}

    def v47_clean_runtime_preflight(self, project_id: str, payload: V47CleanRuntimeReq):
        truth = self.dependencies._v47_clean_agent_preflight(
            project_id, payload.image_ids, payload.clean_scope, payload.selection_spec, payload.selection_mode,
        )
        truth.setdefault('label_counts', self.dependencies.material_store(project_id).label_usage())
        return {
            'local_available': True,
            'default_execution_mode': 'local',
            **truth,
        }

    def v47_create_clean_task(self, project_id: str, payload: V47CleanReq):
        task_id = ''
        try:
            task, _ = self.dependencies._v62_prepare_clean_compat(project_id, payload)
            task_id = str(task['id'])
            self.dependencies._v62_publish_clean_compat(project_id, task_id)
            self._v47_apply_clean_scheduling(task_id)
            durable = self.dependencies.shared_task_repository().get(task_id)
            if durable is None:
                raise ValueError('清洗任务发布后未找到持久化任务')
            return self.dependencies._v47_clean_compat_task(durable)
        except NodeAssignmentError as error:
            current = self.dependencies.shared_task_repository().get(task_id) if task_id else None
            if current is not None and current.status is TaskStatus.QUEUED:
                self.dependencies.shared_task_repository().request_cancel(task_id)
            raise HTTPException(
                status_code=error.status_code,
                detail={'code': error.code, 'message': str(error)},
            ) from error
        except ValueError as error:
            current = self.dependencies.shared_task_repository().get(task_id) if task_id else None
            if current is not None and current.status is TaskStatus.QUEUED:
                self.dependencies.shared_task_repository().request_cancel(task_id)
            raise HTTPException(status_code=409, detail=str(error)) from error

    def v47_stop_clean_task(self, project_id: str, task_id: str):
        task = self.dependencies.shared_task_repository().get(task_id)
        if task is None or task.project_id != project_id or task.kind is not TaskKind.MATERIAL_BATCH:
            raise HTTPException(status_code=404, detail='清洗任务不存在')
        self.dependencies.shared_task_repository().request_cancel(task_id)
        return {'ok': True}

    def v47_clean_result(
        self, project_id: str, task_id: str, *, page: Optional[int] = None,
        page_size: int = 20, review_filter: str = 'all', issue_code: str = '',
        include_suggested_ids: bool = False,
    ):
        task = self.dependencies._v33_get_task(project_id, 'clean_tasks', task_id)
        if not task:
            raise HTTPException(status_code=404, detail='清洗任务不存在')
        return {'task': task, 'result': self._v47_durable_clean_results(
            task_id, project_id, page=page, page_size=page_size, review_filter=review_filter,
            issue_code=issue_code, include_suggested_ids=include_suggested_ids,
        )}

    def v47_clean_annotation_audit(self,
        project_id: str,
        task_id: str,
        cursor: str = '',
        limit: int = 100,
        page: Optional[int] = Query(default=None, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
    ):
        task = self.dependencies._v33_get_task(project_id, 'clean_tasks', task_id)
        if not task:
            raise HTTPException(status_code=404, detail='清洗任务不存在')
        return self._v47_durable_annotation_audit(
            task_id, project_id, cursor=cursor,
            limit=max(1, min(200, int(limit or 100))),
            page=page, page_size=page_size,
        )

    def v47_confirm_clean(self, project_id: str, task_id: str, payload: V47CleanConfirmReq):
        task = self.dependencies._v33_get_task(project_id, 'clean_tasks', task_id)
        if not task:
            raise HTTPException(status_code=404, detail='清洗任务不存在')
        if payload.validate_only and (not payload.deletion_plan_id or task.get('status') != 'awaiting_confirmation'):
            raise HTTPException(409, detail='清洗任务当前不能核验删除计划')
        # Never delete or mark processed based on the previous contents of a
        # storage-source object. Validate the entire frozen selection first.
        if payload.delete_ids:
            self.dependencies._require_material_delete_preview(project_id)
        skipped={str(value) for value in payload.skip_image_ids}
        if payload.deletion_plan_id:
            if not skipped or payload.delete_ids:
                raise HTTPException(422, detail='清洗确认须提供原删除计划的排除范围')
            hashes = self._linked_deletion_hashes(project_id, payload.deletion_plan_id, skipped, preview=payload.validate_only)
            allowed = self._v47_validate_clean_confirmation(project_id, task_id, skip_image_ids=skipped, skipped_source_hashes=hashes)
        else:
            allowed = self._v47_validate_clean_confirmation(project_id, task_id, skip_image_ids=skipped) if skipped else self._v47_validate_clean_confirmation(project_id,task_id)
        requested = {str(x) for x in payload.delete_ids}
        if requested - allowed:
            raise HTTPException(status_code=409, detail='删除范围不属于本次有效清洗结果')
        if skipped - allowed:
            raise HTTPException(status_code=409,detail='跳过范围不属于本次有效清洗结果')
        if payload.validate_only:
            return {'ok': True, 'deletion_plan_id': payload.deletion_plan_id, 'processed_ids': []}
        deleted = 0
        deleted_images = []
        failed_items = []
        # 清洗确认严格绑定创建时已经冻结的 selection.sqlite3。
        # FILTERED 范围不能因为兼容层 image_ids 为空而扩大到整个素材库。
        wanted = set(self._v47_frozen_clean_selection_ids(task_id))
        if not wanted:
            raise HTTPException(status_code=409, detail='清洗冻结范围不存在，请重新创建任务')
        cleaned_at = self.dependencies.now_iso()
        materials = self.dependencies.material_store(project_id)
        existing_ids = []
        ordered_wanted = sorted(wanted)
        for offset in range(0, len(ordered_wanted), 500):
            existing_ids.extend(
                str(row.get('id'))
                for row in materials.get_many(ordered_wanted[offset:offset + 500])
                if str(row.get('id') or '')
            )
        # Any delete-requested image that remains after a failed provider/index
        # delete must not be acknowledged as clean/processed. A successful delete
        # no longer exists, while a failed delete retains its previous state for
        # an explicit retry. The frozen selection remains authoritative.
        processed_ids = list(dict.fromkeys(
            image_id for image_id in existing_ids if image_id not in requested | skipped
        ))
        if processed_ids:
            materials.patch_many(
                processed_ids,
                {
                    'processing_status': 'processed',
                    'cleaned_at': cleaned_at,
                    'clean_task_id': task_id,
                },
                batch_size=500,
            )
        deleted_ids = [str(item.get('id')) for item in deleted_images]
        self.dependencies.shared_task_artifacts().atomic_write_json(task_id, 'clean_confirmation.json', {
            'confirmed_at': self.dependencies.now_iso(), 'deleted': deleted, 'deleted_ids': deleted_ids,
            'delete_failures': len(failed_items), 'processed_ids': processed_ids,
            'skipped_image_ids': sorted(skipped),
            **({'deletion_plan_id': payload.deletion_plan_id} if payload.deletion_plan_id else {}),
        })
        return {'ok': not failed_items, 'deleted': deleted, 'deleted_ids': deleted_ids, 'deleted_images': deleted_images, 'failed_items': failed_items, 'processed_ids': processed_ids,
                **({'deletion_plan_id': payload.deletion_plan_id} if payload.deletion_plan_id else {})}

    def _v47_durable_clean_results(self,
        task_id: str,
        project_id: Optional[str] = None,
        *,
        page: Optional[int] = None,
        page_size: int = 20,
        review_filter: str = 'all',
        issue_code: str = '',
        include_suggested_ids: bool = False,
    ) -> Dict[str, Any]:
        artifacts = self.dependencies.shared_task_artifacts()
        path = artifacts.artifact_path(task_id, MATERIAL_BATCH_SELECTION_REF)
        projection: Dict[str, Any] = {}
        if page is not None:
            projection.update(page=1, page_size=page_size, total=0, scanned=0, suggested=0,
                              failed=0, issue_options=[])
            if include_suggested_ids:
                projection['suggested_ids'] = []
        if not path.is_file():
            return {'items': [], **projection}
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as database:
            database.execute('BEGIN')
            if database.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='clean_results'").fetchone() is None:
                return {'items': [], **projection}
            source = ' FROM clean_results r JOIN selection s ON s.image_id=r.image_id'
            columns = 'SELECT r.result_json,s.state,s.error'
            if page is None:
                rows = database.execute(columns + source + ' ORDER BY r.image_id').fetchall()
            else:
                failed = "(s.state='failed' OR LOWER(COALESCE(json_extract(r.result_json,'$.status'),''))='failed')"
                suggested = "COALESCE(json_extract(r.result_json,'$.suggest_delete'),0)=1"
                issues = "json_each(r.result_json,'$.issues') j"
                key = "COALESCE(NULLIF(json_extract(j.value,'$.code'),''),NULLIF(json_extract(j.value,'$.name'),''),'')"
                name = f"COALESCE(NULLIF(json_extract(j.value,'$.name'),''),{key})"
                reviewable = f"({failed} OR json_array_length(r.result_json,'$.issues')>0)"
                where = ' WHERE ' + reviewable
                if review_filter == 'suggested':
                    where += ' AND ' + suggested
                elif review_filter == 'failed':
                    where += ' AND ' + failed
                parameters = ()
                if issue_code:
                    where += f' AND EXISTS (SELECT 1 FROM {issues} WHERE {key}=?)'
                    parameters = (issue_code,)
                total = database.execute('SELECT COUNT(*)' + source + where, parameters).fetchone()[0]
                page = min(page, max(1, (total + page_size - 1) // page_size))
                rows = database.execute(
                    columns + source + where + ' ORDER BY r.image_id LIMIT ? OFFSET ?',
                    (*parameters, page_size, (page - 1) * page_size),
                ).fetchall()
                scanned, suggested_count, failed_count = database.execute(
                    f'SELECT COUNT(*), COALESCE(SUM({suggested}),0), COALESCE(SUM({failed}),0)' + source
                ).fetchone()
                options = database.execute(
                    f'SELECT {key}, MIN({name})' + source + f', {issues} WHERE {key}<>\'\' GROUP BY 1 ORDER BY 1'
                ).fetchall()
                projection.update(page=page, total=total, scanned=scanned, suggested=suggested_count,
                                  failed=failed_count, issue_options=options)
                if include_suggested_ids:
                    projection['suggested_ids'] = [
                        row[0] for row in database.execute(
                            'SELECT r.image_id' + source + ' WHERE ' + suggested + ' ORDER BY r.image_id'
                        )
                    ]
        items = [
            {**json.loads(row[0]), 'item_state': row[1], 'item_error': row[2]}
            for row in rows
        ]
        if project_id and items:
            indexed = {
                str(row.get('id')): self.dependencies.public_material(project_id, row)
                for row in self.dependencies.material_store(project_id).get_many(
                    [str(item.get('image_id')) for item in items]
                )
            }
            for item in items:
                material = indexed.get(str(item.get('image_id'))) or {}
                annotation_state = str(
                    material.get('annotation_state')
                    or material.get('annotation_status')
                    or ('annotated' if material.get('annotated') else 'unannotated')
                ).strip().lower()
                annotation_origin = str(material.get('annotation_origin') or '').strip().lower()
                annotation_provenance = (
                    'confirmed_empty'
                    if annotation_state == 'confirmed_empty'
                    else annotation_origin or ('unannotated' if annotation_state == 'unannotated' else 'unknown')
                )
                item.update({
                    'url': material.get('url') or '',
                    'annotation_state': annotation_state,
                    'annotation_provenance': annotation_provenance,
                    'annotation_origin': annotation_origin,
                    'box_count': int(material.get('box_count') or 0),
                    'labels': list(material.get('labels') or []),
                })
        if page is None:
            projection['annotation_audit'] = self._v47_durable_annotation_audit(task_id, project_id)
        return {'items': items, **projection}

    def _v47_durable_annotation_audit(self,
        task_id: str,
        project_id: Optional[str] = None,
        *,
        cursor: str = '',
        limit: int = 100,
        page: Optional[int] = None,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        path = self.dependencies.shared_task_artifacts().artifact_path(task_id, MATERIAL_BATCH_SELECTION_REF)
        if not path.is_file():
            empty = {
                'enabled': False, 'audited_images': 0, 'review_images': 0,
                'warning_count': 0, 'items': [], 'next_cursor': None,
            }
            if page is None:
                return empty
            if page != 1:
                raise HTTPException(status_code=422, detail='page exceeds total_pages (1)')
            return {**empty, 'page': 1, 'page_size': page_size, 'total': 0,
                    'total_pages': 1, 'has_previous': False, 'has_next': False}
        from platform_core.annotation_quality import read_annotation_audit
        try:
            with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as database:
                audit_page = read_annotation_audit(
                    database, cursor=cursor, limit=limit, page=page, page_size=page_size,
                )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        items = list(audit_page.get('items') or [])
        if project_id and items:
            indexed = {
                str(row.get('id')): self.dependencies.public_material(project_id, row)
                for row in self.dependencies.material_store(project_id).get_many(
                    [str(item.get('image_id')) for item in items]
                )
            }
            for item in items:
                material = indexed.get(str(item.get('image_id'))) or {}
                item['url'] = material.get('url') or ''
        return {**audit_page, 'items': items}

    def _v47_frozen_clean_selection_ids(self, task_id: str) -> List[str]:
        path = self.dependencies.shared_task_artifacts().artifact_path(task_id, MATERIAL_BATCH_SELECTION_REF)
        if not path.is_file():
            return []
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as database:
            if database.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='selection'"
            ).fetchone() is None:
                return []
            return [
                str(row[0])
                for row in database.execute(
                    'SELECT image_id FROM selection ORDER BY image_id'
                ).fetchall()
            ]

    def _linked_deletion_hashes(self, project_id, plan_id, skipped, *, preview=False):
        repository = self.dependencies.shared_task_repository()
        artifacts = self.dependencies.shared_task_artifacts()
        if preview:
            path = artifacts.artifact_path(plan_id, _material_integrity_plan_ref(plan_id))
        else:
            deletion = repository.get(plan_id)
            if deletion is None or deletion.project_id != project_id or deletion.kind is not TaskKind.MATERIAL_BATCH:
                raise HTTPException(409, detail='删除任务尚未登记或与当前项目不一致')
            body = artifacts.read_json(plan_id, deletion.payload_ref, default={}) or {}
            if body.get('operation') != 'DELETE_INDEX' or (body.get('options') or {}).get('material_integrity_plan_id') != plan_id:
                raise HTTPException(409, detail='删除任务未绑定原删除计划')
            path = artifacts.artifact_path(plan_id, MATERIAL_BATCH_SELECTION_REF)
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as database:
                if preview:
                    metadata = _json_metadata(database)
                    if (metadata.get('project_id') != project_id or metadata.get('plan_id') != plan_id
                            or metadata.get('general_deletion') is not True):
                        raise HTTPException(409, detail='删除预检计划与当前项目不一致')
                    rows = database.execute("SELECT image_id,content_sha256 FROM plan_items WHERE action='DELETE'")
                else:
                    rows = database.execute('SELECT s.image_id, p.content_sha256 FROM selection s '
                                            'LEFT JOIN integrity_plan_items p ON p.image_id=s.image_id')
                hashes = {str(image_id): str(digest or '').lower() for image_id, digest in rows}
        except sqlite3.Error as error:
            raise HTTPException(409, detail='原删除计划缺少冻结证据') from error
        if hashes.keys() != skipped or not all(hashes.values()):
            raise HTTPException(409, detail='排除项与原删除冻结范围或素材身份不一致')
        return hashes

    def _v47_validate_clean_confirmation(self, project_id: str, task_id: str, *, skip_image_ids=(), skipped_source_hashes=None) -> set[str]:
        """Fail closed before any destructive or processed-status confirmation."""
        from platform_core.cleaning_batches import clean_result_source_sha256

        path = self.dependencies.shared_task_artifacts().artifact_path(task_id, MATERIAL_BATCH_SELECTION_REF)
        if not path.is_file():
            raise HTTPException(status_code=409, detail='清洗冻结范围不存在，请重新创建任务')
        materials = self.dependencies.material_store(project_id)
        accepted = set()
        cursor = ''
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as database:
            database.execute('BEGIN')
            tables = {
                str(row[0])
                for row in database.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('selection','clean_results')"
                )
            }
            if tables != {'selection', 'clean_results'}:
                raise HTTPException(status_code=409, detail='清洗结果证据不完整，请重新清洗')
            while True:
                rows = database.execute(
                    'SELECT s.image_id,s.state,r.result_json FROM selection s '
                    'LEFT JOIN clean_results r ON r.image_id=s.image_id '
                    'WHERE s.image_id>? ORDER BY s.image_id LIMIT 500', (cursor,),
                ).fetchall()
                if not rows:
                    break
                cursor = str(rows[-1][0])
                current = {
                    str(row.get('id')): str(row.get('content_sha256') or '').strip().lower()
                    for row in materials.get_many([str(row[0]) for row in rows])
                }
                for image_id, state, raw_result in rows:
                    if state != 'succeeded' or not raw_result:
                        raise HTTPException(
                            status_code=409,
                            detail='清洗尚有未成功素材，不能确认；请先重试或创建新的清洗任务',
                        )
                    try:
                        result = json.loads(raw_result)
                        source_hash = clean_result_source_sha256(result)
                    except (TypeError, ValueError, AttributeError):
                        source_hash = ''
                    if (skipped_source_hashes is not None and str(image_id) in skip_image_ids
                            and source_hash != skipped_source_hashes.get(str(image_id))):
                        raise HTTPException(409, detail='删除计划与清洗结果的素材代际不一致')
                    if not source_hash or (str(image_id) not in skip_image_ids and source_hash != current.get(str(image_id), '')):
                        raise HTTPException(
                            status_code=409,
                            detail='素材内容已变化或清洗结果无可信哈希，请重新清洗后确认',
                        )
                    accepted.add(str(image_id))
        if not accepted:
            raise HTTPException(status_code=409, detail='清洗冻结范围不存在，请重新创建任务')
        return accepted

    def _v47_apply_clean_scheduling(self, task_id: str) -> Dict[str, Any]:
        request = self.dependencies._v47_material_batch_request(task_id)
        scheduling = dict(request.get('scheduling') or {})
        mode = str(scheduling.get('mode') or 'auto')
        policy = str(scheduling.get('queue_policy') or 'normal')
        node_id = str(scheduling.get('node_id') or '')
        if mode != 'node':
            return {'mode': 'auto', 'queue_policy': 'normal'}
        repository = self.dependencies.shared_task_repository()
        allocator = CentralTaskAllocator(repository, self.dependencies.shared_task_artifacts())
        if policy == 'front':
            promoted = repository.promote(task_id)
            event = {
                'mode': 'node',
                'queue_policy': 'front',
                'node_id': node_id,
                'incoming_task_id': task_id,
                'priority': promoted.priority,
                'queue_rank': promoted.queue_rank,
                'created_at': self.dependencies.now_iso(),
            }
        elif policy == 'preempt':
            event = allocator.preempt_for(task_id, node_id)
            event['queue_policy'] = 'preempt'
        else:
            event = {
                'mode': 'node',
                'queue_policy': 'normal',
                'node_id': node_id,
                'incoming_task_id': task_id,
                'created_at': self.dependencies.now_iso(),
            }
        self.dependencies.shared_task_artifacts().atomic_write_json(task_id, 'scheduling.json', event)
        return event
