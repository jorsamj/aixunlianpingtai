"""Explicit bounded reconstruction from the original Task/Snapshot owner.

No task/material/GT rows are modified. Missing originals remain unknown; this
tool never certifies complete historical coverage or infers batches from status.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from filelock import FileLock

from .annotations import atomic_write_json
from .task_runtime.artifacts import ArtifactStore
from .training_material_usage import TrainingMaterialUsage


def _read_json(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def _owner_evidence(data_dir, project_id, row, artifacts):
    task_id = str(row['task_id'])
    ArtifactStore._validate_task_id(task_id)
    if row['project_id'] != project_id or row['kind'] != 'TRAINING':
        raise ValueError('usage maintenance Task scope mismatch')
    payload = artifacts.read_json(task_id, row['payload_ref'], default={})
    snapshot = artifacts.read_json(task_id, 'snapshot.json', default={})
    snapshot_id = str(snapshot.get('snapshot_id') or '')
    canonical = {key: value for key, value in snapshot.items() if key not in {'snapshot_id','created_at'}}
    digest = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    if not snapshot_id or digest != snapshot_id or str(payload.get('snapshot_id') or '') != snapshot_id:
        return None
    frozen = artifacts.read_json(task_id, payload.get('input_freeze_ref') or 'input-freeze.json', default={})
    sources = []
    if frozen:
        from .training_tasks import resolve_training_input_freeze
        from .training_splits import SplitMode, SplitRequest
        split = frozen.get('split') or {}
        request = SplitRequest(mode=SplitMode(split['mode']), train_image_ids=tuple(split['train_image_ids']),
            test_image_ids=tuple(split.get('test_image_ids') or []),
            validation_percent=split['validation_percent'], experiment_percent=split.get('experiment_percent'))
        sources, _schema, _manifest, replay = resolve_training_input_freeze(frozen, request,
            seed=int(split['seed']), supplement_candidate_set=payload.get('supplement_candidate_set'))
        if replay['snapshot_id'] != snapshot_id or payload.get('input_freeze_id') != frozen.get('input_freeze_id'):
            return None
    job_path = data_dir/'projects'/project_id/'jobs'/task_id/'job.json'
    job = _read_json(job_path)
    if (str(job.get('id') or job.get('task_id') or '') != task_id
        or str(job.get('snapshot_id') or '') != snapshot_id
        or (job.get('project_id') is not None and str(job['project_id']) != project_id)):
        job = {}
    return {'algorithm_id': str(payload.get('algorithm_asset_id') or payload.get('asset_algorithm_id') or ''),
        'snapshot': snapshot, 'source_images': sources, 'job': job, 'generation': 0}


def rebuild_owner_batch(data_dir, project_id, *, batch_size=100, apply=False):
    data_dir = Path(data_dir).resolve()
    ArtifactStore._validate_task_id(project_id)
    if not 1 <= int(batch_size) <= 500:
        raise ValueError('maintenance batch_size must be 1..500')
    database = data_dir/'task_runtime'/'tasks.sqlite3'
    artifacts_root = data_dir/'task_runtime'/'artifacts'
    if not database.is_file() or not artifacts_root.is_dir() or not (data_dir/'projects'/project_id/'meta.json').is_file():
        raise ValueError('maintenance requires the original project and Task database/artifact roots')
    cursor_path = data_dir/'task_runtime'/'maintenance'/f'training_usage_{project_id}.json'
    identity = {'database': str(database), 'device': database.stat().st_dev,
                'inode': database.stat().st_ino, 'project_id': project_id}
    # dry-run does not create a lock, cursor, DB table, or directory.
    if apply:
        cursor_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(cursor_path)+'.lock', timeout=10):
            return _batch(data_dir, identity, database, artifacts_root, cursor_path, int(batch_size), True)
    return _batch(data_dir, identity, database, artifacts_root, cursor_path, int(batch_size), False)


def _batch(data_dir, identity, database, artifacts_root, cursor_path, batch_size, apply):
    cursor = _read_json(cursor_path)
    if cursor and cursor.get('identity') != identity:
        raise ValueError('maintenance cursor database/project identity mismatch')
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        bound = cursor.get('bound')
        if bound is None:
            latest = db.execute("SELECT created_at,task_id FROM tasks WHERE project_id=? AND kind='TRAINING' ORDER BY created_at DESC,task_id DESC LIMIT 1", (identity['project_id'],)).fetchone()
            bound = list(latest) if latest else ['', '']
        after = cursor.get('after') or ['', '']
        rows = [dict(row) for row in db.execute("SELECT * FROM tasks WHERE project_id=? AND kind='TRAINING' AND (created_at,task_id)>(?,?) AND (created_at,task_id)<=(?,?) ORDER BY created_at,task_id LIMIT ?",
            (identity['project_id'], *after, *bound, batch_size))]
    artifacts = ArtifactStore(artifacts_root)
    index = TrainingMaterialUsage(database)
    unresolved = list(cursor.get('unresolved_task_ids') or [])
    eligible = []
    unknown_execution = []
    for row in rows:
        try:
            evidence = _owner_evidence(data_dir, identity['project_id'], row, artifacts)
        except (ValueError, KeyError, OSError, TypeError):
            evidence = None
        if evidence is None or not evidence['algorithm_id']:
            unresolved.append(row['task_id'])
        else:
            eligible.append(row['task_id'])
            if not evidence['job'].get('training_started') and not evidence['job'].get('usage_completed_epoch'):
                unknown_execution.append(row['task_id'])
            if apply:
                index.record_selected(identity['project_id'], evidence['algorithm_id'], row['task_id'],
                    evidence['snapshot'], source_images=evidence['source_images'])
                job = evidence['job']
                index.record_execution(row['task_id'], first_batch=job.get('training_started') is True,
                    completed_epoch=job.get('usage_completed_epoch') is True,
                    validation_observed=job.get('usage_validation_observed') is True)
        after = [row['created_at'], row['task_id']]
    result = {'identity': identity, 'bound': bound, 'after': after,
        'unresolved_task_ids': sorted(set(unresolved)), 'eligible_task_ids': eligible,
        'scanned': len(rows), 'complete_scan': after == bound, 'applied': apply,
        'unknown_execution_task_ids': unknown_execution,
        'coverage': 'unknown'}
    if apply:
        atomic_write_json(cursor_path, result)
    return result
