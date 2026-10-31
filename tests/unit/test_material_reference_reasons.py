import json
from dataclasses import replace

import pytest

from platform_core.material_batches import BatchRequestError, _historical_material_references
from platform_core.remote_material_lifecycle import RemoteExecutionStagingLifecycle
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository, TaskStatus


@pytest.mark.parametrize('dependency', [
    None, 'remote-material/staging-cleanup.json', 'work/bundle/manifest.json',
    'checkpoint.pt', 'unknown.lock', 'staging-cleanup.json.lock',
    'remote-material/other.json.lock', 'input-freeze.json',
    'payload', 'recovery', 'retry_reference', 'attempt', 'running', 'succeeded',
])
def test_remote_cleanup_lock_does_not_override_real_training_dependencies(tmp_path, monkeypatch, dependency):
    project = tmp_path / 'project'
    project.mkdir()
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    artifacts = ArtifactStore(tmp_path / 'artifacts')
    artifacts.atomic_write_json('failed', 'payload.json', {'train_image_ids': ['a', 'b']})
    task = replace(TaskRecord.new('failed', 'p', TaskKind.TRAINING, 'payload.json', 'training'),
                   status=TaskStatus.FAILED)
    if dependency == 'attempt':
        task = replace(task, attempt=1)
    elif dependency in {'running', 'succeeded'}:
        task = replace(task, status=TaskStatus.RUNNING if dependency == 'running' else TaskStatus.SUCCEEDED)
    repository.create(task, artifacts=artifacts)

    def no_provider(project_id, reference):
        pytest.fail('request-only cleanup must not access storage')

    lifecycle = RemoteExecutionStagingLifecycle(repository, artifacts, no_provider)
    task_root = artifacts.artifact_path('failed', '.')
    build_ledger = lifecycle._build_terminal_ledger

    def inspect_locked_cleanup(record, **kwargs):
        assert build_ledger(record, **kwargs) is None
        # Inspect the real FileLock while held: Windows removes it on release,
        # whereas Linux can leave this exact synchronization file behind.
        assert (task_root / 'remote-material/staging-cleanup.json.lock').is_file()
        assert not (task_root / 'remote-material/staging-cleanup.json').exists()
        if dependency == 'payload':
            artifacts.atomic_write_json('failed', 'payload.json', {
                'train_image_ids': ['a', 'b'], 'execution': {'checkpoint_ref': 'missing.pt'},
            })
        elif dependency in {'recovery', 'retry_reference'}:
            artifacts.atomic_write_json('related', 'payload.json', {'recovery_task_id': 'failed'})
            related = TaskRecord.new('related', 'p', TaskKind.TRAINING, 'payload.json', 'training')
            if dependency == 'retry_reference':
                artifacts.atomic_write_json('related', 'payload.json', {})
                related = replace(related, retry_of='failed')
            repository.create(related, artifacts=artifacts)
        elif dependency and dependency not in {'attempt', 'running', 'succeeded'}:
            artifacts.atomic_write_json('failed', dependency, {'train_image_ids': ['a', 'b']})
        before = {path.relative_to(task_root): path.read_bytes() for path in task_root.rglob('*')
                  if path.is_file() and path.name != 'staging-cleanup.json.lock'}
        expected = {'a', 'b'} if dependency else set()
        assert _historical_material_references('p', project, repository, artifacts) == expected
        reasons = _historical_material_references('p', project, repository, artifacts, with_reasons=True)
        assert set(reasons) == {'a', 'b'}
        assert all(any(item['protected'] is bool(dependency) for item in items) for items in reasons.values())
        if not dependency:
            assert all(item['reason'] == 'TRAINING_FAILED_REQUEST_ONLY' and not item['protected']
                       for items in reasons.values() for item in items)
        assert {path.relative_to(task_root): path.read_bytes() for path in task_root.rglob('*')
                if path.is_file() and path.name != 'staging-cleanup.json.lock'} == before
        return None

    monkeypatch.setattr(lifecycle, '_build_terminal_ledger', inspect_locked_cleanup)
    assert lifecycle.cleanup_task(task)['status'] == 'NO_OBJECTS'
    assert _historical_material_references('p', project, repository, artifacts) == ({'a', 'b'} if dependency else set())
    assert repository.get('failed') == task


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
