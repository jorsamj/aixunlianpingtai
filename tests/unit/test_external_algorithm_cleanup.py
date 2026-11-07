from pathlib import Path

import pytest

from platform_core.algorithms import list_algorithms, save_algorithms
from platform_core.errors import PlatformError


def seed(tmp_path):
    path = tmp_path / 'projects' / 'p' / 'algorithms.json'
    path.parent.mkdir(parents=True)
    save_algorithms(path, [{
        'id': 'a', 'name': 'external', 'source_type': 'EXTERNAL',
        'provider_type': 'CHANG_LIAN', 'external_product_id': '11',
        'external_active': True, 'versions': [{'id': 'v'}],
    }])
    return path


@pytest.mark.parametrize('response', [None, {}, {'data': None}, {'data': {}},
    {'data': [None]}, {'code': 500, 'data': []},
    {'data': [{'productId': True, 'productType': 3, 'status': 1}]},
    {'data': [{'productId': '11', 'productName': '产品', 'productType': 3}]},
    {'data': [{'productId': '11', 'productName': '产品', 'productType': 3, 'status': 9}]},
    {'data': [{'productId': '11', 'productName': '产品', 'productType': 3, 'status': 1}] * 2},
    {'data': [], 'total': 1}, {'data': [], 'total': True}])
def test_product_snapshot_rejects_untrusted_response(response):
    from platform_core.external_algorithm_platform import validated_product_snapshot
    with pytest.raises(PlatformError):
        validated_product_snapshot(response)


def test_empty_product_snapshot_is_observation_never_deletion_proof():
    from platform_core.external_algorithm_platform import validated_product_snapshot
    assert validated_product_snapshot({'code': 200, 'data': [], 'total': 0}) == []


def test_missing_product_retains_versions_and_becomes_suspected(tmp_path):
    from platform_core.external_algorithm_platform import mirror_products_to_algorithms
    path = seed(tmp_path)
    result = mirror_products_to_algorithms(algorithms_path=path, products=[], categories=[], analyses_by_product={})
    row = list_algorithms(path)[0]
    assert row['external_deletion_status'] == 'SUSPECTED_DELETED'
    assert row['versions'] == [{'id': 'v'}]
    assert row['external_active'] is True
    assert not row.get('external_delete_pending')
    assert result['deleted'] == 0 and result['suspected_deleted'] == 1


def test_unverified_evidence_cannot_confirm_or_enqueue(tmp_path):
    from platform_core.external_algorithm_cleanup import CleanupRepository, DeletionEvidence
    path = seed(tmp_path)
    repo = CleanupRepository(path)
    evidence = DeletionEvidence('CHANG_LIAN', '11', 'event', 'unknown-contract', 'e1', '2026-10-26T00:00:00Z')
    with pytest.raises(PlatformError):
        repo.confirm_deleted('a', evidence)
    assert not list_algorithms(path)[0].get('external_delete_pending')
    assert repo.list_operations() == []


def test_confirmation_is_atomic_durable_and_idempotent(tmp_path):
    from platform_core.external_algorithm_cleanup import CleanupRepository, DeletionEvidence, VerifiedDeletionContract
    path = seed(tmp_path)
    contract = VerifiedDeletionContract('verified-event-v1', 'event')
    repo = CleanupRepository(path, contracts=(contract,))
    evidence = DeletionEvidence('CHANG_LIAN', '11', 'event', contract.contract_id, 'e1', '2026-10-26T00:00:00Z')
    operation = repo.confirm_deleted('a', evidence)
    assert repo.confirm_deleted('a', evidence)['operation_id'] == operation['operation_id']
    row = list_algorithms(path)[0]
    assert row['external_delete_pending'] is True
    assert row['external_deletion_status'] == 'CONFIRMED_DELETED'
    assert len(CleanupRepository(path).list_operations()) == 1


def test_confirmation_commit_failure_does_not_retire_algorithm(tmp_path, monkeypatch):
    from platform_core.external_algorithm_cleanup import CleanupRepository, DeletionEvidence, VerifiedDeletionContract
    from platform_core.algorithm_sql_store import AlgorithmSqlStore
    path = seed(tmp_path)
    repo = CleanupRepository(path, contracts=(VerifiedDeletionContract('v1', 'event'),))
    def fail(*args):
        raise RuntimeError('injected SQL write failure')
    monkeypatch.setattr(AlgorithmSqlStore, '_update_algorithm_conn', fail)
    with pytest.raises(RuntimeError):
        repo.confirm_deleted('a', DeletionEvidence('CHANG_LIAN', '11', 'event', 'v1', 'e1', '2026-10-26T00:00:00Z'))
    assert repo.list_operations() == []
    assert not list_algorithms(path)[0].get('external_delete_pending')


def confirmed(tmp_path):
    from platform_core.external_algorithm_cleanup import CleanupRepository, DeletionEvidence, VerifiedDeletionContract
    path = seed(tmp_path)
    repo = CleanupRepository(path, contracts=(VerifiedDeletionContract('v1', 'event'),))
    op = repo.confirm_deleted('a', DeletionEvidence('CHANG_LIAN', '11', 'event', 'v1', 'e1', '2026-10-26T00:00:00Z'))
    return path, repo, op


def worker(tmp_path, *, models=None):
    from platform_core.external_algorithm_cleanup import ExternalAlgorithmCleanupHandler
    from platform_core.task_runtime import ArtifactStore, FencedTaskRepository, Scheduler, TaskKind
    tasks = FencedTaskRepository(tmp_path / 'task_runtime' / 'tasks.sqlite3')
    artifacts = ArtifactStore(tmp_path / 'task_runtime' / 'artifacts')
    handler = ExternalAlgorithmCleanupHandler(tmp_path, model_service_factory=(lambda: models) if models else None,
        stop_timeout_seconds=0.03, stop_poll_seconds=0.01)
    return tasks, artifacts, Scheduler(tasks, artifacts, 'cleanup-worker',
        {TaskKind.EXTERNAL_ALGORITHM_CLEANUP: handler}, {'external.cleanup'})


def add_task(tasks, artifacts, identity, algorithm='a', kind=None):
    from platform_core.task_runtime import TaskRecord, TaskKind
    artifacts.atomic_write_json(identity, 'request.json', {'algorithm_asset_id': algorithm})
    tasks.create(TaskRecord.new(identity, 'p', kind or TaskKind.TRAINING, 'request.json', 'training:remote:test'))


def test_version_delete_receipt_cannot_retire_product(tmp_path):
    from platform_core.external_algorithm_cleanup import CleanupRepository, DeletionEvidence, VerifiedDeletionContract
    path = seed(tmp_path)
    repo = CleanupRepository(path, contracts=(VerifiedDeletionContract('v1', 'event'),))
    with pytest.raises(PlatformError, match='产品'):
        repo.confirm_deleted('a', DeletionEvidence('CHANG_LIAN', '11', 'event', 'v1', 'version-receipt', 'now', 'VERSION_DELETED'))
    assert not list_algorithms(path)[0].get('external_delete_pending')


def test_dispatch_is_idempotent_and_cleanup_keeps_durable_receipt(tmp_path):
    path, repo, op = confirmed(tmp_path)
    tasks, artifacts, scheduler = worker(tmp_path)
    add_task(tasks, artifacts, 'owned')
    add_task(tasks, artifacts, 'other', 'other-algorithm')
    job = path.parent / 'jobs' / 'owned'
    job.mkdir(parents=True)
    (job / 'model.pt').write_bytes(b'model')
    repo.dispatch(tmp_path)
    repo.dispatch(tmp_path)
    assert scheduler.run_once()
    assert tasks.get(op['task_id']).status.value == 'SUCCEEDED'
    assert list_algorithms(path) == []
    assert tasks.get('owned') is None
    assert tasks.get('other').status.value == 'QUEUED'
    assert repo.get(op['operation_id'])['state'] == 'CLEANUP_COMPLETED'
    assert not job.exists()
    assert any((tmp_path / 'external_cleanup_recovery').rglob('model.pt'))


def test_active_durable_without_job_file_is_cancelled_then_waited(tmp_path):
    from platform_core.task_runtime import TaskKind
    path, repo, op = confirmed(tmp_path)
    tasks, artifacts, scheduler = worker(tmp_path)
    add_task(tasks, artifacts, 'running')
    lease = tasks.claim_next('trainer', (TaskKind.TRAINING,), (), 30)
    repo.dispatch(tmp_path)
    scheduler.run_once()
    assert tasks.get('running').status.value == 'CANCEL_REQUESTED'
    assert repo.get(op['operation_id'])['state'] == 'CLEANUP_FAILED'
    assert list_algorithms(path)[0]['versions'] == [{'id': 'v'}]
    tasks.finish('running', lease.lease_token, __import__('platform_core.task_runtime', fromlist=['TaskStatus']).TaskStatus.CANCELLED,
                 execution_generation=lease.task.attempt)
    repo.dispatch(tmp_path, retry_failed=True)
    scheduler.run_once()
    assert repo.get(op['operation_id'])['state'] == 'CLEANUP_COMPLETED'


def test_outbox_survives_task_creation_failure_and_restart(tmp_path, monkeypatch):
    from platform_core.external_algorithm_cleanup import CleanupRepository
    from platform_core.task_runtime import TaskRepository
    path, repo, op = confirmed(tmp_path)
    original = TaskRepository.create
    monkeypatch.setattr(TaskRepository, 'create', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('task db unavailable')))
    with pytest.raises(RuntimeError):
        repo.dispatch(tmp_path)
    assert list_algorithms(path)[0]['external_delete_pending']
    monkeypatch.setattr(TaskRepository, 'create', original)
    CleanupRepository(path).dispatch(tmp_path)
    assert TaskRepository(tmp_path / 'task_runtime/tasks.sqlite3').get(op['task_id'])


def test_recreated_product_has_new_cleanup_cycle_and_old_worker_is_fenced(tmp_path):
    from platform_core.external_algorithm_cleanup import DeletionEvidence
    path, repo, old = confirmed(tmp_path)
    tasks, artifacts, scheduler = worker(tmp_path)
    repo.dispatch(tmp_path)
    scheduler.run_once()
    assert repo.get(old['operation_id'])['state'] == 'CLEANUP_COMPLETED'
    save_algorithms(path, [{'id': 'a', 'name': 'recreated', 'source_type': 'EXTERNAL',
        'provider_type': 'CHANG_LIAN', 'external_product_id': '11', 'external_active': True, 'versions': []}])
    new = repo.confirm_deleted('a', DeletionEvidence('CHANG_LIAN', '11', 'event', 'v1', 'e2', 'later'))
    assert new['operation_id'] != old['operation_id']
    with pytest.raises(PlatformError):
        repo.update(old['operation_id'], state='CLEANUP_RUNNING')
    assert list_algorithms(path)[0]['external_cleanup_operation_id'] == new['operation_id']


def model_fixture(tmp_path, monkeypatch):
    import hashlib
    from platform_core.model_artifacts import ModelArtifactService, build_artifact_object_key
    service = ModelArtifactService(data_dir=tmp_path, project_dir=lambda p: tmp_path/'projects'/p,
        algorithms_file=lambda p: tmp_path/'projects'/p/'algorithms.json',
        storage_sources_factory=lambda: None, storage_credentials_factory=lambda: None)
    source = tmp_path/'projects/p/algorithm_versions/a/v/best.pt'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b'model')
    row = service.repository.upsert(dict(artifact_id='artifact-a', project_id='p', algorithm_id='a',
        version_id='v', artifact_kind='original', target='original', file_name='best.pt',
        source_path=str(source), sha256=hashlib.sha256(b'model').hexdigest(), size_bytes=5, metadata={}))
    key = build_artifact_object_key(root_prefix='changlian-ai/artifacts', project_id='p',
        algorithm_id='a', version_id='v', target='original', sha256=row['sha256'], file_name='best.pt')
    row = service.repository.patch(row['artifact_id'], storage_source_id='oss', object_key=key, storage_status='UPLOADED')
    class Provider:
        exists_now = True
        fail = False
        deleted = 0
        def exists(self, key): return self.exists_now
        def download(self, key, destination): Path(destination).write_bytes(b'model')
        def delete(self, key):
            if self.fail: raise RuntimeError('injected OSS denial')
            self.deleted += 1
            self.exists_now = False
    provider = Provider()
    monkeypatch.setattr(service, '_provider', lambda *a: provider)
    return service, provider, row


def test_oss_failure_retains_rows_and_verified_backup_then_retries_same_task(tmp_path, monkeypatch):
    path, repo, op = confirmed(tmp_path)
    models, provider, row = model_fixture(tmp_path, monkeypatch)
    provider.fail = True
    tasks, artifacts, scheduler = worker(tmp_path, models=models)
    repo.dispatch(tmp_path)
    scheduler.run_once()
    assert repo.get(op['operation_id'])['state'] == 'CLEANUP_FAILED'
    assert models.repository.get(row['artifact_id'])
    assert list_algorithms(path)
    assert any((tmp_path/'external_cleanup_recovery').rglob('*.bin'))
    provider.fail = False
    repo.dispatch(tmp_path, retry_failed=True)
    scheduler.run_once()
    assert tasks.get(op['task_id']).status.value == 'SUCCEEDED'
    assert provider.deleted == 1
    assert models.repository.get(row['artifact_id']) is None


def test_shared_object_or_unverified_key_is_never_deleted(tmp_path, monkeypatch):
    models, provider, row = model_fixture(tmp_path, monkeypatch)
    shared = models.repository.upsert({**row, 'artifact_id':'other-artifact', 'algorithm_id':'other', 'version_id':'other-v'})
    models.repository.patch(shared['artifact_id'], storage_source_id='oss', object_key=row['object_key'])
    with pytest.raises(PlatformError) as error:
        models.purge_confirmed_artifact(row, tmp_path/'backup')
    assert error.value.code == 'EXTERNAL_CLEANUP_OBJECT_SHARED'
    assert provider.deleted == 0
    with models.repository._connect() as db:
        db.execute('DELETE FROM model_artifacts WHERE artifact_id=?', (shared['artifact_id'],))
    row = models.repository.patch(row['artifact_id'], object_key='foreign/best.pt')
    with pytest.raises(PlatformError):
        models.purge_confirmed_artifact(row, tmp_path/'backup')
    assert provider.deleted == 0


def test_final_sql_commit_failure_retains_outbox_and_recovers(tmp_path, monkeypatch):
    from platform_core.external_algorithm_cleanup import CleanupRepository
    path, repo, op = confirmed(tmp_path)
    tasks, artifacts, scheduler = worker(tmp_path)
    repo.dispatch(tmp_path)
    original = CleanupRepository.update
    def fail(self, identity, **kwargs):
        if kwargs.get('remove_algorithm'): raise RuntimeError('injected final SQL failure')
        return original(self, identity, **kwargs)
    monkeypatch.setattr(CleanupRepository, 'update', fail)
    scheduler.run_once()
    assert list_algorithms(path)
    assert repo.get(op['operation_id'])['state'] == 'CLEANUP_FAILED'
    monkeypatch.setattr(CleanupRepository, 'update', original)
    repo.dispatch(tmp_path, retry_failed=True)
    scheduler.run_once()
    assert repo.get(op['operation_id'])['state'] == 'CLEANUP_COMPLETED'


def test_public_operations_are_paginated_and_suspicion_has_no_task(tmp_path):
    from platform_core.external_algorithm_cleanup import CleanupRepository
    from platform_core.external_algorithm_platform import mirror_products_to_algorithms
    path = seed(tmp_path)
    mirror_products_to_algorithms(algorithms_path=path, products=[], categories=[], analyses_by_product={})
    repo = CleanupRepository(path)
    items = repo.public_operations(limit=1)
    assert len(items) == 1 and items[0]['operation_id'] == 'suspect:a'
    assert items[0]['task_id'] == '' and not items[0]['evidence']['authoritative']
    assert repo.public_operation('suspect:a') == items[0]
    assert repo.public_operations(limit=1, offset=1) == []
    assert repo.summary()['SUSPECTED_DELETED'] == 1


def test_concurrent_confirmation_uses_single_active_generation(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from platform_core.external_algorithm_cleanup import CleanupRepository, DeletionEvidence, VerifiedDeletionContract
    path = seed(tmp_path)
    def confirm(index):
        repo = CleanupRepository(path, contracts=(VerifiedDeletionContract('v1', 'event'),))
        return repo.confirm_deleted('a', DeletionEvidence('CHANG_LIAN', '11', 'event', 'v1', f'e{index}', 'time'))
    with ThreadPoolExecutor(max_workers=3) as pool:
        operations = list(pool.map(confirm, range(3)))
    assert len({op['operation_id'] for op in operations}) == 1
    assert len(CleanupRepository(path).list_operations()) == 1


def test_shared_version_task_is_retained(tmp_path):
    path, repo, op = confirmed(tmp_path)
    from platform_core.algorithm_sql_store import AlgorithmSqlStore
    store = AlgorithmSqlStore(path)
    store.create_algorithm({'id':'other', 'name':'other'})
    store.attach_version('other', {'id':'other-v', 'task_id':'shared'})
    tasks, artifacts, scheduler = worker(tmp_path)
    add_task(tasks, artifacts, 'shared')
    repo.dispatch(tmp_path)
    scheduler.run_once()
    assert repo.get(op['operation_id'])['state'] == 'CLEANUP_FAILED'
    assert tasks.get('shared') is not None
    assert tasks.get('shared').status.value == 'QUEUED'
    assert len(list_algorithms(path)) == 2


def test_worker_waits_for_safe_exit_and_continues_same_task(tmp_path, monkeypatch):
    from platform_core.task_runtime import TaskKind, TaskStatus, WorkerContext
    path, repo, op = confirmed(tmp_path)
    tasks, artifacts, scheduler = worker(tmp_path)
    add_task(tasks, artifacts, 'active')
    lease = tasks.claim_next('trainer', (TaskKind.TRAINING,), (), 30)
    original = WorkerContext.heartbeat
    observed = []
    def heartbeat(context, *args, **kwargs):
        if kwargs.get('stage') == 'waiting_for_tasks' and not observed:
            observed.append(repo.get(op['operation_id'])['state'])
            tasks.finish('active', lease.lease_token, TaskStatus.CANCELLED, execution_generation=lease.task.attempt)
        return original(context, *args, **kwargs)
    monkeypatch.setattr(WorkerContext, 'heartbeat', heartbeat)
    repo.dispatch(tmp_path)
    scheduler.run_once()
    assert observed == ['CLEANUP_RUNNING']
    assert tasks.get(op['task_id']).status == TaskStatus.SUCCEEDED
    assert repo.get(op['operation_id'])['state'] == 'CLEANUP_COMPLETED'


@pytest.mark.parametrize('filename', ['model:stream', 'CON.bin', 'trailing.'])
def test_cleanup_rejects_windows_stream_and_device_aliases(tmp_path, filename):
    from platform_core.external_algorithm_cleanup import assert_safe_cleanup_path
    with pytest.raises(PlatformError):
        assert_safe_cleanup_path(tmp_path / 'backup' / filename, tmp_path)


def test_backup_ancestor_link_is_rejected_before_oss_delete(tmp_path, monkeypatch):
    models, provider, row = model_fixture(tmp_path, monkeypatch)
    target = tmp_path / 'outside'
    target.mkdir()
    link = tmp_path / 'linked'
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip('OS does not permit symlink creation')
    with pytest.raises(PlatformError):
        models.purge_confirmed_artifact(row, link/'objects')
    assert provider.deleted == 0


def test_artifact_sql_commit_failure_after_oss_delete_is_recoverable(tmp_path, monkeypatch):
    models, provider, row = model_fixture(tmp_path, monkeypatch)
    original = models.repository._connect
    class FailedCommit:
        def __init__(self, db): self.db, self.deleted = db, False
        def execute(self, sql, *args):
            self.deleted |= sql.startswith('DELETE FROM model_artifacts')
            return self.db.execute(sql, *args)
        def commit(self):
            if self.deleted: raise RuntimeError('injected artifact SQL commit failure')
            self.db.commit()
        def __getattr__(self, name): return getattr(self.db, name)
    monkeypatch.setattr(models.repository, '_connect', lambda: FailedCommit(original()))
    with pytest.raises(RuntimeError):
        models.purge_confirmed_artifact(row, tmp_path/'backup')
    assert models.repository.get(row['artifact_id'])
    assert provider.deleted == 1
    monkeypatch.setattr(models.repository, '_connect', original)
    models.purge_confirmed_artifact(row, tmp_path/'backup')
    assert models.repository.get(row['artifact_id']) is None
    assert provider.deleted == 1


def test_stale_worker_lease_cannot_start_cleanup(tmp_path):
    from platform_core.external_algorithm_cleanup import ExternalAlgorithmCleanupHandler
    from platform_core.task_runtime import TaskKind, WorkerContext, ExecutionFencedError
    path, repo, op = confirmed(tmp_path)
    tasks, artifacts, scheduler = worker(tmp_path)
    repo.dispatch(tmp_path)
    old = tasks.claim_next('old', (TaskKind.EXTERNAL_ALGORITHM_CLEANUP,), ('external.cleanup',), 30)
    with tasks._connect() as db:
        db.execute("UPDATE tasks SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE task_id=?", (old.task.task_id,))
    replacement = tasks.claim_next('new', (TaskKind.EXTERNAL_ALGORITHM_CLEANUP,), ('external.cleanup',), 30)
    assert replacement.task.attempt > old.task.attempt
    context = WorkerContext(old.task, old, tasks, artifacts)
    with pytest.raises(ExecutionFencedError):
        ExternalAlgorithmCleanupHandler(tmp_path).run(context)
    assert repo.get(op['operation_id'])['state'] == 'CLEANUP_PENDING'
    assert list_algorithms(path)


def test_cleanup_http_routes_have_project_guard_and_no_confirmation(tmp_path):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from platform_core.external_algorithm_platform import external_algorithm_platform_router, mirror_products_to_algorithms
    from platform_core.secrets import MemorySecretStore
    path = seed(tmp_path)
    mirror_products_to_algorithms(algorithms_path=path, products=[], categories=[], analyses_by_product={})
    def project(identity):
        if identity != 'p': raise HTTPException(404)
    app = FastAPI()
    app.include_router(external_algorithm_platform_router(data_dir=tmp_path, get_project=project,
        algorithms_file=lambda identity: path, secret_store_factory=MemorySecretStore))
    client = TestClient(app)
    prefix = '/api/v63/external-algorithm-platform'
    listing = client.get(prefix+'/cleanup-operations?project_id=p&limit=1').json()
    assert listing['total'] == 1 and listing['limit'] == 1 and not listing['has_more']
    assert client.get(prefix+'/cleanup-operations/suspect:a?project_id=p').json()['operation']['state'] == 'SUSPECTED_DELETED'
    assert client.get(prefix+'/cleanup-operations?project_id=other').status_code == 404
    assert client.post(prefix+'/cleanup-operations/suspect:a/confirm?project_id=p', json={'trusted':True}).status_code == 404


def test_other_queued_training_frozen_base_blocks_cleanup_before_cancel(tmp_path):
    import hashlib
    from platform_core.training_tasks import resolve_frozen_training_base
    path, repo, op = confirmed(tmp_path)
    tasks, artifacts, scheduler = worker(tmp_path)
    add_task(tasks, artifacts, 'owned')
    add_task(tasks, artifacts, 'other', 'other-algorithm')
    source = path.parent/'jobs/owned/best.pt'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'shared-checkpoint')
    payload = {'algorithm_asset_id':'other-algorithm', 'label_contract':{
        'base_model_contract_schema_version':1, 'base_training_mode':'previous_weights_init',
        'base_version_id':'shared-v', 'base_model_reference':str(source),
        'base_model_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'base_model_size_bytes':source.stat().st_size}}
    artifacts.atomic_write_json('other', 'request.json', payload)
    assert resolve_frozen_training_base(payload)['base_model_path'] == str(source.resolve())
    repo.dispatch(tmp_path)
    scheduler.run_once()
    assert repo.get(op['operation_id'])['state'] == 'CLEANUP_FAILED'
    assert tasks.get('owned').status.value == 'QUEUED'
    assert tasks.get('other').status.value == 'QUEUED'
    assert resolve_frozen_training_base(payload)['base_model_path'] == str(source.resolve())


def test_other_version_path_without_artifact_or_task_id_blocks_cleanup(tmp_path):
    from platform_core.algorithm_sql_store import AlgorithmSqlStore
    path, repo, op = confirmed(tmp_path)
    tasks, artifacts, scheduler = worker(tmp_path)
    add_task(tasks, artifacts, 'owned')
    source = path.parent/'jobs/owned/best.pt'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'shared-model')
    store = AlgorithmSqlStore(path)
    store.create_algorithm({'id':'other', 'name':'other'})
    store.attach_version('other', {'id':'other-v', 'stored_path':str(source)})
    repo.dispatch(tmp_path)
    scheduler.run_once()
    assert repo.get(op['operation_id'])['state'] == 'CLEANUP_FAILED'
    assert tasks.get('owned').status.value == 'QUEUED'
    assert source.read_bytes() == b'shared-model'


def test_cross_project_checkpoint_reference_blocks_cleanup(tmp_path):
    from platform_core.task_runtime import TaskRecord, TaskKind
    path, repo, op = confirmed(tmp_path)
    tasks, artifacts, scheduler = worker(tmp_path)
    add_task(tasks, artifacts, 'owned')
    source = path.parent/'jobs/owned/last.pt'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'checkpoint')
    artifacts.atomic_write_json('foreign', 'request.json', {'algorithm_asset_id':'foreign-algorithm'})
    artifacts.atomic_write_json('foreign', 'checkpoints/worker.json', {'checkpoint':{'path':str(source)}})
    tasks.create(TaskRecord.new('foreign', 'other-project', TaskKind.TRAINING, 'request.json', 'training:remote:foreign'))
    repo.dispatch(tmp_path)
    scheduler.run_once()
    assert repo.get(op['operation_id'])['state'] == 'CLEANUP_FAILED'
    assert tasks.get('owned').status.value == tasks.get('foreign').status.value == 'QUEUED'
    assert source.is_file()


def test_consumer_inserted_after_plan_freeze_is_rechecked_before_object_delete(tmp_path, monkeypatch):
    path, repo, op = confirmed(tmp_path)
    models, provider, row = model_fixture(tmp_path, monkeypatch)
    tasks, artifacts, scheduler = worker(tmp_path, models=models)
    original = provider.download
    inserted = []
    def download(key, destination):
        original(key, destination)
        if not inserted:
            inserted.append(True)
            add_task(tasks, artifacts, 'late-consumer', 'other-algorithm')
            artifacts.atomic_write_json('late-consumer', 'request.json',
                {'algorithm_asset_id':'other-algorithm', 'label_contract':{'base_model_reference':row['source_path']}})
    monkeypatch.setattr(provider, 'download', download)
    repo.dispatch(tmp_path)
    scheduler.run_once()
    assert repo.get(op['operation_id'])['state'] == 'CLEANUP_FAILED'
    assert provider.deleted == 0
    assert models.repository.get(row['artifact_id'])
    assert Path(row['source_path']).is_file()
    assert tasks.get('late-consumer').status.value == 'QUEUED'


def test_retired_synchronous_purger_cannot_cancel_or_delete(tmp_path):
    from platform_core.external_algorithm_platform import ExternalAlgorithmLocalPurger
    from platform_core.secrets import MemorySecretStore
    path = seed(tmp_path)
    tasks, artifacts, scheduler = worker(tmp_path)
    add_task(tasks, artifacts, 'owned')
    source = path.parent/'jobs/owned/best.pt'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'protected')
    with pytest.raises(PlatformError) as error:
        ExternalAlgorithmLocalPurger(tmp_path, MemorySecretStore).purge('p', list_algorithms(path)[0])
    assert error.value.code == 'EXTERNAL_ALGORITHM_DURABLE_CLEANUP_REQUIRED'
    assert tasks.get('owned').status.value == 'QUEUED'
    assert source.read_bytes() == b'protected'
    assert len(list_algorithms(path)) == 1


def test_repeated_suspected_observation_updates_check_time_without_revision_or_history(tmp_path):
    from platform_core.algorithm_sql_store import AlgorithmSqlStore
    from platform_core.external_algorithm_cleanup import CleanupRepository
    from platform_core.external_algorithm_platform import mirror_products_to_algorithms
    path = seed(tmp_path)
    def observe(stamp):
        mirror_products_to_algorithms(algorithms_path=path, products=[], categories=[],
            analyses_by_product={}, synced_at=stamp)
    observe('2026-10-26T01:00:00Z')
    first = CleanupRepository(path).public_operation('suspect:a')
    revision = AlgorithmSqlStore(path).revision()
    observe('2026-10-26T02:00:00Z')
    second = CleanupRepository(path).public_operation('suspect:a')
    assert second['created_at'] == first['created_at'] == '2026-10-26T01:00:00Z'
    assert second['updated_at'] == '2026-10-26T02:00:00Z'
    assert second['history'] == first['history']
    assert AlgorithmSqlStore(path).revision() == revision
