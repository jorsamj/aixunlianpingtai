from platform_core.task_runtime import TaskKind, TaskRecord, TaskRepository, task_to_public


def add(repository, task_id, priority=50, resource='gpu:0'):
    return repository.create(TaskRecord.new(
        task_id, 'project-1', TaskKind.TRAINING, 'request.json', resource,
        priority=priority, required_capabilities=('cuda',),
    ))


def test_public_projection_exposes_real_waiting_resource_and_resource_queue_position(tmp_path):
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    first = add(repository, 'first', priority=5)
    second = add(repository, 'second', priority=50)
    assert repository.resource_queue_position(first.task_id) == 1
    assert repository.resource_queue_position(second.task_id) == 2

    promoted = repository.promote('second')
    assert promoted.priority == 4
    assert repository.resource_queue_position('second') == 1

    def deny(database, candidate, worker_id, token, expires_at, now):
        return False, 'GPU_MEMORY_BUSY'

    assert repository.claim_next('worker', [TaskKind.TRAINING], {'cuda'}, admission=deny) is None
    waiting = repository.get('second')
    assert waiting is not None
    public = task_to_public(waiting, repository)
    assert public['status'] == 'WAITING_RESOURCE'
    assert public['persisted_status'] == 'QUEUED'
    assert public['resource_wait_reason'] == 'GPU_MEMORY_BUSY'
    assert public['resource_queue_position'] == 1


def test_worker_lease_and_progress_survive_repository_reopen(tmp_path):
    path = tmp_path / 'tasks.sqlite3'
    repository = TaskRepository(path)
    add(repository, 'running', priority=1, resource='gpu:9')
    lease = repository.claim_next('worker-a800-01', [TaskKind.TRAINING], {'cuda'})
    assert lease is not None
    repository.heartbeat(lease.task.task_id, lease.lease_token, progress=37.5, stage='training', current_item='epoch 3/10')

    reopened = TaskRepository(path)
    task = reopened.get('running')
    assert task is not None
    assert task.worker_id == 'worker-a800-01'
    assert task.lease_expires_at
    public = task_to_public(task, reopened)
    assert public['status'] == 'RUNNING'
    assert public['progress_percent'] == 37.5
    assert public['phase'] == 'training'
    assert public['current_item'] == 'epoch 3/10'
    assert public['worker_id'] == 'worker-a800-01'
    assert public['lease_expires_at']
    assert public['resource_queue_position'] is None
