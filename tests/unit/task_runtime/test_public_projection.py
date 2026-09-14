import os

from platform_core.task_runtime import (
    TaskKind,
    TaskRecord,
    TaskRepository,
    WorkerInstanceService,
    task_to_public,
    training_queue_truth,
)


def add(repository, task_id, priority=50, resource='gpu:0'):
    return repository.create(TaskRecord.new(
        task_id, 'project-1', TaskKind.TRAINING, 'request.json', resource,
        priority=priority, required_capabilities=('cuda',),
    ))


def register_worker(
    repository,
    worker_id,
    *,
    task_kinds=(TaskKind.TRAINING.value,),
    capabilities=('cuda',),
):
    return WorkerInstanceService(repository).acquire(
        repository.path.parent,
        {worker_id},
        'default',
        worker_id,
        pid=os.getpid(),
        hostname=f'{worker_id}.example',
        build_id='build-current',
        task_kinds=task_kinds,
        capabilities=capabilities,
    )


def test_training_queue_truth_waits_when_no_worker_is_online(tmp_path):
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    task = add(repository, 'no-worker', resource='training:cpu')

    truth = training_queue_truth(task, repository)

    assert truth['status'] == 'WAITING_RESOURCE'
    assert truth['resource_wait_reason'] == '当前没有在线 Worker'
    assert repository.get(task.task_id).status.value == 'QUEUED'
    assert repository.get(task.task_id).stage == 'queued'


def test_training_queue_truth_requires_training_task_kind(tmp_path):
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    task = add(repository, 'wrong-kind', resource='training:cpu')
    register_worker(
        repository,
        'annotation-worker',
        task_kinds=(TaskKind.AI_ANNOTATION.value,),
        capabilities=('cuda',),
    )

    truth = training_queue_truth(task, repository)

    assert truth['status'] == 'WAITING_RESOURCE'
    assert truth['resource_wait_reason'] == '当前没有可执行训练任务的 Worker'


def test_training_queue_truth_requires_all_capabilities(tmp_path):
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    task = add(repository, 'missing-capability', resource='training:cpu')
    register_worker(repository, 'training-worker', capabilities=('training.ultralytics',))

    truth = training_queue_truth(task, repository)

    assert truth['status'] == 'WAITING_RESOURCE'
    assert truth['resource_wait_reason'] == '当前在线 Training Worker 不支持 cuda'


def test_training_queue_truth_recovers_when_compatible_worker_arrives(tmp_path):
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    task = add(repository, 'worker-recovers', resource='training:cpu')
    assert training_queue_truth(task, repository)['status'] == 'WAITING_RESOURCE'

    register_worker(repository, 'training-worker', capabilities=('cuda',))
    truth = training_queue_truth(task, repository)

    assert truth['status'] == 'QUEUED'
    assert truth['resource_wait_reason'] is None


def test_training_queue_truth_preserves_scheduler_admission_reason(tmp_path):
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    task = add(repository, 'admission-wait', resource='training:auto')
    register_worker(repository, 'training-worker', capabilities=('cuda',))

    def deny(_database, _candidate, _worker_id, _token, _expires_at, _now):
        return False, 'GPU_MEMORY_BUSY'

    assert repository.claim_next(
        'training-worker', [TaskKind.TRAINING], {'cuda'}, admission=deny,
    ) is None
    waiting = repository.get(task.task_id)
    truth = training_queue_truth(waiting, repository)

    assert truth['status'] == 'WAITING_RESOURCE'
    assert truth['resource_wait_reason'] == 'GPU_MEMORY_BUSY'


def test_remote_training_never_borrows_local_worker_compatibility(tmp_path):
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    task = add(repository, 'remote-task', resource='training:remote:A800-01')
    register_worker(repository, 'local-training-worker', capabilities=('cuda',))

    truth = training_queue_truth(task, repository)

    assert truth['status'] == 'WAITING_RESOURCE'
    assert truth['resource_pool_key'] == 'training:remote:A800-01'
    assert truth['resource_pool_label'] == '指定远程服务器'
    assert truth['resource_wait_reason'] == '指定远程服务器的 Worker 路由尚未建立'


def test_queue_position_is_exact_only_for_a_provable_cpu_worker_queue(tmp_path):
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    first = add(repository, 'cpu-first', priority=5, resource='training:cpu')
    second = add(repository, 'cpu-second', priority=50, resource='training:cpu')
    register_worker(repository, 'dedicated-training-worker', capabilities=('cuda',))

    truth = training_queue_truth(second, repository)

    assert truth['status'] == 'QUEUED'
    assert truth['resource_pool_label'] == 'CPU'
    assert truth['resource_queue_position'] == 2
    assert truth['resource_queue_position_exact'] is True
    assert repository.resource_queue_position(first.task_id) == 1


def test_gpu_resource_position_is_not_presented_as_exact_without_gpu_runtime_truth(tmp_path):
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    task = add(repository, 'gpu-auto', resource='training:auto')
    register_worker(repository, 'training-worker', capabilities=('cuda',))

    truth = training_queue_truth(task, repository)

    assert truth['status'] == 'QUEUED'
    assert truth['resource_pool_label'] == 'GPU 自动'
    assert truth['resource_queue_position'] == 1
    assert truth['resource_queue_position_exact'] is False


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
