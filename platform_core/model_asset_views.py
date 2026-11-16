"""Bounded display projections only. Original repositories and task truth remain owners."""
import re
from pathlib import Path

METRICS=('map50','mAP50','map50_95','mAP50_95','precision','recall','metrics/mAP50(B)','metrics/mAP50-95(B)')
PARAMETERS=('epochs','batch','imgsz','precision','optimizer','lr0','patience','seed','workers','device')
CONVERSION_PARAMS=('precision','chip','soc_version','batch','input_size','input_width','input_height','num_core','dynamic','opset','simplify','csc_preset','csc_mode','input_color','output_color','target_environment','sdk_version','sdk_chip_code','local_vendor_id','local_chip_id','template_id','constraint_id','source_training_precision')

def text(value,limit=512):
    if not isinstance(value,str):return value if type(value) in (int,float,bool) or value is None else None
    value=re.sub(r'https?://\S+','[地址已隐藏]',value)
    value=re.sub(r'(?i)\bBearer\s+[^\s,;}"\']+','Bearer [已隐藏]',value)
    value=re.sub(r'''(?i)(token|password|secret|api[_-]?key|authorization)["']?\s*[:=]\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}]+)''',r'\1=[已隐藏]',value)
    value=re.sub(r'\\\\[^\s,;"\']+','[路径已隐藏]',value)
    value=re.sub(r'[A-Za-z]:[\\/][^\s,;]*|(?<!\w)/(?:[\w.\-]+/)*[\w.\-]+','[路径已隐藏]',value)
    return value[:limit]

def filename(value):return str(value or '').replace('\\','/').rsplit('/',1)[-1][:240]

def fields(value,keys):
    if not isinstance(value,dict):return {}
    return {key:text(value[key]) if not isinstance(value[key],list) else [text(x) for x in value[key][:8] if type(x) in (str,int,float,bool)] for key in keys if key in value and (value[key] is None or type(value[key]) in (str,int,float,bool,list))}

def json_fields(path,keys,column='v.payload_json'):
    # Callers supply static field lists only, never user-controlled SQL paths.
    args=[]
    for key in keys:args.extend(["'"+key+"'",f"json_extract({column}, '$.{path}{key}')"])
    return 'json_object('+','.join(args)+')'

def version_columns(detail=False):
    base='v.id,v.algorithm_id,v.version_name,v.version_no,v.training_job_id,v.framework,v.training_status,v.artifact_verified,v.trainable,v.external_publish_status,v.created_at,v.finished_at,v.stored_path,v.model_name'
    extra=json_fields('',('size_bytes','size_mb','sha256','model_sha256','format','source_type','status','parent_version_id','base_version_id','artifact_id','map50','mAP50'))
    cols=base+','+extra+' AS display_json'
    cols+=','+json_fields('metrics.',METRICS)+' AS metrics_json'
    cols+=','+json_fields('evaluation.metrics.',METRICS)+' AS test_metrics_json'
    if detail:
        cols+=','+json_fields('val_metrics.',METRICS)+' AS val_metrics_json'
        cols+=','+json_fields('training_lineage.parameters.actual.',PARAMETERS)+' AS parameters_json'
        cols+=','+json_fields('training_lineage.',('base_version_id','parent_version_id','source_version_id','task_id','snapshot_id','algorithm_id','version_id','iteration'))+' AS lineage_json'
        cols+=','+json_fields('model_metadata.',('image_width','image_height','framework_version','class_count','label_source','label_validation_status','yolo_version'))+' AS metadata_json'
        cols+=",(SELECT json_group_array(value) FROM (SELECT value FROM json_each(v.payload_json,'$.label_codes') LIMIT 256)) AS classes_json"
        cols+=",json_array_length(v.payload_json,'$.label_codes') AS class_count"
    return cols

def version_record(row,decode):
    row=dict(row);payload=decode(row.pop('display_json'))
    name=filename(row.pop('stored_path',None) or row.get('model_name'))
    result={key:text(value) for key,value in row.items() if key not in ('metrics_json','test_metrics_json','val_metrics_json','parameters_json','lineage_json','metadata_json','classes_json','class_count')}
    result.update(fields(payload,('source_type','status','parent_version_id','base_version_id','artifact_id','map50','mAP50')))
    result['artifact_verified']=None if row.get('artifact_verified') is None else bool(row['artifact_verified'])
    result['trainable']=None if row.get('trainable') is None else bool(row['trainable'])
    result['model_file']={'file_name':name or None,'extension':name.rsplit('.',1)[-1].lower() if '.' in name else None,**fields(payload,('format','size_bytes','size_mb','sha256','model_sha256')),'availability':'UNVERIFIED'}
    for source,target in [('metrics_json','metrics'),('test_metrics_json','test_metrics'),('val_metrics_json','val_metrics'),('parameters_json','training_parameters'),('lineage_json','training_lineage'),('metadata_json','model_metadata')]:
        if source in row:result[target]={key:text(value) if not isinstance(value,list) else [text(x) for x in value[:8]] for key,value in decode(row[source]).items() if value is None or type(value) in (str,int,float,bool,list)}
    if 'classes_json' in row:
        import json
        result['classes']=[text(value) for value in json.loads(row['classes_json'] or '[]') if isinstance(value,str)]
        result['class_count']=row['class_count'];result['classes_truncated']=bool((row['class_count'] or 0)>len(result['classes']))
    return result

def conversion_record(job,root):
    result=fields(job,('id','target','target_name','status','stage','progress','task_id','task_status','durable_status','worker_id','created_at','started_at','finished_at','conversion_status','validation_status','runtime_verified','hardware_verified','numeric_status','publication_status','resource_wait_reason','queue_rank','resource_queue_position','source_name','error_code','error','message','solution'))
    result.setdefault('numeric_status',None);result.setdefault('publication_status',None)
    result['resource_name']=text((job.get('resource') or {}).get('name'))
    result['params']=fields(job.get('params'),CONVERSION_PARAMS)
    result['requested_params']=fields(job.get('requested_params'),CONVERSION_PARAMS)
    # Preserve the existing nested CSC contract without deriving SDK capability.
    for source,target in [('params','params'),('requested_params','requested_params')]:
        params=job.get(source) or {}
        for key,value in fields(params.get('csc'),('preset','input_format','require_embedded','model_only','deployment_contract_acknowledged','execution_location','output_color_order')).items():
            result[target]['csc.'+key]=value
    result['source_identity']=fields(job.get('source_trace'),('source_id','sha256','algorithm_id','version_id','artifact_id'))
    result['execution_evidence']=fields(job.get('execution_evidence'),('node_id','worker_id','sdk_version','chip','precision','framework','started_at','finished_at','status','error_code','message'))
    result['hardware_verification']=fields(job.get('hardware_verification'),('status','verified','chip','verified_at','error_code','message','solution'))
    outputs=[]
    for item in (job.get('outputs') or [])[:20]:
        if not isinstance(item,dict):continue
        exists=None;raw=item.get('path')
        if isinstance(raw,str) and raw:
            try:
                path=Path(raw).resolve()
                if path.is_relative_to(Path(root).resolve()):exists=path.is_file()
            except (OSError,ValueError):pass
        outputs.append({'file_name':filename(item.get('name') or raw),**fields(item,('sha256','size_mb','size_bytes','validation_status')),'exists':exists})
    result['outputs']=outputs;result['outputs_truncated']=len(job.get('outputs') or [])>len(outputs)
    return result
