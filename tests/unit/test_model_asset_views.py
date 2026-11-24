import json
import pytest
from platform_core.algorithm_sql_store import AlgorithmSqlStore
from platform_core.algorithms import save_algorithms
from platform_core.errors import PlatformError

def seeded(tmp_path):
    path=tmp_path/'project-a'/'algorithms.json';path.parent.mkdir()
    save_algorithms(path,[{'id':f'a{i}','name':f'算法{i:02}','algorithm_type':'yolo_ultralytics','industry':'安全','status':'active','source_type':'LOCAL','current_version_id':f'v{i}-0','versions':[
        {'id':f'v{i}-{j}','version_name':f'版本{j}','framework':'ultralytics','stored_path':'/private/models/model.pt','map50':None,'metrics':{'map50':0 if j==0 else None},'evaluation':{'metrics':{'map50':0.72},'samples':['FROZEN_GT_SENTINEL']},'training_lineage':{'parameters':{'actual':{'epochs':50,'imgsz':640,'dataset':'/secret/data'}}},'label_codes':['smoke'],'label_schema':[{'class_id':0,'code':'smoke'}],'report':{'log':'PRIVATE_LOG_SENTINEL'}} for j in range(3)]} for i in range(3)])
    return AlgorithmSqlStore(path)

def test_asset_summary_is_paged_and_does_not_hydrate_versions(tmp_path,monkeypatch):
    store=seeded(tmp_path)
    monkeypatch.setattr(store,'read_all',lambda **kw:pytest.fail('full catalog read'))
    monkeypatch.setattr(store,'read_one',lambda *a:pytest.fail('full detail read'))
    result=store.asset_algorithms(page=2,page_size=1,query='算法')
    assert result['total']==3 and len(result['items'])==1
    row=result['items'][0];assert row['version_count']==3 and row['versions_deferred'] is True
    assert row['current_version_id']==row['current_version']['id']
    assert 'versions' not in row and 'stored_path' not in json.dumps(result)
    assert 'PRIVATE_LOG_SENTINEL' not in json.dumps(result)

def test_version_detail_is_scoped_safe_and_preserves_missing_vs_zero(tmp_path):
    store=seeded(tmp_path)
    page=store.asset_versions('a0',page=2,page_size=1)
    assert page['total']==3 and len(page['items'])==1
    value=store.asset_version('a0','v0-0')
    assert value['metrics']['map50']==0 and value['map50'] is None
    assert value['test_metrics']['map50']==0.72
    assert value['model_file']['file_name']=='model.pt'
    assert value['training_parameters']['epochs']==50
    body=json.dumps(value);assert '/private' not in body and '/secret' not in body and 'FROZEN_GT_SENTINEL' not in body and 'PRIVATE_LOG_SENTINEL' not in body
    with pytest.raises(PlatformError):store.asset_version('a1','v0-0')
    with pytest.raises(PlatformError):store.asset_algorithms(page_size=10001)

def test_conversion_safe_projection_never_equates_completion_with_verification(tmp_path):
    from platform_core.model_asset_views import conversion_record
    row=conversion_record({'id':'j','status':'done','source_trace':{'algorithm_id':'a','version_id':'v','sha256':'s','snapshot':{'gt':'SECRET'}},'params':{'precision':'fp16','token':'SECRET','python_path':'/secret/python'},'execution_evidence':{'command':['/secret/bin'],'worker_id':'w'},'outputs':[{'path':'/outside/secrets/model.onnx','name':'/outside/secrets/model.onnx'}]},tmp_path)
    assert row['status']=='done' and row['numeric_status'] is None and row['publication_status'] is None
    assert row['outputs'][0]['exists'] is None and row['outputs'][0]['file_name']=='model.onnx'
    assert 'SECRET' not in json.dumps(row) and '/secret' not in json.dumps(row)

def test_safe_diagnostics_hide_quoted_credentials_and_unc_paths():
    from platform_core.model_asset_views import text
    value=text(r'''{"token":"SECRET_SENTINEL", "password": "SECOND_SECRET"} \\server\private\credentials.txt''')
    assert 'SECRET' not in value and 'server' not in value and 'credentials.txt' not in value


def test_conversion_view_reads_projected_numeric_and_publication_status(tmp_path):
    from platform_core.model_asset_views import conversion_record
    for numeric, publication in (
        ('consistent', 'numeric_consistent_delivery_evidence_incomplete'),
        ('difference_detected', 'blocked_numeric_difference'),
        ('not_comparable', 'blocked_numeric_not_comparable'),
        ('unavailable', 'blocked_numeric_unavailable'),
    ):
        row = conversion_record({'id': 'j', 'status': 'done', 'numeric_status': numeric,
                                 'publication_status': publication}, tmp_path)
        assert row['numeric_status'] == numeric
        assert row['publication_status'] == publication
    absent = conversion_record({'id': 'j2', 'status': 'done'}, tmp_path)
    assert absent['numeric_status'] is None and absent['publication_status'] is None
