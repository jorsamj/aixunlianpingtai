"""Execution integration: real lease DB/candidate DB, isolated provider doubles."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from platform_core.annotation_candidates import CandidateStore
from platform_core.annotation_task_service import run_ai_annotation
from platform_core.task_runtime import ArtifactStore, FencedTaskRepository, TaskKind, TaskRecord, WorkerContext, TaskStatus
from platform_core.providers.base import ProviderRequestError
from platform_core.annotation_inference import call_annotation_with_policy


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


def _wevisone_request():
    return {'_provider_config': {'provider_adapter': 'wevisone_vl', 'model_name': 'wevisone-vl-2b',
            'wevisone_label_queries': {'person': 'A standing human', 'tangzhe': 'A lying human'}},
            'label_ids': {'person': 0, 'tangzhe': 1},
            'label_catalog': [{'code': 'person', 'class_id': 0}, {'code': 'tangzhe', 'class_id': 1}],
            'label_aliases': {'person': [], 'tangzhe': []}}


def test_per_label_detection_uses_one_existing_permit_per_http_request(tmp_path, monkeypatch):
    context, store = setup_context(tmp_path, monkeypatch, count=1)
    request, calls, acquired = _wevisone_request(), [], []
    original_acquire = context.repository.acquire_inference_permit
    def acquire(**kwargs):
        receipt = original_acquire(**kwargs)
        if receipt.get('permit_id'):
            acquired.append(kwargs['domain'])
        return receipt
    monkeypatch.setattr(context.repository, 'acquire_inference_permit', acquire)
    def infer(one, image):
        code = next(iter(one['label_ids']))
        assert [row['code'] for row in one['label_catalog']] == [code]
        calls.append(code)
        x1 = 10 if code == 'person' else 100
        return {'boxes': [{'label': code, 'x1': x1, 'y1': 10, 'x2': x1 + 30, 'y2': 60,
                           'confidence': None}], 'raw_response_hash': code,
                'diagnostics': {'wevisone': {'parser_source': 'structured_boxes'}}}
    result = call_annotation_with_policy(context, request, {'id': '0'}, infer,
                                         {'domain': 'test-account', 'concurrency': 2, 'requests_per_minute': 120})
    assert calls == ['person', 'tangzhe']
    assert acquired == ['test-account', 'test-account']
    assert [box['label'] for box in result['boxes']] == ['person', 'tangzhe']
    assert result['diagnostics']['execution']['subrequest_count'] == 2
    assert result['diagnostics']['query_strategy'] == 'per_label'
    assert not context.artifacts.artifact_path('task', 'candidates/manifest.json').is_file()


def test_per_label_partial_failure_does_not_publish_first_label(tmp_path, monkeypatch):
    context, store = setup_context(tmp_path, monkeypatch, count=1)
    seen = []
    def infer(one, image):
        code = next(iter(one['label_ids']))
        seen.append(code)
        if code == 'tangzhe':
            raise ProviderRequestError('invalid second result', code='MODEL_LABEL_NOT_ALLOWED')
        return {'boxes': [{'label': code, 'x1': 10, 'y1': 10, 'x2': 50, 'y2': 50}]}
    with pytest.raises(ProviderRequestError) as error:
        call_annotation_with_policy(context, _wevisone_request(), {'id': '0'}, infer,
                                    {'domain': 'test-account', 'concurrency': 1})
    assert seen == ['person', 'tangzhe']
    assert error.value.diagnostics['failed_label'] == 'tangzhe'
    assert error.value.diagnostics['completed_label_count'] == 1
    assert not context.artifacts.artifact_path('task', 'candidates/manifest.json').is_file()


def test_per_label_overlap_is_ambiguous_but_distinct_and_zero_boxes_are_safe(tmp_path, monkeypatch):
    context, store = setup_context(tmp_path, monkeypatch, count=1)
    def conflicting(one, image):
        return {'boxes': [{'label': next(iter(one['label_ids'])),
                           'x1': 12, 'y1': 24, 'x2': 50, 'y2': 80}]}
    result = call_annotation_with_policy(context, _wevisone_request(), {'id': '0'}, conflicting,
                                         {'domain': 'test-account', 'concurrency': 1})
    assert result['manual_review_required'] is True
    assert [box['label'] for box in result['boxes']] == ['person', 'tangzhe']
    assert result['review_conflicts'][0]['iou'] == 1.0
    assert result['diagnostics']['label_match_status'] == 'cross_label_overlap'
    assert result['diagnostics']['execution']['subrequest_count'] == 2
    assert len(result['diagnostics']['per_label_requests']) == 2
    assert not context.artifacts.artifact_path('task', 'candidates/manifest.json').is_file()
    result = call_annotation_with_policy(context, _wevisone_request(), {'id': '0'},
                                         lambda *_args: {'boxes': []},
                                         {'domain': 'test-account', 'concurrency': 1})
    assert result['boxes'] == [] and len(result['diagnostics']['per_label_requests']) == 2


def test_worker_persists_one_whole_image_only_and_preserves_prior_success(tmp_path, monkeypatch):
    context, store = setup_context(tmp_path, monkeypatch, count=2, concurrency=1)
    request = context.artifacts.read_json('task', 'request.json')
    request.update(_wevisone_request())
    request.pop('_provider_config')  # JSON freeze contains only the saved model snapshot.
    request['labels'] = ['person', 'tangzhe']
    request['model_config_snapshot'].update({
        'provider_adapter': 'wevisone_vl', 'model_name': 'wevisone-vl-2b',
        'wevisone_label_queries': {'person': 'A standing human', 'tangzhe': 'A lying human'},
    })
    context.artifacts.atomic_write_json('task', 'request.json', request)
    seen = []
    def annotate(one, image):
        code = next(iter(one['label_ids']))
        seen.append((image['id'], code))
        if image['id'] == '1' and code == 'tangzhe':
            raise ProviderRequestError('bad second query', code='MODEL_LABEL_NOT_ALLOWED')
        return {'boxes': [{'label': code, 'x1': 10 if code == 'person' else 100,
                           'y1': 20, 'x2': 40 if code == 'person' else 130,
                           'y2': 70, 'confidence': None}]}
    outcome = run_ai_annotation(context, annotate=annotate)
    assert outcome.status is TaskStatus.AWAITING_CONFIRMATION and outcome.generation_partial
    assert store.get('0')['status'] == 'success'
    assert [b['label'] for b in store.get('0')['boxes']] == ['person', 'tangzhe']
    assert store.get('1')['status'] == 'failed' and store.get('1')['boxes'] == []
    assert store.get('1')['error_code'] == 'MODEL_LABEL_NOT_ALLOWED'
    assert seen == [('0','person'), ('0','tangzhe'), ('1','person'), ('1','tangzhe')]
    assert store.statistics()['gt_committed'] == 0


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
    from types import SimpleNamespace
    from platform_core import annotation_inference

    # Keep setup speed and the real Worker/SQLite lease clock out of the test.
    # Only the inference evidence clock advances after BOTH first calls enter.
    expiry = time.time() + 3600
    clock = [expiry - 1]
    monkeypatch.setattr(annotation_inference, 'time', SimpleNamespace(
        time=lambda: clock[0], monotonic=time.monotonic, sleep=time.sleep))
    context, store = setup_context(tmp_path, monkeypatch, count=6, evidence_expires_at=expiry)
    lock = threading.Lock()
    barrier = threading.Barrier(2, action=lambda: clock.__setitem__(0, expiry + 1))
    active, initial_maximum, later_maximum = 0, 0, 0
    def annotate(_request, image):
        nonlocal active, initial_maximum, later_maximum
        initial = int(image['id']) < 2
        with lock:
            active += 1
            if initial:
                initial_maximum = max(initial_maximum, active)
            else:
                later_maximum = max(later_maximum, active)
        try:
            if initial:
                barrier.wait(timeout=10)
            return {'boxes': []}
        finally:
            with lock:
                active -= 1
    assert run_ai_annotation(context, annotate=annotate).status is TaskStatus.AWAITING_CONFIRMATION
    assert initial_maximum == 2
    assert later_maximum == 1
    assert store.statistics()['empty'] == 6
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
