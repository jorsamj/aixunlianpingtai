"""Bounded presentation of existing Task artifacts; no task execution or GT reads."""
import json
from pathlib import Path
from .model_asset_views import fields,text,METRICS,PARAMETERS
from .task_runtime.public import task_to_public
from .task_runtime.payload_publications import VERSION_REF, PayloadPublicationError

CONFIG=PARAMETERS+('framework','model','requested_device','gpu_policy','precision','target','training_target','resource_id','node_id')

def attach_version_refs(rows,refs):
    for row in rows:
        match=refs.get(row['task_id'])
        if not match:continue
        conflict=match['reference_count']!=1 or bool(row.get('algorithm_id') and row['algorithm_id']!=match['algorithm_id']) or bool(row.get('version_id') and row['version_id']!=match['version_id'])
        row['identity_conflict']=row.get('identity_conflict',False) or conflict
        if not conflict:row.update({key:match[key] for key in ('algorithm_id','algorithm_name','version_id')})
    return rows

def bounded_json(path,limit=2*1024*1024):
    try:
        with Path(path).open('rb') as stream:
            raw=stream.read(limit+1)
        if len(raw)>limit:return {},'DEFERRED'
        value=json.loads(raw)
        return (value,'AVAILABLE') if isinstance(value,dict) else ({},'ERROR')
    except FileNotFoundError:return {},'MISSING'
    except (OSError,ValueError,UnicodeError):return {},'ERROR'

def _read_task_payload(task, artifacts, limit):
    try:
        if VERSION_REF.fullmatch(task.payload_ref):
            payload = artifacts.payload_reader.read_payload_version(task.task_id, task.payload_ref, max_bytes=limit).data
            payload, state = (payload, 'AVAILABLE') if isinstance(payload, dict) else ({}, 'ERROR')
        else:
            payload, state = bounded_json(artifacts.artifact_path(task.task_id, task.payload_ref), limit=limit)
    except PayloadPublicationError as error:
        payload, state = {}, {'PAYLOAD_SIZE_LIMIT': 'DEFERRED', 'PAYLOAD_VERSION_MISSING': 'MISSING'}.get(error.code, 'ERROR')
    except ValueError:
        payload, state = {}, 'ERROR'
    return payload, state

def task_display(task,artifacts,detail=False):
    raw=task_to_public(task)  # Original status owner; deliberately no queue/worker scan.
    result=fields(raw,('task_id','project_id','kind','status','persisted_status','phase','progress_percent','created_at','updated_at','finished_at','worker_id','resource_key','resource_wait_reason','error','attempt'))
    limit = 512 * 1024 if detail else 32 * 1024
    payload, state = _read_task_payload(task, artifacts, limit)
    result['metadata_state']=state
    identity=payload.get('algorithm_identity') or {}
    ids={str(value) for value in (payload.get('asset_algorithm_id'),payload.get('algorithm_asset_id'),identity.get('id')) if value}
    result['algorithm_id']=text(next(iter(ids))) if len(ids)==1 else None
    result['algorithm_name']=text(payload.get('asset_algorithm_name') or identity.get('name'))
    result['version_id']=text(payload.get('auto_version_id') or payload.get('version_id'))
    result['identity_conflict']=len(ids)>1
    result['report_job_id']=task.task_id if task.kind.value=='TRAINING' else None
    if detail:
        if task.kind.value == 'TRAINING_PREPARE':
            parent_id = str(payload.get('training_task_id') or '')
            if parent_id and task.task_id == f'trainprep_{parent_id}':
                result['related_task_id'] = parent_id
        result['configuration']=fields(payload,CONFIG)
        result['requested_execution']=fields(payload.get('execution'),CONFIG)
        finalized,final_state=bounded_json(artifacts.artifact_path(task.task_id,'result.json'))
        result['result_state']=final_state
        result['execution']=fields(finalized.get('execution'),('node_id','worker_id','device','gpu_name','started_at','finished_at','hostname','status'))
        result['started_at']=text(finalized.get('started_at') or (finalized.get('execution') or {}).get('started_at'))
    return result

def metrics(value):
    import math
    value=value if isinstance(value,dict) else {}
    aliases={'precision':('precision','metrics/precision(B)'),'recall':('recall','metrics/recall(B)'),
             'map50':('map50','mAP50','metrics/mAP50(B)'), 'map50_95':('map50_95','mAP50_95','metrics/mAP50-95(B)')}
    return {key:next((value[name] for name in names if type(value.get(name)) in (int,float) and math.isfinite(value[name])),None) for key,names in aliases.items()}

def _split_sample_evidence(snapshot, snapshot_id):
    from .snapshots import snapshot_content_matches_identity

    if not snapshot_content_matches_identity(snapshot, snapshot_id):
        return {}
    counts = {role: {"positive": 0, "confirmed_negative": 0} for role in ('train', 'validation', 'test')}
    for row in snapshot.get('images', []):
        role = row.get('role')
        if role not in counts:
            return {}
        state, box_count = row.get('annotation_state'), row.get('box_count')
        if state == 'confirmed_empty' and box_count == 0:
            counts[role]["confirmed_negative"] += 1
        elif state == 'annotated' and type(box_count) is int and box_count > 0:
            counts[role]["positive"] += 1
        else:
            return {}
    totals = snapshot.get('counts') or {}
    return counts if all(sum(values.values()) == totals.get(role) for role, values in counts.items()) else {}


def report_display(job_id,task,artifacts,legacy_path,algorithm_id='',version_id='',history_offset=None,history_limit=200):
    from .reports import build_version_report,diagnose_training_history
    legacy,legacy_state=bounded_json(legacy_path)
    finalized,final_state=bounded_json(artifacts.artifact_path(job_id,'result.json')) if task else ({},'MISSING')
    if final_state in ('ERROR','DEFERRED'):return {'state':final_state,'message':'正式结果读取异常或超出摘要读取边界，请使用原报告入口'}
    if final_state=='MISSING' and legacy_state in ('ERROR','DEFERRED'):return {'state':legacy_state,'message':'历史报告记录读取异常或超出摘要读取边界'}
    if not task and legacy_state=='MISSING':return {'state':'NOT_FOUND','message':'没有此任务或报告记录'}
    for record in (legacy,finalized):
        trace=record.get('training_lineage') or {}
        if any(str(value)!=job_id for value in (record.get('id'),record.get('task_id'),trace.get('task_id')) if value):return {'state':'IDENTITY_CONFLICT','message':'任务报告身份冲突'}
        if algorithm_id and any(str(value)!=algorithm_id for value in (record.get('asset_algorithm_id'),record.get('algorithm_asset_id'),trace.get('algorithm_id')) if value):return {'state':'IDENTITY_CONFLICT','message':'算法报告身份冲突'}
        if version_id and any(str(value)!=version_id for value in (record.get('auto_version_id'),record.get('version_id'),trace.get('version_id')) if value):return {'state':'IDENTITY_CONFLICT','message':'版本报告身份冲突'}
    committed=finalized.get('training_report')
    committed=committed if isinstance(committed,dict) and committed else None
    report=committed or (legacy.get('training_report') if isinstance(legacy.get('training_report'),dict) else {})
    evaluation=finalized.get('evaluation') if isinstance(finalized.get('evaluation'),dict) else legacy.get('evaluation') or report.get('test_result') or {}
    canonical=build_version_report({**legacy,'training_report':report,'evaluation':evaluation,
        'metric_credibility':finalized.get('metric_credibility') if task else None})
    original_history=report.get('history') or []
    original_history=original_history if isinstance(original_history,list) else []
    history_total=len(original_history)
    history_start=max(0,history_total-200) if history_offset is None else history_offset
    history=[fields(row,('epoch','map50','map50_95','mAP50_95','map5095','precision','recall','f1','F1','box_loss','val_box_loss','cls_loss','val_cls_loss','dfl_loss','val_dfl_loss','learning_rate','duration_seconds','images_per_second')) for row in original_history[history_start:history_start+history_limit] if isinstance(row,dict)]
    quality=diagnose_training_history([fields(row,('epoch','map50','precision','recall','box_loss','val_box_loss','cls_loss','val_cls_loss','dfl_loss','val_dfl_loss')) for row in original_history[-200:] if isinstance(row,dict)])
    warnings=[text(row.get('phenomenon'))+'；'+text(row.get('action')) for row in quality['findings']]
    gates=report.get('gate_events') or legacy.get('gate_events') or []
    warnings.extend(text(row if isinstance(row,str) else row.get('message') or row.get('reason') or row.get('code')) for row in gates[:20] if isinstance(row,(str,dict)))
    has_metrics=any(value is not None for value in metrics(canonical['metrics']).values())
    state='AVAILABLE' if report else 'PARTIAL' if has_metrics else 'NOT_GENERATED'
    payload={}
    if task:
        payload, payload_state = _read_task_payload(task, artifacts, 512 * 1024)
        if payload_state in ('ERROR','DEFERRED'):
            warnings.append('任务配置无法核验或超出读取边界，其他已记录结果仍可查看。')
    configuration={
        **fields(payload,CONFIG),
        **fields(report.get('requested_train_params'),CONFIG),
        **fields(legacy.get('requested_train_params'),CONFIG),
        **fields(finalized.get('requested_train_params'),CONFIG),
    }
    actual={
        **fields(legacy.get('actual_train_params'),CONFIG),
        **fields(report.get('actual_train_params'),CONFIG),
        **fields(finalized.get('actual_train_params'),CONFIG),
    }
    historical={key:value for key,value in fields(legacy,CONFIG).items()
                if key not in configuration and key not in actual}
    result=fields({**legacy,**finalized},('status','created_at','started_at','finished_at','elapsed_seconds',
        'completed_epochs','requested_epochs','current_epoch','best_epoch','completion_reason','completion_message',
        'quality_gate_reason','early_stopping_reason','training_outcome','snapshot_id','dataset_revision_id'))
    if task:
        current=task_to_public(task)
        result['status']=current['status']
        result.update(fields(current,('error',)))
        if not result.get('finished_at'):
            result.update(fields(current,('finished_at',)))
    if result.get('elapsed_seconds') is None:
        telemetry=finalized.get('training_metrics') or {}
        duration=report.get('total_duration_seconds',telemetry.get('total_duration_seconds') if isinstance(telemetry,dict) else None)
        if type(duration) in (int,float):
            result['elapsed_seconds']=duration
    if result.get('best_epoch') is None:
        telemetry=finalized.get('training_metrics') or {}
        if isinstance(telemetry,dict):
            result.update(fields(telemetry,('best_epoch',)))
    sample_distribution = {}
    snapshot_id = finalized.get('snapshot_id')
    if task and isinstance(snapshot_id, str) and len(snapshot_id) == 64 and all(c in '0123456789abcdef' for c in snapshot_id):
        project = Path(legacy_path).parent.parent.parent
        snapshot, _ = bounded_json(project / 'snapshots' / f'{snapshot_id}.json')
        sample_distribution = _split_sample_evidence(snapshot, snapshot_id)
    best = report.get('best_metrics')
    return {'state':state,'source':'DURABLE_FINALIZED' if committed else 'LEGACY_RECORDED',
        'message':'仅展示已记录结果，未生成完整报告' if state in ('PARTIAL','NOT_GENERATED') else '',
        'configuration':configuration,'actual_parameters':actual,'historical_parameters':historical,'result':result,'sample_distribution':sample_distribution,
        'best_metrics':metrics(best) if isinstance(best,dict) and best else {},
        'val_metrics':metrics(canonical['metrics']),'test_metrics':metrics(evaluation.get('metrics') if isinstance(evaluation,dict) else {}),
        'test_status':text(evaluation.get('status')) if isinstance(evaluation,dict) else None,
        'credibility':fields(canonical.get('metric_credibility'),('status','level','message','reason','note','source')),
        'warnings':[value for value in warnings if value], 'quality_status':quality['status'],
        'history':history,'history_truncated':history_start>0 or history_start+history_limit<history_total,'history_total':history_total,'history_offset':history_start,'history_limit':history_limit,'history_has_next':history_start+history_limit<history_total}
