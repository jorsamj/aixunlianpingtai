from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO

from filelock import FileLock


DEFAULT_PART_SIZE = 8 * 1024 * 1024
MIN_PART_SIZE = 4 * 1024 * 1024
MAX_PART_SIZE = 32 * 1024 * 1024
DEFAULT_TTL_SECONDS = 24 * 60 * 60
MIN_TTL_SECONDS = 60 * 60
MAX_TTL_SECONDS = 7 * 24 * 60 * 60


def _safe_part_size(value: int | None) -> int:
    try:
        size = int(value or DEFAULT_PART_SIZE)
    except (TypeError, ValueError):
        size = DEFAULT_PART_SIZE
    return max(MIN_PART_SIZE, min(MAX_PART_SIZE, size))


def _safe_ttl_seconds(value: int | str | None) -> int:
    try:
        seconds = int(value or DEFAULT_TTL_SECONDS)
    except (TypeError, ValueError):
        seconds = DEFAULT_TTL_SECONDS
    return max(MIN_TTL_SECONDS, min(MAX_TTL_SECONDS, seconds))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or '').strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(timezone.utc)
    except ValueError:
        return None


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


class ZipMultipartRepository:
    """Durable application-level multipart store for browser ZIP uploads.

    Parts are persisted independently so a failed request retries only that part.
    Incomplete sessions have a bounded retention window so abandoned uploads do
    not consume project disk forever. Active writes/resumes extend the expiry.
    Completed uploads are not deleted by multipart GC; their parts are already
    removed immediately after assemble().
    """

    def __init__(self, project_root: str | Path, *, ttl_seconds: int | None = None):
        self.root = Path(project_root) / 'import_uploads'
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.root / '.multipart.lock'), timeout=30)
        configured_ttl = ttl_seconds if ttl_seconds is not None else os.environ.get('MC_ZIP_MULTIPART_TTL_SECONDS')
        self.ttl_seconds = _safe_ttl_seconds(configured_ttl)

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

    def _touch(self, meta: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        current = now or _utc_now()
        meta['updated_at'] = _iso(current)
        meta['expires_at'] = _iso(current + timedelta(seconds=self.ttl_seconds))
        meta['ttl_seconds'] = self.ttl_seconds
        return meta

    def _expired(self, meta: dict[str, Any], meta_path: Path, *, now: datetime | None = None) -> bool:
        if str(meta.get('status') or '') == 'completed':
            return False
        current = now or _utc_now()
        explicit = _parse_iso(meta.get('expires_at'))
        if explicit is not None:
            return explicit <= current
        base = _parse_iso(meta.get('updated_at')) or _parse_iso(meta.get('created_at'))
        if base is None:
            try:
                base = datetime.fromtimestamp(meta_path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                return True
        return base + timedelta(seconds=self.ttl_seconds) <= current

    def _remove_upload_dir(self, upload_dir: Path) -> int:
        released = 0
        if upload_dir.exists():
            for path in upload_dir.rglob('*'):
                if not path.is_file():
                    continue
                try:
                    released += path.stat().st_size
                except OSError:
                    pass
            shutil.rmtree(upload_dir, ignore_errors=True)
        return released

    def cleanup_expired(self, *, now: datetime | None = None) -> dict[str, int]:
        current = now or _utc_now()
        removed = 0
        released = 0
        with self.lock:
            for meta_path in list(self.root.glob('*/upload.json')):
                try:
                    meta = json.loads(meta_path.read_text(encoding='utf-8'))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(meta, dict) or not self._expired(meta, meta_path, now=current):
                    continue
                released += self._remove_upload_dir(meta_path.parent)
                removed += 1
        return {'removed_uploads': removed, 'released_bytes': released}

    def get(self, upload_id: str) -> dict[str, Any]:
        with self.lock:
            meta = self._read(upload_id)
            meta_path = self._meta_path(upload_id)
            if self._expired(meta, meta_path):
                self._remove_upload_dir(self._dir(upload_id))
                raise FileNotFoundError(upload_id)
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
        cleanup = self.cleanup_expired()
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
                        self._touch(existing)
                        _atomic_json(meta_path, existing)
                        return {**self._public(existing), 'cleanup': cleanup}
            upload_id = uuid.uuid4().hex[:16]
            now = _utc_now()
            meta = {
                'upload_id': upload_id,
                'dataset_id': str(dataset_id or 'default'),
                'file_name': str(file_name),
                'file_size': size,
                'part_size': part,
                'total_parts': int(math.ceil(size / part)),
                'fingerprint': fingerprint,
                'status': 'uploading',
                'created_at': _iso(now),
            }
            self._touch(meta, now=now)
            self._dir(upload_id).mkdir(parents=True, exist_ok=True)
            _atomic_json(self._meta_path(upload_id), meta)
            return {**self._public(meta), 'cleanup': cleanup}

    def write_part(self, upload_id: str, part_number: int, stream: BinaryIO) -> dict[str, Any]:
        # Different part numbers are independent and may be written in parallel.
        # A per-part lock protects duplicate retries without serialising the whole upload.
        with self.lock:
            meta = self._read(upload_id)
            if self._expired(meta, self._meta_path(upload_id)):
                self._remove_upload_dir(self._dir(upload_id))
                raise FileNotFoundError(upload_id)
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
        with self.lock:
            latest = self._read(upload_id)
            self._touch(latest)
            _atomic_json(self._meta_path(upload_id), latest)
            public = self._public(latest)
        return {**public, 'part_number': number, 'part_sha256': digest.hexdigest()}

    def assemble(self, upload_id: str, destination: str | Path) -> dict[str, Any]:
        with self.lock:
            meta = self._read(upload_id)
            if self._expired(meta, self._meta_path(upload_id)):
                self._remove_upload_dir(self._dir(upload_id))
                raise FileNotFoundError(upload_id)
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
            completed_at = _utc_now()
            meta['status'] = 'completed'
            meta['sha256'] = digest.hexdigest()
            meta['completed_at'] = _iso(completed_at)
            meta['updated_at'] = _iso(completed_at)
            meta['expires_at'] = None
            _atomic_json(self._meta_path(upload_id), meta)
            parts = self._dir(upload_id) / 'parts'
            if parts.exists():
                shutil.rmtree(parts, ignore_errors=True)
            return {**self._public(meta), 'assembled_bytes': written, 'sha256': digest.hexdigest()}
