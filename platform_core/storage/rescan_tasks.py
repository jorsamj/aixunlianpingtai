"""Durable external-source recovery. Source bytes and annotations are never deleted."""
from __future__ import annotations

import hashlib
import json
import time
from contextlib import closing
from pathlib import Path

from filelock import FileLock
from PIL import Image

from platform_core.material_repository import MaterialRepository
from platform_core.task_runtime import TaskStatus

from .errors import StorageError
from .import_candidates import RescanCandidateStore, _redact_error
from .import_tasks import (
    BATCH_SIZE, IMAGE_EXTENSIONS, MANIFEST_REF, StorageImportHandler,
    iter_provider_objects,
)
from .manager import StorageManager

RESULT_REF = 'rescan/result.json'
FINAL_REF = 'rescan/final.json'
DEFAULT_POLICY = {'new': 'import', 'missing': 'mark_unavailable', 'changed': 'update'}


def confirm_rescan(artifacts, task_id, policy):
    allowed = {'new': {'import', 'ignore'}, 'missing': {'mark_unavailable', 'ignore'},
               'changed': {'update', 'ignore'}}
    if set(policy) != set(allowed) or any(policy[k] not in values for k, values in allowed.items()):
        raise ValueError('invalid rescan policy')
    store = RescanCandidateStore(artifacts.artifact_path(task_id, MANIFEST_REF))
    store.confirm_policy(policy)
    # This is immutable durable intent; only TaskRepository's accepted CAS lets
    # the worker apply it. A crash between these steps is repaired by a retry.
    return policy


class RescanCancelled(Exception):
    pass


class _LeaseContext:
    def __init__(self, context):
        self.context, self.last = context, 0.0

    def __getattr__(self, name):
        return getattr(self.context, name)

    def check(self, current='', force=False):
        if force or time.monotonic() - self.last >= 5:
            current_task = self.repository.heartbeat(
                self.task.task_id, self.lease.lease_token,
                stage='indexing' if self.task.accepted else 'SCANNING', current_item=current)
            self.last = time.monotonic()
            if current_task.status is TaskStatus.CANCEL_REQUESTED:
                raise RescanCancelled()

    def cancel_requested(self):
        self.check(force=True)
        return False


def _missing(error):
    if isinstance(error, FileNotFoundError) or getattr(error, 'code', '') == 'STORAGE_OBJECT_NOT_FOUND':
        return True
    if error.__cause__ is not None and error.__cause__ is not error:
        return _missing(error.__cause__)
    response = getattr(error, 'response', {})
    return (getattr(error, 'status', None) == 404 or getattr(response, 'status_code', None) == 404 or
            (isinstance(response, dict) and str(response.get('Error', {}).get('Code', ''))
             in {'404', 'NoSuchKey', 'NotFound'}))


class StorageRescanHandler(StorageImportHandler):
    def _inspect_verified(self, context, provider, source, item):
        key = str(item.key)
        row = dict(object_key=key, filename=Path(key).name, storage_source_id=source.id,
                   storage_type=source.type, size_bytes=item.size_bytes, etag=item.etag or '',
                   content_sha256='', width=0, height=0, status='SKIPPED', error='')
        if Path(key).suffix.lower() not in IMAGE_EXTENSIONS:
            return row
        try:
            context.check(key)
            with closing(provider.open_reader(key)) as stream:
                with Image.open(stream) as image:
                    row['width'], row['height'] = image.size
                    image.verify()
            digest, size = hashlib.sha256(), 0
            with closing(provider.open_reader(key)) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    context.check(key)
                    digest.update(chunk)
                    size += len(chunk)
            if not size or size != int(item.size_bytes):
                raise ValueError('object changed while being read; run a new rescan')
            actual = digest.hexdigest()
            row.update(content_sha256=actual, size_bytes=size, status='IMPORTABLE')
        except (RescanCancelled, PermissionError):
            raise
        except Exception as error:
            row.update(status='INVALID', error=_redact_error(error))
        return row

    def _scan_rescan(self, context, source, provider, store, materials):
        if not store.meta('baseline_complete'):
            context.check(force=True)
            materials.snapshot_storage_references(store.path, source.id)
        if not store.meta('scan_complete'):
            store.restart_inventory()
            batch = []

            def flush():
                if not batch:
                    return
                context.check(force=True)
                existing = store.baseline_for_keys(row['object_key'] for row in batch)
                for row in batch:
                    old = existing.get(row['object_key'])
                    row['old_sha256'] = str((old or {}).get('content_sha256') or '')
                    if row['status'] != 'IMPORTABLE':
                        row['category'] = 'INVALID' if old or row['status'] == 'INVALID' else 'SKIPPED'
                    elif old is None:
                        row['category'] = 'NEW'
                    else:
                        row['category'] = ('UNCHANGED' if row['content_sha256'] == row['old_sha256'] else 'CHANGED')
                store.object_batch(batch)
                store.upsert_many(row for row in batch if row['category'] == 'NEW')
                context.save_checkpoint({'stage': 'SCANNING', **store.summary()})
                batch.clear()

            # Full-source scope prevents prefix/recursive ambiguity from marking
            # out-of-scope references missing. Restart only the interrupted listing.
            for item in iter_provider_objects(provider, '', True):
                context.check(str(item.key))
                batch.append(self._inspect_verified(context, provider, source, item))
                if len(batch) >= BATCH_SIZE:
                    flush()
            flush()
            context.check(force=True)
            store.finish_inventory()
        result = {'mode': 'storage_rescan', 'storage_source_id': source.id,
                  'stage': 'awaiting_confirmation', 'default_policy': DEFAULT_POLICY, **store.summary()}
        context.artifacts.atomic_write_json(context.task.task_id, RESULT_REF, result)
        return TaskStatus.AWAITING_CONFIRMATION, RESULT_REF

    def _apply_rescan(self, context, source, provider, store, materials):
        policy = store.meta('policy')
        if not policy:
            raise ValueError('rescan confirmation is missing')
        categories = ['UNCHANGED']
        if policy['missing'] == 'mark_unavailable':
            categories.append('MISSING')
        if policy['changed'] == 'update':
            categories.append('CHANGED')
        manager = StorageManager(data_dir=self.data_dir, project_id=context.task.project_id, materials=materials)
        while batch := store.pending_objects(categories):
            for row in batch:
                context.check(row['object_key'])
                if row['category'] == 'MISSING':
                    row['old_sha256'] = row.get('content_sha256', '')
                    try:
                        provider.stat(row['object_key'])
                    except Exception as error:
                        if not _missing(error):
                            raise
                    else:
                        raise ValueError('missing object has reappeared; create a new rescan')
                else:
                    fresh = self._inspect_verified(context, provider, source, provider.stat(row['object_key']))
                    if fresh['status'] != 'IMPORTABLE' or fresh['content_sha256'] != row['content_sha256']:
                        raise ValueError('source changed after rescan; create a new rescan')
                    for field in ('size_bytes', 'etag', 'width', 'height'):
                        row[field] = fresh[field]
                    if row['category'] == 'CHANGED':
                        # Purge the old hash entry before committing the new binding;
                        # retries repeat invalidation even if the metadata committed.
                        manager.invalidate_content_cache(row['old_sha256'], row.get('filename', row['object_key']))
            context.check(force=True)
            materials.reconcile_storage_batch(context.task.task_id, source.id, batch)
            store.mark_applied(batch)
            context.save_checkpoint({'stage': 'indexing', **store.summary()})
        if policy['new'] == 'import':
            # Revalidate newly discovered bytes before handing off to the existing
            # deduplicating, checkpointed material-import indexing pipeline.
            for row in store.iter_status('IMPORTABLE'):
                if row.get('indexed'):
                    continue
                context.check(row['object_key'])
                fresh = self._inspect_verified(context, provider, source, provider.stat(row['object_key']))
                if fresh['status'] != 'IMPORTABLE' or fresh['content_sha256'] != row['content_sha256']:
                    raise ValueError('new source object changed after rescan; create a new rescan')
            selection = store.confirm(row['object_key'] for row in store.iter_status('IMPORTABLE'))
            context.artifacts.atomic_write_json(context.task.task_id, 'scan/confirmation.json', {
                'accepted': True, 'selected_count': selection.selected_count,
                'selection_digest': selection.digest, 'confirmed_at': selection.confirmed_at})
            status, _ = self._index_confirmed(context, self._request(context))
            if status not in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS}:
                return status, None
            while batch := store.pending_objects(['NEW']):
                context.check(force=True)
                store.mark_applied(batch)
        else:
            status = TaskStatus.SUCCEEDED
        summary = store.summary()
        if summary['counts'].get('INVALID'):
            status = TaskStatus.PARTIAL_SUCCESS
        context.artifacts.atomic_write_json(context.task.task_id, FINAL_REF, {
            'mode': 'storage_rescan', 'stage': 'complete', 'storage_source_id': source.id,
            'policy': policy, 'new_indexing': store.indexing_counts(), **summary})
        return status, FINAL_REF

    def run(self, context):
        request = self._request(context)
        if request.get('mode') != 'storage_rescan':
            return super().run(context)
        manifest = context.artifacts.artifact_path(context.task.task_id, MANIFEST_REF)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        # Fence shared task artifacts against an old worker surviving lease expiry.
        with FileLock(str(manifest) + '.rescan.lock', timeout=30):
            checked = _LeaseContext(context)
            try:
                checked.check(force=True)
                source, provider = self._source_and_provider(checked, request)
                store = RescanCandidateStore(manifest)
                fingerprint = hashlib.sha256(json.dumps(
                    [source.id, source.type, source.config], sort_keys=True).encode()).hexdigest()
                previous = store.meta('source_fingerprint')
                if previous and previous != fingerprint:
                    raise ValueError('storage source configuration changed; create a new rescan')
                store.set_meta('source_fingerprint', fingerprint)
                materials = MaterialRepository(self.data_dir / 'projects' / context.task.project_id)
                if context.task.accepted is True:
                    return self._apply_rescan(checked, source, provider, store, materials)
                return self._scan_rescan(checked, source, provider, store, materials)
            except RescanCancelled:
                return TaskStatus.CANCELLED, None
            except (ValueError, StorageError) as error:
                checked.check(force=True)
                context.artifacts.atomic_write_json(context.task.task_id, FINAL_REF, {
                    'mode': 'storage_rescan', 'stage': 'failed',
                    'error': {'code': 'STORAGE_RESCAN_CONFLICT', 'message': _redact_error(error)},
                })
                return TaskStatus.FAILED, FINAL_REF

    def recover(self, context):
        if self._request(context).get('mode') == 'storage_rescan':
            return self.run(context)
        return super().recover(context)


def worker_registration(data_dir: Path):
    from platform_core.task_runtime import TaskKind
    return {'handlers': {TaskKind.MATERIAL_IMPORT: StorageRescanHandler(data_dir)},
            'capabilities': {'storage.import', 'storage.rescan'}}
