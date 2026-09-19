import json
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pytest

from platform_core.zip_multipart import ZipMultipartRepository


def test_multipart_parts_resume_and_assemble(tmp_path: Path):
    repository = ZipMultipartRepository(tmp_path)
    payload = b'a' * (4 * 1024 * 1024) + b'b' * 321
    session = repository.create_or_resume(
        dataset_id='default', file_name='dataset.zip', file_size=len(payload),
        fingerprint='dataset.zip:resume-test', part_size=4 * 1024 * 1024,
    )
    assert session['total_parts'] == 2
    assert session['created_at']
    assert session['updated_at']
    assert session['expires_at']
    repository.write_part(session['upload_id'], 0, BytesIO(payload[:4 * 1024 * 1024]))
    resumed = repository.create_or_resume(
        dataset_id='default', file_name='dataset.zip', file_size=len(payload),
        fingerprint='dataset.zip:resume-test', part_size=4 * 1024 * 1024,
    )
    assert resumed['upload_id'] == session['upload_id']
    assert resumed['completed_parts'] == [0]
    repository.write_part(session['upload_id'], 1, BytesIO(payload[4 * 1024 * 1024:]))
    target = tmp_path / 'assembled.zip'
    result = repository.assemble(session['upload_id'], target)
    assert result['assembled_bytes'] == len(payload)
    assert target.read_bytes() == payload
    completed = repository.get(session['upload_id'])
    assert completed['status'] == 'completed'
    assert completed['expires_at'] is None
    assert completed['completed_at']


def test_multipart_rejects_wrong_part_size(tmp_path: Path):
    repository = ZipMultipartRepository(tmp_path)
    session = repository.create_or_resume(
        dataset_id='default', file_name='dataset.zip', file_size=5 * 1024 * 1024,
        fingerprint='wrong-size', part_size=4 * 1024 * 1024,
    )
    with pytest.raises(ValueError, match='part size mismatch'):
        repository.write_part(session['upload_id'], 0, BytesIO(b'x' * 32))


def test_expired_incomplete_upload_is_removed_and_reports_released_bytes(tmp_path: Path):
    repository = ZipMultipartRepository(tmp_path)
    payload = b'x' * (4 * 1024 * 1024)
    session = repository.create_or_resume(
        dataset_id='default', file_name='abandoned.zip', file_size=len(payload),
        fingerprint='abandoned', part_size=4 * 1024 * 1024,
    )
    repository.write_part(session['upload_id'], 0, BytesIO(payload))

    meta_path = tmp_path / 'import_uploads' / session['upload_id'] / 'upload.json'
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    meta['expires_at'] = '2000-01-01T00:00:00Z'
    meta_path.write_text(json.dumps(meta), encoding='utf-8')

    result = repository.cleanup_expired()

    assert result['removed_uploads'] == 1
    assert result['released_bytes'] >= len(payload)
    assert not meta_path.parent.exists()
    with pytest.raises(FileNotFoundError):
        repository.get(session['upload_id'])


def test_completed_upload_is_never_removed_by_multipart_gc(tmp_path: Path):
    repository = ZipMultipartRepository(tmp_path)
    payload = b'y' * (4 * 1024 * 1024)
    session = repository.create_or_resume(
        dataset_id='default', file_name='done.zip', file_size=len(payload),
        fingerprint='done', part_size=4 * 1024 * 1024,
    )
    repository.write_part(session['upload_id'], 0, BytesIO(payload))
    repository.assemble(session['upload_id'], tmp_path / 'done.zip')

    meta_path = tmp_path / 'import_uploads' / session['upload_id'] / 'upload.json'
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    meta['expires_at'] = '2000-01-01T00:00:00Z'
    meta_path.write_text(json.dumps(meta), encoding='utf-8')

    result = repository.cleanup_expired()

    assert result == {'removed_uploads': 0, 'released_bytes': 0}
    assert repository.get(session['upload_id'])['status'] == 'completed'


def test_legacy_session_without_expiry_uses_metadata_mtime(tmp_path: Path):
    repository = ZipMultipartRepository(tmp_path)
    session = repository.create_or_resume(
        dataset_id='default', file_name='legacy.zip', file_size=4 * 1024 * 1024,
        fingerprint='legacy', part_size=4 * 1024 * 1024,
    )
    meta_path = tmp_path / 'import_uploads' / session['upload_id'] / 'upload.json'
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    for key in ('created_at', 'updated_at', 'expires_at'):
        meta.pop(key, None)
    meta_path.write_text(json.dumps(meta), encoding='utf-8')
    old = (datetime.now(timezone.utc) - timedelta(days=2)).timestamp()
    meta_path.touch()
    import os
    os.utime(meta_path, (old, old))

    result = repository.cleanup_expired()

    assert result['removed_uploads'] == 1
