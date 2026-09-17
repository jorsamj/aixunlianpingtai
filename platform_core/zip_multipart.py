from __future__ import annotations

import hashlib
import json
import math
import shutil
import uuid
from pathlib import Path
from typing import Any, BinaryIO

from filelock import FileLock


DEFAULT_PART_SIZE = 8 * 1024 * 1024
MIN_PART_SIZE = 4 * 1024 * 1024
MAX_PART_SIZE = 32 * 1024 * 1024


def _safe_part_size(value: int | None) -> int:
    try:
        size = int(value or DEFAULT_PART_SIZE)
    except (TypeError, ValueError):
        size = DEFAULT_PART_SIZE
    return max(MIN_PART_SIZE, min(MAX_PART_SIZE, size))


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


class ZipMultipartRepository:
    """Durable application-level multipart store for browser ZIP uploads.

    Parts are persisted independently so a failed request retries only that part.
    The caller owns the final ZIP import job lifecycle after assemble().
    """

    def __init__(self, project_root: str | Path):
        self.root = Path(project_root) / 'import_uploads'
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.root / '.multipart.lock'), timeout=30)

    def _dir(self, upload_id: str) -> Path:
        return self.root / str(upload_id)

    def _meta_path(self, upload_id: str) -> Path:
        return self._dir(upload_id) / 'upload.json'

    def _part_path(self, upload_id: str, part_number: int) -> Path:
        return self._dir(upload_id) / 'parts' / f'{int(part_number):06d}.part'

    def _read(self, upload_id: str) -> dict[str, Any]:
        path = self._meta_path(upload_id)
        if not path.is_file():
            raise FileNotFoundError(upload_id)
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError('invalid multipart metadata')
        return value

    def get(self, upload_id: str) -> dict[str, Any]:
        with self.lock:
            meta = self._read(upload_id)
            return self._public(meta)

    def _public(self, meta: dict[str, Any]) -> dict[str, Any]:
        upload_id = str(meta['upload_id'])
        completed: list[int] = []
        received = 0
        for index in range(int(meta['total_parts'])):
            path = self._part_path(upload_id, index)
            if path.is_file():
                completed.append(index)
                received += path.stat().st_size
        return {
            **meta,
            'completed_parts': completed,
            'received_bytes': received,
            'upload_progress': round(100.0 * received / max(1, int(meta['file_size'])), 2),
        }

    def create_or_resume(
        self,
        *,
        dataset_id: str,
        file_name: str,
        file_size: int,
        fingerprint: str = '',
        part_size: int | None = None,
    ) -> dict[str, Any]:
        size = int(file_size)
        if size <= 0:
            raise ValueError('ZIP file is empty')
        part = _safe_part_size(part_size)
        fingerprint = str(fingerprint or '').strip()
        with self.lock:
            if fingerprint:
                for meta_path in self.root.glob('*/upload.json'):
                    try:
                        existing = json.loads(meta_path.read_text(encoding='utf-8'))
                    except (OSError, json.JSONDecodeError):
                        continue
                    if (
                        isinstance(existing, dict)
                        and existing.get('status') != 'completed'
                        and str(existing.get('fingerprint') or '') == fingerprint
                        and str(existing.get('dataset_id') or '') == str(dataset_id)
                        and str(existing.get('file_name') or '') == str(file_name)
                        and int(existing.get('file_size') or 0) == size
                    ):
                        return self._public(existing)
            upload_id = uuid.uuid4().hex[:16]
            meta = {
                'upload_id': upload_id,
                'dataset_id': str(dataset_id or 'default'),
                'file_name': str(file_name),
                'file_size': size,
                'part_size': part,
                'total_parts': int(math.ceil(size / part)),
                'fingerprint': fingerprint,
                'status': 'uploading',
            }
            self._dir(upload_id).mkdir(parents=True, exist_ok=True)
            _atomic_json(self._meta_path(upload_id), meta)
            return self._public(meta)

    def write_part(self, upload_id: str, part_number: int, stream: BinaryIO) -> dict[str, Any]:
        # Different part numbers are independent and may be written in parallel.
        # A per-part lock protects duplicate retries without serialising the whole upload.
        meta = self._read(upload_id)
        if meta.get('status') == 'completed':
            return self._public(meta)
        total_parts = int(meta['total_parts'])
        number = int(part_number)
        if number < 0 or number >= total_parts:
            raise ValueError('multipart part number out of range')
        expected = int(meta['part_size'])
        if number == total_parts - 1:
            expected = int(meta['file_size']) - int(meta['part_size']) * (total_parts - 1)
        target = self._part_path(upload_id, number)
        target.parent.mkdir(parents=True, exist_ok=True)
        part_lock = FileLock(str(target) + '.lock', timeout=30)
        with part_lock:
            temporary = target.with_suffix('.tmp')
            written = 0
            digest = hashlib.sha256()
            with temporary.open('wb') as output:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
            if written != expected:
                temporary.unlink(missing_ok=True)
                raise ValueError(f'multipart part size mismatch: {written}/{expected}')
            temporary.replace(target)
        return {**self._public(meta), 'part_number': number, 'part_sha256': digest.hexdigest()}

    def assemble(self, upload_id: str, destination: str | Path) -> dict[str, Any]:
        with self.lock:
            meta = self._read(upload_id)
            public = self._public(meta)
            total_parts = int(meta['total_parts'])
            if len(public['completed_parts']) != total_parts:
                raise ValueError(f'multipart upload incomplete: {len(public["completed_parts"])}/{total_parts}')
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + '.assembling')
            digest = hashlib.sha256()
            written = 0
            with temporary.open('wb') as output:
                for index in range(total_parts):
                    part_path = self._part_path(upload_id, index)
                    with part_path.open('rb') as source:
                        while True:
                            chunk = source.read(8 * 1024 * 1024)
                            if not chunk:
                                break
                            output.write(chunk)
                            digest.update(chunk)
                            written += len(chunk)
            if written != int(meta['file_size']):
                temporary.unlink(missing_ok=True)
                raise ValueError(f'assembled ZIP size mismatch: {written}/{meta["file_size"]}')
            temporary.replace(destination)
            meta['status'] = 'completed'
            meta['sha256'] = digest.hexdigest()
            _atomic_json(self._meta_path(upload_id), meta)
            parts = self._dir(upload_id) / 'parts'
            if parts.exists():
                shutil.rmtree(parts, ignore_errors=True)
            return {**self._public(meta), 'assembled_bytes': written, 'sha256': digest.hexdigest()}
