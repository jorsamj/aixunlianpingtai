"""Durable external-source recovery. Source bytes and annotations are never deleted."""
from __future__ import annotations

import hashlib
import json
import time
from contextlib import closing
from pathlib import Path

from filelock import FileLock
from PIL import Image

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
from platform_core.task_runtime import TaskStatus

from .detection_import import DetectionDatasetScanner
from .errors import StorageError
from .import_candidates import RescanCandidateStore, _redact_error
from .import_tasks import (
    BATCH_SIZE, IMAGE_EXTENSIONS, MANIFEST_REF, StorageImportHandler,
    iter_provider_objects,
)
from .manager import StorageManager
from .yolo_import import YoloImportScanner

RESULT_REF = 'rescan/result.json'
FINAL_REF = 'rescan/final.json'
DEFAULT_POLICY = {
    'new': 'import',
    'missing': 'mark_unavailable',
    'changed': 'update',
    'annotation_changed': 'update',
    'annotation_removed': 'keep',
    'annotation_conflicts': 'keep',
}


def confirm_rescan(artifacts, task_id, policy, annotation_confirmation=None):
    allowed = {
        'new': {'import', 'ignore'},
        'missing': {'mark_unavailable', 'ignore'},
        'changed': {'update', 'ignore'},
        'annotation_changed': {'update', 'ignore'},
        'annotation_removed': {'clear', 'keep'},
        'annotation_conflicts': {'overwrite', 'keep'},
    }
    normalized = dict(DEFAULT_POLICY)
    normalized.update(dict(policy or {}))
    if set(normalized) != set(allowed) or any(
        normalized[key] not in values for key, values in allowed.items()
    ):
        raise ValueError('invalid rescan policy')
    store = RescanCandidateStore(artifacts.artifact_path(task_id, MANIFEST_REF))
    store.confirm_policy(normalized)
    if annotation_confirmation is not None:
        frozen = {
            'label_mapping': dict(annotation_confirmation.get('label_mapping') or {}),
            'create_labels': sorted(set(annotation_confirmation.get('create_labels') or [])),
            'accept_quality_report': bool(annotation_confirmation.get('accept_quality_report')),
        }
        previous = store.meta('annotation_confirmation')
        if previous is not None and previous != frozen:
            raise ValueError('annotation rescan confirmation is already frozen')
        store.set_meta('annotation_confirmation', frozen)
    # This is immutable durable intent; only TaskRepository's accepted CAS lets
    # the worker apply it. A crash between these steps is repaired by a retry.
    return normalized


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


def _classify_rescan_row(row, old):
    if row['status'] != 'IMPORTABLE':
        return 'INVALID' if old or row['status'] == 'INVALID' else 'SKIPPED'
    if old is None:
        return 'NEW'
    same_hash = str(row.get('content_sha256') or '') == str(old.get('content_sha256') or '')
    try:
        same_size = int(row.get('size_bytes') or 0) == int(old.get('size_bytes') or 0)
    except (TypeError, ValueError):
        same_size = False
    same_etag = str(row.get('etag') or '') == str(old.get('etag') or '')
    return 'UNCHANGED' if same_hash and same_size and same_etag else 'CHANGED'


def _annotation_delta_category(evidence, old_material, current_annotation):
    status = str(evidence.get('annotation_status') or 'unannotated')
    if status == 'invalid':
        return 'ANNOTATION_INVALID'
    previous = old_material.get('external_annotation') if isinstance(old_material, dict) else None
    if not isinstance(previous, dict) or (
        str(previous.get('source_format') or '') != str(evidence.get('source_format') or '')
    ):
        previous = None
    current_state = str(
        (current_annotation or {}).get('annotation_state')
        or (old_material or {}).get('annotation_state')
        or 'unannotated'
    )
    current_hash = str(
        (current_annotation or {}).get('content_digest')
        or (old_material or {}).get('annotation_hash')
        or ''
    )
    if status == 'unannotated':
        if previous and str(previous.get('annotation_status') or '') != 'unannotated':
            synced_hash = str(previous.get('synced_annotation_hash') or '')
            if current_state != 'unannotated' and (
                not synced_hash or (current_hash and current_hash != synced_hash)
            ):
                return 'ANNOTATION_CONFLICT'
            return 'ANNOTATION_REMOVED'
        return 'ANNOTATION_UNCHANGED'
    if previous is None:
        return (
            'ANNOTATION_CONFLICT'
            if current_state in {'annotated', 'confirmed_empty'}
            else 'ANNOTATION_NEW'
        )
    if str(previous.get('source_digest') or '') == str(evidence.get('source_digest') or ''):
        return 'ANNOTATION_UNCHANGED'
    synced_hash = str(previous.get('synced_annotation_hash') or '')
    if current_state in {'annotated', 'confirmed_empty'} and (
        not synced_hash or (current_hash and current_hash != synced_hash)
    ):
        return 'ANNOTATION_CONFLICT'
    return 'ANNOTATION_CHANGED'


def _build_annotation_deltas(store, project_path: Path, *, source_format: str):
    normalized = str(source_format or '').strip().lower()
    store.restart_annotation_deltas()
    if normalized not in {'yolo', 'coco'}:
        return store.annotation_summary()
    annotations = AnnotationRepository(project_path)
    page = []

    def flush():
        if not page:
            return
        keys = [row['object_key'] for row in page]
        baseline = store.baseline_for_keys(keys)
        evidence = store.annotation_source_evidence(keys, source_format=normalized)
        image_ids = [
            str(row.get('id') or '')
            for row in baseline.values()
            if str(row.get('id') or '')
        ]
        current = annotations.get_many(image_ids)
        deltas = []
        for candidate in page:
            key = candidate['object_key']
            old = baseline.get(key)
            source = evidence[key]
            current_annotation = current.get(str((old or {}).get('id') or ''))
            deltas.append({
                'object_key': key,
                'image_id': str((old or {}).get('id') or ''),
                'category': _annotation_delta_category(source, old, current_annotation),
                'source_evidence': source,
                'platform_annotation_hash': str(
                    (current_annotation or {}).get('content_digest')
                    or (old or {}).get('annotation_hash')
                    or ''
                ),
                'platform_annotation_state': str(
                    (current_annotation or {}).get('annotation_state')
                    or (old or {}).get('annotation_state')
                    or 'unannotated'
                ),
            })
        store.annotation_delta_batch(deltas)
        page.clear()

    for candidate in store.iter_status('IMPORTABLE', batch_size=BATCH_SIZE):
        page.append(candidate)
        if len(page) >= BATCH_SIZE:
            flush()
    flush()
    return store.annotation_summary()


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
        request = self._request(context)
        import_format = str(request.get('import_format') or 'images').strip().lower()
        if import_format not in {'images', 'yolo', 'coco'}:
            raise ValueError('storage_rescan supports images, YOLO or COCO in Phase 2B')
        scanner = None
        detection_scanner = None
        quality = None
        if not store.meta('scan_complete'):
            store.restart_inventory()
            if import_format == 'yolo':
                store.restart_annotation_review()
                scanner = YoloImportScanner(
                    provider,
                    store,
                    iter_provider_objects,
                    cancelled=context.cancel_requested,
                    progress=lambda key: context.check(f'YOLO：{key}'),
                )
                resolved = scanner.prepare(
                    'yolo',
                    prefix='',
                    recursive=True,
                    dataset_yaml=request.get('dataset_yaml') or None,
                )
                if resolved != 'yolo':
                    raise ValueError('YOLO dataset discovery failed')
                objects = (
                    item
                    for item in scanner.iter_inventory(dataset_only=False)
                    if Path(str(item.key)).suffix.lower() in IMAGE_EXTENSIONS
                )
            elif import_format == 'coco':
                store.restart_annotation_review()
                detection_scanner = DetectionDatasetScanner(
                    provider,
                    store,
                    iter_provider_objects,
                    lambda current, item, **_kwargs: self._inspect_verified(
                        context, current, source, item
                    ),
                    storage_source_id=source.id,
                    storage_type=source.type,
                    cancelled=context.cancel_requested,
                    progress=lambda key: context.check(f'COCO：{key}'),
                    deduplicate_images=False,
                )
                detected = detection_scanner.scan('coco', prefix='', recursive=True)
                detection_scanner.ensure_all_image_candidates()
                quality = detected.quality
                objects = store.iter_candidates(batch_size=BATCH_SIZE)
            else:
                objects = iter_provider_objects(provider, '', True)
            preinspected = import_format == 'coco'
            batch = []

            def flush():
                if not batch:
                    return
                context.check(force=True)
                existing = store.baseline_for_keys(row['object_key'] for row in batch)
                for row in batch:
                    old = existing.get(row['object_key'])
                    row['old_sha256'] = str((old or {}).get('content_sha256') or '')
                    row['category'] = _classify_rescan_row(row, old)
                store.object_batch(batch)
                store.upsert_many(row for row in batch if row['status'] == 'IMPORTABLE')
                context.save_checkpoint({'stage': 'SCANNING', **store.summary()})
                batch.clear()

            for item in objects:
                current_key = str(
                    item.get('object_key') if isinstance(item, dict) else item.key
                )
                context.check(current_key)
                batch.append(
                    dict(item)
                    if preinspected
                    else self._inspect_verified(context, provider, source, item)
                )
                if len(batch) >= BATCH_SIZE:
                    flush()
            flush()
            if scanner is not None:
                quality = scanner.scan_annotations()
            context.check(force=True)
            store.finish_inventory()
        elif import_format in {'yolo', 'coco'}:
            quality = store.quality_summary()
        annotation = _build_annotation_deltas(
            store,
            self.data_dir / 'projects' / context.task.project_id,
            source_format=import_format,
        )
        result = {
            'mode': 'storage_rescan',
            'storage_source_id': source.id,
            'stage': 'awaiting_confirmation',
            'default_policy': DEFAULT_POLICY,
            'import_format': import_format,
            **store.summary(),
        }
        if import_format in {'yolo', 'coco'}:
            result.update({
                **(
                    {'dataset_yaml': str(request.get('dataset_yaml') or '')}
                    if import_format == 'yolo'
                    else {}
                ),
                'quality': quality or store.quality_summary(),
                'external_classes': store.external_classes(),
                'annotation_counts': annotation['counts'],
                'annotation_examples': annotation['examples'],
                'annotation_applied': annotation['applied'],
            })
        context.artifacts.atomic_write_json(context.task.task_id, RESULT_REF, result)
        return TaskStatus.AWAITING_CONFIRMATION, RESULT_REF

    @staticmethod
    def _verify_remote_review_object(provider, row):
        """Revalidate Agent-reviewed object identity without re-reading its body."""
        metadata = provider.stat(row['object_key'])
        expected_size = int(row.get('size_bytes') or 0)
        actual_size = int(metadata.size_bytes or 0)
        expected_etag = str(row.get('etag') or '').strip().strip('"')
        actual_etag = str(metadata.etag or '').strip().strip('"')
        if actual_size != expected_size:
            raise ValueError('source size changed after Agent review; create a new rescan')
        if not expected_etag or not actual_etag or actual_etag != expected_etag:
            raise ValueError('source identity changed after Agent review; create a new rescan')
        expected_sha = str(row.get('content_sha256') or '').strip().lower()
        actual_sha = str(metadata.sha256 or '').strip().lower()
        if actual_sha and expected_sha and actual_sha != expected_sha:
            raise ValueError('source hash changed after Agent review; create a new rescan')
        return metadata

    def _apply_annotation_rescan(self, context, source, store, materials, policy, request):
        source_format = str(request.get('import_format') or 'images').strip().lower()
        if source_format not in {'yolo', 'coco'}:
            return store.annotation_summary()
        confirmation = store.meta('annotation_confirmation') or {}
        mapping = {
            str(key): str(value)
            for key, value in dict(confirmation.get('label_mapping') or {}).items()
        }
        project_path = self.data_dir / 'projects' / context.task.project_id
        annotations = AnnotationRepository(project_path)
        meta = json.loads((project_path / 'meta.json').read_text(encoding='utf-8'))
        labels = list(meta.get('labels') or [])
        label_meta = list(meta.get('label_meta') or [])
        label_ids = {
            str(code): index
            for index, code in enumerate(labels)
            if index >= len(label_meta)
            or str((label_meta[index] or {}).get('status') or 'active') == 'active'
        }
        categories = [
            'ANNOTATION_NEW', 'ANNOTATION_CHANGED', 'ANNOTATION_REMOVED',
            'ANNOTATION_UNCHANGED', 'ANNOTATION_CONFLICT', 'ANNOTATION_INVALID',
        ]
        while batch := store.pending_annotation_deltas(categories):
            by_ref = materials.get_by_storage_references(
                (source.id, row['object_key']) for row in batch
            )
            material_ids = [
                str(material.get('id') or '')
                for material in by_ref.values()
                if str(material.get('id') or '')
            ]
            current_annotations = annotations.get_many(material_ids)
            annotation_rows = []
            apply_evidence = {}
            patches = {}
            for row in batch:
                material = by_ref.get((source.id, row['object_key']))
                if material is None:
                    continue
                material_id = str(material['id'])
                category = row['category']
                evidence = dict(row.get('source_evidence') or {})
                current_annotation = current_annotations.get(material_id) or {}
                current_hash = str(
                    current_annotation.get('content_digest')
                    or material.get('annotation_hash')
                    or ''
                )
                current_state = str(
                    current_annotation.get('annotation_state')
                    or material.get('annotation_state')
                    or 'unannotated'
                )
                review_image_id = str(row.get('image_id') or '')

                # NEW images are indexed by the existing import pipeline before
                # annotation reconciliation. Their external detection annotation is therefore
                # already committed with the same frozen mapping; record source
                # provenance instead of treating annotation_changed as a second
                # independent write decision.
                if (
                    not review_image_id
                    and category == 'ANNOTATION_NEW'
                    and policy['new'] == 'import'
                ):
                    source_status = str(evidence.get('annotation_status') or 'unannotated')
                    expected_state = (
                        'annotated' if source_status == 'annotated'
                        else 'confirmed_empty' if source_status == 'confirmed_empty'
                        else 'unannotated'
                    )
                    if current_state != expected_state:
                        raise ValueError(
                            'new material annotation does not match the confirmed external review; '
                            'create a new rescan'
                        )
                    patches[material_id] = {
                        'external_annotation': {
                            'schema_version': 1,
                            'source_format': source_format,
                            'source_digest': str(evidence.get('source_digest') or ''),
                            'annotation_status': source_status,
                            'split': str(evidence.get('split') or ''),
                            'label_key': evidence.get('label_key'),
                            'dataset_key': evidence.get('dataset_key'),
                            'synced_annotation_hash': current_hash,
                            'task_id': context.task.task_id,
                        },
                        'external_annotation_needs_review': False,
                        'external_annotation_review_reason': '',
                        'imported_split': str(evidence.get('split') or ''),
                    }
                    continue

                should_write = (
                    category in {'ANNOTATION_NEW', 'ANNOTATION_CHANGED'}
                    and policy['annotation_changed'] == 'update'
                ) or (
                    category == 'ANNOTATION_CONFLICT'
                    and policy['annotation_conflicts'] == 'overwrite'
                ) or (
                    category == 'ANNOTATION_REMOVED'
                    and policy['annotation_removed'] == 'clear'
                )
                if should_write:
                    expected_hash = str(row.get('platform_annotation_hash') or '')
                    expected_state = str(row.get('platform_annotation_state') or 'unannotated')
                    if review_image_id and (
                        current_hash != expected_hash or current_state != expected_state
                    ):
                        raise ValueError(
                            'platform annotation changed after rescan review; create a new rescan'
                        )
                    status = str(evidence.get('annotation_status') or 'unannotated')
                    boxes = []
                    if status == 'annotated':
                        width, height = float(material['width']), float(material['height'])
                        for box in evidence.get('boxes') or []:
                            code = mapping.get(str(box['class_id']))
                            if code not in label_ids:
                                raise ValueError(
                                    'confirmed platform label is no longer active; resolve the label before retrying'
                                )
                            boxes.append({
                                'id': f"{material['id']}-{int(box['line_number'])}",
                                'label': code,
                                'class_id': label_ids[code],
                                'x1': max(0.0, (float(box['cx']) - float(box['w']) / 2) * width),
                                'y1': max(0.0, (float(box['cy']) - float(box['h']) / 2) * height),
                                'x2': min(width, (float(box['cx']) + float(box['w']) / 2) * width),
                                'y2': min(height, (float(box['cy']) + float(box['h']) / 2) * height),
                            })
                    state = (
                        'annotated' if boxes
                        else 'confirmed_empty' if status == 'confirmed_empty'
                        else 'unannotated'
                    )
                    annotation_rows.append({
                        'image_id': material['id'],
                        'boxes': boxes,
                        'annotation_state': state,
                    })
                    apply_evidence[material_id] = evidence
                elif category not in {'ANNOTATION_UNCHANGED'}:
                    reason = {
                        'ANNOTATION_REMOVED': 'EXTERNAL_ANNOTATION_REMOVED',
                        'ANNOTATION_CONFLICT': 'EXTERNAL_ANNOTATION_CONFLICT',
                        'ANNOTATION_INVALID': 'EXTERNAL_ANNOTATION_INVALID',
                    }.get(category, 'EXTERNAL_ANNOTATION_UPDATE_AVAILABLE')
                    patches[material_id] = {
                        'external_annotation_needs_review': True,
                        'external_annotation_review_reason': reason,
                    }
            persisted = annotations.upsert_many(
                annotation_rows,
                return_rows=True,
            ) if annotation_rows else []
            for saved in persisted:
                image_id = str(saved['image_id'])
                evidence = apply_evidence[image_id]
                patches[image_id] = {
                    **patches.get(image_id, {}),
                    'external_annotation': {
                        'schema_version': 1,
                        'source_format': source_format,
                        'source_digest': str(evidence.get('source_digest') or ''),
                        'annotation_status': str(evidence.get('annotation_status') or ''),
                        'split': str(evidence.get('split') or ''),
                        'label_key': evidence.get('label_key'),
                        'dataset_key': evidence.get('dataset_key'),
                        'synced_annotation_hash': str(saved.get('content_digest') or ''),
                        'task_id': context.task.task_id,
                    },
                    'external_annotation_needs_review': False,
                    'external_annotation_review_reason': '',
                    'imported_split': str(evidence.get('split') or ''),
                }
            if patches:
                materials.patch(patches)
            store.mark_annotation_applied(batch)
            context.check(force=True)
        return store.annotation_summary()

    def _apply_rescan(self, context, source, provider, store, materials, request):
        policy = store.meta('policy')
        if not policy:
            raise ValueError('rescan confirmation is missing')
        categories = ['UNCHANGED']
        if policy['missing'] == 'mark_unavailable':
            categories.append('MISSING')
        if policy['changed'] == 'update':
            categories.append('CHANGED')
        manager = StorageManager(data_dir=self.data_dir, project_id=context.task.project_id, materials=materials)
        remote_review = str(request.get('execution_mode') or 'local').strip().lower() == 'agent'
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
                    if remote_review:
                        metadata = self._verify_remote_review_object(provider, row)
                        row['size_bytes'] = int(metadata.size_bytes or 0)
                        row['etag'] = str(metadata.etag or '')
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
            for row in store.iter_category_candidates('NEW'):
                if row.get('indexed'):
                    continue
                context.check(row['object_key'])
                if remote_review:
                    self._verify_remote_review_object(provider, row)
                else:
                    fresh = self._inspect_verified(context, provider, source, provider.stat(row['object_key']))
                    if (
                        fresh['status'] != 'IMPORTABLE'
                        or fresh['content_sha256'] != row['content_sha256']
                        or int(fresh['size_bytes']) != int(row['size_bytes'])
                        or str(fresh.get('etag') or '') != str(row.get('etag') or '')
                    ):
                        raise ValueError('new source object changed after rescan; create a new rescan')
            annotation_confirmation = store.meta('annotation_confirmation') or {}
            details = {
                'label_mapping': dict(annotation_confirmation.get('label_mapping') or {}),
                'create_labels': list(annotation_confirmation.get('create_labels') or []),
                'accept_quality_report': bool(annotation_confirmation.get('accept_quality_report')),
            }
            selection = store.confirm(store.iter_category_keys('NEW'), details=details)
            context.artifacts.atomic_write_json(context.task.task_id, 'scan/confirmation.json', {
                **details,
                'accepted': True,
                'selected_count': selection.selected_count,
                'selection_digest': selection.digest,
                'confirmed_at': selection.confirmed_at,
            })
            status, _ = self._index_confirmed(context, self._request(context))
            if status not in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS}:
                return status, None
            while batch := store.pending_objects(['NEW']):
                context.check(force=True)
                store.mark_applied(batch)
        else:
            status = TaskStatus.SUCCEEDED
        annotation = self._apply_annotation_rescan(
            context, source, store, materials, policy, request,
        )
        summary = store.summary()
        if (
            summary['counts'].get('INVALID')
            or annotation['counts'].get('ANNOTATION_INVALID')
            or (
                annotation['counts'].get('ANNOTATION_CONFLICT')
                and policy['annotation_conflicts'] != 'overwrite'
            )
        ):
            status = TaskStatus.PARTIAL_SUCCESS
        context.artifacts.atomic_write_json(context.task.task_id, FINAL_REF, {
            'mode': 'storage_rescan',
            'stage': 'complete',
            'storage_source_id': source.id,
            'policy': policy,
            'new_indexing': store.indexing_counts(),
            'annotation_counts': annotation['counts'],
            'annotation_examples': annotation['examples'],
            'annotation_applied': annotation['applied'],
            **summary,
        })
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
                    return self._apply_rescan(checked, source, provider, store, materials, request)
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


def prepare_remote_rescan_review(
    *,
    data_dir: Path,
    artifacts,
    task_id: str,
    project_id: str,
    storage_source_id: str,
) -> dict:
    """Project a server-confirmed Agent review into the existing rescan owner."""
    manifest = artifacts.artifact_path(task_id, MANIFEST_REF)
    if not manifest.is_file():
        raise ValueError('remote rescan review manifest is missing')
    store = RescanCandidateStore(manifest)
    materials = MaterialRepository(Path(data_dir) / 'projects' / str(project_id))
    if not store.meta('baseline_complete'):
        materials.snapshot_storage_references(store.path, str(storage_source_id))
    store.restart_rescan_inventory()
    batch = []

    def flush():
        if not batch:
            return
        existing = store.baseline_for_keys(row['object_key'] for row in batch)
        classified = []
        for raw in batch:
            row = dict(raw)
            old = existing.get(row['object_key'])
            row['old_sha256'] = str((old or {}).get('content_sha256') or '')
            row['category'] = _classify_rescan_row(row, old)
            classified.append(row)
        store.object_batch(classified)
        batch.clear()

    for candidate in store.iter_candidates(batch_size=BATCH_SIZE):
        batch.append(candidate)
        if len(batch) >= BATCH_SIZE:
            flush()
    flush()
    store.finish_inventory()
    scan_result = artifacts.read_json(task_id, 'scan/result.json', default={})
    scan_result = scan_result if isinstance(scan_result, dict) else {}
    import_format = str(scan_result.get('import_format') or 'images').strip().lower()
    annotation = _build_annotation_deltas(
        store,
        Path(data_dir) / 'projects' / str(project_id),
        source_format=import_format,
    )
    store.set_meta('remote_review_ready', True)
    result = {
        'mode': 'storage_rescan',
        'execution_mode': 'agent',
        'storage_source_id': str(storage_source_id),
        'stage': 'awaiting_confirmation',
        'default_policy': DEFAULT_POLICY,
        'import_format': import_format,
        **store.summary(),
    }
    if import_format in {'yolo', 'coco'}:
        result.update({
            **(
                {'dataset_yaml': str(scan_result.get('dataset_yaml') or '')}
                if import_format == 'yolo'
                else {}
            ),
            'quality': scan_result.get('quality') or store.quality_summary(),
            'external_classes': list(scan_result.get('external_classes') or []),
            'annotation_counts': annotation['counts'],
            'annotation_examples': annotation['examples'],
            'annotation_applied': annotation['applied'],
        })
    artifacts.atomic_write_json(task_id, RESULT_REF, result)
    return result


def worker_registration(data_dir: Path):
    from platform_core.task_runtime import TaskKind
    return {'handlers': {TaskKind.MATERIAL_IMPORT: StorageRescanHandler(data_dir)},
            'capabilities': {'storage.import', 'storage.rescan'}}
