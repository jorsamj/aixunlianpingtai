from dataclasses import replace

import app as platform_app
from platform_core.task_runtime import TaskKind, TaskRecord, TaskStatus


class FakeRepository:
    def __init__(self, task):
        self.task = task

    def get(self, task_id):
        return self.task if task_id == self.task.task_id else None

    def resource_queue_position(self, task_id):
        assert task_id == self.task.task_id
        return 2


def test_conversion_overlay_projects_real_waiting_resource_truth(monkeypatch):
    task = replace(
        TaskRecord.new(
            'convert-waiting', 'project-1', TaskKind.MODEL_CONVERSION,
            'request.json', 'conversion:gpu:0', priority=20,
            required_capabilities=('conversion.tensorrt',),
        ),
        status=TaskStatus.QUEUED,
        stage='resource_waiting',
        progress=17.5,
        current_item='waiting for GPU memory',
        resource_wait_reason='GPU_MEMORY_BUSY',
        queue_rank=4,
    )
    repository = FakeRepository(task)
    monkeypatch.setattr(platform_app, 'shared_task_repository', lambda: repository)

    job = platform_app._overlay_durable_deploy_job({
        'id': task.task_id, 'task_id': task.task_id, 'status': 'queued',
        'target': 'tensorrt',
    })

    assert job['status'] == 'waiting_resource'
    assert job['task_status'] == 'WAITING_RESOURCE'
    assert job['durable_status'] == 'QUEUED'
    assert job['progress'] == 17.5
    assert job['stage'] == 'resource_waiting'
    assert job['priority'] == 20
    assert job['queue_rank'] == 4
    assert job['resource_queue_position'] == 2
    assert job['resource_wait_reason'] == 'GPU_MEMORY_BUSY'
    assert job['current_item'] == 'waiting for GPU memory'


def test_conversion_overlay_exposes_running_worker_and_lease(monkeypatch):
    task = replace(
        TaskRecord.new(
            'convert-running', 'project-1', TaskKind.MODEL_CONVERSION,
            'request.json', 'conversion:gpu:0', priority=10,
        ),
        status=TaskStatus.RUNNING, stage='converting', progress=62,
        worker_id='conversion-worker-a800',
        lease_expires_at='2026-09-13T01:00:00+00:00',
    )
    repository = FakeRepository(task)
    monkeypatch.setattr(platform_app, 'shared_task_repository', lambda: repository)
    job = platform_app._overlay_durable_deploy_job({
        'id': task.task_id, 'task_id': task.task_id, 'status': 'queued',
    })
    assert job['status'] == 'running'
    assert job['task_status'] == 'RUNNING'
    assert job['worker_id'] == 'conversion-worker-a800'
    assert job['lease_expires_at'] == '2026-09-13T01:00:00+00:00'
    assert job['progress'] == 62
