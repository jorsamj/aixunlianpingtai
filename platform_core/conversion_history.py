"""Bounded read-only projection of the original per-job conversion records."""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from time import monotonic, perf_counter
import os


_ACTIVE = frozenset({'queued', 'pending', 'running', 'preparing', 'converting', 'recovering',
                     'submitted', 'waiting', 'waiting_resource', 'starting', 'uploading', 'downloading', 'validating', 'stopping'})


def _time(value):
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()
    except (TypeError, ValueError, OverflowError):
        raise ValueError('invalid conversion history date') from None


def _scope(job):
    trace = job.get('source_trace') or {}
    meta = job.get('source_meta') or {}
    algorithm = str(trace.get('algorithm_id') or meta.get('algorithm_id') or job.get('algorithm_id') or '')
    version = str(trace.get('version_id') or meta.get('version_id') or job.get('version_id') or '')
    legacy = str(job.get('source_id') or '').split('::')
    if len(legacy) == 3 and legacy[0] == 'version':
        algorithm = algorithm or legacy[1]
        version = version or legacy[2]
    return algorithm, version


def _default_csc(job):
    params = job.get('params') or {}
    return str(params.get('csc_preset') or params.get('csc_mode') or 'unknown')


class ConversionHistoryProjection:
    """Cache derived JSON only; job files and the supplied overlay remain owners.

    The jobs_dir must be the already-authorized project's deploy/jobs directory.
    Directory polling is amortized for <=1 second. ``force`` bypasses that TTL;
    unchanged file signatures still reuse their parsed JSON. All callbacks run
    under a short process-local lock, without writes or background threads.
    """
    def __init__(self, *, max_projects=16, refresh_seconds=1.0):
        self.max_projects = max(1, int(max_projects))
        self.refresh_seconds = min(1.0, max(0.0, float(refresh_seconds)))
        self._projects = OrderedDict()
        self._lock = RLock()

    def query(self, jobs_dir, *, read_json, overlay=None, algorithm_id='', version_id='',
              status='', target='', chip='', precision='', csc='', created_from='',
              created_to='', page=1, page_size=20, force=False, csc_value=None):
        if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError('conversion history page/page_size invalid')
        lower, upper = _time(created_from), _time(created_to)
        date_end = bool(upper is not None and len(str(created_to))==10)
        if date_end: upper += 86400
        if lower is not None and upper is not None and lower > upper:
            raise ValueError('conversion history date range reversed')
        started = perf_counter()
        stats = dict(json_reads=0, overlays=0, metadata_files=0, cache_hits=0)
        root = Path(jobs_dir).resolve()
        with self._lock:
            key = str(root)
            state = self._projects.pop(key, None) or dict(files={}, checked=None, scan_errors=[])
            self._projects[key] = state
            while len(self._projects) > self.max_projects:
                self._projects.popitem(last=False)
            now = monotonic()
            if force or state['checked'] is None or now - state['checked'] >= self.refresh_seconds:
                self._refresh(root, state, read_json, stats)
                state['checked'] = monotonic()
            else:
                stats['cache_hits'] = len(state['files'])
            diagnostics = list(state['scan_errors'])
            matches = []
            for name, record in state['files'].items():
                raw = record['job']
                if raw is None:
                    diagnostics.append({'file': name, 'error': record['error']})
                    continue
                job = dict(raw)
                source_algorithm, source_version = _scope(job)
                if algorithm_id and source_algorithm != str(algorithm_id):
                    continue
                if version_id and source_version != str(version_id):
                    continue
                if overlay is not None and str(job.get('status') or '').lower() in _ACTIVE:
                    try:
                        stats['overlays'] += 1
                        updated = overlay(deepcopy(job))
                        if not isinstance(updated, dict):
                            raise ValueError('overlay did not return an object')
                        job = dict(updated)
                    except Exception as error:
                        diagnostics.append({'file': name, 'error': 'overlay:' + type(error).__name__})
                        # A failed live read cannot substantiate a status filter.
                        if status:
                            continue
                params = job.get('params') or {}
                if status and str(job.get('status') or '').lower() != str(status).lower():
                    continue
                if target and str(job.get('target') or '') != str(target):
                    continue
                if chip and str(params.get('chip') or params.get('soc_version') or '').lower() != str(chip).lower():
                    continue
                if precision and str(params.get('precision') or '').lower() != str(precision).lower():
                    continue
                if csc and str((csc_value or _default_csc)(job)) != str(csc):
                    continue
                try:
                    created = _time(job.get('created_at'))
                except ValueError:
                    created = None
                if (lower is not None and (created is None or created < lower)) or (upper is not None and (created is None or (created >= upper if date_end else created > upper))):
                    continue
                matches.append((created if created is not None else float('-inf'), str(job.get('id') or name), job))
            matches.sort(key=lambda row: (row[0], row[1]), reverse=True)
            total = len(matches)
            items = [deepcopy(row[2]) for row in matches[(page-1)*page_size:page*page_size]]
            stats['elapsed_ms'] = round((perf_counter()-started)*1000, 3)
            return dict(items=items, total=total, page=page, page_size=page_size,
                        total_pages=max(1, (total+page_size-1)//page_size), complete=not diagnostics,
                        unreadable_count=sum(r['job'] is None for r in state['files'].values()),
                        diagnostics=diagnostics[:20], stats=stats)

    @staticmethod
    def _refresh(root, state, read_json, stats):
        files = {}
        scan_errors = []
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    # Do not follow directories outside the authorized job owner.
                    if not entry.is_dir(follow_symlinks=False) or entry.is_symlink():
                        continue
                    path = Path(entry.path) / 'job.json'
                    name = entry.name + '/job.json'
                    try:
                        info = path.stat(follow_symlinks=False)
                        if path.is_symlink():
                            raise ValueError('symlink job record')
                        signature = (info.st_mtime_ns, info.st_size, info.st_ctime_ns, info.st_ino)
                        stats['metadata_files'] += 1
                        old = state['files'].get(name)
                        if old and old['signature'] == signature and old['job'] is not None:
                            files[name] = old
                            stats['cache_hits'] += 1
                            continue
                        stats['json_reads'] += 1
                        # A sentinel distinguishes unreadable/malformed data from a
                        # legitimate empty dict when the original reader catches IO.
                        value = read_json(path, None)
                        if not isinstance(value, dict) or not value or not value.get('status'):
                            raise ValueError('unreadable or invalid job record')
                        projected=dict(value)
                        trace=projected.get('source_trace')
                        if isinstance(trace,dict):
                            # Version history never exposes frozen GT/snapshot bodies.
                            # Preserve immutable source identity without retaining bulk evidence.
                            projected['source_trace']={key:trace[key] for key in
                                ('source_id','sha256','algorithm_id','version_id','artifact_id') if key in trace}
                        files[name] = dict(signature=signature, job=projected, error='')
                    except FileNotFoundError:
                        # Incomplete directory creation is not an authoritative job.
                        continue
                    except Exception as error:
                        files[name] = dict(signature=None, job=None, error=type(error).__name__)
        except FileNotFoundError:
            pass
        except Exception as error:
            scan_errors.append({'file': str(root), 'error': type(error).__name__})
        state.update(files=files, scan_errors=scan_errors)
