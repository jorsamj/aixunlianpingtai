import io
import zipfile
import pytest
import app as app_module
from fastapi import HTTPException
from platform_core.storage.zip_import import ServerZipImportError

@pytest.mark.parametrize('entrypoint', ['scan', 'extract'])
@pytest.mark.parametrize('limit', ['ratio', 'count'])
def test_active_entrypoints_enforce_configured_safety(tmp_path, monkeypatch, entrypoint, limit):
    archive = tmp_path / 'fixture.zip'
    if limit == 'count':
        monkeypatch.setenv('MC_ZIP_MAX_MEMBERS', '2')
        members = [('one.jpg', b'x'), ('two.jpg', b'y'), ('three.jpg', b'z')]
    else:
        monkeypatch.setenv('MC_ZIP_MAX_RATIO', '2')
        members = [('one.jpg', b'A' * 65536)]
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
        for name, payload in members:
            output.writestr(name, payload)
    with pytest.raises((HTTPException, ServerZipImportError)):
        if entrypoint == 'scan':
            app_module.v19_scan_zip(archive)
        else:
            app_module._v18_safe_extract(archive, tmp_path / 'output')

def test_scan_preserves_original_stop_exception(tmp_path):
    archive = tmp_path / 'fixture.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('one.jpg', b'image')
    def stop(*args):
        raise app_module._V19ImportStopped('audit requested stop')
    with pytest.raises(app_module._V19ImportStopped):
        app_module.v19_scan_zip(archive, stop)

def test_real_v19_create_rejects_over_count_archive(monkeypatch, client):
    monkeypatch.setenv('MC_ZIP_MAX_MEMBERS', '2')
    project = client.post('/api/projects', json={'name': 'audit-zip560', 'labels': []})
    project.raise_for_status()
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as output:
        for index in range(3):
            output.writestr(str(index) + '.jpg', b'image')
    monkeypatch.setattr(zipfile.ZipFile, 'open', lambda *args, **kwargs: pytest.fail('preflight must precede any member read'))
    monkeypatch.setattr(app_module, 'write_annotation', lambda *args, **kwargs: pytest.fail('no formal GT writes'))
    response = client.post(f"/api/v19/projects/{project.json()['id']}/datasets/default/import/jobs", files={'file': ('fixture.zip', payload.getvalue(), 'application/zip')})
    assert response.status_code == 400, response.text[:200]


@pytest.mark.parametrize('failure', ['cancel', 'disk', 'crc', 'actual'])
def test_extract_failure_preserves_existing_target_and_cleans_owned_part(tmp_path, monkeypatch, failure):
    from types import SimpleNamespace
    archive = tmp_path / 'fixture.zip'
    data = b'A' * (2 * 1024 * 1024 + 7)
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as output:
        output.writestr('one.jpg', data)
    if failure == 'crc':
        payload = bytearray(archive.read_bytes())
        payload[30 + len('one.jpg')] ^= 1
        archive.write_bytes(payload)
    dest = tmp_path / 'output'
    dest.mkdir()
    original = b'existing destination must survive'
    (dest / 'one.jpg').write_bytes(original)
    checks = []
    monkeypatch.setenv('MC_ZIP_DISK_MARGIN_BYTES', '0')
    monkeypatch.setenv('MC_ZIP_DISK_MARGIN_RATIO', '0')
    def disk_usage(path):
        checks.append(path)
        return SimpleNamespace(free=0 if failure == 'disk' and len(checks) > 1 else 100 * 1024**2)
    monkeypatch.setattr(app_module.shutil, 'disk_usage', disk_usage)
    events = []
    def stop(done, total, message):
        events.append((done, total))
        if failure == 'cancel' and len(events) == 2:
            raise app_module._V19ImportStopped('stop within member')
    if failure == 'actual':
        def larger_stream(self, member, *args, **kwargs):
            return io.BytesIO(data + b'overflow')
        monkeypatch.setattr(zipfile.ZipFile, 'open', larger_stream)
    with pytest.raises((ServerZipImportError, app_module._V19ImportStopped, zipfile.BadZipFile)):
        app_module._v18_safe_extract(archive, dest, stop)
    assert (dest / 'one.jpg').read_bytes() == original
    assert sorted(p.name for p in dest.iterdir()) == ['one.jpg']
    if failure == 'cancel':
        assert events[0] == (0, 1), 'cancel must be checked before a whole member is published'

def test_scan_progress_is_bounded_across_multiple_member_passes(tmp_path, monkeypatch):
    from types import SimpleNamespace
    archive = tmp_path / 'many.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        for index in range(2000):
            output.writestr(f'images/{index}.jpg', b'x')
    from types import FunctionType
    clock = SimpleNamespace(**vars(app_module.time))
    clock.monotonic = lambda: 100.0
    scanner = FunctionType(app_module.v19_scan_zip.__code__,
        {**app_module.v19_scan_zip.__globals__, 'time': clock},
        argdefs=app_module.v19_scan_zip.__defaults__)
    events = []
    result = scanner(archive, lambda *event: events.append(event))
    assert result['image_count'] == 2000
    assert len([event for event in events if event[0] == 'SCAN']) <= 3
    assert len(events) <= 15

@pytest.mark.parametrize('name', ['annotations.json', 'one.xml', 'data.yaml', 'classes.txt', 'labels/one.txt'])
def test_scan_does_not_swallow_sidecar_safety_errors(tmp_path, monkeypatch, name):
    archive = tmp_path / 'sidecars.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('one.jpg', b'image')
        output.writestr(name, b'content')
    def unsafe_read(*args, **kwargs):
        raise ServerZipImportError('unsafe sidecar')
    monkeypatch.setattr(zipfile.ZipFile, 'read', unsafe_read)
    with pytest.raises(ServerZipImportError, match='unsafe sidecar'):
        app_module.v19_scan_zip(archive)

def test_selected_extract_disk_budget_includes_all_sidecars_not_skipped_images(tmp_path, monkeypatch):
    from types import SimpleNamespace
    archive = tmp_path / 'selected.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('keep.jpg', b'keep')
        output.writestr('skip.jpg', b'x' * 10000)
        output.writestr('labels/keep.txt', b'keep-label')
        output.writestr('labels/skip.txt', b'skip-label')
    monkeypatch.setenv('MC_ZIP_DISK_MARGIN_BYTES', '0')
    monkeypatch.setenv('MC_ZIP_DISK_MARGIN_RATIO', '0')
    monkeypatch.setattr(app_module.shutil, 'disk_usage', lambda path: SimpleNamespace(free=24))
    events = []
    dest = tmp_path / 'dest'
    app_module._v18_safe_extract(archive, dest, lambda *event: events.append(event), selected_image_paths=['keep.jpg'])
    assert (dest / 'keep.jpg').read_bytes() == b'keep'
    assert not (dest / 'skip.jpg').exists()
    assert (dest / 'labels/keep.txt').read_bytes() == b'keep-label'
    assert (dest / 'labels/skip.txt').read_bytes() == b'skip-label'
    assert events[-1][:2] == (3, 3)


@pytest.mark.parametrize('image_path', ['./images/one.jpg', 'images//one.jpg'])
def test_selected_paths_use_the_same_normalization_as_archive_plan(tmp_path, image_path):
    archive = tmp_path / 'aliases.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr(image_path, b'keep')
        output.writestr('images/other.jpg', b'skip')
        output.writestr('./labels//one.txt', b'0 0.5 0.5 1 1')
        output.writestr('data.yaml', b'names: [external]')
    scan = app_module.v19_scan_zip(archive)
    selected = next(row['path'] for row in scan['images'] if row['name'] == 'one.jpg')
    assert scan['external_classes'][0]['name'] == 'external'
    dest = tmp_path / 'dest'
    app_module._v18_safe_extract(archive, dest, selected_image_paths=[selected])
    assert (dest / 'images/one.jpg').read_bytes() == b'keep'
    assert not (dest / 'images/other.jpg').exists()
    assert (dest / 'labels/one.txt').read_bytes() == b'0 0.5 0.5 1 1'
