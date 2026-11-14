"""Additive project-scoped API. Existing business authorization is injected."""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from fastapi import APIRouter, Body, HTTPException, Request

from ..material_batches import BatchRequestError, public_batch
from ..task_runtime import TaskKind
from ..material_repository import MaterialRepository
from ..storage.manager import StorageManager
from ..storage.source_repository import StorageSourceRepository
from ..storage.import_tasks import _provider
from ..storage.errors import StorageError
from ..algorithm_sql_store import AlgorithmSqlStore
from ..algorithms import is_trainable_version
from . import audit_configuration
from .service import OPERATION, configuration, project_path, estimate_audit, create_audit, reject
from .results import findings_page, review_finding


def smart_material_audit_router(get_project,data_dir_provider,task_repository,task_artifacts,*,actor_provider):
    router=APIRouter(prefix='/api/v62/projects/{project_id}/smart-material-audit')

    def invoke(function,*args,**kwargs):
        try:
            return function(*args,**kwargs)
        except BatchRequestError as error:
            raise HTTPException(error.status_code,detail={'code':error.code,'message':str(error)}) from error
        except (ValueError,TypeError) as error:
            raise HTTPException(422,detail={'code':'SMART_AUDIT_INVALID_REQUEST','message':str(error)}) from error
        except StorageError as error:
            changed=error.code in {'SOURCE_CONTENT_CHANGED','STORAGE_SHA256_MISMATCH','MATERIAL_NOT_FOUND'}
            raise HTTPException(409 if changed else 503,detail={'code':'SMART_AUDIT_EVIDENCE_CHANGED' if changed else 'SMART_AUDIT_DATA_UNAVAILABLE',
                'message':'原图身份已变化，请重新核验' if changed else '素材存储暂不可用，请稍后重试'}) from error
        except (sqlite3.Error,OSError) as error:
            raise HTTPException(503,detail={'code':'SMART_AUDIT_DATA_UNAVAILABLE','message':'分析数据或存储暂不可用；原业务不变，可稍后重试'}) from error

    def task_for(project_id,task_id):
        get_project(project_id)
        task=task_repository().get(task_id)
        if not task or task.project_id!=project_id or task.kind!=TaskKind.MATERIAL_BATCH:
            raise HTTPException(404,detail='smart audit task not found')
        payload=task_artifacts().read_json(task_id,task.payload_ref,default={})
        if payload.get('operation')!=OPERATION:
            raise HTTPException(404,detail='smart audit task not found')
        return task

    def result_for(task,generation):
        chosen=task.attempt if generation is None else generation
        if chosen<=0 or chosen>task.attempt:
            raise HTTPException(409,detail={'code':'SMART_AUDIT_NOT_READY','message':'当前分析尚未生成结果'})
        if chosen==task.attempt and not task.result_ref:
            raise HTTPException(409,detail={'code':'SMART_AUDIT_NOT_READY','message':'当前分析未完成；历史结果不会冒充本次结果'})
        path=task_artifacts().artifact_path(task.task_id,f'smart-audit/{chosen}/findings.sqlite3')
        if not path.is_file():
            raise HTTPException(409,detail={'code':'SMART_AUDIT_NOT_READY','message':'分析结果尚不可用'})
        return path,chosen

    @router.get('/status')
    def status(project_id:str):
        get_project(project_id)
        try:
            value=audit_configuration(data_dir_provider())
            enabled=value['enabled']
            return {'enabled':enabled,'max_images':value['max_images'],'feature':'hog-color-v1',
                'environment_validation':'not_checked','read_only':True,
                'message':'需使用独立venv，实际环境由任务执行核验' if enabled else '智能分析未启用，原清洗、审核、标注和训练不受影响'}
        except (ValueError,OSError):
            return {'enabled':False,'environment_validation':'invalid_configuration','message':'智能分析配置不可用，原业务不受影响'}

    @router.post('/estimate')
    def estimate(project_id:str,payload:dict=Body(...)):
        get_project(project_id)
        return invoke(estimate_audit,data_dir_provider(),project_id,payload.get('selection_spec'))

    @router.post('',status_code=202)
    def create(project_id:str,request:Request,payload:dict=Body(...)):
        get_project(project_id)
        actor=actor_provider(request,project_id)
        task=invoke(create_audit,data_dir_provider(),project_id,task_repository(),task_artifacts(),payload,actor=actor)
        return public_batch(task,task_artifacts(),task_repository())

    @router.get('/models')
    def models(project_id:str,cursor:str='',limit:int=25):
        get_project(project_id)
        if not 1<=limit<=50:
            raise HTTPException(422,detail='invalid model page')
        def read():
            project=project_path(data_dir_provider(),project_id)
            if not audit_configuration(data_dir_provider())['enabled']:
                return {'items':[],'next_cursor':None,'enabled':False}
            path=project/'algorithms.sqlite3'
            if not path.is_file():
                return {'items':[],'next_cursor':None,'reason':'旧算法存储未迁移，智能分析不会执行迁移'}
            store=AlgorithmSqlStore(project/'algorithms.json')
            with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
                db.row_factory=sqlite3.Row
                if not store._initialization_complete(db):
                    return {'items':[],'next_cursor':None,'reason':'算法存储缺少可验证版本'}
                rows=db.execute('SELECT v.* FROM algorithm_versions v JOIN algorithms a ON a.id=v.algorithm_id WHERE a.project_id=? AND v.id>? ORDER BY v.id LIMIT ?',
                    (project_id,cursor,limit+1)).fetchall()
                items=[]
                for row in rows[:limit]:
                    version=store._version_from_row(row)
                    if is_trainable_version(version,'ultralytics') and (version.get('evaluation') or {}).get('status')=='succeeded':
                        name=db.execute('SELECT name FROM algorithms WHERE id=?',(row['algorithm_id'],)).fetchone()[0]
                        items.append({'algorithm_id':row['algorithm_id'],'version_id':version['id'],
                            'label':name+' / '+str(version.get('version_name') or version['id']),
                            'validation':'metadata_only; bytes and benchmark reverified in Worker'})
                return {'items':items,'next_cursor':rows[limit-1]['id'] if len(rows)>limit else None}
        return invoke(read)

    @router.get('/{task_id}/findings')
    def findings(project_id:str,task_id:str,offset:int=0,limit:int=25,issue_type:str='',generation:int|None=None):
        task=task_for(project_id,task_id)
        path,chosen=result_for(task,generation)
        result=invoke(findings_page,path,project_path(data_dir_provider(),project_id),offset=offset,limit=limit,issue_type=issue_type)
        return {**result,'task_id':task_id,'project_id':project_id,'historical_generation':chosen!=task.attempt}

    @router.post('/{task_id}/retry',status_code=202)
    def retry(project_id:str,task_id:str):
        task=task_for(project_id,task_id)
        if task.status.value not in {'FAILED','CANCELLED','PARTIAL_SUCCESS','BLOCKED_BY_ENVIRONMENT','BLOCKED_BY_HARDWARE'}:
            raise HTTPException(409,detail='only incomplete terminal smart audits can be retried')
        invoke(configuration,data_dir_provider())
        task=invoke(task_repository().retry,task_id)
        return public_batch(task,task_artifacts(),task_repository())

    @router.get('/{task_id}/findings/{issue_id}')
    def detail(project_id:str,task_id:str,issue_id:str,generation:int|None=None):
        task=task_for(project_id,task_id);path,chosen=result_for(task,generation)
        result=invoke(findings_page,path,project_path(data_dir_provider(),project_id),issue_id=issue_id,limit=1)
        if not result['items']:
            raise HTTPException(404,detail='smart audit finding not found')
        return {**result['items'][0],'generation':chosen,'historical_generation':chosen!=task.attempt}

    @router.post('/{task_id}/findings/{issue_id}/review')
    def review(project_id:str,task_id:str,issue_id:str,request:Request,payload:dict=Body(...)):
        task=task_for(project_id,task_id)
        expected=payload.get('expected_generation')
        if isinstance(expected,bool) or not isinstance(expected,int) or expected!=task.attempt:
            raise HTTPException(409,detail={'code':'SMART_AUDIT_GENERATION_CHANGED','message':'分析代际已变化，请重新读取当前结果'})
        payload={key:value for key,value in payload.items() if key!='expected_generation'}
        path,_=result_for(task,None)
        actor=actor_provider(request,project_id)
        project=project_path(data_dir_provider(),project_id)
        def execute():
            page=findings_page(path,project,issue_id=issue_id,limit=1)
            if not page['items']:
                reject('SMART_AUDIT_FINDING_NOT_FOUND','分析候选不存在',404)
            # Original StorageManager verifies actual source bytes before review.
            materials=MaterialRepository.open_readonly(project)
            sources=StorageSourceRepository.open_readonly(Path(data_dir_provider())/'storage/storage_sources.sqlite3')
            manager=StorageManager(data_dir=data_dir_provider(),project_id=project_id,materials=materials,sources=sources,
                provider_resolver=lambda source,_secret:_provider(Path(data_dir_provider()),project_id,source),cache_maintenance=False)
            for image_id,facts in page['items'][0]['inputs'].items():
                local=manager.materialize(image_id,read_only=True)
                if local.content_sha256!=facts.get('content_sha256'):
                    reject('SMART_AUDIT_EVIDENCE_CHANGED','原图字节与分析输入不一致')
            current=task_for(project_id,task_id)
            if current.attempt!=task.attempt or current.result_ref!=task.result_ref:
                reject('SMART_AUDIT_GENERATION_CHANGED','任务已重试，请核验新的分析结果')
            return review_finding(path,project,issue_id,payload,actor_id=actor.get('actor_id',''))
        return invoke(execute)
    return router
