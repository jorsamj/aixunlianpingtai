import asyncio
from types import SimpleNamespace

import pytest
from filelock import FileLock, Timeout
from platform_core.storage.http import StoredSourceFileResponse
from starlette.requests import ClientDisconnect


def http_scope(spec_version='2.3'):
    return {'type':'http','asgi':{'version':'3.0','spec_version':spec_version},
            'http_version':'1.1','method':'GET','scheme':'http','path':'/original.png',
            'raw_path':b'/original.png','query_string':b'','headers':[],
            'server':('testserver',80),'client':('127.0.0.1',12345)}


def test_source_lease_is_held_through_http_delivery_and_released(tmp_path):
    path = tmp_path / 'original.png'
    path.write_bytes(b'original bytes')
    lock_path = str(path) + '.lease'
    manager = SimpleNamespace(source_byte_lease=lambda material, timeout: FileLock(lock_path, timeout=timeout, thread_local=False))
    response = StoredSourceFileResponse(path, manager=manager, material={'id':'i'})
    body = []
    messages = []
    finished = asyncio.Event()
    async def send(message):
        with pytest.raises(Timeout):
            with FileLock(lock_path, timeout=0):
                pass
        if message['type'] == 'http.response.body':
            body.append(message['body'])
            if not message.get('more_body',False):
                finished.set()
        messages.append(message)
    request_received = False
    async def receive():
        nonlocal request_received
        if not request_received:
            request_received = True
            return {'type':'http.request','body':b'','more_body':False}
        # A connected client remains present until the complete body is sent.
        await finished.wait()
        return {'type':'http.disconnect'}
    asyncio.run(response(http_scope(), receive, send))
    assert messages[0]['type'] == 'http.response.start'
    assert messages[0]['status'] == 200
    assert messages[-1]['type'] == 'http.response.body'
    assert not messages[-1].get('more_body',False)
    assert b''.join(body) == path.read_bytes()
    with FileLock(lock_path, timeout=0):
        pass


def test_source_lease_is_released_when_http_transport_disconnects_during_body(tmp_path):
    path = tmp_path / 'original.png'
    path.write_bytes(b'original bytes')
    lock_path = str(path) + '.lease'
    manager = SimpleNamespace(source_byte_lease=lambda material, timeout: FileLock(lock_path, timeout=timeout, thread_local=False))
    response = StoredSourceFileResponse(path, manager=manager, material={'id':'i'})
    sent = []
    async def send(message):
        with pytest.raises(Timeout):
            with FileLock(lock_path, timeout=0):
                pass
        sent.append(message['type'])
        if message['type'] == 'http.response.body':
            # ASGI 2.4 transports raise OSError when sending to a closed client.
            raise OSError('client connection closed during body delivery')
    async def receive():
        await asyncio.Event().wait()
    with pytest.raises((OSError, ClientDisconnect)):
        asyncio.run(response(http_scope('2.4'), receive, send))
    assert sent == ['http.response.start','http.response.body']
    with FileLock(lock_path, timeout=0):
        pass
