import json
from dataclasses import replace

import pytest

from platform_core.material_batches import BatchRequestError, _historical_material_references
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository, TaskStatus


@pytest.mark.parametrize('status,freeze,reason', [
    (TaskStatus.FAILED, False, 'TRAINING_FAILED_REQUEST_ONLY'),
    (TaskStatus.FAILED, True, 'TRAINING_FAILED_WITH_FREEZE'),
    (TaskStatus.SUCCEEDED, True, 'TRAINING_COMPLETED_HISTORY'),
    (TaskStatus.RUNNING, False, 'ACTIVE_TASK_INPUT'),
    (TaskStatus.QUEUED, False, 'ACTIVE_TASK_INPUT'),
])
def test_reference_reasons_distinguish_request_only_from_durable_history(tmp_path, status, freeze, reason):
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
    is_protected = reason != 'TRAINING_FAILED_REQUEST_ONLY'
    expected = {'a', 'b'} if is_protected else set()
    assert _historical_material_references('p', project, repository, artifacts) == expected
    details = _historical_material_references(
        'p', project, repository, artifacts, with_reasons=True, reference_image_ids=['a'],
    )
    assert set(details) == {'a'}
    assert any(item['reason'] == reason and item['task_status'] == status.value for item in details['a'])
    assert all(item['protected'] is is_protected for item in details['a'])
    assert artifacts.read_json('history', 'payload.json') == before
    assert _historical_material_references('p', project, repository, artifacts) == expected


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
    assert {item['reason'] for item in details['a']} >= {'TRAINING_FAILED_REQUEST_ONLY', 'FROZEN_TEST_SNAPSHOT'}
    assert _historical_material_references('p', project, repository, artifacts) == {'a'}
    assert (project / 'snapshots' / 'history.json').read_text() == json.dumps({'test_image_ids': ['a']})


@pytest.mark.parametrize('dependency', ['snapshot.json', 'checkpoint-resume.json', 'unknown-contract.json'])
def test_failed_without_freeze_preserves_durable_or_unknown_dependencies(tmp_path, dependency):
    project = tmp_path / 'project'
    project.mkdir()
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    artifacts = ArtifactStore(tmp_path / 'artifacts')
    artifacts.atomic_write_json('failed', 'payload.json', {'train_image_ids': ['a']})
    artifacts.atomic_write_json('failed', dependency, {'image_ids': ['b']})
    repository.create(replace(TaskRecord.new('failed', 'p', TaskKind.TRAINING, 'payload.json', 'training'),
                              status=TaskStatus.FAILED), artifacts=artifacts)
    assert _historical_material_references('p', project, repository, artifacts) == {'a', 'b'}
    reasons = _historical_material_references('p', project, repository, artifacts, with_reasons=True)
    assert all(reason['protected'] for values in reasons.values() for reason in values)


def test_failed_prepare_unknown_artifact_protects_parent_request(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    artifacts = ArtifactStore(tmp_path / 'artifacts')
    artifacts.atomic_write_json('failed', 'payload.json', {'train_image_ids': ['a']})
    artifacts.atomic_write_json('prepare', 'payload.json', {'training_task_id': 'failed'})
    artifacts.atomic_write_json('prepare', 'prepared-input.json', {'snapshot_id': 'snapshot-history'})
    for task_id, kind in [('failed', TaskKind.TRAINING), ('prepare', TaskKind.TRAINING_PREPARE)]:
        repository.create(replace(TaskRecord.new(task_id, 'p', kind, 'payload.json', 'training'),
                                  status=TaskStatus.FAILED), artifacts=artifacts)
    assert _historical_material_references('p', project, repository, artifacts) == {'a'}


def test_terminal_audit_task_ids_keep_their_training_input_dependency(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    artifacts = ArtifactStore(tmp_path / 'artifacts')
    artifacts.atomic_write_json('failed', 'payload.json', {'train_image_ids': ['a']})
    artifacts.atomic_write_json('audit', 'payload.json', {'task_ids': ['failed']})
    for task_id, kind in [('failed', TaskKind.TRAINING), ('audit', TaskKind.MATERIAL_BATCH)]:
        repository.create(replace(TaskRecord.new(task_id, 'p', kind, 'payload.json', 'history'),
                                  status=TaskStatus.FAILED), artifacts=artifacts)
    assert _historical_material_references('p', project, repository, artifacts) == {'a'}


def test_missing_historical_training_payload_blocks_governance(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    artifacts = ArtifactStore(tmp_path / 'artifacts')
    repository.create(replace(TaskRecord.new('unknown', 'p', TaskKind.TRAINING, 'missing.json', 'training'),
                              status=TaskStatus.FAILED), artifacts=artifacts)
    with pytest.raises(BatchRequestError, match='历史任务'):
        _historical_material_references('p', project, repository, artifacts)


def test_diagnostic_filename_cannot_hide_a_checkpoint_dependency(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    artifacts = ArtifactStore(tmp_path / 'artifacts')
    artifacts.atomic_write_json('failed', 'payload.json', {'train_image_ids': ['a']})
    artifacts.atomic_write_json('failed', 'input-preparation-error.json', {
        'task_id': 'failed', 'project_id': 'p', 'stage': 'training_input_preparation_failed',
        'input_freeze_created': False, 'checkpoint_ref': 'missing-checkpoint.json',
    })
    repository.create(replace(TaskRecord.new('failed', 'p', TaskKind.TRAINING, 'payload.json', 'training'),
                              status=TaskStatus.FAILED), artifacts=artifacts)
    assert _historical_material_references('p', project, repository, artifacts) == {'a'}
