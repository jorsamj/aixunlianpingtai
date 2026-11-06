"""Bounded inference calls; candidate/GT persistence belongs to the coordinator."""
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
