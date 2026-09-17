import uuid

import app as platform_app
from platform_core.task_runtime import TaskKind, TaskRecord


def make_task(project_id, *, priority=50, resource='cpu:unified', capability='unified.test'):
    task_id = f'unified-{uuid.uuid4().hex[:10]}'
    return platform_app.shared_task_repository().create(TaskRecord.new(
        task_id, project_id, TaskKind.DEPLOYMENT_TEST, 'request.json', resource,
        priority=priority, required_capabilities=(capability,),
    ))


def test_unified_task_api_reports_real_queue_state_and_promote(client, seeded_project):
    project_id, _image = seeded_project
    first = make_task(project_id, priority=10)
    second = make_task(project_id, priority=50)

    listing = client.get(f'/api/v62/projects/{project_id}/tasks?kind=DEPLOYMENT_TEST')
    listing.raise_for_status()
    by_id = {item['task_id']: item for item in listing.json()['items']}
    assert by_id[first.task_id]['status'] == 'QUEUED'
    assert by_id[first.task_id]['resource_queue_position'] == 1
    assert by_id[second.task_id]['resource_queue_position'] == 2

    promoted = client.post(f'/api/v62/projects/{project_id}/tasks/{second.task_id}/promote')
    promoted.raise_for_status()
    assert promoted.json()['priority'] < first.priority
    assert promoted.json()['resource_queue_position'] == 1


def test_unified_task_api_survives_repository_reopen_and_exposes_worker_truth(client, seeded_project):
    project_id, _image = seeded_project
    task = make_task(project_id, priority=1, resource='cpu:lease', capability='lease.test')
    repository = platform_app.shared_task_repository()
    lease = repository.claim_next('worker-real-01', [TaskKind.DEPLOYMENT_TEST], {'lease.test'})
    assert lease is not None and lease.task.task_id == task.task_id
    repository.heartbeat(task.task_id, lease.lease_token, progress=61, stage='running_test', current_item='sample-61')

    # Simulate a new API-side repository object reading the persisted truth.
    platform_app._SHARED_TASK_REPOSITORY = None
    response = client.get(f'/api/v62/projects/{project_id}/tasks/{task.task_id}')
    response.raise_for_status()
    body = response.json()
    assert body['status'] == 'RUNNING'
    assert body['progress_percent'] == 61
    assert body['phase'] == 'running_test'
    assert body['current_item'] == 'sample-61'
    assert body['worker_id'] == 'worker-real-01'
    assert body['lease_expires_at']


def test_unified_task_cancel_is_real_repository_state(client, seeded_project):
    project_id, _image = seeded_project
    task = make_task(project_id, resource='cpu:cancel')
    response = client.post(f'/api/v62/projects/{project_id}/tasks/{task.task_id}/cancel')
    response.raise_for_status()
    assert response.json()['status'] == 'CANCELLED'
    again = client.get(f'/api/v62/projects/{project_id}/tasks/{task.task_id}')
    again.raise_for_status()
    assert again.json()['status'] == 'CANCELLED'
