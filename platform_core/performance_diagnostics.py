"""Opt-in, bounded scalar timings for hot paths; never record input or SQL."""
from collections import Counter
from contextvars import ContextVar
from functools import wraps
import logging
import os
import random
import re
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
    (re.compile(r'/api/v62/projects/[^/]+/training-materials(?:/(?:page|role-page|bulk-selection))?'), 'training.materials'),
    (re.compile(r'/api/v61/projects/[^/]+/materials'), 'material.list'),
    (re.compile(r'/api/v61/projects/[^/]+/materials/[^/]+/content/thumbnail'), 'material.thumbnail'),
    (re.compile(r'/api/v42/projects/[^/]+/algorithms/[^/]+/versions/[^/]+/deployments'), 'conversion.history'),
    (re.compile(r'/api/v39/deploy/resources'), 'conversion.resources'),
    (re.compile(r'/api/v39/deploy/resources/[^/]+/detect'), 'conversion.resource_detect'),
    (re.compile(r'/api/v39/deploy/local/auto-detect'), 'conversion.local_detect'),
    (re.compile(r'/api/v39/deploy/catalog/chips/[^/]+/detect'), 'conversion.chip_detect'),
    (re.compile(r'/api/v41/deploy/plugins'), 'conversion.plugins'),
    (re.compile(r'/api/v19/projects/[^/]+/import/jobs(?:/[^/]+)?'), 'upload.jobs'),
)


def _endpoint(path):
    return next((name for pattern, name in _ENDPOINTS if pattern.fullmatch(path)), None)


def count(name, amount=1):
    trace=_current.get()
    if trace is not None: trace['counts'][name]+=amount


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
               'sql_scope':'instrumented_repository_connections','sqlite_lock_wait_ms':None,
               'sql_cumulative_ms':None, 'external_process_ms':None}
        for key, value in scope.get('headers',[]):
            if key.lower()==b'x-client-operation-id':
                candidate=value.decode('ascii','ignore')
                if re.fullmatch(r'[A-Za-z0-9_-]{8,64}',candidate):
                    trace['client_operation_id']=candidate
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
