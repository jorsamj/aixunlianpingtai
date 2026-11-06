"""Execution integration: real lease DB/candidate DB, isolated provider doubles."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from platform_core.annotation_candidates import CandidateStore
from platform_core.annotation_task_service import run_ai_annotation
from platform_core.task_runtime import ArtifactStore, FencedTaskRepository, TaskKind, TaskRecord, WorkerContext, TaskStatus
from platform_core.providers.base import ProviderRequestError


def setup_context(tmp_path, monkeypatch, concurrency=2, count=4, **policy_values):
    repo = FencedTaskRepository(tmp_path / 'tasks.sqlite3')
    artifacts = ArtifactStore(tmp_path / 'artifacts')
    ids = [str(i) for i in range(count)]
    artifacts.atomic_write_json('task', 'request.json', {
        'image_ids': ids, 'labels': ['fire'], 'model_config_snapshot': {
            'inference_execution_policy': {'version': 1, 'concurrency': concurrency,
                'domain': 'test-account', 'evidence_status': 'operator_attested',
                'max_attempts': 1, 'total_retry_seconds': 30, **policy_values}}})
    repo.create(TaskRecord.new('task', 'project', TaskKind.AI_ANNOTATION, 'request.json', 'vision:test'))
    lease = repo.claim_next('worker', [TaskKind.AI_ANNOTATION], [], lease_seconds=30)
    context = WorkerContext(lease.task, lease, repo, artifacts)
    monkeypatch.setattr('platform_core.annotation_task_service.load_task_images', lambda *_: [
        {'id': i, 'width': 1280, 'height': 960, 'source_content_sha256': 'a' * 64} for i in ids])
    return context, CandidateStore(artifacts, task_id='task')


def test_bounded_parallel_results_persist_out_of_order_and_success_is_not_repeated(tmp_path, monkeypatch):
    context, store = setup_context(tmp_path, monkeypatch)
    calls, running, maximum = [], 0, 0
    lock = threading.Lock()
    barrier = threading.Barrier(2)
    def annotate(request, image):
        nonlocal running, maximum
        with lock:
            running += 1
            maximum = max(maximum, running)
            calls.append(image['id'])
        if image['id'] in {'0', '1'}:
            barrier.wait(timeout=2)
        if image['id'] == '0':
            time.sleep(.1)
        with lock:
            running -= 1
        return {'boxes': []}
    assert run_ai_annotation(context, annotate=annotate).status is TaskStatus.AWAITING_CONFIRMATION
    assert maximum == 2
    assert store.statistics()['empty'] == 4
    assert store.statistics()['gt_committed'] == 0
    assert list(store.iter_items())[0]['image_id'] == '1'
    assert run_ai_annotation(context, annotate=annotate).status is TaskStatus.AWAITING_CONFIRMATION
    assert len(calls) == 4


def test_cancel_discards_late_results_and_keeps_permits_until_requests_return(tmp_path, monkeypatch):
    context, store = setup_context(tmp_path, monkeypatch, count=6)
    started = threading.Barrier(3)
    release = threading.Event()
    calls = []
    def annotate(_request, image):
        calls.append(image['id'])
        started.wait(timeout=3)
        release.wait(timeout=3)
        return {'boxes': [{'label': 'fire'}]}
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(run_ai_annotation, context, annotate=annotate)
        started.wait(timeout=3)
        context.repository.request_cancel('task')
        outcome = task.result(timeout=2)
        assert outcome.status is TaskStatus.CANCELLED
        with context.repository._connect() as db:
            assert db.execute('SELECT COUNT(*) FROM inference_permits').fetchone()[0] == 2
        release.set()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with context.repository._connect() as db:
            if db.execute('SELECT COUNT(*) FROM inference_permits').fetchone()[0] == 0:
                break
        time.sleep(.01)
    assert sorted(calls) == ['0', '1']
    assert store.statistics()['total'] == 0


def test_protocol_failure_stops_new_dispatch_and_transient_retry_is_bounded(tmp_path, monkeypatch):
    context, store = setup_context(tmp_path, monkeypatch, concurrency=1, count=5)
    calls = []
    def fatal(_request, image):
        calls.append(image['id'])
        raise ProviderRequestError('bad native query', code='MODEL_REQUEST_CONTRACT_INVALID', status_code=422)
    outcome = run_ai_annotation(context, annotate=fatal)
    assert calls == ['0'] and outcome.status is TaskStatus.BLOCKED_BY_ENVIRONMENT
    assert store.get('0')['http_status'] == 422


def test_transient_retry_keeps_model_and_persists_empty_as_success(tmp_path, monkeypatch):
    context, store = setup_context(tmp_path, monkeypatch, concurrency=1, count=1, max_attempts=2)
    calls = []
    def limited(request, image):
        calls.append(id(request))
        if len(calls) == 1:
            raise ProviderRequestError('temporary', code='MODEL_RATE_LIMITED', status_code=429,
                                       retryable=True, retry_after_seconds=.01)
        return {'boxes': []}
    assert run_ai_annotation(context, annotate=limited).status is TaskStatus.AWAITING_CONFIRMATION
    assert len(calls) == 2 and calls[0] == calls[1]
    assert store.get('0')['diagnostics']['execution']['attempts'] == 2


@pytest.mark.parametrize('error_code,status', [('MODEL_QUOTA_EXCEEDED',429), ('MODEL_AUTHENTICATION_FAILED',401), ('MODEL_PERMISSION_DENIED',403)])
def test_fatal_provider_errors_are_not_retried_or_switched(tmp_path, monkeypatch, error_code, status):
    context, store = setup_context(tmp_path, monkeypatch, concurrency=1, max_attempts=3)
    calls = []
    def fatal(request, image):
        calls.append(image['id'])
        raise ProviderRequestError('fatal', code=error_code, status_code=status, retryable=False)
    assert run_ai_annotation(context, annotate=fatal).status is TaskStatus.BLOCKED_BY_ENVIRONMENT
    assert calls == ['0']
    assert store.statistics()['gt_committed'] == 0


def test_evidence_expiring_during_task_downgrades_next_dispatch(tmp_path, monkeypatch):
    context, store = setup_context(tmp_path, monkeypatch, count=6, evidence_expires_at=time.time()+1)
    lock, barrier = threading.Lock(), threading.Barrier(2)
    active, later_maximum = 0, 0
    def annotate(_request, image):
        nonlocal active, later_maximum
        with lock:
            active += 1
            if int(image['id']) >= 2:
                later_maximum = max(later_maximum, active)
        if int(image['id']) < 2:
            barrier.wait(timeout=2)
            time.sleep(1.1)
        with lock:
            active -= 1
        return {'boxes': []}
    assert run_ai_annotation(context, annotate=annotate).status is TaskStatus.AWAITING_CONFIRMATION
    assert later_maximum == 1
    report = context.artifacts.read_json('task', 'generation.json')['execution']
    assert report['persisted_succeeded'] == report['persisted_empty'] == 6


def test_generation_fence_discards_both_late_results(tmp_path, monkeypatch):
    from platform_core.task_runtime import ExecutionFencedError
    context, store = setup_context(tmp_path, monkeypatch, count=3)
    started, release = threading.Barrier(3), threading.Event()
    def annotate(_request, image):
        started.wait(timeout=3)
        release.wait(timeout=3)
        return {'boxes': []}
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run_ai_annotation, context, annotate=annotate)
        started.wait(timeout=3)
        with context.repository._connect() as db:
            db.execute("UPDATE tasks SET attempt=attempt+1,lease_token='new-execution' WHERE task_id='task'")
        try:
            with pytest.raises(ExecutionFencedError):
                future.result(timeout=2)
            assert store.statistics()['total'] == 0
        finally:
            release.set()
