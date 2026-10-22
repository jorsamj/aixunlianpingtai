from types import SimpleNamespace
from contextlib import closing
import sqlite3
import hashlib
import json

import pytest

from platform_core.material_repository import MaterialRepository
from platform_core.annotation_repository import AnnotationRepository
from platform_core.task_runtime import TaskRepository,ArtifactStore
from platform_core.task_runtime import Scheduler,TaskKind,TaskRecord,TaskStatus
from platform_core.material_batches import estimate_batch,create_batch,BatchRequestError,BatchSelection,MaterialBatchHandler
import platform_core.material_batches as batches


def runtime(tmp_path,count=2):
    project=tmp_path/'projects'/'p';materials=MaterialRepository(project)
    materials.upsert_many([{'id':f'i{x:04}','filename':f'{x}.jpg','object_key':f'uploads/{x}.jpg',
        'content_sha256':f'{x:064x}','size_bytes':12,'split':'test' if x==0 else 'train'} for x in range(count)])
    annotations=AnnotationRepository(project)
    annotations.upsert('i0000',[],'confirmed_empty',annotation_scope=['fire'])
    return materials,TaskRepository(tmp_path/'tasks.sqlite3'),ArtifactStore(tmp_path/'artifacts')


def test_general_delete_preview_freezes_1001_ids_and_is_idempotent(tmp_path):
    materials,repository,artifacts=runtime(tmp_path,1001)
    payload={'operation':'DELETE_INDEX','selection_spec':{'scope':'FILTERED','filters':{}},'options':{}}
    preview=estimate_batch('p',materials,payload,repository=repository,artifacts=artifacts,actor={'actor_id':'u'})
    plan=preview['deletion_preview']
    assert plan['selected_count']==1001 and plan['current_test_count']==1
    for field in ('manual_required_count', 'unverifiable_count', 'skipped_groups', 'skipped_item_count',
                  'protected_item_count', 'protected_groups', 'manual_required_groups', 'anomaly_groups', 'anomaly_item_count'):
        assert plan[field] == 0
    assert plan['skip_reasons'] == {}
    assert plan['physical_retained_count']==1001 and plan['reclaimed_bytes']==0
    payload['selection_spec']=preview['selection_spec']
    payload['options']={'deletion_plan_id':plan['plan_id'],'confirmation_credential':plan['confirmation_credential']}
    task=create_batch('p',materials,repository,artifacts,payload,actor={'actor_id':'u'})
    assert create_batch('p',materials,repository,artifacts,payload,actor={'actor_id':'u'}).task_id==task.task_id
    with closing(BatchSelection(artifacts.artifact_path(task.task_id,'selection.sqlite3'))) as selection:
        assert selection.database.execute('SELECT COUNT(*) FROM selection').fetchone()[0]==1001


def test_project_clear_requires_verified_actor_name_and_same_actor(tmp_path):
    materials,repository,artifacts=runtime(tmp_path)
    payload={'operation':'DELETE_INDEX','selection_spec':{'scope':'FILTERED','filters':{}},
        'options':{'clear_project':True,'project_name_confirmation':'Project'}}
    with pytest.raises(BatchRequestError):
        estimate_batch('p',materials,payload,repository=repository,artifacts=artifacts,actor={},project={'name':'Project'})
    preview=estimate_batch('p',materials,payload,repository=repository,artifacts=artifacts,
        actor={'actor_id':'alice'},project={'name':'Project'})
    payload['selection_spec']=preview['selection_spec']
    payload['options'].update(deletion_plan_id=preview['deletion_preview']['plan_id'],confirmation_credential=preview['deletion_preview']['confirmation_credential'])
    with pytest.raises(BatchRequestError):
        create_batch('p',materials,repository,artifacts,payload,actor={'actor_id':'bob'},project={'name':'Project'})
    assert create_batch('p',materials,repository,artifacts,payload,actor={'actor_id':'alice'},project={'name':'Project'}).task_id==preview['deletion_preview']['plan_id']


def test_preview_rejects_gt_drift_before_publication(tmp_path):
    materials,repository,artifacts=runtime(tmp_path)
    payload={'operation':'DELETE_INDEX','selection_spec':{'scope':'SELECTED','image_ids':['i0000']},'options':{}}
    preview=estimate_batch('p',materials,payload,repository=repository,artifacts=artifacts,actor={'actor_id':'u'})
    AnnotationRepository(materials.project_path).upsert('i0000',[],'confirmed_empty',annotation_scope=['smoke'])
    payload['selection_spec']=preview['selection_spec'];payload['options']={'deletion_plan_id':preview['deletion_preview']['plan_id'],'confirmation_credential':preview['deletion_preview']['confirmation_credential']}
    with pytest.raises(BatchRequestError,match='变化'):
        create_batch('p',materials,repository,artifacts,payload,actor={'actor_id':'u'})


def test_real_worker_logically_removes_current_test_and_active_reference(tmp_path):
    materials,repository,artifacts=runtime(tmp_path)
    artifacts.atomic_write_json('training','request.json',{'train_image_ids':['i0000'],'test_image_ids':[]})
    repository.create(TaskRecord.new('training','p',TaskKind.TRAINING,'request.json','training',required_capabilities=('not-this-worker',)),artifacts=artifacts)
    payload={'operation':'DELETE_INDEX','selection_spec':{'scope':'SELECTED','image_ids':['i0000']},'options':{}}
    preview=estimate_batch('p',materials,payload,repository=repository,artifacts=artifacts,actor={'actor_id':'u'})
    payload['selection_spec']=preview['selection_spec'];payload['options']={'deletion_plan_id':preview['deletion_preview']['plan_id'],'confirmation_credential':preview['deletion_preview']['confirmation_credential']}
    task=create_batch('p',materials,repository,artifacts,payload,actor={'actor_id':'u'})
    scheduler=Scheduler(repository,artifacts,'worker',{TaskKind.MATERIAL_BATCH:MaterialBatchHandler(tmp_path)},{'materials.batch'},lease_seconds=10)
    assert scheduler.run_once()
    current=repository.get(task.task_id)
    assert current.status is TaskStatus.SUCCEEDED,artifacts.read_json(task.task_id,'result.json',default={})
    assert materials.get('i0000') is None
    assert materials.get('i0001') is not None
    with closing(materials._connect()) as db:
        assert db.execute('SELECT actor_id FROM material_retirements').fetchone()[0]=='u'


def _audit_groups(materials,artifacts,count,issue_type):
    from platform_core.training_compatibility import _file_digest
    annotations=AnnotationRepository(materials.project_path)
    task=SimpleNamespace(task_id='audit',status=TaskStatus.SUCCEEDED)
    path=artifacts.artifact_path('audit',batches.MATERIAL_INTEGRITY_REF);path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path)) as db:
        db.executescript(batches._MATERIAL_INTEGRITY_SCHEMA)
        for x in range(count):
            row=materials.get(f'i{x:04}');ann=annotations.get(row['id']);group=f'{issue_type}:{x//2}'
            db.execute('INSERT OR IGNORE INTO issue_groups VALUES (?,?,?,?,?)',(group,issue_type,row['content_sha256'],2,'{}'))
            db.execute('INSERT INTO issue_items VALUES (?,?,?,?,?)',(group,issue_type,row['content_sha256'],row['id'],json.dumps({**row,'annotation_digest':annotations.record_digest(ann)})))
        metadata={'material_revision':materials.current_revision(),'annotation_revision':annotations.current_revision(),'label_schema_digest':_file_digest(materials.project_path/'meta.json')}
        db.executemany('INSERT INTO audit_metadata VALUES (?,?)',((key,json.dumps(value)) for key,value in metadata.items()));db.commit()
    return task


def test_nineteen_conflict_groups_discard_all_38_without_keeper(tmp_path):
    materials,repository,artifacts=runtime(tmp_path,38)
    annotations=AnnotationRepository(materials.project_path)
    annotations.upsert_many([{'image_id':f'i{x:04}','boxes':[{'id':f'b{x}','label':'fire' if x%2 else 'smoke','x1':1,'y1':1,'x2':8,'y2':8}],
        'annotation_state':'annotated','annotation_scope':['fire','smoke']} for x in range(38)])
    audit=_audit_groups(materials,artifacts,38,'DUPLICATE_ANNOTATION_CONFLICT')
    plan=batches.create_material_integrity_plan('p',audit,materials,repository,artifacts,{'scope':'DISCARD_CONFLICTS','confirm_discard_conflicts':True})
    assert plan['delete_count']==38 and plan['included_groups']==19
    assert all(not group['keeper_image_id'] for group in plan['preview_groups'])
    task=batches.execute_material_integrity_plan('p',audit,plan['plan_id'],plan['confirmation_credential'],materials,repository,artifacts)
    scheduler=Scheduler(repository,artifacts,'worker',{TaskKind.MATERIAL_BATCH:MaterialBatchHandler(tmp_path)},{'materials.batch'},lease_seconds=10)
    assert scheduler.run_once()
    assert repository.get(task.task_id).status is TaskStatus.SUCCEEDED
    assert materials.get_many([f'i{x:04}' for x in range(38)])==[]


def test_identical_group_keep_one_remains_explicit_and_deletes_only_surplus(tmp_path):
    materials,repository,artifacts=runtime(tmp_path)
    audit=_audit_groups(materials,artifacts,2,'DUPLICATE_IDENTICAL')
    plan=batches.create_material_integrity_plan('p',audit,materials,repository,artifacts,{'scope':'SELECTED_IMAGES','image_ids':['i0000','i0001'],'delete_mode':'KEEP_ONE'})
    assert plan['delete_count']==1
    assert plan['preview_groups'][0]['keeper_image_id'] in {'i0000','i0001'}


def test_batch_http_preview_create_and_results_report_exact_logical_retirements(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    materials,repository,artifacts=runtime(tmp_path,3)
    api=FastAPI();api.include_router(batches.material_batch_router(
        lambda _pid:{'id':'p','name':'Project'},lambda _pid:materials,lambda:repository,lambda:artifacts,
        actor_provider=lambda _request,_pid:{'actor_id':'alice'}))
    client=TestClient(api);base='/api/v62/projects/p/material-batches'
    payload={'operation':'DELETE_INDEX','selection_spec':{'scope':'FILTERED','filters':{}},'options':{'clear_project':True,'project_name_confirmation':'Project'}}
    response=client.post(base+'/estimate',json=payload);assert response.status_code==200,response.text
    preview=response.json();payload['selection_spec']=preview['selection_spec']
    payload['options'].update(deletion_plan_id=preview['deletion_preview']['plan_id'],confirmation_credential=preview['deletion_preview']['confirmation_credential'])
    created=client.post(base,json=payload);assert created.status_code==202,created.text
    task_id=created.json()['task_id']
    assert client.post(base,json=payload).json()['task_id']==task_id
    scheduler=Scheduler(repository,artifacts,'worker',{TaskKind.MATERIAL_BATCH:MaterialBatchHandler(tmp_path)},{'materials.batch'},lease_seconds=10)
    assert scheduler.run_once()
    public=client.get(base+'/'+task_id).json()
    assert public['logical_removed']==3 and public['physical_retained']==3 and public['reclaimed_bytes']==0
    first=client.get(base+'/'+task_id+'/results?limit=2').json()
    second=client.get(base+'/'+task_id+'/results',params={'limit':2,'cursor':first['next_cursor']}).json()
    assert first['succeeded_image_ids']+second['succeeded_image_ids']==['i0000','i0001','i0002']
    assert second['next_cursor'] is None
    assert all(item['physical_retained'] and item['reclaimed_bytes']==0 for item in first['items']+second['items'])


def test_training_plan_uses_all_compatibility_issue_types_without_keeper(tmp_path):
    from platform_core.algorithms import save_algorithms
    materials,repository,artifacts=runtime(tmp_path)
    project=materials.project_path
    (project/'meta.json').write_text(json.dumps({'label_meta':[{'code':'fire','class_id':0,'active':True},{'code':'smoke','class_id':1,'active':True}]}),encoding='utf-8')
    save_algorithms(project/'algorithms.json',[{'id':'alg','versions':[]}])
    materials.patch_many(['i0000','i0001'],{'processing_status':'processed','width':100,'height':100})
    annotations=AnnotationRepository(project)
    annotations.upsert_many([{'image_id':iid,'annotation_state':'annotated','annotation_scope':[label],
        'boxes':[{'id':iid+'box','label':label,'class_id':cid,'x1':1,'y1':1,'x2':20,'y2':20}]} for iid,label,cid in [('i0000','fire',0),('i0001','smoke',1)]])
    plan=batches.create_training_integrity_plan('p',SimpleNamespace(task_id='audit',status=TaskStatus.SUCCEEDED),materials,repository,artifacts,{
        'expected_material_revision':materials.current_revision(),'expected_annotation_revision':annotations.current_revision(),
        'training_selection':{'algorithm_asset_id':'alg','image_ids':['i0000','i0001'],'train_labels':['fire','smoke'],'model':'yolo11n.pt','framework':'ultralytics'},
        'all_issues':True,'query':'unmatched','issue_type':'duplicate_annotation_conflict'},actor={'actor_id':'alice'})
    assert plan['delete_count']==2 and plan['training_selection']['selected_count']==2
    assert plan['audit_task_id']=='audit'
    with closing(sqlite3.connect(artifacts.artifact_path('audit',batches._material_integrity_plan_ref(plan['plan_id'])))) as db:
        assert db.execute('SELECT COUNT(*) FROM plan_groups').fetchone()[0]==0


def test_integrity_preview_reports_references_independently_of_logical_protection(tmp_path, monkeypatch):
    materials, repository, artifacts = runtime(tmp_path)
    audit = _audit_groups(materials, artifacts, 2, 'DUPLICATE_IDENTICAL')
    monkeypatch.setattr(batches, '_historical_material_references', lambda *_a, **_k: {
        'i0001': [{'reason': 'TRAINING_COMPLETED_HISTORY', 'task_status': 'SUCCEEDED', 'protected': True}]})
    plan = batches.create_material_integrity_plan('p', audit, materials, repository, artifacts,
        {'scope': 'SELECTED_IMAGES', 'image_ids': ['i0000', 'i0001']})
    assert plan['protected_item_count'] == 0
    assert plan['historical_reference_count'] == 1
    assert plan['active_reference_count'] == 0
    assert plan['current_test_count'] == 1
    assert plan['gt_count'] == 1
    monkeypatch.setattr(batches, '_historical_material_references', lambda *_a, **_k: (_ for _ in ()).throw(OSError('unknown')))
    unknown = batches.create_material_integrity_plan('p', audit, materials, repository, artifacts,
        {'scope': 'SELECTED_IMAGES', 'image_ids': ['i0000', 'i0001']})
    assert unknown['historical_reference_count'] is None
    assert unknown['active_reference_count'] is None
    assert unknown['current_test_count'] == 1


class SimulatedProcessExit(BaseException):
    pass


@pytest.mark.parametrize('crash_after_commit', [False, True])
def test_delete_worker_recovers_hard_exit_between_gt_retirement_and_manifest(tmp_path, monkeypatch, crash_after_commit):
    materials, repository, artifacts = runtime(tmp_path)
    annotations = AnnotationRepository(materials.project_path)
    original_gt = annotations.get('i0000')
    payload = {'operation': 'DELETE_INDEX', 'selection_spec': {'scope': 'SELECTED', 'image_ids': ['i0000']}}
    estimated = estimate_batch('p', materials, payload, repository=repository, artifacts=artifacts)
    preview = estimated['deletion_preview']
    payload.update(selection_spec=estimated['selection_spec'], options={'deletion_plan_id': preview['plan_id'], 'confirmation_credential': preview['confirmation_credential']})
    task = create_batch('p', materials, repository, artifacts, payload)
    context = SimpleNamespace(task=task, repository=repository, artifacts=artifacts, save_checkpoint=lambda *_: None)
    monkeypatch.setattr(batches, '_check_active', lambda *_a, **_k: None)
    original_retire = MaterialRepository.retire_many
    def interrupted_retire(self, *args, **kwargs):
        if crash_after_commit:
            original_retire(self, *args, **kwargs)
        raise SimulatedProcessExit('hard process termination')
    monkeypatch.setattr(MaterialRepository, 'retire_many', interrupted_retire)
    handler = MaterialBatchHandler(tmp_path)
    path = artifacts.artifact_path(task.task_id, 'selection.sqlite3')
    with closing(BatchSelection(path)) as manifest:
        with pytest.raises(SimulatedProcessExit):
            handler._run(context, manifest)
    assert not annotations.exists('i0000')
    monkeypatch.setattr(MaterialRepository, 'retire_many', original_retire)
    with closing(BatchSelection(path)) as manifest:
        status, _ = handler._run(context, manifest)
        assert status is TaskStatus.SUCCEEDED
        assert manifest.summary()['succeeded'] == 1
    assert materials.get('i0000') is None
    retired = materials.retirement(task.task_id, 'i0000')
    assert json.loads(retired['annotation_json'])['content_digest'] == original_gt['content_digest']
    assert annotations.delete_backup_count(f"material_delete_{task.task_id[:32]}_{hashlib.sha256(b'i0000').hexdigest()[:24]}") == 0


@pytest.mark.parametrize('drift', ['sha', 'gt', 'schema'])
def test_delete_crash_recovery_never_restores_old_gt_over_changed_identity(tmp_path, monkeypatch, drift):
    materials, repository, artifacts = runtime(tmp_path)
    annotations = AnnotationRepository(materials.project_path)
    payload = {'operation': 'DELETE_INDEX', 'selection_spec': {'scope': 'SELECTED', 'image_ids': ['i0000']}}
    estimated = estimate_batch('p', materials, payload, repository=repository, artifacts=artifacts)
    preview = estimated['deletion_preview']
    payload.update(selection_spec=estimated['selection_spec'], options={'deletion_plan_id': preview['plan_id'], 'confirmation_credential': preview['confirmation_credential']})
    task = create_batch('p', materials, repository, artifacts, payload)
    context = SimpleNamespace(task=task, repository=repository, artifacts=artifacts, save_checkpoint=lambda *_: None)
    monkeypatch.setattr(batches, '_check_active', lambda *_a, **_k: None)
    original_retire = MaterialRepository.retire_many
    monkeypatch.setattr(MaterialRepository, 'retire_many', lambda *_a, **_k: (_ for _ in ()).throw(SimulatedProcessExit()))
    handler = MaterialBatchHandler(tmp_path)
    path = artifacts.artifact_path(task.task_id, 'selection.sqlite3')
    with closing(BatchSelection(path)) as manifest:
        with pytest.raises(SimulatedProcessExit): handler._run(context, manifest)
    monkeypatch.setattr(MaterialRepository, 'retire_many', original_retire)
    if drift == 'sha': materials.upsert({**materials.get('i0000'), 'content_sha256': 'f' * 64})
    if drift == 'gt': annotations.upsert_many([{'image_id':'i0000','boxes':[],'annotation_state':'confirmed_empty','annotation_scope':['smoke']}], project_material=False)
    if drift == 'schema': (materials.project_path / 'meta.json').write_text('{"labels":[]}', encoding='utf-8')
    before = annotations.get('i0000')
    with closing(BatchSelection(path)) as manifest:
        status, _ = handler._run(context, manifest)
        assert status is TaskStatus.FAILED
        assert manifest.summary()['failed'] == 1
    assert materials.get('i0000') is not None
    assert annotations.get('i0000') == before
    assert annotations.delete_backup_count(f"material_delete_{task.task_id[:32]}_{hashlib.sha256(b'i0000').hexdigest()[:24]}") == 1
