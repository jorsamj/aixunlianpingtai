from platform_core.annotation_reader_views import task_display, failure_display

def test_unknown_statistics_are_null_and_sensitive_fields_are_not_projected():
    value=task_display({'id':'t','project_id':'p','status':'FAILED','summary':{},'failed_count':0,'total_count':0,'error':'token=secret /private/data https://host/key','native_inference_config':{'key':'secret'}})
    assert value['statistics_known'] is False
    assert value['counts']['failed'] is None and value['total_count'] is None
    assert '/private' not in value['error'] and 'https://' not in value['error']
    assert 'native_inference_config' not in value

def test_failed_preview_uses_only_authenticated_project_media_and_bounded_safe_fields():
    row=failure_display('p',{'image_id':'i','filename':'C:/private/photo.jpg','url':'https://secret/source','status':'failed','error':'password=secret','diagnostics':{'secret':'x'},'boxes':[{'secret':'x'}]})
    assert row['filename']=='photo.jpg' and row['thumbnail_url'].startswith('/api/v61/projects/p/')
    assert 'url' not in row and 'boxes' not in row and 'diagnostics' not in row
