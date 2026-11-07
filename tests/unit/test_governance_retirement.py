import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

from platform_core.material_repository import MaterialRepository
from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_batches import BatchSelection, MaterialBatchHandler
from platform_core.storage.manager import StorageManager
from platform_core.task_runtime import TaskRepository, ArtifactStore, TaskRecord, TaskKind


def setup(tmp_path):
    project=tmp_path/'projects'/'p'
    materials=MaterialRepository(project)
    row={'id':'image','filename':'image.jpg','object_key':'uploads/shared.jpg',
         'content_sha256':'a'*64,'size_bytes':12,'split':'test'}
    materials.upsert(row)
    annotations=AnnotationRepository(project)
    ann=annotations.upsert('image',[],'confirmed_empty',annotation_scope=['fire'])
    repository=TaskRepository(tmp_path/'tasks.sqlite3')
    artifacts=ArtifactStore(tmp_path/'artifacts')
    task=TaskRecord.new('delete','p',TaskKind.MATERIAL_BATCH,'request.json','materials:p')
    context=SimpleNamespace(task=task,repository=repository,artifacts=artifacts)
    manifest=BatchSelection(tmp_path/'selection.sqlite3')
    manifest.database.execute("INSERT INTO selection(image_id) VALUES ('image')")
    return project,materials,annotations,ann,context,manifest


def test_logical_delete_retires_test_gt_atomically_and_retains_bytes(tmp_path):
    project,materials,annotations,ann,context,manifest=setup(tmp_path)
    source=project/'uploads'/'shared.jpg';source.parent.mkdir();source.write_bytes(b'actual bytes')
    MaterialBatchHandler(tmp_path)._delete_index_rows(context,manifest,materials,['image'],project)
    assert materials.get('image') is None
    assert annotations.get('image')['version']==0
    with closing(materials._connect()) as db:
        retired=db.execute('SELECT payload_json,annotation_json,reclamation_state,task_id FROM material_retirements').fetchone()
    assert json.loads(retired[0])['object_key']=='uploads/shared.jpg'
    assert json.loads(retired[1])['content_digest']==ann['content_digest']
    assert retired[2]=='DEFERRED_SAFETY_UNVERIFIED'
    assert retired[3]=='delete'
    assert source.read_bytes()==b'actual bytes'


def test_retirement_write_failure_preserves_material_and_formal_gt(tmp_path,monkeypatch):
    project,materials,annotations,ann,context,manifest=setup(tmp_path)
    monkeypatch.setattr(materials,'retire_many',lambda *a,**kw: (_ for _ in ()).throw(OSError('retirement unavailable')))
    MaterialBatchHandler(tmp_path)._delete_index_rows(context,manifest,materials,['image'],project)
    assert materials.get('image') is not None
    assert annotations.get('image')['content_digest']==ann['content_digest']
    assert manifest.database.execute("SELECT state FROM selection WHERE image_id='image'").fetchone()[0]=='failed'


def test_unproven_physical_delete_is_rejected_before_provider_mutation(tmp_path):
    _project,materials,*_=setup(tmp_path)
    manager=StorageManager(data_dir=tmp_path,project_id='p',materials=materials)
    calls=[]
    manager.provider_for=lambda _source:SimpleNamespace(delete=lambda key:calls.append(key))
    with pytest.raises(Exception,match='PHYSICAL_DELETE_SAFETY_UNVERIFIED'):
        manager.delete_source_file('image')
    assert calls==[]


@pytest.mark.parametrize('remote_source', [False, True])
def test_retired_material_still_materializes_original_frozen_source_mapping(tmp_path, remote_source):
    import hashlib
    import io
    from platform_core.storage import LocalStorageProvider, StorageSourceRepository, StorageType
    project, materials, annotations, _ann, context, manifest = setup(tmp_path)
    content = b'original source bytes retained for frozen active consumers'
    sources = StorageSourceRepository(tmp_path / 'storage' / 'sources.sqlite3')
    if remote_source:
        source = sources.create({'id':'shared-remote','name':'shared','type':'remote',
            'config':{'base_url':'http://127.0.0.1'}})
        provider = LocalStorageProvider(source.id, tmp_path / 'mock-remote')
        provider.storage_type = StorageType.REMOTE
        provider.upload('uploads/shared.jpg', io.BytesIO(content))
        row = {**materials.get('image'), 'storage_source_id':source.id, 'storage_type':'remote'}
    else:
        source_file = project / 'uploads' / 'shared.jpg'
        source_file.parent.mkdir()
        source_file.write_bytes(content)
        provider = None
        row = materials.get('image')
    row.update(content_sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content))
    materials.upsert(row)
    frozen = dict(materials.get('image'))
    manager = StorageManager(data_dir=tmp_path, project_id='p', materials=materials, sources=sources,
        provider_resolver=(lambda *_args: provider) if remote_source else None)
    MaterialBatchHandler(tmp_path)._delete_index_rows(context, manifest, materials, ['image'], project)
    assert materials.get('image') is None
    assert not annotations.exists('image')
    resolved = manager.materialize(frozen)
    assert resolved.path.read_bytes() == content
    assert hashlib.sha256(resolved.path.read_bytes()).hexdigest() == frozen['content_sha256']
    assert materials.get('image') is None
    assert materials.retirement(context.task.task_id, 'image')['object_key'] == frozen['object_key']
