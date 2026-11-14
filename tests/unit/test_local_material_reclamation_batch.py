"""The batch operator is only a bounded frontend to the existing offline GC owner."""
import re
import sqlite3
import json

import pytest

from tools.reclaim_retired_original import batch_retirement_preview, main


class _GCPreview:
    def __init__(self):
        self.calls = []

    @staticmethod
    def _identifier(value):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', str(value)):
            raise ValueError('invalid reclamation identity')
        return str(value)

    def preview(self, project, task, image_id):
        self.calls.append((project, task, image_id))
        return {'eligible':image_id != 'image-b',
            'blockers':['LIVE_REFERENCE'] if image_id == 'image-b' else [],
            'fingerprint':f'proof-{image_id}',
            'source_identity':{'sha256':f'sha-{image_id}'}}


def test_retirement_batch_preview_is_stably_bounded_and_protects_live_bytes(tmp_path):
    project = tmp_path / 'projects/p'
    project.mkdir(parents=True)
    with sqlite3.connect(project / 'materials.sqlite3') as db:
        db.execute('CREATE TABLE material_retirements(task_id TEXT,image_id TEXT)')
        db.executemany('INSERT INTO material_retirements VALUES (?,?)',
            [('retire',name) for name in ('image-a','image-b','image-c')])
    owner = _GCPreview()
    first = batch_retirement_preview(owner,tmp_path,'p','retire',limit=2)
    assert first['count'] == 2
    assert first['eligible_count'] == 1
    assert first['has_more'] is True
    assert first['next_cursor'] == 'image-b'
    assert first['items'][1]['blockers'] == ['LIVE_REFERENCE']
    assert owner.calls == [('p','retire','image-a'),('p','retire','image-b')]
    assert batch_retirement_preview(owner,tmp_path,'p','retire',limit=2)['digest'] == first['digest']
    second = batch_retirement_preview(owner,tmp_path,'p','retire',after='image-b',limit=2)
    assert second['count'] == 1 and second['next_cursor'] == 'image-c'
    assert second['has_more'] is False
    assert second['digest'] != first['digest']
    with pytest.raises(ValueError,match='1至50'):
        batch_retirement_preview(owner,tmp_path,'p','retire',limit=51)
    with pytest.raises(ValueError,match='invalid reclamation identity'):
        batch_retirement_preview(owner,tmp_path,'../other','retire')


def test_retirement_batch_preview_mutation_changes_confirmation_digest(tmp_path):
    project=tmp_path/'projects/p'
    project.mkdir(parents=True)
    with sqlite3.connect(project/'materials.sqlite3') as db:
        db.execute('CREATE TABLE material_retirements(task_id TEXT,image_id TEXT)')
        db.execute('INSERT INTO material_retirements VALUES (?,?)',('retire','image-a'))
    owner=_GCPreview()
    original=batch_retirement_preview(owner,tmp_path,'p','retire',limit=20)
    with sqlite3.connect(project/'materials.sqlite3') as db:
        db.execute('INSERT INTO material_retirements VALUES (?,?)',('retire','image-b'))
    changed=batch_retirement_preview(owner,tmp_path,'p','retire',limit=20)
    assert changed['digest']!=original['digest']
    assert changed['eligible_count']==1
    assert changed['items'][1]['eligible'] is False


def test_retirement_batch_apply_requires_exact_preview_and_never_calls_gc_for_shared_bytes(
    tmp_path,monkeypatch,capsys,
):
    from platform_core.task_runtime.repository import _SCHEMA_VERSION
    from platform_core import local_material_reclamation

    runtime=tmp_path/'task_runtime'
    (runtime/'artifacts').mkdir(parents=True)
    with sqlite3.connect(runtime/'tasks.sqlite3') as db:
        db.execute(f'PRAGMA user_version={_SCHEMA_VERSION}')
    project=tmp_path/'projects/p'
    project.mkdir(parents=True)
    with sqlite3.connect(project/'materials.sqlite3') as db:
        db.execute('CREATE TABLE material_retirements(task_id TEXT,image_id TEXT)')
        db.executemany('INSERT INTO material_retirements VALUES (?,?)',
            [('retire','image-a'),('retire','image-b')])
    calls=[]
    class FakeGC(_GCPreview):
        def __init__(self,*_args,**_kwargs):
            super().__init__()

        def apply(self,project,task,image_id,*,expected_fingerprint,operation_id,confirmed,actor):
            calls.append((image_id,expected_fingerprint,operation_id,confirmed,actor))
            return {'status':'deleted','deleted_logical_bytes':100}

    monkeypatch.setattr(local_material_reclamation,'LocalMaterialReclamationService',FakeGC)
    monkeypatch.setattr('getpass.getuser',lambda:'isolated-operator')
    command=['--data-dir',str(tmp_path),'--project','p','--retirement-task','retire','--batch','--limit','20']
    assert main(command)==0
    preview=json.loads(capsys.readouterr().out)
    assert preview['dry_run'] is True and preview['eligible_count']==1
    wrong=command+['--apply','--expected-batch-digest','wrong','--operation-id','gc-001',
        '--confirm',preview['required_confirmation']]
    assert main(wrong)==2
    assert calls==[]
    capsys.readouterr()
    applied=command+['--apply','--expected-batch-digest',preview['digest'],
        '--operation-id','gc-001','--confirm',preview['required_confirmation']]
    assert main(applied)==0
    result=json.loads(capsys.readouterr().out)
    assert result['applied'][0]['image_id']=='image-a'
    assert result['skipped_count']==1 and result['physical_space_released'] is None
    assert len(calls)==1
    assert calls[0][0:2]==('image-a','proof-image-a')
    assert calls[0][3:]==(True,'isolated-operator')
