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
    assert repository.get(session['upload_id'])['status'] == 'completed'


def test_multipart_rejects_wrong_part_size(tmp_path: Path):
    repository = ZipMultipartRepository(tmp_path)
    session = repository.create_or_resume(
        dataset_id='default', file_name='dataset.zip', file_size=5 * 1024 * 1024,
        fingerprint='wrong-size', part_size=4 * 1024 * 1024,
    )
    with pytest.raises(ValueError, match='part size mismatch'):
        repository.write_part(session['upload_id'], 0, BytesIO(b'x' * 32))
