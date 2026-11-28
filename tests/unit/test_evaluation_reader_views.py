import json
from platform_core.evaluation_reader_views import report_section, samples_display, comparison_display

def test_evaluation_sections_are_bounded_and_paths_redacted():
    raw={'evaluation_id':'e','status':'succeeded','secret':'PRIVATE','per_class':[{'class_id':i,'label':'/private/label','map50':0} for i in range(3)],'confidence_curves':[{'class_id':0,'points':[{'confidence':i/100,'precision':0,'recall':0,'f1':0,'secret':'PRIVATE'} for i in range(30)]}],'confusion_matrix':{'protocol':'confidence_first_class_agnostic_iou_0.5','cells':[{'actual':0,'predicted':None,'count':2,'images':['/private/image']}]*3}}
    result=report_section(raw,'curves',0,1)
    assert result['total']==1 and result['evaluation']['confidence_curves'][0]['points_truncated'] is True
    assert 'PRIVATE' not in json.dumps(result) and '/private' not in json.dumps(result)
    matrix=report_section(raw,'confusion',0,1)
    assert matrix['has_next'] is True and matrix['evaluation']['confusion_matrix']['cells_total']==3
    summary=report_section({**raw,'snapshot_id':'snap','evaluation_protocol_id':'protocol',
                            'metrics':{'metrics/mAP50(B)':0,'metrics/mAP50-95(B)':.42}},'summary',0,1)
    assert summary['evaluation']['snapshot_id']=='snap' and summary['evaluation']['evaluation_protocol_id']=='protocol'
    assert summary['evaluation']['metrics']=={'precision':None,'recall':None,'map50':0,'map50_95':.42}
    comparison=comparison_display({'comparable':True,'metrics':{'metrics/mAP50-95(B)':{'before':0,'after':.42,'delta':.42}}})
    assert comparison['metrics']['map50_95']=={'before':0,'after':.42,'delta':.42}

def test_oversized_evaluation_defers_and_sample_urls_bind_original_evidence():
    assert report_section({'x':'a'*(2*1024*1024)},'summary',0,20)['state']=='DEFERRED'
    result=samples_display('p','a','v',{'evaluation_id':'e','items':[{'image_id':'i','image':'p.jpg','image_content_sha256':'a'*64,'url':'https://secret','gt_boxes':[{'class_id':0,'box':[1,2,10,20],'kind':'ground_truth'}],'pred_boxes':[],'boxes_truncated':True}],'total':1,'offset':0,'limit':24})
    row=result['items'][0]
    assert 'expected_evaluation_id=e' in row['preview_url'] and 'expected_image_id=i' in row['preview_url']
    assert '/private' not in json.dumps(result) and 'https://' not in json.dumps(result)
    assert row['gt_boxes'][0]['box']==[1,2,10,20] and row['boxes_truncated'] is True
    invalid=samples_display('p','a','v',{'items':[{'image':'/private/p.jpg'}]})
    assert invalid['items'][0]['preview_url'] is None
    assert invalid['items'][0]['preview_state']=='UNAVAILABLE_IMAGE_IDENTITY'

def test_history_page_preserves_zero_and_allows_only_bounded_recorded_fields(tmp_path):
    from platform_core.task_runtime import TaskRecord,TaskKind
    from platform_core.task_runtime.artifacts import ArtifactStore
    from platform_core.training_reader_views import report_display
    store=ArtifactStore(tmp_path/'artifacts');task=TaskRecord.new('t','p',TaskKind.TRAINING,'payload.json','training:auto')
    store.atomic_write_json('t','result.json',{'training_report':{'history':[{'epoch':i,'precision':0,'recall':None,'map50_95':0,'f1':0,'box_loss':1,'secret':'PRIVATE'} for i in range(5)]}})
    result=report_display('t',task,store,tmp_path/'missing.json',history_offset=2,history_limit=2)
    assert result['history_total']==5 and result['history_offset']==2 and result['history_has_next'] is True
    assert result['history'][0]['epoch']==2 and result['history'][0]['precision']==0
    assert 'PRIVATE' not in json.dumps(result)
    other=report_display('t',task,store,tmp_path/'missing.json',history_offset=0,history_limit=1)
    assert other['quality_status']==result['quality_status'] and other['warnings']==result['warnings']
