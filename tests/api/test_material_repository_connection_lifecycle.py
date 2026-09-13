import gc
import sqlite3

import pytest

from platform_core import material_repository as material_repository_module
from platform_core.material_repository import MaterialRepository


class _TrackedConnection(sqlite3.Connection):
    pass


def _connection_is_closed(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute('SELECT 1')
    except sqlite3.ProgrammingError as error:
        return 'closed' in str(error).lower()
    return False


def test_material_repository_explicitly_closes_connections_without_gc(tmp_path, monkeypatch):
    repository = MaterialRepository(tmp_path / 'project')
    real_connect = material_repository_module.sqlite3.connect
    opened = []

    def tracked_connect(*args, **kwargs):
        kwargs['factory'] = _TrackedConnection
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(material_repository_module.sqlite3, 'connect', tracked_connect)

    repository.current_revision()
    repository.summary()
    repository.count_filtered({})
    repository.upsert({
        'id': 'image-1',
        'filename': 'image-1.jpg',
        'object_key': 'uploads/image-1.jpg',
        'storage_source_id': 'default_local',
    })
    repository.get('image-1')
    repository.patch({'image-1': {'processing_status': 'ready'}})
    repository.get_many(['image-1'])
    repository.read()

    assert opened, 'test must observe real MaterialRepository SQLite connections'
    leaked = [connection for connection in opened if not _connection_is_closed(connection)]
    assert leaked == [], f'{len(leaked)} MaterialRepository SQLite connections were left open'


def test_material_repository_repeated_reads_do_not_depend_on_gc_for_fd_recovery(tmp_path):
    psutil = pytest.importorskip('psutil')
    process = psutil.Process()
    counter = getattr(process, 'num_fds', None) or getattr(process, 'num_handles', None)
    if counter is None:
        pytest.skip('platform does not expose a process FD/handle counter')

    repository = MaterialRepository(tmp_path / 'project')
    gc.collect()
    baseline = int(counter())
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(128):
            repository.current_revision()
        after = int(counter())
    finally:
        if was_enabled:
            gc.enable()
        gc.collect()

    assert after - baseline <= 4, f'FD/handle growth requires GC recovery: {baseline} -> {after}'
