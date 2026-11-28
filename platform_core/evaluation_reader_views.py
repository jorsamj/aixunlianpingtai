"""Bounded display of persisted evaluation evidence. No rescoring or image reads."""
import json
from urllib.parse import quote, urlencode
from .training_reader_views import fields, text, metrics
from .model_asset_views import filename
METRICS=('precision','recall','map50','map50_95','f1','false_positive','false_negative')
METRIC_ALIASES={'metrics/precision(B)':'precision','metrics/recall(B)':'recall',
                'metrics/mAP50(B)':'map50','metrics/mAP50-95(B)':'map50_95'}
CLASS=('class_id','label','evaluation_status','precision','recall','map50','map50_95','f1','true_positive','false_positive','false_negative','ground_truth_count','prediction_count')
def bounded(value):
    count=0
    for chunk in json.JSONEncoder(ensure_ascii=False).iterencode(value):
        count+=len(chunk.encode('utf-8'))
        if count>2*1024*1024:return False
    return True

def report_section(raw,section,offset,limit,class_id=None):
    result={'state':'AVAILABLE' if raw else 'NOT_GENERATED','evaluation_id':text(raw.get('evaluation_id')),'section':section,'offset':offset,'limit':limit,'total':0,'has_next':False,'evaluation':{}}
    if not bounded(raw):return {**result,'state':'DEFERRED','message':'评测证据超出2MiB安全读取边界，请使用原报告入口'}
    e=fields(raw,('evaluation_id','status','image_count','created_at','completed_at','confidence_curve_protocol',
                  'snapshot_id','dataset_revision_id','evaluation_protocol_id','historical_independence'))
    e['metrics']={**fields(raw.get('metrics'),METRICS),**metrics(raw.get('metrics'))}
    result['evaluation']=e
    classes=raw.get('per_class') or []
    classes=[row for row in classes if isinstance(row,dict)] if isinstance(classes,list) else []
    if section=='summary':
        e['class_count']=len(classes)
        e['benchmark_scope']=fields(raw.get('benchmark_scope'),('scope_id','content_digest','ground_truth_digest','label_schema_digest','evaluation_input_digest','binding_level'))
        return result
    if section=='classes':
        rows=classes
        e['per_class']=[fields(row,CLASS) for row in rows[offset:offset+limit]]
    elif section=='curves':
        rows=[row for row in (raw.get('confidence_curves') or []) if isinstance(row,dict) and (class_id is None or row.get('class_id')==class_id)]
        visible=rows[offset:offset+limit]
        ids={row.get('class_id') for row in visible}
        e['per_class']=[fields(row,CLASS) for row in classes if row.get('class_id') in ids][:100]
        e['confidence_curves']=[{**fields(row,('class_id',)), 'points':[fields(point,('confidence','precision','recall','f1','true_positive','false_positive','false_negative')) for point in (row.get('points') or [])[:21] if isinstance(point,dict)],'points_total':len(row.get('points') or []),'points_truncated':len(row.get('points') or [])>21} for row in visible]
    else:
        matrix=raw.get('confusion_matrix') or {}
        rows=[row for row in (matrix.get('cells') or []) if isinstance(row,dict) and (class_id is None or row.get('actual')==class_id or row.get('predicted')==class_id)]
        visible=rows[offset:offset+limit];ids={value for row in visible for value in (row.get('actual'),row.get('predicted'))}
        e['per_class']=[fields(row,CLASS) for row in classes if row.get('class_id') in ids][:100]
        e['confusion_matrix']={**fields(matrix,('protocol','operating_conf')), 'cells':[fields(row,('actual','predicted','count')) for row in visible],'cells_total':len(rows),'cells_truncated':offset>0 or offset+limit<len(rows)}
    result.update(total=len(rows),has_next=offset+limit<len(rows))
    return result

def samples_display(project,algorithm,version,value):
    result=fields(value,('total','offset','limit','evaluation_id','cohort_complete','image_count','diagnostic_low_confidence_threshold','filter_scope','filter_evidence_complete'))
    result['items']=[]
    for source in value.get('items',[]):
        row=fields(source,('image_id','image_content_sha256','image_width','image_height','width','height','tp_count','fp_count','fn_count','box_evidence_available','evidence_complete','diagnostic_tags'))
        row['image']=filename(source.get('image'));row['filename']=row['image']
        for key in ('gt_boxes','pred_boxes'):
            boxes=source.get(key) or []
            row[key]=[fields(box,('class_id','label','box','kind','prediction_index','target_index','matched_iou','confidence','matched','diagnostic_tags')) for box in boxes[:300] if isinstance(box,dict)]
            row[key+'_total']=len(boxes);row[key+'_truncated']=len(boxes)>300
        row['boxes_truncated']=source.get('boxes_truncated') is True or row['gt_boxes_truncated'] or row['pred_boxes_truncated']
        root=f'/api/v12/projects/{quote(project,safe="")}/algorithms/{quote(algorithm,safe="")}/versions/{quote(version,safe="")}/evaluation/images/{quote(row["image"],safe="")}'
        row['preview_url']=root+'?'+urlencode({'expected_evaluation_id':value.get('evaluation_id') or '', 'expected_image_id':source.get('image_id') or '', 'expected_sha256':source.get('image_content_sha256') or ''})
        original_name=source.get('image')
        if not isinstance(original_name,str) or original_name!=row['image'] or original_name in ('','.','..'):
            row['preview_url']=None
            row['preview_state']='UNAVAILABLE_IMAGE_IDENTITY'
        else:row['preview_state']='FROZEN_EVIDENCE_REFERENCE'
        result['items'].append(row)
    return result

def comparison_display(raw,offset=0,limit=20):
    result=fields(raw,('comparable','reason_codes','source_version_id','current_version_id'))
    result['metrics']={METRIC_ALIASES.get(key,key):fields(value,('before','after','delta'))
                       for key,value in (raw.get('metrics') or {}).items() if key in METRICS or key in METRIC_ALIASES}
    classes=raw.get('classes') or []
    result['classes']=[{**fields(row,('class_id','label','comparable','regressed')),'metrics':{key:fields(value,('before','after','delta')) for key,value in (row.get('metrics') or {}).items() if key in METRICS}} for row in classes[offset:offset+limit]]
    result.update(offset=offset,limit=limit,total=len(classes),has_next=offset+limit<len(classes))
    result['parameter_differences']={key:fields(value,('before','after')) for key,value in (raw.get('parameter_differences') or {}).items() if key in ('epochs','imgsz','batch','workers','precision','optimizer','lr0')}
    return result
