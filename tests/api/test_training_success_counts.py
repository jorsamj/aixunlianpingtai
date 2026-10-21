from dataclasses import replace
import json

import pytest

import app as platform
from platform_core.task_runtime import TaskKind, TaskRecord, TaskStatus


def _job(project_id, identity, **fields):
    path = platform.project_dir(project_id) / 'jobs' / identity / 'job.json'
    platform.write_json(path, {'id': identity, 'asset_algorithm_name': 'frozen', **fields})
    return path


@pytest.mark.parametrize('successes,failed,extra', [(1, 0, None), (1, 3, None), (0, 5, None), (2, 0, 'queued'), (3, 0, 'running'), (3, 0, 'cancelled')])
def test_algorithm_success_count_uses_entire_history_not_page(client, successes, failed, extra):
    project = client.post('/api/projects', json={'name': 'count', 'labels': []}).json()['id']
    algorithm = client.post(f'/api/v12/projects/{project}/algorithms', json={'name': 'one'}).json()['algorithm']['id']
    for index in range(successes):
        _job(project, f'ok-{index}', asset_algorithm_id=algorithm, status='finished', artifact_verified=True)
    for index in range(failed):
        _job(project, f'fail-{index}', asset_algorithm_id=algorithm, status='failed', artifact_verified=True)
    if extra:
        _job(project, 'extra', asset_algorithm_id=algorithm, status=extra, artifact_verified=True)
    response = client.get(f'/api/v12/projects/{project}/algorithms')
    assert response.status_code == 200
    assert response.json()['items'][0]['successful_training_count'] == successes
    assert len(list((platform.project_dir(project) / 'jobs').glob('*/job.json'))) == successes + failed + bool(extra)


def test_durable_status_retry_and_archived_job_payload_are_authoritative(client):
    project = client.post('/api/projects', json={'name': 'durable-count', 'labels': []}).json()['id']
    algorithm = client.post(f'/api/v12/projects/{project}/algorithms', json={'name': 'one'}).json()['algorithm']['id']
    repository = platform.shared_task_repository()
    for index, status in enumerate([TaskStatus.FAILED, TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS]):
        identity = f'count-{project}-{index}'
        task = replace(TaskRecord.new(identity, project, TaskKind.TRAINING, 'payload.json', 'cpu'), status=status, result_ref='result.json', attempt=3)
        repository.create(task)
        platform.shared_task_artifacts().atomic_write_json(identity, 'payload.json', {'asset_algorithm_id': algorithm})
        if status is not TaskStatus.SUCCEEDED:
            _job(project, identity, asset_algorithm_id=algorithm, status='done', artifact_verified=True)
    assert platform._successful_training_counts(project) == {algorithm: 2}


def test_success_count_not_truncated_deduplicated_and_project_isolated(client):
    project = client.post('/api/projects', json={'name': 'full-history', 'labels': []}).json()['id']
    algorithm = client.post(f'/api/v12/projects/{project}/algorithms', json={'name': 'one'}).json()['algorithm']['id']
    for index in range(151):
        _job(project, f'history-{index}', asset_algorithm_id=algorithm, status='done', artifact_verified=True)
    _job(project, 'shadow', task_id='history-0', asset_algorithm_id=algorithm, status='done', artifact_verified=True)
    _job(project, 'unknown', asset_algorithm_id=algorithm, status='done')
    _job(project, 'conversion', asset_algorithm_id=algorithm, status='done', artifact_verified=True, kind='MODEL_CONVERSION')
    assert platform._successful_training_counts(project) == {algorithm: 151}
    assert len(platform.sync_jobs_index(project)) == 50
    assert platform.v12_list_algorithms(project)['items'][0]['successful_training_count'] == 151
    snapshot = platform._v53_build_snapshot(project)
    assert snapshot['algorithms'][0]['successful_training_count'] == 151
    assert len(snapshot['jobs']) == 50
    other = client.post('/api/projects', json={'name': 'other-project', 'labels': []}).json()['id']
    assert platform._successful_training_counts(other) == {}
    summary = client.get(f'/api/v49/projects/{project}/algorithms/{algorithm}/report').json()['summary']
    assert summary['training_count'] == summary['successful_count'] == 151


def test_bootstrap_core_does_not_wait_for_background_ready(client, monkeypatch):
    project = client.post('/api/projects', json={'name': 'cold-core', 'labels': []}).json()
    monkeypatch.setattr(platform, '_V53_BOOTSTRAP_STATUS', {'status': 'running', 'stage': '读取素材索引'})
    monkeypatch.setattr(platform, '_V53_BOOTSTRAP_SNAPSHOT', {})
    monkeypatch.setattr(platform, 'list_projects', lambda: [project])
    response = client.get('/api/v53/bootstrap/snapshot')
    assert response.status_code == 200, response.text
    assert response.json()['project']['id'] == project['id']
    assert response.json()['bootstrap']['status'] == 'running'
    assert float(response.headers['Server-Timing'].split('dur=')[1]) >= 0


def test_history_projection_refreshes_changed_terminal_and_active_without_rewriting_job(tmp_path, monkeypatch):
    from platform_core.task_runtime import TaskRepository
    monkeypatch.setattr(platform, 'project_dir', lambda _: tmp_path)
    monkeypatch.setattr(platform, 'shared_task_repository', lambda: TaskRepository(tmp_path / 'tasks.sqlite3'))
    path = _job('p', 'one', status='failed')
    first = platform.sync_jobs_index('p')
    assert first[0]['status'] == 'failed'
    payload = json.loads(path.read_text())
    payload['status'] = 'queued'
    path.write_text(json.dumps(payload))
    assert platform.sync_jobs_index('p')[0]['status'] == 'queued'
    assert json.loads(path.read_text()) == payload


def test_warm_snapshot_reads_zero_historical_job_json_and_changed_file_once(tmp_path, monkeypatch):
    from platform_core.task_runtime import TaskRepository
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    monkeypatch.setattr(platform, 'project_dir', lambda _: tmp_path)
    monkeypatch.setattr(platform, 'shared_task_repository', lambda: repository)
    path = _job('p', 'one', status='failed')
    original = platform.read_json
    reads = []
    def read(path, default):
        if path.name == 'job.json':
            reads.append(path)
        return original(path, default)
    monkeypatch.setattr(platform, 'read_json', read)
    platform._v53_live_jobs('p')
    assert len(reads) == 1
    platform._v53_live_jobs('p')
    assert len(reads) == 1
    payload = json.loads(path.read_text())
    payload['error'] = 'new failure evidence'
    path.write_text(json.dumps(payload))
    assert platform._v53_live_jobs('p')[0]['error'] == 'new failure evidence'
    assert len(reads) == 2


def test_snapshot_defers_large_report_evidence_without_changing_on_demand_report(client):
    project = client.post('/api/projects', json={'name': 'deferred-report', 'labels': []}).json()['id']
    history = [{'epoch': index + 1, 'map50': .75, 'box_loss': .2} for index in range(1200)]
    errors = [{'image_id': f'image-{index}', 'reason': 'retained actual fixture evidence'} for index in range(1000)]
    report = {'metrics': {'map50': .75}, 'summary': {'epochs': 1200}, 'history': history,
              'error_samples': errors, 'resource_samples': [{'time': index, 'cpu': 12} for index in range(1000)],
              'frozen_evidence': {'selected_ids': [f'image-{index}' for index in range(5000)]}}
    path = _job(project, 'evidence', status='failed', training_report=report,
                dataset_selected_ids={'train': [f'image-{index}' for index in range(5000)]},
                metrics={'map50': .75}, snapshot_id='unknown-history')
    original = json.loads(path.read_text())
    snapshot = platform._v53_build_snapshot(project)
    row = snapshot['jobs'][0]
    assert row['training_report']['metrics'] == {'map50': .75}
    assert row['training_report']['summary'] == {'epochs': 1200}
    assert row['snapshot_id'] == 'unknown-history'
    assert 'history' not in row['training_report']
    assert 'error_samples' not in row['training_report']
    assert 'resource_samples' not in row['training_report']
    assert 'frozen_evidence' not in row['training_report']
    assert 'dataset_selected_ids' not in row
    assert len(json.dumps(row)) < len(json.dumps(original)) * .05
    assert json.loads(path.read_text()) == original
    index = json.loads((path.parent.parent / 'index.json').read_text(encoding='utf-8'))
    assert index[0]['training_report']['history'] == history
    response = client.get(f'/api/v44/projects/{project}/jobs/evidence/report')
    assert response.status_code == 200, response.text
    assert response.json()['report']['history'] == history
    assert response.json()['job']['training_report']['error_samples'] == errors


def test_incremental_legacy_success_keeps_existing_version_archive_recovery(client, monkeypatch):
    from platform_core.algorithms import attach_version
    project = client.post('/api/projects', json={'name': 'legacy-archive', 'labels': []}).json()['id']
    algorithm = client.post(f'/api/v12/projects/{project}/algorithms', json={'name': 'one'}).json()['algorithm']['id']
    attach_version(platform.algorithms_file(project), algorithm, {
        'id': 'historical-version', 'job_id': 'legacy-completed', 'report': {'metrics': {'map50': .7}},
    })
    path = _job(project, 'legacy-completed', status='done', asset_algorithm_id=algorithm, artifact_verified=True)
    original_archive = platform._v48_archive_training_version
    attempts = []
    def archive(project_id, job):
        attempts.append(job['id'])
        return original_archive(project_id, job)
    monkeypatch.setattr(platform, '_v48_archive_training_version', archive)
    rows = platform.sync_jobs_index(project)
    assert rows[0]['auto_version_id'] == 'historical-version'
    assert json.loads(path.read_text(encoding='utf-8'))['auto_version_id'] == 'historical-version'
    platform.sync_jobs_index(project)  # The archive receipt changed job.json once.
    calls_after_receipt = len(attempts)
    platform.sync_jobs_index(project)
    platform.sync_jobs_index(project)
    assert len(attempts) == calls_after_receipt
    assert len(platform.list_algorithms_internal(project)[0]['versions']) == 1
