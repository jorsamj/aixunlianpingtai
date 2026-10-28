import hashlib
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from platform_core import remote_conversion_runtime as runtime
from platform_core.task_runtime import ExecutionFencedError


class Response:
    def __init__(self, value=None, content=b'', status=200):
        self.value, self.content, self.status_code = value, content, status

    def json(self):
        return self.value

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def contract(chip='bm1688'):
    return {'kind':'sophon','chip':chip,'precision':'fp16','batch':1,'num_core':1,'dynamic':False,
            'input_height':384,'input_width':640,'opset':12,'simplify':False,
            'preprocessing':{'owner':'caller','pixel_format':'rgb','mean':[0.0]*3,'scale':[1.0/255]*3,
                             'letterbox':True,'pad_value':114,'channel_format':'nchw','nms':'external','fuse_preprocess':False}}


def bundle(chip='bm1688', data=b'compiled', digest=None, mutate=None):
    bmodel={'name':'model.bmodel','size_bytes':len(data),'sha256':digest or hashlib.sha256(data).hexdigest()}
    onnx_data=b'isolated-onnx-protocol-fixture'
    onnx={'name':'model.onnx','size_bytes':len(onnx_data),'sha256':hashlib.sha256(onnx_data).hexdigest()}
    manifest = {'schema_version':1,'job_id':'same-id','target':contract(chip),'parameters':contract(chip),
        'source':{'sha256':hashlib.sha256(b'source').hexdigest(),'version_id':'v1','algorithm_id':'a1'},
        'onnx':{**onnx,'input_shapes':[[1,3,384,640]],'checker':'passed','runtime':'onnxruntime'},
        'sophon_validation':{'structure':'passed','chip':chip,'hardware_verified':False,
                             'inspection':f'BMODEL chip: {chip}', 'artifact':dict(bmodel),
                             'toolchain':{'available':True,'version':'isolated-protocol-fixture'},
                             'preprocessing':contract(chip)['preprocessing']},
        'outputs':[bmodel,onnx]}
    if mutate:mutate(manifest)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as zf:
        zf.writestr('manifest.json', json.dumps(manifest))
        zf.writestr('model.bmodel', data)
        zf.writestr('model.onnx',onnx_data)
    return stream.getvalue()


@pytest.fixture
def task(tmp_path, monkeypatch):
    source=tmp_path/'model.onnx';source.write_bytes(b'source')
    job={'id':'same-id','target':'sophon','status':'running','params':contract(),'source_path':str(source),
         'source_trace':{'sha256':hashlib.sha256(b'source').hexdigest(),'version_id':'v1','algorithm_id':'a1'},
         'remote_upload_attempted':True,'remote_job_id':'same-id'}
    (tmp_path/'job.json').write_text(json.dumps(job))
    monkeypatch.setattr('platform_core.secrets.KeyringSecretStore', lambda: SimpleNamespace(get=lambda r: 'secret'))
    context=SimpleNamespace(assert_current_execution=lambda: None, cancel_requested=lambda:False, heartbeat=lambda **k:None)
    return context, {'job_dir':str(tmp_path),'remote_connection':{'base_url':'http://isolated.invalid','secret_ref':'test'}}, tmp_path


@pytest.fixture
def unsubmitted_task(task):
    context, request, jd = task
    job = json.loads((jd/'job.json').read_text())
    job.pop('remote_upload_attempted')
    job.pop('remote_job_id')
    (jd/'job.json').write_text(json.dumps(job))
    return task


def test_recovery_before_upload_receipt_performs_first_post_with_same_id(unsubmitted_task):
    context, request, jd = unsubmitted_task
    uploaded=[]
    def post(url, **kwargs):
        saved=json.loads((jd/'job.json').read_text())
        assert saved['remote_upload_attempted'] is True
        assert saved['remote_job_id']==kwargs['data']['client_job_id']=='same-id'
        uploaded.append(url)
        return Response({'job_id':'same-id'})
    http=SimpleNamespace(post=post,get=lambda url,**kwargs:Response(content=bundle()) if url.endswith('.zip') else Response({'status':'done'}))
    job=runtime.synchronize_remote_conversion(context,request,recovering=True,http=http)
    assert uploaded==['http://isolated.invalid/api/deploy/convert']
    assert job['status']=='blocked_by_hardware'


def test_recovery_cancel_before_upload_receipt_never_posts(unsubmitted_task):
    context, request, jd = unsubmitted_task
    context.cancel_requested=lambda:True
    uploaded=[]
    http=SimpleNamespace(post=lambda url,**kwargs:uploaded.append(url) or Response())
    job=runtime.synchronize_remote_conversion(context,request,recovering=True,http=http)
    assert job['status']=='stopped'
    assert not uploaded
    assert not job.get('remote_upload_attempted')


def test_lease_lost_after_upload_receipt_cannot_post(unsubmitted_task):
    context, request, jd = unsubmitted_task
    lost=False
    def assert_current():
        if lost:raise ExecutionFencedError('lease changed before POST')
    def heartbeat(**kwargs):
        nonlocal lost
        lost=True
    context.assert_current_execution=assert_current
    context.heartbeat=heartbeat
    uploaded=[]
    http=SimpleNamespace(post=lambda url,**kwargs:uploaded.append(url) or Response({'job_id':'same-id'}))
    with pytest.raises(ExecutionFencedError):
        runtime.synchronize_remote_conversion(context,request,http=http)
    assert not uploaded
    saved=json.loads((jd/'job.json').read_text())
    assert saved['remote_upload_attempted'] is True
    assert saved['remote_job_id']=='same-id'


def test_lease_lost_before_receipt_replace_cannot_commit(unsubmitted_task,monkeypatch):
    context, request, jd = unsubmitted_task
    before=(jd/'job.json').read_bytes()
    lost=False
    def assert_current():
        if lost:raise ExecutionFencedError('lease changed while writing receipt')
    original_write=Path.write_text
    def write_text(path,*args,**kwargs):
        nonlocal lost
        result=original_write(path,*args,**kwargs)
        if path.suffix=='.tmp':lost=True
        return result
    context.assert_current_execution=assert_current
    monkeypatch.setattr(Path,'write_text',write_text)
    http=SimpleNamespace(post=lambda *a,**kwargs:pytest.fail('fenced receipt must not upload'))
    with pytest.raises(ExecutionFencedError):
        runtime.synchronize_remote_conversion(context,request,http=http)
    assert (jd/'job.json').read_bytes()==before


def test_recovery_only_reads_existing_remote_id_and_preserves_unverified_artifact(task):
    context, request, jd=task
    calls=[]
    def get(url, **kwargs):
        calls.append(url)
        return Response(content=bundle()) if url.endswith('.zip') else Response({'status':'done','hardware_verified':True})
    http=SimpleNamespace(get=get, post=lambda *a,**k: pytest.fail('recovery must not POST a new job'))
    job=runtime.synchronize_remote_conversion(context,request,recovering=True,http=http)
    assert job['status']=='blocked_by_hardware'
    assert job['hardware_verified'] is False
    assert (jd/'artifacts/model.bmodel').read_bytes()==b'compiled'
    assert all('/same-id' in url for url in calls)


def test_known_remote_id_without_new_receipt_is_still_read_only(task):
    context,request,jd=task
    saved=json.loads((jd/'job.json').read_text());saved.pop('remote_upload_attempted')
    (jd/'job.json').write_text(json.dumps(saved))
    uploaded=[]
    http=SimpleNamespace(post=lambda url,**kwargs:uploaded.append(url) or Response({'job_id':'same-id'}),
                         get=lambda url,**kwargs:Response(content=bundle()) if url.endswith('.zip') else Response({'status':'done'}))
    job=runtime.synchronize_remote_conversion(context,request,recovering=True,http=http)
    assert job['status']=='blocked_by_hardware'
    assert not uploaded


def test_upload_timeout_resolves_same_client_identity(unsubmitted_task):
    context,request,jd=unsubmitted_task
    def post(url,**kwargs):
        saved=json.loads((jd/'job.json').read_text())
        assert saved['remote_job_id']=='same-id'
        assert kwargs['data']['client_job_id']=='same-id'
        raise requests.Timeout('ambiguous upload')
    http=SimpleNamespace(post=post,get=lambda url,**k: Response(content=bundle()) if url.endswith('.zip') else Response({'status':'done'}))
    assert runtime.synchronize_remote_conversion(context,request,http=http)['status']=='blocked_by_hardware'


def test_recovery_missing_job_never_creates_replacement(task):
    context,request,jd=task
    http=SimpleNamespace(get=lambda *a,**k:Response(status=404),post=lambda *a,**k:pytest.fail('no blind recreation'))
    assert runtime.synchronize_remote_conversion(context,request,recovering=True,http=http)['status']=='failed'
    assert not (jd/'artifacts').exists()


@pytest.mark.parametrize('content',[bundle('bm1684x'),bundle(digest='0'*64)])
def test_invalid_remote_artifact_is_not_published(task,content):
    context,request,jd=task
    http=SimpleNamespace(get=lambda url,**k:Response(content=content) if url.endswith('.zip') else Response({'status':'done'}))
    job=runtime.synchronize_remote_conversion(context,request,recovering=True,http=http)
    assert job['status']=='failed'
    assert not (jd/'artifacts').exists()


@pytest.mark.parametrize('section,field,value',[
    ('source','sha256','0'*64),('source','version_id','other-version'),('source','algorithm_id','other-algorithm'),
    ('target','precision','fp32'),('target','batch',2),('target','input_height',640),
    ('parameters','batch',2),('parameters','precision','fp32'),
    ('onnx','input_shapes',[[1,3,640,640]]),('onnx','input_shapes',[[1,3,'height',640]]),
    ('onnx','checker','failed'),('onnx','runtime','unverified'),('onnx','sha256','0'*64),
    ('sophon_validation','structure','missing'),('sophon_validation','chip','bm1684x'),
    ('sophon_validation','artifact',{'name':'model.bmodel','size_bytes':8,'sha256':'0'*64}),
    ('sophon_validation','inspection','BMODEL chip: bm1684x'),
    ('sophon_validation','preprocessing',{'owner':'compiler'}),
])
def test_remote_manifest_requires_same_version_shape_and_structure(task,section,field,value):
    context,request,jd=task
    content=bundle(mutate=lambda manifest:manifest[section].update({field:value}))
    http=SimpleNamespace(get=lambda url,**kwargs:Response(content=content) if url.endswith('.zip') else Response({'status':'done'}))
    job=runtime.synchronize_remote_conversion(context,request,recovering=True,http=http)
    assert job['status']=='failed'
    assert not (jd/'artifacts').exists()


@pytest.mark.parametrize('name',['../escape','/absolute','folder\\escape','C:/escape'])
def test_zip_rejects_unsafe_entries(tmp_path,name):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as zf:
        member = zipfile.ZipInfo('placeholder')
        member.filename = name
        zf.writestr(member,b'bad')
    with zipfile.ZipFile(io.BytesIO(stream.getvalue())) as zf:
        with pytest.raises(ValueError):runtime.safe_extract_zip(zf,tmp_path)


def test_cancel_stops_exact_remote_job(task):
    context,request,jd=task
    context.cancel_requested=lambda:True
    urls=[]
    http=SimpleNamespace(post=lambda url,**k:urls.append(url) or Response())
    job=runtime.synchronize_remote_conversion(context,request,recovering=True,http=http)
    assert job['status']=='stopped'
    assert urls==['http://isolated.invalid/api/deploy/jobs/same-id/stop']


def test_cancel_before_upload_never_starts_remote_work(unsubmitted_task):
    context,request,jd=unsubmitted_task
    context.cancel_requested=lambda:True
    http=SimpleNamespace(post=lambda *a,**k:pytest.fail('pre-upload cancellation must not start a remote task'))
    job=runtime.synchronize_remote_conversion(context,request,http=http)
    assert job['status']=='stopped'
    assert not job.get('remote_upload_attempted')


def test_timeout_stops_exact_remote_job(task):
    context,request,jd=task
    job=json.loads((jd/'job.json').read_text());job['remote_deadline']=1;(jd/'job.json').write_text(json.dumps(job))
    urls=[]
    http=SimpleNamespace(post=lambda url,**k:urls.append(url) or Response())
    job=runtime.synchronize_remote_conversion(context,request,recovering=True,http=http)
    assert job['error_code']=='REMOTE_CONVERSION_TIMEOUT'
    assert urls==['http://isolated.invalid/api/deploy/jobs/same-id/stop']


def test_fenced_owner_cannot_write_or_create_remote_job(task):
    context,request,jd=task
    before=(jd/'job.json').read_bytes()
    def fenced():raise ExecutionFencedError('lost lease')
    context.assert_current_execution=fenced
    with pytest.raises(ExecutionFencedError):
        runtime.synchronize_remote_conversion(context,request,http=SimpleNamespace())
    assert (jd/'job.json').read_bytes()==before


def test_remote_tool_disappeared_keeps_environment_error(unsubmitted_task):
    context,request,jd=unsubmitted_task
    http=SimpleNamespace(post=lambda *a,**k:Response({'detail':{'code':'TPU_MLIR_UNAVAILABLE','error':'compiler unavailable','solution':'configure compiler'}},status=400))
    job=runtime.synchronize_remote_conversion(context,request,http=http)
    assert job['error_code']=='TPU_MLIR_UNAVAILABLE'


@pytest.mark.parametrize('mode',['recover','cancel','timeout','fenced'])
def test_existing_conversion_handler_with_real_queue_and_lease(task,monkeypatch,mode):
    from platform_core.deployment.conversion_tasks import ConversionHandler
    from platform_core.task_runtime import ArtifactStore,FencedTaskRepository,TaskKind,TaskRecord,TaskStatus,WorkerContext
    _,request,jd=task
    request.update(execution_mode='remote',target='sophon')
    artifacts=ArtifactStore(jd/'durable-artifacts')
    repository=FencedTaskRepository(jd/'tasks.sqlite3')
    artifacts.atomic_write_json('same-id','request.json',request)
    repository.create(TaskRecord.new('same-id','p',TaskKind.MODEL_CONVERSION,'request.json','conversion:sophon',required_capabilities=('conversion.runtime',)))
    assert repository.claim_next('ineligible',[TaskKind.MODEL_CONVERSION],set()) is None
    lease=repository.claim_next('owner',[TaskKind.MODEL_CONVERSION],{'conversion.runtime'})
    assert lease is not None
    assert repository.claim_next('second-owner',[TaskKind.MODEL_CONVERSION],{'conversion.runtime'}) is None
    context=WorkerContext(lease.task,lease,repository,artifacts)
    gets=[];stops=[]
    def get(url,**kwargs):
        gets.append(url)
        return Response(content=bundle()) if url.endswith('.zip') else Response({'status':'done'})
    monkeypatch.setattr(runtime.requests,'get',get)
    monkeypatch.setattr(runtime.requests,'post',lambda url,**kwargs:stops.append(url) or Response())
    if mode=='cancel':repository.request_cancel('same-id')
    if mode=='timeout':
        job=json.loads((jd/'job.json').read_text());job['remote_deadline']=1;(jd/'job.json').write_text(json.dumps(job))
    if mode=='fenced':
        context.mark_lease_lost()
        with pytest.raises(ExecutionFencedError):ConversionHandler().recover(context)
        assert not gets and not stops
        assert not artifacts.artifact_path('same-id','conversion/result.json').exists()
    else:
        status,result_ref=ConversionHandler().recover(context)
        expected={'recover':TaskStatus.BLOCKED_BY_HARDWARE,'cancel':TaskStatus.CANCELLED,'timeout':TaskStatus.FAILED}[mode]
        assert status is expected
        result=artifacts.read_json('same-id',result_ref)
        assert result['hardware_verified'] is False
        if mode!='recover':assert stops==['http://isolated.invalid/api/deploy/jobs/same-id/stop']


def test_csc_remote_reference_matches_frozen_contract_and_rejects_tampering(tmp_path):
    from platform_core.conversion import validate_target, file_record
    from platform_core.conversion_csc import write_csc_deployment_bundle
    directory=tmp_path/'remote';directory.mkdir()
    with zipfile.ZipFile(io.BytesIO(bundle())) as archive:archive.extractall(directory)
    manifest=json.loads((directory/'manifest.json').read_text())
    request={**contract(),'csc':{'preset':'bt601_limited','input_format':'NV12','deployment_contract_acknowledged':True}}
    expected=validate_target('sophon',request)
    manifest['target']=expected;manifest['parameters']=expected
    manifest['execution_evidence']={'csc':expected['csc_contract']}
    write_csc_deployment_bundle(directory,expected['csc_contract'],include_reference_sources=False)
    manifest['outputs'].extend(file_record(directory/name,relative_to=directory) for name in
        ('csc_deployment_contract.json','csc_deployment_reference.zip'))
    (directory/'manifest.json').write_text(json.dumps(manifest))
    source=tmp_path/'source.onnx';source.write_bytes(b'source')
    job={'id':'same-id','params':request,'source_path':str(source),'source_trace':manifest['source']}
    assert runtime.validate_remote_artifacts(directory,job)['target']['csc_contract']['applied'] is False
    (directory/'csc_deployment_reference.zip').write_bytes(b'tampered')
    manifest['outputs']=[file_record(directory/entry['name'],relative_to=directory) for entry in manifest['outputs']]
    (directory/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='可信参考'):
        runtime.validate_remote_artifacts(directory,job)
