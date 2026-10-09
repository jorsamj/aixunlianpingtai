#!/usr/bin/env python3
"""Read-only, bounded Material/Annotation audit for a failed V19 ZIP import.

Usage: python tools/audit_v19_partial_import.py --project-root /data/platform-data/projects/PROJECT_ID --job-id JOB_ID
Never modifies production files or either SQLite database.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path


def _select(db_path: Path, sql: str, ids: list[str]) -> dict[str, dict]:
    if not db_path.is_file():
        return {}
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    rows = {}
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        for offset in range(0, len(ids), 400):
            chunk = ids[offset:offset + 400]
            if not chunk:
                continue
            placeholders = ','.join('?' for _ in chunk)
            for row in conn.execute(sql.format(placeholders=placeholders), chunk):
                rows[str(row[0])] = dict(row)
    return rows


def audit(root: Path, job_id: str) -> dict:
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', job_id):
        raise ValueError('invalid job id')
    root = root.resolve()
    job_dir = root / 'import_jobs' / job_id
    job = json.loads((job_dir / 'job.json').read_text(encoding='utf-8'))
    report_path = job_dir / 'report.json'
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.is_file() else job.get('report') or {}
    original_ids = [str(v) for v in report.get('imported_image_ids') or [] if str(v)]
    ids = list(dict.fromkeys(original_ids))
    material_rows = _select(root / 'materials.sqlite3',
        'SELECT id, payload_json FROM materials WHERE id IN ({placeholders})', ids)
    gt_rows = _select(root / 'annotations.sqlite3',
        'SELECT image_id, annotation_state, version, content_digest, boxes_json FROM annotations WHERE image_id IN ({placeholders})', ids)

    issues = Counter()
    examples: dict[str, list[str]] = {}
    content_hashes = Counter()
    gt_states = Counter()
    for image_id in ids:
        material_record = material_rows.get(image_id)
        if material_record is None:
            issues['missing_material'] += 1
            examples.setdefault('missing_material', []).append(image_id)
            continue
        data = json.loads(material_record['payload_json'])
        digest = str(data.get('content_sha256') or '').strip().lower()
        if digest:
            content_hashes[digest] += 1
        if str(data.get('storage_type') or '').lower() in {'local', 'filesystem', 'file'}:
            object_key = str(data.get('object_key') or '')
            if object_key and not (root / object_key).is_file():
                issues['missing_local_source'] += 1
                examples.setdefault('missing_local_source', []).append(image_id)
        truth = gt_rows.get(image_id)
        if truth is None or int(truth.get('version') or 0) < 1:
            issues['missing_formal_annotation'] += 1
            examples.setdefault('missing_formal_annotation', []).append(image_id)
            continue
        gt_states[str(truth.get('annotation_state') or '')] += 1
        if int(data.get('annotation_version') or 0) != int(truth.get('version') or 0):
            issues['annotation_projection_version_mismatch'] += 1
            examples.setdefault('annotation_projection_version_mismatch', []).append(image_id)
        if str(data.get('annotation_hash') or '') != str(truth.get('content_digest') or ''):
            issues['annotation_projection_digest_mismatch'] += 1
            examples.setdefault('annotation_projection_digest_mismatch', []).append(image_id)
        if str(truth.get('annotation_state') or '') in {'annotated', 'confirmed_empty'}:
            linked_digest = str(data.get('annotation_source_content_sha256') or '').lower()
            if digest and linked_digest != digest:
                issues['annotation_source_identity_mismatch'] += 1
                examples.setdefault('annotation_source_identity_mismatch', []).append(image_id)
    return {
        'audit_only': True, 'job_id': job_id,
        'job_status': job.get('status'), 'job_error': job.get('error'),
        'report_imported_images': report.get('imported_images'),
        'report_annotated_images': report.get('annotated_images'),
        'report_boxes': report.get('boxes'),
        'report_image_id_count': len(original_ids),
        'unique_report_image_ids': len(ids),
        'duplicate_report_image_ids': len(original_ids)-len(ids),
        'indexed_material_rows': len(material_rows),
        'persisted_annotation_rows': len(gt_rows),
        'ground_truth_states': dict(gt_states),
        'duplicate_content_hash_groups': sum(n>1 for n in content_hashes.values()),
        'issues': dict(issues),
        'examples_first_12': {k:v[:12] for k,v in examples.items()},
        'note': 'Read-only audit; no repairs performed and no training approval granted.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--job-id', required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.project_root, args.job_id), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
