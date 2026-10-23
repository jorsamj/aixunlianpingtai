"""Incremental read projection over the existing worker-owned job history.

No task state is persisted here. File signatures invalidate cached JSON; callers
overlay current durable task truth on every read. A restart rebuilds the cache.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Mapping


class TrainingHistoryProjection:
    def __init__(self):
        self._lock = threading.RLock()
        self._files = {}

    def read(self, jobs_dir: Path, loader):
        key = str(jobs_dir.resolve())
        with self._lock:
            previous = self._files.get(key, {})
            current = {}
            for child in jobs_dir.iterdir() if jobs_dir.exists() else ():
                if not child.is_dir():
                    continue
                path = child / 'job.json'
                try:
                    stat = path.stat()
                except FileNotFoundError:
                    continue
                signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
                old = previous.get(str(path))
                if old is not None and old[0] == signature:
                    value = old[1]
                else:
                    value = loader(path)
                if isinstance(value, dict) and value:
                    current[str(path)] = (signature, value)
            self._files[key] = current
            return [dict(value) for _signature, value in current.values()]


def successful_training_counts(rows, durable: Mapping | None = None):
    """Count distinct successful training identities, with verified evidence.

    Durable lifecycle wins over legacy labels. Pre-Durable success requires the
    historical artifact_verified contract. Unknown status/evidence fails closed.
    """
    durable = durable or {}
    canonical = {}
    for row in rows:
        identity = str(row.get('task_id') or row.get('id') or '').strip()
        if not identity:
            continue
        old = canonical.get(identity)
        if old is None or str(row.get('id') or '') == identity:
            canonical[identity] = row
    counts = {}
    for identity, row in canonical.items():
        task = durable.get(identity)
        kind = str((task or {}).get('kind') or row.get('task_kind') or row.get('kind') or 'TRAINING').upper()
        if kind != 'TRAINING' or row.get('never_started'):
            continue
        algorithm_id = str(row.get('asset_algorithm_id') or row.get('algorithm_asset_id') or '').strip()
        if not algorithm_id:
            continue
        if task is not None:
            success = str(task.get('status') or '').upper() in {'SUCCEEDED', 'PARTIAL_SUCCESS'} and bool(task.get('result_ref'))
        else:
            success = str(row.get('status') or '').upper() in {'DONE', 'FINISHED', 'COMPLETED', 'SUCCESS', 'SUCCEEDED', 'PARTIAL_SUCCESS'} and row.get('artifact_verified') is True
        if success:
            counts[algorithm_id] = counts.get(algorithm_id, 0) + 1
    return counts
