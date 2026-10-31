from pathlib import Path

import pytest


@pytest.fixture
def isolated_other_project(client):
    import io
    from PIL import Image
    other=client.post('/api/projects',json={'name':'isolated-other-files','labels':['fire']}).json()
    data=io.BytesIO();Image.new('RGB',(16,16),'red').save(data,format='PNG')
    response=client.post(f'/api/projects/{other["id"]}/images',files=[('files',('other.png',data.getvalue(),'image/png'))])
    response.raise_for_status()
    return other['id'],response.json()['uploaded'][0]


@pytest.fixture
def authenticated_project_files(client,seeded_project,isolated_other_project,monkeypatch):
    import app as platform
    from platform_core.changlian_login_auth import SESSION_COOKIE_NAME
    pid,image=seeded_project
    monkeypatch.setattr(platform,'_auth_test_bypass_enabled',lambda:False)
    monkeypatch.setattr(platform,'ALLOW_MULTIPLE_PROJECTS_FOR_TESTS',False)
    monkeypatch.setattr(platform,'DEFAULT_PROJECT_ID',pid)
    client.cookies.set(SESSION_COOKIE_NAME,platform._CHANGLIAN_AUTH_SESSIONS.issue('isolated-file-user'))
    yield platform,pid,image,isolated_other_project
    client.cookies.clear()


@pytest.mark.parametrize('relative',['auth/changlian-session.key','task_runtime/internal-fixture.sqlite3','storage/internal-fixture.json','worker/private-fixture.txt'])
def test_authenticated_data_mount_never_serves_internal_files(client,authenticated_project_files,relative):
    platform,pid,image,other=authenticated_project_files
    if relative!='auth/changlian-session.key':
        target=platform.DATA_DIR/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(b'isolated-internal-fixture')
    response=client.get('/data/'+relative,follow_redirects=False)
    assert response.status_code in (403,404)


def test_unregistered_project_model_is_not_downloadable(client,authenticated_project_files):
    platform,pid,image,other=authenticated_project_files
    rogue=platform.project_dir(pid)/'models'/'unregistered-fixture.pt'
    rogue.parent.mkdir(parents=True,exist_ok=True)
    rogue.write_bytes(b'isolated-unregistered-model')
    for url in (f'/data/projects/{pid}/models/{rogue.name}',f'/api/projects/{pid}/models/{rogue.name}/download'):
        assert client.get(url).status_code==404


def test_authorized_material_content_and_thumbnail_stay_available(client,authenticated_project_files):
    platform,pid,image,other=authenticated_project_files
    image_id=image['id']
    for url in (f'/api/v61/projects/{pid}/materials/{image_id}/content',f'/api/v61/projects/{pid}/materials/{image_id}/content/thumbnail'):
        response=client.get(url)
        assert response.status_code==200
        assert response.headers['content-type'].startswith('image/')


def test_signed_user_cannot_read_material_in_another_project(client,authenticated_project_files):
    platform,pid,image,other=authenticated_project_files
    other_pid,other_image=other
    response=client.get(f'/api/v61/projects/{other_pid}/materials/{other_image["id"]}/content')
    assert response.status_code in (403,404)


def test_registered_model_and_legacy_url_share_private_response(client,authenticated_project_files):
    platform,pid,image,other=authenticated_project_files
    root=platform.project_dir(pid)
    model=root/'models'/'registered.pt';model.write_bytes(b'isolated-model')
    platform.write_json(root/'jobs'/'registered-job'/'job.json',{'id':'registered-job','project_id':pid,'models':[str(model)]})
    for url in (f'/api/projects/{pid}/files/models/{model.name}',f'/data/projects/{pid}/models/{model.name}',f'/api/projects/{pid}/models/{model.name}/download'):
        response=client.get(url)
        assert response.status_code==200
        assert response.content==b'isolated-model'
        assert response.headers['cache-control']=='private, no-store'
        assert response.headers['x-content-type-options']=='nosniff'


def test_legacy_material_url_uses_registered_source(client,authenticated_project_files):
    platform,pid,image,other=authenticated_project_files
    response=client.get(f'/data/projects/{pid}/images/{image["stored_name"]}')
    assert response.status_code==200
    assert response.headers['content-type'].startswith('image/')


def test_conversion_only_registered_outputs_can_download_or_enter_package(client,authenticated_project_files):
    import io,zipfile
    platform,pid,image,other=authenticated_project_files
    jobdir=platform._deploy_job_dir(pid,'file-conversion');jobdir.mkdir(parents=True,exist_ok=True)
    output=jobdir/'artifacts'/'model.rknn';output.parent.mkdir();output.write_bytes(b'isolated-rknn')
    private=jobdir/'artifacts'/'private.rknn';private.write_bytes(b'private-not-registered')
    platform.write_json(jobdir/'job.json',{'id':'file-conversion','project_id':pid,'status':'done','target':'rockchip',
        'outputs':[{'path':str(output),'rel':'artifacts/model.rknn'}]})
    assert client.get(f'/api/v39/projects/{pid}/deploy/jobs/file-conversion/artifact?rel=artifacts/private.rknn').status_code==404
    response=client.get(f'/api/v39/projects/{pid}/deploy/jobs/file-conversion/package')
    assert response.status_code==200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist()==['model/model.rknn']


def test_deleted_sql_version_cannot_be_revived_by_json_mirror(client,authenticated_project_files):
    from platform_core.algorithms import save_algorithms
    platform,pid,image,other=authenticated_project_files
    root=platform.project_dir(pid);model=root/'models'/'deleted.pt';model.write_bytes(b'deleted-version')
    graph=[{'id':'a','versions':[{'id':'v','stored_path':str(model)}]}]
    save_algorithms(platform.algorithms_file(pid),graph)
    assert client.get(f'/api/v12/projects/{pid}/algorithms/a/versions/v/download').status_code==200
    save_algorithms(platform.algorithms_file(pid),[])
    platform.write_json(platform.algorithms_file(pid),graph)
    assert client.get(f'/api/projects/{pid}/models/{model.name}/download').status_code==404


def test_prediction_task_requires_project_kind_and_success_for_output(client,authenticated_project_files,monkeypatch):
    from types import SimpleNamespace
    platform,pid,image,other=authenticated_project_files
    root=platform.project_dir(pid)/'predictions'/'controlled-task';root.mkdir()
    original=root/'input.jpg';original.write_bytes(b'input-image')
    output=root/'result.jpg';output.write_bytes(b'result-image')
    task=SimpleNamespace(task_id='controlled-task',project_id=pid,kind=platform.TaskKind.DEPLOYMENT_TEST,
                         status=platform.TaskStatus.QUEUED,payload_ref='request.json',result_ref='result.json')
    monkeypatch.setattr(platform,'shared_task_repository',lambda:SimpleNamespace(get=lambda task_id: task))
    def read(task_id,ref,default=None):
        return {'input_path':str(original),'output_path':str(output)}
    monkeypatch.setattr(platform,'shared_task_artifacts',lambda:SimpleNamespace(read_json=read))
    base=f'/api/projects/{pid}/files/predictions/controlled-task'
    assert client.get(base+'/input.jpg').status_code==200
    assert client.get(base+'/result.jpg').status_code==404
    task.status=platform.TaskStatus.SUCCEEDED
    assert client.get(base+'/result.jpg').status_code==200
    task.project_id=other[0]
    assert client.get(base+'/result.jpg').status_code==404


def test_sync_prediction_requires_digest_registration(client,authenticated_project_files):
    platform,pid,image,other=authenticated_project_files
    root=platform.project_dir(pid)/'predictions'
    original=root/'sync-input.jpg';original.write_bytes(b'input-image')
    output=root/'sync_result.jpg';output.write_bytes(b'result-image')
    platform._register_prediction_files(pid,'sync',original,output)
    url=f'/api/projects/{pid}/files/predictions/{output.name}'
    assert client.get(url).status_code==200
    output.write_bytes(b'changed')
    assert client.get(url).status_code==404


def test_onnx_export_extends_existing_version_record(client,authenticated_project_files,monkeypatch):
    import sys
    from types import SimpleNamespace
    from platform_core.algorithms import save_algorithms, list_algorithms
    platform,pid,image,other=authenticated_project_files
    root=platform.project_dir(pid);model=root/'models'/'export-source.pt';model.write_bytes(b'formal-model')
    generated=root/'models'/'generated.onnx'
    def export(**kwargs):
        generated.write_bytes(b'fixture-onnx')
        return str(generated)
    monkeypatch.setitem(sys.modules,'ultralytics',SimpleNamespace(YOLO=lambda path:SimpleNamespace(export=export)))
    save_algorithms(platform.algorithms_file(pid),[{'id':'export-a','versions':[{'id':'export-v','stored_path':str(model)}]}])
    response=client.post(f'/api/projects/{pid}/export/onnx',data={'model_name':model.name})
    assert response.status_code==200,response.text
    assert client.get(response.json()['download_url']).content==b'fixture-onnx'
    assert list_algorithms(platform.algorithms_file(pid))[0]['versions'][0]['exported_models'][0]['sha256']


@pytest.mark.parametrize('tail',[
    '/dataset/download','/dataset/download_paddle',
    '/v12/algorithms/missing/versions/missing/evaluation/images/input.jpg',
    '/v62/training-materials/IMAGE/thumbnail',
    '/v62/material-batches/missing/log',
])
def test_other_project_file_routes_reject_before_record_lookup(client,authenticated_project_files,tail):
    platform,pid,image,other=authenticated_project_files
    other_pid,other_image=other
    if tail.startswith('/v12/'):
        url=f'/api/v12/projects/{other_pid}'+tail[len('/v12'):]
    elif tail.startswith('/v62/'):
        url=f'/api/v62/projects/{other_pid}'+tail[len('/v62'):].replace('IMAGE',other_image['id'])
    else:
        url=f'/api/projects/{other_pid}'+tail
    response=client.get(url)
    assert response.status_code in (403,404)
    assert response.json().get('message')=='文件不存在或无权访问'


@pytest.mark.parametrize('identifier',['../meta.json','%2e%2e/meta.json','%252e%252e/model.pt','..%5cmodel.pt','a.pt%3Astream'])
def test_http_path_encoding_does_not_authorize_files(client,authenticated_project_files,identifier):
    platform,pid,image,other=authenticated_project_files
    response=client.get(f'/api/projects/{pid}/files/models/{identifier}')
    assert response.status_code in (400,404)
    assert str(platform.DATA_DIR) not in response.text


def test_unauthenticated_business_and_legacy_resources_require_login(client,seeded_project,monkeypatch):
    import app as platform
    pid,_=seeded_project
    monkeypatch.setattr(platform,'_auth_test_bypass_enabled',lambda:False)
    client.cookies.clear()
    for path in [f'/api/projects/{pid}/files/models/model.pt',f'/data/projects/{pid}/models/model.pt','/data/task_runtime/private.sqlite3']:
        response=client.get(path,follow_redirects=False)
        if path.startswith('/data/'):
            assert response.status_code==307
            assert response.headers['location'].startswith('/login?')
        else:
            assert response.status_code==401


def test_production_flag_alone_cannot_bypass_real_http_login(client,seeded_project,monkeypatch):
    import app as platform
    pid,_=seeded_project
    monkeypatch.setattr(platform,'ALLOW_MULTIPLE_PROJECTS_FOR_TESTS',True)
    monkeypatch.setenv('MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS','1')
    monkeypatch.setenv('MC_PLATFORM_VERSION','42.24.387')
    client.cookies.clear()
    assert client.get(f'/api/projects/{pid}/files/models/model.pt').status_code==401


def test_registered_model_link_is_denied_by_http(client,authenticated_project_files):
    platform,pid,image,other=authenticated_project_files
    root=platform.project_dir(pid);model=root/'models'/'link-source.pt';model.write_bytes(b'model')
    link=root/'models'/'registered-link.pt'
    try:
        link.symlink_to(model)
    except OSError:
        pytest.skip('Windows symlink privilege unavailable; Linux auth CI runs this case')
    platform.write_json(root/'jobs'/'link-job'/'job.json',{'id':'link-job','project_id':pid,'models':[str(link)]})
    assert client.get(f'/api/projects/{pid}/files/models/{link.name}').status_code==404


def test_historical_export_zip_requires_exact_manifest_and_preserves_bytes(client,authenticated_project_files):
    platform,pid,image,other=authenticated_project_files
    root=platform.project_dir(pid)/'exports'
    archive=root/'export_model_e1.zip';archive.write_bytes(b'fixture-zip')
    platform.write_json(root/'export_model_e1'/'model_meta.json',{'project_id':pid,'export_id':'e1',
        'model_file':'model/registered.pt','model_path_source':'historical-recorded-source'})
    for path in [f'/data/projects/{pid}/exports/{archive.name}',f'/api/projects/{pid}/files/exports/{archive.name}']:
        assert client.get(path).content==b'fixture-zip'


@pytest.mark.parametrize('role',['content','thumbnail'])
def test_material_file_errors_do_not_publish_provider_paths(client,authenticated_project_files,monkeypatch,role):
    from types import SimpleNamespace
    from platform_core.storage import StorageError
    platform,pid,image,other=authenticated_project_files
    def fail(*args,**kwargs):
        raise StorageError(code='STORAGE_OBJECT_NOT_FOUND',message='missing /private/provider/path',
            detail='C:/private/provider/path/key',solution='inspect C:/private/provider/path')
    monkeypatch.setattr(platform,'storage_manager',lambda pid:SimpleNamespace(material=fail,thumbnail=fail))
    url=f'/api/v61/projects/{pid}/materials/{image["id"]}/content'+('/thumbnail' if role=='thumbnail' else '')
    response=client.get(url)
    assert response.status_code in (404,503)
    assert 'private/provider/path' not in response.text


def test_conversion_package_preserves_registered_inference_config_and_directory_layout(client,authenticated_project_files):
    import io,zipfile
    platform,pid,image,other=authenticated_project_files
    job_id='paddle-public-package'
    jobdir=platform._deploy_job_dir(pid,job_id)
    destination=jobdir/'artifacts'/'inference_model';destination.mkdir(parents=True)
    outputs=[]
    expected={'inference.pdmodel':b'public-model','inference.pdiparams':b'public-params','infer_cfg.yml':b'arch: YOLO\n'}
    for name,body in expected.items():
        item=destination/name;item.write_bytes(body)
        outputs.append({'path':str(item),'rel':'artifacts/inference_model/'+name})
    (destination/'internal-config.yml').write_text('not registered',encoding='utf-8')
    platform.write_json(jobdir/'job.json',{'id':job_id,'project_id':pid,'status':'done','target':'paddle','outputs':outputs})
    base=f'/api/v39/projects/{pid}/deploy/jobs/{job_id}'
    for name,body in expected.items():
        response=client.get(base+'/artifact',params={'rel':'artifacts/inference_model/'+name})
        assert response.status_code==200
        assert response.content==body
    assert client.get(base+'/artifact',params={'rel':'artifacts/inference_model/internal-config.yml'}).status_code==404
    response=client.get(base+'/package');assert response.status_code==200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist())=={'model/inference_model/'+name for name in expected}
        for name,body in expected.items():assert archive.read('model/inference_model/'+name)==body


def test_cleanup_status_cannot_cross_current_project_scope(client,authenticated_project_files):
    platform,pid,image,other=authenticated_project_files
    other_pid,other_image=other
    response=client.get('/api/v63/external-algorithm-platform/cleanup-operations',params={'project_id':other_pid})
    assert response.status_code in (403,404)
