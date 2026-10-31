"""Real TrainingCompatibility -> frozen integrity plan -> DELETE_INDEX contracts."""
import json
from dataclasses import replace

import pytest
import app as app_module
from platform_core.annotation_repository import AnnotationRepository
from platform_core.task_runtime import TaskRecord, TaskKind, TaskStatus
from tests.api.test_material_integrity import _runtime, _run_integrity_audit, _duplicate_material


def _conflict(client, seeded_project, tmp_path, monkeypatch, count=3):
    project_id, original = seeded_project
    materials = app_module.material_store(project_id)
    source = materials.get(original['id'])
    ids = [original['id']] + [f'conflict-{i:05}' for i in range(count-1)]
    materials.upsert_many([_duplicate_material(source, image_id, image_id+'.jpg') for image_id in ids[1:]])
    annotations = AnnotationRepository(materials.project_path)
    for offset in range(0, len(ids), 500):
        annotations.upsert_many([dict(image_id=image_id, annotation_state='annotated', annotation_scope=['fire'],
            boxes=[dict(label='fire', class_id=0, x1=1 if image_id == ids[0] else 4, y1=1, x2=12, y2=12)])
            for image_id in ids[offset:offset+500]])
    repository, artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    audit_id = _run_integrity_audit(client, scheduler, project_id)
    algorithm = client.post(f'/api/v12/projects/{project_id}/algorithms', json={'name':'governance-test', 'algorithm_type':'yolo_ultralytics'}).json()['algorithm']
    selection = dict(algorithm_asset_id=algorithm['id'], train_image_ids=ids, split_mode='random_test_from_training_pool',
        experiment_percent=20, validation_percent=20)
    base = f'/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}'
    return project_id, materials, ids, repository, artifacts, scheduler, selection, base


def test_training_filtered_scope_uses_shared_preview_and_worker_without_changing_history(client, seeded_project, tmp_path, monkeypatch):
    pid, materials, ids, repository, artifacts, scheduler, selection, base = _conflict(client, seeded_project, tmp_path, monkeypatch)
    old = TaskRecord.new('failed-request-only', pid, TaskKind.TRAINING, 'payload.json', 'isolated-history')
    artifacts.atomic_write_json(old.task_id, old.payload_ref, selection)
    repository.create(replace(old, status=TaskStatus.FAILED), artifacts=artifacts)
    group_key = 'DUPLICATE_ANNOTATION_CONFLICT:' + materials.get(ids[0])['content_sha256']
    body = dict(training_task_id=old.task_id, all_filtered=True, excluded_image_ids=[ids[1]],
        expected_material_revision=materials.current_revision(),
        expected_annotation_revision=AnnotationRepository(materials.project_path).current_revision(),
        manual_decisions={group_key:ids[0]})
    response = client.post(base+'/training-plans', json=body)
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan['selected_count'] == 2
    assert plan['delete_count'] == 2
    assert plan['training_selection']['filtered_count'] == 3
    assert 'image_ids' not in plan['training_selection']
    url = base+f"/dedup-plans/{plan['plan_id']}/execute"
    task = client.post(url, json={'confirmation_credential':plan['confirmation_credential']})
    assert task.status_code == 202, task.text
    assert client.post(url, json={'confirmation_credential':plan['confirmation_credential']}).json()['task_id'] == task.json()['task_id']
    assert scheduler.run_once()
    finished = client.get(f"/api/v62/projects/{pid}/material-batches/{task.json()['task_id']}").json()
    assert finished['status'] == 'SUCCEEDED', finished
    assert finished['succeeded'] == 2
    assert materials.get(ids[0]) is None and materials.get(ids[1])
    assert materials.get(ids[2]) is None
    assert artifacts.read_json(old.task_id, old.payload_ref) == selection
    assert client.get(base+'/groups').json()['stale'] is True
    # Same physical source and original historical task remain intact.
    assert client.get(f'/api/v61/projects/{pid}/materials/{ids[1]}/content').status_code == 200
    diagnosis = client.get(f'/api/v62/projects/{pid}/training-tasks/{old.task_id}/input-diagnosis').json()
    assert diagnosis['current_diagnosis']['available'] is True
    assert diagnosis['current_diagnosis']['selection_truth']['missing_current_image_count'] == 2


@pytest.mark.parametrize('mutation', ['revision', 'foreign_selection', 'no_manual', 'foreign_task'])
def test_training_plan_rejects_stale_or_foreign_scope_and_keeps_gt_review(client, seeded_project, tmp_path, monkeypatch, mutation):
    pid, materials, ids, repository, artifacts, scheduler, selection, base = _conflict(client, seeded_project, tmp_path, monkeypatch)
    body = dict(training_selection=selection, all_filtered=True,
        expected_material_revision=materials.current_revision(),
        expected_annotation_revision=AnnotationRepository(materials.project_path).current_revision())
    if mutation == 'revision':
        body['expected_annotation_revision'] -= 1
    elif mutation == 'foreign_selection':
        body.update(all_filtered=False, image_ids=['not-in-current-conflicts'])
    elif mutation == 'foreign_task':
        body['training_task_id'] = 'not-a-project-task'
    response = client.post(base+'/training-plans', json=body)
    if mutation == 'no_manual':
        assert response.status_code == 201, response.text
        assert response.json()['delete_count'] == 3
        assert response.json()['manual_required_count'] == 0
        plan=response.json()
        assert repository.get(plan['plan_id']) is None  # Preview alone changes no identity.
    else:
        assert response.status_code == (404 if mutation == 'foreign_task' else 409), response.text
        assert ('训练任务不存在' if mutation == 'foreign_task' else 'MATERIAL_INTEGRITY_') in response.text
    assert all(materials.get(image_id) for image_id in ids)


def test_training_all_filtered_freezes_99_pages_without_returning_ids(client, seeded_project, tmp_path, monkeypatch):
    pid, materials, ids, repository, artifacts, scheduler, selection, base = _conflict(client, seeded_project, tmp_path, monkeypatch, count=2376)
    response = client.post(base+'/training-plans', json=dict(training_selection=selection,
        all_filtered=True, query='conflict-', excluded_image_ids=[ids[1]],
        expected_material_revision=materials.current_revision(),
        expected_annotation_revision=AnnotationRepository(materials.project_path).current_revision()))
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan['selected_count'] == 2374
    assert plan['training_selection']['filtered_count'] == 2375
    assert plan['delete_count'] == 2374  # Exact explicit discard freezes every selected member.
    assert len(plan['preview_items']) <= 20
    assert len(response.content) < 45000


def test_selection_summary_explicitly_identifies_deleted_draft_ids(client, seeded_project):
    pid, image = seeded_project
    response = client.post(f'/api/v62/projects/{pid}/training-materials/selection-summary',
        json={'image_ids':[image['id'],'deleted-draft-index']})
    assert response.status_code == 200, response.text
    assert response.json()['missing_image_ids'] == ['deleted-draft-index']


def test_audit_classification_is_shared_read_only_plan_truth_not_hidden_duplicates(client, seeded_project, tmp_path, monkeypatch):
    pid, materials, ids, repository, artifacts, scheduler, selection, base = _conflict(client, seeded_project, tmp_path, monkeypatch)
    snapshots=materials.project_path/'snapshots';snapshots.mkdir(exist_ok=True)
    (snapshots/'frozen-test.json').write_text(json.dumps({'test_image_ids':ids[:2]}),encoding='utf-8')
    response=client.get(base+'/governance-summary')
    assert response.status_code==200,response.text
    summary=response.json()
    assert summary['available'] is True
    assert summary['historical_retained_count']==0
    assert summary['historical_reference_count']==2
    assert summary['pending_image_count']==3
    assert summary['safe_delete_count']==3  # Logical retirement keeps all source bytes.
    assert summary['actually_deleted_count']==0
    assert not artifacts.artifact_path(base.split('/')[-1], 'dedup-plans').exists()
    groups=client.get(base+'/groups').json()
    assert groups['total_images']==3
    assert all(materials.get(image_id) for image_id in ids)


def test_2531_historical_references_allow_discard_while_keep_one_requires_gt_decision(client, seeded_project, tmp_path, monkeypatch):
    pid, materials, ids, repository, artifacts, scheduler, selection, base = _conflict(client, seeded_project, tmp_path, monkeypatch, count=2531)
    snapshots=materials.project_path/'snapshots';snapshots.mkdir(exist_ok=True)
    (snapshots/'isolated-frozen-test.json').write_text(json.dumps({'test_image_ids':ids}),encoding='utf-8')
    summary=client.get(base+'/governance-summary')
    assert summary.status_code==200,summary.text
    assert summary.json()['historical_retained_count']==0
    assert summary.json()['historical_reference_count']==2531
    assert summary.json()['safe_delete_count']==2531
    assert summary.json()['pending_image_count']==2531
    assert summary.json()['actually_deleted_count']==0
    assert summary.json()['protection_reason_counts']=={}
    assert json.loads((snapshots/'isolated-frozen-test.json').read_text(encoding='utf-8')) == {'test_image_ids':ids}
    plan=client.post(base+'/dedup-plans',json={'scope':'SAFE_ALL'}).json()
    assert plan['protected_item_count']==0 and plan['delete_count']==0
    assert plan['historical_reference_count']==2531
    assert plan['retained_count']==2531
    assert len(plan['preview_items'])==20
    assert plan['manual_required_count']==2531
    assert client.get(base+'/groups').json()['total_images']==2531
    assert materials.summary()['total']==2531


def test_partial_delete_refreezes_only_original_unprocessed_range_without_browser_ids(client, seeded_project, tmp_path, monkeypatch):
    pid, materials, ids, repository, artifacts, scheduler, selection, base = _conflict(client, seeded_project, tmp_path, monkeypatch, count=4)
    group='DUPLICATE_ANNOTATION_CONFLICT:'+materials.get(ids[0])['content_sha256']
    options=dict(training_selection=selection,all_filtered=True,delete_mode='KEEP_ONE',manual_decisions={group:ids[0]},
        expected_material_revision=materials.current_revision(),expected_annotation_revision=AnnotationRepository(materials.project_path).current_revision())
    plan=client.post(base+'/training-plans',json=options).json()
    queued=client.post(base+f"/dedup-plans/{plan['plan_id']}/execute",json={'confirmation_credential':plan['confirmation_credential']}).json()
    AnnotationRepository(materials.project_path).upsert(ids[1],[dict(label='fire',class_id=0,x1=6,y1=1,x2=12,y2=12)],annotation_state='annotated',annotation_scope=['fire'])
    assert scheduler.run_once()
    task=client.get(f"/api/v62/projects/{pid}/material-batches/{queued['task_id']}").json()
    assert task['status']=='PARTIAL_SUCCESS' and task['succeeded']==2 and task['failed']==1
    audit=_run_integrity_audit(client,scheduler,pid)
    newbase=f'/api/v62/projects/{pid}/material-integrity/audits/{audit}'
    options.update(training_selection={**selection,'train_image_ids':ids[:2]},all_filtered=False,
        previous_execution_task_id=task['task_id'],expected_material_revision=materials.current_revision(),
        expected_annotation_revision=AnnotationRepository(materials.project_path).current_revision())
    response=client.post(newbase+'/training-plans',json=options)
    assert response.status_code==201,response.text
    assert response.json()['selected_count']==1
    assert response.json()['delete_count']==1
    assert response.json()['training_selection']['retained_execution_count']==1
    assert repository.get(task['task_id']).status is TaskStatus.PARTIAL_SUCCESS


def test_governance_resolves_private_benchmark_before_candidate_selection(client, seeded_project, tmp_path, monkeypatch):
    pid, materials, ids, repository, artifacts, scheduler, selection, base = _conflict(client, seeded_project, tmp_path, monkeypatch)
    calls=[]
    def benchmark(project, algorithm, source, scope):
        calls.append((project,algorithm['id'],source,scope))
        return {'test_image_ids':[ids[0]]}
    monkeypatch.setattr(app_module,'_training_reusable_benchmark',benchmark)
    response=client.post(base+'/training-plans',json=dict(training_selection={**selection,
        'benchmark_source_version_id':'verified-source','benchmark_scope_id':'a'*64},all_filtered=True,
        expected_material_revision=materials.current_revision(),expected_annotation_revision=AnnotationRepository(materials.project_path).current_revision()))
    assert response.status_code==409,response.text
    assert '固定评测保留范围' in response.text
    assert calls==[(pid,selection['algorithm_asset_id'],'verified-source','a'*64)]
    assert all(materials.get(image_id) for image_id in ids)
