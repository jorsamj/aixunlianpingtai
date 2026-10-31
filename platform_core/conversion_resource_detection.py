"""Conversion views read last observations; only explicit actions run detectors.

Uses the existing ResourceCache. A per-resource lock coalesces synchronous
inspection requests, including concurrent forced refreshes of the same config.
No SDK import, network request, or persistence occurs in observe().
"""
from datetime import datetime, timezone
import hashlib
import json
import threading

from .resource_cache import ResourceCache
from .performance_diagnostics import stage

TTL_SECONDS = 300
_entries = {}
_registry_lock = threading.Lock()
_OBSERVATIONS = {'status', 'targets', 'supported_chips', 'supported_precisions',
    'message', 'version', 'last_checked_at', 'remote_health', 'sophon_probe',
    'agent_nodes', 'detection', 'detection_error', 'error_code', 'api_key', 'has_api_key', 'api_key_masked'}


def configuration_identity(resource):
    config = {k:v for k,v in resource.items() if k not in _OBSERVATIONS}
    # A detector or another Web worker can persist newer observations without
    # changing resource configuration. Never let an older process-local TTL
    # snapshot override those durable facts (including a newly failed probe).
    config['_observed_status'] = str(resource.get('status') or '')
    config['_observed_at'] = str(resource.get('last_checked_at') or '')
    return hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()


def _entry(resource):
    identity = configuration_identity(resource)
    key = str(resource.get('id') or identity)
    with _registry_lock:
        entry = _entries.get(key)
        if entry is None or entry[0] != identity:
            entry = (identity, ResourceCache(TTL_SECONDS), threading.Lock(), threading.Event())
            _entries[key] = entry
        return entry


def observe(resource):
    _, cache, _, checking = _entry(resource)
    snapshot = cache.snapshot()
    row = {**resource, **(snapshot['items'][0] if snapshot['items'] else {})}
    checked = str(row.get('last_checked_at') or '')
    try:
        stamp = datetime.fromisoformat(checked.replace('Z', '+00:00'))
        stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
        age = max(0., (datetime.now(timezone.utc)-stamp).total_seconds())
    except ValueError:
        age = None
    state = ('checking' if checking.is_set() else
        'not_checked' if age is None else 'expired' if age >= TTL_SECONDS else
        'available' if row.get('status') == 'ready' else
        'failed' if row.get('detection_error') else 'unavailable')
    row['detection'] = {'state':state, 'checked_at':checked,
        'age_seconds':round(age, 3) if age is not None else None,
        'ttl_seconds':TTL_SECONDS, 'error':str(row.get('detection_error') or '')}
    return row


@stage("conversion.resource_inspection")
def detect(resource, detector, *, force=False):
    _, cache, lock, checking = _entry(resource)
    previous = cache.snapshot()['updated_at']
    with lock:
        observation = observe(resource)
        if not force and not cache.snapshot()['items'] and observation['detection']['state'] in {'available','unavailable','failed'}:
            cache.replace([{k:v for k,v in resource.items() if k!='api_key'}])
        if not force and observe(resource)['detection']['state'] in {'not_checked','expired'}:
            cache.invalidate()
        # If another caller completed this same request while we waited, reuse it.
        if force and cache.snapshot()['updated_at'] == previous:
            cache.invalidate()
        @stage("conversion.detector_call")
        def load():
            checking.set()
            try:
                value = dict(detector(dict(resource)))
                value.pop('api_key', None)
                value['last_checked_at'] = datetime.now(timezone.utc).isoformat()
                return [value]
            except Exception as error:
                cache.replace([{**{k:v for k,v in resource.items() if k!='api_key'},
                    'status':'error','detection_error':str(error),
                    'last_checked_at':datetime.now(timezone.utc).isoformat()}])
                raise
            finally:
                checking.clear()
        cache.get_or_refresh(load)
    return observe(resource)
