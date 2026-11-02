"""Conversion views read last observations; only explicit actions run detectors.

Uses the existing ResourceCache. A per-resource lock coalesces synchronous
inspection requests, including concurrent forced refreshes of the same config.
No SDK import, network request, or persistence occurs in observe().
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import threading
import time

from .resource_cache import ResourceCache
from .performance_diagnostics import stage

# This is a review horizon for SDK capabilities, NOT a five-minute health TTL.
# Explicit configuration edits and changes to the configured local tools
# invalidate evidence immediately. Remote liveness is checked independently.
TTL_SECONDS = 7 * 24 * 3600
DETECTION_LEASE_SECONDS = 10 * 60
_entries = {}
_registry_lock = threading.Lock()
_OBSERVATIONS = {'status', 'targets', 'supported_chips', 'supported_precisions',
    'message', 'version', 'last_checked_at', 'remote_health', 'sophon_probe',
    'agent_nodes', 'detection', 'detection_error', 'error_code', 'api_key', 'has_api_key', 'api_key_masked',
    'detection_run', 'detection_config_key', 'detection_environment_fingerprint',
    'detection_timings_ms',
    'rknn_python', 'rknn_version', 'model_transform_path', 'model_deploy_path',
    'run_calibration_path', 'model_tool_path', 'npu_smi_path', 'cann_home',
    'device_info', 'detected_soc_versions', 'atlas_products', 'conversion_ready',
    'hardware_detected', 'trtexec_path', 'atc_path', 'paddle2onnx_path'}


def environment_fingerprint(resource):
    """Cheap configured-path identity; never executes an SDK or remote probe.

    Paths discovered *by* a detector are excluded: they aren't user config.
    A package changed in-place without touching these paths is covered by the
    periodic review, not falsely claimed to be detectable by a filesystem stat.
    """
    paths = {}
    if str(resource.get('mode') or 'local').lower() == 'local':
        for field in ('python_path', 'tool_root', 'env_script'):
            value = str(resource.get(field) or '').strip()
            if not value:
                continue
            try:
                info = Path(value).stat()
                paths[field] = (value, info.st_size, info.st_mtime_ns)
            except OSError:
                paths[field] = (value, None, None)
    return hashlib.sha256(json.dumps(paths, sort_keys=True).encode()).hexdigest()


def _age(timestamp):
    try:
        stamp = datetime.fromisoformat(str(timestamp or '').replace('Z', '+00:00'))
        stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
        return max(0., (datetime.now(timezone.utc)-stamp).total_seconds())
    except (ValueError, TypeError):
        return None


def detection_owner_alive(run):
    """Recover promptly after a local Web worker crash, including PID reuse."""
    if not run.get('owner_pid') or run.get('owner_host') != socket.gethostname():
        return True  # Cross-host records are bounded by the lease instead.
    try:
        import psutil
    except ImportError:
        return True
    try:
        process = psutil.Process(int(run['owner_pid']))
        return abs(process.create_time()-float(run['owner_started_at'])) < 1.0
    except (ValueError, TypeError, OSError, psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def configuration_identity(resource):
    config = {k:v for k,v in resource.items() if k not in _OBSERVATIONS}
    # A detector or another Web worker can persist newer observations without
    # changing resource configuration. Never let an older process-local TTL
    # snapshot override those durable facts (including a newly failed probe).
    config['_observed_status'] = str(resource.get('status') or '')
    config['_observed_at'] = str(resource.get('last_checked_at') or '')
    return hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()


def resource_configuration_key(resource):
    """Stable SDK configuration key, excluding volatile detector observations.

    Resources edited through the current API carry a config_revision. Legacy
    resources are still compared by their actual configuration fields.
    """
    # Current API writes a new config_revision for every real SDK/secret edit.
    # Normalize missing optional fields: filling their default '' on a later
    # metadata-only PUT must not invalidate a previously detected SDK.
    stable_fields = ('id', 'config_revision', 'kind', 'mode', 'base_url', 'secret_ref',
        'python_path', 'ultralytics_python', 'paddledet_dir', 'tool_root', 'env_script')
    config = {key:str(resource.get(key) or '') for key in stable_fields}
    if not resource.get('config_revision'):
        # Legacy hand-authored resources lack a revision: keep the actual
        # non-observation fields in the key until the first edited revision.
        config['legacy'] = {k:v for k,v in resource.items() if k not in _OBSERVATIONS
                            and k not in {'created_at','updated_at','name','remark'}}
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
    age = _age(checked)
    run = row.get('detection_run') or {}
    run_age = _age(run.get('started_at'))
    active = (run.get('state') == 'checking' and
              run.get('config_key') == resource_configuration_key(row) and
              run_age is not None and run_age < DETECTION_LEASE_SECONDS and
              detection_owner_alive(run))
    configuration_changed = bool(row.get('detection_config_key') and
        row['detection_config_key'] != resource_configuration_key(row))
    environment_changed = bool(row.get('detection_environment_fingerprint') and
        row['detection_environment_fingerprint'] != environment_fingerprint(row))
    state = ('checking' if checking.is_set() or active else
        'not_checked' if configuration_changed else
        'failed' if row.get('detection_error') else
        'expired' if environment_changed or (age is not None and age >= TTL_SECONDS) or run.get('state') == 'checking' else
        'not_checked' if age is None else
        'available' if row.get('status') == 'ready' else 'unavailable')
    reason = ('resource_configuration_changed' if configuration_changed else
              'local_environment_changed' if environment_changed else
              'interrupted_detection' if run.get('state') == 'checking' and not active else
              'review_due' if age is not None and age >= TTL_SECONDS else '')
    row['detection'] = {'state':state, 'checked_at':checked,
        'age_seconds':round(age, 3) if age is not None else None,
        'ttl_seconds':TTL_SECONDS, 'error':str(row.get('detection_error') or ''),
        'reason':reason, 'run_id':str(run.get('id') or '') if active else '',
        'started_at':str(run.get('started_at') or '') if active else ''}
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
            began = time.perf_counter()
            try:
                value = dict(detector(dict(resource)))
                value.pop('api_key', None)
                value['last_checked_at'] = datetime.now(timezone.utc).isoformat()
                value['detection_error'] = ''
                value['detection_config_key'] = resource_configuration_key(resource)
                value['detection_environment_fingerprint'] = environment_fingerprint(resource)
                metric = 'remote_http_ms' if resource.get('mode') == 'remote' else ('agent_registry_ms' if resource.get('mode') == 'agent' else 'sdk_probe_ms')
                value['detection_timings_ms'] = {metric: round((time.perf_counter()-began)*1000, 3)}
                return [value]
            except Exception as error:
                cache.replace([{**{k:v for k,v in resource.items() if k!='api_key'},
                    'status':'error','detection_error':str(error),
                    'last_checked_at':datetime.now(timezone.utc).isoformat(),
                    'detection_config_key':resource_configuration_key(resource),
                    'detection_environment_fingerprint':environment_fingerprint(resource),
                    'detection_timings_ms':{'failed_probe_ms':round((time.perf_counter()-began)*1000, 3)}}])
                raise
            finally:
                checking.clear()
        cache.get_or_refresh(load)
    return observe(resource)
