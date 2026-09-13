import gc
import sqlite3
import traceback
from pathlib import Path

import pytest

from platform_core import material_repository as material_repository_module
from platform_core import material_repository_batch as material_repository_batch_module
from platform_core.material_repository import MaterialRepository


class _TrackedConnection(sqlite3.Connection):
    pass


def _connection_is_closed(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute('SELECT 1')
    except sqlite3.ProgrammingError as error:
        return 'closed' in str(error).lower()
    return False


def _record(image_id: str) -> dict:
    return {
        'id': image_id,
        'filename': f'{image_id}.jpg',
        'object_key': f'uploads/{image_id}.jpg',
        'storage_source_id': 'default_local',
    }


def test_material_repository_sources_require_explicit_connection_owners():
    forbidden = 'with self._connect() as database:'
    for module in (material_repository_module, material_repository_batch_module):
        source = Path(module.__file__).read_text(encoding='utf-8')
        assert forbidden not in source, f'{Path(module.__file__).name} still relies on sqlite transaction context for close()'


def test_material_repository_explicitly_closes_connections_without_gc(tmp_path, monkeypatch):
    repository = MaterialRepository(tmp_path / 'project')
    real_connect = material_repository_module.sqlite3.connect
    opened = []

    def tracked_connect(*args, **kwargs):
        kwargs['factory'] = _TrackedConnection
        connection = real_connect(*args, **kwargs)
        connection._test_origin = ''.join(traceback.format_stack(limit=10))
        opened.append(connection)
        return connection

    monkeypatch.setattr(material_repository_module.sqlite3, 'connect', tracked_connect)

    repository.current_revision()
    repository.summary()
    repository.count_filtered({})
    repository.upsert(_record('image-1'))
    repository.upsert_many([_record('image-2')])
    repository.get('image-1')
    repository.patch({'image-1': {'processing_status': 'ready'}})
    repository.patch_many(['image-1'], {'processing_status': 'reviewed'})
    repository.add_labels_many(['image-1'], ['object'])
    repository.remove_labels_many(['image-1'], ['object'])
    repository.get_many(['image-1', 'image-2'])
    repository.read()
    repository.mutate(lambda rows: len(rows))
    repository.remove_many(['image-2'])
    repository.remove(['image-1'])

    assert opened, 'test must observe real MaterialRepository SQLite connections'
    leaked = [connection for connection in opened if not _connection_is_closed(connection)]
    leaked_origins = '\n--- leaked connection ---\n'.join(
        getattr(connection, '_test_origin', '<unknown>') for connection in leaked
    )
    assert leaked == [], (
        f'{len(leaked)} MaterialRepository SQLite connections were left open\n{leaked_origins}'
    )


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
