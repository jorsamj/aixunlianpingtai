import json
import uuid
from pathlib import Path

import pytest
import app as app_module


@pytest.mark.parametrize('operation',['dataset','image','batch'])
def test_legacy_implicit_deletion_requires_v62_frozen_preview(client,seeded_project,operation):
    pid,image=seeded_project
    source=app_module.project_dir(pid)/image['object_key'];before=source.read_bytes()
    if operation=='dataset':
        response=client.delete(f'/api/projects/{pid}/datasets/default')
    elif operation=='image':
        response=client.delete(f"/api/projects/{pid}/images/{image['id']}?delete_source=false")
    else:
        response=client.post(f'/api/v46/projects/{pid}/images/batch-delete',json={'image_ids':[image['id']],'delete_source':False})
    assert response.status_code==409,response.text
    assert 'MATERIAL_DELETE_PREVIEW_REQUIRED' in response.text
    assert '/material-batches/estimate' in response.text
    assert app_module.material_store(pid).get(image['id']) is not None
    assert source.read_bytes()==before


def test_legacy_journal_cleanup_never_reclaims_staged_image_bytes(client,seeded_project):
    pid,image=seeded_project;token=uuid.uuid4().hex
    staging=app_module._v50_dataset_delete_staging_dir(pid,token);staging.mkdir(parents=True)
    image_path=staging/'evidence.jpg';image_path.write_bytes(b'protected original')
    journal={'project_id':pid,'token':token}
    with pytest.raises(Exception,match='STAGED_BYTES|保留'):
        app_module._v50_cleanup_dataset_delete_artifacts(journal)
    assert image_path.read_bytes()==b'protected original'


def test_upload_rollback_persists_deferred_source_cleanup(client,seeded_project):
    pid,image=seeded_project
    errors=app_module._v50_cleanup_buffered_image_batch_files(pid,[image])
    assert errors==[]
    with app_module.material_store(pid)._connect() as db:
        rows=db.execute('SELECT payload_json,reclamation_state FROM material_cleanup_deferred').fetchall()
    assert any(json.loads(row[0])['id']==image['id'] and row[1]=='DEFERRED_SAFETY_UNVERIFIED' for row in rows)
    assert (app_module.project_dir(pid)/image['object_key']).is_file()


def _historical_staged_journal(pid,image):
    token=uuid.uuid4().hex
    journal={'token':token,'project_id':pid,'dataset_id':image.get('dataset_id','default'),
        'created_at':app_module.now_iso(),'updated_at':app_module.now_iso(),'status':'staged',
        'staging_dir':str(app_module._v50_dataset_delete_staging_dir(pid,token)),
        'claimed_rows':[dict(image)],'claimed_positions':{image['id']:0}}
    journal['files']=app_module._v50_dataset_delete_file_entries(pid,journal)
    app_module.AnnotationRepository(app_module.project_dir(pid)).prepare_delete(token,[image['id']])
    app_module.material_store(pid).patch({image['id']:{app_module._V50_DATASET_DELETE_CLAIM_FIELD:token}})
    for item in journal['files']:
        if item.get('existed'):
            app_module._v50_stage_material_file(Path(item['source']),Path(item['staged']))
    app_module._v50_write_dataset_delete_journal(journal)
    return journal


def test_existing_dataset_historical_journal_restores_gt_and_bytes(client,seeded_project):
    pid,image=seeded_project;repository=app_module.AnnotationRepository(app_module.project_dir(pid))
    before=repository.get(image['id']);source=app_module.project_dir(pid)/image['object_key'];before_bytes=source.read_bytes()
    journal=_historical_staged_journal(pid,image)
    repository.finalize_delete(journal['token']);app_module.material_store(pid).remove([image['id']])
    assert app_module._v50_recover_one_dataset_deletion(pid,journal) is True
    assert source.read_bytes()==before_bytes
    assert repository.get(image['id'])['content_digest']==before['content_digest']
    assert app_module.material_store(pid).get(image['id']) is not None
    assert not app_module._v50_dataset_delete_journal_path(pid,journal['token']).exists()


def test_absent_dataset_historical_journal_preserves_staging_and_gt_backup(client,seeded_project):
    pid,image=seeded_project;journal=_historical_staged_journal(pid,image)
    app_module.atomic_write_json(app_module.datasets_file(pid),[])
    staged=Path(journal['files'][0]['staged']);before=staged.read_bytes()
    with pytest.raises(app_module.HTTPException,match='DATASET_METADATA_ABSENT'):
        app_module._v50_recover_one_dataset_deletion(pid,journal)
    assert staged.read_bytes()==before
    assert app_module.material_store(pid).get(image['id']) is not None
    assert app_module.AnnotationRepository(app_module.project_dir(pid)).delete_backup_count(journal['token'])==1
    assert app_module.read_json(app_module._v50_dataset_delete_journal_path(pid,journal['token']),{})['status']=='manual_recovery_required'
