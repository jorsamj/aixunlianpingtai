"""Bounded inference calls; candidate/GT persistence belongs to the coordinator."""
import hashlib
import threading
import time
import uuid

from .providers.base import ProviderRequestError
from .task_runtime.worker import ExecutionFencedError


def _pause(context, seconds, stop=None):
    until = time.monotonic() + max(0, seconds)
    while True:
        if context.cancel_requested() or (stop is not None and stop.is_set()):
            raise InterruptedError('AI annotation cancelled before dispatch')
        remaining = until - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(.1, remaining))


def call_with_policy(context, request, image, call, policy, *, stop=None):
    """Retry only explicit transient errors, on the SAME frozen provider.

    Rate waiting and backoff are cancellable. Network calls hold a durable
    capacity receipt, renewed independently until the call actually returns.
    No candidate write, checkpoint, model selection or GT operation occurs here.
    """
    repo = context.repository
    acquire = getattr(repo, 'acquire_inference_permit', None)
    domain = str(policy.get('domain') or '')
    domains = list(dict.fromkeys([domain, *([str(policy['shared_domain'])] if policy.get('shared_domain') else [])]))
    tracked = callable(acquire) and bool(domain)
    max_attempts = max(1, min(3, int(policy.get('max_attempts') or 1)))
    retry_budget = max(0, min(30, float(policy.get('total_retry_seconds') or 0)))
    started = time.monotonic()
    queued_seconds = 0.0
    platform_request_id = uuid.uuid4().hex
    last_error = None
    for attempt in range(1, max_attempts + 1):
        if context.cancel_requested():
            raise InterruptedError('AI annotation cancelled before dispatch')
        permit_id = None
        if tracked:
            while True:
                _pause(context, 0, stop)
                if attempt > 1 and time.monotonic() - started >= retry_budget:
                    raise last_error
                receipt = acquire(
                    task_id=context.task.task_id, lease_token=context.lease.lease_token,
                    execution_generation=context.task.attempt, domain=domain,
                    capacity=(1 if policy.get('evidence_expires_at') and time.time() >= float(policy['evidence_expires_at'])
                              else int(policy.get('concurrency') or 1)), hold_seconds=900,
                    requests_per_minute=policy.get('requests_per_minute') or 0,
                    shared_domain=policy.get('shared_domain'),
                    rate_valid_until=policy.get('evidence_expires_at'),
                )
                permit_id = receipt.get('permit_id')
                if permit_id:
                    break
                wait = min(1, max(.01, float(receipt.get('retry_after_seconds') or .1)))
                before = time.monotonic()
                if attempt > 1:
                    wait = min(wait, max(0, retry_budget - (time.monotonic() - started)))
                _pause(context, wait, stop)
                queued_seconds += time.monotonic() - before
        stop_renewal = threading.Event()
        renewal_error = []
        def renew():
            while not stop_renewal.wait(30):
                try:
                    repo.renew_inference_permit(permit_id, hold_seconds=900)
                except Exception as error:
                    # Fail closed for publication after unconfirmed reservation.
                    if not renewal_error:
                        renewal_error.append(error)
                    # Continue holding capacity for an actual in-flight call.
                    # Publication remains failed closed after the first loss.
        renewal = None
        if tracked:
            renewal = threading.Thread(target=renew, name='inference-capacity-lease', daemon=True)
            renewal.start()
        try:
            _pause(context, 0, stop)
            if attempt > 1 and time.monotonic() - started >= retry_budget:
                raise last_error
            result = call(request, image)
            if renewal_error:
                raise ExecutionFencedError('INFERENCE_CAPACITY_LEASE_LOST') from renewal_error[0]
            if tracked:
                for scope in domains:
                    repo.defer_inference_domain(scope, 0, failure=False)
            result = dict(result)
            diagnostics = dict(result.get('diagnostics') or {})
            diagnostics['execution'] = {
                'platform_request_id': platform_request_id, 'task_id': context.task.task_id,
                'image_id': str(image['id']), 'model_config_revision': request.get('model_config_revision', ''),
                'attempts': attempt, 'queue_ms': round(queued_seconds * 1000),
                'elapsed_ms': round((time.monotonic() - started) * 1000),
                'concurrency': int(policy.get('concurrency') or 1),
            }
            result['diagnostics'] = diagnostics
            return result
        except ProviderRequestError as error:
            if renewal_error:
                raise ExecutionFencedError('INFERENCE_CAPACITY_LEASE_LOST') from renewal_error[0]
            last_error = error
            error.diagnostics = {**dict(getattr(error, 'diagnostics', {}) or {}),
                **{key: getattr(error, key) for key in ('request_id', 'backend_instance_id', 'actual_model') if getattr(error, key, None)},
                'model_config_revision': request.get('model_config_revision', ''), 'execution': {
                'platform_request_id': platform_request_id, 'task_id': context.task.task_id,
                'image_id': str(image['id']), 'attempts': attempt,
                'queue_ms': round(queued_seconds * 1000),
                'elapsed_ms': round((time.monotonic() - started) * 1000),
            }}
            retryable = bool(getattr(error, 'retryable', False))
            delay = max(.25 * 2 ** (attempt - 1), float(getattr(error, 'retry_after_seconds', 0) or 0))
            if tracked and retryable:
                for scope in domains:
                    repo.defer_inference_domain(scope, delay, failure=True)
            if (not retryable or attempt >= max_attempts or (stop is not None and stop.is_set())
                    or time.monotonic() - started + delay >= retry_budget):
                raise
        finally:
            stop_renewal.set()
            if renewal:
                renewal.join(timeout=1)
            if permit_id:
                repo.release_inference_permit(permit_id)
        _pause(context, delay, stop)


def _box_iou(left, right):
    x1, y1 = max(left['x1'], right['x1']), max(left['y1'], right['y1'])
    x2, y2 = min(left['x2'], right['x2']), min(left['y2'], right['y2'])
    overlap = max(0, x2 - x1) * max(0, y2 - y1)
    if not overlap:
        return 0.0
    def area(box):
        return (box['x2'] - box['x1']) * (box['y2'] - box['y1'])
    return overlap / (area(left) + area(right) - overlap)


def call_annotation_with_policy(context, request, image, call, policy, *, stop=None):
    """Count every WeVisOne native HTTP call against the existing shared lease/RPM.

    Per-label results remain private until *all* labels succeed. CandidateStore
    receives exactly one image-level success/empty result or one failure.
    """
    config = request.get('_provider_config') or request.get('model_config_snapshot') or {}
    codes = list((request.get('label_ids') or {}).keys())
    if str(config.get('provider_adapter') or config.get('provider_type')) != 'wevisone_vl' or len(codes) < 2:
        return call_with_policy(context, request, image, call, policy, stop=stop)
    from .providers.wevisone_vision import effective_detection_config
    if effective_detection_config(config, codes)['request_mode'] != 'per_label':
        return call_with_policy(context, request, image, call, policy, stop=stop)

    # Both labels must inspect the exact same EXIF-corrected raster, even if
    # the underlying source path changes between the two native calls.
    from .annotation_task_service import annotate_one, prepare_annotation_image
    frozen_image = prepare_annotation_image(image['path']) if call is annotate_one else None
    group_trace_id = uuid.uuid4().hex
    results = []
    for code in codes:
        _pause(context, 0, stop)
        one = dict(request)
        one['labels'] = [code]
        one['label_ids'] = {code: request['label_ids'][code]}
        one['label_catalog'] = [row for row in request['label_catalog'] if row['code'] == code]
        one['label_aliases'] = {code: (request.get('label_aliases') or {}).get(code, [])}
        if frozen_image is not None:
            one['_wevisone_prepared_image'] = frozen_image
        try:
            result = call_with_policy(context, one, image, call, policy, stop=stop)
        except ProviderRequestError as error:
            diagnostics = dict(getattr(error, 'diagnostics', {}) or {})
            execution = dict(diagnostics.get('execution') or {})
            execution['subrequest_trace_id'] = execution.get('platform_request_id', '')
            execution['platform_request_id'] = group_trace_id
            diagnostics.update(execution=execution, failed_label=code,
                               completed_label_count=len(results), query_strategy='per_label')
            error.diagnostics = diagnostics
            raise
        results.append((code, result))

    boxes = [box for _, result in results for box in result.get('boxes', [])]
    for index, left in enumerate(boxes):
        for right in boxes[index + 1:]:
            if left.get('label') != right.get('label') and _box_iou(left, right) > 0.5:
                error = ProviderRequestError('WeVisOne 跨标签目标框显著重叠，无法安全判定类别', code='MODEL_LABEL_AMBIGUOUS')
                error.diagnostics = {
                    'query_strategy': 'per_label', 'label_match_status': 'cross_label_overlap',
                    'conflicting_labels': sorted({str(left['label']), str(right['label'])}),
                    'completed_label_count': len(results),
                    'execution': {'platform_request_id': group_trace_id},
                }
                raise error
    first = results[0][1]
    merged = dict(first)
    merged['boxes'] = boxes
    merged['latency_ms'] = sum(int(result.get('latency_ms') or 0) for _, result in results)
    merged['request_id'] = ''  # No single upstream request represents the whole image.
    merged['raw_response_hash'] = hashlib.sha256('|'.join(
        str(result.get('raw_response_hash') or '') for _, result in results
    ).encode()).hexdigest()
    diagnostics = dict(first.get('diagnostics') or {})
    execution = dict(diagnostics.get('execution') or {})
    execution['platform_request_id'] = group_trace_id
    execution['subrequest_count'] = len(results)
    execution['attempts'] = sum(int((result.get('diagnostics') or {}).get('execution', {}).get('attempts') or 1)
                                for _, result in results)
    execution['queue_ms'] = sum(int((result.get('diagnostics') or {}).get('execution', {}).get('queue_ms') or 0)
                                for _, result in results)
    execution['elapsed_ms'] = sum(int((result.get('diagnostics') or {}).get('execution', {}).get('elapsed_ms') or 0)
                                  for _, result in results)
    counts = [(result.get('diagnostics') or {}).get('counts') or {} for _, result in results]
    merged_counts = {key: sum(int(item.get(key) or 0) for item in counts)
                     for key in ('raw', 'invalid', 'threshold_filtered', 'nms_filtered')}
    merged_counts['final'] = len(boxes)
    diagnostics.update(execution=execution, query_strategy='per_label',
                       per_label_requests=[{'label': code, 'request_id': result.get('request_id') or '',
                                            'trace_id': (result.get('diagnostics') or {}).get('execution', {}).get('platform_request_id') or '',
                                            'box_count': len(result.get('boxes') or [])} for code, result in results],
                       final_boxes=[dict(box) for box in boxes[:100]],
                       converted_boxes=[box for _, result in results
                                        for box in (result.get('diagnostics') or {}).get('converted_boxes', [])][:100],
                       counts=merged_counts,
                       confidence_unavailable_count=sum(box.get('confidence') is None for box in boxes))
    merged['diagnostics'] = diagnostics
    return merged
