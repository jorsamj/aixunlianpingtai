import json
from platform_core.task_runtime import TaskRecord,TaskKind
from platform_core.task_runtime.artifacts import ArtifactStore

def test_finalized_metrics_outrank_legacy_and_val_test_remain_independent(tmp_path):
    from platform_core.training_reader_views import report_display
    artifacts=ArtifactStore(tmp_path/'artifacts');task=TaskRecord.new('t','p',TaskKind.TRAINING,'payload.json','training:auto')
    artifacts.atomic_write_json('t','result.json',{'training_report':{'metrics':{'map50':None,'precision':0},'history':[{'epoch':1,'map50':0}]},'evaluation':{'status':'succeeded','metrics':{'map50':.72},'error_samples':['GT_SENTINEL']},'metric_credibility':{'status':'warning','message':'token=PRIVATE /private/key'}})
    legacy=tmp_path/'job.json';legacy.write_text(json.dumps({'metrics':{'map50':.99}}))
    result=report_display('t',task,artifacts,legacy)
    assert result['source']=='DURABLE_FINALIZED' and result['val_metrics']['map50'] is None and result['val_metrics']['precision']==0
    assert result['test_metrics']['map50']==.72 and result['history'][0]['map50']==0
    assert 'GT_SENTINEL' not in json.dumps(result) and 'PRIVATE' not in json.dumps(result)

def test_report_absent_not_generated_and_corrupt_are_distinct(tmp_path):
    from platform_core.training_reader_views import report_display
    artifacts=ArtifactStore(tmp_path/'artifacts');legacy=tmp_path/'job.json'
    assert report_display('t',None,artifacts,legacy)['state']=='NOT_FOUND'
    legacy.write_text('{}');assert report_display('t',None,artifacts,legacy)['state']=='NOT_GENERATED'
    legacy.write_text('{broken');assert report_display('t',None,artifacts,legacy)['state']=='ERROR'
