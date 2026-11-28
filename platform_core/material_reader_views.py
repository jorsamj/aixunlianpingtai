"""Read-only bounded DTOs from the existing Material/Annotation owners."""
from urllib.parse import quote
from .model_asset_views import fields,filename

def boxes(values,limit):
    return [fields(value,('class_id','label','class_name','x1','y1','x2','y2','source','confidence')) for value in (values or [])[:limit] if isinstance(value,dict)]

def material_display(project_id,row):
    result=fields(row,('id','width','height','size_bytes','storage_source_id','storage_type','source_type','source_batch_id','import_batch_id','processing_status','quality_status','source_available','content_sha256','created_at','annotation_state','annotation_status','annotation_issue_type','box_count','annotated','dataset_id'))
    result['filename']=filename(row.get('filename') or row.get('id'))
    result['storage_source_id']=result.get('storage_source_id') or 'default_local'
    result['annotation_preview']=boxes(row.get('annotation_preview'),32)
    result['boxes_preview_only']=True
    labels=row.get('labels') or [value.get('label') for value in result['annotation_preview']]
    result['labels']=[str(value)[:160] for value in labels[:100] if isinstance(value,str)] if isinstance(labels,list) else []
    root=f'/api/v61/projects/{quote(str(project_id),safe="")}/materials/{quote(str(row.get("id") or ""),safe="")}/content'
    result.update(content_url=root,thumbnail_url=root+'/thumbnail?edge=384')
    return result

def annotation_display(project_id,row,annotation):
    values=annotation.get('boxes') or []
    values=values if isinstance(values,list) else []
    result=fields(annotation,('annotation_state','source_content_sha256','updated_at'))
    result.update(boxes=boxes(values,1000),annotation_version=annotation.get('annotation_version',annotation.get('version')))
    result['reviewed_label_codes']=[str(value)[:160] for value in (annotation.get('reviewed_label_codes') or [])[:256] if isinstance(value,str)]
    return {'ok':True,'project_id':project_id,'image':material_display(project_id,row),'annotation':result,'boxes_total':len(values),'boxes_truncated':len(values)>1000}
