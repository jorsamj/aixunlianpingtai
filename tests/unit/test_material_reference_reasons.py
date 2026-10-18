import json
from dataclasses import replace

import pytest

from platform_core.material_batches import _historical_material_references
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository, TaskStatus


@pytest.mark.parametrize('status,freeze,reason', [
    (TaskStatus.FAILED, False, 'TRAINING_FAILED_NO_FREEZE'),
    (TaskStatus.FAILED, True, 'TRAINING_FAILED_WITH_FREEZE'),
    (TaskStatus.SUCCEEDED, True, 'TRAINING_COMPLETED_HISTORY'),
    (TaskStatus.RUNNING, False, 'ACTIVE_TASK_INPUT'),
    (TaskStatus.QUEUED, False, 'ACTIVE_TASK_INPUT'),
])
def test_reference_reasons_do_not_unprotect_failed_or_frozen_history(tmp_path, status, freeze, reason):
    project = tmp_path / 'project'
    project.mkdir()
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    artifacts = ArtifactStore(tmp_path / 'artifacts')
    artifacts.atomic_write_json('history', 'payload.json', {'train_image_ids': ['a', 'b']})
    if freeze:
        artifacts.atomic_write_json('history', 'input-freeze.json', {'split': {'train_image_ids': ['a', 'b']}})
    record = replace(TaskRecord.new('history', 'p', TaskKind.TRAINING, 'payload.json', 'training'), status=status)
    repository.create(record, artifacts=artifacts)
    before = artifacts.read_json('history', 'payload.json')
    assert _historical_material_references('p', project, repository, artifacts) == {'a', 'b'}
    details = _historical_material_references(
        'p', project, repository, artifacts, with_reasons=True, reference_image_ids=['a'],
    )
    assert set(details) == {'a'}
    assert any(item['reason'] == reason and item['task_status'] == status.value for item in details['a'])
    assert all(item['protected'] is True for item in details['a'])
    assert artifacts.read_json('history', 'payload.json') == before
    assert _historical_material_references('p', project, repository, artifacts) == {'a', 'b'}


def test_snapshot_test_and_multiple_sources_keep_independent_reasons(tmp_path):
    project = tmp_path / 'project'
    (project / 'snapshots').mkdir(parents=True)
    (project / 'snapshots' / 'history.json').write_text(json.dumps({'test_image_ids': ['a']}))
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    artifacts = ArtifactStore(tmp_path / 'artifacts')
    artifacts.atomic_write_json('failed', 'payload.json', {'train_image_ids': ['a']})
    repository.create(replace(
        TaskRecord.new('failed', 'p', TaskKind.TRAINING, 'payload.json', 'training'),
        status=TaskStatus.FAILED,
    ), artifacts=artifacts)
    details = _historical_material_references('p', project, repository, artifacts, with_reasons=True)
    assert {item['reason'] for item in details['a']} >= {'TRAINING_FAILED_NO_FREEZE', 'FROZEN_TEST_SNAPSHOT'}
    assert (project / 'snapshots' / 'history.json').read_text() == json.dumps({'test_image_ids': ['a']})
