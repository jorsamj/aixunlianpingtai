"""Read-only v62 task HTTP boundary; execution and persistence retain their owners."""
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Query
from platform_core.task_runtime import TaskKind, TaskStatus, WorkerInstanceService, task_to_public
from ..algorithm_repository import open_algorithm_repository


def create_task_query_router(
    get_project: Callable,
    shared_task_repository: Callable,
    shared_task_artifacts: Callable,
    algorithms_file: Callable,
    _runtime_task_for_project: Callable,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v62/projects/{project_id}/tasks")
    def list_unified_runtime_tasks(
        project_id: str,
        kind: Optional[str] = Query(default=None),
        limit: int = Query(default=50, ge=1, le=100),
        cursor: Optional[str] = Query(default=None),
        reader_view: bool = False, status: str = '', query: str = '',
    ):
        get_project(project_id)
        if reader_view:
            from platform_core.training_reader_views import task_display,attach_version_refs
            from platform_core.algorithm_sql_store import AlgorithmSqlStore
            try:
                kinds=(TaskKind.TRAINING,TaskKind.TRAINING_PREPARE) if not kind else (TaskKind(str(kind).upper()),)
                if any(item not in (TaskKind.TRAINING,TaskKind.TRAINING_PREPARE) for item in kinds):raise ValueError('只读训练中心仅支持训练及准备任务')
                statuses=(TaskStatus(status),) if status else None
                page=shared_task_repository().list(project_id=project_id,kinds=kinds,statuses=statuses,task_query=query,limit=limit,cursor=cursor)
            except ValueError as error:raise HTTPException(422,detail=str(error)) from error
            rows=[task_display(task,shared_task_artifacts()) for task in page.items]
            refs=open_algorithm_repository(algorithms_file(project_id)).training_display_refs([task.task_id for task in page.items])
            return {'ok':True,'project_id':project_id,'items':attach_version_refs(rows,refs),'next_cursor':page.next_cursor,'filter_options':{'status':[item.value for item in TaskStatus],'kind':[TaskKind.TRAINING.value,TaskKind.TRAINING_PREPARE.value]}}
        kinds = None
        if kind:
            try:
                kinds = (TaskKind(str(kind).strip().upper()),)
            except ValueError as error:
                raise HTTPException(status_code=422, detail=f"未知任务类型：{kind}") from error
        repository = shared_task_repository()
        try:
            page = repository.list(project_id=project_id, kinds=kinds, limit=limit, cursor=cursor)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        queue_positions = repository.resource_queue_positions(
            task.task_id for task in page.items if task.status is TaskStatus.QUEUED
        )
        needs_queue_evidence = any(
            task.status is TaskStatus.QUEUED
            and task.kind is not TaskKind.TRAINING
            for task in page.items
        )
        worker_runtime = None
        queued_candidates = None
        if needs_queue_evidence:
            worker_runtime = WorkerInstanceService(repository).list_runtime()
            queued_candidates = repository.queued_candidates()
        return {
            "items": [
                task_to_public(
                    task, repository,
                    queue_positions=queue_positions,
                    worker_runtime=worker_runtime,
                    queued_candidates=queued_candidates,
                )
                for task in page.items
            ],
            "next_cursor": page.next_cursor,
        }


    @router.get("/api/v62/projects/{project_id}/tasks/{task_id}")
    def get_unified_runtime_task(project_id: str, task_id: str, reader_view: bool=False):
        if reader_view:
            from platform_core.training_reader_views import task_display,attach_version_refs
            from platform_core.algorithm_sql_store import AlgorithmSqlStore
            task=_runtime_task_for_project(project_id,task_id)
            if task.kind not in (TaskKind.TRAINING,TaskKind.TRAINING_PREPARE):raise HTTPException(404,detail='训练任务不存在')
            rows=attach_version_refs([task_display(task,shared_task_artifacts(),detail=True)],open_algorithm_repository(algorithms_file(project_id)).training_display_refs([task_id]))
            if task.kind is TaskKind.TRAINING:
                child = shared_task_repository().get(f'trainprep_{task_id}')
                if child and child.project_id == project_id and child.kind is TaskKind.TRAINING_PREPARE:
                    rows[0]['related_task_id'] = child.task_id
            elif parent_id := rows[0].pop('related_task_id', None):
                parent = shared_task_repository().get(parent_id)
                if parent and parent.project_id == project_id and parent.kind is TaskKind.TRAINING:
                    rows[0]['related_task_id'] = parent_id
            return {'ok':True,'project_id':project_id,'task':rows[0]}
        repository = shared_task_repository()
        return task_to_public(_runtime_task_for_project(project_id, task_id), repository)


    return router
