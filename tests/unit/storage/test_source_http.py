import asyncio
from types import SimpleNamespace

import pytest
from filelock import FileLock, Timeout
from platform_core.storage.http import StoredSourceFileResponse


def test_source_lease_is_held_through_http_delivery_and_released(tmp_path):
    path = tmp_path / 'original.png'
    path.write_bytes(b'original bytes')
    lock_path = str(path) + '.lease'
    manager = SimpleNamespace(source_byte_lease=lambda material, timeout: FileLock(lock_path, timeout=timeout, thread_local=False))
    response = StoredSourceFileResponse(path, manager=manager, material={'id':'i'})
    body = []
    async def send(message):
        with pytest.raises(Timeout):
            with FileLock(lock_path, timeout=0):
                pass
        if message['type'] == 'http.response.body':
            body.append(message['body'])
    async def receive():
        return {'type':'http.disconnect'}
    asyncio.run(response({'type':'http','method':'GET','headers':[]}, receive, send))
    assert b''.join(body) == path.read_bytes()
    with FileLock(lock_path, timeout=0):
        pass
