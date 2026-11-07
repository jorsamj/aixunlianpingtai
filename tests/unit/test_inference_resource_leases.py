from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import multiprocessing
from pathlib import Path
import sys
import time

import pytest

from platform_core.task_runtime import FencedTaskRepository, TaskKind, TaskRecord


def claim(repo, name):
    repo.create(TaskRecord.new(name, 'p', TaskKind.AI_ANNOTATION, 'request.json', 'vision:' + name))
    return repo.claim_next(name, [TaskKind.AI_ANNOTATION], [], lease_seconds=30)


def acquire(repo, lease, domain='same-account', capacity=2):
    return repo.acquire_inference_permit(
        task_id=lease.task.task_id, lease_token=lease.lease_token,
        execution_generation=lease.task.attempt, domain=domain,
        capacity=capacity, hold_seconds=600, requests_per_minute=0,
    )


def _spawn_permit_contender(path, name, ready, dispatch, release, results):
    """Top-level target is importable under Windows multiprocessing spawn."""
    repo = FencedTaskRepository(path)
    lease = claim(repo, name)
    # The canonical two-phase claim may lose its candidate snapshot to another
    # process. Like the Worker, poll again; create the task only once.
    deadline = time.monotonic() + 10
    while lease is None and time.monotonic() < deadline:
        time.sleep(.01)
        lease = repo.claim_next(name, [TaskKind.AI_ANNOTATION], [], lease_seconds=30)
    assert lease is not None, 'contender did not acquire a task lease before dispatch'
    ready.put(name)
    if not dispatch.wait(20):
        raise RuntimeError('parent did not open dispatch gate')
    receipt = acquire(repo, lease, capacity=1)
    results.put(receipt)
    if not release.wait(20):
        raise RuntimeError('parent did not release held requests')
    if receipt['permit_id']:
        repo.release_inference_permit(receipt['permit_id'])


def test_spawned_processes_share_durable_capacity_until_actual_call_release(tmp_path, monkeypatch):
    # Some environments have an installed `tests` package. Spawn imports this
    # target by its unique basename instead of the pytest namespace package.
    module_name = Path(__file__).stem
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    monkeypatch.setitem(sys.modules, module_name, sys.modules[__name__])
    monkeypatch.setattr(_spawn_permit_contender, '__module__', module_name)
    path = tmp_path / 'process-shared.sqlite3'
    repo = FencedTaskRepository(path)
    parent_lease = claim(repo, 'parent')
    ctx = multiprocessing.get_context('spawn')
    ready, results = ctx.Queue(), ctx.Queue()
    dispatch, release = ctx.Event(), ctx.Event()
    processes = [ctx.Process(target=_spawn_permit_contender,
                            args=(path, f'process-{i}', ready, dispatch, release, results))
                 for i in range(2)]
    try:
        for process in processes:
            process.start()
        assert {ready.get(timeout=20), ready.get(timeout=20)} == {'process-0', 'process-1'}
        dispatch.set()
        receipts = [results.get(timeout=20), results.get(timeout=20)]
        assert sum(bool(row['permit_id']) for row in receipts) == 1
        assert not acquire(repo, parent_lease, capacity=1)['permit_id']
        release.set()
        for process in processes:
            process.join(timeout=20)
            assert process.exitcode == 0
        receipt = acquire(repo, parent_lease, capacity=1)
        assert receipt['permit_id']
        repo.release_inference_permit(receipt['permit_id'])
    finally:
        dispatch.set()
        release.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
            if process.pid is not None:
                process.join(timeout=5)
        ready.close()
        results.close()


def test_separate_repository_connections_share_capacity_and_isolate_domains(tmp_path):
    path = tmp_path / 'tasks.sqlite3'
    repo = FencedTaskRepository(path)
    leases = [claim(repo, f't{i}') for i in range(5)]
    with ThreadPoolExecutor(max_workers=5) as pool:
        permits = list(pool.map(lambda lease: acquire(FencedTaskRepository(path), lease), leases))
    owned = [p for p in permits if p['permit_id']]
    assert len(owned) == 2
    assert acquire(repo, leases[4], domain='unrelated-account')['permit_id']
    repo.release_inference_permit(owned[0]['permit_id'])
    assert acquire(repo, leases[4])['permit_id']


def test_cancel_and_generation_fence_block_dispatch_but_do_not_free_live_calls(tmp_path):
    repo = FencedTaskRepository(tmp_path / 'tasks.sqlite3')
    old, other = claim(repo, 'old'), claim(repo, 'other')
    permit = acquire(repo, old, capacity=1)
    repo.request_cancel(old.task.task_id)
    with pytest.raises(PermissionError):
        acquire(repo, old)
    assert not acquire(repo, other)['permit_id']
    with pytest.raises(PermissionError):
        acquire(repo, replace(other, lease_token='stale'))
    repo.release_inference_permit(permit['permit_id'])
    assert acquire(repo, other)['permit_id']


def test_shared_cooldown_rate_spacing_and_conservative_mixed_capacity(tmp_path):
    repo = FencedTaskRepository(tmp_path / 'tasks.sqlite3')
    a, b = claim(repo, 'a'), claim(repo, 'b')
    one = acquire(repo, a, capacity=1)
    assert not acquire(repo, b, capacity=2)['permit_id']
    repo.release_inference_permit(one['permit_id'])
    repo.defer_inference_domain('same-account', 2, failure=True)
    denied = acquire(repo, b)
    assert not denied['permit_id'] and denied['retry_after_seconds'] > 1
    # Independent quota domains do not inherit another account's cooldown.
    assert acquire(repo, b, domain='another-model')['permit_id']
    result = repo.acquire_inference_permit(
        task_id=a.task.task_id, lease_token=a.lease_token, execution_generation=a.task.attempt,
        domain='paced', capacity=2, hold_seconds=600, requests_per_minute=60)
    assert result['permit_id']
    result = repo.acquire_inference_permit(
        task_id=b.task.task_id, lease_token=b.lease_token, execution_generation=b.task.attempt,
        domain='paced', capacity=2, hold_seconds=600, requests_per_minute=60)
    assert not result['permit_id'] and 0 < result['retry_after_seconds'] <= 1


def test_orphan_permit_expires_by_request_budget_not_task_lease(tmp_path):
    repo = FencedTaskRepository(tmp_path / 'tasks.sqlite3')
    a, b = claim(repo, 'a'), claim(repo, 'b')
    permit = acquire(repo, a, capacity=1)
    with repo._connect() as db:
        db.execute('UPDATE inference_permits SET expires_at=? WHERE permit_id=?',
                   (time.time() - 1, permit['permit_id']))
    assert acquire(repo, b, capacity=1)['permit_id']


def test_shared_alias_scope_and_expired_fallback_cannot_split_capacity(tmp_path):
    repo = FencedTaskRepository(tmp_path / 'tasks.sqlite3')
    a, b, c = claim(repo, 'a'), claim(repo, 'b'), claim(repo, 'c')
    one = repo.acquire_inference_permit(
        task_id=a.task.task_id, lease_token=a.lease_token, execution_generation=a.task.attempt,
        domain='backend-a-account', shared_domain='vendor-account', capacity=1)
    # Same backend after capacity evidence expires still overlaps the base domain.
    assert not acquire(repo, b, domain='backend-a-account', capacity=2)['permit_id']
    # A configured alias shares the additional quota scope atomically.
    other = repo.acquire_inference_permit(
        task_id=c.task.task_id, lease_token=c.lease_token, execution_generation=c.task.attempt,
        domain='backend-alias-account', shared_domain='vendor-account', capacity=2)
    assert not other['permit_id']
    repo.release_inference_permit(one['permit_id'])
    assert acquire(repo, b, domain='backend-a-account')['permit_id']


def test_unconfigured_task_cannot_clear_another_tasks_known_account_rate(tmp_path):
    repo = FencedTaskRepository(tmp_path / 'tasks.sqlite3')
    a, b = claim(repo, 'a'), claim(repo, 'b')
    first = repo.acquire_inference_permit(
        task_id=a.task.task_id, lease_token=a.lease_token, execution_generation=a.task.attempt,
        domain='account', capacity=2, requests_per_minute=60)
    repo.release_inference_permit(first['permit_id'])
    with repo._connect() as db:
        db.execute("UPDATE inference_domain_state SET next_start=0 WHERE domain='account'")
    assert acquire(repo, b, domain='account')['permit_id']
    with repo._connect() as db:
        row = db.execute("SELECT next_start,rate_interval FROM inference_domain_state WHERE domain='account'").fetchone()
        assert row['rate_interval'] == 1 and row['next_start'] > time.time() + .5
