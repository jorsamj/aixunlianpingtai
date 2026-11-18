import json
import app as api
from platform_core.algorithms import save_algorithms
from platform_core.model_artifacts import ModelArtifactRepository

def test_opt_in_views_use_scoped_repository_without_full_algorithm_or_model_scan(tmp_path,monkeypatch):
    path=tmp_path/'projects'/'p'/'algorithms.json';path.parent.mkdir(parents=True)
    save_algorithms(path,[{'id':'a','name':'模型浏览测试','current_version_id':'v','versions':[{'id':'v','version_name':'V1','framework':'ultralytics','stored_path':'/secret/best.pt','evaluation':{'samples':['FROZEN_GT_SENTINEL']},'metrics':{'map50':0},'label_codes':['smoke']}]}])
    seen=[];monkeypatch.setattr(api,'get_project',lambda project:seen.append(project) or {'id':project})
    monkeypatch.setattr(api,'algorithms_file',lambda project:path);monkeypatch.setattr(api,'DATA_DIR',tmp_path)
    monkeypatch.setattr(api,'list_algorithms_internal',lambda *a,**k:(_ for _ in ()).throw(AssertionError('full algorithm projection used')))
    result=api.v12_list_algorithms('p',summary_only=True,asset_view=True,page_size=1)
    assert result['project_id']=='p' and result['items'][0]['versions_deferred'] is True
    versions=api.v12_get_algorithm('p','a',asset_view=True,page_size=1)
    assert versions['total']==1 and versions['algorithm']['current_version_id']=='v'
    detail=api.v12_get_algorithm('p','a',asset_view=True,version_id='v')
    assert detail['version']['metrics']['map50']==0 and detail['artifacts']['total']==0
    assert '/secret' not in json.dumps(detail) and 'FROZEN_GT_SENTINEL' not in json.dumps(detail)
    monkeypatch.setattr(api,'_conversion_history_page',lambda project,**q:{'items':[{'id':'j','status':'done','source_trace':{'algorithm_id':'a','version_id':'v','sha256':'saved-sha'},'params':{'precision':'fp16','secret':'PRIVATE'},'outputs':[]}],'total':1,'page':q['page'],'page_size':q['page_size'],'complete':True,'filter_options':{'target':['onnx'],'chip':['rk3568','token=SECRET_SENTINEL','/private/sdk']}})
    history=api.v423_version_deployments('p','a','v',asset_view=True,page_size=20)
    assert history['project_id']=='p' and history['algorithm_id']=='a' and history['version_id']=='v'
    assert history['items'][0]['source_identity']['sha256']=='saved-sha'
    assert history['items'][0]['numeric_status'] is None and 'PRIVATE' not in json.dumps(history)
    assert history['filter_options']['chip']==['rk3568']
    assert seen==['p']*5  # deploy_root also validates the project before resolving its owner path.

def test_artifact_display_is_existing_registration_only_and_scope_bounded(tmp_path):
    repo=ModelArtifactRepository(tmp_path)
    with repo._connect() as db:
        db.execute("INSERT INTO model_artifacts(artifact_id,project_id,algorithm_id,version_id,artifact_kind,target,file_name,source_path,sha256,size_bytes,storage_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",('asset','p','a','v','converted','onnx','model.onnx','/secret/model.onnx','abc',12,'PENDING','now','now'));db.commit()
    result=repo.version_display('p','a','v')
    assert result['total']==1 and result['items'][0]['artifact_kind']=='converted'
    assert result['items'][0]['storage_status']=='PENDING' and 'source_path' not in json.dumps(result)
    assert repo.version_display('other','a','v')['total']==0


def test_independent_spa_static_entry_keeps_existing_api_authentication(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    mount=next(route for route in api.app.routes if getattr(route,'path',None)=='/app')
    (tmp_path/'index.html').write_text('<main>independent Vue shell</main>',encoding='utf-8')
    monkeypatch.setattr(mount.app,'directory',str(tmp_path))
    monkeypatch.setattr(mount.app,'all_directories',[str(tmp_path)])
    monkeypatch.setattr(api,'_auth_test_bypass_enabled',lambda:False)
    client=TestClient(api.app)
    assert client.get('/app/').text=='<main>independent Vue shell</main>'
    assert client.get('/app/').status_code==200
    assert client.get('/api/projects').status_code==401
    assert client.get('/api/auth/session').json()['authenticated'] is False


def test_library_global_filters_sort_and_current_version_are_sql_paged(tmp_path,monkeypatch):
    from platform_core.algorithm_sql_store import AlgorithmSqlStore
    path=tmp_path/'p'/'algorithms.json';path.parent.mkdir()
    rows=[{'id':f'a{i:02}','name':f'算法{i}','industry':'工业','algorithm_type':'yolo_ultralytics','current_version_id':'current'+str(i),
           'versions':[{'id':'newer'+str(i),'created_at':'2030','metrics':{'map50':0.99}},
                       {'id':'current'+str(i),'metrics':{'map50':i/100},'snapshot':'SECRET_FROZEN'}]} for i in range(25)]
    rows.append({'id':'ext','name':'外部','source_type':'EXTERNAL','provider_type':'CHANG_LIAN','external_active':True,
                 'external_category_id':'leaf','external_master_data_digest':'old','external_analyses':[{'analysis_id':'x','analysis_type':'1','status':'1'}]})
    save_algorithms(path,rows);store=AlgorithmSqlStore(path)
    monkeypatch.setattr(store,'read_all',lambda **k:(_ for _ in ()).throw(AssertionError('full hydration')))
    stats=[{'algorithm_id':f'a{i:02}','count':i,'active':'running' if i==3 else None,'filter_active':i==3} for i in range(25)]
    categories=[{'categoryId':'root','categoryName':'父级'},{'categoryId':'leaf','categoryName':'叶子','parentId':'root'}]
    def page(**kw):return store.library_algorithms(statistics=stats,master_digest='new',categories=categories,page_size=10,**kw)
    result=page(sort='training');assert result['total']==26 and len(result['items'])==10 and result['items'][0]['id']=='a24'
    assert result['items'][0]['current_version']['id']=='current24'
    assert page(sort='metric')['items'][0]['map50_percent']==24
    assert page(sort='comprehensive')['items'][0]['id']=='a03'
    assert [r['id'] for r in page(query='a23')['items']]==['a23']
    assert [r['id'] for r in page(training_state='training')['items']]==['a03']
    assert page(training_state='trainable')['total']==25
    assert page(training_state='blocked')['items'][0]['id']=='ext'
    assert page(source_type='external',category_ids='root')['total']==1
    assert page(source_type='internal',category_ids='leaf')['total']==0
    assert page(training_state='trained')['total']==25 and page(training_state='untrained')['total']==1
    assert page(sort='metric',page=3)['items'][-1]['id']=='ext'
    assert 'SECRET_FROZEN' not in json.dumps(result)


def test_library_opt_in_reuses_history_once_and_preserves_asset_view(tmp_path,monkeypatch):
    from types import SimpleNamespace
    path=tmp_path/'p'/'algorithms.json';path.parent.mkdir();save_algorithms(path,[{'id':'a','name':'算法','algorithm_type':'yolo_ultralytics','versions':[]}])
    history=([{'id':'t','asset_algorithm_id':'a','status':'running'}],None,{'t':SimpleNamespace(status=api.TaskStatus.SUCCEEDED,stage='')})
    calls=[]
    monkeypatch.setattr(api,'get_project',lambda p:{'id':p});monkeypatch.setattr(api,'algorithms_file',lambda p:path);monkeypatch.setattr(api,'DATA_DIR',tmp_path)
    monkeypatch.setattr(api,'_training_history_context',lambda p:calls.append(p) or history)
    monkeypatch.setattr(api,'_successful_training_counts',lambda p,history_context:{'a':7})
    result=api.v12_list_algorithms('p',summary_only=True,asset_view=True,library_view=True,sort='training')
    assert result['items'][0]['successful_training_count']==7 and result['items'][0]['training_status'] is None
    assert calls==['p']  # Durable terminal truth overrides stale legacy running.
    old=api.v12_list_algorithms('p',summary_only=True,asset_view=True)
    assert 'successful_training_count' not in old['items'][0] and calls==['p']


def test_library_version_note_preserves_generated_identity_and_verified_read(tmp_path,monkeypatch):
    path=tmp_path/'p'/'algorithms.json';path.parent.mkdir()
    save_algorithms(path,[{'id':'a','name':'算法','versions':[{'id':'v','version_name':'generated','remark':'旧备注','stored_path':'/secret/model.pt','training_lineage':{},'evaluation':{}}]}])
    monkeypatch.setattr(api,'get_project',lambda p:{'id':p});monkeypatch.setattr(api,'algorithms_file',lambda p:path);monkeypatch.setattr(api,'DATA_DIR',tmp_path)
    result=api.v12_update_version('p','a','v',api.VersionPatchReq(remark='备注 /business/path token=业务原文'),asset_view=True)
    assert result=={'ok':True}
    detail=api.v12_get_algorithm('p','a',asset_view=True,version_id='v')
    assert detail['version']['remark']=='备注 /business/path token=业务原文' and detail['version']['version_name']=='generated'
    assert detail['version']['has_model']==1 and detail['version']['has_lineage']==1 and detail['version']['has_evaluation']==1
    assert '/secret' not in json.dumps(detail)
