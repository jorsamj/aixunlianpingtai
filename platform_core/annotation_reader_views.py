"""Bounded read projections of original annotation Task/Candidate facts only."""
from urllib.parse import quote
from .training_reader_views import fields, text
from .model_asset_views import filename

COUNT_KEYS=('total','success','empty','failed','accepted','rejected','unreviewed','boxes','gt_committed')
def task_display(raw):
    result=fields(raw,('id','project_id','kind','status','persisted_status','name','model_config_name','model_provider','created_at','updated_at','finished_at','phase','progress_percent','worker_id','resource_wait_reason','error','accepted','statistics_synced_at','generation_interruption_code','review_scope_policy'))
    source=raw.get('stage_statistics') or raw.get('summary') or {}
    known=isinstance(source,dict) and all(type(source.get(key)) is int and source[key]>=0 for key in COUNT_KEYS)
    if known:
        known=(source['total']==source['success']+source['empty']+source['failed'] and source['success']+source['empty']==source['accepted']+source['rejected']+source['unreviewed'] and source['gt_committed']<=source['accepted'])
    result['statistics_known']=known
    result['counts']={key:source[key] if known else None for key in COUNT_KEYS}
    result['total_count']=raw.get('total_count') if type(raw.get('total_count')) is int and raw['total_count']>0 else (0 if known and source['total']==0 else None)
    result['completed_count']=source['total'] if known else None
    result['remaining_count']=max(0,result['total_count']-source['total']) if known and result['total_count'] is not None else None
    result['requested_labels']=[text(value,160) for value in (raw.get('requested_labels') or [])[:100] if isinstance(value,str)]
    return result

def failure_display(project_id,row):
    result=fields(row,('image_id','status','width','height','error','error_code','error_stage','http_status','attempt_count','retry_suggestion'))
    result['filename']=filename(row.get('filename') or row.get('image_id'))
    root=f'/api/v61/projects/{quote(str(project_id),safe="")}/materials/{quote(str(row.get("image_id") or ""),safe="")}/content'
    result['thumbnail_url']=root+'/thumbnail?edge=384'
    return result

def failure_page(project_id,task_id,value):
    return {'ok':True,'project_id':project_id,'task_id':task_id,'items':[failure_display(project_id,row) for row in value.get('items',[])],
        'next_cursor':value.get('next_cursor'),'total':value.get('total'),'review_revision':value.get('review_revision'),
        'task_error':fields(value.get('task_error'),('code','stage','message')) if value.get('task_error') else None}
