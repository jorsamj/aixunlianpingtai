"""Opt-in, bounded scalar timings for hot paths; never record input or SQL."""
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import hashlib
import logging
import os
import random
import re
import sqlite3
from time import perf_counter
from uuid import uuid4


_current = ContextVar('platform_performance_trace', default=None)
_logger = logging.getLogger('platform.performance')

_ENDPOINTS = (
    (re.compile(r'/api/v53/bootstrap/(?:snapshot|status)'), 'bootstrap'),
    (re.compile(r'/api/v12/projects/[^/]+/algorithms'), 'algorithm.list'),
    (re.compile(r'/api/training_options'), 'training.options'),
    (re.compile(r'/api/projects/[^/]+/jobs'), 'training.jobs'),
    (re.compile(r'/api/projects/[^/]+/jobs/[^/]+'), 'training.status'),
    (re.compile(r'/api/v62/projects/[^/]+/tasks/[^/]+'), 'training.durable_status'),
    (re.compile(r'/api/v62/projects/[^/]+/training-materials(?:/(?:page|role-page|bulk-selection|selection-summary|revision|compatibility|negative-preview))?'), 'training.materials'),
    (re.compile(r'/api/v61/projects/[^/]+/materials'), 'material.list'),
    (re.compile(r'/api/v61/projects/[^/]+/materials/status-counts'), 'material.status_counts'),
    (re.compile(r'/api/v61/projects/[^/]+/materials/[^/]+/content/thumbnail'), 'material.thumbnail'),
    (re.compile(r'/api/v42/projects/[^/]+/algorithms/[^/]+/versions/[^/]+/deployments'), 'conversion.history'),
    (re.compile(r'/api/v39/deploy/resources'), 'conversion.resources'),
    (re.compile(r'/api/v39/deploy/resources/[^/]+/detect'), 'conversion.resource_detect'),
    (re.compile(r'/api/v39/deploy/local/auto-detect'), 'conversion.local_detect'),
    (re.compile(r'/api/v39/deploy/catalog/chips/[^/]+/detect'), 'conversion.chip_detect'),
    (re.compile(r'/api/v41/deploy/plugins'), 'conversion.plugins'),
    (re.compile(r'/api/v19/projects/[^/]+/import/jobs(?:/[^/]+)?'), 'upload.jobs'),
    (re.compile(r'/api/v63/external-algorithm-platform/config'), 'external.config'),
    (re.compile(r'/api/v63/external-algorithm-platform/provider(?:/[^/]+)+'), 'external.provider'),
    (re.compile(r'/api/v63/external-algorithm-platform/(?:test|diagnostics)'), 'external.diagnostics'),
    (re.compile(r'/api/v63/external-algorithm-platform/(?:sync|sync-operation|sync-history)'), 'external.sync'),
    (re.compile(r'/api/v63/external-algorithm-platform/(?:training-preflight|readiness)'), 'external.readiness'),
    (re.compile(r'/api/v63/external-algorithm-platform/(?:cleanup-operations(?:/[^/]+){0,2})'), 'external.cleanup'),
    (re.compile(r'/api/v63/external-algorithm-platform/(?:interaction-logs(?:/[^/]+)?|cache)'), 'external.audit'),
)


def _endpoint(path):
    return next((name for pattern, name in _ENDPOINTS if pattern.fullmatch(path)), None)


def count(name, amount=1):
    trace=_current.get()
    if trace is not None: trace['counts'][name]+=amount


@contextmanager
def measure(name):
    """Wall time at the actual operation; inclusive spans must not be summed."""
    trace = _current.get()
    if trace is None:
        yield
        return
    trace['counts'][name+'.calls'] += 1
    began = perf_counter()
    try:
        yield
    finally:
        elapsed = (perf_counter()-began)*1000
        trace['stages_ms'][name] += elapsed
        aggregate = ('sql_cumulative_ms' if name.startswith('sql.') else
                     'external_http_ms' if name.startswith('external.http.') else
                     'file_read_ms' if name == 'file.read' else None)
        if aggregate:
            trace[aggregate] = (trace[aggregate] or 0.0) + elapsed


class _TimedCursor(sqlite3.Cursor):
    """Opt-in SQLite driver timing including row fetching (not SQL text)."""
    def execute(self, *args, **kwargs):
        with measure('sql.execute'):
            return super().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        with measure('sql.execute'):
            return super().executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        with measure('sql.execute'):
            return super().executescript(*args, **kwargs)

    def fetchone(self):
        with measure('sql.fetch'):
            return super().fetchone()

    def fetchmany(self, size=None):
        with measure('sql.fetch'):
            return super().fetchmany() if size is None else super().fetchmany(size)

    def fetchall(self):
        with measure('sql.fetch'):
            return super().fetchall()

    def __next__(self):
        # Iteration can produce tens of thousands of rows. Avoid a Python
        # contextmanager allocation per row in an opt-in performance probe.
        trace = _current.get()
        if trace is None:
            return super().__next__()
        began = perf_counter()
        try:
            return super().__next__()
        finally:
            elapsed = (perf_counter()-began)*1000
            trace['counts']['sql.fetch.calls'] += 1
            trace['stages_ms']['sql.fetch'] += elapsed
            trace['sql_cumulative_ms'] = (trace['sql_cumulative_ms'] or 0.0) + elapsed


class _TimedConnection(sqlite3.Connection):
    def cursor(self, factory=None):
        return super().cursor(factory=factory or _TimedCursor)

    def execute(self, *args, **kwargs):
        return self.cursor().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        return self.cursor().executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        return self.cursor().executescript(*args, **kwargs)

    def commit(self):
        with measure('sql.transaction'):
            return super().commit()

    def rollback(self):
        with measure('sql.transaction'):
            return super().rollback()


def connect_sqlite(*args, **kwargs):
    """Existing repository connections; default path is untouched."""
    if _current.get() is not None and 'factory' not in kwargs:
        kwargs['factory'] = _TimedConnection
    return sqlite3.connect(*args, **kwargs)


def stage(name):
    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            trace=_current.get()
            if trace is None: return function(*args, **kwargs)
            trace['counts'][name+'.calls']+=1
            began=perf_counter()
            try: return function(*args, **kwargs)
            finally: trace['stages_ms'][name]+=(perf_counter()-began)*1000
        return run
    return decorate


def observe_connection(database):
    trace=_current.get()
    if trace is not None:
        trace['counts']['repository_db_connections']+=1
        # SQLite expands parameters in this callback. Deliberately never store,
        # parse or log that argument. No process-global connect monkeypatch.
        database.set_trace_callback(lambda _statement: trace['counts'].update(['repository_sql_statements']))
    return database


class PerformanceDiagnosticsMiddleware:
    """Pure ASGI pass-through: no extra response/body buffering when disabled."""
    def __init__(self, app):
        self.app=app

    async def __call__(self, scope, receive, send):
        if scope['type']!='http' or os.environ.get('MC_PERFORMANCE_DIAGNOSTICS')!='1':
            return await self.app(scope,receive,send)
        endpoint=_endpoint(scope.get('path',''))
        if endpoint is None: return await self.app(scope,receive,send)
        # 48 thumbs on a page must not become 48 verbose log entries.
        if endpoint=='material.thumbnail' and random.randrange(32)!=0:
            return await self.app(scope,receive,send)
        _logger.setLevel(logging.INFO)
        if not _logger.hasHandlers(): _logger.addHandler(logging.StreamHandler())
        trace={'request_id':uuid4().hex,'endpoint':endpoint,'method':scope.get('method',''),
               'counts':Counter(),'stages_ms':Counter(), 'response_bytes':0,
               'sql_scope':'instrumented_repository_connections',
               'sqlite_lock_wait_ms':None, 'sql_cumulative_ms':None,
               'external_http_ms':None, 'file_read_ms':None, 'external_process_ms':None}
        for key, value in scope.get('headers',[]):
            if key.lower()==b'x-client-operation-id':
                candidate=value.decode('ascii','ignore')
                if re.fullmatch(r'[A-Za-z0-9_-]{8,64}',candidate):
                    # The header is client-controlled. Never log its raw value:
                    # a caller may accidentally supply a credential-like ID.
                    trace['client_operation_id_sha256']=hashlib.sha256(candidate.encode('ascii')).hexdigest()
                break
        token=_current.set(trace);began=perf_counter()
        async def observed_send(message):
            if message['type']=='http.response.start':
                trace['status_code']=message['status']
                trace['headers_ms']=round((perf_counter()-began)*1000,3)
                timing=', '.join(f'{name};dur={value:.3f}' for name,value in
                    [('total',trace['headers_ms']),*trace['stages_ms'].items()]).encode('ascii')
                headers=[(key,value) for key,value in message.get('headers',[]) if key.lower()!=b'x-request-id']
                for index,(key,value) in enumerate(headers):
                    if key.lower()==b'server-timing':
                        headers[index]=(key,value+b', '+timing)
                        break
                else: headers.append((b'server-timing',timing))
                headers.append((b'x-request-id',trace['request_id'].encode('ascii')))
                message={**message,'headers':headers}
            elif message['type']=='http.response.body':
                trace['response_bytes']+=len(message.get('body') or b'')
            await send(message)
        try:
            await self.app(scope,receive,observed_send)
        finally:
            trace['total_ms']=round((perf_counter()-began)*1000,3)
            trace['cache_hits']={name:max(0,trace['counts'][name+'_requests']-trace['counts'][name+'_build.calls'])
                for name in ('role_index','usage_pool') if name+'_requests' in trace['counts']}
            # Fixed metric names and scalars only, never exception/SQL/input text.
            import json
            try: _logger.info(json.dumps(trace,separators=(',',':')))
            finally: _current.reset(token)
